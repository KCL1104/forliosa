---
target: 個股頁（估值分頁為重點）
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/user/forliosa/apps/web/src/pages/stock/StockPage.tsx"
target_fingerprint: "sha256:820e440870576a4f86ce41a209f66ad1ff02f05711f4351ffa2703f9136c1c70"
target_path: /home/user/forliosa/apps/web/src/pages/stock/StockPage.tsx
timestamp: 2026-11-11T16-29-49Z
slug: apps-web-src-pages-stock-stockpage-tsx
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 個股頁（估值分頁為重點）

Target: `apps/web/src/pages/stock/StockPage.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 收盤／延遲時間、示範章 |
| 2 | Match System / Real World | 4 | 本益比河流圖倍數、EPS ≤ 0 說明、千元→億元 |
| 3 | User Control and Freedom | 3 | 分頁寫進網址 |
| 4 | Consistency and Standards | 3 | 分頁列與 Panel 一致 |
| 5 | Error Prevention | 3 | EPS ≤ 0 留白並說明，不畫錯誤區間 |
| 6 | Recognition Rather Than Recall | 3 | 各倍數對應今日股價表＋現價列 |
| 7 | Flexibility and Efficiency | 3 | ⌘K 直達、K 線日週月切換 |
| 8 | Aesthetic and Minimalist Design | 3 | 資訊密集但分區 |
| 9 | Error Recovery | 3 | 404 代號說明格式 |
| 10 | Help and Documentation | 3 | 河流圖一句白話說明 |
| **Total** | | **31/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: Specific to Taiwan equity research: the river chart (eps_ttm × multiples) is drawn as a single-hue band ramp deliberately free of red/green so it never reads as up/down, the current-multiple panel states the bracket in words, and EPS ≤ 0 periods are left blank with an explicit note (2409 友達 demo).

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

Specific to Taiwan equity research: the river chart (eps_ttm × multiples) is drawn as a single-hue band ramp deliberately free of red/green so it never reads as up/down, the current-multiple panel states the bracket in words, and EPS ≤ 0 periods are left blank with an explicit note (2409 友達 demo). Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- Valuation side panel: big current multiple, bracket sentence, 5-year percentile, and a band→price table with the live price row inserted in place (also the chart's table view).
- Revenue and YoY are two charts sharing an x-axis (no dual axis).
- K 線 uses lightweight-charts with TradingView attribution logo + text credit; colours follow the convention setting.

## Priority Issues

- **[P1] Inactive tab labels and 「即將推出」 failed contrast (4.0–4.4:1)**
  - Status: Fixed: tabs use --muted-foreground (6.3:1); active underline in stamp blue.
- **[P1] Mock EPS made 2330 sit above every band with a 4% percentile (contradictory copy)**
  - Status: Fixed: mock EPS now derived from a multiple wave, so price wanders through bands and percentile matches the bracket.
- **[P2] Dividend-yield line drew 0% before mock data coverage**
  - Status: Fixed: yield is null (gap) before the first recorded ex-date + 1 year.
- **[P2] Long fund names wrapped 3 lines at 28px on phones**
  - Status: Fixed: names > 12 chars use 22px on mobile.

## Persona Red Flags

Riley: 00999 stress ETF (26 chars) wraps cleanly; ETF valuation tab explains why there is no river. Sam: charts carry role=img labels / legends; tooltip is never the only way (band table, revenue table).

## Minor Observations

- 籌碼／新聞／AI 報告 tabs are designed 即將推出 states; consider hiding them on mobile to shorten the tab scroller.

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
