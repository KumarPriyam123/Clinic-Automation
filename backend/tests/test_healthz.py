"""Health probe smoke test. No network — pure in-process TestClient."""

from fastapi.testclient import TestClient

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
