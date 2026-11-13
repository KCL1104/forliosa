> 本資料夾的文件都是草稿，供產品負責人與律師審閱，不是法律意見。

# 隱私權政策與服務條款草稿：給產品負責人的說明

| 檔案 | 內容 |
|---|---|
| [`privacy-policy.md`](privacy-policy.md) | 隱私權政策（草稿） |
| [`terms-of-service.md`](terms-of-service.md) | 服務條款（草稿） |
| `README.md`（本檔） | 待填的空格、每句敘述的依據、產品還沒做到的承諾、請律師確認的事、連結要放在哪裡 |

兩份草稿是依 2026-11-13 的程式與文件寫的，只寫產品**實際**會做的事。程式或設定改了（尤其是 (c) 末段列的環境變數），草稿要跟著改。草稿用「你」稱呼使用者（和 app 的語氣一致）；要改成「您」可以整份取代。

**撰寫時無法核對的事（重要）**：這次工作的網路環境連不到全國法規資料庫（`law.moj.gov.tw`）、臺北市法規查詢系統（`laws.gov.taipei`）與 Anthropic 的隱私說明網站（`privacy.claude.com`）。因此：

- 草稿裡的法條條號是依記憶寫的，全部標了【待確認：條號與現行條文】，請律師對照現行條文。
- AI 服務供應商（Anthropic）怎麼保存資料、是否用於訓練，**沒有寫進草稿**，留了【待填】，見 (d) 第 5 點。

---

## (a) 要你填的空格

### 已經填好的（你 2026-11-13 提供）

| 項目 | 填入的內容 | 出現在 |
|---|---|---|
| 營運者／蒐集者名稱 | 「Forliosa（個人經營）」（個人，沒有公司） | 隱私 §1、條款前言 |
| 聯絡信箱 | support@forliosa.trade（個資請求、一般聯絡；草稿也把它當作申訴與權利人通知的信箱） | 隱私 §1、§10.2、§15；條款前言、§6.4、§6.5、§6.7、§11.4、§15 |
| 網站 | <https://forliosa.trade>（API：`https://api.forliosa.trade`） | 隱私 §1、條款前言 |

> **2026-11-13 更新（產品負責人：都照建議）**：第 2、7、8、9、10、11、12、13、14 項已照下表的建議填進兩份草稿（通訊地址不公開、最低年齡 18、用登記的 Email 確認本人、不收費、外洩時寄信並公告、重大變更 14 天前在 app 內公告、收費前另行公告並取得同意、申訴 14 天內回覆、終止服務 30 天前公告）。
> 還沒填的：第 1 項生效日期（開放註冊當天）、第 5 項（備份：Railway 目前的方案不能開，等產品負責人決定做法；第 3、4 項已在 2026-11-13 部署後填好）、第 6 項（要先讀 AI 服務供應商公布的條款）、第 15 項責任上限與第 16 項管轄法院（產品負責人與律師決定）。
> **2026-11-13 已完成**（兩份草稿已照實際的做法改寫：隱私 §10、條款 §6.5、§12）：自助刪除帳號、匯出我的資料、`/terms` 與 `/privacy` 頁面、登入頁的同意文字與同意版本紀錄（`TERMS_VERSION`，定稿那天才設）、條款更新時登入後的一行通知、登出時清掉瀏覽器裡的 AI 對話。另外新增一項要律師看的：帳號刪除時若公開發言正在停權，會保留一筆不可逆的識別雜湊（隱私 §10.3）。
> **要先處理、否則草稿有一句不實**：正式環境的網頁目前被 Cloudflare 自動插入了 Web Analytics 的程式（`static.cloudflareinsights.com/beacon.min.js`，2026-11-13 實測），但隱私權政策開頭與 §2 寫「沒有任何第三方的流量分析或追蹤程式、沒有外部腳本」。要在 Cloudflare 後台把 Web Analytics 關掉（建議），或把那兩句改成照實揭露。API token 找不到這個開關，要產品負責人在後台處理。
> 原本的決定：自助刪除帳號、匯出我的資料、`/terms` 與 `/privacy` 頁面、登入頁的同意文字與同意版本紀錄（合約：`docs/api-contract.md`「帳號：匯出資料、刪除帳號、條款版本」）。做完後 (c) 的對應項目要更新。

### 還要填的【待填】（原本 16 種；已填的在表裡劃掉。兩份草稿裡的字樣和下表完全相同，可以直接搜尋）

