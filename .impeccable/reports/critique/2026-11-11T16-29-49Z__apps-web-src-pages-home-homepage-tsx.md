---
target: 總覽（首頁）＋ App shell
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/user/forliosa/apps/web/src/pages/home/HomePage.tsx"
target_fingerprint: "sha256:dfc0cc14921409769be1b250184bff2efbf0590ffb922cc0e8f4ecbc8239a1e4"
target_path: /home/user/forliosa/apps/web/src/pages/home/HomePage.tsx
timestamp: 2026-11-11T16-29-49Z
slug: apps-web-src-pages-home-homepage-tsx
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 總覽（首頁）＋ App shell

Target: `apps/web/src/pages/home/HomePage.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 示範資料章、收盤時間、骨架都有；1D 只有兩點的限制有說明 |
| 2 | Match System / Real World | 4 | 張／股、紅漲綠跌、萬／億、台北時間 |
| 3 | User Control and Freedom | 3 | 隱私一鍵切換；圖表區間可切回 |
| 4 | Consistency and Standards | 3 | Panel、分段按鈕一致 |
| 5 | Error Prevention | 3 | 首次使用導向；AI 卡不給可誤會的結論 |
| 6 | Recognition Rather Than Recall | 3 | 前五大與除權息直接列出名稱與代號 |
| 7 | Flexibility and Efficiency | 3 | ⌘K、/ 快捷鍵；桌面記一筆常駐 |
| 8 | Aesthetic and Minimalist Design | 3 | hero 兩個數字＋影響最大清單，其餘降一級 |
| 9 | Error Recovery | 3 | 錯誤狀態有重試 |
| 10 | Help and Documentation | 3 | AI 卡說明何時推出 |
| **Total** | | **31/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: Authored for this product: the hero answers 「總資產與今日損益」 in Taiwanese conventions, the 「今天誰影響最大」 contribution list is a product-specific move a generic dashboard would not have, and the seal chops (示範資料、M4 推出) carry the world. Category-interchangeable risk: the lower three-card row (配置／除權息／前五大) is a familiar dashboard grid; it earns its place by content, not by form.

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

Authored for this product: the hero answers 「總資產與今日損益」 in Taiwanese conventions, the 「今天誰影響最大」 contribution list is a product-specific move a generic dashboard would not have, and the seal chops (示範資料、M4 推出) carry the world. Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- Hero hierarchy: 48px proportional total, 22px P&L with ▲▼ and colour, then a quiet supporting line (未實現／已實現／股利).
- 「今天誰影響最大」 turns today's P&L into reasons (per-holding contribution bars) without inventing AI copy.
- Return chart indexes mine vs 0050 on one axis (no dual axis), legend carries period returns.

## Priority Issues

- **[P1] Chart would show an infinite skeleton when performance has < 2 points (new user who only entered holdings today)**
  - Status: Fixed: distinct 「走勢圖需要至少兩個交易日」 state.
- **[P1] Flat type hierarchy on panel titles (16px = body) — detector `flat-type-hierarchy`**
  - Status: Fixed: home panels use the 22px title size; 「今天誰影響最大」 label raised to 14px.
- **[P2] 1D/5D are sliced from the 1M API range; 1D is just yesterday→today**
  - Status: Documented in-chart and in OPEN_QUESTIONS (needs intraday series from M2).
- **[P2] Mobile top bar showed the 示範資料 chop twice (top bar + hero)**
  - Status: Fixed: removed the global mobile chop; each data surface shows its own.

## Persona Red Flags

Casey (distracted mobile): hero + P&L fit the first viewport on iPhone 15; the tab bar respects the home indicator. Jordan (first-timer): empty scenario shows two entry points (輸入目前持股／匯入 M3) plus 「已經有交易紀錄？」. Sam (a11y): ▲▼ + sr-only 上漲/下跌; colour is never alone.

## Minor Observations

- Allocation donut card has spare height on desktop when only 2 slices exist.
- AI card copy is long on 360px widths (wraps to 3 lines).

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
