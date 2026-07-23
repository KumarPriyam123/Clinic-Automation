"""Panel REST API — JWT-auth routes the clinic web panel polls and mutates.

Design notes
------------
* Every mutating route runs its engine transition inside one asyncpg
  transaction (via ``PgRepo``, real ``SELECT ... FOR UPDATE``), then returns the
  *fresh queue snapshot* so the panel never needs a follow-up GET.
* Undo: before each mutation we snapshot the session row + all its entry rows.
  ``POST /undo`` (valid 5 s, one deep per clinic) restores that before-image —
  the true inverse of any action, uniform across walk-in / arrived / cancel /
  next / delay. Created rows (walk-in, emergency) are deleted on restore.
* Notifications are dispatched exactly like the convo path: the engine returns
  intents as data, the one dispatcher bridges them to WhatsApp (eta_shift is
  owned by the ping_scan job, so it is skipped here).
"""

from __future__ import annotations

import time as _time
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import bcrypt
from fastapi import APIRouter, Body, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from app import db, engine
from app.api.security import Clinic, CurrentClinic, encode_token
from app.engine.pg_repo import PgRepo
from app.models import Source
from app.wa.notify import NotificationDispatcher
from app.wa.resolver import PgRecipientResolver
from app.wa.sender import Sender
from app.wa.store import PoolWaStore

IST = ZoneInfo("Asia/Kolkata")
UNDO_WINDOW_S = 5.0

# entry columns restored on undo (mirrors PgRepo.save_entry's writable set)
_RESTORE_COLS = (
    "priority_time,status,source,eta,report_time,arrived_at,called_at,consult_start,"
    "done_at,grace_until,skip_count,gap_offered_at,next_up,last_notified_eta,"
    "notified_pre_arrival_at,notified_three_away_at"
).split(",")

_ACTIVE = {"booked", "arrived", "called", "in_consult", "skipped"}


# --------------------------------------------------------------------------- #
# request bodies
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    slug: str
    pin: str


class WalkinBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phone: str | None = None


class DelayBody(BaseModel):
    minutes: int = Field(ge=1, le=240)


class TimetableRow(BaseModel):
    weekday: int = Field(ge=0, le=6)
    name: str
    start_time: str  # "HH:MM"
    end_time: str
    token_cap: int = Field(ge=1, le=200)


class SettingsBody(BaseModel):
    name: str | None = None
    doctor_name: str | None = None
    specialty: str | None = None
    fee_inr: int | None = None
    language: str | None = None  # 'hi' | 'en'
    settings: dict | None = None  # policy overrides jsonb
    new_pin: str | None = None
    timetable: list[TimetableRow] | None = None


# --------------------------------------------------------------------------- #
# undo store (per-clinic, in-process — v1 is one process)
# --------------------------------------------------------------------------- #
class _LastAction:
    __slots__ = ("session_id", "snapshot", "at")

    def __init__(self, session_id: UUID, snapshot: dict, at: float) -> None:
        self.session_id = session_id
        self.snapshot = snapshot
        self.at = at


_last_action: dict[UUID, _LastAction] = {}


def _remember(clinic_id: UUID, session_id: UUID, snapshot: dict) -> None:
    _last_action[clinic_id] = _LastAction(session_id, snapshot, _time.monotonic())


# --------------------------------------------------------------------------- #
# infra: dispatcher, now
# --------------------------------------------------------------------------- #
_dispatcher: NotificationDispatcher | None = None


def _dispatch() -> NotificationDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = NotificationDispatcher(Sender(PoolWaStore()), PgRecipientResolver())
    return _dispatcher


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


# --------------------------------------------------------------------------- #
# snapshot (undo) helpers
# --------------------------------------------------------------------------- #
async def _read_snapshot(con: Any, session_id: UUID) -> dict:
    s = await con.fetchrow(
        "select id, status, doctor_free_at, avg_consult_s, consults_done "
        "from sessions where id = $1",
        session_id,
    )
    rows = await con.fetch("select * from queue_entries where session_id = $1", session_id)
    return {"session": dict(s), "entries": {r["id"]: dict(r) for r in rows}}


async def _restore(con: Any, snap: dict) -> None:
    s = snap["session"]
    await con.execute(
        "update sessions set status=$2, doctor_free_at=$3, avg_consult_s=$4, consults_done=$5 "
        "where id=$1",
        s["id"],
        s["status"],
        s["doctor_free_at"],
        s["avg_consult_s"],
        s["consults_done"],
    )
    ids = list(snap["entries"].keys())
    # rows created after the snapshot (walk-in / emergency) leave the queue again
    await con.execute(
        "delete from queue_entries where session_id=$1 and not (id = any($2::uuid[]))",
        s["id"],
        ids,
    )
    set_clause = ", ".join(f"{c}=${i + 2}" for i, c in enumerate(_RESTORE_COLS))
    sql = f"update queue_entries set {set_clause} where id=$1"
    for e in snap["entries"].values():
        await con.execute(sql, e["id"], *[e[c] for c in _RESTORE_COLS])


