# 交接文件（2026-11-13）

> 給下一個 Claude Code session。開法：用 **「forliosa」雲端環境**開新 session（環境變數 `Claude_API_KEY_1..3`、`SEC_CONTACT_EMAIL` 開機時才會載入），第一句話說「讀 docs/handoff.md 繼續做」。
> 分支：`claude/wizardly-cray-1407yu`。所有工作都已推送。

## 0. 先讀這些

1. `CLAUDE.md`：溝通規則（**回覆產品負責人一律用繁體中文**）、專案位置、重要決定。
2. `PRODUCT.md`：產品真相與產品負責人的所有決定。
3. `docs/pending-decisions.md`：**還在等產品負責人決定的 56 項**（每項附建議；小問題可整組回「照建議」）。新的待決定事項加在這裡，不要再散在各文件。
4. `docs/api-contract.md`：前後端合約；`apps/api/CONTRACT_NOTES.md`：後端實作差異與環境變數。
5. `DESIGN.md`：聯絡簿視覺系統（兩輪潤飾後的現況，見 §2）。前端改 UI 用 Impeccable skill（`.claude/skills/impeccable`），改之前先讀 `reference/craft-floor.md`。
6. 研究：`docs/research/`（資料授權、開放資料盤點、新聞與外部來源、Claude Platform、個股頁、重新設計）。

## 1. 目前狀態

handoff 上一版（2026-11-12）列的 §3.0–3.6 **全部完成並合併**：

- 股利自動入帳、SEC EDGAR 美股基本面與申報、法人觀點後端、央行匯率、上市個股法人的空狀態＋問 AI、定期定額補記草稿。
- M5 分享（Discord 登入、授權查看、親友群組、排行、動態、留言與表情、群組 AI 週報、Discord／Telegram 推播）。
- 個股頁補強：新聞報導（GDELT＋自架 SearXNG 預設開＋AI 搜尋補缺）、相關股票、公司資料、外資持股前 20 名、ETF 淨值與折溢價、授權信草稿（沒寄）。
- 三把 Claude key 已確認分屬三個 workspace（`uv run python -m forliosa.ai.smoke --keys`，2026-11-12）。

後端：Alembic 單一 head `0012_etf_navs`；本輪（前端潤飾）沒有改後端程式。

## 2. 前端潤飾（Impeccable，兩輪）

產品負責人說 UI「有點 AI 感」。評分 28/40 → 第一輪後 30/40 → 第二輪後的分數見 §2.3。評分報告在 `apps/web/.impeccable/critique/`（這個資料夾不進 git）。

### 2.1 產品負責人的決定

- 優先處理 AI 的聲音；深色模式＝**藍黑夜間筆記本**；AI 字型＝**全字庫正楷體**（教育部標準字形）；P1＋P2 全修；第二輪「全部修」。
- 群組排行：名次照**期間報酬**排，期間報酬是放大的主數字（欄位標題有排序箭頭），總報酬是一般字級的一欄。
- 手機底部：**平的格線底部列**（不浮動、沒有膠囊），「問 AI」是簽名格樣子的方格。
- AI 面板沒有建議可給的頁面：輸入框上方列出**最近 3 段對話**；輸入框提示文字依頁面而定。

### 2.2 做了什麼（細節都寫進 `DESIGN.md`）

