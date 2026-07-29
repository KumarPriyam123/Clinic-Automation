# ClinicQ — 60-minute clinic onboarding (done-for-you)

Goal: a pilot clinic live and taking WhatsApp bookings by tomorrow morning, with
a receptionist who confidently does **four** things and nothing else.

Prereq: backend + panel already deployed (see `DEPLOY.md`) and the production
WhatsApp number passed the live round-trip smoke.

---

## 0–10 min · Collect (one WhatsApp call or visit)

- Clinic name, doctor name, specialty, consult fee (₹).
- Language: **hi** (default) or **en**.
- Weekly hours: morning + evening windows, days open, and the **token cap** per
  session (how many patients the doctor sees in one session).
- The receptionist's phone (for the panel) and the doctor's phone (for the digest).

## 10–20 min · Create the clinic (script, not raw SQL)

```bash
DATABASE_URL="<direct Supabase DSN>" python scripts/create_clinic.py \
  --slug <slug> --name "<Clinic>" --doctor "Dr. <X>" \
  --pin <6 digits> --language hi --fee <inr> \
  --morning 09:00-13:00 --evening 17:00-21:00 --cap <n>
```
Pick a short lowercase **slug** (the panel login) and a **6-digit PIN** the
receptionist will remember. Re-running updates the clinic + timetable.

Overnight, the `stamp_sessions` job (00:05 IST) materializes tomorrow's sessions
from this timetable — nothing else to do.

## 20–30 min · Poster

```bash
python scripts/qr_poster.py --number <91XXXXXXXXXX> --clinic "<Clinic>" \
  --out <slug>_poster.pdf     # needs: pip install ".[pilot]"
```
Print A4, **laminate**, place at the desk and on the door. The QR opens
`wa.me/<number>?text=Namaste` — patients scan and send "Namaste" to book.

## 30–45 min · Train the receptionist (15 min, exactly four actions)

Open the panel on their phone → login (slug + PIN) → **Add to Home Screen**
(installs the PWA; bookmark). Teach only these, on the live queue screen:

1. **NEXT** — the big bottom button. Call the next patient. That's the whole job
   most of the day.
2. **Walk-in** — someone without WhatsApp: tap **+ वॉक-इन**, type the name, **Add**.
3. **Mark arrived** — patient reaches the desk: tap their row → **आ गए**.
4. **Undo** — tapped wrong: the **↩ वापस लें** snackbar (5 seconds) reverses it.

Explicitly say: ignore everything else. Delays, close, settings are for you (the
onboarder) or occasional use. The colored chips read themselves (amber = booked,
green = arrived, blue = in consult).

## 45–55 min · Doctor's phone

- Panel bookmark (optional — the doctor rarely needs it).
- Confirm the doctor's number will receive the **21:45 IST digest** (seen /
  no-shows / tomorrow's load). No app to install.

## 55–60 min · Dry run with 3 staff phones

From three phones, message the clinic number "Namaste" → book → watch the three
tokens land live on the panel (chime + badge). Have the receptionist **NEXT**
through them, mark one **arrived**, and **undo** once. Cancel the test tokens
(panel → row → Cancel, or just Close today afterwards).

Go live next morning.

---

## Rollback / if something breaks mid-session

- **Slow down / stop calling:** panel → session controls → **Pause** (bookings
  still queue; nobody is called until Resume).
- **Abandon the session:** **Close today** — patients already seen are recorded;
  waiting patients get "come tomorrow." Mis-tap → **Reopen** (same day).
- **Total outage (panel won't load):** the clinic can run on paper for the
  session; bookings keep arriving on WhatsApp and appear once the panel is back
  (the DB is the source of truth). Call the ClinicQ contact; check
  `https://<subdomain>/healthz`.
- **Take the clinic fully offline:** stop the backend (`docker compose down`) or
  Pause every session — patients then simply get no auto-replies until restored.
