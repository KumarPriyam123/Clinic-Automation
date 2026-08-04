/** @type {import('next').NextConfig} */

// In proxy/demo mode the Next.js server forwards /api/* to the backend so a
// single ngrok tunnel on :3000 serves everything.  BACKEND_INTERNAL_URL is
// server-side only (no NEXT_PUBLIC_ prefix) — never exposed to the browser.
// In P7 production (Vercel + droplet) NEXT_PUBLIC_API_URL is set to the
// absolute droplet URL and the client bypasses this proxy entirely.
const BACKEND_INTERNAL_URL =
  process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

// One identifier per build, used for BOTH the Next build ID and the service
// worker's cache name. The SW cache used to be a hand-maintained constant that
// someone had to remember to bump; forgetting meant a device served last
// deploy's JS against this deploy's API with no signal that anything was wrong.
// Deriving it here removes the step that can be forgotten.
const BUILD_ID =
  process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 12) ?? `local-${Date.now().toString(36)}`;

const nextConfig = {
  reactStrictMode: true,

  generateBuildId: async () => BUILD_ID,
  // Exposed to the client so SwRegister can register /sw.js?v=<BUILD_ID>.
  // A changed script URL is itself what makes the browser fetch and install the
  // new worker rather than keeping the installed one.
  env: { NEXT_PUBLIC_BUILD_ID: BUILD_ID },

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
