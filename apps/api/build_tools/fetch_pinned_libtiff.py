"""Fetch the fixed LibTIFF release from bounded, explicitly approved mirrors.

The OSGeo primary and cache are occasionally unreachable inside GitHub Actions
Docker builders. Two reputable MacPorts distfiles mirrors provide the published
upstream artifact as independent download paths. Every candidate MUST satisfy
the original SHA-512; a mismatch is an immediate hard failure and MUST NEVER
fall back to another source. Only network transport errors permit fallback.
No caller-provided production URL, alternate digest, version or bypass.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

# MacPorts distfiles mirrors, plus OSGeo-operated origin and cache.
# These are read-only, fixed URLs for the exact original release archive.
# SHA-512 below, rather than mirror trust alone, authorizes every byte.
URLS = (
    "https://fra.de.distfiles.macports.org/tiff/tiff-4.7.2.tar.gz",
    "https://mse.uk.distfiles.macports.org/tiff/tiff-4.7.2.tar.gz",
    "https://download-cache.osgeo.org/libtiff/tiff-4.7.2.tar.gz",
    "https://download.osgeo.org/libtiff/tiff-4.7.2.tar.gz",
)
SHA512 = "bad66954a7e7e158c6dcbfc0e2d0032b8f3e2a354b6d0fdbb8038a7963e36c5b8a433dd4ee81c6c4dabfb50094152d440aa1f32b5299098c9ae29e55de2e41fc"
MAX_ATTEMPTS_PER_SOURCE = 2
TIMEOUT_SECONDS = 25


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
                except OSError as exc:
                    # Fixed-host diagnostics only; do not echo external
                    # exception text, URLs with query strings or response
                    # bodies into CI. Never suppress digest or filesystem
                    # failures as transport issues.
                    reason = getattr(exc, "reason", None)
                    http_status = getattr(exc, "code", None)
                    print(
                        "libtiff_transport_failure"
                        f" source_host={urlsplit(url).hostname}"
                        f" error_class={type(exc).__name__}"
                        f" reason_class={type(reason).__name__}"
                        f" http_status={http_status if isinstance(http_status, int) else 'none'}"
                        f" attempt={attempt}/{MAX_ATTEMPTS_PER_SOURCE}",
                        file=sys.stderr,
                    )
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
