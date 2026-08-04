"""Test-suite gates.

`pytest` on its own reports "130 passed, 16 skipped" and prints a green bar.
Those 16 are not decoration: they are every undo test, the panel route tests,
and the Postgres parity and concurrency tests — i.e. most of what actually
touches the database. A green bar that silently omits them is a false green,
and it is the kind of signal a deploy gets made on.

Two mechanisms:

* `make test` (scripts/run_tests.sh) starts the disposable Postgres and sets
  DATABASE_URL_TEST, so the default developer command runs all 146.
* `REQUIRE_PG_TESTS=1` turns "skipped because there is no database" into a hard
  failure. Set it in CI and before a deploy, where a skip must never pass for a
  pass.
"""

from __future__ import annotations

import asyncio
import os

import pytest

_REQUIRE = os.getenv("REQUIRE_PG_TESTS") == "1"
_DSN = os.getenv("DATABASE_URL_TEST")

# Substring identifying the skipif marks the pg-gated modules declare.
_PG_SKIP_MARKER = "DATABASE_URL_TEST"


def pytest_configure(config: pytest.Config) -> None:
    """Fail the whole run early when pg tests are required but unavailable.

    Checked here rather than per-test so a missing container reports one clear
    message instead of sixteen connection errors.
    """
    if not _REQUIRE:
        return

    if not _DSN:
        raise pytest.UsageError(
            "REQUIRE_PG_TESTS=1 but DATABASE_URL_TEST is not set. The Postgres "
            "suite would be skipped, and a skip must not pass for a pass. "
            "Run `make test`, which starts the container and sets it."
        )

    try:
        asyncio.run(_probe(_DSN))
    except Exception as exc:  # noqa: BLE001 — any failure to reach pg is fatal here
        raise pytest.UsageError(
            f"REQUIRE_PG_TESTS=1 but DATABASE_URL_TEST is unreachable: {exc}. "
            "Start the disposable Postgres (`make test` does this for you)."
        ) from None


async def _probe(dsn: str) -> None:
    import asyncpg

    con = await asyncpg.connect(dsn, timeout=5)
    try:
        await con.execute("select 1")
    finally:
        await con.close()


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Turn a pg skip into a failure under REQUIRE_PG_TESTS.

    `tryfirst` matters: this must run before pytest's own skipping plugin
    evaluates the module-level `skipif`, or the test is already skipped by the
    time we see it.
    """
    if not _REQUIRE or _DSN:
        return
    for mark in item.iter_markers(name="skipif"):
        if _PG_SKIP_MARKER in str(mark.kwargs.get("reason", "")):
            pytest.fail(
                "requires DATABASE_URL_TEST (REQUIRE_PG_TESTS=1 forbids skipping it)",
                pytrace=False,
            )
