"""Sign in with Discord (docs/api-contract.md 「分享（M5）」→「登入（Discord OAuth）」).

* ``state``: a random value + ``next``, HMAC-signed with a key derived from ``SESSION_SECRET``, kept 10 minutes in a
  cookie (``__Host-forliosa_oauth`` with secure cookies: ``Secure; HttpOnly; SameSite=Lax; Path=/``; ``forliosa_oauth``
  without ``Secure`` in development). The callback compares in constant time and always deletes the cookie.
* Discord's access token is used once to read ``/users/@me`` and then revoked (best effort); no Discord token is ever
  stored or logged, nor is the client secret, the authorization code or the state.
* Account mapping: by Discord id first. Otherwise an existing account that has **no** Discord id yet is linked by a
  **verified** e-mail; that e-mail already linked to another Discord id → ``oauth_email_conflict``. Otherwise a new
  account (display name = Discord global name, else username, as one line without control characters). Creating or
  linking requires a verified e-mail (``oauth_email_unverified``). Every login refreshes the e-mail (verified, not
  used by another account) and avatar.

Tests replace the HTTP transport (:func:`set_transport`); no test reaches discord.com.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from forliosa.config import Settings
from forliosa.crypto import b64url, b64url_decode, random_token, sign, verify
from forliosa.ids import new_id
from forliosa.models import User, UserIdentity
from forliosa.services.ledger_io import DEFAULT_PREFERENCES
from forliosa.textsafe import one_line
from forliosa.timeutil import now_utc

log = logging.getLogger("forliosa.oauth")

PROVIDER = "discord"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
API = "https://discord.com/api/v10"
TOKEN_URL = f"{API}/oauth2/token"
REVOKE_URL = f"{API}/oauth2/token/revoke"
ME_URL = f"{API}/users/@me"
CDN = "https://cdn.discordapp.com"
SCOPE = "identify email"
STATE_TTL_SECONDS = 600
NEXT_RE = re.compile(r"^/(?![/\\])[\x21-\x7E]{0,511}$")
DISPLAY_NAME_MAX = 30

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: route every Discord request through ``transport`` (e.g. ``httpx.MockTransport``)."""
    global _transport
    _transport = transport