# --------------------------------------------------------------------------- #
# queue snapshot response
# --------------------------------------------------------------------------- #
async def _session_row(con: Any, session_id: UUID) -> dict | None:
    r = await con.fetchrow("select * from sessions where id = $1", session_id)
    return dict(r) if r else None


async def _queue_snapshot(con: Any, session: dict) -> dict:
    rows = await con.fetch(
        """
        select q.id, q.token_number, q.status, q.source, q.priority_time, q.eta,
               q.report_time, q.arrived_at, q.consult_start, q.grace_until, q.next_up,
               coalesce(nullif(p.display_name, ''), nullif(p.profile_name, 'self'),
                        'T' || q.token_number) as name
        from queue_entries q
        join patients p on p.id = q.patient_id
        where q.session_id = $1
        order by q.next_up desc, q.priority_time, q.booked_at
        """,
        session["id"],
    )
    entries: list[dict] = []
    now_serving: dict | None = None
    served = waiting = 0
    for r in rows:
        st = r["status"]
        if st == "done":
            served += 1
        if st in ("booked", "arrived", "skipped"):
            waiting += 1
        if st not in _ACTIVE:
            continue
        item = {
            "entry_id": str(r["id"]),
            "token_number": r["token_number"],
            "name": r["name"],
            "status": st,
            "source": r["source"],
            "priority_time": _iso(r["priority_time"]),
            "eta": _iso(r["eta"]),
            "report_time": _iso(r["report_time"]),
            "arrived_at": _iso(r["arrived_at"]),
            "grace_until": _iso(r["grace_until"]),
            "next_up": r["next_up"],
        }
        if st in ("called", "in_consult"):
            now_serving = {
                "entry_id": str(r["id"]),
                "token_number": r["token_number"],
                "name": r["name"],
                "consult_start": _iso(r["consult_start"]),
            }
        else:
            entries.append(item)
    return {
        "session": {
            "id": str(session["id"]),
            "name": session["name"],
            "status": session["status"],
            "date": session["date"].isoformat(),
            "start_at": _iso(session["start_at"]),
            "end_at": _iso(session["end_at"]),
            "token_cap": session["token_cap"],
            "avg_consult_s": session["avg_consult_s"],
            "doctor_free_at": _iso(session["doctor_free_at"]),
            "served": served,
            "waiting": waiting,
        },
        "now_serving": now_serving,
        "entries": entries,
    }


async def _queue_response(session_id: UUID) -> dict:
    pool = db.get_pool()
    async with pool.acquire() as con:
        session = await _session_row(con, session_id)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
        return await _queue_snapshot(con, session)


# --------------------------------------------------------------------------- #
# mutation runner: snapshot (before) + engine transition in one txn
# --------------------------------------------------------------------------- #
async def _mutate(session_id: UUID, factory: Any) -> tuple[engine.EngineResult, dict]:
    pool = db.get_pool()
    async with pool.acquire() as con, con.transaction():
        snap = await _read_snapshot(con, session_id)
        result = await factory(PgRepo(con))
    return result, snap


async def _finish(
    clinic_id: UUID, session_id: UUID, result: engine.EngineResult, snap: dict
) -> dict:
    _remember(clinic_id, session_id, snap)
    await _dispatch().dispatch(_now(), result)
    body = await _queue_response(session_id)
    body["can_undo"] = True
    return body


# --------------------------------------------------------------------------- #
# session selection
# --------------------------------------------------------------------------- #
async def _today_sessions(con: Any, clinic_id: UUID) -> list[dict]:
    today = datetime.now(IST).date()
    rows = await con.fetch(
        "select * from sessions where clinic_id = $1 and date = $2 order by start_at",
        clinic_id,
        today,
    )
    return [dict(r) for r in rows]


def _pick_current(sessions: list[dict], now: datetime) -> dict | None:
    if not sessions:
        return None
    live = [s for s in sessions if s["status"] in ("open", "paused")]
    if live:
        return live[0]
    upcoming = [s for s in sessions if s["end_at"] > now and s["status"] == "scheduled"]
    if upcoming:
        return upcoming[0]
    return sessions[-1]


