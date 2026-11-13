"""Fixtures shared by the API tests of the discussion threads."""

from __future__ import annotations

import pytest

from forliosa.config import get_settings
from forliosa.services import discussions as discussion_service
from tests.api.discussions import Clock
from tests.api.m5 import login

ADMIN_EMAIL = "boss@forliosa.local"


@pytest.fixture()
def clock():
    """The discussion service's clock, moved by the test (no sleeping)."""
    c = Clock()
    discussion_service.set_clock(c)
    yield c
    discussion_service.set_clock(None)


@pytest.fixture()
def admin(app, monkeypatch):
    """A signed-in site admin (``ADMIN_EMAILS``)."""
    monkeypatch.setattr(get_settings(), "admin_emails", [ADMIN_EMAIL])
    return login(app, ADMIN_EMAIL, "站長本人")
