#!/usr/bin/env sh
# The real `make test`: bring up the disposable Postgres, then run the WHOLE
# suite with skipping forbidden.
#
# Plain `pytest` reports "130 passed, 16 skipped" with a green bar. The 16 are
# every undo test, the panel routes, and the Postgres parity/concurrency tests.
# This script exists so the default developer command cannot produce that false
# green.

set -eu

CONTAINER=clinicq_pg
IMAGE=postgres:16
HOST_PORT=55432
DSN="postgresql://postgres:postgres@localhost:${HOST_PORT}/postgres"

cd "$(dirname "$0")/.."

# --- disposable Postgres -------------------------------------------------- #
if ! command -v docker >/dev/null 2>&1; then
  echo "run_tests: docker not found — needed for the Postgres suite." >&2
  echo "           Install Docker, or run the unit-only subset knowing it" >&2
  echo "           skips 16 database tests." >&2
  exit 1
fi

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "run_tests: $CONTAINER already running."
elif docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "run_tests: starting existing $CONTAINER..."
  docker start "$CONTAINER" >/dev/null
else
  echo "run_tests: creating $CONTAINER ($IMAGE) on :$HOST_PORT..."
  docker run -d --name "$CONTAINER" \
    -e POSTGRES_PASSWORD=postgres \
    -p "${HOST_PORT}:5432" \
    "$IMAGE" >/dev/null
fi

printf 'run_tests: waiting for postgres'
i=0
until docker exec "$CONTAINER" pg_isready -U postgres -q 2>/dev/null; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo ""
    echo "run_tests: postgres did not become ready in 60s." >&2
    exit 1
  fi
  printf '.'
  sleep 1
done
echo " ready."

# --- interpreter ---------------------------------------------------------- #
# Prefer the project venv so this works in Git Bash on Windows, where the
# msys `python` on PATH is a different interpreter without the dev deps.
if [ -x "backend/.venv/Scripts/python.exe" ]; then
  PY="backend/.venv/Scripts/python.exe"
elif [ -x "backend/.venv/bin/python" ]; then
  PY="backend/.venv/bin/python"
else
  PY="python"
fi

# --- run ------------------------------------------------------------------ #
# REQUIRE_PG_TESTS=1 makes a skipped database test a failure (see conftest.py).
cd backend
DATABASE_URL_TEST="$DSN" REQUIRE_PG_TESTS=1 "../$PY" -m pytest "$@"
