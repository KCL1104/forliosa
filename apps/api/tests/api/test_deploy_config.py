"""Production cookie and CORS settings.

Deployment target: frontend on Cloudflare Pages at ``https://app.example.com``, API on Railway at
``https://api.example.com``. Both are the same *site* (registrable domain ``example.com``), so a
``SameSite=Lax`` session cookie is sent on the frontend's ``fetch(..., {credentials: "include"})``;
the cookie must be ``Secure`` and ``HttpOnly``, and CORS must echo the exact frontend origin with
``Access-Control-Allow-Credentials: true`` (never ``*``).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from forliosa.config import get_settings

API = "/api/v1"
APP_ORIGIN = "https://app.example.com"
SECRET = "test-session-secret-" + "x" * 40


@pytest.fixture()
def prod_app(monkeypatch, engine, market):
    """Build the app with production settings; settings are re-read from the patched environment."""

    def build(**env: str | None):
        values: dict[str, str | None] = {
            "FORLIOSA_ENV": "prod", "SESSION_SECRET": SECRET, "CORS_ORIGINS": APP_ORIGIN,
            "COOKIE_DOMAIN": ".example.com", "COOKIE_SECURE": None,
        }
        values.update(env)
        for key, value in values.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        from forliosa.api.app import create_app

        return create_app()

    yield build
    monkeypatch.undo()
    get_settings.cache_clear()


def _login() -> tuple[str, str]:
    """Create a session the way a production login will (dev-login is disabled in prod)."""
    from forliosa.api.deps import create_session
    from forliosa.db import session_factory
    from forliosa.models import User

    with session_factory()() as db:
        user = User(id="usr_prod", email="prod@example.com", display_name="正式使用者", preferences={})
        db.add(user)
        db.commit()
        resp = Response()
        create_session(db, user, resp)
    cookie = resp.headers["set-cookie"]
    token = cookie.split("forliosa_session=", 1)[1].split(";", 1)[0]
    return cookie, token


def test_prod_session_cookie_is_secure_httponly_lax_and_shared_with_subdomains(prod_app):
    prod_app()
    settings = get_settings()
    assert settings.secure_cookies is True and settings.cookie_domain == ".example.com"
    cookie, _ = _login()
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Domain=.example.com", "Path=/", "Max-Age=2592000"):
        assert attr in cookie, (attr, cookie)


def test_prod_cookie_is_host_only_without_cookie_domain(prod_app):
    prod_app(COOKIE_DOMAIN="")  # an empty variable must not produce "Domain=" or a broken cookie
    assert get_settings().cookie_domain is None
    cookie, _ = _login()
    assert "Domain" not in cookie and "Secure" in cookie and "SameSite=lax" in cookie


def test_credentialed_request_from_the_frontend_origin(prod_app):
    app = prod_app()
    _, token = _login()
    client = TestClient(app, base_url="https://api.example.com")
    r = client.get(f"{API}/me", headers={"Origin": APP_ORIGIN, "Cookie": f"forliosa_session={token}"})
    assert r.status_code == 200 and r.json()["email"] == "prod@example.com"
    assert r.headers["access-control-allow-origin"] == APP_ORIGIN
    assert r.headers["access-control-allow-credentials"] == "true"
    assert "Origin" in r.headers.get("vary", "")


def test_preflight_allows_the_frontend_and_rejects_other_origins(prod_app):
    client = TestClient(prod_app(), base_url="https://api.example.com")
    ok = client.options(f"{API}/me/preferences", headers={
        "Origin": APP_ORIGIN, "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == APP_ORIGIN
    assert ok.headers["access-control-allow-credentials"] == "true"
    assert "PATCH" in ok.headers["access-control-allow-methods"]

    bad = client.options(f"{API}/me/preferences", headers={
        "Origin": "https://evil.example.net", "Access-Control-Request-Method": "PATCH"})
    assert bad.status_code == 400 and "access-control-allow-origin" not in bad.headers
    simple = client.get(f"{API}/health", headers={"Origin": "https://evil.example.net"})
    assert "access-control-allow-origin" not in simple.headers


def test_cors_origins_are_normalized(prod_app):
    app = prod_app(CORS_ORIGINS=" https://app.example.com/ ,https://staging.example.com,, ")
    assert get_settings().cors_origins == ["https://app.example.com", "https://staging.example.com"]
    client = TestClient(app)
    for origin in ("https://app.example.com", "https://staging.example.com"):
        r = client.options(f"{API}/transactions", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert r.headers["access-control-allow-origin"] == origin


def test_prod_rejects_wildcard_cors_and_default_secret(prod_app):
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        prod_app(CORS_ORIGINS="*")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        prod_app(SESSION_SECRET=None)


def test_prod_disables_dev_login_and_logout_clears_the_shared_cookie(prod_app):
    client = TestClient(prod_app(), base_url="https://api.example.com")
    r = client.post(f"{API}/auth/dev-login", json={"email": "a@example.com"})
    assert r.status_code == 404
    r = client.post(f"{API}/auth/logout", headers={"Origin": APP_ORIGIN})
    assert r.status_code == 204
    cleared = r.headers["set-cookie"]
    # The deletion must carry the same Domain/Secure attributes, or the browser keeps the cookie.
    assert "forliosa_session=" in cleared and "Max-Age=0" in cleared
    assert "Domain=.example.com" in cleared and "Secure" in cleared
