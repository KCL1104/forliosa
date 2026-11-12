## 分享（M5）：登入、授權唯讀查看、親友群組（2026-11-12）

產品負責人決定（`PRODUCT.md`）：照 `docs/product-spec.md` §4.8 一次做完；正式登入用 **Discord OAuth**；排行期間今日／本月／今年＋總報酬率（含股利），可對照大盤與 0050；交易動態只顯示買賣哪一檔，可選擇附上價格，**不提供理由欄位**；授權唯讀查看和群組一起做。

**分享投影（後端實作要求）**：群組與授權查看的每個端點、推播與 AI 週報，都只能經過 `services/sharing.py` 的分享投影讀取別人的資料。投影依「這位成員在這個群組的分享設定」或「這份授權的範圍」過濾；沒開放的欄位**不出現在回應裡**（不是 `null`，也不是 0），也不回傳「某某沒分享」這類資訊。測試必須逐項證明關掉的開關不會洩漏（含金額、股數、交易價格、帳戶名稱）。

### 登入（Discord OAuth）

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/auth/providers` | 不需登入。`{"providers": [{"id": "discord", "name": "Discord", "enabled": true}], "dev_login": false}`；`enabled` 依環境變數是否齊全 |
| GET | `/auth/discord/start?next=/invite/abc` | 302 到 Discord 授權頁（scope `identify email`）。`state` 存在 10 分鐘的 httpOnly cookie（`forliosa_oauth`，含 `next`）。`next` 只接受站內相對路徑，否則改成 `/` |
| GET | `/auth/discord/callback?code=&state=` | 驗證 `state`、換 token、讀 `/users/@me`；**Email 必須已驗證**。以 Discord 使用者 id 找帳號，找不到再以 email 連結既有帳號，都沒有就建立新帳號（`display_name` 取 Discord 的 global name，否則 username）。成功：建立 session，302 到 `{FRONTEND_URL}{next}`；失敗：302 到 `{FRONTEND_URL}/login?error=<code>` |

失敗代碼：`oauth_disabled`、`oauth_denied`（使用者按取消）、`oauth_state`（state 不符或過期）、`oauth_email_unverified`、`oauth_failed`（Discord 回錯誤或連不上）。

環境變數：`DISCORD_CLIENT_ID`、`DISCORD_CLIENT_SECRET`、`DISCORD_REDIRECT_URI`（例如 `https://api.example.com/api/v1/auth/discord/callback`，要和 Discord Developer Portal 設定的一致）、`FRONTEND_URL`。`POST /auth/dev-login` 照舊只在開發環境啟用。

`User` 新增 `avatar_url`（Discord 頭像，可為 null）與 `login_providers`（例如 `["discord"]`）。

