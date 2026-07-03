# ClinicQ — dev tasks. Requires the Supabase CLI (https://supabase.com/docs/guides/cli).

.PHONY: db-reset db-diff test lint fmt

# Reset the local/linked Supabase DB: drop, re-apply supabase/migrations/*,
# then run supabase/seed.sql (demo clinic slug 'demo', PIN 123456).
db-reset:
	supabase db reset

# Show a schema diff against migrations (sanity check before writing a new one).
db-diff:
	supabase db diff

# Backend test suite (set DATABASE_URL_TEST to include the DB round-trip test).
test:
	cd backend && python -m pytest

lint:
	cd backend && ruff check . && black --check .

fmt:
	cd backend && ruff check --fix . && black .
