"""M5 login: GET /auth/providers, Discord OAuth start/callback (Discord HTTP mocked), PATCH /me, CSRF origin check,
production startup checks."""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from forliosa.config import get_settings
from forliosa.crypto import b64url, sign
from forliosa.db import session_factory
from forliosa.services import discord_oauth
from tests.api.m5 import API

CLIENT_SECRET = "discord-client-secret-value-xyz"
ACCESS_TOKEN = "discord-access-token-abc"
CODE = "discord-auth-code-123"
FRONTEND = "http://localhost:5173"


class FakeDiscord:
    """Answers the three Discord endpoints the login uses; records what was asked."""

    def __init__(self, profile: dict | None = None):
        self.profile = profile or {"id": "111", "username": "papa", "global_name": "爸爸", "avatar": "abc123",
                                   "email": "Papa@Example.com", "verified": True}
        self.token_status = 200
        self.me_status = 200
        self.requests: list[httpx.Request] = []
        self.revoked = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == discord_oauth.TOKEN_URL:
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"] and form["code"] == [CODE]
            assert form["redirect_uri"] == ["http://testserver/api/v1/auth/discord/callback"]
            assert request.headers["authorization"].startswith("Basic ")
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": ACCESS_TOKEN, "token_type": "Bearer",
                                             "refresh_token": "refresh-should-not-be-kept", "expires_in": 604800})
        if url == discord_oauth.ME_URL:
            assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
            return httpx.Response(self.me_status, json=self.profile)
        if url == discord_oauth.REVOKE_URL:
            self.revoked += 1
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture()
def discord_app(monkeypatch, engine, market):
    def build(**extra: str | None):
        env = {"DISCORD_CLIENT_ID": "cid-123", "DISCORD_CLIENT_SECRET": CLIENT_SECRET,
               "DISCORD_REDIRECT_URI": "http://testserver/api/v1/auth/discord/callback", "FRONTEND_URL": FRONTEND,
               **extra}
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        from forliosa.api.app import create_app

        return create_app()

    yield build
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture()
def fake():
    f = FakeDiscord()
    discord_oauth.set_transport(httpx.MockTransport(f))
    return f


