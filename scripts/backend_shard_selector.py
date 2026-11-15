"""Fail-closed, stable exact-node assignment for Full Backend CI shards.

Execute from apps/api. Only successful pytest collection is admissible. Every
collected node gets exactly one SHA-256 based shard independent of list order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
COLLECTED = re.compile(r"^(\d+) tests? collected(?: / .*)? in .+$", re.MULTILINE)


def checkout_tree(commit: str, *, cwd: Path | None = None) -> str:
    """Verify the actual checkout, including PR merge refs, before trusting nodes."""
    if not SHA.fullmatch(commit):
        raise ValueError("invalid_backend_commit")

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            check=True, timeout=20,
        )
        return result.stdout.strip()

    actual = git("rev-parse", "--verify", "HEAD^{commit}")
    tree = git("rev-parse", "--verify", "HEAD^{tree}")
    if (actual != commit or not SHA.fullmatch(tree)
            or git("status", "--porcelain=v1", "--untracked-files=normal")):
        raise ValueError("backend_checkout_mismatch_or_dirty")
    return tree


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


def collect_nodes() -> list[str]:
    result = subprocess.run(
        ["pytest", "--collect-only", "-q", "tests"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise ValueError("backend_collection_failed")
    nodes = parse_collected_nodes(result.stdout)
    totals = COLLECTED.findall(result.stdout)
    if len(totals) != 1 or int(totals[0]) != len(nodes):
        raise ValueError("backend_collection_incomplete")
    return nodes


def manifest_bytes(nodes: list[str], *, commit: str, tree: str, shard_count: int) -> bytes:
    if not SHA.fullmatch(commit) or not SHA.fullmatch(tree):
        raise ValueError("invalid_backend_checkout_identity")
    # Reuse the collection parser: reject empty, duplicate, or malformed nodes.
    if parse_collected_nodes("\n".join(nodes)) != nodes:
        raise ValueError("invalid_backend_manifest_nodes")
    # The producer cannot succeed with a shard that will execute zero tests.
    for shard in range(shard_count):
        select_nodes(nodes, shard=shard, shard_count=shard_count)
    if shard_count < 1:
        raise ValueError("invalid_shard_count")
    return json.dumps(
        {"version": 1, "commit": commit, "tree": tree, "shards": shard_count,
         "node_count": len(nodes), "nodes": nodes},
        ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")


def read_manifest(path: Path, *, commit: str, tree: str,
                  digest: str, shard_count: int) -> list[str]:
    if not SHA.fullmatch(commit) or not SHA.fullmatch(tree) or not DIGEST.fullmatch(digest):
        raise ValueError("invalid_backend_manifest_identity")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("backend_manifest_digest_mismatch")
    doc = json.loads(data)
    if (not isinstance(doc, dict)
            or set(doc) != {"version", "commit", "tree", "shards", "node_count", "nodes"}
            or type(doc["version"]) is not int or doc["version"] != 1
            or type(doc["shards"]) is not int or doc["shards"] != shard_count
            or doc["commit"] != commit or doc["tree"] != tree
            or not isinstance(doc["nodes"], list)
            or type(doc["node_count"]) is not int or doc["node_count"] != len(doc["nodes"])
            or any(not isinstance(node, str) for node in doc["nodes"])):
        raise ValueError("invalid_backend_manifest")
    # Same strict validation at both ends; consumers never recollect or silently
    # fall back after a missing, stale, truncated, or substituted artifact.
    manifest_bytes(doc["nodes"], commit=commit, tree=tree, shard_count=shard_count)
    return doc["nodes"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select stable backend tests with NUL delimiters")
    parser.add_argument("--shard", type=int)
    parser.add_argument("--shards", type=int, default=64)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write-manifest", type=Path)
    mode.add_argument("--manifest", type=Path)
    parser.add_argument("--commit")
    parser.add_argument("--manifest-sha256")
    args = parser.parse_args(argv)
    if (args.shards < 1
            or (args.write_manifest is not None and args.shard is not None)
            or (args.write_manifest is None and (
                args.shard is None or args.shard < 0 or args.shard >= args.shards))
            or ((args.write_manifest is not None or args.manifest is not None)
                and (args.commit is None or not SHA.fullmatch(args.commit)))
            or (args.manifest is not None and args.manifest_sha256 is None)
            or (args.manifest is None and args.manifest_sha256 is not None)
            or (args.manifest is None and args.write_manifest is None and args.commit is not None)):
        print("backend_shard_selection_invalid", file=sys.stderr)
        return 1
    try:
        tree = None
        if args.manifest is not None or args.write_manifest is not None:
            tree = checkout_tree(args.commit)
        if args.manifest is not None:
            nodes = read_manifest(args.manifest, commit=args.commit, tree=tree,
                                  digest=args.manifest_sha256, shard_count=args.shards)
        else:
            nodes = collect_nodes()
        if args.write_manifest is not None:
            data = manifest_bytes(nodes, commit=args.commit, tree=tree, shard_count=args.shards)
            # Imports/collection may not mutate the tree whose identity we bind.
            if checkout_tree(args.commit) != tree:
                raise ValueError("backend_checkout_changed_during_collection")
            args.write_manifest.write_bytes(data)
            print("manifest_sha256=" + hashlib.sha256(data).hexdigest())
            return 0
        selected = select_nodes(nodes, shard=args.shard, shard_count=args.shards)
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError):
        print("backend_shard_selection_failed_closed", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(b"\x00".join(node.encode("utf-8") for node in selected) + b"\x00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
