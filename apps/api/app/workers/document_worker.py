from __future__ import annotations

import argparse
import socket
import time

from app.core.config import get_settings
from app.db import metadata as _metadata  # noqa: F401 - register all ORM models for standalone worker
from app.db.session import create_session
from app.modules import ai_runtime
from app.modules import processing as _processing_package  # noqa: F401
from app.modules.intake.maturity import process_intake_job
from app.modules.intake.service import claim_next_intake_job
from app.modules.processing import service as processing_service

# Worker-time AI authorization must use the newest applicable control plane.
# Assign before importing the public processing helpers so queued work cannot
# fall back to an older Production authorization after Sprint 11G exists.
processing_service.require_external_ai_runtime_authorization = (
    ai_runtime.require_external_ai_runtime_authorization
)
claim_next_job = processing_service.claim_next_job
process_job = processing_service.process_job


def run_once(worker_id: str) -> bool:
    with create_session() as db:
        security_job = claim_next_job(db, worker_id=worker_id, security_only=True)
        if security_job is not None:
            process_job(db, job=security_job)
            return True
        intake_job = claim_next_intake_job(db, worker_id=worker_id)
        if intake_job is not None:
            process_intake_job(db, job=intake_job)
            return True
        job = claim_next_job(db, worker_id=worker_id)
        if job is None:
            return False
        process_job(db, job=job)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="MCRI document processing worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-document-worker")
    args = parser.parse_args()
    settings = get_settings()
    if args.once:
        run_once(args.worker_id)
        return
    while True:
        processed = run_once(args.worker_id)
        if not processed:
            time.sleep(settings.processing_poll_seconds)


if __name__ == "__main__":
    main()