| # | 空格 | 檔案 | 要決定什麼 | 建議 |
|---|---|---|---|---|
| 1 | 【待填：生效日期】 | 兩份 | 兩份文件的生效日 | 正式開放註冊當天 |
| 2 | 【待填：營運者通訊地址（是否公開由產品負責人決定）】 | 隱私 §1 | 個人經營要不要公開地址 | A. 不列地址、只列信箱；B. 列一個非住家的收件地址。建議 A，但請律師確認個人經營者是否必須揭露（見 (d) 第 11 點） |
| 3 | ~~【待填：主機所在地區（Railway 的區域）】~~ | 隱私 §4.1 | 資料實際放在哪裡 | **已填（2026-11-13）**：新加坡。api、worker、PostgreSQL 都部署在 Railway 的 `asia-southeast1` 區域；API 的 DNS 是「DNS only」，不經 Cloudflare 代理，§4.1 的【待確認】一併拿掉 |
| 4 | ~~【待填：伺服器紀錄保存期間】~~ | 隱私 §7 | 存取紀錄（含 IP）留多久 | **已填（2026-11-13）**：7 天。Railway 文件〈Logs〉的 Log retention：Hobby 方案 7 天、Pro 方案 30 天；目前是 Hobby。**升級方案時這一格要改** |
| 5 | 【待填：資料庫備份的做法與保存期間】 | 隱私 §7 | 有沒有備份、留多久 | **還不能填**：Railway 的 volume 備份只給 Pro 方案（2026-11-13 API 回覆，目前是 Hobby），所以現在**沒有備份**。等產品負責人決定：A. 升級 Pro 用內建備份（每日保存 6 天、每週保存 1 個月）；B. 每天 `pg_dump` 到 Cloudflare R2，保存天數自己定；C. 寫明「目前沒有備份」。正式開放前要定案 |
| 6 | 【待填：AI 服務供應商如何保存送出的內容、是否用於訓練模型】 | 隱私 §5.7 | 照 Anthropic 當時公布的條款寫 | 見 (d) 第 5 點的網址，讀完再填；不要憑印象寫 |
| 7 | 【待填：最低年齡】 | 隱私 §12、條款 §3.2 | 幾歲可以用 | A. 18 歲（最單純，不必處理法定代理人同意）；B. 比照 Discord 的年齡下限，未成年需法定代理人同意。建議 A |
| 8 | 【待填：確認申請人是本人的方式】 | 隱私 §10.2 | 刪除帳號、索取副本時怎麼驗證 | 要求用帳號登記的 Email（Discord 已驗證的那個）寄信，並回信到同一個 Email 確認 |
| 9 | 【待填：是否收取查詢或複製本的必要成本費用】 | 隱私 §10.2 | 個資法允許酌收成本 | 不收費 |
| 10 | 【待填：資料外洩時通知使用者的方式】 | 隱私 §9 | 出事時怎麼通知 | 寄到帳號登記的 Email，並在網站公告（目前都要人工做，見 (c) 第 9 點） |
| 11 | 【待填：重大變更的通知方式與提前天數】 | 隱私 §14、條款 §13 | 改條款怎麼通知 | 生效前 14 天在 app 內公告（公告功能要先做，見 (c) 第 9 點） |
| 12 | 【待填：之後如果收費，如何通知並取得同意】 | 條款 §1.3 | 未來收費的程序 | 「收費前會另行公告並取得你的同意，不同意可以停止使用」；或在決定商業化前先刪掉這句 |
| 13 | 【待填：申訴的回覆時間】 | 條款 §6.5 | 被隱藏或停權的人來信，多久回 | 14 天 |
| 14 | 【待填：終止服務的提前公告天數】 | 條款 §11.6 | 收掉服務前多久公告 | 30 天 |
| 15 | 【待填：責任上限金額】 | 條款 §12.3 | 賠償上限 | 由律師決定；常見寫法是「你在過去 12 個月付給我們的費用，或新臺幣○○元，取較高者」 |
| 16 | 【待填：第一審管轄法院】 | 條款 §14 | 合意管轄 | 你住所地的地方法院（例如臺灣○○地方法院）；請律師確認對消費者的效力 |

（第 1、7、11 項在兩份文件各出現一次，所以是 16 種空格、19 處。）

### 草稿裡的【待確認】（共 9 種）

| 標記 | 檔案 | 說明 |
|---|---|---|
| 【待確認：條號與現行條文】 | 隱私 §4.1、§9、§10、§10.2、附表；條款 §2.2 | 個資法第 3、8、9、12、13、21 條與證券投資信託及顧問法第 4 條，條號與內容未能上網核對 |
| 【待確認：法定依據（個資法第 19 條、第 20 條）的寫法】 | 隱私 §3 | 草稿寫「服務約定＋同意」 |
| 【待確認：上線時 API 是否經 Cloudflare 代理】 | 隱私 §4.1 | `docs/deploy.md:255-258` 寫 `api` 先用 DNS only；若改成經 Cloudflare 代理，Cloudflare 就會經手帳本資料，要改這一格 |
| 【待確認：各供應商的公司所在地與實際資料存放地】 | 隱私 §4.1（Anthropic、Discord） | 草稿只寫「境外」 |
| 【待確認：Telegram 的營運主體與所在地】 | 隱私 §4.1 | 同上 |
| 【待確認：授權範圍與期間的寫法（著作權法）】 | 條款 §4.3 | 公開貼文的授權 |
| 【待確認：是否需要依著作權法訂定「通知／取下」與重複侵權的處理程序】 | 條款 §6.7 | 見 (d) 第 9 點 |
| 【待確認：責任限制條款在消費者保護法與民法下的效力】 | 條款 §12.4 | 見 (d) 第 8 點 |
| 【待確認：合意管轄條款對消費者的效力】 | 條款 §14 | 見 (d) 第 8 點 |

### 草稿替你做的承諾（不是空格，但請你確認願意承諾）

1. 沒有廣告、不販售資料、不把資料提供給別人做行銷、不寄行銷信（隱私「重點先講」、§3）。現況屬實（程式沒有廣告、分析或寄信功能），但寫進政策後，之後要放廣告或寄行銷信就要先改政策。
2. 營運者只在維護系統、排除錯誤、處理請求或依法配合時存取資料庫（隱私 §4.3）。
3. 15 天／30 天內回覆個資請求（隱私 §10.2，法定期限）。
4. 發現未達年齡的帳號會刪除（隱私 §12）。
5. 收到權利人或媒體通知後會隱藏內容或移除該媒體的標題（條款 §6.7）。
6. 申訴會回覆（條款 §6.5）。

---

## (b) 草稿裡每一句「產品怎麼處理資料」的依據

路徑以 repo 根目錄為準；`api/` 指 `apps/api/src/forliosa/`，`web/` 指 `apps/web/`。行號是 2026-11-13 的版本；只寫函式或常數名稱的，是我沒有逐行確認行號的地方。

### 隱私權政策

