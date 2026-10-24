"""Offline regressions for source-pinned LibTIFF download resilience."""
from __future__ import annotations

import hashlib

import pytest

from build_tools import fetch_pinned_libtiff as pinned

DATA = b"fictional-libtiff-test-bytes-only"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


def test_upstream_version_digest_timeout_and_retry_budget_remain_pinned():
    assert pinned.URL == "https://download.osgeo.org/libtiff/tiff-4.7.2.tar.gz"
    assert pinned.SHA512 == (
        "bad66954a7e7e158c6dcbfc0e2d0032b8f3e2a354b6d0fdbb8038a7963e36c5b8a433dd4ee81c6c4dabfb50094152d440aa1f32b5299098c9ae29e55de2e41fc"
    )
    assert pinned.TIMEOUT_SECONDS == 120
    assert pinned.MAX_ATTEMPTS == 3


def test_socket_timeout_then_success_verifies_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(pinned, "SHA512", hashlib.sha512(DATA).hexdigest())
    filename = tmp_path / "tiff.tar.gz"
    filename.write_bytes(b"stale archive")
    calls = []
    waits = []

    def opener(url, timeout):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise TimeoutError("transient socket timeout")
        return Response(DATA)

    pinned.fetch(filename, open_url=opener, sleep=waits.append)
    assert filename.read_bytes() == DATA
    assert calls == [(pinned.URL, 120), (pinned.URL, 120)]
    assert waits == [2]
    assert not (tmp_path / "tiff.tar.gz.unverified").exists()


def test_network_read_timeout_retries_then_success(tmp_path, monkeypatch):
    monkeypatch.setattr(pinned, "SHA512", hashlib.sha512(DATA).hexdigest())
    calls = []
    def opener(_url, timeout):
        calls.append(timeout)
        return Response(TimeoutError("read timed out") if len(calls) == 1 else DATA)

    path = tmp_path / "tiff.tar.gz"
    pinned.fetch(path, open_url=opener, sleep=lambda _: None)
    assert calls == [120, 120]
    assert path.read_bytes() == DATA


def test_retry_exhaustion_fails_and_leaves_no_partial_archive(tmp_path):
    filename = tmp_path / "tiff.tar.gz"
    filename.write_bytes(b"old unverified file")
    calls = []
    waits = []
    def offline(_url, timeout):
        calls.append(timeout)
        raise TimeoutError("transport unavailable")

    with pytest.raises(pinned.DownloadUnavailable, match="^pinned_libtiff_download_unavailable$"):
        pinned.fetch(filename, open_url=offline, sleep=waits.append)
    assert calls == [120, 120, 120]
    assert waits == [2, 4]
    assert not filename.exists()
    assert not (tmp_path / "tiff.tar.gz.unverified").exists()


def test_wrong_hash_fails_immediately_without_retry_or_written_data(tmp_path):
    filename = tmp_path / "tiff.tar.gz"
    filename.write_bytes(b"stale")
    count = 0
    def wrong(_url, timeout):
        nonlocal count
        count += 1
        return Response(DATA)

    with pytest.raises(pinned.IntegrityMismatch, match="^pinned_libtiff_sha512_mismatch$"):
        pinned.fetch(filename, open_url=wrong, sleep=lambda _: pytest.fail("must not retry digest mismatch"))
    assert count == 1
    assert not filename.exists()
    assert not (tmp_path / "tiff.tar.gz.unverified").exists()


def test_unexpected_response_bug_is_not_masked_by_network_retry(tmp_path):
    count = 0
    def buggy(_url, timeout):
        nonlocal count
        count += 1
        raise ValueError("invalid response state")
    with pytest.raises(ValueError, match="invalid response state"):
        pinned.fetch(tmp_path / "tiff.tar.gz", open_url=buggy, sleep=lambda _: pytest.fail("must not retry"))
    assert count == 1
