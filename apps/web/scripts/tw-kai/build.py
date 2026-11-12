"""把全字庫正楷體（TW-Kai）切成依 unicode-range 載入的 woff2 子集。

AI 的話用這套字（教育部標準字形：為、說、著、裡…），只載入畫面上用到的切片。
拉丁字母與數字不在切片裡，會落到 Noto Sans TC（等寬數字），和帳本的數字一致。

來源：國家發展委員會／數位發展部「CNS11643 中文標準交換碼全字庫」開放資料
  https://data.cns11643.gov.tw/opendata/Fonts_Kai.zip 內的 TW-Kai.ttf（Unicode BMP 字面）。
授權：字型名稱表自述可擇一使用「政府資料開放授權條款－第1版」或 SIL OFL 1.1；
  本專案選 OFL 1.1（見 src/assets/fonts/tw-kai/OFL.txt）。

用法（在 apps/web 底下，需要 fonttools 與 brotli）：
  uv run --with fonttools --with brotli python scripts/tw-kai/build.py /path/to/TW-Kai.ttf

輸出：
  src/assets/fonts/tw-kai/tw-kai-<slice>.woff2
  src/styles/tw-kai.css（@font-face 清單，由 globals.css 匯入）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
WEB = HERE.parent.parent
OUT_FONTS = WEB / "src" / "assets" / "fonts" / "tw-kai"
OUT_CSS = WEB / "src" / "styles" / "tw-kai.css"
FAMILY = "TW-Kai"
SIZE_ADJUST = 110

# 標點與全形符號：AI 的話裡的「」，。、：；！？（）—…～ 也要是楷體
PUNCT = list(range(0x3000, 0x3040)) + list(range(0xFE30, 0xFE50)) + list(range(0xFF01, 0xFF61)) + [0x2014, 0x2025, 0x2026, 0x2027]
# 切片定義（Google Fonts 的分片）也含拉丁字母、數字與 ▲▼ 等符號；那些留給 Noto Sans TC
KEEP_BELOW_CJK = {0x2014, 0x2025, 0x2026, 0x2027}


def is_kai(cp: int) -> bool:
    return cp >= 0x2E80 or cp in KEEP_BELOW_CJK


def parse_ranges(text: str) -> set[int]:
    cps: set[int] = set()
    for part in text.split(","):
        part = part.strip().upper().removeprefix("U+")
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            cps.update(range(int(a, 16), int(b, 16) + 1))
        else:
            cps.add(int(part, 16))
    return cps


def big5_chars() -> set[int]:
    """Big5 常用字＋次常用字，確保台灣常見的字都有楷體。"""
    out: set[int] = set()
    for hi in range(0xA4, 0xFA):
        for lo in list(range(0x40, 0x7F)) + list(range(0xA1, 0xFF)):
            try:
                ch = bytes([hi, lo]).decode("big5")
            except UnicodeDecodeError:
                continue
            out.add(ord(ch))
    return out


def compact(cps: list[int]) -> str:
    parts: list[str] = []
    start = prev = cps[0]
    for cp in cps[1:] + [None]:  # type: ignore[list-item]
        if cp is not None and cp == prev + 1:
            prev = cp
            continue
        parts.append(f"U+{start:x}" if start == prev else f"U+{start:x}-{prev:x}")
        if cp is not None:
            start = prev = cp
    return ",".join(parts)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = Path(sys.argv[1])
    font = TTFont(src)
    cmap = set(font.getBestCmap())
    version = font["name"].getDebugName(5)

    slices_def = json.loads((HERE / "slices.json").read_text())["slices"]
    covered: set[int] = set()
    slices: list[tuple[str, list[int]]] = []
    for s in slices_def:
        cps = {cp for cp in parse_ranges(s["ranges"]) & cmap if is_kai(cp)} - covered
        if cps:
            covered |= cps
            slices.append((s["name"], sorted(cps)))
    # 切片沒涵蓋的 Big5 字與標點：每 300 字一片，避免一個罕用字就載入整包
    extra = sorted({cp for cp in (big5_chars() | set(PUNCT)) & cmap if is_kai(cp)} - covered)
    for i in range(0, len(extra), 300):
        slices.append((f"x{i // 300}", extra[i : i + 300]))

    OUT_FONTS.mkdir(parents=True, exist_ok=True)
    for old in OUT_FONTS.glob("tw-kai-*.woff2"):
        old.unlink()

    css = [
        f"/* 由 scripts/tw-kai/build.py 產生，請勿手改。全字庫正楷體 {version}，OFL 1.1。 */",
        "/* 只含漢字與全形標點；拉丁字母與數字落到 Noto Sans TC。 */",
    ]
    total = 0
    for name, cps in slices:
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["*"]
        opts.name_IDs = ["*"]
        opts.name_languages = ["*"]
        opts.hinting = False
        opts.notdef_outline = False
        opts.drop_tables += ["FFTM"]
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=cps)
        f = TTFont(src)
        sub.subset(f)
        f.flavor = "woff2"
        path = OUT_FONTS / f"tw-kai-{name}.woff2"
        f.save(path)
        total += path.stat().st_size
        css += [
            "@font-face {",
            f'  font-family: "{FAMILY}";',
            "  font-style: normal;",
            "  font-weight: 400;",
            "  font-display: swap;",
            # 楷體的字面比 Noto Sans TC 小一圈；放大一點，和同一行的數字（Noto Sans）看起來一樣大
            f"  size-adjust: {SIZE_ADJUST}%;",
            f'  src: url("../assets/fonts/tw-kai/{path.name}") format("woff2");',
            f"  unicode-range: {compact(cps)};",
            "}",
        ]
    OUT_CSS.write_text("\n".join(css) + "\n")
    print(f"{len(slices)} slices, {sum(len(c) for _, c in slices)} chars, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
