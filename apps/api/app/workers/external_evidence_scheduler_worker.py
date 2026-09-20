from __future__ import annotations

import argparse
import socket
import time

from app.core.config import get_settings
from app.db import metadata as _metadata  # noqa: F401
from app.db.session import create_session
from app.modules.external_document_sources.due_tick_dispatch_service import dispatch_next_due_tick


def run_once(worker_id: str) -> bool:
    with create_session() as db:
        return dispatch_next_due_tick(db, worker_id=worker_id) is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="MCRI external Evidence recurring observation scheduler")
    parser.add_argument("--once", action="store_true", help="Create at most one due-tick dispatch and exit")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-external-evidence-scheduler")
    args = parser.parse_args()
    settings = get_settings()
    if args.once:
        run_once(args.worker_id)
        return
    while True:
        dispatched = run_once(args.worker_id)
        if not dispatched:
            time.sleep(settings.external_evidence_scheduler_poll_seconds)


if __name__ == "__main__":
    main()
