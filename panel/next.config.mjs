/** @type {import('next').NextConfig} */

// In proxy/demo mode the Next.js server forwards /api/* to the backend so a
// single ngrok tunnel on :3000 serves everything.  BACKEND_INTERNAL_URL is
// server-side only (no NEXT_PUBLIC_ prefix) — never exposed to the browser.
// In P7 production (Vercel + droplet) NEXT_PUBLIC_API_URL is set to the
// absolute droplet URL and the client bypasses this proxy entirely.
const BACKEND_INTERNAL_URL =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,

  async rewrites() {
    return [
      {
        // /api/:path* → backend /:path*
        // Covers both /api/panel/* (queue API) and /api/healthz.
        // Note: with this proxy active, the browser talks only to :3000, so
        // CORS and PANEL_ORIGINS on the backend are irrelevant in this mode.
        source: "/api/:path*",
        destination: `${BACKEND_INTERNAL_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
