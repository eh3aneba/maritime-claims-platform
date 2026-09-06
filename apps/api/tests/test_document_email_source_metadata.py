import subprocess
import sys


def test_direct_document_import_registers_email_attachment_fk_target() -> None:
    code = (
        "from app.modules.documents.models import Document; "
        "assert 'email_attachment_manifests' in Document.metadata.tables"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
