"""APScheduler jobs: sweep (auto-open/close + grace/gap expiries), ping_scan
(pre_arrival / three_away / eta_shift), daily session stamping, doctor digest.

Job bodies are pure functions with an injected ``now`` (FakeClock in tests);
scheduler.py binds them to real triggers inside the FastAPI lifespan.
"""

from app.jobs.digest import run_digest
from app.jobs.pings import ping_scan
from app.jobs.scheduler import build_scheduler
from app.jobs.store import ClinicRow, JobBackend, MemJobs, PgJobs, TimetableRow
from app.jobs.sweep import stamp_daily, sweep_tick

__all__ = [
    "run_digest",
    "ping_scan",
    "build_scheduler",
    "sweep_tick",
    "stamp_daily",
    "JobBackend",
    "MemJobs",
    "PgJobs",
    "ClinicRow",
    "TimetableRow",
]