# --------------------------------------------------------------------------- #
# walk-in patient
# --------------------------------------------------------------------------- #
async def _ensure_walkin_patient(con: Any, clinic_id: UUID, name: str, phone: str | None) -> UUID:
    wa_number = phone.strip() if phone and phone.strip() else f"walkin:{uuid4().hex[:12]}"
    pid = await con.fetchval(
        """
        insert into patients (clinic_id, wa_number, profile_name, display_name)
        values ($1, $2, 'self', $3)
        on conflict (clinic_id, wa_number, profile_name)
          do update set display_name = excluded.display_name
        returning id
        """,
        clinic_id,
        wa_number,
        name.strip(),
    )
    return pid


router = APIRouter(prefix="/panel", tags=["panel"])


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
@router.post("/login")
async def login(body: LoginBody) -> dict:
    pool = db.get_pool()
    async with pool.acquire() as con:
        row = await con.fetchrow(
            "select id, slug, pin_hash, name, language from clinics where slug = $1", body.slug
        )
    if row is None or not bcrypt.checkpw(body.pin.encode(), row["pin_hash"].encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "गलत slug या PIN / wrong slug or PIN")
    token = encode_token(clinic_id=row["id"], slug=row["slug"])
    return {
        "token": token,
        "clinic": {"name": row["name"], "slug": row["slug"], "language": row["language"]},
    }


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #
@router.get("/session/today")
async def session_today(clinic: Clinic = CurrentClinic) -> dict:
    pool = db.get_pool()
    async with pool.acquire() as con:
        sessions = await _today_sessions(con, clinic.id)
        current = _pick_current(sessions, _now())
        if current is None:
            return {"session": None, "now_serving": None, "entries": [], "sessions": []}
        body = await _queue_snapshot(con, current)
    body["sessions"] = [
        {
            "id": str(s["id"]),
            "name": s["name"],
            "status": s["status"],
            "start_at": _iso(s["start_at"]),
            "end_at": _iso(s["end_at"]),
        }
        for s in sessions
    ]
    return body


@router.get("/queue")
async def get_queue(session_id: UUID = Query(...), clinic: Clinic = CurrentClinic) -> dict:
    return await _queue_response(session_id)


# --------------------------------------------------------------------------- #
# per-session mutations
# --------------------------------------------------------------------------- #
@router.post("/next")
async def next_patient(
    session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic
) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.next_patient(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/walkin")
async def walkin(
    body: WalkinBody,
    session_id: UUID = Query(...),
    clinic: Clinic = CurrentClinic,
) -> dict:
    now = _now()
    pool = db.get_pool()
    async with pool.acquire() as con:
        patient_id = await _ensure_walkin_patient(con, clinic.id, body.name, body.phone)
    result, snap = await _mutate(
        session_id,
        lambda repo: engine.book(
            repo,
            now,
            clinic_id=clinic.id,
            session_id=session_id,
            patient_id=patient_id,
            requested_time=None,
            source=Source.walkin,
        ),
    )
    if result.overflow is not None:
        _last_action.pop(clinic.id, None)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"reason": result.overflow.reason, "message": "session full / सत्र भरा है"},
        )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/emergency")
