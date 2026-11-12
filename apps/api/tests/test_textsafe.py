"""Names that reach other people's screens and chat channels: one line, Discord markdown escaped."""

from __future__ import annotations

import pytest

from forliosa.textsafe import discord_escape, has_control, one_line


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
