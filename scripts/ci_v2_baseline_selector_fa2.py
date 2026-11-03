"""Fail-closed, stable exact-node assignment for Full Backend CI shards.

Execute from apps/api. Only successful pytest collection is admissible. Every
collected node gets exactly one SHA-256 based shard independent of list order.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys


def assigned_shard(node: str, *, shard_count: int) -> int:
    if not isinstance(node, str) or not node.startswith("tests/") or "::" not in node:
        raise ValueError("invalid_backend_test_node")
    if shard_count < 1:
        raise ValueError("invalid_shard_count")
    return int.from_bytes(hashlib.sha256(node.encode("utf-8")).digest()[:8], "big") % shard_count


def parse_collected_nodes(output: str) -> list[str]:
    """Accept only pytest's fully qualified node IDs, not summaries/warnings."""
    nodes = [line for line in output.splitlines() if line.startswith("tests/") and "::" in line]
    if not nodes or any("\x00" in node or "\r" in node for node in nodes):
        raise ValueError("backend_test_collection_empty_or_invalid")
    if len(nodes) != len(set(nodes)):
        raise ValueError("backend_test_collection_duplicate_node")
    return nodes


def select_nodes(nodes: list[str], *, shard: int, shard_count: int) -> list[str]:
    if shard_count < 1 or shard < 0 or shard >= shard_count:
        raise ValueError("invalid_backend_shard")
    selected = [node for node in nodes if assigned_shard(node, shard_count=shard_count) == shard]
    if not selected:
        raise ValueError("empty_backend_shard")
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select stable backend tests with NUL delimiters")
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=64)
    args = parser.parse_args(argv)
    if args.shards < 1 or args.shard < 0 or args.shard >= args.shards:
        print("backend_shard_selection_invalid", file=sys.stderr)
        return 1
    try:
        result = subprocess.run(
            ["pytest", "--collect-only", "-q", "tests"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("backend_collection_failed")
        nodes = parse_collected_nodes(result.stdout)
        selected = select_nodes(nodes, shard=args.shard, shard_count=args.shards)
    except (ValueError, OSError, UnicodeError):
        print("backend_shard_selection_failed_closed", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(b"\x00".join(node.encode("utf-8") for node in selected) + b"\x00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
