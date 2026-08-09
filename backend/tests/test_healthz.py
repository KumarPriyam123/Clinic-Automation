"""Health probe smoke test. No network — pure in-process TestClient."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_healthz_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_healthz_stays_open_and_leaks_nothing() -> None:
    """Uptime monitors depend on this being unauthenticated. It must also stay
    a bare liveness answer — no counts, no identifiers."""
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_metrics_404s_when_no_token_configured(monkeypatch) -> None:
    """Unset METRICS_TOKEN must fail CLOSED, never serve unguarded counts."""
    from app.config import settings

    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    client = TestClient(create_app())
    resp = client.get("/metrics")
    assert resp.status_code == 404
    assert "bookings_today" not in resp.text


def test_metrics_401s_without_a_valid_token(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    client = TestClient(create_app())

    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "s3cret-token"},  # missing the Bearer scheme
        {"Authorization": "Bearer "},
        {"Authorization": "Bearer s3cret-toke"},  # prefix of the real token
    ):
        resp = client.get("/metrics", headers=headers)
        assert resp.status_code == 401, headers
        assert "bookings_today" not in resp.text


# --------------------------------------------------------------------------- #
# Boot guard: production must not fall back to the localhost CORS defaults.
#
# HAZARD: this guard can take production down if it misfires, so its scope is
# tested as carefully as its trigger. An unrecognised ENV must always boot.
# --------------------------------------------------------------------------- #
def _settings(**kw) -> Settings:
    return Settings(**kw)


def test_prod_without_panel_origins_refuses_to_boot(monkeypatch) -> None:
    monkeypatch.delenv("PANEL_ORIGINS", raising=False)
    for env in ("prod", "production", "PROD", " Production "):
        s = _settings(ENV=env)
        with pytest.raises(RuntimeError) as exc:
            s.assert_panel_origins_configured()
        assert "PANEL_ORIGINS" in str(exc.value), env


def test_prod_with_panel_origins_boots(monkeypatch) -> None:
    monkeypatch.setenv("PANEL_ORIGINS", '["https://app.clinicq.kpriyam.me"]')
    s = _settings(ENV="prod", PANEL_ORIGINS=["https://app.clinicq.kpriyam.me"])
    s.assert_panel_origins_configured()  # must not raise


def test_prod_tolerates_localhost_alongside_real_origins(monkeypatch) -> None:
    """The live droplet legitimately carries localhost next to real origins."""
    # Must be a JSON array: pydantic-settings json-decodes this field at
    # construction, so a bare string raises SettingsError before we get here.
    monkeypatch.setenv(
        "PANEL_ORIGINS", '["https://app.clinicq.kpriyam.me","http://localhost:3000"]'
    )
    s = _settings(
        ENV="prod",
        PANEL_ORIGINS=["https://app.clinicq.kpriyam.me", "http://localhost:3000"],
    )
    s.assert_panel_origins_configured()  # must not raise


def test_unrecognised_env_never_fails_closed(monkeypatch) -> None:
    """A typo in ENV must boot normally, never take the backend dark."""
    monkeypatch.delenv("PANEL_ORIGINS", raising=False)
    for env in ("dev", "staging", "prodution", "", "PRODUCTION_LIKE"):
        s = _settings(ENV=env)
        s.assert_panel_origins_configured()  # must not raise
        assert s.is_production() is False, env


def test_is_production_recognises_only_prod_values() -> None:
    for env in ("prod", "production", "PROD", "Production", " prod "):
        assert _settings(ENV=env).is_production() is True, env
    for env in ("dev", "test", "staging", "prd", "prodution", ""):
        assert _settings(ENV=env).is_production() is False, env
