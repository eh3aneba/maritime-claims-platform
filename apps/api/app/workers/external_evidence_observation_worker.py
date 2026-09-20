from __future__ import annotations

import argparse
import time

from app.core.config import get_settings
from app.db import metadata as _metadata  # noqa: F401
from app.db.session import create_session
from app.modules.external_document_sources.due_tick_dispatch_consumption_service import (
    consume_next_due_tick_dispatch,
)


def run_once(service_executor_id: str) -> bool:
    with create_session() as db:
        return (
            consume_next_due_tick_dispatch(
                db,
                service_executor_id=service_executor_id,
            )
            is not None
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "MCRI external Evidence internal service-executor observation worker"
        )
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Consume at most one due-tick dispatch and exit",
    )
    args = parser.parse_args()
    settings = get_settings()
    service_executor_id = settings.external_evidence_service_executor_id
    if args.once:
        run_once(service_executor_id)
        return
    while True:
        consumed = run_once(service_executor_id)
        if not consumed:
            time.sleep(settings.external_evidence_observer_poll_seconds)


if __name__ == "__main__":
    main()