| # | 位置 | 敘述（摘要） | 依據 |
|---|---|---|---|
| P1 | 重點、§2.1 | 只用 Discord 登入；授權範圍 `identify email`；取得使用者編號、名稱、頭像、Email 與是否已驗證 | `api/services/discord_oauth.py:48`（`SCOPE`）、`:114-132`（`DiscordProfile`）、`:140-178`（`fetch_profile`）；`docs/api-contract.md:770-781` |
| P2 | §2.1 | 顯示名稱只在第一次登入取自 Discord，之後不同步 | `api/services/discord_oauth.py:182-218`（`sign_in`：既有帳號只更新 Email 與頭像，新帳號才設 `display_name`） |
| P3 | §2.1 | 每次登入更新 Email 與頭像；建立帳號要求 Email 已驗證 | `api/services/discord_oauth.py:191-202`；`docs/api-contract.md:778-780` |
| P4 | §2.1、§9 | 不保存 Discord 權杖，讀完就提出撤銷；Discord 回傳的其他欄位不保存 | `api/services/discord_oauth.py:155-161`、`:172-178`；`api/models.py:826-828`；`apps/api/CONTRACT_NOTES.md:1266-1267` |
| P5 | §2.1 | 記錄帳號建立與最後登入時間 | `api/models.py:35`、`:841-842` |
| P6 | §2.2 | 個人設定：顯示名稱、公開暱稱、顯示偏好 | `api/models.py:27-41`；`docs/api-contract.md:45-52` |
| P7 | §2.2 | 帳本欄位（帳戶、交易、持股快照、自選、定期定額） | `api/models.py:53-66`、`:73-99`、`:123-136`、`:306-313`、`:332-350` |
| P8 | §2.2 | 系統自動記股利、標示「自動」 | `PRODUCT.md:111`；`api/models.py:95-97`、`:104-120` |
| P9 | §2.2 | 不連接券商、不取得券商密碼、身分證字號、銀行帳號、付款資料 | `PRODUCT.md:47`；`api/models.py`（沒有這類欄位）；`apps/api/pyproject.toml:7-19`（沒有金流套件） |
| P10 | §2.3 | 群組成員身分、分享設定與開啟時間、留言表情、授權、邀請只存雜湊、webhook 加密、Telegram 聊天室編號與名稱 | `api/models.py:845-866`、`:869-911`、`:914-927`、`:930-952`、`:977-997`；`api/crypto.py`（`token_hash`、`encrypt_secret`）；`api/services/groups.py:250-254`；`api/services/channels.py:263-290` |
| P11 | §2.4 | 主題、回覆、表情、檢舉、停權紀錄、發言時間紀錄（不含內容） | `api/models.py:1223-1335` |
| P12 | §2.5 | AI 對話與查到的資料原樣保存、草稿、用量紀錄不含內容；法人觀點記錄發起人 | `api/models.py:354-442`、`:474`；`api/ai/analyst.py:246`、`:264` |
| P13 | §2.6、§9 | 登入狀態：伺服器只存 Cookie 的雜湊、帳號與到期時間 | `api/api/deps.py:23-37`；`api/models.py:44-50` |
| P14 | §2.6 | 存取紀錄含 IP、時間、路徑、結果；敏感參數遮蔽；不寫入資料庫 | `apps/api/Dockerfile:34`（uvicorn 預設開啟 access log，加 `--proxy-headers`）；`api/logredact.py:18-30`、`:61-65`；`docs/deploy.md:59`。**這是依 uvicorn 的預設行為推論的，沒有在正式環境實際看過 log，部署後請確認** |
| P15 | §2.6、§7 | 只記「哪檔股票最近被看過」與時間，不記是誰；30 天後刪除 | `api/models.py:1073-1080`；`api/news/service.py:145-156`、`:274-275`；`api/config.py:142` |
| P16 | 重點、§2.7 | 沒有第三方分析、追蹤、廣告程式，沒有外部字型或腳本 | `apps/web/index.html`（只有本地 script）；`apps/web/package.json`（`dependencies` 沒有分析套件，字型是內含的 `@fontsource-variable/noto-sans-tc`）；2026-11-13 在 `apps/web/src`、`index.html`、`public` 搜尋 `gtag、google-analytics、googletagmanager、sentry、posthog、plausible、mixpanel、amplitude、hotjar、clarity、umami、sendBeacon、fonts.googleapis、serviceWorker` 都沒有結果 |
| P17 | §2.7、§5.4 | AI 搜尋用固定的「台北」當大約位置 | `api/ai/tools.py:61-62`、`:822-824` |
| P18 | §3 | AI 每人每天、每月上限 | `api/config.py:98-99`；`api/ai/store.py:346-352` |
| P19 | §3 | 不寄行銷信（實際上沒有任何寄信功能） | `apps/api/pyproject.toml:7-19`；在 `apps/api/src` 搜尋 `smtplib、sendgrid、mailgun、send_mail、send_email` 沒有結果 |
| P20 | §4.1 | Railway 放 API、背景工作、資料庫；Cloudflare Pages 放前端；API 目前不經 Cloudflare 代理 | `docs/deploy.md:5-12`、`:250-258` |
| P21 | §4.1 | 頭像由瀏覽器直接向 Discord 的圖片伺服器讀取 | `api/services/discord_oauth.py:47`、`:123-125`；`web/src/components/avatar.tsx:12` |
| P22 | §4.1、§6.2 | 推播送到 Discord webhook／Telegram Bot API | `api/services/pushers.py:186-205`、`:235-237` |
| P23 | §4.1 | 對外查詢市場資料與新聞時只有股票代號與公司名稱；對象是有人持有、觀察或最近看過的股票；SearXNG 自架、只對內 | `api/config.py:136-168`；`PRODUCT.md:94-96`；`api/news/service.py:145-165`；`docs/deploy.md:10`、`:158-173`；`web/src/pages/data-sources/DataSourcesPage.tsx:123` |
| P24 | §4.3 | 站方管理員只處理公開內容，看不到 Email、帳號編號、群組內容 | `api/services/discussions.py:108-117`、`:590-599`、`:601-650`；`docs/api-contract.md:1141-1153` |
| P25 | §4.3 | 資料庫內容除 webhook 網址外沒有另外加密 | `api/crypto.py`（只有 `channel-webhook` 一種加密用途）；`api/models.py`（其餘欄位為一般型別）。`docs/product-spec.md:422` 寫的「資料庫加密、後台存取留稽核紀錄」**沒有實作** |
| P26 | §5.1 | AI 請求的內容：問題、對話歷史、頁面情境、工具查到的本人帳本資料 | `api/ai/chat.py:163-172`（`params`：只有 system、tools、messages，沒有使用者識別欄位）、`:380-383`；`api/ai/prompts.py:202-221`；`api/ai/tools.py:160-167`、`:189-297`、`:489-507`；`api/models.py:375-378`；`apps/api/CONTRACT_NOTES.md:1087-1091` |
| P27 | §5.2 | 不送出顯示名稱、Email、Discord 編號、帳號編號、IP；AI 只讀本人資料、不讀討論 | `api/ai/prompts.py:1-7`、`:15-50`（系統提示固定，不含使用者資訊）；`apps/api/CONTRACT_NOTES.md:1107`（工具沒有使用者 id 欄位）；`docs/api-contract.md:558`、`:826`、`:1093`；`api/services/discussions.py:13` |
| P28 | 重點、§5.3 | 隱私模式只要求 AI 不寫出絕對數字，資料照樣送出 | `api/ai/prompts.py:50`、`:213`；`api/ai/tools.py`（工具不看隱私模式） |
| P29 | §5.4 | 網路搜尋與讀取網頁由 AI 服務供應商執行，關鍵字由 AI 決定 | `api/ai/tools.py:816-846`；`api/ai/prompts.py:30-32`；`api/config.py:107-112` |
| P30 | §5.5 | 群組週報只送匿名代號與數字；為什麼漲跌、法人觀點、新聞補充、公司簡介只送股票資訊 | `api/services/digests.py:66-74`、`:128-149`；`docs/api-contract.md:1001-1003`；`api/ai/prompts.py:179-181`、`:224-242` |
| P31 | §5.6 | AI 不寫入帳本，只產生草稿 | `api/models.py:400-402`；`docs/api-contract.md:558` |
| P32 | §5.7、§7 | AI 對話、訊息、草稿最後活動後 30 天刪除；可逐段刪除；用量紀錄保留；瀏覽器端也留 30 天 | `api/ai/retention.py:43-66`；`api/config.py:126`；`api/worker.py:226`；`api/api/routes/ai.py:86`；`api/models.py:420-429`；`web/src/ai/store.ts:52`、`:132-150` |
| P33 | §6.1 | 分享開關與預設值、關掉立即生效、不標示誰沒分享、可推算股數、留言顯示「已離開的成員」、加入動態、邀請預覽、授權候選名單 | `api/services/sharing.py:79-88`；`api/models.py:890-911`；`docs/api-contract.md:750-755`、`:882-890`、`:983-988`；`api/services/groups.py:288-299`；`api/services/delegations.py:55-62` |
| P34 | §6.2 | 推播內容、本人要開、換頻道自動關閉 | `docs/api-contract.md:1009-1020`；`api/services/notifications.py:135-173`；`api/services/channels.py:124-130` |
| P35 | §6.3 | 授權查看看得到與看不到的範圍；不會因離開群組自動撤銷 | `api/api/middleware.py`（`VIEW_AS_READ_PATHS`、`ViewAsMiddleware.classify`）；`docs/api-contract.md:812-826` |
| P36 | §6.4 | 公開內容不用登入可讀、只顯示公開暱稱；群組內容顯示名稱與頭像；帳號刪除後內容保留 | `api/services/discussions.py:293-303`；`docs/api-contract.md:1070-1079`；`api/models.py:1224-1226`、`:1238`、`:1265` |
| P37 | §7 | 各項保存期間 | 登入 30 天：`api/config.py:30`、`api/api/deps.py:28-37`、`:48-55`；OAuth Cookie 10 分鐘：`api/services/discord_oauth.py:49`、`api/api/routes/auth.py:46-47`；法人觀點 24 小時：`api/ai/analyst.py:94`、`:158-160`、`api/worker.py:227`；週報 26 週：`api/services/digests.py:56`、`:379-390`；動態 90 天與連動刪除：`api/services/sharing.py:83`、`:667`；推播紀錄 30 天、連結碼：`api/services/notifications.py:49-50`、`:290-297`、`api/models.py:1025-1027`；邀請期限：`api/services/groups.py:42`；發言時間紀錄：`api/models.py:1323-1326`、`api/services/discussions.py:69`；檢舉隨主題刪除：`api/models.py:1299` |
| P38 | §8 | 兩個 Cookie 與屬性；瀏覽器儲存的項目；登出不清除 | `api/api/deps.py:20`、`:34-37`；`api/services/discord_oauth.py:76-77`；`docs/api-contract.md:774-776`；`web/index.html:13-21`；`web/src/stores/prefs.ts:55-58`；`web/src/pages/ledger/ledger-prefs.ts:54`；`web/src/stores/watchlist.ts:17`；`web/src/ai/store.ts:132-150`；`web/src/api/view-as.ts:27-31`；`web/src/app/AvatarMenu.tsx:109`（登出只呼叫 API 後重新整理） |
| P39 | §9 | 安全措施 | HTTPS 與啟動檢查：`api/api/app.py`（`check_production_settings`）；換發登入狀態：`api/api/deps.py:40-45`；跨站請求檢查：`api/api/middleware.py`（`OriginCheckMiddleware`）；資料限定本人與分享規則：`api/models.py:1`、`api/services/sharing.py:1-22`、`api/services/scope.py`；雜湊與加密：`api/crypto.py`；紀錄遮蔽：`api/logredact.py`；頻率限制：`api/services/discussions.py:61-71`、`api/services/channels.py:73-100` |
| P40 | §10.1 | 可以自助做的事；公開暱稱 7 天冷卻；貼文不能編輯 | `api/api/routes/users.py:62-74`；`api/api/routes/transactions.py:126-133`；`api/api/routes/accounts.py:66-85`；`api/api/routes/ai.py:86`；`docs/api-contract.md:798`、`:841`、`:848`、`:1115`、`:1118`；`api/services/discussions.py:70`；`PRODUCT.md:79` |
| P41 | 重點、§10.2 | 沒有自助刪除帳號、匯出、一次刪除全部 AI 對話 | `api/api/routes/users.py`（沒有刪除帳號的端點）；`docs/api-contract.md:1035`（「之後提供刪除帳號時」）；`api/api/routes/`（沒有匯出端點）；`apps/api/CONTRACT_NOTES.md:1220` |
| P42 | §10.3 | 刪除帳號後哪些刪除、哪些保留 | `api/models.py` 的外鍵設定：`CASCADE`（`:48`、`:57`、`:81`、`:365`、`:388`、`:408`、`:852-853`、`:885`、`:1315`）與 `SET NULL`（`:429`、`:940`、`:1238`、`:1265`、`:1300`）；`docs/api-contract.md:1035`、`:1076`。**群組轉交目前只是合約裡的規劃，還沒有程式**（見 (c) 第 1 點） |
| P43 | §11 | 沒有已驗證 Email 不能建立帳號；沒登入可讀公開討論與資料來源 | `api/services/discord_oauth.py:201-202`；`docs/api-contract.md:1070`、`:1079`；`api/api/app.py`（`/meta/attributions` 不需登入） |
| P44 | §12 | 目前沒有驗證年齡 | 程式裡沒有相關欄位或檢查 |

