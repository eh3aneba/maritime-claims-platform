from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.modules.intake import maturity as intake_maturity
from app.modules.intake.models import ClaimIntakeDraft, ClaimIntakeProcessingJob, ClaimIntakeStatus
from app.modules.processing import extractors
from app.modules.processing.extractors import TextExtractionResult, TextSegmentResult
from app.modules.processing.models import ProcessingJobStatus
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_claim_intake import login, seed
from tests.test_claim_intake_maturity import _upload_processing_draft


def setup_function() -> None:
    reset_database()


def _native_mixed_pdf() -> TextExtractionResult:
    return TextExtractionResult(
        method="pypdf",
        segments=[
            TextSegmentResult(
                locator_type="page",
                locator_value="1",
                text="Chief Engineer Report — native text remains authoritative and readable.",
            ),
            TextSegmentResult(locator_type="page", locator_value="2", text=""),
        ],
        requires_ocr=True,
        warnings=["PDF contains 1 low-text page(s) that may require OCR."],
    )


def _enable_fake_ocr(monkeypatch, *, text: str = "اعلام خسارت Claim Notification") -> None:
    monkeypatch.setattr(extractors, "_tesseract_available", lambda: True)
    monkeypatch.setattr(extractors.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        extractors.subprocess,
        "run",
        lambda *args, **kwargs: type("Completed", (), {"stdout": ""})(),
    )
    monkeypatch.setattr(extractors, "_ocr_one_image", lambda *args, **kwargs: text)


def test_selective_mixed_pdf_ocr_preserves_native_text_and_recovers_low_text_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_fake_ocr(monkeypatch)
    native = _native_mixed_pdf()

    result = extractors._extract_pdf_ocr(
        tmp_path / "mixed.pdf",
        native_result=native,
        languages="eng+fas",
        max_pages=20,
        timeout_seconds=5,
    )

    assert result.method == "pypdf+selective-tesseract:eng+fas"
    assert result.requires_ocr is False
    assert result.segments[0].text == native.segments[0].text
    assert "اعلام خسارت" in result.segments[1].text
    assert result.segments[1].locator_value == "2"
    assert result.text_hash is not None
    assert result.text_hash == extractors.TextExtractionResult(
        method=result.method,
        segments=list(result.segments),
    ).text_hash
    assert any("recovered 1" in warning for warning in result.warnings)


def test_selective_pdf_ocr_page_cap_is_explicit_and_partial_text_is_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_fake_ocr(monkeypatch, text="Recovered page two text from OCR")
    native = TextExtractionResult(
        method="pypdf",
        segments=[
            TextSegmentResult("page", "1", "Native first page has enough useful claim text."),
            TextSegmentResult("page", "2", ""),
            TextSegmentResult("page", "3", ""),
        ],
        requires_ocr=True,
    )

    result = extractors._extract_pdf_ocr(
        tmp_path / "capped.pdf",
        native_result=native,
        languages="eng+fas",
        max_pages=2,
        timeout_seconds=5,
    )

    assert result.segments[0].text == native.segments[0].text
    assert result.segments[1].text == "Recovered page two text from OCR"
    assert result.segments[2].text == ""
    assert result.requires_ocr is True
    assert any("page cap 2" in warning.lower() for warning in result.warnings)
    assert any("3" in warning for warning in result.warnings if "page cap" in warning.lower())


def test_selective_pdf_ocr_timeout_keeps_native_evidence_and_reports_partial_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    native = _native_mixed_pdf()
    monkeypatch.setattr(extractors, "_tesseract_available", lambda: True)
    monkeypatch.setattr(extractors.shutil, "which", lambda name: f"/usr/bin/{name}")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="pdftoppm", timeout=1)

    monkeypatch.setattr(extractors.subprocess, "run", timeout)

    result = extractors._extract_pdf_ocr(
        tmp_path / "timeout.pdf",
        native_result=native,
        languages="eng+fas",
        max_pages=20,
        timeout_seconds=1,
    )

    assert result.segments[0].text == native.segments[0].text
    assert result.segments[1].text == ""
    assert result.requires_ocr is True
    assert any("timed out" in warning.lower() for warning in result.warnings)
    assert any("partial extraction was preserved" in warning.lower() for warning in result.warnings)


def test_stale_intake_worker_lease_requeues_without_resetting_attempt_budget(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed()
    login("alpha", "alpha@example.com")
    draft_id = _upload_processing_draft(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    monkeypatch.setattr(intake_maturity.settings, "processing_stale_after_seconds", 60)

    with TestingSessionLocal() as db:
        from app.modules.intake.service import claim_next_intake_job

        claimed = claim_next_intake_job(db, worker_id="worker-that-disappears")
        assert claimed is not None
        assert claimed.attempt_count == 1
        claimed.locked_at = now - timedelta(minutes=5)
        db.commit()

        recovered = intake_maturity.recover_stale_intake_jobs(db, now=now)
        assert recovered == 1

        job = db.get(ClaimIntakeProcessingJob, claimed.id)
        draft = db.get(ClaimIntakeDraft, draft_id)
        assert job is not None and draft is not None
        assert job.status == ProcessingJobStatus.PENDING
        assert job.attempt_count == 1
        assert job.locked_at is None
        assert job.locked_by is None
        assert draft.status == ClaimIntakeStatus.PROCESSING
        assert "attempt 2" in (draft.extraction_warnings or [""])[0]


def test_stale_intake_worker_on_final_attempt_becomes_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seed()
    login("alpha", "alpha@example.com")
    draft_id = _upload_processing_draft(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    monkeypatch.setattr(intake_maturity.settings, "processing_stale_after_seconds", 60)

    with TestingSessionLocal() as db:
        job = db.query(ClaimIntakeProcessingJob).filter_by(intake_draft_id=draft_id).one()
        job.status = ProcessingJobStatus.RUNNING
        job.attempt_count = job.max_attempts
        job.locked_at = now - timedelta(minutes=5)
        job.locked_by = "final-attempt-worker"
        db.commit()

        recovered = intake_maturity.recover_stale_intake_jobs(db, now=now)
        assert recovered == 1

        db.refresh(job)
        draft = db.get(ClaimIntakeDraft, draft_id)
        assert draft is not None
        assert job.status == ProcessingJobStatus.FAILED
        assert job.attempt_count == job.max_attempts
        assert job.locked_at is None
        assert draft.status == ClaimIntakeStatus.FAILED
        assert "attempt limit is exhausted" in (draft.extraction_warnings or [""])[0]
