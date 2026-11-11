"""Prefixed ULID identifiers (``usr_01J…``, ``acc_01J…``, ``txn_01J…``)."""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_last_ms = 0
_last_rand = 0


def ulid() -> str:
    """26-char ULID; monotonic within the same millisecond in this process."""
    global _last_ms, _last_rand
    ms = int(time.time() * 1000)
    if ms == _last_ms:
        _last_rand = (_last_rand + 1) & ((1 << 80) - 1)
    else:
        _last_ms = ms
        _last_rand = int.from_bytes(os.urandom(10), "big")
    value = (ms << 80) | _last_rand
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"