### 服務條款

| # | 位置 | 敘述（摘要） | 依據 |
|---|---|---|---|
| T1 | §1 | 帳本與資訊工具；不連接券商、不能下單 | `PRODUCT.md:27-33`、`:47` |
| T2 | §1.3 | 目前不收費 | 程式沒有金流；`PRODUCT.md:17`、`:23`、`:57`（是否商業化尚未決定） |
| T3 | §2.3 | 收盤價、非即時、公布時間、美股與上市法人資料目前沒有 | `docs/api-contract.md:1037-1059`；`PRODUCT.md:78`、`:105`、`:108-109`；`web/src/pages/data-sources/DataSourcesPage.tsx:61-63`、`:114` |
| T4 | §2.4 | 稅費、股利、績效是估算；自動股利可改可刪 | `PRODUCT.md:29`、`:111`；`docs/api-contract.md:201-241` |
| T5 | §2.6 | 法人觀點是第三方看法；新聞只列標題與連結 | `PRODUCT.md:94`、`:110`；`api/ai/prompts.py:137`；`api/models.py:1039-1042` |
| T6 | §3.1 | Discord 登入、需已驗證 Email、第一次登入自動建立帳號 | `docs/api-contract.md:778-785`；`web/src/pages/auth/LoginPage.tsx:38` |
| T7 | §3.5 | 顯示名稱 1–30 字；公開暱稱 2–20 字、唯一、保留字、7 天冷卻 | `api/api/schemas.py:55-63`；`docs/api-contract.md:1077-1079`；`api/services/discussions.py:70`、`:145-171` |
| T8 | §4.3 | 公開內容顯示在清單、個股頁、摘要 | `PRODUCT.md:72-73`；`docs/api-contract.md:1070`、`:1112`、`:1126` |
| T9 | §4.5 | AI 不讀討論、不替人發言 | `PRODUCT.md:77`；`docs/api-contract.md:1093` |
| T10 | §4.7 | 不能編輯；刪主題連同回覆、表情、檢舉 | `PRODUCT.md:79`；`docs/api-contract.md:1087`；`api/services/discussions.py:463-485` |
| T11 | §6.1 | 公開討論頁底部固定一行聲明 | `web/src/pages/discussions/labels.ts:6`；`docs/api-contract.md:1154` |
| T12 | §6.3 | 發言頻率、字數、標記股票上限 | `api/services/discussions.py:61-68`；`docs/api-contract.md:1082-1091`、`:1102`、`:1113` |
| T13 | §6.4 | 檢舉的理由、次數限制、不能檢舉群組內容 | `api/services/discussions.py:71`、`:559-587`；`api/api/schemas_discussions.py:30`；`web/src/pages/discussions/labels.ts:13-18` |
| T14 | §6.5 | 隱藏、暫停公開發言（1／7／30 天或永久）、不處理檢舉；不另外通知 | `api/services/discussions.py:265-270`、`:652-664`、`:680-705`；`docs/api-contract.md:1085-1092`、`:1147-1150`；`web/src/pages/discussions/labels.ts:8-11`；程式沒有通知功能 |
| T15 | §6.6 | 站方不處理群組內容；群組管理者可刪除、移除成員；刪群組連同內容 | `api/services/discussions.py:251-256`、`:472-475`、`:590-599`；`docs/api-contract.md:838`、`:841`、`:855`、`:1139` |
| T16 | §6.7 | 媒體可要求移除標題 | `api/models.py:1062-1069`；`PRODUCT.md:94` |
| T17 | §7 | 預設只分享報酬率、推播要本人開、換頻道自動關閉、擁有者要先轉移、邀請期限、授權不自動撤銷、人數上限 | `api/services/sharing.py:79-80`；`api/services/groups.py:40-42`；`docs/api-contract.md:755`、`:758`、`:812`、`:841-846`、`:1018-1020` |
| T18 | §8.1 | AI 只處理投資相關問題 | `api/ai/prompts.py:17-21`；`api/ai/scope.py:50` |
| T19 | §8.2 | 列出引用來源、標示無來源（可能漏標誤標）、固定聲明 | `api/ai/grounding.py`；`api/ai/prompts.py:60`；`apps/api/CONTRACT_NOTES.md:1100-1105`、`:1226` |
| T20 | §8.3 | AI 只產生草稿，確認後才寫入；沒寫價格時用收盤價估算 | `api/ai/tools.py:524-636`；`api/ai/prompts.py:36-40`；`PRODUCT.md:84` |
| T21 | §8.4 | AI 不給目標價；可引用第三方評等 | `api/ai/prompts.py:46`、`:72-97` |
| T22 | §8.5 | 每天 50 則、每月 300 萬計費 token；被婉拒的問題與法人觀點查詢各算一則；對話太長要開新對話 | `api/config.py:98-100`；`api/ai/store.py:329-352`；`docs/api-contract.md:586`、`:588`、`:632`；`apps/api/CONTRACT_NOTES.md:1232` |
| T23 | §9 | 資料來源與授權 | `api/datapolicy.py:54-92`、`:468-515`；`docs/research/data-sources-licensing.md`；`GET /meta/attributions`（`api/api/app.py`） |
| T24 | §11.5 | 產品內建的處置只有隱藏與暫停公開發言 | `api/models.py:27-41`（`User` 沒有停用欄位）；`api/services/discussions.py` |

