#!/usr/bin/env sh
# Refuse destructive DB work unless the target is unmistakably local.
#
# `make db-reset` drops the schema, re-applies migrations, and seeds a demo
# clinic with a PIN that is written down in this repo. Pointed at production
# that wipes a live clinic's queue and plants known credentials on it.
#
# This is not hypothetical: during P8 the panel's .env.local was aimed at the
# production backend for an entire week without anyone noticing. The same class
# of mistake in DATABASE_URL is one keystroke away.
#
# Exits 0 only when the DSN host is localhost / 127.0.0.1 / ::1, or when no DSN
# is set at all (the Supabase CLI then uses its own local stack).

set -eu

dsn="${DATABASE_URL:-}"

if [ -z "$dsn" ]; then
  echo "guard: DATABASE_URL unset — assuming the local Supabase stack. OK."
  exit 0
fi

# Strip scheme and any user:password@, then take the host up to : / ? or end.
host=$(printf '%s' "$dsn" | sed -e 's|^[a-zA-Z0-9+]*://||' -e 's|^[^@/]*@||' -e 's|[:/?].*$||')

case "$host" in
  localhost | 127.0.0.1 | ::1 | "[::1]")
    echo "guard: DATABASE_URL host is '$host'. OK."
    exit 0
    ;;
  "")
    echo "guard: REFUSING — could not parse a host out of DATABASE_URL." >&2
    exit 1
    ;;
  *)
    echo "guard: REFUSING to reset a non-local database." >&2
    echo "       DATABASE_URL host is '$host', which is not localhost." >&2
    echo "       This target drops the schema and seeds a demo clinic with a" >&2
    echo "       PIN documented in this repo. Refusing to run it against a" >&2
    echo "       remote database." >&2
    echo "" >&2
    echo "       If you really meant a local reset, point DATABASE_URL at" >&2
    echo "       localhost (or unset it to use the local Supabase stack)." >&2
    exit 1
    ;;
esac
