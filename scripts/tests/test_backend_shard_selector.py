"""Offline safety and stability checks for Full Backend shard assignment."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import backend_shard_selector as selector


class BackendShardSelectorTests(unittest.TestCase):
    def test_order_and_unrelated_node_changes_never_reassign_existing_nodes(self):
        initial = [f"tests/test_claims.py::test_case_{i}[variant]" for i in range(800)]
        expanded = ["tests/test_unrelated.py::test_new", *reversed(initial)]
        for count in (17, 64):
            old = {node: selector.assigned_shard(node, shard_count=count) for node in initial}
            new = {node: selector.assigned_shard(node, shard_count=count) for node in expanded}
            self.assertTrue(all(old[node] == new[node] for node in initial))
            self.assertEqual(sum(
                len([node for node in expanded if new[node] == shard])
                for shard in range(count)
            ), len(expanded))
            self.assertEqual(len(set(old.values())), count)

    def test_collection_strips_only_reporter_lines_and_refuses_duplicates(self):
        source = "tests/test_a.py::test_one\ntests/test_b.py::test_two[x]\n2 tests collected in 0.1s\n"
        self.assertEqual(selector.parse_collected_nodes(source), [
            "tests/test_a.py::test_one", "tests/test_b.py::test_two[x]",
        ])
        with self.assertRaises(ValueError):
            selector.parse_collected_nodes("0 tests collected\n")
        with self.assertRaises(ValueError):
            selector.parse_collected_nodes("tests/test_a.py::test_one\ntests/test_a.py::test_one\n")
        with self.assertRaises(ValueError):
            selector.parse_collected_nodes("tests/test_a.py::test_one\x00\n")

    def test_empty_shard_and_bad_identifier_fail_closed(self):
        nodes = ["tests/test_a.py::test_one"]
        shard = selector.assigned_shard(nodes[0], shard_count=64)
        self.assertEqual(selector.select_nodes(nodes, shard=shard, shard_count=64), nodes)
        with self.assertRaises(ValueError):
            selector.select_nodes(nodes, shard=(shard + 1) % 64, shard_count=64)
        with self.assertRaises(ValueError):
            selector.select_nodes(nodes, shard=-1, shard_count=64)
        with self.assertRaises(ValueError):
            selector.assigned_shard("totally-not-a-node", shard_count=64)

    def test_failed_collection_refuses_to_emit_any_nodes(self):
        fake = subprocess.CompletedProcess(
            args=["pytest"], returncode=1, stdout="tests/test_a.py::test_one\n", stderr="PRIVATE fixture"
        )
        with patch.object(selector.subprocess, "run", return_value=fake):
            with redirect_stderr(StringIO()) as redacted:
                self.assertEqual(selector.main(["--shard", "0", "--shards", "1"]), 1)
        self.assertNotIn("PRIVATE", redacted.getvalue())

    def test_workflow_uses_selector_and_preserves_64_shard_gate(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/backend-premerge.yml").read_text(encoding="utf-8")
        self.assertIn('python ../../scripts/backend_shard_selector.py --shard', workflow)
        self.assertIn("mapfile -d '' -t shard_nodes", workflow)
        self.assertNotIn('index % 64', workflow)
        self.assertIn('[ "$SHARD_RESULT" = "success" ] ||', workflow)
        self.assertIn('name: Backend tests', workflow)
        self.assertIn('shard: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10', workflow)
        self.assertIn('python -m unittest scripts.tests.test_backend_shard_selector scripts.tests.test_ci_backend_narrow_scope -v', workflow)


if __name__ == "__main__":
    unittest.main()