class OAuthError(Exception):
    """A login failure; ``code`` is sent to the frontend as ``/login?error=<code>``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# -- next and state ------------------------------------------------------------------------------------------
def safe_next(value: str | None) -> str:
    """``next`` as received (already URL-decoded once by the framework) when it is a same-site path, else ``/``."""
    return value if value and NEXT_RE.match(value) else "/"


def state_cookie_name(settings: Settings) -> str:
    return "__Host-forliosa_oauth" if settings.secure_cookies else "forliosa_oauth"


def make_state(next_path: str) -> tuple[str, str]:
    """(state for Discord, signed cookie value)."""
    nonce = random_token(32)
    payload = b64url(json.dumps({"s": nonce, "n": next_path, "e": int(time.time()) + STATE_TTL_SECONDS},
                                separators=(",", ":")).encode())
    return nonce, f"{payload}.{b64url(sign('oauth-state', payload.encode()))}"


def check_state(cookie: str | None, state: str | None) -> str:
    """The ``next`` path of a valid state; raises ``oauth_state`` otherwise."""
    if not cookie or not state or "." not in cookie:
        raise OAuthError("oauth_state")
    payload, _, sig = cookie.partition(".")
    try:
        ok = verify("oauth-state", payload.encode(), b64url_decode(sig))
        data = json.loads(b64url_decode(payload)) if ok else None
    except (ValueError, TypeError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("s"), str) or not isinstance(data.get("e"), int):
        raise OAuthError("oauth_state")
    if not hmac.compare_digest(data["s"].encode(), state.encode()) or data["e"] < int(time.time()):
        raise OAuthError("oauth_state")
    return safe_next(data.get("n") if isinstance(data.get("n"), str) else None)


def authorize_url(settings: Settings, state: str) -> str:
    assert settings.discord_client_id and settings.discord_redirect_uri
    return AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code", "client_id": settings.discord_client_id, "scope": SCOPE, "state": state,
        "redirect_uri": settings.discord_redirect_uri,
    })


# -- Discord HTTP -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DiscordProfile:
    id: str
    username: str
    global_name: str | None
    avatar: str | None
    email: str | None
    verified: bool

    @property
    def avatar_url(self) -> str | None:
        return f"{CDN}/avatars/{self.id}/{self.avatar}.png?size=128" if self.avatar else None

    @property
    def display_name(self) -> str:
        """Discord's global name (else the username) as one line (``textsafe.one_line``: no line breaks, control or
        invisible format characters), at most 30 characters."""
        name = one_line(self.global_name or self.username or "")
        return name[:DISPLAY_NAME_MAX].strip() or "Discord 使用者"


def _client() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False, transport=_transport,
                        headers={"User-Agent": "Forliosa (oauth)"})


def fetch_profile(settings: Settings, code: str) -> DiscordProfile:
    """Exchange ``code`` for a token, read the profile, revoke the token. Any failure → ``oauth_failed``."""
    assert settings.discord_client_id and settings.discord_client_secret and settings.discord_redirect_uri
    auth = (settings.discord_client_id, settings.discord_client_secret.get_secret_value())
    try:
        with _client() as http:
            tok = http.post(TOKEN_URL, auth=auth, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": settings.discord_redirect_uri})
            if tok.status_code != 200:
                log.warning("discord token exchange failed: HTTP %s", tok.status_code)
                raise OAuthError("oauth_failed")
            access = tok.json().get("access_token")
            if not isinstance(access, str) or not access:
                log.warning("discord token exchange returned no access token")
                raise OAuthError("oauth_failed")
            try:
                me = http.get(ME_URL, headers={"Authorization": f"Bearer {access}"})
            finally:
                try:  # the token is not needed any more: revoke it (best effort)
                    http.post(REVOKE_URL, auth=auth, data={"token": access, "token_type_hint": "access_token"})
                except httpx.HTTPError:
                    log.info("discord token revoke failed")
            if me.status_code != 200:
                log.warning("discord /users/@me failed: HTTP %s", me.status_code)
                raise OAuthError("oauth_failed")
            data = me.json()
    except httpx.HTTPError as exc:
        log.warning("discord request failed: %s", type(exc).__name__)
        raise OAuthError("oauth_failed") from None
    except ValueError:
        log.warning("discord returned invalid JSON")
        raise OAuthError("oauth_failed") from None
    if not isinstance(data, dict) or not data.get("id"):
        raise OAuthError("oauth_failed")
    email = data.get("email")
    return DiscordProfile(id=str(data["id"]), username=str(data.get("username") or ""),
                          global_name=data.get("global_name") or None, avatar=data.get("avatar") or None,
                          email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
                          verified=data.get("verified") is True)


# -- account mapping -------------------------------------------------------------------------------------------------
def sign_in(db: Session, profile: DiscordProfile) -> User:
    """The account for this Discord profile (found, linked or created); commits."""
    now = now_utc()
    ident = db.scalar(select(UserIdentity).where(UserIdentity.provider == PROVIDER,
                                                 UserIdentity.subject == profile.id))
    if ident is not None:
        user = db.get(User, ident.user_id)
        if user is None:  # pragma: no cover - identities are deleted with the user
            raise OAuthError("oauth_failed")
        ident.email = profile.email
        ident.last_login_at = now
        if profile.verified and profile.email and profile.email != user.email:
            taken = db.scalar(select(User.id).where(User.email == profile.email, User.id != user.id))
            if taken is None:
                user.email = profile.email
        user.avatar_url = profile.avatar_url
        db.commit()
        return user

    if not profile.email or not profile.verified:
        raise OAuthError("oauth_email_unverified")
    user = db.scalar(select(User).where(User.email == profile.email))
    if user is not None:
        linked = db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id,
                                                      UserIdentity.provider == PROVIDER))
        if linked is not None:
            raise OAuthError("oauth_email_conflict")
        user.avatar_url = profile.avatar_url
    else:
        user = User(id=new_id("usr"), email=profile.email, display_name=profile.display_name,
                    avatar_url=profile.avatar_url, preferences=dict(DEFAULT_PREFERENCES), created_at=now)
        db.add(user)
        db.flush()
    db.add(UserIdentity(id=new_id("uid"), user_id=user.id, provider=PROVIDER, subject=profile.id,
                        email=profile.email, created_at=now, last_login_at=now))
    db.commit()
    return user
