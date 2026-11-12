## 分享（M5）：登入、授權唯讀查看、親友群組（2026-11-12）

產品負責人決定（`PRODUCT.md`「分享（M5）範圍」）：照 `docs/product-spec.md` §4.8 一次做完；正式登入用 **Discord OAuth**、開放任何人註冊；
排行看今日、本月、今年，另外顯示總報酬率（含股利），可對照大盤與 0050；交易動態只顯示買賣哪一檔，可選擇附上價格，**沒有理由欄位**；
推播要本人另開「推播」開關；加入群組前先選分享；授權唯讀查看只能給同群組的成員。

### 共通規則

- **分享投影**：群組、授權查看、推播與 AI 週報讀別人的資料時，一律經過 `services/sharing.py`。投影依「這位成員目前在這個群組的分享設定」或
  「這份授權目前的範圍」過濾，**每次讀取時重新套用**（關掉開關、離開群組、撤銷授權，立刻看不到，包括過去的週報與動態）。
  沒開放的欄位**不出現在回應裡**（鍵不存在，不是 `null` 也不是 0）。測試必須逐項證明關掉的開關不會洩漏（金額、股數、交易價格、帳戶名稱、備註）。
- **不透露誰沒分享**：沒開放的成員不出現在排行、動態、持股裡，也沒有「未分享」標記；`SharedPortfolio` 沒開任何項目時只回身分欄位。
  前端不得拿成員名單去比對排行或動態，也不顯示「某某沒分享」；沒有資料時和「還沒有資料」顯示一樣的中性狀態。
- **精度**：分享投影裡的權重四捨五入到 0.01、報酬率到 0.0001。同時打開「持股」與「金額」時，別人可以推算大約股數：前端在開關旁提示。
- **存在與權限**：不是成員的人，群組相關端點一律 404 `not_found`（不透露群組是否存在）；是成員但權限不足回 403 `forbidden`。
- **CSRF**：非 `GET`／`HEAD`／`OPTIONS` 的請求若帶 `Origin`，必須在 `CORS_ORIGINS` 內，否則 403 `forbidden`（全站適用）。
- **上限**：每個群組最多 50 位成員；每人最多加入 20 個群組（超過回 409 `limit_reached`）。
- 錯誤代碼：`forbidden`、`not_found`、`read_only`、`view_as_not_allowed`、`delegation_revoked`、`already_member`、`invite_invalid`、
  `limit_reached`、`webhook_failed`、`oauth_*`（見登入）；格式錯誤一律 422 `validation_error`。

### 登入（Discord OAuth）與個人資料

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/auth/providers` | 不需登入：`{"discord": true, "dev_login": false}`（`discord` 依環境變數是否齊全） |
| GET | `/auth/discord/start?next=/invite/abc` | 302 到 Discord 授權頁（scope `identify email`、`prompt=none` 不帶） |
| GET | `/auth/discord/callback?code=&state=` | 驗證 state、換 token、讀 `/users/@me`；成功建立 session（輪換 session id）後 302 到 `{FRONTEND_URL}{next}`；失敗 302 到 `{FRONTEND_URL}/login?error=<code>` |
| PATCH | `/me` | `{"display_name"}`（1–30 字，去頭尾空白）→ `User`。群組裡顯示的就是這個名稱 |

- **state**：隨機值＋`next`，以 `SESSION_SECRET` 做 HMAC 簽章，存在 10 分鐘的 cookie（正式環境 `__Host-forliosa_oauth`：
  `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600`；開發環境不加 `__Host-` 前綴、不加 `Secure`）。callback 以固定時間比對，
  不論成敗都刪除這個 cookie（一次性）。不可用 `SameSite=Strict`（callback 是從 discord.com 來的跨站導覽）。
- **`next`**：解碼一次後必須符合 `^/(?![/\\])[\x21-\x7E]{0,511}$`，否則改成 `/`（避免 `//evil.com`、`/\evil.com`）。
- **帳號對應**：先以 Discord 使用者 id 找。找不到時，只有既有帳號**還沒連結任何 Discord id** 才以**已驗證**的 email 連結；那個 email
  已連結到別的 Discord id → `oauth_email_conflict`。都沒有就建立新帳號（`display_name` 取 Discord 的 global name，否則 username）。
  建立或連結時要求 Discord 回報 email 已驗證（否則 `oauth_email_unverified`）；已連結的帳號之後照常登入，每次登入更新 email 與頭像。
