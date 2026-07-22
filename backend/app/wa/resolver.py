"""Production RecipientResolver: entry_id -> patient/clinic contact.

Shared by the convo dispatcher and the scheduler jobs so the entry→recipient
query lives in exactly one place.
"""

from __future__ import annotations

from uuid import UUID

from app.wa.notify import Recipient


class PgRecipientResolver:
    async def for_entry(self, entry_id: UUID) -> Recipient | None:
        from app import db

        async with db.get_pool().acquire() as con:
            r = await con.fetchrow(
                """
                select q.token_number, q.eta, q.report_time, q.clinic_id,
                       p.wa_number, p.profile_name, c.language
                from queue_entries q
                join patients p on p.id = q.patient_id
                join clinics c on c.id = q.clinic_id
                where q.id = $1
                """,
                entry_id,
            )
        if r is None:
            return None
        return Recipient(
            wa_number=r["wa_number"],
            name="" if r["profile_name"] == "self" else r["profile_name"],
            lang=r["language"],
            token_number=r["token_number"],
            clinic_id=r["clinic_id"],
            eta=r["eta"],
            report=r["report_time"],
        )
