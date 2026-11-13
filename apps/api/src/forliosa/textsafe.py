"""User-chosen names that other people see in the app and in group chat channels (display names, group names).

* **Input**: :func:`has_control` rejects line breaks, tabs and other control characters (Unicode ``Cc``, ``Zl``,
  ``Zp``) and invisible format characters (``Cf``: bidi overrides, zero-width spaces, BOM …; ``Cs``: lone
  surrogates) — except U+200D ZERO WIDTH JOINER, which multi-person emoji sequences need. A name is one visible line,
  so it can never fake another line of a pushed message.
* **Output**: :func:`one_line` makes any stored text one line the same way (names saved before the check, Discord
  global names, chat titles), and :func:`discord_escape` backslash-escapes Discord markdown so a name can never become
  a masked link, a heading, a quote, a spoiler or code (Discord shows the escaped characters as typed).
"""

from __future__ import annotations

import re
import unicodedata

KEEP_FORMAT = frozenset({"\u200d"})  # ZERO WIDTH JOINER: emoji sequences
_BREAKING = frozenset({"Cc", "Zl", "Zp"})  # → a space
_INVISIBLE = frozenset({"Cf", "Cs"})  # → removed
# Inline markdown anywhere (emphasis, code, spoilers, masked links, <…> mentions / timestamps / links) and ``:`` (so
# ``https\://…`` is not turned into a link); line-start markdown (headings, -# subtext, lists, quotes) at the start of
# the value — a value is one line, so that is the only place it can begin a line.
_DISCORD_INLINE = re.compile(r"([\\*_~`|\[\]()<:])")
_DISCORD_LINE_START = re.compile(r"^(?:([#>+\-])|(\d+)([.)]))")


def _kind(ch: str) -> str | None:
    if ch in KEEP_FORMAT:
        return None
    cat = unicodedata.category(ch)
    if cat in _BREAKING:
        return "break"
    if cat in _INVISIBLE:
        return "drop"
    return None


def has_control(text: str) -> bool:
    """True when ``text`` has a line break, tab, other control character or an invisible format character."""
    return any(_kind(ch) is not None for ch in text)


def one_line(text: str) -> str:
    """``text`` as one line: control characters and line breaks become spaces, invisible format characters are
    removed, and every run of whitespace is one space (no leading or trailing space)."""
    out = []
    for ch in text:
        kind = _kind(ch)
        if kind == "break":
            out.append(" ")
        elif kind is None:
            out.append(ch)
    return " ".join("".join(out).split())


def discord_escape(text: str) -> str:
    """Backslash-escape Discord markdown in a one-line value placed in a message: inline markdown anywhere; ``#``,
    ``>``, ``-``, ``+`` and ``1.`` / ``1)`` (headings, quotes, lists) at its start."""
    out = _DISCORD_INLINE.sub(r"\\\1", text)
    return _DISCORD_LINE_START.sub(lambda m: "\\" + m.group(1) if m.group(1) else m.group(2) + "\\" + m.group(3),
                                   out, count=1)


# -- multi-line text (discussion topics and replies) and public names ---------------------------------------------
def normalize_text(text: str) -> str:
    """Multi-line plain text as stored: CRLF / CR become LF, trailing whitespace of every line is removed, more than
    two consecutive empty lines become two, and empty lines at the start and the end are dropped."""
    out: list[str] = []
    blank = 0
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip()
        blank = 0 if line else blank + 1
        if blank <= 2:
            out.append(line)
    return "\n".join(out).strip("\n")


def text_has_control(text: str) -> bool:
    """:func:`has_control` for multi-line text: LF is the only control character allowed (tabs, other line
    separators and invisible format characters are not)."""
    return has_control(text.replace("\n", ""))


# Characters that show nothing (or a blank) although :func:`has_control` lets them through: the zero width joiner,
# Hangul fillers, the braille blank, the combining grapheme joiner and variation selectors.
_SHOWS_NOTHING = (KEEP_FORMAT | frozenset("\u115f\u1160\u3164\uffa0\u2800\u034f")
                  | frozenset(map(chr, range(0xFE00, 0xFE10))) | frozenset(map(chr, range(0xE0100, 0xE01F0))))


def visible(text: str) -> str:
    """``text`` without whitespace and without characters that show nothing: what a reader actually sees of it
    (empty for a "blank" name or post)."""
    return "".join(ch for ch in text if not ch.isspace() and ch not in _SHOWS_NOTHING)


def name_key(name: str) -> str:
    """The comparison key of a public name: NFKC + casefold (full-width and half-width, upper and lower case are the
    same name), without characters that show nothing, and with every run of whitespace as one space."""
    key = unicodedata.normalize("NFKC", name)
    key = "".join(ch for ch in key if ch not in _SHOWS_NOTHING)
    return " ".join(unicodedata.normalize("NFKC", key.casefold()).split())