---

## (c) 草稿承諾了、但產品還沒做到的事（要做出來，或把那句話拿掉）

依重要性排列。前五項建議在開放註冊前處理。

1. **刪除帳號**（隱私 §10.2、§10.3；條款 §11.4）。沒有端點也沒有畫面。個資法給使用者刪除的權利，所以草稿寫「來信人工處理」。你至少要有一套可重複執行的人工流程（腳本）：刪除使用者資料、把他擁有的群組轉給最早的管理員或成員（`docs/api-contract.md:1035` 的規劃，尚無程式）、確認貼文變成「已刪除的帳號」。之後做成自助功能時把草稿改掉。`docs/product-spec.md:425` 原本就寫要提供。
2. **資料副本／匯出**（隱私 §10.2；條款 §11.6）。沒有匯出功能。同樣是法定權利，至少要有人工匯出的腳本。條款 §11.6「終止服務時說明如何取得資料副本」也依賴它。
3. **登出不清除瀏覽器裡的 AI 對話紀錄**（隱私 §8 已照實寫）。`forliosa:ai` 留在瀏覽器（`web/src/ai/store.ts:132-150`），登出只重新整理（`web/src/app/AvatarMenu.tsx:109`）。同一台瀏覽器換另一個帳號登入時，前一個人的對話是否會顯示出來，我沒有實際測；建議確認，並在登出或換帳號時清除。修好後把隱私 §8 的粗體提醒改掉。
4. **同意的紀錄與入口**（條款前言寫「登入即同意」）。登入頁目前沒有任何條款文字或連結（`web/src/pages/auth/LoginPage.tsx`），也沒有記錄使用者同意了哪一版。至少要在登入按鈕旁加上一行並連到兩份文件（見 (e)）；建議另外記錄同意的版本與時間。
5. **備份、監控、紀錄保存**（隱私 §7 的兩個空格；條款 §11.3）。目前沒有備份與監控（`docs/deploy.md:302`）。之後如果加錯誤追蹤（例如 Sentry）或分析工具，隱私 §2.7、§4.1 要先改。
6. **一次刪除全部 AI 對話**（隱私 §10.2 寫來信處理）。目前只能逐段刪（`apps/api/CONTRACT_NOTES.md:1220` 也列為待確認）。
7. **過期的登入紀錄沒有清除**。`purge_expired_sessions`（`api/api/deps.py:109-112`）沒有任何地方呼叫，過期的列（雜湊、帳號、時間）會一直留在資料庫。草稿只寫「到期後失效」，沒有說會刪除；建議排進 worker。
8. **AI 用量紀錄沒有保存期限**（隱私 §7 照實寫「持續保留」）。含帳號編號與時間；建議訂一個期限（例如 13 個月）並實作。
9. **通知機制**（隱私 §9、§14；條款 §13）。沒有寄信功能，也沒有 app 內公告。條款變更、資安事故通知目前都只能你自己從 support@forliosa.trade 手動寄信（收件地址在資料庫的 `users.email`）。建議做一個登入後的公告橫幅。
10. **年齡**（隱私 §12；條款 §3.2）。沒有年齡確認。至少在登入頁加一句「我已年滿○歲」。
11. **停用帳號**（條款 §11.5 寫「由我們人工處理」）。`User` 沒有停用欄位，現在只能直接改資料庫。另外，停權紀錄會隨帳號刪除而消失（`api/models.py:1315`），被永久停權的人請你刪除帳號後重新註冊，停權就沒了；條款 §5.4 禁止這樣做，但程式擋不住。
12. **申訴**（條款 §6.5）。沒有 app 內的申訴流程，靠來信；管理端可以恢復內容與解除停權（`api/services/discussions.py:652-664`、`:699-705`）。
13. **公開討論頁沒有「不讓搜尋引擎收錄」的標記**。`docs/pending-decisions.md:270`（N-4）建議條款準備好之前先加上。隱私 §6.4 已提醒公開內容可能被他人保存。
14. **資料庫加密與存取稽核**。`docs/product-spec.md:422` 寫了，但沒有實作；草稿**沒有**宣稱（隱私 §4.3 照實寫沒有另外加密）。之後做了可以把 §9 補上。
15. **邀請連結預覽**不用登入就顯示群組名稱與邀請人的顯示名稱（`api/services/groups.py:288-299`）。草稿已照實寫（隱私 §6.1、條款 §7.6），這是提醒不是缺口。
16. **隱私模式**不影響送給 AI 的資料（隱私 §5.3 已照實寫）。建議在隱私模式的開關或 AI 輸入框旁加一句說明，避免誤會。
17. **AI 用量**：條款 §8.5 的數字後端有（`GET /ai/usage`），但我在前端沒找到顯示剩餘額度的畫面；建議顯示，讓使用者知道自己用了多少。