def start(client: TestClient, next_path: str | None = "/invite/abc") -> tuple[str, httpx.Response]:
    params = {"next": next_path} if next_path is not None else {}
    r = client.get(f"{API}/auth/discord/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    return q["state"][0], r


def callback(client: TestClient, state: str, code: str = CODE, **extra) -> httpx.Response:
    return client.get(f"{API}/auth/discord/callback", params={"code": code, "state": state, **extra},
                      follow_redirects=False)


def error_of(r: httpx.Response) -> str | None:
    loc = r.headers["location"]
    assert loc.startswith(f"{FRONTEND}/login?error="), loc
    return parse_qs(urlparse(loc).query)["error"][0]


def all_rows_text() -> str:
    with session_factory()() as db:
        tables = [r[0] for r in db.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
        return json.dumps([[list(map(str, row)) for row in db.execute(text(f'SELECT * FROM "{t}"'))] for t in tables],
                          ensure_ascii=False)


# -- providers -----------------------------------------------------------------------------------------------
def test_providers_without_discord(app):
    r = TestClient(app).get(f"{API}/auth/providers")
    assert r.status_code == 200 and r.json() == {"discord": False, "dev_login": True}


def test_providers_with_discord_and_start_redirect(discord_app):
    client = TestClient(discord_app())
    assert client.get(f"{API}/auth/providers").json() == {"discord": True, "dev_login": True}
    state, r = start(client)
    url = urlparse(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://discord.com/oauth2/authorize"
    q = parse_qs(url.query)
    assert q["client_id"] == ["cid-123"] and q["scope"] == ["identify email"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://testserver/api/v1/auth/discord/callback"]
    assert "prompt" not in q and len(state) >= 40
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("forliosa_oauth=")  # development: no __Host- prefix, no Secure
    for attr in ("HttpOnly", "Max-Age=600", "Path=/", "SameSite=lax"):
        assert attr in cookie, (attr, cookie)
    assert "Secure" not in cookie and "Domain" not in cookie
    assert CLIENT_SECRET not in r.headers["location"]


def test_start_without_discord_redirects_with_oauth_disabled(app):
    r = TestClient(app).get(f"{API}/auth/discord/start", follow_redirects=False)
    assert r.status_code == 302 and "/login?error=oauth_disabled" in r.headers["location"]
    r = TestClient(app).get(f"{API}/auth/discord/callback?code=x&state=y", follow_redirects=False)
    assert r.status_code == 302 and "/login?error=oauth_disabled" in r.headers["location"]


def test_secure_state_cookie_uses_host_prefix(discord_app):
    app = discord_app(COOKIE_SECURE="true", COOKIE_DOMAIN=".example.com")
    client = TestClient(app, base_url="https://testserver")
    _, r = start(client)
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("__Host-forliosa_oauth=")
    for attr in ("Secure", "HttpOnly", "Path=/", "SameSite=lax", "Max-Age=600"):
        assert attr in cookie
    assert "Domain" not in cookie  # __Host- forbids Domain even when COOKIE_DOMAIN is set


# -- callback: success, next, linking -----------------------------------------------------------------------------
def test_login_creates_account_and_session(discord_app, fake, caplog):
    caplog.set_level(logging.DEBUG)
    client = TestClient(discord_app())
    state, _ = start(client, "/invite/abc?x=1")
    r = callback(client, state)
    assert r.status_code == 302 and r.headers["location"] == f"{FRONTEND}/invite/abc?x=1"
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("forliosa_session=") for c in cookies)
    assert any(c.startswith("forliosa_oauth=") and "Max-Age=0" in c for c in cookies)  # one-time state
    me = client.get(f"{API}/me").json()
    assert me["email"] == "papa@example.com" and me["display_name"] == "爸爸"
    assert me["avatar_url"] == "https://cdn.discordapp.com/avatars/111/abc123.png?size=128"
    assert fake.revoked == 1  # the Discord token is revoked after one use
    stored = all_rows_text()
    server_logs = "\n".join(r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage())
    for secret in (ACCESS_TOKEN, "refresh-should-not-be-kept", CODE, CLIENT_SECRET, state):
        assert secret not in stored
        assert secret not in server_logs
    # The state is one-time: replaying the callback fails.
    assert error_of(callback(client, state)) == "oauth_state"


@pytest.mark.parametrize(("raw", "expected"), [
    ("/groups/grp_1", "/groups/grp_1"),
    ("//evil.com", "/"),
    ("/\\evil.com", "/"),
    ("https://evil.com", "/"),
    ("evil", "/"),
    ("/a b", "/"),
    ("/" + "a" * 512, "/"),
    (None, "/"),
])
def test_next_is_validated(discord_app, fake, raw, expected):
    client = TestClient(discord_app())
    state, _ = start(client, raw)
    r = callback(client, state)
    assert r.headers["location"] == f"{FRONTEND}{expected}"


def test_global_name_falls_back_to_username(discord_app, fake):
    fake.profile = {**fake.profile, "global_name": None, "avatar": None, "username": "x" * 40}
    client = TestClient(discord_app())
    state, _ = start(client)
    callback(client, state)
    me = client.get(f"{API}/me").json()
    assert me["display_name"] == "x" * 30 and me["avatar_url"] is None


def test_discord_global_name_becomes_one_line(discord_app, fake):
    fake.profile = {**fake.profile, "global_name": "明\n[群組頁](https://ev.il/g)\u202e\u200b"}
    client = TestClient(discord_app())
    state, _ = start(client)
    callback(client, state)
    assert client.get(f"{API}/me").json()["display_name"] == "明 [群組頁](https://ev.il/g)"  # escaped when pushed
    assert discord_oauth.DiscordProfile("1", "user", "\u200b\n", None, None, True).display_name == "Discord 使用者"


def test_links_existing_account_by_verified_email(discord_app, fake):
    app = discord_app()
    dev = TestClient(app)
    dev.post(f"{API}/auth/dev-login", json={"email": "papa@example.com", "display_name": "老爸"})
    existing = dev.get(f"{API}/me").json()["id"]
    client = TestClient(app)
    state, _ = start(client)
    callback(client, state)
    me = client.get(f"{API}/me").json()
    assert me["id"] == existing and me["display_name"] == "老爸"  # the name is kept; the avatar is Discord's
    assert me["avatar_url"].startswith("https://cdn.discordapp.com/")


def test_unverified_email_cannot_create_or_link(discord_app, fake):
    fake.profile = {**fake.profile, "verified": False}
    client = TestClient(discord_app())
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_email_unverified"
    assert client.get(f"{API}/me").status_code == 401
    fake.profile = {**fake.profile, "verified": True, "email": None}
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_email_unverified"


def test_email_linked_to_another_discord_id_conflicts(discord_app, fake):
    app = discord_app()
    first = TestClient(app)
    state, _ = start(first)
    callback(first, state)
    fake.profile = {**fake.profile, "id": "222"}  # another Discord account with the same e-mail
    second = TestClient(app)
    state, _ = start(second)
    assert error_of(callback(second, state)) == "oauth_email_conflict"


def test_linked_account_logs_in_and_refreshes_email_and_avatar(discord_app, fake):
    app = discord_app()
    c = TestClient(app)
    state, _ = start(c)
    callback(c, state)
    uid = c.get(f"{API}/me").json()["id"]
    fake.profile = {**fake.profile, "email": "new@example.com", "avatar": "def456", "verified": False}
    c2 = TestClient(app)
    state, _ = start(c2)
    callback(c2, state)
    me = c2.get(f"{API}/me").json()
    assert me["id"] == uid and me["avatar_url"].endswith("/def456.png?size=128")
    assert me["email"] == "papa@example.com"  # an unverified e-mail is not taken over
    fake.profile = {**fake.profile, "verified": True}
    c3 = TestClient(app)
    state, _ = start(c3)
    callback(c3, state)
    assert c3.get(f"{API}/me").json()["email"] == "new@example.com"


def test_login_rotates_the_session(discord_app, fake):
    app = discord_app()
    client = TestClient(app)
    client.post(f"{API}/auth/dev-login", json={"email": "someone@example.com"})
    old = client.cookies.get("forliosa_session")
    state, _ = start(client)
    callback(client, state)
    new = client.cookies.get("forliosa_session")
    assert new and new != old
    stale = TestClient(app)
    stale.cookies.set("forliosa_session", old)
    assert stale.get(f"{API}/me").status_code == 401  # the old session id no longer exists


# -- callback failures ---------------------------------------------------------------------------------------------
def test_denied_and_state_failures(discord_app, fake):
    app = discord_app()
    client = TestClient(app)
    state, _ = start(client)
    r = client.get(f"{API}/auth/discord/callback", params={"error": "access_denied", "state": state},
                   follow_redirects=False)
    assert error_of(r) == "oauth_denied"
    assert any("Max-Age=0" in c for c in r.headers.get_list("set-cookie"))
    # mismatching state
    state, _ = start(client)
    assert error_of(callback(client, state + "x")) == "oauth_state"
    # no cookie at all (e.g. another browser)
    state, _ = start(client)
    assert error_of(callback(TestClient(app), state)) == "oauth_state"
    # tampered cookie (sent by a fresh browser)
    state, _ = start(client)
    _payload, sig = client.cookies.get("forliosa_oauth").split(".")
    forged = b64url(json.dumps({"s": state, "n": "//evil.com", "e": int(time.time()) + 600}).encode())
    r = TestClient(app).get(f"{API}/auth/discord/callback", params={"code": CODE, "state": state},
                            headers={"Cookie": f"forliosa_oauth={forged}.{sig}"}, follow_redirects=False)
    assert error_of(r) == "oauth_state"
    # expired (correctly signed)
    expired = b64url(json.dumps({"s": "abc", "n": "/", "e": int(time.time()) - 1}).encode())
    good_sig = b64url(sign("oauth-state", expired.encode()))
    r = TestClient(app).get(f"{API}/auth/discord/callback", params={"code": CODE, "state": "abc"},
                            headers={"Cookie": f"forliosa_oauth={expired}.{good_sig}"}, follow_redirects=False)
    assert error_of(r) == "oauth_state"
    # the same, not expired: accepted (the signature check above is what failed)
    fresh = b64url(json.dumps({"s": "abc", "n": "/x", "e": int(time.time()) + 60}).encode())
    good_sig = b64url(sign("oauth-state", fresh.encode()))
    assert fake.requests == []  # nothing reached Discord so far
    r = TestClient(app).get(f"{API}/auth/discord/callback", params={"code": CODE, "state": "abc"},
                            headers={"Cookie": f"forliosa_oauth={fresh}.{good_sig}"}, follow_redirects=False)
    assert r.headers["location"] == f"{FRONTEND}/x"


def test_discord_errors_are_oauth_failed(discord_app, fake, caplog):
    client = TestClient(discord_app())
    fake.token_status = 400
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_failed"
    fake.token_status, fake.me_status = 200, 401
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_failed"
    assert fake.revoked == 1
    discord_oauth.set_transport(httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))))
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_failed"
    assert client.get(f"{API}/me").status_code == 401
    assert CLIENT_SECRET not in caplog.text and CODE not in caplog.text


