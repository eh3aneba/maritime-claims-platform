"""Fail-closed exact-path, DB-free classifier for synthetic H&M AI tests.

The PostgreSQL CI classifier only skips concurrency jobs for the two
explicitly audited, offline synthetic AI test modules when this check
passes. Any unexpected import or database / dynamic execution construct
forces the full PostgreSQL concurrency matrix. This is not a security
sandbox and may not replace human review or the normal test workflows.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_ALLOWED_IMPORTS = {
    "apps/api/tests/test_local_ai_hm_loopback_smoke.py": frozenset({
        "json", "pathlib", "sys", "pytest",
        "app.ai.gateway.base",
        "scripts.pilot_local_ai_hm_fixture_matrix",
        "scripts.pilot_local_ai_hm_loopback_smoke",
    }),
    "apps/api/tests/test_local_ai_hm_fixture_matrix.py": frozenset({
        "copy", "pathlib", "sys", "pytest",
        "scripts.pilot_local_ai_source_gate",
        "scripts.pilot_local_ai_hm_fixture_matrix",
    }),
    "apps/api/tests/test_local_ai_hm_repeat_smoke.py": frozenset({
        "json", "pathlib", "sys", "pytest",
        "app.ai.gateway.base",
        "scripts.pilot_local_ai_hm_fixture_matrix",
        "scripts.pilot_local_ai_hm_repeat_smoke",
    }),
}
_FORBIDDEN_NAMES = frozenset({
    "DATABASE_URL", "TestingSessionLocal", "SessionLocal",
    "create_engine", "sessionmaker", "sqlalchemy",
    "psycopg", "asyncpg", "sqlite3", "subprocess",
    "importlib", "__import__", "exec", "eval",
    "compile", "open", "getattr", "setattr",
})
_FORBIDDEN_ATTRIBUTES = frozenset({
    "execute", "exec", "exec_driver_sql", "commit",
    "rollback", "connect", "begin", "cursor", "raw_connection",
    "read_text", "write_text", "read_bytes", "write_bytes",
    "run", "Popen", "system", "import_module",
})


def is_db_free_synthetic_test(repo_relative_path: object) -> bool:
    """Strictly whitelist an offline fixture module; unknown means DB required."""
    if type(repo_relative_path) is not str:
        return False
    permitted = _ALLOWED_IMPORTS.get(repo_relative_path)
    if permitted is None:
        return False
    candidate = (_ROOT / repo_relative_path).resolve()
    if not candidate.is_relative_to(_ROOT) or not candidate.is_file():
        return False
    try:
        tree = ast.parse(candidate.read_text(encoding="utf-8"), filename=repo_relative_path)
    except (OSError, UnicodeError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name not in permitted for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in permitted:
                return False
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            return False
        elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRIBUTES:
            return False
        elif isinstance(node, ast.Call):
            # Disallow source rewriting, arbitrary eval, or DB-like adapters.
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_NAMES:
                return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("postgres_synthetic_test_scope_not_verified")
        return 1
    if is_db_free_synthetic_test(args[0]):
        print("postgres_synthetic_test_scope_verified")
        return 0
    print("postgres_synthetic_test_scope_not_verified")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
