from __future__ import annotations

import argparse
import socket
import time

from app.core.config import get_settings
from app.db import metadata as _metadata  # noqa: F401 - register all ORM models for standalone worker
from app.db.session import create_session
from app.modules.processing.service import claim_next_job, process_job


def run_once(worker_id: str) -> bool:
    with create_session() as db:
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
