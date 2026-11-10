"""Fetch the fixed LibTIFF release from bounded official OSGeo endpoints.

No caller-provided production URL, version, digest, alternate mirror or bypass.
The OSGeo download cache and the primary OSGeo download host publish the same
release artifact. Each candidate MUST satisfy the existing fixed SHA-512;
a digest mismatch is an immediate hard failure, never a fallback condition.
Only transport errors can try the next official endpoint.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import time
from urllib.request import urlopen

# The cache is an OSGeo-operated distribution endpoint, not an Edge or
# third-party repackaged release. Prefer it while the primary is unavailable.
URLS = (
    "https://download-cache.osgeo.org/libtiff/tiff-4.7.2.tar.gz",
    "https://download.osgeo.org/libtiff/tiff-4.7.2.tar.gz",
)
SHA512 = "bad66954a7e7e158c6dcbfc0e2d0032b8f3e2a354b6d0fdbb8038a7963e36c5b8a433dd4ee81c6c4dabfb50094152d440aa1f32b5299098c9ae29e55de2e41fc"
MAX_ATTEMPTS_PER_SOURCE = 2
TIMEOUT_SECONDS = 45


class DownloadUnavailable(RuntimeError):
    """Both bounded official source download paths failed to deliver bytes."""


class IntegrityMismatch(RuntimeError):
    """Downloaded bytes differ from the approved, fixed SHA-512 artifact."""


def fetch(output: Path = Path("/tmp/tiff.tar.gz"), *, open_url=None, sleep=None) -> None:
    """Publish the verified release atomically; never publish partial content."""
    opener = urlopen if open_url is None else open_url
    delay = time.sleep if sleep is None else sleep
    destination = Path(output)
    temporary = destination.with_name(destination.name + ".unverified")
    temporary.unlink(missing_ok=True)
    destination.unlink(missing_ok=True)
    try:
        for url in URLS:
            for attempt in range(1, MAX_ATTEMPTS_PER_SOURCE + 1):
                try:
                    with opener(url, timeout=TIMEOUT_SECONDS) as stream:
                        archive = stream.read()
                except OSError:
                    # Only transient transport failures may be retried. An
                    # integrity or filesystem failure must never select a
                    # different mirror, version or package.
                    if attempt < MAX_ATTEMPTS_PER_SOURCE:
                        delay(attempt * 2)
                    continue

                digest = hashlib.sha512(archive).hexdigest()
                if not hmac.compare_digest(digest, SHA512):
                    raise IntegrityMismatch("pinned_libtiff_sha512_mismatch")

                temporary.write_bytes(archive)
                temporary.replace(destination)
                return
        raise DownloadUnavailable("pinned_libtiff_download_unavailable")
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        fetch()
    except (DownloadUnavailable, IntegrityMismatch) as exc:
        raise SystemExit(str(exc)) from None
