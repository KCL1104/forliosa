// 即時更新的前後端實測（真實後端，不是 mock；docs/api-contract.md「即時更新（2026-11-17）」）：
// 兩個瀏覽器、不重新整理，別人或自己另一台裝置改的東西 2 秒內出現在開著的頁面上。
//   1. 群組：B 用邀請連結加入 → A 開著的「成員」與「動態」分頁 2 秒內出現 B（不重新載入頁面）
//   2. 帳本：同一個人兩台裝置，裝置 1 用「記一筆」買進 2330 → 裝置 2 的持股 2 秒內出現；裝置 1 自己的事件略過（每個查詢只重抓一次）
//   3. B 分享的交易進到 A 開著的動態（group.ledger）；B 留言 → A 的留言數；B 在 A 開著的群組討論串回覆 → A 看到回覆
//   4. A 的分頁在背景時不重新讀，回到前景時才讀；A 的串流被擋（/events 連不上）→ 30 秒一次的備援仍然把變更帶進來
//   5. 批次 4 的寫入（2026-11-17 合併）：裝置 1 匯入庫存（「以券商為準」換掉 2330、加一檔 2317）→ 裝置 2 的持股 2 秒內變；
//      裝置 1 刪除這檔 2317 → 裝置 2 2 秒內不見；裝置 1 清除所有持倉 → 裝置 2 2 秒內變成空的（都是整批刪除，伺服器自己送事件）
//
// 1. 後端（全新的資料庫；dev 模式才有開發登入；示範資料讓 2330 查得到）：
//      cd apps/api && export DATABASE_URL=sqlite:////tmp/forliosa-rt.db FORLIOSA_ENV=dev ADMIN_EMAILS=demo@forliosa.local \
//        CORS_ORIGINS=http://localhost:5231 DATA_POLICY=personal MARKET_DATA_PROVIDERS=demo \
//        && uv run alembic upgrade head && uv run uvicorn forliosa.main:app --port 8010
// 2. 前端（連真實後端）：cd apps/web && FORLIOSA_API_ORIGIN=http://localhost:8010 pnpm exec vite --mode api --port 5231 --strictPort
// 3. node scripts/e2e-realtime.mjs [截圖輸出資料夾] [--base=http://localhost:5231] [--skip-fallback]
// 不用 `waitUntil: "networkidle"`：即時更新的串流一直開著，網路永遠不會「閒下來」（等的是畫面上的字）。
import { mkdirSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
const require = createRequire(import.meta.url)
let pw
try {
  pw = require("playwright")
} catch {
  pw = require("/opt/node-tools/node_modules/playwright")
}
const args = process.argv.slice(2)
const BASE = (args.find((a) => a.startsWith("--base="))?.slice(7) ?? "http://localhost:5231").replace(/\/$/, "")
const out = args.find((a) => !a.startsWith("--")) ?? "/tmp/forliosa-e2e-realtime"
const SKIP_FALLBACK = args.includes("--skip-fallback")
mkdirSync(out, { recursive: true })
const API = `${BASE}/api/v1`
const LIMIT_MS = 2000
// 每次跑用新的帳號（同一個資料庫可以重跑）；A 是開發登入的示範使用者，每次開一個新群組
const RUN = Date.now().toString(36)
const results = []
const errors = []

const step = async (name, fn) => {
  const t = Date.now()
  try {
    const r = await fn()
    console.log("✓", name, r ?? "", `(${Date.now() - t} ms)`)
    return r
  } catch (e) {
    console.log("✗", name, "—", String(e.message).split("\n")[0])
    throw e
  }
}
const record = (name, ms, limit = LIMIT_MS) => {
  results.push({ name, ms, limit, ok: ms <= limit })
  if (ms > limit) throw new Error(`${name}: ${ms} ms > ${limit} ms`)
  return `${ms} ms`
}

// 兩個瀏覽器（照字面：兩個 chromium 行程）
const browserA = await pw.chromium.launch()
const browserB = await pw.chromium.launch()

async function context(browser, { email, name, video } = {}) {
  const c = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "zh-TW", ...(video ? { recordVideo: { dir: `${out}/video`, size: { width: 1280, height: 900 } } } : {}) })
  if (email) {
    const r = await c.request.post(`${API}/auth/dev-login`, { data: { email, display_name: name }, headers: { Origin: BASE } })
    if (!r.ok()) throw new Error(`dev-login ${r.status()} ${await r.text()}`)
  }
  return c
}

