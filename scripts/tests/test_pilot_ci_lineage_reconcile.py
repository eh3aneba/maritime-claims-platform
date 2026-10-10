"""Network-free regression tests for Pilot synthetic restored-DB lineage custody."""
from pathlib import Path
import hashlib
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_ci_lineage_reconcile as lineage  # noqa: E402


def readback(row=None):
    return json.dumps([row if row is not None else {
        "id": "00000000-0000-0000-0000-000000000001",
        "status": "approved", "payload": "synthetic-test-only",
    }])


class LineageReconcileTests(unittest.TestCase):
    def test_sql_table_allowlist_and_scoping(self):
        self.assertEqual(len(lineage.ALL_TABLES), 7)
        for table in lineage.CLAIM_TABLES:
            sql = lineage.sql_for(table)
            self.assertIn("t.claim_id", sql)
            self.assertIn("MCRI-DEMO-MT-ORION", sql)
            self.assertIn("jsonb_agg", sql)
            self.assertNotIn("DELETE", sql)
        self.assertIn("t.organization_id", lineage.sql_for("audit_logs"))
        for bad in ("audit_logs; DROP TABLE claims", "users", "secret", ""):
            with self.assertRaises(lineage.LineageError):
                lineage.sql_for(bad)

    def test_equal_rows_accepted_and_metadata_only_result(self):
        def query(db, sql):
            self.assertTrue(db.startswith("synthetic_"))
            return readback()
        a = lineage.collect_lineage("synthetic_source", query)
        b = lineage.collect_lineage("synthetic_clone", query)
        output = lineage.reconcile(a, b)
        self.assertEqual(output, {"lineage_families_compared": 7,
                                  "lineage_rows_compared": 7})
        self.assertNotIn("payload", json.dumps(output))
        self.assertTrue(all(len(digest) == 64 for _, digest in a.values()))

    def test_same_count_but_mutated_approval_is_rejected(self):
        def query(db, sql):
            if db == "synthetic_clone" and "initial_assessments" in sql:
                return readback({"id": "00000000-0000-0000-0000-000000000001",
                                 "status": "draft", "payload": "synthetic-test-only"})
            return readback()
        a = lineage.collect_lineage("synthetic_source", query)
        b = lineage.collect_lineage("synthetic_clone", query)
        with self.assertRaisesRegex(lineage.LineageError, "lineage differs"):
            lineage.reconcile(a, b)

    def test_empty_required_family_fails_closed(self):
        def query(db, sql):
            return "[]" if "documents" in sql else readback()
        with self.assertRaisesRegex(lineage.LineageError, "family empty"):
            lineage.collect_lineage("synthetic_source", query)

    def test_malformed_oversized_and_duplicate_ids_rejected(self):
        a = {"id": "a", "payload": "synthetic"}
        invalid = (
            '{"not":"a list"}',
            '[{"payload":"no id"}]',
            json.dumps([a, a]),
            "not-json",
            json.dumps([{"id": "a", "text": "x" * (4 * 1024 * 1024)}]),
        )
        for raw in invalid:
            with self.subTest(value=raw[:20]), self.assertRaises(lineage.LineageError):
                lineage.canonical_fingerprint(raw)

    def test_canonical_json_order_stable(self):
        a = '{"id":"synthetic","x":1,"y":2}'
        b = '{"y":2,"x":1,"id":"synthetic"}'
        self.assertEqual(
            lineage.canonical_fingerprint("[" + a + "]"),
            lineage.canonical_fingerprint("[" + b + "]"),
        )

    def test_incomplete_group_set_rejected(self):
        a = {t: (1, hashlib.sha256(t.encode()).hexdigest())
             for t in lineage.ALL_TABLES}
        b = dict(a)
        b.pop("audit_logs")
        with self.assertRaisesRegex(lineage.LineageError, "incomplete"):
            lineage.reconcile(a, b)


if __name__ == "__main__":
    unittest.main()