**設定改了就要改草稿的地方**：`AI_RETENTION_DAYS`（30 天；設 0 是永久保存）、`AI_DAILY_MESSAGE_LIMIT`／`AI_MONTHLY_TOKEN_BUDGET`（50／300 萬）、`SESSION_TTL_DAYS`（30）、`NEWS_VIEW_DAYS`、`DATA_POLICY`（改成 `personal` 會用到非商用來源，條款 §9 不再正確）、`AI_WEB_SEARCH`／`AI_WEB_FETCH`、`AI_WEB_DYNAMIC_FILTERING`、`api` 改成經 Cloudflare 代理、Railway 區域。

---

## (d) 上線前請臺灣律師確認的事

1. **個資法條號與現行條文**。草稿引用第 3 條（當事人權利）、第 8 條（直接蒐集的告知）、第 9 條（間接蒐集的告知，用於 Discord）、第 12 條（事故通知）、第 13 條（15 天／30 天回覆期限）、第 14 條（成本費用）、第 19、20 條（蒐集與利用的依據）、第 21 條（國際傳輸）、第 27 條（安全措施）。這些是依記憶寫的。另請確認近年的修正（個人資料保護委員會、事故通報義務）是否已施行、對個人經營者有什麼新義務【待確認】。
2. **蒐集依據與同意方式**。「登入即同意」加上登入頁的連結，是否足以構成第 8、9 條的告知與第 19 條的依據；分享、推播、AI 是否需要另外取得同意（目前產品裡分享與推播是逐項開關，AI 沒有另外的同意畫面）。
3. **特定目的與個資類別代號**。草稿用白話寫目的，沒有列法務部公告的代號。可能適用的（依記憶，【待確認】）：〇六九 契約、類似契約或其他法律關係事務；〇九〇 消費者、客戶管理與服務；一三五 資（通）訊服務；一三六 資（通）訊與資料庫管理；一三七 資通安全與管理。類別：C001 辨識個人者、C002 辨識財務者、C081 收入、所得、資產與投資、C093 財務交易。要不要列進政策請律師決定。
4. **委外與國際傳輸**。Railway、Cloudflare、Anthropic、Discord、Telegram 在個資法下是受託人還是第三人；是否要和它們簽資料處理條款（各家通常有制式的）；第 21 條的限制是否適用；政策裡要不要寫出各家的國家。
5. **AI 服務供應商（Anthropic）的資料保存與訓練**。草稿留了【待填】。請讀 Anthropic 當時公布的頁面後再寫，至少確認：(a) 透過 API 送出的內容保存多久；(b) 是否用於訓練模型；(c) 被安全機制標記的內容是否保存更久；(d) 你的帳號是否有任何零資料保留的安排，以及它是否涵蓋本產品用到的功能。產品用到：一般的 Messages API（`claude-haiku-5-5`）、伺服器端的網路搜尋與網頁讀取工具、群組週報用的 Message Batches API（`api/services/digests.py`）。可以從這幾頁開始（網址是搜尋結果給的，**我沒能打開核對**）：
   - `https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data`
   - `https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training`
   - `https://platform.claude.com/docs/en/manage-claude/api-and-data-retention`
   - `https://privacy.claude.com/en/articles/15425996-data-retention-practices-for-covered-models`

   搜尋結果的摘要（未經核對，只供你知道要查什麼）提到：商用 API 的內容預設不用於訓練；保存期間依模型與功能不同；批次處理等功能不在零資料保留的範圍。請以原頁為準。