- 不儲存 Discord 的 access／refresh token（只用一次讀個人資料）。
- 失敗代碼：`oauth_disabled`、`oauth_denied`（使用者按取消）、`oauth_state`、`oauth_email_unverified`、`oauth_email_conflict`、`oauth_failed`。
- 環境變數：`DISCORD_CLIENT_ID`、`DISCORD_CLIENT_SECRET`、`DISCORD_REDIRECT_URI`（API 主機上的 callback 網址，與 Discord Developer Portal 設定一致）、
  `FRONTEND_URL`。`FORLIOSA_ENV=prod` 啟動時檢查：`FRONTEND_URL` 在 `CORS_ORIGINS` 裡、兩者與 `DISCORD_REDIRECT_URI` 都是 https，否則拒絕啟動。
- `POST /auth/dev-login` 照舊只在開發環境啟用。開放任何 Discord 帳號註冊；每人的 AI 額度照現有限制。
- `User` 新增 `avatar_url`（Discord 頭像網址，可為 `null`）。

### 授權唯讀查看（一對一）

只能授權給**和自己同在至少一個群組**的成員。

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/delegations` | `{"granted": Delegation[], "received": Delegation[]}`（我授權給別人的／別人授權給我的） |
| GET | `/delegations/candidates` | 可以授權的人：和我同群組的成員 `[{"user_id", "display_name", "avatar_url"}]`（已授權的也列，帶 `delegation_id`） |
| POST | `/delegations` | `{"viewer_user_id", "scope": "all" \| "accounts", "account_ids": [...]}` → `Delegation`。對方不是同群組成員回 404；已授權過回 409 `already_member`（改用 PATCH）；`account_ids` 必須是自己的帳戶（否則 422） |
| PATCH | `/delegations/{id}` | 授權者修改範圍：`{"scope", "account_ids"}` |
| DELETE | `/delegations/{id}` | 授權者撤銷，或被授權者自己移除；立即生效 |

```json
// Delegation
{
  "id": "dlg_01J...",
  "owner": {"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null},
  "viewer": {"user_id": "usr_...", "display_name": "小明", "avatar_url": null},
  "scope": "accounts",                       // "all" 也包含之後新增的帳戶
  "accounts": [{"id": "acc_...", "name": "永豐－一般"}],   // 授權範圍內的帳戶；帳戶刪除後自動移出
  "created_at": "2026-11-12T20:00:00+08:00"
}
```

- 授權者與被授權者之後不再同群組時，授權**不會**自動撤銷（授權是一對一的決定）；授權者可隨時撤銷。

**以唯讀身分查看**：前端在請求加上標頭 `X-Forliosa-View-As: <delegation_id>`（CORS `allow_headers` 包含它）。以路由白名單實作，預設拒絕：

1. **使用者資料端點**只允許這些 `GET`：`/accounts`、`/accounts/{id}/holdings`、`/portfolio/summary`、`/portfolio/holdings`、`/portfolio/performance`、
   `/portfolio/closed`、`/portfolio/upcoming`、`/transactions`、`/transactions/{id}`、`/instruments/{symbol}/position`、
   `/instruments/{symbol}/position/history`、`/instruments/{symbol}/events`。回應以授權者身分計算，**而且授權者只有授權範圍內的帳戶**
   （`allocation.by_account`、`upcoming` 的定期定額、`events` 的 `mine`／`amount_estimate` 都只算範圍內）；`account_id` 參數超出範圍回 404。
2. **不讀使用者資料的端點**忽略這個標頭：商品搜尋、`/instruments/{symbol}`、報價、K 線、估值、月營收、股利、總覽、盤中、籌碼、財務、
   新聞、為什麼漲跌、`/quotes`、`/stream/quotes`、`/derivatives/*`、`/meta/*`、`/auth/providers`、`GET /me`。
3. 其他請求：寫入（非 `GET`）回 403 `read_only`；其他使用者資料端點（AI、自選、群組、授權、設定、匯出）回 403 `view_as_not_allowed`。
4. 授權不存在、已撤銷、或被授權者不是我：一律 403 `delegation_revoked`（不區分），前端退出查看模式。

- 顯示偏好（紅漲綠跌、以張或股、隱私模式）用查看者自己的；成本法、基準用授權者的。
- AI 不讀被查看者的資料：查看模式下前端停用全域 AI 輸入框與 AI 面板，並隱藏「加入自選」「記一筆」「問 AI」這類動作。

### 親友群組

角色：`owner`（擁有者，一位）、`admin`（管理員）、`member`（成員）。

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/groups` | 登入 | `GroupSummary[]`（我加入的群組） |
| POST | `/groups` | 登入 | `{"name"}`（1–40 字）→ `Group`；建立者為 owner，分享設定為預設值 |
| GET | `/groups/{id}` | 成員 | `Group` |
| PATCH | `/groups/{id}` | 管理員；`ranking_enabled` 只限 owner | `{"name"?, "ranking_enabled"?}` |
| DELETE | `/groups/{id}` | owner | 刪除群組（含留言、週報、頻道設定） |
| POST | `/groups/{id}/transfer` | owner | `{"user_id"}` 把 owner 轉給另一位成員（原 owner 變 admin） |
| PATCH | `/groups/{id}/members/{user_id}` | owner | `{"role": "admin" \| "member"}` |
| DELETE | `/groups/{id}/members/{user_id}` | 管理員移除成員；任何人移除自己 | owner 要先轉移才能離開；admin 不能移除 owner 或其他 admin。移除成員時撤回群組所有「可多次使用」的邀請。離開或被移除後分享設定刪除，重新加入時重新選 |
| POST | `/groups/{id}/invites` | 管理員 | `{"expires": "24h" \| "7d", "multi_use": false}`（預設 7 天、單次）→ `{"id", "url", "expires_at", "multi_use", "uses"}`；`url` 只在建立時回傳 |
| GET | `/groups/{id}/invites` | 管理員 | 有效的邀請（不含 `url`） |
| DELETE | `/groups/{id}/invites/{invite_id}` | 管理員 | 撤回 |
| GET | `/invites/{token}` | 不需登入 | 預覽 `{"group_name", "inviter_display_name", "status": "valid" \| "member"}`（`member`：已登入且已是成員）。無效的 token 404；過期、撤回、用完 410 `invite_invalid` |
| POST | `/invites/{token}/accept` | 登入 | `{"share": ShareSettings}`（必填：前端先讓使用者確認開關）→ `Group`；已是成員 409 `already_member`；無效 404／410 |
| GET | `/groups/{id}/share` | 成員 | 我在這個群組的 `ShareSettings` |
| PUT | `/groups/{id}/share` | 成員 | 更新我在這個群組的 `ShareSettings`（立即生效） |
| GET | `/groups/{id}/leaderboard?period=day` | 成員 | `Leaderboard`；`period`：`day`、`month`、`year` |
| GET | `/groups/{id}/holdings` | 成員 | `GroupHoldings` |
| GET | `/groups/{id}/members/{user_id}/shared` | 成員 | `SharedPortfolio` |
| GET | `/groups/{id}/feed?limit=30&cursor=&user_id=` | 成員 | `{"items": FeedItem[], "next_cursor"}`；`user_id` 篩選一位成員 |
| GET | `/groups/{id}/comments?target=&limit=50&cursor=` | 成員 | 一個對象的留言，舊到新，`{"items": Comment[], "next_cursor"}` |
| POST | `/groups/{id}/comments` | 成員 | `{"target", "body"}`（1–500 字）→ `Comment` |
| DELETE | `/groups/{id}/comments/{comment_id}` | 作者或管理員 | 刪除留言 |
| PUT | `/groups/{id}/reactions` | 成員 | `{"target", "emoji"}` 加表情（重複呼叫不重複計） |
| DELETE | `/groups/{id}/reactions?target=&emoji=` | 成員 | 收回自己的表情 |
| GET | `/groups/{id}/digests?limit=8&cursor=` | 成員 | 群組 AI 週報，新到舊，`{"items": Digest[], "next_cursor"}` |
| GET | `/groups/{id}/channels` | 成員 | `Channels`（`webhook_hint` 只有 owner 看得到） |
| PUT | `/groups/{id}/channels/discord` | owner | `{"webhook_url", "notify_trades", "notify_digest"}`；儲存前送一則測試訊息，失敗 422 `webhook_failed` |
| PATCH | `/groups/{id}/channels/discord` | owner | `{"notify_trades"?, "notify_digest"?}` |
| DELETE | `/groups/{id}/channels/discord` | owner | 解除 |
| POST | `/groups/{id}/channels/telegram/link` | owner | → `{"code", "bot_username", "expires_at"}`：把 bot 加進 Telegram 群組，在群組裡傳 `/link <code>`（10 分鐘內、一次性） |
| PATCH | `/groups/{id}/channels/telegram` | owner | `{"notify_trades"?, "notify_digest"?}` |
| DELETE | `/groups/{id}/channels/telegram` | owner | 解除 |

```json
// GroupSummary
{"id": "grp_...", "name": "家族投資", "my_role": "owner", "member_count": 5, "ranking_enabled": true,
 "latest_activity_at": "2026-11-12T13:40:00+08:00", "latest_digest_at": "2026-11-15T20:00:00+08:00"}

// Group
{
  "id": "grp_...", "name": "家族投資", "my_role": "owner", "ranking_enabled": true,
  "created_at": "2026-11-12T20:00:00+08:00",
  "members": [{"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null, "role": "owner",
               "joined_at": "2026-11-12T20:00:00+08:00", "is_me": true}],
  "my_share": ShareSettings,
  "push_targets": [{"kind": "discord", "label": "Discord 頻道"}, {"kind": "telegram", "label": "家族投資群"}]   // 每位成員都看得到
}

// ShareSettings（預設只開 returns；接受邀請時由本人確認）
{
  "returns": true,        // 報酬率（只有 %）：今日、本月、今年、總報酬率
  "holdings": false,      // 持股名稱與權重（不含股數、金額）
  "amounts": false,       // 實際金額與損益：市值、今日損益、總損益
  "trades": false,        // 交易動態：買進／賣出哪一檔（打開時也顯示最近 90 天）
  "trade_prices": false,  // 交易動態附上成交價（trades 關閉時保存但無作用）；沒有理由欄位
  "push": false           // 把我開放的內容送到群組的 Discord／Telegram 頻道（預設關）
}

// Leaderboard
{
  "period": "month",
  "date": "2026-11-12",                   // 最新收盤的交易日
  "start_date": "2026-10-30",             // 期間起點（上月最後收盤）
  "as_of": "2026-11-12T13:30:00+08:00",
  "ranked": true,                         // owner 關掉排行時為 false：沒有 rank，依加入順序
  "entries": [{"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null, "return_pct": 0.0321,
               "total_return_pct": 0.284, "rank": 1, "is_me": false}],
  "benchmarks": [{"symbol": "^TAIEXTR", "name": "發行量加權股價報酬指數", "return_pct": 0.0254},
                 {"symbol": "0050.TW", "name": "元大台灣50", "return_pct": 0.0247}],
  "notes": [], "sources": ["臺灣證券交易所〈…〉（2026），依政府資料開放授權條款第 1 版"],
  "is_demo": false
}
```

- **期間定義**：以收盤價、該成員全部帳戶合併、新台幣計。`day` = 最新收盤相對前一收盤；`month` = 上月最後收盤到最新收盤的 TWR；
  `year` = 去年最後收盤到最新收盤的 TWR。所有成員與基準共用同一個 `start_date`（期間起點與存檔起點較晚者）；期間中才開始持有的成員從第一天
  有持股起算。只記持股的帳戶以快照為期初。有任何持股沒有收盤價（例如 commercial 下的美股）時該成員所有期間為 `null`，排在最後、沒有 rank，
  不說明原因。報酬率四捨五入到 4 位後相同就並列名次（1、1、3）。
- **總報酬率** `total_return_pct` 每筆都附上、不排名、沒有基準（各人起點不同）；同 `PortfolioSummary.total_return_pct`（含股利）。
- `/portfolio/performance` 的 `range` 新增 `MTD`（上月最後收盤起）；分享卡的「本月」用它。

```json
// GroupHoldings（只有開了 holdings 的成員）
{
  "members": [{"user_id": "usr_...", "display_name": "爸爸",
               "holdings": [{"symbol": "2330.TW", "name": "台積電", "weight": 0.42}]}],
  "common": [{"symbol": "2330.TW", "name": "台積電", "holder_count": 3}],     // 兩人以上持有，依人數排序
  "industries": [{"industry": "半導體業", "holder_count": 4}],
  "is_demo": false
}

// SharedPortfolio（只出現對方開放的區塊；沒開放的鍵不存在）
{
  "user_id": "usr_...", "display_name": "爸爸", "avatar_url": null,
  "returns": {"day": 0.0124, "month": 0.0321, "year": 0.152, "total": 0.284},
  "holdings": [{"symbol": "2330.TW", "name": "台積電", "weight": 0.42}],
  "amounts": {"market_value": 3284500, "day_change": 40320, "total_pnl": 242000},
  "is_demo": false
}

// FeedItem
{
  "id": "gfi_...", "type": "trade",              // "trade" | "member_joined"
  "user_id": "usr_...", "display_name": "爸爸", "avatar_url": null,
  "side": "buy", "symbol": "2330.TW", "name": "台積電", "trade_date": "2026-11-12",
  "count": 1,                                    // 同一人同一天同一檔同方向的交易合併成一則（定期定額不會洗版）
  "price": 1085.0, "currency": "TWD",            // 只有開了 trade_prices 才有這兩個鍵：交易幣別的成交價（多筆合併時為加權平均），不含費用
  "created_at": "2026-11-12T13:40:00+08:00",
  "comment_count": 2,
  "reactions": [{"emoji": "👍", "count": 3, "mine": true}]
}

// Comment
{"id": "gcm_...", "target": "trade:gfi_...", "user_id": "usr_...", "display_name": "小明", "body": "跟上",
 "created_at": "2026-11-12T20:05:00+08:00", "can_delete": true}
// 已離開群組的成員的留言：display_name 為「已離開的成員」、user_id 為 null

// Digest（群組 AI 週報）
{
  "id": "gdg_...", "status": "ready",          // "pending" | "ready" | "failed"
  "week_start": "2026-11-09", "week_end": "2026-11-13",
  "created_at": "2026-11-15T20:00:00+08:00",
  "summary": "本週群組整體……",                 // AI 只寫群組整體，不點名個人，不給買賣建議或目標價
  "facts": {                                   // 讀取時依「目前」的分享設定過濾
    "returns": [{"user_id": "usr_...", "display_name": "爸爸", "week_return_pct": 0.012}],
    "benchmarks": [{"symbol": "^TAIEXTR", "name": "發行量加權股價報酬指數", "week_return_pct": 0.008}],
    "common_holdings": [{"symbol": "2330.TW", "name": "台積電", "holder_count": 3}],
    "industries": [{"industry": "半導體業", "holder_count": 4}],
    "trades_count": 7                          // 只算開了 trades 的成員
  },
  "disclaimer": "AI 分析僅供參考，不構成投資建議。",
  "sources": ["…"], "comment_count": 0, "reactions": []
}

// Channels
{
  "discord": {"configured": true, "status": "active", "disabled_reason": null, "webhook_hint": "…/a1b2",
              "notify_trades": true, "notify_digest": true},
  "telegram": {"configured": false, "status": null, "disabled_reason": null, "chat_title": null,
               "notify_trades": true, "notify_digest": true},
  "telegram_available": true            // 伺服器有設定 bot 時才為 true
}
```

**交易動態**

- 來源：開了 `trades` 的成員，`source` 為 `manual`、`import`、`ai_draft` 的 `buy`／`sell`（股利、自動入帳、只記持股的快照都不列），
  `trade_date`（台北）在最近 90 天內。打開 `trades` 時最近 90 天的也會出現（開關旁明講）。排序：`trade_date`、`created_at`、`id` 由新到舊。
- 成員關掉 `trades` 或離開群組，他的動態立刻消失（留言保留但看不到；重新打開時恢復）；交易被刪除時，那則動態和底下的留言一起刪除。
- 新成員加入時產生一則 `member_joined`（每個人都看得到加入的事實，不含任何分享內容）。

**留言與表情**

- 對象 `target`：`trade:<feed_item_id>`、`digest:<digest_id>`、`leaderboard:<YYYY-MM-DD>`（當天排行的討論串）。對象必須屬於這個群組、而且在目前的
  分享投影裡看得到；看不到、不存在、屬於別的群組的，一律 404 `not_found`（同一個訊息）。`comment_count`／`reactions` 只算看得到的對象。
- 表情固定六個：`👍`、`🎉`、`🔥`、`😮`、`😢`、`👀`；其他值 422 `validation_error`。

**群組 AI 週報**

- 一週 = 台北的週一到週五；`week_return_pct` = 週一前最後收盤到週五（或之前最後一個交易日）收盤。沒有交易日的週、開了 `returns` 的成員少於 2 位
  的群組不產生。worker 每週六 20:00（台北）以 Message Batches API 送出，結果回來（`ready`）後才推播。
- `facts` 由伺服器從分享投影計算，以 `user_id` 儲存，讀取時依目前的成員身分與開關過濾（關掉或離開的人從過去的週報消失）。
  AI 只拿到匿名代號（成員 A、B…）與數字，`summary` 只描述群組整體；顯示名稱不進 prompt。週報不計入成員的 AI 額度。

**推播**

- 只推播 `push` 為 true 的成員所開放的內容：交易動態（`notify_trades`；`trades` 開啟、交易日在 3 個日曆日內、建立時間晚於頻道設定與他打開
  `push`／`trades` 的時間；建立 15 分鐘後才送，期間刪除或關閉就不送；送出後的修改不重送；有開 `trade_prices` 才附價格）與週報
  （`notify_digest`；只含 `push` 為 true 的成員的數字）。
- Discord：webhook 網址解析後主機必須是 `discord.com` 或 `discordapp.com`、沒有帳密與連接埠、路徑為 `/api/webhooks/{id}/{token}`；不跟隨轉址；
  加密儲存、不寫進 log、回應只給最後 4 碼。訊息帶 `allowed_mentions: {"parse": []}`（名稱與內容不能 @everyone）。404／401 → 頻道 `disabled`。
- Telegram：worker 以 `getUpdates` 輪詢（不開公開的 webhook 端點），處理 `/link <code>` 與 `/link@<bot> <code>`；連結成功時 bot 回覆群組名稱，
  owner 在 app 裡看到 `chat_title` 確認。訊息不用 `parse_mode`。403（bot 被移出）→ `disabled`；`migrate_to_chat_id` 時更新 chat id。
- 送出失敗會重試（最多 5 次、指數退避）。環境變數：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_BOT_USERNAME`（沒設定時 `telegram_available: false`）。
- 個人通知管道（§4.9 的個人 Telegram／Discord）不在這一批。

**帳號刪除**（之後提供刪除帳號時）：擁有的群組轉給最早的 admin，沒有就最早加入的成員，沒有成員就刪除群組；授權全部刪除；留言顯示「已刪除的帳號」。
