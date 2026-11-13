"""Sign in with Google: GET /auth/providers, /auth/google/start and /callback (Google HTTP mocked), the shared account
rules (one account for the same verified e-mail across Discord and Google), a state issued for one provider is not
accepted by the other, an optional provider that is half configured stays off without stopping the API, and a
public-posting suspension follows the e-mail to a new account made through the other provider."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from forliosa import models
from forliosa.config import get_settings
from forliosa.services import discord_oauth, google_oauth
from tests.api.discussions import GAP, error, post_topic, set_name
from tests.api.m5 import API, login
from tests.api.test_m5_auth import FRONTEND, FakeDiscord, all_rows_text, error_of
from tests.api.test_m5_auth import callback as discord_callback
from tests.api.test_m5_auth import start as discord_start


def gprofile(sub: str, email: str, name: str = "Papa") -> dict:
    return {"sub": sub, "name": name, "picture": None, "email": email, "email_verified": True}

CLIENT_SECRET = "google-client-secret-value-xyz"
ACCESS_TOKEN = "google-access-token-abc"
CODE = "google-auth-code-123"
REDIRECT = "http://testserver/api/v1/auth/google/callback"
ADMIN_URL = f"{API}/admin/discussions"


class FakeGoogle:
    """Answers the three Google endpoints the login uses; records what was asked."""

    def __init__(self, profile: dict | None = None):
        self.profile = profile or {"sub": "g-900", "name": "王 媽媽", "email": "Mama@Example.com",
                                   "picture": "https://lh3.googleusercontent.com/a/pic", "email_verified": True}
        self.token_status = 200
        self.me_status = 200
        self.revoked = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == google_oauth.TOKEN_URL:
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["authorization_code"] and form["code"] == [CODE]
            assert form["redirect_uri"] == [REDIRECT] and form["client_id"] == ["gid-123"]
            assert form["client_secret"] == [CLIENT_SECRET]
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": ACCESS_TOKEN, "token_type": "Bearer", "expires_in": 3599,
                                             "id_token": "id-token-should-not-be-kept"})
        if url == google_oauth.USERINFO_URL:
            assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
            return httpx.Response(self.me_status, json=self.profile)
        if url == google_oauth.REVOKE_URL:
            assert parse_qs(request.content.decode())["token"] == [ACCESS_TOKEN]
            self.revoked += 1
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture()
def google_app(monkeypatch, engine, market):
    def build(**extra: str | None):
        env = {"GOOGLE_CLIENT_ID": "gid-123", "GOOGLE_CLIENT_SECRET": CLIENT_SECRET, "GOOGLE_REDIRECT_URI": REDIRECT,
               "DISCORD_CLIENT_ID": "cid-123", "DISCORD_CLIENT_SECRET": "discord-secret",
               "DISCORD_REDIRECT_URI": "http://testserver/api/v1/auth/discord/callback",
               "FRONTEND_URL": FRONTEND, "ADMIN_EMAILS": "boss@forliosa.local", **extra}
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
    google_oauth.set_transport(None)
    discord_oauth.set_transport(None)


@pytest.fixture()
def fake():
    f = FakeGoogle()
    google_oauth.set_transport(httpx.MockTransport(f))
    return f


def start(client: TestClient, next_path: str | None = "/") -> tuple[str, httpx.Response]:
    r = client.get(f"{API}/auth/google/start", params={"next": next_path} if next_path else {}, follow_redirects=False)
    assert r.status_code == 302, r.text
    return parse_qs(urlparse(r.headers["location"]).query)["state"][0], r


def callback(client: TestClient, state: str, code: str = CODE, **extra) -> httpx.Response:
    return client.get(f"{API}/auth/google/callback", params={"code": code, "state": state, **extra},
                      follow_redirects=False)


def google_login(app, fake: FakeGoogle) -> TestClient:
    google_oauth.set_transport(httpx.MockTransport(fake))
    c = TestClient(app)
    state, _ = start(c)
    assert callback(c, state).status_code == 302
    assert c.get(f"{API}/me").status_code == 200
    return c


def discord_login(app, fake: FakeDiscord) -> TestClient:
    discord_oauth.set_transport(httpx.MockTransport(fake))
    c = TestClient(app)
    state, _ = discord_start(c, "/")
    assert discord_callback(c, state).status_code == 302
    return c


# -- providers and start -------------------------------------------------------------------------------------------
def test_providers_and_start_redirect(google_app):
    client = TestClient(google_app())
    assert client.get(f"{API}/auth/providers").json() == {"discord": True, "google": True, "dev_login": True}
    state, r = start(client, "/groups")
    url = urlparse(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    q = parse_qs(url.query)
    assert q["client_id"] == ["gid-123"] and q["scope"] == ["openid email profile"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == [REDIRECT] and q["prompt"] == ["select_account"] and len(state) >= 40
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("forliosa_oauth=") and "HttpOnly" in cookie and "Max-Age=600" in cookie
    assert CLIENT_SECRET not in r.headers["location"]


def test_start_without_google_redirects_with_oauth_disabled(app):
    assert TestClient(app).get(f"{API}/auth/providers").json()["google"] is False
    r = TestClient(app).get(f"{API}/auth/google/start", follow_redirects=False)
    assert r.status_code == 302 and "/login?error=oauth_disabled" in r.headers["location"]
    r = TestClient(app).get(f"{API}/auth/google/callback?code=x&state=y", follow_redirects=False)
    assert r.status_code == 302 and "/login?error=oauth_disabled" in r.headers["location"]


# -- callback ------------------------------------------------------------------------------------------------------
def test_login_creates_account_and_session_and_keeps_no_google_secret(google_app, fake, caplog):
    caplog.set_level(logging.DEBUG)
    client = TestClient(google_app())
    state, _ = start(client, "/invite/abc?x=1")
    r = callback(client, state)
    assert r.status_code == 302 and r.headers["location"] == f"{FRONTEND}/invite/abc?x=1"
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("forliosa_session=") for c in cookies)
    assert any(c.startswith("forliosa_oauth=") and "Max-Age=0" in c for c in cookies)  # one-time state
    me = client.get(f"{API}/me").json()
    assert me["email"] == "mama@example.com" and me["display_name"] == "王 媽媽"
    assert me["avatar_url"] == "https://lh3.googleusercontent.com/a/pic"
    assert fake.revoked == 1  # the Google token is revoked after one use
    stored = all_rows_text()
    server_logs = "\n".join(r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage())
    for secret in (ACCESS_TOKEN, "id-token-should-not-be-kept", CODE, CLIENT_SECRET, state):
        assert secret not in stored
        assert secret not in server_logs
    assert error_of(callback(client, state)) == "oauth_state"  # replay


def test_unverified_email_and_odd_profiles(google_app, fake):
    client = TestClient(google_app())
    fake.profile = {**fake.profile, "email_verified": False}
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_email_unverified"
    # a string "true" (older responses) counts as verified; a picture that is not https is dropped; no name → a default
    fake.profile = {"sub": "g-901", "email": "kid@example.com", "email_verified": "true", "picture": "http://x/y.png"}
    state, _ = start(client)
    assert callback(client, state).headers["location"] == f"{FRONTEND}/"
    me = client.get(f"{API}/me").json()
    assert me["display_name"] == "Google 使用者" and me["avatar_url"] is None


def test_google_errors_are_oauth_failed(google_app, fake):
    client = TestClient(google_app())
    fake.token_status = 400
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_failed"
    fake.token_status, fake.me_status = 200, 500
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_failed"
    google_oauth.set_transport(httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))))
    state, _ = start(client)
    assert error_of(callback(client, state)) == "oauth_failed"
    state, _ = start(client)
    assert error_of(callback(client, state, error="access_denied")) == "oauth_denied"


# -- one person, two providers -------------------------------------------------------------------------------------
def test_same_verified_email_is_one_account_across_discord_and_google(google_app, fake, engine):
    app = google_app()
    papa = FakeDiscord()  # papa@example.com
    first = discord_login(app, papa)
    uid = first.get(f"{API}/me").json()["id"]
    fake.profile = gprofile("g-777", "papa@example.com", "Papa G")
    second = google_login(app, fake)
    me = second.get(f"{API}/me").json()
    assert me["id"] == uid and me["display_name"] == "爸爸"  # the same account; its name is not overwritten
    with Session(engine) as db:
        providers = sorted(db.scalars(select(models.UserIdentity.provider).where(models.UserIdentity.user_id == uid)))
        assert providers == ["discord", "google"]
        assert db.scalar(select(func.count()).select_from(models.User)) == 1
    # a different Google account claiming the same e-mail cannot take the account over
    fake.profile = {**fake.profile, "sub": "g-778"}
    c = TestClient(app)
    state, _ = start(c)
    assert error_of(callback(c, state)) == "oauth_email_conflict"


def test_a_state_issued_for_one_provider_is_not_accepted_by_the_other(google_app, fake):
    app = google_app()
    discord_oauth.set_transport(httpx.MockTransport(FakeDiscord()))
    client = TestClient(app)
    state, _ = discord_start(client, "/")  # the cookie now holds a Discord state
    assert error_of(callback(client, state)) == "oauth_state"
    state, _ = start(client)  # and the other way round
    assert error_of(discord_callback(client, state)) == "oauth_state"


# -- configuration -------------------------------------------------------------------------------------------------
PROD = {"FORLIOSA_ENV": "prod", "SESSION_SECRET": "x" * 40, "CORS_ORIGINS": "https://app.example.com",
        "FRONTEND_URL": "https://app.example.com",
        "DISCORD_REDIRECT_URI": "https://api.example.com/api/v1/auth/discord/callback"}


@pytest.mark.parametrize("extra", [
    {"GOOGLE_CLIENT_SECRET": None},
    {"GOOGLE_CLIENT_ID": "  "},
    {"GOOGLE_REDIRECT_URI": None},
    {**PROD, "GOOGLE_REDIRECT_URI": "http://api.example.com/api/v1/auth/google/callback"},  # not https in production
])
def test_half_configured_google_is_off_and_does_not_stop_the_api(google_app, extra, caplog):
    caplog.set_level(logging.WARNING)
    app = google_app(**extra)  # starts: Google is optional
    base = "https://testserver" if extra.get("FORLIOSA_ENV") == "prod" else "http://testserver"
    providers = TestClient(app, base_url=base).get(f"{API}/auth/providers").json()
    assert providers["google"] is False and providers["discord"] is True
    warning = "\n".join(r.getMessage() for r in caplog.records)
    assert "Google login is off" in warning and CLIENT_SECRET not in warning


def test_prod_with_https_google_is_on(google_app):
    app = google_app(**PROD, GOOGLE_REDIRECT_URI="https://api.example.com/api/v1/auth/google/callback")
    assert TestClient(app, base_url="https://testserver").get(f"{API}/auth/providers").json()["google"] is True


# -- a suspension follows the person across providers ------------------------------------------------------------------
def test_a_suspension_follows_the_email_to_an_account_made_through_the_other_provider(google_app, fake, engine, clock):
    app = google_app()
    papa = FakeDiscord()  # the account has only a Discord login
    user = discord_login(app, papa)
    admin = login(app, "boss@forliosa.local", "站長本人")
    set_name(user, "洗版的人")
    topic = post_topic(user, clock)
    s = admin.post(f"{ADMIN_URL}/suspensions", json={"target": f"topic:{topic['id']}", "days": 7, "reason": "洗版"})
    assert s.status_code == 201, s.text
    until = s.json()["until"]
    # the person sees the reason, not only until when
    me = user.get(f"{API}/me").json()
    assert me["public_posting_suspended_until"] == until and me["public_posting_suspended_reason"] == "洗版"
    clock.tick(seconds=GAP)
    refused = user.post(f"{API}/discussions/topics", json={"scope": "public", "title": "標題", "body": "內文"})
    assert refused.status_code == 403 and error(refused) == "posting_suspended"
    err = refused.json()["error"]
    assert err["until"] == until and err["reason"] == "洗版"

    assert user.request("DELETE", f"{API}/me", json={"confirm": "刪除我的帳號"}).status_code == 204
    with Session(engine) as db:
        rows = db.scalars(select(models.DiscussionSuspensionCarryover)).all()
        assert len(rows) == 2  # the Discord login and the e-mail
        stored = json.dumps([[r.identity_hash, r.reason] for r in rows], ensure_ascii=False)
        assert "papa@example.com" not in stored and papa.profile["id"] not in stored  # keyed hashes only

    # back through Google with the same e-mail: a new account, still suspended, with the reason
    fake.profile = gprofile("g-555", "papa@example.com")
    again = google_login(app, fake)
    me = again.get(f"{API}/me").json()
    assert me["public_posting_suspended_until"] == until and me["public_posting_suspended_reason"] == "洗版"
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(models.DiscussionSuspensionCarryover)) == 1  # the Discord one
    # someone else through Google is not affected
    fake.profile = gprofile("g-556", "mama@example.com", "Mama")
    other = google_login(app, fake)
    me = other.get(f"{API}/me").json()
    assert me["public_posting_suspended_until"] is None and me["public_posting_suspended_reason"] is None
