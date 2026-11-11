---
target: 績效
total_score: 30
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/user/forliosa/apps/web/src/pages/performance/PerformancePage.tsx"
target_fingerprint: "sha256:f08cc423b484d7e8880e5c64c5353a30237e0ad41ba9e01e3f6baeea76413a03"
target_path: /home/user/forliosa/apps/web/src/pages/performance/PerformancePage.tsx
timestamp: 2026-11-11T16-29-49Z
slug: apps-web-src-pages-performance-performancepage-tsx
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 績效

Target: `apps/web/src/pages/performance/PerformancePage.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 區間、日期範圍、示範章 |
| 2 | Match System / Real World | 3 | TWR／XIRR 白話說明 tooltip |
| 3 | User Control and Freedom | 3 | 區間與帳戶可切換 |
| 4 | Consistency and Standards | 3 | 指標格一致 |
| 5 | Error Prevention | 3 | XIRR 無法計算時說明 |
| 6 | Recognition Rather Than Recall | 3 | 超額報酬直接寫「比 0050 少 9.81%」 |
| 7 | Flexibility and Efficiency | 3 | 區間 chips |
| 8 | Aesthetic and Minimalist Design | 3 | 圖表數量剛好 |
| 9 | Error Recovery | 3 | 資料不足狀態 |
| 10 | Help and Documentation | 3 | 「計算方式」摺疊說明 |
| **Total** | | **30/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: Grounded in the API's calculation definitions (TWR, XIRR, MDD from twr_index) and written for non-experts. The world is light here — correct for a dense analysis page.

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

Grounded in the API's calculation definitions (TWR, XIRR, MDD from twr_index) and written for non-experts. Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- Metric strip in a hairline grid with plain-language tooltips.
- Benchmark comparison on one indexed axis; realized-by-year bars coloured by sign with ▲▼ text list.
- Privacy mode hides money charts with an explanation instead of leaking axis values.

## Priority Issues

- **[P1] 每年已實現損益 Y axis rendered five identical ticks (domain collapsed on one bar)**
  - Status: Fixed: domain always includes 0.
- **[P1] Realized-by-year included sells outside the selected range**
  - Status: Fixed: mock filters realized events by trade date within range.

## Persona Red Flags

Sam: tooltip-only explanations are also reachable via the 計算方式 disclosure.

## Minor Observations

- Benchmark choice lives in 設定 only.

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