### 授權唯讀查看（一對一）

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/delegations` | `{"granted": Delegation[], "received": Delegation[]}`（我授權給別人的／別人授權給我的） |
| POST | `/delegations/invites` | body `{"scope": "all" \| "accounts", "account_ids": [...], "expires_in_days": 7}`（1–30，預設 7）→ `{"id", "url", "expires_at"}`。邀請連結只能用一次 |
| GET | `/delegations/invites/{token}` | 預覽：`{"owner_display_name", "scope", "account_count", "expires_at", "status": "valid" \| "expired" \| "used" \| "revoked" \| "own"}` |
| POST | `/delegations/invites/{token}/accept` | 建立授權，回傳 `Delegation`；自己的邀請回 409 `own_invite` |
| DELETE | `/delegations/invites/{id}` | 授權者撤回尚未使用的邀請 |
| PATCH | `/delegations/{id}` | 授權者修改範圍：`{"scope", "account_ids"}` |
| DELETE | `/delegations/{id}` | 授權者撤銷，或被授權者自己移除；立即生效 |

```json
// Delegation
{
  "id": "dlg_01J...",
  "owner": {"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null},
  "viewer": {"user_id": "usr_...", "display_name": "小明", "avatar_url": null},
  "scope": "accounts",
  "accounts": [{"id": "acc_...", "name": "永豐－一般"}],   // 只有授權者看得到帳戶名稱；被授權者看到的是可查看的帳戶
  "created_at": "2026-11-12T20:00:00+08:00"
}
```

**以唯讀身分查看**：前端在請求加上標頭 `X-Forliosa-View-As: <delegation_id>`。

- 只允許這些 `GET`：`/accounts`、`/portfolio/summary`、`/portfolio/holdings`、`/portfolio/performance`、`/portfolio/closed`、`/portfolio/upcoming`、`/transactions`、`/transactions/{id}`、`/instruments/{symbol}/position`，以及不含使用者資料的行情端點（`/instruments/*` 的報價、K 線、估值等）。回應是授權者在授權範圍內的資料，`account_id` 參數超出範圍回 404。
- 帶這個標頭的其他請求：寫入（非 `GET`）回 403 `read_only`；其他含使用者資料的端點（AI、自選、群組、設定、匯出）回 403 `view_as_not_allowed`。
- 授權撤銷或不存在：403 `delegation_revoked`，前端退出查看模式。
- 顯示偏好（紅漲綠跌、以張或股）用查看者自己的；成本法、基準用授權者的。
- AI 不讀被查看者的資料（AI 只讀登入者本人的資料）。

### 親友群組

角色：`owner`（擁有者，一位）、`admin`（管理員）、`member`（成員）。非成員對群組端點一律 404（不透露群組是否存在）；成員權限不足回 403 `forbidden`。

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/groups` | 登入 | `GroupSummary[]`（我加入的群組） |
| POST | `/groups` | 登入 | `{"name"}`（1–40 字）→ `Group`；建立者為 owner，分享設定為預設值 |
| GET | `/groups/{id}` | 成員 | `Group` |
| PATCH | `/groups/{id}` | 管理員；`leaderboard_enabled` 只限 owner | `{"name"?, "leaderboard_enabled"?}` |
| DELETE | `/groups/{id}` | owner | 刪除群組（含留言、週報、頻道設定） |
| POST | `/groups/{id}/transfer` | owner | `{"user_id"}` 把 owner 轉給另一位成員（原 owner 變 admin） |
| PATCH | `/groups/{id}/members/{user_id}` | owner | `{"role": "admin" \| "member"}` |
| DELETE | `/groups/{id}/members/{user_id}` | 管理員可移除成員；任何人可移除自己 | owner 要先轉移才能離開；admin 不能移除 owner 或其他 admin |
| POST | `/groups/{id}/invites` | 管理員 | `{"expires_in_hours": 72, "max_uses": null}`（1–720 小時；`max_uses` 1–50 或 null）→ `{"id", "url", "expires_at", "max_uses", "uses"}` |
| GET | `/groups/{id}/invites` | 管理員 | 有效的邀請 |
| DELETE | `/groups/{id}/invites/{invite_id}` | 管理員 | 撤回 |
| GET | `/invites/{token}` | 登入 | 預覽 `{"group_name", "inviter_display_name", "member_count", "expires_at", "status": "valid" \| "expired" \| "revoked" \| "used_up" \| "member"}` |
| POST | `/invites/{token}/accept` | 登入 | 加入 → `Group`；已是成員回 409 `already_member`；過期或撤回回 410 `invite_invalid` |
| GET | `/groups/{id}/share` | 成員 | 我在這個群組的 `ShareSettings` |
| PUT | `/groups/{id}/share` | 成員 | 更新我在這個群組的 `ShareSettings`（立即生效） |
| GET | `/groups/{id}/leaderboard?period=day` | 成員 | `Leaderboard`；`period`：`day`、`month`、`year`、`total` |
| GET | `/groups/{id}/holdings` | 成員 | `GroupHoldings`：有開「持股與權重」的成員 |
| GET | `/groups/{id}/members/{user_id}/shared` | 成員 | `SharedPortfolio`：這位成員對這個群組開放的部分 |
| GET | `/groups/{id}/feed?limit=30&cursor=` | 成員 | 交易動態（分頁） |
| GET | `/groups/{id}/comments?target=` | 成員 | 一個對象的留言，舊到新 |
| POST | `/groups/{id}/comments` | 成員 | `{"target", "body"}`（1–500 字）→ `Comment` |
| DELETE | `/groups/{id}/comments/{comment_id}` | 作者或管理員 | 刪除留言 |
| PUT | `/groups/{id}/reactions` | 成員 | `{"target", "emoji"}` 加表情（重複呼叫不重複計） |
| DELETE | `/groups/{id}/reactions?target=&emoji=` | 成員 | 收回自己的表情 |
| GET | `/groups/{id}/digests?limit=8` | 成員 | 群組 AI 週報，新到舊 |
| POST | `/groups/{id}/digests` | 管理員 | 立即產生本週週報（每群組每週最多一次手動；計入觸發者的 AI 額度）→ `Digest`（`status: "pending"`） |
| GET | `/groups/{id}/channels` | 管理員 | `Channels` |
| PUT | `/groups/{id}/channels/discord` | 管理員 | `{"webhook_url", "notify_trades", "notify_digest"}`；網址必須是 `https://discord.com/api/webhooks/…`（或 `discordapp.com`）；儲存前送一則測試訊息，失敗回 422 `webhook_failed` |
| DELETE | `/groups/{id}/channels/discord` | 管理員 | 解除 |
| POST | `/groups/{id}/channels/telegram/link` | 管理員 | → `{"code", "bot_username", "expires_at"}`；把 bot 加進 Telegram 群組後在群組裡傳 `/link <code>`（10 分鐘內有效） |
| PATCH | `/groups/{id}/channels/telegram` | 管理員 | `{"notify_trades", "notify_digest"}` |
| DELETE | `/groups/{id}/channels/telegram` | 管理員 | 解除 |
| POST | `/integrations/telegram/webhook` | Telegram | bot webhook；以 `X-Telegram-Bot-Api-Secret-Token` 驗證；處理 `/link <code>` |

```json
// GroupSummary
{"id": "grp_...", "name": "家族投資", "role": "owner", "member_count": 5, "leaderboard_enabled": true}

// Group
{
  "id": "grp_...", "name": "家族投資", "my_role": "owner", "leaderboard_enabled": true,
  "created_at": "2026-11-12T20:00:00+08:00",
  "members": [{"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null, "role": "owner",
               "joined_at": "2026-11-12T20:00:00+08:00", "is_me": true}],
  "my_share": ShareSettings
}

// ShareSettings（預設只開 returns）
{
  "returns": true,        // 報酬率（只有 %）：今日、本月、今年、總報酬
  "holdings": false,      // 持股名稱與權重（不含股數、金額）
  "amounts": false,       // 實際金額與損益：市值、今日損益、總損益
  "trades": false,        // 交易動態：買進／賣出哪一檔
  "trade_prices": false   // 交易動態附上成交價（trades 開啟時才有作用）；沒有理由欄位
}

// Leaderboard
{
  "period": "month",
  "as_of": "2026-11-12T13:30:00+08:00",
  "ranked": true,                         // owner 關掉排行時為 false：不排名、依加入順序列出、沒有 rank
  "entries": [{"user_id": "usr_...", "display_name": "爸爸", "avatar_url": null, "return_pct": 0.0321,
               "rank": 1, "is_me": false}],
  "benchmarks": [{"symbol": "^TAIEXTR", "name": "發行量加權股價報酬指數", "return_pct": 0.0254},
                 {"symbol": "0050.TW", "name": "元大台灣50", "return_pct": 0.0247}],
  "is_demo": false
}
```

- `entries` 只有開了 `returns` 的成員，沒開的不出現（也沒有「未分享」標記）。`return_pct`：`day` 為今日報酬（同 `day_change_pct`），`month`／`year` 為月初／年初至今的時間加權報酬（TWR），`total` 為總報酬率（含股利，同 `total_return_pct`）。沒有足夠資料的成員該期間為 `null`，排在最後、沒有 rank。
- 留言對象 `target`：`leaderboard:<period>:<YYYY-MM-DD>`（當天的排行）、`trade:<feed_item_id>`、`digest:<digest_id>`。

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
  "user_id": "usr_...", "display_name": "爸爸",
  "returns": {"day": 0.0124, "month": 0.0321, "year": 0.152, "total": 0.284},
  "holdings": [{"symbol": "2330.TW", "name": "台積電", "weight": 0.42}],
  "amounts": {"market_value": 3284500, "day_change": 40320, "total_pnl": 242000},
  "is_demo": false
}

// FeedItem（只有開了 trades 的成員；最近 90 天的買進、賣出；不含股數、金額、理由、帳戶）
{
  "id": "gfi_...", "type": "trade", "user_id": "usr_...", "display_name": "爸爸",
  "side": "buy", "symbol": "2330.TW", "name": "台積電", "trade_date": "2026-11-12",
  "price": 1085.0,                      // 只有開了 trade_prices 才有這個鍵
  "currency": "TWD",
  "comment_count": 2,
  "reactions": [{"emoji": "👍", "count": 3, "mine": true}]
}

// Comment
{"id": "gcm_...", "target": "trade:gfi_...", "user_id": "usr_...", "display_name": "小明", "body": "跟上",
 "created_at": "2026-11-12T20:05:00+08:00", "can_delete": true}

// Digest（群組 AI 週報）
{
  "id": "gdg_...", "status": "ready",          // "pending" | "ready" | "failed"
  "week_start": "2026-11-09", "week_end": "2026-11-13",
  "created_at": "2026-11-15T20:00:00+08:00",
  "summary": "本週群組平均……",               // AI 依下面的數字寫的短評，不給買賣建議
  "facts": {
    "returns": [{"display_name": "爸爸", "week_return_pct": 0.012}],
    "common_holdings": [{"symbol": "2330.TW", "name": "台積電", "holder_count": 3}],
    "industries": [{"industry": "半導體業", "holder_count": 4}],
    "trades_count": 7
  },
  "disclaimer": "AI 分析僅供參考，不構成投資建議。",
  "comment_count": 0, "reactions": []
}

// Channels
{
  "discord": {"configured": true, "webhook_hint": "…/a1b2", "notify_trades": true, "notify_digest": true},
  "telegram": {"configured": false, "chat_title": null, "notify_trades": true, "notify_digest": true},
  "telegram_available": true            // 伺服器有設定 bot 時才為 true
}
```

- **表情**：固定六個 `👍`、`🎉`、`🔥`、`😮`、`😢`、`👀`，其他值回 422。
- **交易動態的來源**：開了 `trades` 的成員，`source` 為 `manual`、`import`、`ai_draft` 的 `buy`／`sell`（股利、自動入帳、只記持股的快照都不列）。成員關掉 `trades` 後，他的動態與底下的留言立刻從群組消失（資料保留，重新打開時恢復）。交易被刪除時，那則動態一起消失。
- **群組 AI 週報**：worker 每週日 20:00（台北）為每個群組產生（Message Batches API）；`facts` 由伺服器從分享投影計算，AI 只拿到 `facts` 寫 `summary`，不讀原始帳本，也不給買賣建議或目標價。週報費用不計入成員的每日對話額度（手動產生計入觸發者）。
- **推播**：群組有頻道時，worker 把新的交易動態（交易日在 3 天內、成員有開 `trades`；有開 `trade_prices` 才附價格）與週報送到 Discord webhook／Telegram 群組。訊息只用分享投影的內容。送出失敗會重試；Discord 回 404／401（webhook 被刪）時自動停用該頻道。
- 環境變數：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_WEBHOOK_SECRET`、`TELEGRAM_BOT_USERNAME`（沒設定時 `telegram_available: false`）。Discord webhook 網址視同密碼：只存在後端，回應只給最後 4 碼。

錯誤代碼：`forbidden`、`read_only`、`view_as_not_allowed`、`delegation_revoked`、`already_member`、`invite_invalid`、`own_invite`、`webhook_failed`、`digest_limit`（本週已手動產生過）。
