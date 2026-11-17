"""The API's router: a plain sync endpoint gives its database connection back before FastAPI validates its response.

FastAPI runs a sync endpoint in one threadpool call and the validation of what it returned (``response_model``) in
another; the request's session keeps the connection of its open read transaction until ``get_db`` closes it after the
response is sent. Between the two calls the request waited for one of anyio's 40 tokens while holding a pooled
connection — the same wait as between the sign-in dependency and the endpoint (``api.deps``), and under a burst of more
requests than tokens plus connections the two pools waited for each other until the pool timed out (2026-11-17; a
burst of 500 requests did it with the sign-in dependencies fixed alone). Every route of the API is therefore added by
:class:`Router`, which wraps a plain sync endpoint so that, when it returns, a session it was given ends its read-only
transaction (``forliosa.db.release_connection``; a session with uncommitted writes is left to ``close()`` as before).
What the response's validation still reads (a lazy relationship) takes a connection inside that call, which holds a
token, and gives it back with ``close()``, which FastAPI runs without one.

Async endpoints and generator endpoints are added unchanged (they hold no token between calls / stream themselves).
``tests/test_db_release.py`` checks that every route of the app is a wrapped one.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from sqlalchemy.orm import Session

from forliosa.db import release_connection

RELEASES = "__forliosa_releases__"


def plain_sync(endpoint: Callable[..., Any]) -> bool:
    fn = inspect.unwrap(endpoint)
    return inspect.isfunction(fn) and not (inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn)
                                           or inspect.isasyncgenfunction(fn))


def releasing(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """``endpoint``, giving back the connection of every session it was given when it returns (not when it raises:
    the error handlers hold no token, and ``close()`` rolls back)."""
    if getattr(endpoint, RELEASES, False) or not plain_sync(endpoint):
        return endpoint

    @functools.wraps(endpoint)
    def run(*args: Any, **kwargs: Any) -> Any:
        out = endpoint(*args, **kwargs)
        for value in kwargs.values():
            if isinstance(value, Session):
                release_connection(value)
        return out

    setattr(run, RELEASES, True)
    return run


class Router(APIRouter):
    """``APIRouter`` whose sync endpoints give their connection back before the response is validated (see above)."""

    def add_api_route(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        super().add_api_route(path, releasing(endpoint), **kwargs)