/** 開一個頁面：記下錯誤、/events 的回應、各端點的 GET（數重新讀了幾次）、即時更新的除錯訊息 */
async function page(ctx, label) {
  const p = await ctx.newPage()
  p.streams = []
  p.gets = []
  p.rt = []
  p.on("pageerror", (e) => errors.push(`${label}: ${e}`))
  p.on("response", (r) => {
    if (r.status() >= 500) errors.push(`${label}: ${r.status()} ${r.url()}`)
    if (r.url().includes("/api/v1/events")) p.streams.push(r.status())
  })
  p.on("request", (r) => {
    if (r.method() === "GET" && r.url().includes("/api/v1/") && !r.url().includes("/events")) p.gets.push({ at: Date.now(), path: r.url().slice(API.length) })
  })
  p.on("console", (m) => {
    if (m.text().startsWith("realtime:")) p.rt.push({ at: Date.now(), text: m.text() })
  })
  return p
}

/** 串流連上了（/events 回 200，再等 hello 進來） */
async function streamOpen(p, timeout = 10_000) {
  const until = Date.now() + timeout
  while (!p.streams.includes(200)) {
    if (Date.now() > until) throw new Error(`no open stream (statuses: ${p.streams.join(",") || "none"})`)
    await p.waitForTimeout(50)
  }
  await p.waitForTimeout(300)
}

/** 在頁面裡等一段文字出現，記下出現的那一刻（頁面自己的時鐘，和這支程式同一台機器） */
async function arm(p, key, pattern, root = "main") {
  await p.evaluate(
    ([key, src, root]) => {
      const re = new RegExp(src)
      window.__seen ??= {}
      const check = () => {
        if (!window.__seen[key] && re.test(document.querySelector(root)?.innerText ?? "")) window.__seen[key] = Date.now()
      }
      new MutationObserver(check).observe(document.body, { subtree: true, childList: true, characterData: true })
      check()
    },
    [key, pattern.source, root],
  )
}
/** 等一段文字從頁面上消失，記下消失的那一刻 */
async function armGone(p, key, pattern, root = "main") {
  await p.evaluate(
    ([key, src, root]) => {
      const re = new RegExp(src)
      window.__seen ??= {}
      const check = () => {
        if (!window.__seen[key] && !re.test(document.querySelector(root)?.innerText ?? "")) window.__seen[key] = Date.now()
      }
      new MutationObserver(check).observe(document.body, { subtree: true, childList: true, characterData: true })
      check()
    },
    [key, pattern.source, root],
  )
}
async function seenAt(p, key, timeout = 10_000) {
  await p.waitForFunction((k) => window.__seen?.[k], key, { timeout })
  return p.evaluate((k) => window.__seen[k], key)
}
async function notYet(p, key) {
  if (await p.evaluate((k) => window.__seen?.[k], key)) throw new Error(`"${key}" was already on the page before the change`)
}
const mark = (p, v) => p.evaluate((v) => (window.__mark = v), v)
const stillMarked = async (p, v) => {
  if ((await p.evaluate(() => window.__mark)) !== v) throw new Error("the page reloaded")
}
const post = async (ctx, path, data, method = "post") => {
  const r = await ctx.request[method](`${API}${path}`, { data, headers: { Origin: BASE } })
  if (!r.ok()) throw new Error(`${method.toUpperCase()} ${path} → ${r.status()} ${await r.text()}`)
  return r.status() === 204 ? null : r.json()
}

