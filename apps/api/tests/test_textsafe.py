"""Names that reach other people's screens and chat channels: one line, Discord markdown escaped."""

from __future__ import annotations

import pytest

from forliosa.textsafe import (
    discord_escape,
    has_control,
    name_key,
    normalize_text,
    one_line,
    text_has_control,
    visible,
)


@pytest.mark.parametrize("text", ["a\nb", "a\rb", "a\tb", "a\x00b", "a\u2028b", "a\u2029b", "a\u202eb", "a\u2066b",
                                  "a\u200bb", "a\ufeffb", "a\u00adb", "a\u200eb"])
def test_control_and_format_characters_are_refused(text):
    assert has_control(text)


@pytest.mark.parametrize("text", ["小明", "王 家", "A.B-C_D", "\U0001F468\u200d\U0001F469\u200d\U0001F467",
                                  "家族　投資", "[x](https://y)"])
def test_ordinary_names_pass(text):
    assert not has_control(text)


def test_one_line():
    assert one_line("明\n[群組頁]\t x\u200b y\u202e z \u2028w  ") == "明 [群組頁] x y z w"
    assert one_line("\U0001F468\u200d\U0001F469") == "\U0001F468\u200d\U0001F469"
    assert one_line("\u200b\n") == ""


@pytest.mark.parametrize(("raw", "escaped"), [
    ("[群組頁](https://ev.il/g)", "\\[群組頁\\]\\(https\\://ev.il/g\\)"),
    ("**粗**_斜_~~刪~~`碼`||雷||", "\\*\\*粗\\*\\*\\_斜\\_\\~\\~刪\\~\\~\\`碼\\`\\|\\|雷\\|\\|"),
    ("<@123> <t:1:R>", "\\<@123> \\<t\\:1\\:R>"),
    ("# 大標", "\\# 大標"), ("-# 小字", "\\-# 小字"), ("- 清單", "\\- 清單"), ("> 引用", "\\> 引用"),
    ("+ 清單", "\\+ 清單"), ("1. 清單", "1\\. 清單"), ("2) 清單", "2\\) 清單"),
    ("a\\b", "a\\\\b"),
    ("王-小明 +1.5% #1 > 0", "王-小明 +1.5% #1 > 0"),  # only at the start of a line do these mean anything
    ("2330", "2330"),
])
def test_discord_escape(raw, escaped):
    assert discord_escape(raw) == escaped


# -- multi-line text and public-name keys (discussion threads) --------------------------------------------------
def test_normalize_text_keeps_paragraphs_and_drops_noise():
    assert normalize_text("a\r\nb\rc\n") == "a\nb\nc"
    assert normalize_text("\n\n  first  \n\n\n\n\nsecond\t \n\n") == "  first\n\n\nsecond"
    assert normalize_text(" \n\t\n") == ""


def test_text_has_control_allows_only_line_feeds():
    assert not text_has_control("第一行\n第二行\n\n第三行")
    for bad in ("a\tb", "a\rb", "a\u2028b", "a\u200bb", "a\u202eb", "a\x00b"):
        assert text_has_control(bad), repr(bad)


@pytest.mark.parametrize(("a", "b"), [("Abc", "abc"), ("ＡＢＣ", "abc"), ("阿 土伯", "阿   土伯"),
                                      ("Straße", "STRASSE"), ("ｶﾀｶﾅ", "カタカナ"), (" 前後 ", "前後")])
def test_name_key_folds_case_width_and_spacing(a, b):
    assert name_key(a) == name_key(b)


def test_name_key_keeps_different_names_apart():
    assert name_key("阿土伯") != name_key("阿土伯2") and name_key("ab") != name_key("a b")


# Hangul fillers, the zero width joiner, the braille blank, the combining grapheme joiner, variation selectors: none
# is a "format" character for has_control, and none shows anything.
SHOWS_NOTHING = [chr(c) for c in (0x115F, 0x1160, 0x3164, 0xFFA0, 0x200D, 0x2800, 0x034F, 0xFE00, 0xFE0F, 0xE0100)]


def test_visible_drops_whitespace_and_characters_that_show_nothing():
    assert visible(" 阿 土\n伯　") == "阿土伯"
    for ch in SHOWS_NOTHING:
        assert visible(ch * 3) == "" and visible(f"阿{ch}土") == "阿土", hex(ord(ch))


def test_name_key_ignores_characters_that_show_nothing():
    for ch in SHOWS_NOTHING:
        assert name_key(f"阿{ch}土伯{ch}") == name_key("阿土伯"), hex(ord(ch))
