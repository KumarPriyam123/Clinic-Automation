# ClinicQ — Pilot metrics (the sales case study)

Three numbers turn a pilot into a case study. All come from the append-only
`events` table + `queue_entries` (every state change writes an event, by design).
Run against the clinic's Postgres. Replace `:clinic` and the date bounds.

Times are stored UTC; the clinic lives in `Asia/Kolkata`, so convert with
`at time zone 'Asia/Kolkata'` before bucketing by day/hour.

---

## 1. No-show rate — before vs after

No-show = a token that was never seen (`expired`). Seen = `done`. Rate =
expired / (done + expired), per day, so you can compare the pre-pilot baseline
(paper/verbal) to the ClinicQ period.

```sql
select
  (s.date)                                             as day,
  count(*) filter (where q.status = 'done')            as seen,
  count(*) filter (where q.status = 'expired')         as no_shows,
  round(
    100.0 * count(*) filter (where q.status = 'expired')
    / nullif(count(*) filter (where q.status in ('done','expired')), 0)
  , 1)                                                 as no_show_pct
from queue_entries q
join sessions s on s.id = q.session_id
where q.clinic_id = :clinic
group by s.date
order by s.date;
```

Headline: average `no_show_pct` for the two weeks **before** go-live vs the two
weeks **after**. (If there is no digital baseline, capture the clinic's own
estimate on day 0 and compare to the measured post number.)

---

## 2. After-hours bookings captured — the revenue that used to walk

Enquiries that arrived when the clinic was closed (would have been a missed call
/ lost patient) but ClinicQ captured. Defined as WhatsApp bookings created
outside 09:00–21:00 IST; adjust the window to the clinic's true hours.

```sql
select
  count(*) as after_hours_bookings
from events e
where e.clinic_id = :clinic
  and e.type = 'booked'
  and (e.payload->>'source' is distinct from 'walkin')
  and (extract(hour from (e.created_at at time zone 'Asia/Kolkata')) < 9
       or extract(hour from (e.created_at at time zone 'Asia/Kolkata')) >= 21);
```

Break it down by hour to show the pattern (late-night / early-morning demand):

```sql
select
  extract(hour from (e.created_at at time zone 'Asia/Kolkata'))::int as ist_hour,
  count(*) as bookings
from events e
where e.clinic_id = :clinic and e.type = 'booked'
group by ist_hour
order by ist_hour;
```

---

## 3. Average arrived → called wait — the waiting-room experience

How long a patient sat between checking in (`arrived_at`) and being called
(`called_at`). This is the number patients feel.

```sql
select
  round(avg(extract(epoch from (q.called_at - q.arrived_at)) / 60.0), 1)
      as avg_wait_min,
  round(percentile_cont(0.5) within group (
      order by extract(epoch from (q.called_at - q.arrived_at)) / 60.0), 1)
      as median_wait_min,
  count(*) as sample
from queue_entries q
where q.clinic_id = :clinic
  and q.arrived_at is not null
  and q.called_at  is not null;
```

Split before/after or by week by adding `join sessions s ... group by s.date`.

---

## Pulling it together

- **No-show rate:** before X% → after Y%.
- **After-hours bookings:** N enquiries captured that were previously lost.
- **Average wait:** M minutes (down from the clinic's prior estimate).

Sanity-cross-check against `/metrics` (`bookings_today`, `wa_sends_today`) while
the pilot runs. The `events` log is append-only, so these queries are always
reproducible after the fact.
