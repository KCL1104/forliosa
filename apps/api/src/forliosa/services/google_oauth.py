"""Sign in with Google (OpenID Connect authorization-code flow; docs/api-contract.md 「登入（Google OAuth）」).

The same shape as ``discord_oauth`` and the same account rules (``discord_oauth.sign_in``): the signed ``state`` cookie,
the provider's access token used once to read the profile and then revoked (best effort), nothing from Google stored
except the account id (``sub``), the e-mail as last reported and the avatar URL. Creating or linking an account needs an
e-mail Google reports as verified.

Endpoints are the ones in Google's discovery document (https://accounts.google.com/.well-known/openid-configuration).
Tests replace the HTTP transport (:func:`set_transport`); no test reaches Google.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from forliosa.config import Settings
from forliosa.services.discord_oauth import DISPLAY_NAME_MAX, OAuthError
from forliosa.textsafe import one_line

log = logging.getLogger("forliosa.oauth")

PROVIDER = "google"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPE = "openid email profile"
AVATAR_URL_MAX = 500

_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> None:
    """Tests: route every Google request through ``transport`` (e.g. ``httpx.MockTransport``)."""
    global _transport
    _transport = transport


def authorize_url(settings: Settings, state: str) -> str:
    assert settings.google_client_id and settings.google_redirect_uri
    return AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code", "client_id": settings.google_client_id, "scope": SCOPE, "state": state,
        "redirect_uri": settings.google_redirect_uri,
        # Always show Google's account chooser: on a shared computer the next person can pick their own account.
        "prompt": "select_account",
    })


@dataclass(frozen=True)
class GoogleProfile:
    id: str  # Google's ``sub``: stable per Google account
    name: str | None
    picture: str | None
    email: str | None
    verified: bool

    @property
    def avatar_url(self) -> str | None:
        """Google's profile picture URL, only when it is a plain https URL of a sane length."""
        p = self.picture
        return p if p and p.startswith("https://") and len(p) <= AVATAR_URL_MAX and " " not in p else None

    @property
    def display_name(self) -> str:
        """The Google account's name as one line (``textsafe.one_line``), at most 30 characters."""
        name = one_line(self.name or "")
        return name[:DISPLAY_NAME_MAX].strip() or "Google 使用者"


def _client() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False, transport=_transport,
                        headers={"User-Agent": "Forliosa (oauth)"})


def fetch_profile(settings: Settings, code: str) -> GoogleProfile:
    """Exchange ``code`` for a token, read the profile, revoke the token. Any failure → ``oauth_failed``."""
    assert settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri
    try:
        with _client() as http:
            tok = http.post(TOKEN_URL, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": settings.google_redirect_uri,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value()})
            if tok.status_code != 200:
                log.warning("google token exchange failed: HTTP %s", tok.status_code)
                raise OAuthError("oauth_failed")
            access = tok.json().get("access_token")
            if not isinstance(access, str) or not access:
                log.warning("google token exchange returned no access token")
                raise OAuthError("oauth_failed")
            try:
                me = http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
            finally:
                try:  # the token is not needed any more: revoke it (best effort)
                    http.post(REVOKE_URL, data={"token": access})
                except httpx.HTTPError:
                    log.info("google token revoke failed")
            if me.status_code != 200:
                log.warning("google userinfo failed: HTTP %s", me.status_code)
                raise OAuthError("oauth_failed")
            data = me.json()
    except httpx.HTTPError as exc:
        log.warning("google request failed: %s", type(exc).__name__)
        raise OAuthError("oauth_failed") from None
    except ValueError:
        log.warning("google returned invalid JSON")
        raise OAuthError("oauth_failed") from None
    if not isinstance(data, dict) or not data.get("sub"):
        raise OAuthError("oauth_failed")
    email = data.get("email")
    name, picture = data.get("name"), data.get("picture")
    return GoogleProfile(id=str(data["sub"]), name=name if isinstance(name, str) and name.strip() else None,
                         picture=picture if isinstance(picture, str) else None,
                         email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
                         # Google sends a boolean; some older responses send the string "true"
                         verified=data.get("email_verified") in (True, "true"))
