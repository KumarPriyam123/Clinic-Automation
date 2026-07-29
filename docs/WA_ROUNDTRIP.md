# WA Round-Trip — local dev runbook (Windows / Git Bash)

Every session against Meta's test number needs these steps because free ngrok
gives a **new URL on every restart**. The permanent Cloudflare tunnel (P7 / prod
droplet) removes this friction entirely.

---

## Prerequisites (one-time)

| Item | Where |
|---|---|
| ngrok binary | `C:\Users\kumar\ngrok\ngrok.exe` |
| Meta app "ClinicQ" | developers.facebook.com → App dashboard |
| `.env` with all four WA vars | `backend/.env` |
| DB seeded | `make db-reset` |

---

## Each session — exact steps

### 1. Start the backend

Open **Terminal 1** (Git Bash or PowerShell in `backend/`):

```bash
cd "C:/Projects/Clinic Appointment/backend"
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Wait for `Application startup complete.` in the log.

### 2. Start ngrok

Open **Terminal 2**:

```bash
C:\Users\kumar\ngrok\ngrok.exe http 8000
```

Copy the `Forwarding` HTTPS URL, e.g. `https://a1b2c3d4.ngrok-free.app`.

### 3. Update the webhook callback URL in Meta

1. Go to [developers.facebook.com](https://developers.facebook.com) → ClinicQ app
2. **WhatsApp → Configuration → Webhook**
3. Click **Edit**
4. **Callback URL:** `https://a1b2c3d4.ngrok-free.app/webhook`
5. **Verify token:** `clinicq_verify_x7k2m9`
6. Click **Verify and Save** — Meta does a GET handshake; backend must be running

> **Note:** After saving, click **Manage** on the `messages` field and confirm it
> is subscribed. You'll get delivery statuses and inbound messages through this
> field.

### 4. Run the preflight checker

```bash
cd "C:/Projects/Clinic Appointment/backend"
.venv/Scripts/python.exe ../scripts/wa_preflight.py
```

All four checks must show `PASS` before sending test messages.

### 5. Send "hi" from your phone to +1 555 162-7387

Expected log lines in Terminal 1 (in order):

```
INFO clinicq.webhook wa_status_event wamid=... status=sent recipient=...
INFO clinicq.webhook wa_status_event wamid=... status=delivered recipient=...
INFO clinicq http method=POST path=/webhook status=200 dur_ms=...
INFO clinicq http method=POST path=/webhook status=200 dur_ms=...
```

And the inbound message log:

```
INFO clinicq http method=POST path=/webhook status=200 dur_ms=...
```

The flow handler (`convo/flow.py`) will attempt a `clinic_for_phone` lookup.
If the demo clinic has `wa_phone_number_id` set correctly, it will proceed to
greet the patient and offer session booking.

---

## Where to look when it fails

| Symptom | Where to look |
|---|---|
| **GET /webhook → 403** | Verify token mismatch — check `WA_VERIFY_TOKEN` in `.env` matches Meta |
| **POST /webhook → 403** | Signature failure — see `sig_verify` WARNING in backend log (shows expected vs received digest prefix, body len, secret len) |
| **POST /webhook → 403** | `WA_APP_SECRET` wrong — get it from Meta app → Settings → Basic → App Secret |
| **Messages arrive, no reply** | `clinic_for_phone` returns None — check `clinics.wa_phone_number_id` = `1198540706681830` in DB |
| **No webhook hit at all** | ngrok URL not updated in Meta console, or backend not running on port 8000 |
| **ngrok inspector** | `http://127.0.0.1:4040` — shows exact raw request/response for every webhook hit |

---

## Diagnosing signature failures

The backend logs two WARNING lines on every HMAC mismatch (no secrets leaked):

```
sig_verify digest_mismatch expected_prefix=<12 chars> received_prefix=<12 chars> body_len=<N> secret_len=<N>
```

- **`secret_len` ≠ 32** → wrong `WA_APP_SECRET` (copy from Meta → App Settings → Basic)
- **`body_len=0`** → body consumed before signature check (should not happen — `request.body()` is called first)
- **`expected_prefix` ≠ `received_prefix`** → Meta is using a different secret; re-verify the App Secret value

---

## Curl — local preflight verify handshake

Verify the GET endpoint without ngrok:

```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=clinicq_verify_x7k2m9&hub.challenge=test123"
# expected: test123   HTTP 200
```

---

## Known friction

- **Free ngrok = new URL every restart.** Step 3 (update Meta webhook URL) is
  required every session. The paid ngrok plan or a named Cloudflare tunnel
  (used in prod) gives a stable URL and eliminates this step.
- **Meta caches the callback URL** for ~30s after you save. If you see 403s
  immediately after a URL change, wait and retry.
- **Status events fire for every outbound message** (sent → delivered → read).
  These POST to `/webhook` with a `statuses[]` field instead of `messages[]`.
  The backend logs them at INFO and ACKs 200 — they are not errors.
