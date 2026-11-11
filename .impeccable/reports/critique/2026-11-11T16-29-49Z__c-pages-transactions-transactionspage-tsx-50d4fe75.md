---
target: 交易（清單＋新增／編輯表單）
total_score: 30
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/user/forliosa/apps/web/src/pages/transactions/TransactionsPage.tsx"
target_fingerprint: "sha256:b2d68ba816d8532ad66e42687db1c8de84ef086dae900d35701e943a0369cf33"
target_path: /home/user/forliosa/apps/web/src/pages/transactions/TransactionsPage.tsx
timestamp: 2026-11-11T16-29-49Z
slug: c-pages-transactions-transactionspage-tsx-50d4fe75
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 交易（清單＋新增／編輯表單）

Target: `apps/web/src/pages/transactions/TransactionsPage.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 即時稅費試算、儲存中狀態、蓋章通知 |
| 2 | Match System / Real World | 4 | 張／股輸入換算、證交稅與二代健保規則文字 |
| 3 | User Control and Freedom | 3 | 復原（undo）取代確認對話框；可編輯 |
| 4 | Consistency and Standards | 3 | Dialog／Drawer 同一表單 |
| 5 | Error Prevention | 3 | 欄位驗證、零股最低手續費提示 |
| 6 | Recognition Rather Than Recall | 3 | 代號搜尋支援中文 |
| 7 | Flexibility and Efficiency | 3 | 虛擬化清單、月份分組、篩選 |
| 8 | Aesthetic and Minimalist Design | 3 | 表單左右兩欄清楚 |
| 9 | Error Recovery | 3 | 儲存失敗保留內容 |
| 10 | Help and Documentation | 2 | 規則說明只在試算欄 |
| **Total** | | **30/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: The fee/tax preview with rule lines (「手續費 0.1425% × 2.8 折」「證交稅：買進免稅」) and the 「已入帳」 stamp in the toast are product-specific; the virtualized ledger with month group headers reads as a Taiwanese broker statement without costuming it.

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

The fee/tax preview with rule lines (「手續費 0. Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- Live preview debounced 300 ms against POST /transactions/preview; skeleton while fetching.
- Mobile Vaul drawer with a sticky footer showing 「應付（預估）」 and the actions.
- Sonner toast with 復原 for both create and delete (no blocking confirm on the common path).

## Priority Issues

- **[P1] No way to edit a transaction (spec requires 新增與編輯); mobile had no delete either**
  - Status: Fixed: tap/Enter on any row opens the form in edit mode with 「刪除這筆交易」 + undo.
- **[P1] Mobile drawer's Save button sat below the fold**
  - Status: Fixed: sticky footer with net amount and actions, safe-area padded.
- **[P2] Desktop row delete still uses an AlertDialog while the form uses undo**
  - Status: Kept intentionally: hover delete from a dense list is easy to mis-click.

## Persona Red Flags

Alex: ⌘K 「記一筆交易」, Enter on rows. Casey: one-handed drawer, 16px inputs (no iOS zoom), inputmode=decimal. Jordan: empty ledger offers 「記第一筆交易」.

## Minor Observations

- Date input renders mm/dd/yyyy in some locales (native control).

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
