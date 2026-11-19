"""Local-only private OCR study JSON reader with a bounded FD safety boundary.

Study data may contain confidential original scans' transcribed phrases.
This helper does not authenticate source accuracy or grant Pilot acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any, Callable

MAX_STUDY_BYTES = 30_000_000


def _reject_constant(_value: str) -> None:
    raise ValueError("invalid_private_ocr_json")


def read_private_study_json(
    path: Path,
    *,
    object_pairs_hook: Callable[[list[tuple[str, Any]]], dict[str, Any]],
    max_bytes: int = MAX_STUDY_BYTES,
) -> Any:
    """Read one bounded, private regular FD and reject observable write races.

    On POSIX, O_NOFOLLOW prevents a direct symlink substitution and 0600-like
    owner-only permissions are mandatory. On Windows, ACL custody is external
    and must be independently verified by the operator.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_STUDY_BYTES:
        raise ValueError("invalid_private_ocr_size_limit")
    if path.is_symlink():
        raise ValueError("unsafe_private_ocr_input")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("unsafe_private_ocr_input")
        if os.name == "posix" and stat.S_IMODE(before.st_mode) & 0o077:
            raise ValueError("private_ocr_input_permissions_required")
        if before.st_size > max_bytes:
            raise ValueError("private_ocr_input_oversized")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
        if len(payload) > max_bytes or len(payload) != before.st_size:
            raise ValueError("private_ocr_input_size_mismatch")
        if (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
            before.st_mode,
        ) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
            after.st_mode,
        ):
            raise ValueError("private_ocr_input_changed_during_read")
    finally:
        if descriptor != -1:
            os.close(descriptor)
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=object_pairs_hook,
        parse_constant=_reject_constant,
    )
