"""
Shuhul analysis worker.

Takes queued projects from the database one at a time and runs the
analysis pipeline for each.

    python -m backend.worker
"""

import time

from .config import WATCH_REFRESH_HOURS
from .db import claim_next_project, fail_stale_projects, init_db
from .services.pipeline import run_project
from .services.watch_ingest import ingest_in_background

POLL_SECONDS = 2


def run_once():
    """Run one queued project, if any. Returns True when one was run."""
    claimed = claim_next_project()

    if claimed is None:
        return False

    project_id, payload = claimed
    run_project(project_id, payload)
    return True


def work_forever():
    init_db()
    fail_stale_projects()
    last_watch_refresh = 0.0

    while True:
        # Environmental Watch reads the outlets on its own thread, so a
        # refresh never holds up a queued analysis.
        if WATCH_REFRESH_HOURS > 0 and (
            time.time() - last_watch_refresh >= WATCH_REFRESH_HOURS * 3600
        ):
            last_watch_refresh = time.time()
            ingest_in_background()

        if not run_once():
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    print("Shuhul worker started. Waiting for projects.", flush=True)
    work_forever()
