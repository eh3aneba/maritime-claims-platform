"""Build-only compatibility probe; never grants scanner or human approval."""
import json
import shutil
import sqlite3

EXPECTED_VERSION = "3.54.1"


def verify() -> dict:
    if sqlite3.sqlite_version != EXPECTED_VERSION:
        raise RuntimeError("sqlite_runtime_version_mismatch")
    # This is a containment precondition, not a scanner exception or an
    # exhaustive filesystem/reachability proof. Recheck in the final layer.
    if shutil.which("sqlite3") is not None:
        raise RuntimeError("sqlite_runtime_unexpected_sqlite_cli")
    with sqlite3.connect(":memory:") as db:
        options = {row[0] for row in db.execute("PRAGMA compile_options")}
        if not {"ENABLE_FTS5", "ENABLE_SESSION"}.issubset(options):
            raise RuntimeError("sqlite_runtime_feature_regression")
        db.execute("CREATE TABLE synthetic (value TEXT NOT NULL)")
        value = "Synthetic turbocharger evidence — دادهٔ ساختگی"
        db.execute("INSERT INTO synthetic VALUES (?)", (value,))
        if db.execute("SELECT value FROM synthetic").fetchone() != (value,):
            raise RuntimeError("sqlite_runtime_unicode_roundtrip_failed")
        db.execute("CREATE VIRTUAL TABLE synthetic_search USING fts5(content)")
        db.execute("INSERT INTO synthetic_search VALUES (?)", ("synthetic machinery evidence",))
        if db.execute("SELECT count(*) FROM synthetic_search WHERE synthetic_search MATCH 'machinery'").fetchone() != (1,):
            raise RuntimeError("sqlite_runtime_fts5_probe_failed")
    return {"sqlite_version": sqlite3.sqlite_version, "fts5": True,
            "session_extension": True, "synthetic_unicode_roundtrip": True,
            "sqlite_cli_present": shutil.which("sqlite3") is not None,
            "scope": "compatibility only; vulnerability admission is evaluated separately"}


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, sort_keys=True))
