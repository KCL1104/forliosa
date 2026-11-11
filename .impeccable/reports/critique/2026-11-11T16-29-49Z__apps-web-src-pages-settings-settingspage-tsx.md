---
target: 設定
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 1
target_identity: "file:/home/user/forliosa/apps/web/src/pages/settings/SettingsPage.tsx"
target_fingerprint: "sha256:0ef777bb45c5704a4001f67b707cdf4a91be0dd4575f6d7716c88c29172bfbe8"
target_path: /home/user/forliosa/apps/web/src/pages/settings/SettingsPage.tsx
timestamp: 2026-11-11T16-29-49Z
slug: apps-web-src-pages-settings-settingspage-tsx
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 設定

Target: `apps/web/src/pages/settings/SettingsPage.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 即時套用＋失敗還原 toast |
| 2 | Match System / Real World | 4 | 紅漲綠跌預覽、張＋股例子、2.8 折輸入 |
| 3 | User Control and Freedom | 3 | 即時切換可回復 |
| 4 | Consistency and Standards | 3 | 列式設定一致 |
| 5 | Error Prevention | 3 | 折扣範圍驗證 |
| 6 | Recognition Rather Than Recall | 3 | 每列附一句說明 |
| 7 | Flexibility and Efficiency | 3 | 分段按鈕可方向鍵切換 |
| 8 | Aesthetic and Minimalist Design | 3 | 分組清楚 |
| 9 | Error Recovery | 3 | 錯誤訊息具體 |
| 10 | Help and Documentation | 3 | 關於資料與授權 |
| **Total** | | **31/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: Form surface with product-specific defaults (紅漲綠跌 preview with ▲▼, 張＋股 example, fee discount in 折). Unremarkable by design; the chops for M4/M5 rows keep the world.

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

Form surface with product-specific defaults (紅漲綠跌 preview with ▲▼, 張＋股 example, fee discount in 折). Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- Optimistic local apply + PATCH /me/preferences with rollback.
- Accounts list with fee rule summary and edit/create dialog.

## Priority Issues

- **[P1] Accounts could not be created (copy said 「新增帳戶的功能會和登入一起上線」)**
  - Status: Fixed: 新增帳戶 dialog (名稱、券商、幣別、追蹤方式、折扣、最低手續費).

## Persona Red Flags

Jordan: discount explained as 「幾折」 with an example.

## Minor Observations

- Benchmark option 加權報酬指數 depends on backend data (open question).

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
