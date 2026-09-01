from __future__ import annotations

import argparse
import socket
import time

from app.core.config import get_settings
from app.db import metadata as _metadata  # noqa: F401 - register ORM models in standalone worker
from app.db.session import create_session
from app.modules.governance_webhooks.service import (
    claim_next_delivery,
    process_delivery,
    sync_content_free_ai_events,
)


def run_once(worker_id: str) -> bool:
    with create_session() as db:
        sync_content_free_ai_events(db)
        delivery = claim_next_delivery(db, worker_id=worker_id)
        if delivery is None:
            return False
        process_delivery(db, delivery=delivery)
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="MCRI content-free governance webhook worker")
    parser.add_argument("--once", action="store_true", help="Sync and process at most one delivery")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-governance-webhook-worker")
    args = parser.parse_args()
    settings = get_settings()
    if args.once:
        run_once(args.worker_id)
        return
    while True:
        processed = run_once(args.worker_id)
        if not processed:
            time.sleep(settings.governance_webhook_poll_seconds)


if __name__ == "__main__":
    main()
