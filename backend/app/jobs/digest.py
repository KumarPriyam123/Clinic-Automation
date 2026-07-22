"""doctor_digest — one business-initiated summary per clinic, daily 21:45 IST.

Computed from the day's data (events/queue_entries): patients seen, no-shows,
avg consult, WhatsApp bookings, and tomorrow-morning bookings. Sent to the
clinic's WhatsApp number as an approved template (force_template — outside any
24-hour window).
"""

from __future__ import annotations

from datetime import datetime

from app.jobs.store import JobBackend
from app.wa.sender import Sender


async def run_digest(backend: JobBackend, sender: Sender, now: datetime) -> int:
    sent = 0
    for clinic in await backend.clinics():
        if not clinic.wa_number:
            continue
        s = await backend.digest_stats(clinic.id, now)
        await sender.send(
            now,
            clinic.wa_number,
            template_name="doctor_digest",
            ctx={
                "seen": s.seen,
                "noshow": s.no_shows,
                "avg": s.avg_min,
                "wa": s.wa_bookings,
                "tomorrow": s.tomorrow_morning,
            },
            lang=clinic.language,
            clinic_id=clinic.id,
            force_template=True,
        )
        sent += 1
    return sent
