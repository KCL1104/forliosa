---
target: 自選／AI 助理／報告／群組／匯入（規劃中頁面）
total_score: 28
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/home/user/forliosa/apps/web/src/pages/placeholders/ComingSoonPages.tsx"
target_fingerprint: "sha256:b91e4596faadb75065d959b795087289f64df0fa88a9743b6018e50b3293baa6"
target_path: /home/user/forliosa/apps/web/src/pages/placeholders/ComingSoonPages.tsx
timestamp: 2026-11-11T16-29-49Z
slug: rc-pages-placeholders-comingsoonpages-tsx-a22882ac
---
⚠️ DEGRADED: single-context (no sub-agent/Task tool exposed to this frontend subagent; Assessment A was completed and recorded before Assessment B's detector output was read)

# Critique: 自選／AI 助理／報告／群組／匯入（規劃中頁面）

Target: `apps/web/src/pages/placeholders/ComingSoonPages.tsx` · viewed at http://localhost:5173 (desktop 1440×900 @2x and iPhone 15, light and dark) · Direction contract: 印鑑與朱泥 (seed:bf59ff6fbd34ea97)

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|---|---|---|
| 1 | Visibility of System Status | 3 | 里程碑章 M2–M5 |
| 2 | Match System / Real World | 3 | 用使用者語言說明功能 |
| 3 | User Control and Freedom | 3 | 每頁給一個現在能做的事 |
| 4 | Consistency and Standards | 3 | 共用 Planned 骨架 |
| 5 | Error Prevention | 3 | AI 示意只用持股資料計算 |
| 6 | Recognition Rather Than Recall | 3 | 功能三欄說明 |
| 7 | Flexibility and Efficiency | 2 | 自選只存在本機 |
| 8 | Aesthetic and Minimalist Design | 3 | 不塞空洞卡片 |
| 9 | Error Recovery | 2 | 無錯誤情境 |
| 10 | Help and Documentation | 3 | 群組分享預設值展示 |
| **Total** | | **28/40** | **Good** |

## Design Specificity Verdict

**LLM assessment**: Onboarding-style placeholders that teach what is coming with real product facts (four share switches with their defaults, the five-step import flow, an AI answer computed from the user's own allocation). No lorem, no invented AI conclusions.

**Deterministic scan**: `impeccable detect --json apps/web/src` → 4 findings in the first pass (all `design-system-font-size`: `text-[10px]` in CommandSearch, `text-[1.0625rem]` in the wordmark, `text-[2.25rem]` hero in HomePage/StockPage). All fixed by adding `--text-hero-sm` to the ramp and replacing the glyph chop with a drawn icon; re-scan returns `[]`. Rendered-URL scans (`detect http://localhost:5173/…`) found `flat-type-hierarchy` on `/`, `low-contrast` on `/stock/2330.TW?tab=valuation` (tab「即將推出」4.0:1), `/ai` and `/import` (sidebar milestone 4.1:1), and `nested-cards` on `/ai` (chat bubble with border inside a Panel). All fixed; re-scans of `/`, `/holdings`, `/stock/…`, `/transactions`, `/performance`, `/settings`, `/ai`, `/import` return 0 findings. No false positives kept.
**Visual overlays**: not injected (the live-server overlay needs a human-visible browser tab; this run used headless Playwright captures instead).

## Overall Impression

Onboarding-style placeholders that teach what is coming with real product facts (four share switches with their defaults, the five-step import flow, an AI answer computed from the user's own allocation). Biggest opportunity: keep the world in the details (chops, hairlines, tabular figures) while M2–M5 fill the placeholders.

## What's Working

- 自選 already works locally (star on stock page → list with quotes).
- AI sample answer is computed from summary.allocation and labelled 示範 + disclaimer.

## Priority Issues

- **[P1] Chat bubble nested a bordered card inside a Panel (detector nested-cards)**
  - Status: Fixed: borderless muted bubble.
- **[P1] Sidebar milestone labels 4.1:1 contrast**
  - Status: Fixed: full --rail-muted (7.4:1).

## Persona Red Flags

Jordan: every page answers 「現在可以先做什麼」.

## Minor Observations

- Showcase components from Magic UI / Aceternity were evaluated and not used (see docs/ui-libraries.md).

## Questions to Consider

Questions skipped: unattended subagent run; the product owner is asleep. Open product questions are in `apps/web/OPEN_QUESTIONS.md`.
