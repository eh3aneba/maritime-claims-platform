"""Offline safety and stability checks for Full Backend shard assignment."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import BytesIO, StringIO
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
from types import SimpleNamespace
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


class BackendCollectionManifestTests(unittest.TestCase):
    commit = "a" * 40
    tree = "c" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "nodes.json"
        self.nodes = [f"tests/test_claims.py::test_case_{i}[variant]" for i in range(800)]
        identity = patch.object(selector, "checkout_tree", return_value=self.tree)
        identity.start()
        self.addCleanup(identity.stop)

    def write(self, data):
        self.path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def read(self, digest, **kwargs):
        return selector.read_manifest(self.path, commit=kwargs.get("commit", self.commit),
                                      tree=kwargs.get("tree", self.tree),
                                      digest=digest, shard_count=kwargs.get("shard_count", 64))

    def test_roundtrip_preserves_every_existing_assignment_exactly_once(self):
        digest = self.write(selector.manifest_bytes(self.nodes, commit=self.commit, tree=self.tree, shard_count=64))
        restored = self.read(digest)
        assigned = []
        for shard in range(64):
            before = selector.select_nodes(self.nodes, shard=shard, shard_count=64)
            after = selector.select_nodes(restored, shard=shard, shard_count=64)
            self.assertEqual(before, after)
            assigned.extend(after)
        self.assertCountEqual(assigned, self.nodes)
        self.assertEqual(len(set(assigned)), len(self.nodes))

    def test_stale_commit_wrong_shard_count_or_digest_is_rejected(self):
        digest = self.write(selector.manifest_bytes(self.nodes, commit=self.commit, tree=self.tree, shard_count=64))
        for kwargs in ({"commit": "b" * 40}, {"tree": "b" * 40}, {"shard_count": 63}, {}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.read("0" * 64 if not kwargs else digest, **kwargs)
        self.path.write_bytes(self.path.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            self.read(digest)

    def test_invalid_documents_fail_even_with_matching_checksum(self):
        valid = {"version": 1, "commit": self.commit, "tree": self.tree,
                 "shards": 64, "node_count": len(self.nodes), "nodes": self.nodes}
        examples = [b"not json", b"[]"]
        for key, value in (("version", True), ("shards", True), ("node_count", True),
                           ("nodes", self.nodes[:-1]), ("nodes", []),
                           ("nodes", [123]), ("nodes", self.nodes + self.nodes[:1]),
                           ("nodes", ["tests/test_a.py::test_x\x00"]),
                           ("nodes", ["tests/test_a.py::test_x\ntests/test_b.py::test_y"]),
                           ("nodes", ["not-a-test"]),
                           ("nodes", ["tests/test_a.py::test_x"])):
            examples.append(json.dumps({**valid, key: value}).encode())
        examples.append(json.dumps({**valid, "unexpected": True}).encode())
        for data in examples:
            with self.subTest(data=data[:80]):
                digest = self.write(data)
                with self.assertRaises(ValueError):
                    self.read(digest)

    def test_consumer_uses_no_pytest_collection_and_emits_original_nul_nodes(self):
        digest = self.write(selector.manifest_bytes(self.nodes, commit=self.commit, tree=self.tree, shard_count=64))
        output = BytesIO()
        with patch.object(selector.subprocess, "run", side_effect=AssertionError("recollection")):
            with patch.object(selector.sys, "stdout", SimpleNamespace(buffer=output)):
                code = selector.main(["--shard", "7", "--manifest", str(self.path),
                                      "--commit", self.commit, "--manifest-sha256", digest])
        self.assertEqual(code, 0)
        expected = selector.select_nodes(self.nodes, shard=7, shard_count=64)
        self.assertEqual(output.getvalue(), b"\0".join(n.encode() for n in expected) + b"\0")

    def test_producer_collects_once_and_binds_output_checksum(self):
        result = subprocess.CompletedProcess(
            [], 0, "\n".join(self.nodes) + f"\n{len(self.nodes)} tests collected in 0.1s\n", ""
        )
        with patch.object(selector.subprocess, "run", return_value=result) as collect:
            with patch.object(selector.sys, "stdout", StringIO()) as output:
                code = selector.main(["--write-manifest", str(self.path), "--commit", self.commit])
        self.assertEqual(code, 0)
        collect.assert_called_once()
        self.assertEqual(output.getvalue(),
                         "manifest_sha256=" + hashlib.sha256(self.path.read_bytes()).hexdigest() + "\n")

    def test_failed_partial_collection_never_publishes_a_manifest(self):
        for result in (subprocess.CompletedProcess([], 1, "\n".join(self.nodes), "PRIVATE"),
                       subprocess.CompletedProcess([], 0, "0 tests collected", ""),
                       subprocess.CompletedProcess([], 0,
                           "\n".join(self.nodes[:-1]) + "\n800 tests collected in 0.1s\n", ""),
                       subprocess.CompletedProcess([], 0, "\n".join(self.nodes), "")):
            with patch.object(selector.subprocess, "run", return_value=result):
                with patch.object(selector.sys, "stdout", StringIO()) as output:
                    with redirect_stderr(StringIO()) as errors:
                        code = selector.main(["--write-manifest", str(self.path), "--commit", self.commit])
            self.assertEqual(code, 1)
            self.assertFalse(self.path.exists())
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn("PRIVATE", errors.getvalue())

    def test_artifact_corruption_and_missing_nodes_exit_nonzero_without_output(self):
        original = selector.manifest_bytes(self.nodes, commit=self.commit,
                                           tree=self.tree, shard_count=64)
        digest = hashlib.sha256(original).hexdigest()
        missing = json.loads(original)
        missing["nodes"].pop()
        cases = [
            (original[:-1], digest),
            (b"malformed json", hashlib.sha256(b"malformed json").hexdigest()),
            (json.dumps(missing).encode(), None),
            (original, "0" * 64),
        ]
        for data, expected in cases:
            expected = expected or hashlib.sha256(data).hexdigest()
            self.path.write_bytes(data)
            with self.subTest(data=data[:30]):
                with patch.object(selector.sys, "stdout", StringIO()) as output:
                    with redirect_stderr(StringIO()):
                        self.assertEqual(selector.main([
                            "--shard", "0", "--manifest", str(self.path),
                            "--commit", self.commit, "--manifest-sha256", expected,
                        ]), 1)
                self.assertEqual(output.getvalue(), "")

    def test_producer_timeout_or_checkout_change_cannot_publish_outputs(self):
        result = subprocess.CompletedProcess(
            [], 0, "\n".join(self.nodes) + "\n800 tests collected in 0.1s\n", ""
        )
        for problem in ("timeout", "changed tree"):
            with self.subTest(problem=problem):
                with patch.object(selector.subprocess, "run", return_value=result) as collect:
                    with patch.object(selector, "checkout_tree", side_effect=[self.tree, "d" * 40]):
                        if problem == "timeout":
                            collect.side_effect = subprocess.TimeoutExpired("pytest", 20)
                        with patch.object(selector.sys, "stdout", StringIO()) as output:
                            with redirect_stderr(StringIO()):
                                self.assertEqual(selector.main([
                                    "--write-manifest", str(self.path), "--commit", self.commit,
                                ]), 1)
                self.assertFalse(self.path.exists())
                self.assertEqual(output.getvalue(), "")

    def test_missing_manifest_and_incomplete_identity_fail_without_fallback(self):
        examples = [
            ["--shard", "0", "--manifest", str(self.path)],
            ["--shard", "0", "--manifest", str(self.path), "--commit", self.commit,
             "--manifest-sha256", "0" * 64],
            ["--write-manifest", str(self.path), "--commit", "bad"],
            ["--shard", "0", "--write-manifest", str(self.path), "--commit", self.commit],
            ["--shards", "0", "--write-manifest", str(self.path), "--commit", self.commit],
        ]
        for args in examples:
            with self.subTest(args=args):
                with patch.object(selector.subprocess, "run", side_effect=AssertionError("fallback")):
                    with patch.object(selector.sys, "stdout", StringIO()) as output:
                        with redirect_stderr(StringIO()):
                            self.assertEqual(selector.main(args), 1)
                self.assertEqual(output.getvalue(), "")


class BackendCheckoutIdentityTests(unittest.TestCase):
    def test_pr_head_and_merge_checkout_are_distinct_and_dirty_trees_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root,
                                               stderr=subprocess.DEVNULL, text=True).strip()

            git("init", "-q", "--initial-branch=main")
            git("config", "user.name", "Synthetic CI test")
            git("config", "user.email", "ci-test@example.invalid")
            (root / "base.txt").write_text("synthetic base\n")
            git("add", ".")
            git("commit", "-qm", "base")
            git("switch", "-qc", "feature")
            (root / "feature.txt").write_text("synthetic head\n")
            git("add", ".")
            git("commit", "-qm", "head")
            head = git("rev-parse", "HEAD")
            head_tree = git("rev-parse", "HEAD^{tree}")
            git("switch", "-q", "main")
            (root / "main.txt").write_text("synthetic updated main\n")
            git("add", ".")
            git("commit", "-qm", "updated base")
            git("merge", "-q", "--no-ff", "feature", "-m", "synthetic PR merge ref")
            merge = git("rev-parse", "HEAD")
            merge_tree = git("rev-parse", "HEAD^{tree}")
            self.assertNotEqual(head, merge)
            self.assertNotEqual(head_tree, merge_tree)
            self.assertEqual(selector.checkout_tree(merge, cwd=root), merge_tree)
            with self.assertRaises(ValueError):
                selector.checkout_tree(head, cwd=root)
            for state in ("tracked modification", "untracked source", "staged change"):
                with self.subTest(state=state):
                    path = root / ("new.py" if state == "untracked source" else "base.txt")
                    path.write_text("synthetic changed checkout\n")
                    if state == "staged change":
                        git("add", str(path))
                    with self.assertRaises(ValueError):
                        selector.checkout_tree(merge, cwd=root)
                    git("reset", "--hard", "-q", merge)
                    if state == "untracked source":
                        path.unlink()

    def test_unavailable_git_identity_exits_nonzero_without_collecting(self):
        with patch.object(selector, "checkout_tree", side_effect=subprocess.CalledProcessError(1, "git")):
            with patch.object(selector, "collect_nodes", side_effect=AssertionError("collection")):
                with patch.object(selector.sys, "stdout", StringIO()) as output:
                    with redirect_stderr(StringIO()):
                        self.assertEqual(selector.main([
                            "--write-manifest", "/unused", "--commit", "a" * 40,
                        ]), 1)
        self.assertEqual(output.getvalue(), "")


class BackendManifestWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2]
        self.workflow = (self.root / ".github/workflows/backend-premerge.yml").read_text()

    def test_all_11_required_check_names_remain_unique(self):
        from scripts.pilot_ruleset_evidence import EXPECTED_CONTEXTS
        names = []
        for path in (self.root / ".github/workflows").glob("*.yml"):
            names.extend(re.findall(r"^    name: (.+)$", path.read_text(), re.MULTILINE))
        self.assertEqual(len(EXPECTED_CONTEXTS), 11)
        for name in EXPECTED_CONTEXTS:
            with self.subTest(name=name):
                self.assertEqual(names.count(name), 1)

    def test_current_run_artifact_and_producer_consumer_environments_match(self):
        producer = self.workflow.split("  backend-collection:\n")[1].split("  backend-shard:\n")[0]
        consumer = self.workflow.split("  backend-shard:\n")[1].split("  backend-narrow:\n")[0]
        self.assertEqual(producer.split("    env:\n")[1].split("    steps:")[0],
                         consumer.split("    env:\n")[1].split("    steps:")[0])
        for marker in ("needs: [classify, backend-collection]", "--commit \"$GITHUB_SHA\"",
                       "needs.backend-collection.outputs.manifest_sha256",
                       "needs.backend-collection.outputs.artifact_name",
                       "if-no-files-found: error", "retention-days: 1"):
            self.assertIn(marker, self.workflow)
        download = consumer.split("uses: actions/download-artifact@v4", 1)[1].split("      - name:", 1)[0]
        self.assertNotIn("run-id:", download)
        self.assertNotIn("github-token:", download)
        self.assertNotIn("continue-on-error", self.workflow)
        for job in (producer, consumer):
            checkout = job.split("uses: actions/checkout@v6", 1)[1].split("      - name:", 1)[0]
            self.assertIn("ref: ${{ github.sha }}", checkout)
            self.assertNotIn("pull_request.head.sha", checkout)
        # The real shard pytest invocation and the full production-change
        # classifier are unchanged; the manifest cannot stand in for tests.
        self.assertIn('pytest -vv --durations=20 --durations-min=1.0 "${shard_nodes[@]}"', consumer)
        self.assertEqual([int(x) for x in re.search(r"shard: \[([^]]+)\]", consumer).group(1).split(",")], list(range(64)))

    def assert_dependency_contract(self, workflow):
        jobs = dict(re.findall(r"^  ([a-z-]+):\n(.*?)(?=^  [a-z-]+:\n|\Z)",
                               workflow.split("jobs:\n", 1)[1], re.MULTILINE | re.DOTALL))

        def needs(job):
            inline = re.search(r"^    needs: (.+)$", jobs[job], re.MULTILINE)
            if inline:
                return set(inline[1].strip("[]").replace(" ", "").split(","))
            block = re.search(r"^    needs:\n((?:      - [a-z-]+\n)+)", jobs[job], re.MULTILINE)
            self.assertIsNotNone(block)
            return set(re.findall(r"- ([a-z-]+)", block[1]))

        self.assertEqual(needs("backend-collection"), {"classify"})
        self.assertEqual(needs("backend-shard"), {"classify", "backend-collection"})
        self.assertEqual(needs("backend"),
                         {"classify", "backend-collection", "backend-shard", "backend-narrow"})

    def test_invalid_job_dependencies_are_detected(self):
        self.assert_dependency_contract(self.workflow)
        invalid = (
            self.workflow.replace("needs: [classify, backend-collection]", "needs: classify"),
            self.workflow.replace("    needs: classify\n", "    needs: backend-shard\n"),
            self.workflow.replace("      - backend-collection\n", ""),
        )
        for workflow in invalid:
            with self.subTest(workflow=workflow[-80:]), self.assertRaises(AssertionError):
                self.assert_dependency_contract(workflow)

    def test_actual_aggregate_shell_requires_both_collection_and_executed_shards(self):
        gate = self.workflow.split("  backend:\n", 1)[1]
        shell = textwrap.dedent(gate.split("        run: |\n", 1)[1])
        base = {**os.environ, "CLASSIFIER_RESULT": "success", "FULL_REQUIRED": "true",
                "NARROW_REQUIRED": "false", "SHARD_RESULT": "success",
                "COLLECTION_RESULT": "success", "NARROW_RESULT": "skipped"}
        for key in ("CLASSIFIER_RESULT", "SHARD_RESULT", "COLLECTION_RESULT"):
            for status in ("failure", "cancelled", "skipped", ""):
                result = subprocess.run(["bash", "-c", shell], env={**base, key: status},
                                        capture_output=True)
                self.assertNotEqual(result.returncode, 0, (key, status))
        self.assertEqual(subprocess.run(["bash", "-c", shell], env=base,
                                        capture_output=True).returncode, 0)
        for status, expected in (("success", 0), ("skipped", 1), ("failure", 1)):
            result = subprocess.run(["bash", "-c", shell], capture_output=True,
                                    env={**base, "FULL_REQUIRED": "false", "NARROW_REQUIRED": "true",
                                         "COLLECTION_RESULT": "skipped", "SHARD_RESULT": "skipped",
                                         "NARROW_RESULT": status})
            self.assertEqual(result.returncode, expected)


if __name__ == "__main__":
    unittest.main()
