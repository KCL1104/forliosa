---
target: 持股
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
target_identity: "file:/home/user/forliosa/apps/web/src/pages/holdings/HoldingsPage.tsx"
target_fingerprint: "sha256:ebbb8364a81f1da2ed57bdaf7063d2545c9a8a0b18436658871864d2811586a8"
target_path: /home/user/forliosa/apps/web/src/pages/holdings/HoldingsPage.tsx
timestamp: 2026-11-11T16-29-49Z
slug: apps-web-src-pages-holdings-holdingspage-tsx
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 持股

Target: `apps/web/src/pages/holdings/HoldingsPage.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 示範章、合計列、筆數與市值 |
| 2 | Match System / Real World | 4 | X 張 Y 股、均價含手續費說明 |
| 3 | User Control and Freedom | 3 | 篩選寫進網址，可返回 |
| 4 | Consistency and Standards | 4 | 表頭排序、數字右對齊 |
| 5 | Error Prevention | 3 | 篩選無結果有清除 |
| 6 | Recognition Rather Than Recall | 3 | 代號＋市場＋ETF 標示 |
| 7 | Flexibility and Efficiency | 3 | 排序、帳戶與市場篩選；Enter 進個股 |
| 8 | Aesthetic and Minimalist Design | 3 | 密集但分層 |
| 9 | Error Recovery | 3 | 錯誤重試 |
| 10 | Help and Documentation | 2 | AI 訊號欄只有 tooltip 說明 |
| **Total** | | **31/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: Dense, ledger-precise table in the Yahoo 股市 / Shioaji tradition; the world shows in the hairline rhythm, tabular figures, sticky first column and the 示範資料 chop. A neighbouring product could ship a similar table — the specificity is in the Taiwan facts (張＋股, 上市/上櫃/美股 filter, TWD-normalised US rows).

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

Dense, ledger-precise table in the Yahoo 股市 / Shioaji tradition; the world shows in the hairline rhythm, tabular figures, sticky first column and the 示範資料 chop. Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- Mobile collapses to cards with only key fields (名稱、張股、現價、今日、市值、未實現) and a chevron to the full stock page.
- Sticky name column + min-width table keeps 11 columns readable on 768–1023px.
- Privacy mode masks amounts and quantities while keeping % (verified screenshot).

## Priority Issues

- **[P2] No sort control on mobile cards**
  - Status: Open — logged; cards keep market-value order.
- **[P2] AI 訊號 column shows only 「—」 until M4**
  - Status: Kept with a tooltip explaining it arrives with 持倉健檢 (M4).

## Persona Red Flags

Alex (power user): sortable headers with aria-sort, keyboard row entry. Riley (stress): 9,876 張 543 股 and NT$1,234.57 億 rows fit; 26-character fund names truncate with title.

## Minor Observations

- Row height is generous for a dense table (two-line name cell).

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
