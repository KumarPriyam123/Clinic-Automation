# Demo runbook — showing the panel to someone else

## The problem

Free ngrok allows **one tunnel at a time**.  The backend needs a tunnel on :8000
for the WhatsApp webhook; the panel needs a tunnel on :3000 to be reachable on
another device.  Cloudflare quick tunnels (`trycloudflare.com`) are blocked on
some networks.  Pick the mode that fits your situation.

---

## Mode 1 — Single tunnel (demo the panel UI, no live WA)

The Next.js server proxies `/api/*` to the local backend, so one ngrok tunnel on
:3000 serves both the panel **and** the backend API.

```
Terminal 1 — backend (stays local, no tunnel)
  cd backend
  .venv\Scripts\python.exe -m uvicorn app.main:app --reload

Terminal 2 — panel dev server  
  cd panel
  npm run dev           # starts on :3000

Terminal 3 — one tunnel on the panel
  C:\Users\kumar\ngrok\ngrok.exe http 3000
```

Copy the `https://xxxx.ngrok-free.app` URL.  On the remote device, open that URL
and log in with slug `demo` PIN `123456`.

**No env vars needed** — `api.ts` defaults to `/api` and `next.config.mjs`
defaults `BACKEND_INTERNAL_URL` to `http://localhost:8000`.

**⚠ Tradeoff:** While the tunnel is on :3000, the WhatsApp webhook
(`/webhook`) is not reachable from Meta.  Inbound WhatsApp messages will not
arrive and live booking will not work.  Use this mode for visual demos of the
queue UI only.

**Service worker:** `/api/*` requests are never cached — the SW passes them
straight to the Next.js dev server which proxies them to the backend.

---

## Mode 2 — Two tunnels (full WA round-trip, your screen only)

```
Terminal 1 — backend
  cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload

Terminal 2 — ngrok on backend (for Meta webhook)
  C:\Users\kumar\ngrok\ngrok.exe http 8000

Terminal 3 — panel dev server  
  cd panel && npm run dev
```

Use the panel at `http://localhost:3000`.  Point Meta's webhook at the :8000
tunnel.  Full WA flow works; panel is on your screen, not the other device.

---

## Mode 3 — P7 production (Vercel + DigitalOcean)

```
Vercel env vars (panel):
  NEXT_PUBLIC_API_URL = https://clinicq.yourdomain.com   # droplet public URL
  # BACKEND_INTERNAL_URL is not set (proxy bypass)

Droplet (backend):
  PANEL_ORIGINS = ["https://your-panel.vercel.app"]      # for CORS
```

The browser talks directly to the droplet.  The Next.js proxy rewrite exists but
is never triggered because the client uses an absolute URL.

---

## Environment matrix

| Variable | Local dev | Proxy/demo | P7 production |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | *(unset)* = `/api` | *(unset)* = `/api` | `https://backend-domain` |
| `BACKEND_INTERNAL_URL` | *(unset)* = `http://localhost:8000` | *(unset)* = `http://localhost:8000` | *(not used)* |
| `PANEL_ORIGINS` (backend) | `["http://localhost:3000"]` | *(irrelevant — proxy mode)* | `["https://panel.vercel.app"]` |
| ngrok | optional | :3000 only | none (named CF tunnel) |
| WA webhook reachable | only if ngrok on :8000 | ✗ | ✓ |

**CORS note:** in proxy/demo mode the browser never talks to the backend directly,
so `PANEL_ORIGINS` on the backend is irrelevant.  In production the droplet must
list the Vercel domain in `PANEL_ORIGINS`.