try {
  // ── 1. 群組：B 加入，A 開著的成員與動態 ─────────────────────────
  const ca = await context(browserA, { email: "demo@forliosa.local", name: "示範使用者", video: true })
  const group = await step("A creates a group and an invite link (API)", async () => {
    const g = await post(ca, "/groups", { name: "即時測試社" })
    const inv = await post(ca, `/groups/${g.id}/invites`, { expires: "7d", multi_use: true })
    return { id: g.id, token: inv.url.split("/invite/")[1] }
  })
  const aMembers = await page(ca, "A/members")
  const aFeed = await page(ca, "A/feed")
  await step("A opens the members tab and the feed tab (two tabs), both streams open", async () => {
    await aMembers.goto(`${BASE}/groups/${group.id}?tab=members`, { waitUntil: "load" })
    await aMembers.getByText("示範使用者").first().waitFor({ timeout: 15_000 })
    await aFeed.goto(`${BASE}/groups/${group.id}?tab=feed`, { waitUntil: "load" })
    await streamOpen(aMembers)
    await streamOpen(aFeed)
    await mark(aMembers, "A1")
    await mark(aFeed, "A2")
    await arm(aMembers, "member", /路人乙/)
    await arm(aFeed, "joined", /路人乙\s*加入了群組/)
    await notYet(aMembers, "member")
    await notYet(aFeed, "joined")
    await aMembers.screenshot({ path: `${out}/1-a-members-before.png` })
  })
  const cb = await context(browserB, { email: `friend-${RUN}@forliosa.local`, name: "路人乙" })
  const pb = await page(cb, "B")
  const acceptedAt = await step("B opens the invite, turns on trade sharing and joins", async () => {
    await pb.goto(`${BASE}/invite/${group.token}`, { waitUntil: "load" })
    await pb.getByRole("button", { name: "加入群組" }).waitFor({ timeout: 15_000 })
    const trades = pb.getByRole("switch", { name: "交易動態" })
    if ((await trades.getAttribute("aria-checked")) !== "true") await trades.click()
    const accepted = pb.waitForResponse((r) => r.url().includes(`/invites/${group.token}/accept`) && r.request().method() === "POST")
    await pb.getByRole("button", { name: "加入群組" }).click()
    const res = await accepted
    const at = Date.now()
    if (!res.ok()) throw new Error(`accept ${res.status()}`)
    return at
  })
  await step("A's members tab shows B within 2 s, without a reload", async () => {
    const ms = (await seenAt(aMembers, "member")) - acceptedAt
    await stillMarked(aMembers, "A1")
    await aMembers.screenshot({ path: `${out}/1-a-members-after.png` })
    return record("group join → A's members tab", ms)
  })
  await step("A's feed tab shows 「路人乙 加入了群組」 within 2 s, without a reload", async () => {
    const ms = (await seenAt(aFeed, "joined")) - acceptedAt
    await stillMarked(aFeed, "A2")
    await aFeed.screenshot({ path: `${out}/1-a-feed-joined.png` })
    return record("group join → A's feed tab", ms)
  })

  // ── 3. B 的交易（group.ledger）、留言、討論串回覆 ─────────────────
  const bAccount = await step("B creates a broker account (API)", async () => (await post(cb, "/accounts", { name: "永豐", broker: "永豐金", currency: "TWD" })).id)
  await arm(aFeed, "trade", /路人乙\s*買進/)
  await notYet(aFeed, "trade")
  const tradeAt = await step("B records a buy (shared trades) → POST /transactions", async () => {
    await post(cb, "/transactions", { account_id: bAccount, symbol: "2330.TW", type: "buy", trade_date: "2026-11-10", quantity: 1000, price: 1000 })
    return Date.now()
  })
  await step("A's open feed shows B's buy within 2 s (group.ledger)", async () => {
    const ms = (await seenAt(aFeed, "trade")) - tradeAt
    return record("member's trade → A's feed (group.ledger)", ms)
  })
  const target = await step("find the trade's comment thread", async () => {
    const feed = await (await ca.request.get(`${API}/groups/${group.id}/feed`)).json()
    const item = feed.items.find((i) => i.type === "trade")
    if (!item) throw new Error("no trade item in the feed")
    return `trade:${item.id}`
  })
  await arm(aFeed, "comment", /留言\s*1/)
  await notYet(aFeed, "comment")
  const commentAt = await step("B comments on the trade", async () => {
    await post(cb, `/groups/${group.id}/comments`, { target, body: "這筆買得漂亮" })
    return Date.now()
  })
  await step("A's feed comment count changes within 2 s", async () => {
    const ms = (await seenAt(aFeed, "comment")) - commentAt
    await aFeed.screenshot({ path: `${out}/3-a-feed-trade-comment.png` })
    return record("comment → A's comment count", ms)
  })
  const topic = await step("A starts a group discussion topic (API) and opens it", async () => {
    const t = await post(ca, "/discussions/topics", { scope: "group", group_id: group.id, title: "即時更新測試：回覆會自己出現嗎？", body: "開著這一頁等回覆" })
    return t.id
  })
  const aTopic = await page(ca, "A/topic")
  await aTopic.goto(`${BASE}/discussions/${topic}?from=group`, { waitUntil: "load" })
  await aTopic.getByRole("heading", { name: "即時更新測試：回覆會自己出現嗎？" }).waitFor({ timeout: 15_000 })
  await streamOpen(aTopic)
  await arm(aTopic, "reply", /會，不用重新整理/)
  const replyAt = await step("B replies in that thread", async () => {
    await post(cb, `/discussions/topics/${topic}/replies`, { body: "會，不用重新整理" })
    return Date.now()
  })
  await step("A's open topic shows the reply within 2 s", async () => {
    const ms = (await seenAt(aTopic, "reply")) - replyAt
    await aTopic.screenshot({ path: `${out}/3-a-topic-reply.png` })
    return record("reply → A's open topic", ms)
  })
  await aTopic.close()
  await aFeed.close()

  // ── 4a. 背景分頁：不重新讀，回到前景才讀 ──────────────────────
  await step("A's tab goes to the background; B renames themself; A does not refetch while hidden", async () => {
    await aMembers.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" })
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true })
      document.dispatchEvent(new Event("visibilitychange"))
    })
    await arm(aMembers, "renamed", /路人丙/)
    const before = aMembers.gets.length
    await post(cb, "/me", { display_name: "路人丙" }, "patch")
    await aMembers.waitForTimeout(2500)
    const during = aMembers.gets.slice(before).filter((g) => g.path.startsWith(`/groups/${group.id}`))
    if (during.length) throw new Error(`refetched while hidden: ${during.map((g) => g.path).join(", ")}`)
    await notYet(aMembers, "renamed")
    return "0 group requests while hidden"
  })
  await step("A comes back: the new name shows right away", async () => {
    const at = Date.now()
    await aMembers.evaluate(() => {
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" })
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false })
      document.dispatchEvent(new Event("visibilitychange"))
    })
    const ms = (await seenAt(aMembers, "renamed")) - at
    await stillMarked(aMembers, "A1")
    await aMembers.screenshot({ path: `${out}/4-a-members-back-visible.png` })
    return record("hidden tab → visible → refetched", ms)
  })

  // ── 4b. 串流被擋：30 秒一次的備援 ─────────────────────────────
  if (!SKIP_FALLBACK) {
    const aBlocked = await page(ca, "A/blocked")
    await aBlocked.route("**/api/v1/events**", (r) => r.abort())
    await step("A opens another tab whose /events is blocked", async () => {
      await aBlocked.goto(`${BASE}/groups/${group.id}?tab=members`, { waitUntil: "load" })
      await aBlocked.getByText("路人丙").first().waitFor({ timeout: 15_000 })
      await mark(aBlocked, "A3")
      await arm(aBlocked, "fallback", /路人丁/)
    })
    const renamedAt = await step("B renames themself again", async () => {
      await aBlocked.waitForTimeout(1000)
      await post(cb, "/me", { display_name: "路人丁" }, "patch")
      return Date.now()
    })
    await step("the blocked tab still picks it up through the 30 s fallback poll", async () => {
      const ms = (await seenAt(aBlocked, "fallback", 45_000)) - renamedAt
      await stillMarked(aBlocked, "A3")
      await aBlocked.screenshot({ path: `${out}/4-a-blocked-fallback.png` })
      return record("stream blocked → fallback poll", ms, 35_000)
    })
    await aBlocked.close()
  }

  // ── 2. 帳本：同一個人兩台裝置 ──────────────────────────────
  const email = `ledger-${RUN}@forliosa.local`
  const d1ctx = await context(browserA, { email, name: "記帳的人" })
  const d2ctx = await context(browserB, { email, name: "記帳的人", video: true })
  const ledgerAccount = await step("the ledger owner has a broker account (API)", async () => post(d1ctx, "/accounts", { name: "國泰", broker: "國泰證券", currency: "TWD" }).then((a) => a.id))
  const d1 = await page(d1ctx, "device1")
  const d2 = await page(d2ctx, "device2")
  await step("device 2 opens the ledger, device 1 too; both streams open", async () => {
    await d2.goto(`${BASE}/`, { waitUntil: "load" })
    await d1.goto(`${BASE}/`, { waitUntil: "load" })
    await d1.getByRole("button", { name: "記一筆", exact: true }).first().waitFor({ timeout: 15_000 })
    await streamOpen(d1)
    await streamOpen(d2)
    await mark(d2, "D2")
    await arm(d2, "holding", /台積電/)
    await notYet(d2, "holding")
    await d2.screenshot({ path: `${out}/2-device2-before.png` })
  })
  const savedAt = await step("device 1 records a 2330 buy with 記一筆", async () => {
    await d1.getByRole("button", { name: "記一筆", exact: true }).first().click()
    const dialog = d1.getByRole("dialog")
    await dialog.getByPlaceholder("代號或名稱，例如 2330、台積").fill("2330")
    await dialog.getByRole("option", { name: /2330/ }).first().click()
    await dialog.getByRole("group", { name: "選好的股票" }).waitFor()
    const qty = dialog.locator("#lot-qty-0")
    await qty.fill((await qty.getAttribute("aria-label")) === "張數" ? "1" : "1000")
    await dialog.getByRole("button", { name: "買進日期，還沒選" }).click()
    await d1.getByRole("button", { name: /年 11 月 10 日/ }).click()
    await dialog.locator("#lot-price-0").fill("1000")
    const saved = d1.waitForResponse((r) => /\/api\/v1\/transactions(\/batch)?$/.test(new URL(r.url()).pathname) && r.request().method() === "POST")
    await dialog.getByRole("button", { name: "新增", exact: true }).click()
    const res = await saved
    const at = Date.now()
    if (!res.ok()) throw new Error(`save ${res.status()}`)
    return at
  })
  await step("device 2's holdings show 2330 within 2 s, without a reload", async () => {
    const ms = (await seenAt(d2, "holding")) - savedAt
    await stillMarked(d2, "D2")
    await d2.getByText("台積電").first().waitFor()
    await d2.screenshot({ path: `${out}/2-device2-after.png` })
    return record("ledger on device 1 → device 2", ms)
  })
  await step("device 1 skipped its own event: each ledger query was read once after saving", async () => {
    await d1.waitForTimeout(2500)
    const after = d1.gets.filter((g) => g.at >= savedAt - 50 && g.path.startsWith("/portfolio/"))
    const counts = {}
    for (const g of after) counts[g.path] = (counts[g.path] ?? 0) + 1
    const twice = Object.entries(counts).filter(([, n]) => n > 1)
    if (!after.length) throw new Error("device 1 did not refetch its ledger at all")
    if (twice.length) throw new Error(`read more than once: ${JSON.stringify(twice)}`)
    const own = d1.rt.filter((r) => r.at >= savedAt - 50 && /\(this tab\)/.test(r.text)).map((r) => r.text)
    if (!own.length) throw new Error(`no "(this tab)" skip logged: ${d1.rt.map((r) => r.text).join(" | ")}`)
    return `${Object.keys(counts).length} queries × 1; skipped: ${[...new Set(own)].join(", ")}`
  })

  // ── 5. 批次 4 的寫入：匯入庫存、刪除這檔、清除所有持倉（裝置 1 送出，裝置 2 開著帳本） ─────────
  await arm(d2, "imported", /鴻海/)
  await notYet(d2, "imported")
  const importedAt = await step("device 1 imports positions: 2330 replaced (以券商為準), 2317 added (API)", async () => {
    const res = await post(d1ctx, "/imports/positions/commit", { account_id: ledgerAccount, rows: [
      { symbol: "2330", quantity: 2000, price: 990, replace: true }, { symbol: "2317", quantity: 1000, price: 200 }] })
    if (!res.replaced?.[0]?.deleted) throw new Error(`nothing replaced: ${JSON.stringify(res.replaced)}`)
    return Date.now()
  })
  await step("device 2's holdings show 2317 within 2 s (匯入庫存)", async () => {
    const ms = (await seenAt(d2, "imported")) - importedAt
    await stillMarked(d2, "D2")
    await d2.screenshot({ path: `${out}/5-device2-imported.png` })
    return record("positions import on device 1 → device 2", ms)
  })
  await armGone(d2, "deleted", /鴻海/)
  await notYet(d2, "deleted")
  const deletedAt = await step("device 1 deletes the 2317 holding (刪除這檔, API)", async () => {
    await post(d1ctx, `/accounts/${ledgerAccount}/holdings/2317.TW`, undefined, "delete")
    return Date.now()
  })
  await step("2317 leaves device 2's holdings within 2 s (刪除這檔: a bulk delete)", async () => {
    const ms = (await seenAt(d2, "deleted")) - deletedAt
    await stillMarked(d2, "D2")
    return record("delete holding on device 1 → device 2", ms)
  })
  await armGone(d2, "cleared", /台積電/)
  await notYet(d2, "cleared")
  const clearedAt = await step("device 1 clears every record (清除所有持倉, API)", async () => {
    await post(d1ctx, `/portfolio/records?all_accounts=true`, undefined, "delete")
    return Date.now()
  })
  await step("device 2's ledger is empty within 2 s (清除所有持倉)", async () => {
    const ms = (await seenAt(d2, "cleared")) - clearedAt
    await stillMarked(d2, "D2")
    await d2.screenshot({ path: `${out}/5-device2-cleared.png` })
    return record("clear records on device 1 → device 2", ms)
  })

  if (errors.length) throw new Error(`page errors / 5xx: ${errors.slice(0, 5).join("; ")}`)
  console.log("全部通過")
} catch (e) {
  if (errors.length) console.log("errors:", errors.slice(0, 8))
  console.log(String(e?.stack ?? e).split("\n").slice(0, 3).join("\n"))
  process.exitCode = 1
} finally {
  writeFileSync(`${out}/latency.json`, JSON.stringify(results, null, 2))
  console.log("latency:", results.map((r) => `${r.name}: ${r.ms} ms`).join("; "))
  await browserA.close()
  await browserB.close()
}
