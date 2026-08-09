#!/usr/bin/env sh
# Two panel test files re-declare logic that lives elsewhere, because neither
# source can be imported by plain node: a service worker runs in its own global
# scope, and the other is TypeScript.
#
# A hand-copied mirror is only safe if drift is detected mechanically. Without
# this, the test keeps passing against a copy of the logic that no longer ships
# — which is worse than having no test, because it reads as coverage.

set -eu
cd "$(dirname "$0")/.."

fail=0

check() {
  src="$1"
  test_file="$2"
  shift 2
  for fn in "$@"; do
    a=$(node -e '
      const fs=require("fs");
      const s=fs.readFileSync(process.argv[1],"utf8");
      const i=s.indexOf("function "+process.argv[2]+"(");
      if(i<0){process.stdout.write("<<missing>>");process.exit(0);}
      const j=s.indexOf("\n}",i);
      process.stdout.write(s.slice(i,j+2).replace(/\s+/g," "));
    ' "$src" "$fn")
    b=$(node -e '
      const fs=require("fs");
      const s=fs.readFileSync(process.argv[1],"utf8");
      const i=s.indexOf("function "+process.argv[2]+"(");
      if(i<0){process.stdout.write("<<missing>>");process.exit(0);}
      const j=s.indexOf("\n}",i);
      process.stdout.write(s.slice(i,j+2).replace(/\s+/g," "));
    ' "$test_file" "$fn")

    # The TS source carries type annotations the .mjs mirror cannot, and
    # prettier wraps signatures differently in each file. Strip both so the
    # comparison is about logic, not syntax. Applied identically to both sides.
    # Order matters: strip the union forms before the bare ones.
    norm() {
      sed -e 's/: string | null//g' -e 's/: number | null//g' \
          -e 's/: string//g' -e 's/: number//g' -e 's/: boolean//g' -e 's/: null//g' \
          -e 's/export //g' \
          -e 's/( /(/g' -e 's/ )/)/g' -e 's/,)/)/g'
    }
    a_norm=$(printf '%s' "$a" | norm)
    b_norm=$(printf '%s' "$b" | norm)

    if [ "$a_norm" = "$b_norm" ]; then
      printf 'in sync   %-16s %s\n' "$fn" "$(basename "$test_file")"
    else
      printf 'DRIFTED   %-16s %s\n' "$fn" "$(basename "$test_file")" >&2
      printf '   source: %s\n' "$a_norm" >&2
      printf '   test:   %s\n' "$b_norm" >&2
      fail=1
    fi
  done
}

check panel/public/sw.js panel/sw.test.mjs \
  isNetworkOnly isStaticAsset isDocumentLike

check panel/app/lib/session-target.ts panel/session-target.test.mjs \
  shouldAdopt nextSelectedId

check panel/app/lib/poll-policy.ts panel/poll-policy.test.mjs \
  pollsOnInterval shouldIssueRequest

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "check_mirrors: a test's inlined copy no longer matches the shipping" >&2
  echo "               source. Update the mirror, or the test is checking" >&2
  echo "               code that does not run." >&2
  exit 1
fi