6. **未成年人**。最低年齡怎麼訂；未成年人使用是否需要法定代理人同意以及如何取得；兒童及少年福利與權益保障法對有公開討論區的網站有沒有額外要求【待確認】；Discord 自己的年齡規定。
7. **證券投資顧問法規**。條款 §2 聲明不是投顧。請確認下列功能在**免費**與**未來收費**兩種情況下，是否可能被認定為經營證券投資顧問業務（證券投資信託及顧問法第 4 條、第 107 條【待確認】）：AI 對個股的分析與「為什麼漲跌」；「法人觀點」引用第三方評等與目標價；群組的交易動態與排行（是否像帶單）；公開討論區（使用者招攬時站方的責任）。`PRODUCT.md:57` 把投顧法規列為尚未決定，`docs/pending-decisions.md:215-217` 建議在收費或放廣告前諮詢。
8. **消費者保護法與定型化契約**。免費服務是否構成消費關係；審閱期；條款 §12 的免責與賠償上限是否有效（消保法第 12 條、民法第 222 條、第 247 條之 1【待確認】）；條款 §14 的合意管轄對消費者與小額訴訟的效力；條款 §13「繼續使用視為同意」的效力。
9. **著作權**。條款 §4.3 公開貼文的授權範圍是否足夠且不過寬；使用者貼侵權內容時，網路服務提供者的免責要件（著作權法第六章之一，是否必須有通知／取下流程、聯絡窗口與重複侵權者的處理【待確認】），目前產品只能隱藏內容與暫停公開發言，沒有終止帳號的功能；新聞標題與連結、維基百科節錄的現行做法（已有研究：`docs/research/news-and-external-sources.md`）。
10. **討論區的法律風險**。使用者散布不實訊息影響股價（證券交易法第 155 條【待確認】）、誹謗、公開他人個資時站方的責任與處理義務；檢調或主管機關調閱使用者資料時的程序（隱私 §4.4）；是否需要保存發言者資料一定期間。
11. **個人經營**。個人作為個資法的「非公務機關」與消保法的「企業經營者」；蒐集者名稱寫「Forliosa（個人經營）」是否足夠，還是必須揭露本名或地址；個人要負的是無限責任，開放註冊或收費前是否應設立公司；是否需要商業登記或稅籍登記。
12. **個資安全維護的行業規定**。是否適用數位產業的個人資料檔案安全維護管理辦法之類的規定（安全維護計畫、事故通報時限）【待確認】。隱私 §9 只列了程式裡確實有的措施；備份、存取稽核、資料庫加密目前都沒有。
13. **個股頁顯示董事長、總經理姓名**。既有的待辦（`docs/research/news-and-external-sources.md:115`）；和這兩份文件無直接關係，但屬於同一次法律檢查。
14. **SearXNG 自動查詢上游搜尋引擎**違反對方條款的風險，你已決定承擔（`PRODUCT.md:94`）；資料來源頁已說明，條款 §9 沒有另外寫。請律師看是否要在條款裡提。
15. **Discord 與 Telegram 的開發者條款**。Discord 對使用登入資料的應用程式、Telegram 對 bot 是否有隱私權政策或資料刪除的要求【待確認】。
16. **政府資料開放授權條款**。條款 §9 的寫法（標示來源、不暗示政府背書）是否符合授權條款第 1 版。
17. **Cookie**。本服務只有登入必需的 Cookie，是否需要 Cookie 同意橫幅（我的理解是臺灣沒有專法要求，【待確認】）。
18. **語氣與形式**。用「你」還是「您」；是否需要英文版（Discord 開發者後台的審核若需要）。