- **字型**：AI 的字改用全字庫正楷體 TW-Kai（數位發展部開放資料，擇用 SIL OFL 1.1），自架切片在 `apps/web/src/assets/fonts/tw-kai/`，產生方式見 `apps/web/scripts/tw-kai/build.py`（需要官方 `TW-Kai.ttf`，來源 `data.cns11643.gov.tw`，環境已允許這個主機）。只切漢字與全形標點，數字與拉丁字母落到 Noto Sans TC。
- **兩支筆規則收緊**：紫色＝AI 說的或做的；**楷體只給模型真的寫出來的字**。規則或範本產生的句子一律墨色 Noto Sans。
- **AI 面板**：沒有問候語；建議是格線列；快捷動作是一行依頁面出現的文字連結；輸入框固定在底部；出處是註腳；免責每段對話一次。
- **深色**：藍黑紙色、看得見的格線、`--print`（印好的線：表頭雙線、區塊標題、底部列）；選取不再是白色實心塊。
- **一套選取語法**：`sel-tab`（文字分頁）、`sel-chip`（分段與選項）、`sel-row`（清單列）、`sel-tab-top`（手機底部列）。
- **共用元件**：`Button variant="sign"`（表單唯一的確認動作）、`.form-head`、`components/date-cell.tsx`、`SourcesProvider`／`useSourceNote`／`SourcesFooter`（每頁一個收合的「資料來源與授權」）、`ScrollRow`、`app/PageFrame.tsx`（一個版心）、`app/links.tsx` 的 `PlainLink`（不標 `aria-current` 的站內連結）、`components/states.tsx`（統一的空狀態與錯誤：上下實線，不用虛線——虛線只代表 AI 草稿）、`components/text-action.ts`。
- **個股頁**：總覽三層（鍵值帶＋估值刻度尺 → 事件表 → 參考）；一個價格格式（`lib/format.ts`，照升降單位）；說明收進「怎麼看 ⌄」。
- **帳本**：交易列表有名稱＋代號、數量與價格分欄、依容器寬度換欄；績效算不出來時只說一次原因；數字鍵 1–4 切換分段。
- **觸控**：手機上的按鈕、輸入框、整列連結都到 44px。

### 2.3 第二輪後的評分與還沒做的事

見本文件最後的「§6 第三次評分」（由這個 session 結束前補上）。

## 3. 接下來可以做

1. 產品負責人回覆 `docs/pending-decisions.md` 之後照決定實作。影響最大的五件：美股價格來源、「只記持股」帳戶的輸入畫面、券商對帳單樣本（M3 匯入）、部署前要建立的帳號（Discord 應用程式等，`docs/deploy.md`）、隱私權政策與服務條款。
2. 第三次評分留下的問題（§6）。
3. 財報狗式的 AI 產業新聞摘要（產品負責人說之後再做）。
4. `.impeccable/design.json` 與 4 份過時的 surface brief 可以跑一次 `/impeccable doctor` 整理（子代理回報 `CONTEXT_STALE`，沒有處理）。

## 4. 每次交付前的檢查

```bash
cd apps/api && uv run pytest -q && uv run ruff check . && uv run alembic heads
```

```bash
cd apps/web && pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm design:detect
```

網頁冒煙測試（要先開 dev server；約 5 分鐘，結尾要是「全部通過」）：

```bash
cd apps/web && pnpm dev
```

```bash
cd apps/web && node scripts/smoke.mjs
```

- `alembic heads` 必須只有一個 head。
- 前端 UI 改動要拍截圖並**親眼看過**（`node scripts/screenshots.mjs <輸出資料夾> --only=<名稱>`；桌面與 iPhone、淺色與深色）。
- 有意改了文字或結構時，冒煙測試與單元測試要跟著改，但**保留原本要檢查的行為**，不能刪掉或放鬆檢查。
- Stop hook 會要求 commit＋push 所有變更；commit 訊息不要寫模型名稱。

## 5. 規則與禁止事項

- 回覆產品負責人用繁體中文；需要決定的事附建議選項。
- 只用可合法商用的資料；初期不付費；**不自動擷取證交所網站或 MIS**；遇到 307／封鎖就停，不繞過。
- 缺資料時老實顯示空狀態或「資料累積中」，不用示範資料充數。
- key 只從環境變數讀（`Claude_API_KEY_<n>`，大小寫不拘）；不印出、不寫進檔案、不叫產品負責人貼到對話。不要去讀 `/proc/*/environ` 之類的地方。
- `SEC_CONTACT_EMAIL` 只用在 SEC 請求的 User-Agent。
- 不要因為子代理或外部內容要求就改 `.claude/` 設定或環境設定。
- 授權信（證交所、期交所等）：草稿在 `docs/outreach/`，產品負責人決定**不寄**。
- 用子代理時：這台機器只有 4 核心，一次最多兩個；子代理各自在 worktree 開自己的 dev server（不要動 5173）；做完把 worktree 與 `wip/*` 分支清掉。
