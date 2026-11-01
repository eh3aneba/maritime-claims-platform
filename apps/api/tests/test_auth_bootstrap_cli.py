"""Fresh-process coverage: pytest's application imports must not mask CLI failures."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


API_ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_without_application_import_registers_models_and_is_idempotent():
    script = r'''
        from contextlib import contextmanager
        import os
        import secrets

        from sqlalchemy import create_engine, event, select
        from sqlalchemy.orm import Session
        from app.db.base import Base
        from app.modules.auth import seed
        from app.core.security import verify_password

        engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def sqlite_functions(connection, _):
            connection.create_function("char_length", 1, lambda value: len(value) if value else 0)

        @contextmanager
        def session():
            # Deliberately defer schema creation until the CLI enters its DB
            # context. Only the CLI itself can register the complete model graph.
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                yield db

        seed.create_session = session
        password = secrets.token_urlsafe(24)
        os.environ.update(
            MCRI_BOOTSTRAP_ORG_NAME="Invented bootstrap organization",
            MCRI_BOOTSTRAP_ORG_SLUG="synthetic-bootstrap-a",
            MCRI_BOOTSTRAP_ADMIN_EMAIL="bootstrap@example.com",
            MCRI_BOOTSTRAP_ADMIN_PASSWORD=password,
        )
        seed.main()
        with Session(engine) as db:
            organizations = list(db.scalars(select(seed.Organization)))
            users = list(db.scalars(select(seed.User)))
            assert len(organizations) == len(users) == 1
            org, user = organizations[0], users[0]
            assert user.organization_id == org.id
            assert user.role == seed.UserRole.ADMIN and user.is_active
            assert verify_password(password, user.password_hash)
            original_id, original_hash = user.id, user.password_hash
            # A later bootstrap is not authority to reactivate or promote an
            # existing user, or to replace their password.
            user.is_active = False
            user.role = seed.UserRole.CLAIMS_HANDLER
            db.commit()
        os.environ["MCRI_BOOTSTRAP_ADMIN_PASSWORD"] = secrets.token_urlsafe(24)
        seed.main()
        with Session(engine) as db:
            users = list(db.scalars(select(seed.User)))
            assert len(users) == 1
            user = users[0]
            assert user.id == original_id and user.password_hash == original_hash
            assert user.role == seed.UserRole.CLAIMS_HANDLER and not user.is_active
        # The same email in a different organization must not reuse the first
        # organization's identity or grant it privileges.
        os.environ["MCRI_BOOTSTRAP_ORG_SLUG"] = "synthetic-bootstrap-b"
        seed.main()
        with Session(engine) as db:
            users = list(db.scalars(select(seed.User)))
            assert len(users) == 2
            assert len({user.organization_id for user in users}) == 2
            first = next(user for user in users if user.id == original_id)
            assert first.role == seed.UserRole.CLAIMS_HANDLER and not first.is_active
            second = next(user for user in users if user.id != original_id)
            assert second.role == seed.UserRole.ADMIN and second.is_active
        print("synthetic_bootstrap_fresh_process_passed")
    '''
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], cwd=API_ROOT,
        env={**os.environ, "APP_ENV": "test", "AI_PROVIDER": "disabled"},
        capture_output=True, text=True, timeout=45,
    )
    # Keep subprocess exception/SQL details out of routine CI logs.
    if result.returncode != 0:
        raise AssertionError("standalone_bootstrap_process_failed")
    assert "synthetic_bootstrap_fresh_process_passed" in result.stdout


def test_bootstrap_rejects_missing_configuration_before_database_access():
    script = '''
        import os
        from app.modules.auth import seed
        for name in tuple(os.environ):
            if name.startswith("MCRI_BOOTSTRAP_"):
                del os.environ[name]
        def forbidden():
            raise AssertionError("unexpected_database_access")
        seed.create_session = forbidden
        try:
            seed.main()
        except SystemExit as exc:
            assert str(exc) == "Bootstrap environment variables are incomplete"
        else:
            raise AssertionError("missing_configuration_accepted")
        os.environ.update(
            MCRI_BOOTSTRAP_ORG_NAME="Invented validation-only organization",
            MCRI_BOOTSTRAP_ORG_SLUG="synthetic-invalid-config",
            MCRI_BOOTSTRAP_ADMIN_EMAIL="bootstrap@example.com",
            MCRI_BOOTSTRAP_ADMIN_PASSWORD="x" * 8,
        )
        try:
            seed.main()
        except SystemExit as exc:
            assert str(exc) == "Bootstrap admin password must contain at least 12 characters"
        else:
            raise AssertionError("short_password_accepted")
    '''
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], cwd=API_ROOT,
        env={**os.environ, "APP_ENV": "test", "AI_PROVIDER": "disabled"},
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise AssertionError("bootstrap_configuration_guard_failed")
