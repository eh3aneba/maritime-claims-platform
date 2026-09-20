from __future__ import annotations

import argparse
import time

from app.core.config import get_settings
from app.db import metadata as _metadata  # noqa: F401
from app.db.session import create_session
from app.modules.external_document_sources.observation_review_handoff_service import (
    project_next_observation_review_handoff,
)


def run_once(projector_id: str) -> bool:
    with create_session() as db:
        return (
            project_next_observation_review_handoff(
                db,
                projector_id=projector_id,
            )
            is not None
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCRI external Evidence scheduled-observation review projector"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Project at most one changed/missing observation and exit",
    )
    args = parser.parse_args()
    settings = get_settings()
    projector_id = settings.external_evidence_review_projector_id
    if args.once:
        run_once(projector_id)
        return
    while True:
        projected = run_once(projector_id)
        if not projected:
            time.sleep(settings.external_evidence_review_projector_poll_seconds)


if __name__ == "__main__":
    main()
