"""Fetch the fixed LibTIFF source for the isolated OCR Docker builder.

No caller-provided URL, version, digest, alternate mirror or bypass. Transient
transport failures alone get a bounded retry; integrity mismatch is fatal.
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import time
from urllib.request import urlopen

URL = "https://download.osgeo.org/libtiff/tiff-4.7.2.tar.gz"
SHA512 = "bad66954a7e7e158c6dcbfc0e2d0032b8f3e2a354b6d0fdbb8038a7963e36c5b8a433dd4ee81c6c4dabfb50094152d440aa1f32b5299098c9ae29e55de2e41fc"
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 120


class DownloadUnavailable(RuntimeError):
    """The bounded source download retry budget is exhausted."""


class IntegrityMismatch(RuntimeError):
    """Untrusted downloaded source differs from the pinned digest."""


def fetch(output: Path = Path("/tmp/tiff.tar.gz"), *, open_url=None, sleep=None) -> None:
    """Write bytes atomically only after their SHA-512 digest matches the pin."""
    opener = urlopen if open_url is None else open_url
    delay = time.sleep if sleep is None else sleep
    destination = Path(output)
    temporary = destination.with_name(destination.name + ".unverified")
    # Do not allow a stale or incomplete archive to survive a failed build.
    temporary.unlink(missing_ok=True)
    destination.unlink(missing_ok=True)
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with opener(URL, timeout=TIMEOUT_SECONDS) as stream:
                    archive = stream.read()
            except OSError:
                # urllib.error.URLError, TimeoutError and socket errors are
                # transport failures. Never retry an integrity mismatch.
                if attempt == MAX_ATTEMPTS:
                    raise DownloadUnavailable("pinned_libtiff_download_unavailable") from None
                delay(attempt * 2)
                continue

            digest = hashlib.sha512(archive).hexdigest()
            if not hmac.compare_digest(digest, SHA512):
                raise IntegrityMismatch("pinned_libtiff_sha512_mismatch")

            # A failed write/rename is not a network failure and is not retried.
            temporary.write_bytes(archive)
            temporary.replace(destination)
            return
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        fetch()
    except (DownloadUnavailable, IntegrityMismatch) as exc:
        raise SystemExit(str(exc)) from None
