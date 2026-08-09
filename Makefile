# ClinicQ — dev tasks. Requires the Supabase CLI (https://supabase.com/docs/guides/cli).

.PHONY: db-reset db-diff test lint fmt qa-seed qa-sim guard-local-db

# Refuse any destructive DB target unless DATABASE_URL is local (or unset).
# See scripts/guard_local_db.sh for why this exists.
guard-local-db:
	@sh scripts/guard_local_db.sh

# Reset the local/linked Supabase DB: drop, re-apply supabase/migrations/*,
# then run supabase/seed.sql (demo clinic slug 'demo', PIN 123456).
# Guarded: seeding known credentials into a live database must not be one
# mistyped env var away.
db-reset: guard-local-db
	supabase db reset

# Show a schema diff against migrations (sanity check before writing a new one).
db-diff:
	supabase db diff

# THE test command. Starts the disposable Postgres, sets DATABASE_URL_TEST, and
# runs the suite with REQUIRE_PG_TESTS=1 so a skipped database test is a
# failure. Bare `pytest` reports "130 passed, 16 skipped" with a green bar —
# that green omits every undo test, the panel routes, and the pg parity and
# concurrency tests. Use this target, not pytest.
test: test-sw
	@sh scripts/run_tests.sh

# Panel unit tests (no framework, plain node) + the mirror-drift guard that
# keeps their inlined copies honest.
test-sw:
	@sh scripts/check_mirrors.sh
	node panel/sw.test.mjs
	node panel/session-target.test.mjs

lint:
	cd backend && ruff check . && black --check .

fmt:
	cd backend && ruff check --fix . && black .

# One-command QA board: reset+seed the demo clinic, then open today's session
# and pre-load ~5 patients so the panel lands on a realistic live queue.
# DATABASE_URL must point at the same DB (supabase local default shown).
qa-seed: guard-local-db
	supabase db reset
	DATABASE_URL=$${DATABASE_URL:-postgresql://postgres:postgres@localhost:54322/postgres} \
		python scripts/seed_demo_queue.py

# Drive live bookings/arrivals into that session so the panel updates on-screen.
qa-sim:
	DATABASE_URL=$${DATABASE_URL:-postgresql://postgres:postgres@localhost:54322/postgres} \
		python scripts/simulate_session.py --pg --patients 4 --speed 5