async def emergency(
    body: WalkinBody,
    session_id: UUID = Query(...),
    clinic: Clinic = CurrentClinic,
) -> dict:
    now = _now()
    pool = db.get_pool()
    async with pool.acquire() as con:
        patient_id = await _ensure_walkin_patient(con, clinic.id, body.name, body.phone)
    result, snap = await _mutate(
        session_id,
        lambda repo: engine.emergency_insert(repo, now, session_id, patient_id),
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/delay")
async def delay(
    body: DelayBody,
    session_id: UUID = Query(...),
    clinic: Clinic = CurrentClinic,
) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.delay_session(repo, now, session_id, body.minutes)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/pause")
async def pause(session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.pause_session(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/resume")
async def resume(session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.resume_session(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/start")
async def start(session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.open_session(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/close")
async def close(session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.close_session(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/reopen")
async def reopen(session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.reopen_session(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/session/cancel-today")
async def cancel_today(
    session_id: UUID = Body(..., embed=True), clinic: Clinic = CurrentClinic
) -> dict:
    now = _now()
    result, snap = await _mutate(
        session_id, lambda repo: engine.cancel_session_today(repo, now, session_id)
    )
    return await _finish(clinic.id, session_id, result, snap)


# --------------------------------------------------------------------------- #
# per-entry mutations
# --------------------------------------------------------------------------- #
async def _entry_session(entry_id: UUID) -> UUID:
    pool = db.get_pool()
    async with pool.acquire() as con:
        sid = await con.fetchval("select session_id from queue_entries where id = $1", entry_id)
    if sid is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    return sid


@router.post("/entries/{entry_id}/arrived")
async def entry_arrived(entry_id: UUID = Path(...), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    session_id = await _entry_session(entry_id)
    result, snap = await _mutate(session_id, lambda repo: engine.mark_arrived(repo, now, entry_id))
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/entries/{entry_id}/cancel")
async def entry_cancel(entry_id: UUID = Path(...), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    session_id = await _entry_session(entry_id)
    result, snap = await _mutate(session_id, lambda repo: engine.cancel(repo, now, entry_id))
    return await _finish(clinic.id, session_id, result, snap)


@router.post("/entries/{entry_id}/call-now")
async def entry_call_now(entry_id: UUID = Path(...), clinic: Clinic = CurrentClinic) -> dict:
    now = _now()
    session_id = await _entry_session(entry_id)
    result, snap = await _mutate(session_id, lambda repo: engine.call_now(repo, now, entry_id))
    return await _finish(clinic.id, session_id, result, snap)


# --------------------------------------------------------------------------- #
# undo
# --------------------------------------------------------------------------- #
@router.post("/undo")
async def undo(clinic: Clinic = CurrentClinic) -> dict:
    action = _last_action.get(clinic.id)
    if action is None or (_time.monotonic() - action.at) > UNDO_WINDOW_S:
        _last_action.pop(clinic.id, None)
        raise HTTPException(status.HTTP_409_CONFLICT, "undo window expired")
    pool = db.get_pool()
    async with pool.acquire() as con, con.transaction():
        # lock the session so undo can't interleave with a concurrent mutation
        await con.execute("select id from sessions where id=$1 for update", action.session_id)
        await _restore(con, action.snapshot)
    _last_action.pop(clinic.id, None)
    return await _queue_response(action.session_id)


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
@router.get("/settings")
async def get_settings(clinic: Clinic = CurrentClinic) -> dict:
    pool = db.get_pool()
    async with pool.acquire() as con:
        c = await con.fetchrow(
            "select slug, name, doctor_name, specialty, fee_inr, language, settings "
            "from clinics where id = $1",
            clinic.id,
        )
        tt = await con.fetch(
            "select weekday, name, start_time, end_time, token_cap "
            "from timetable where clinic_id = $1 order by weekday, start_time",
            clinic.id,
        )
    return {
        "clinic": {
            "slug": c["slug"],
            "name": c["name"],
            "doctor_name": c["doctor_name"],
            "specialty": c["specialty"],
            "fee_inr": c["fee_inr"],
            "language": c["language"],
            "settings": c["settings"],
        },
        "timetable": [
            {
                "weekday": r["weekday"],
                "name": r["name"],
                "start_time": r["start_time"].strftime("%H:%M"),
                "end_time": r["end_time"].strftime("%H:%M"),
                "token_cap": r["token_cap"],
            }
            for r in tt
        ],
    }


def _parse_hhmm(value: str) -> dt_time:
    hh, mm = value.split(":")
    return dt_time(int(hh), int(mm))


@router.put("/settings")
async def put_settings(body: SettingsBody, clinic: Clinic = CurrentClinic) -> dict:
    pool = db.get_pool()
    async with pool.acquire() as con, con.transaction():
        sets: list[str] = []
        args: list[Any] = []
        for col, val in (
            ("name", body.name),
            ("doctor_name", body.doctor_name),
            ("specialty", body.specialty),
            ("fee_inr", body.fee_inr),
            ("language", body.language),
            ("settings", body.settings),
        ):
            if val is not None:
                args.append(val)
                sets.append(f"{col} = ${len(args)}")
        if body.new_pin is not None:
            if not (body.new_pin.isdigit() and len(body.new_pin) == 6):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "PIN must be 6 digits")
            pin_hash = bcrypt.hashpw(body.new_pin.encode(), bcrypt.gensalt()).decode()
            args.append(pin_hash)
            sets.append(f"pin_hash = ${len(args)}")
        if sets:
            args.append(clinic.id)
            await con.execute(
                f"update clinics set {', '.join(sets)} where id = ${len(args)}", *args
            )
        if body.timetable is not None:
            await con.execute("delete from timetable where clinic_id = $1", clinic.id)
            for row in body.timetable:
                await con.execute(
                    "insert into timetable (clinic_id, weekday, name, start_time, end_time, "
                    "token_cap) values ($1, $2, $3, $4, $5, $6)",
                    clinic.id,
                    row.weekday,
                    row.name,
                    _parse_hhmm(row.start_time),
                    _parse_hhmm(row.end_time),
                    row.token_cap,
                )
    return await get_settings(clinic)


def build_router() -> APIRouter:
    return router


__all__ = ["router", "build_router"]