---

## (e) 這兩份文件要放在哪裡、從哪裡連過去

**先決定網址。** 建議 `https://forliosa.trade/privacy` 與 `https://forliosa.trade/terms`。這兩頁必須**不用登入就能打開**：目前沒登入的人除了公開討論以外都會被導到登入頁（`web/src/app/AuthGate.tsx`），所以要放在公開的外殼（`web/src/app/PublicShell.tsx`）底下，或做成 `apps/web/public/` 裡的靜態頁。文件裡也要顯示版本的生效日期。

| 位置 | 檔案 | 建議 |
|---|---|---|
| 登入頁 | `web/src/pages/auth/LoginPage.tsx`（「用 Discord 登入」按鈕附近，約 :38–:61） | 加一行：「登入即表示你同意〈服務條款〉，並已閱讀〈隱私權政策〉。」兩個連結；若採最低年齡，一併寫「我已年滿○歲」 |
| 邀請頁 | `web/src/pages/groups/InvitePage.tsx` | 沒登入的人會先到這裡：在登入按鈕旁放同一行；確認分享開關的畫面連到隱私 §6 |
| 沒登入的公開討論頁 | `web/src/app/PublicShell.tsx`（目前只有字標與「登入」）；討論頁底部的聲明在 `web/src/pages/discussions/labels.ts:6` | 頁尾加〈服務條款〉〈隱私權政策〉〈討論區規則〉（條款 §6）三個連結，放在「使用者言論，不代表本站立場…」那一行旁邊 |
| 設定頁 | `web/src/pages/settings/SettingsPage.tsx`、`Profile.tsx` | 加「關於與法律」區：兩份文件的連結、聯絡信箱 support@forliosa.trade、之後的「匯出資料」「刪除帳號」入口 |
| 頭像選單 | `web/src/app/AvatarMenu.tsx`（「資料來源與授權」那一項，約 :72–:74） | 在它下面加「條款與隱私」 |
| 資料來源頁 | `web/src/pages/data-sources/DataSourcesPage.tsx` | 頁尾連到條款 §9 與隱私權政策 |
| 第一次公開發言 | `web/src/pages/discussions/PublicNamePrompt.tsx`、`NewTopicPage.tsx` | 設定公開暱稱或發第一則公開內容時，連到〈討論區規則〉（條款 §6），並提醒「公開內容任何人都能看到」 |
| 檢舉視窗 | `web/src/pages/discussions/ReportDialog.tsx` | 連到條款 §6.2 的禁止內容 |
| 群組分享開關、授權查看 | `web/src/pages/groups/`、`web/src/pages/settings/Delegations.tsx` | 開關旁的說明連到隱私 §6（別人看得到什麼） |
| 問 AI | `web/src/ai/`（輸入框或第一次使用時） | 一句「你的問題與查到的帳本資料會送到 AI 服務供應商」並連到隱私 §5；隱私模式的說明見 (c) 第 16 點 |
| 群組推播設定 | 群主設定頻道的畫面 | 連到隱私 §6.2（訊息送出後無法收回） |
| Discord 應用程式 | Discord Developer Portal → 你的應用程式 → General Information 的「Terms of Service URL」與「Privacy Policy URL」 | 填上面兩個網址。`docs/deploy.md` 第 2.4 節（:120–:134）建議之後補上這一步，`docs/deploy.md:292` 已把這兩份文件列為登入上線的前置條件 |
| Telegram bot | BotFather 的 bot 設定 | 若 Telegram 要求 bot 提供隱私權政策，填同一個網址【待確認】 |
| 搜尋引擎 | `web/index.html` 或公開討論頁 | 依 `docs/pending-decisions.md:270` 的建議，條款上線前先讓公開討論頁不被收錄；條款上線後再決定要不要開放 |

文件上線後，`docs/pending-decisions.md` 的 5-2 與 `docs/deploy.md:292` 可以更新狀態（這次沒有改任何既有檔案）。
