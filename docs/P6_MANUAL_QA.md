# P6 — Manual QA runbook (clinic panel)

Runtime end-to-end check on a **360px viewport** (Chrome DevTools → device
toolbar → "Responsive", width 360). The automated suite proves the API + undo +
contract; this proves the panel↔backend loop a machine can't tap.

## 0. One-command setup

```bash
# terminal A — backend
make qa-seed                 # reset+seed demo clinic, open today's session, preload 5 patients
cd backend && uvicorn app.main:app --reload      # http://localhost:8000

# terminal B — panel
cd panel
cp .env.local.example .env.local     # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install && npm run dev           # http://localhost:3000
```

`make qa-seed` leaves the board with: **Asha Devi** (arrived, servable),
**Ramesh Kumar** (absent front token), **Priya Sharma** (arrived), **Sanjay
Gupta** / **Meena Kumari** (future targets, not here). Login **slug `demo` / PIN
`123456`**.

> DB note: `qa-seed` uses `DATABASE_URL` (supabase-local default
> `postgresql://postgres:postgres@localhost:54322/postgres`). Point it at
> whatever Postgres the backend's `DATABASE_URL` uses so panel + seed agree.

## 1. Checklist (each step: action → expected)

| # | Action (≤2 taps where noted) | Expected result |
|---|------|-----------------|
| 1 | Open `/`, login slug `demo` PIN `123456` | Lands on live queue; banner shows morning OPD **चालू/open**, waiting/served counts, avg |
| 2 | **NOW SERVING** card | Empty state until you press NEXT; after serving shows token#, name, **live mm:ss consult timer ticking** |
| 3 | **Walk-in in ≤2 taps**: tap `＋ वॉक-इन`, type a name, tap `＋ जोड़ें` | New token appears in list (amber **बुक** chip); keyboard was needed only for the name |
| 4 | **Mark arrived**: tap Ramesh's row → sheet → `आ गए` | Row chip flips **amber → green (आ गए)**; sheet closes; **UNDO** snackbar for 5s |
| 5 | **NEXT with an absent front**: ensure an arrived patient exists behind an un-arrived earlier token, tap the giant **अगला बुलाएँ** | Serves the **arrived** patient (NOW SERVING fills, timer starts); the absent earlier token flips to **छूटे (grace)** with a **countdown**; doctor is **not** blocked |
| 6 | **UNDO that NEXT** (snackbar `↩ वापस लें`, within 5s) | Queue returns to the prior on-screen state: served patient back in line, skipped token back to its prior chip, timer gone |
| 7 | **Call now**: tap a waiting row → `अभी बुलाएँ` | That row gets **▶ अगला** flag and jumps to the top of the list |
| 8 | **Delay broadcast**: `⚙ नियंत्रण` → `देरी +30` | Sheet closes; ETAs down the list push later; UNDO snackbar |
| 9 | **Arrival chip flip live**: in terminal B run `make qa-sim` | As each sim booking lands you hear a **chime**, see a **badge pulse**, and a new amber row; arrivals flip **green** — all without touching the screen (4s poll) |
| 10 | **Offline**: stop the backend (Ctrl-C in terminal A) | Within ~4s a **"फिर जुड़ रहे हैं… / Reconnecting…"** bar appears; last queue stays visible **read-only** (NEXT + walk-in disabled) |
| 11 | **Recovery**: restart `uvicorn` | Reconnect bar disappears; queue resumes live polling; actions re-enabled |

## 2. Definition-of-done spot checks

- Walk-in, mark-arrived, NEXT, UNDO each completed in **≤2 taps**; keyboard only for the walk-in name.
- Touch targets feel ≥56px; NEXT is the full-width 72px fixed-bottom button.
- Hindi-first labels with English underneath; status chips: booked=amber, arrived=green, in-consult=blue, grace=orange w/ countdown.
- Installable: browser shows "Install app"; installed PWA opens standalone.

## 3. If something is off

- Queue never updates live → check `.env.local` `NEXT_PUBLIC_API_URL` and CORS (`PANEL_ORIGINS` in backend config).
- 401 loop → token expired/invalid; re-login. JWT TTL is 12h.
- `qa-seed` says "No 'demo' clinic" → migrations/seed didn't apply; run `supabase db reset`.