def test_identity_is_unique_per_user(discord_app, fake):
    app = discord_app()
    c = TestClient(app)
    state, _ = start(c)
    callback(c, state)
    from forliosa.models import UserIdentity

    with session_factory()() as db:
        rows = list(db.scalars(select(UserIdentity)))
    assert [(r.provider, r.subject, r.email) for r in rows] == [("discord", "111", "papa@example.com")]


# -- profile ------------------------------------------------------------------------------------------------------
def test_patch_me_display_name(client):
    r = client.patch(f"{API}/me", json={"display_name": "  小明  "})
    assert r.status_code == 200 and r.json()["display_name"] == "小明"
    assert client.get(f"{API}/me").json()["display_name"] == "小明"
    assert "avatar_url" in client.get(f"{API}/me").json()
    for bad in ("", "   ", "x" * 31, "明\n[群組頁](https://ev.il/g)", "小\t明", "小\u202e明", "小\u200b明", "a\u2028b"):
        r = client.patch(f"{API}/me", json={"display_name": bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    family = "\U0001F468\u200d\U0001F469\u200d\U0001F467 王家"  # emoji joined by ZERO WIDTH JOINER are fine
    assert client.patch(f"{API}/me", json={"display_name": family}).json()["display_name"] == family
    r = client.post(f"{API}/auth/dev-login", json={"email": "z@x.tw", "display_name": "a\nb"})
    assert r.status_code == 422
    assert client.patch(f"{API}/me", json={"display_name": "a", "email": "x@y.z"}).status_code == 422


# -- CSRF and CORS -----------------------------------------------------------------------------------------------
def test_origin_check_for_writes(client):
    r = client.post(f"{API}/accounts", json={"name": "a"}, headers={"Origin": "https://evil.example.net"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    r = client.patch(f"{API}/me", json={"display_name": "x"}, headers={"Origin": "null"})
    assert r.status_code == 403
    assert client.post(f"{API}/accounts", json={"name": "a"}, headers={"Origin": "http://localhost:5173"}
                       ).status_code == 201
    assert client.post(f"{API}/accounts", json={"name": "b"}).status_code == 201  # no Origin (not a browser)
    assert client.get(f"{API}/accounts", headers={"Origin": "https://evil.example.net"}).status_code == 200


def test_cors_allows_the_view_as_header(app):
    r = TestClient(app).options(f"{API}/portfolio/summary", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "x-forliosa-view-as"})
    assert r.status_code == 200
    assert "x-forliosa-view-as" in r.headers["access-control-allow-headers"].lower()


# -- production checks --------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("env", "message"), [
    ({"FRONTEND_URL": None}, "FRONTEND_URL must be set"),
    ({"FRONTEND_URL": "https://other.example.com"}, "FRONTEND_URL must be one of CORS_ORIGINS"),
    ({"FRONTEND_URL": "http://app.example.com", "CORS_ORIGINS": "http://app.example.com"}, "https"),
    ({"CORS_ORIGINS": "https://app.example.com,http://staging.example.com"}, "https"),
    ({"DISCORD_CLIENT_ID": "cid", "DISCORD_CLIENT_SECRET": None, "DISCORD_REDIRECT_URI": None}, "set together"),
    ({"DISCORD_CLIENT_ID": "cid", "DISCORD_CLIENT_SECRET": "s", "DISCORD_REDIRECT_URI": "http://api.example.com/cb"},
     "DISCORD_REDIRECT_URI must be https"),
])
def test_prod_startup_checks(discord_app, env, message):
    base = {"FORLIOSA_ENV": "prod", "SESSION_SECRET": "s" * 48, "CORS_ORIGINS": "https://app.example.com",
            "FRONTEND_URL": "https://app.example.com", "DISCORD_CLIENT_ID": None, "DISCORD_CLIENT_SECRET": None,
            "DISCORD_REDIRECT_URI": None}
    with pytest.raises(RuntimeError, match=message) as exc:
        discord_app(**{**base, **env})
    assert "s" * 48 not in str(exc.value)


def test_prod_starts_with_discord_configured(discord_app):
    app = discord_app(FORLIOSA_ENV="prod", SESSION_SECRET="s" * 48, CORS_ORIGINS="https://app.example.com",
                      FRONTEND_URL="https://app.example.com/", DISCORD_REDIRECT_URI="https://api.example.com/api/v1/"
                      "auth/discord/callback")
    client = TestClient(app, base_url="https://api.example.com")
    assert client.get(f"{API}/auth/providers").json() == {"discord": True, "dev_login": False}
    _, r = start(client)
    assert r.headers["set-cookie"].startswith("__Host-forliosa_oauth=")
    assert repr(get_settings().discord_client_secret) == "SecretStr('**********')"


def test_access_log_redacts_codes_and_invite_tokens():
    from forliosa.logredact import RedactingFilter, redact_url

    assert redact_url("/api/v1/auth/discord/callback?code=abc&state=def") == \
        "/api/v1/auth/discord/callback?code=***&state=***"
    assert redact_url("/api/v1/invites/tok_123/accept") == "/api/v1/invites/***/accept"
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4", "GET", "/api/v1/invites/secret-token", "1.1", 200), None)
    RedactingFilter().filter(rec)
    assert "secret-token" not in rec.getMessage()
