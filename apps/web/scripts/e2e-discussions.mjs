// 討論串的前後端實測（真實後端，不是 mock）：發公開主題 → 另一人設定暱稱並回覆 → 頻率限制 → 表情 → 檢舉 → 站方隱藏 → 其他人只看到佔位文字；
// 並確認匿名讀取的回應沒有身分欄位。前端與後端是照合約分開做的，改了任何一邊之後跑這支。
//
// 1. 後端（全新的資料庫；dev 模式才有開發登入；demo@forliosa.local 是前端自動登入的帳號，設成站方管理員）：
//      cd apps/api && export DATABASE_URL=sqlite:////tmp/forliosa-e2e.db FORLIOSA_ENV=dev ADMIN_EMAILS=demo@forliosa.local \
//        CORS_ORIGINS=http://localhost:5231 MARKET_DATA_PROVIDERS= && uv run alembic upgrade head && uv run uvicorn forliosa.main:app --port 8010
// 2. 前端（連真實後端）：cd apps/web && FORLIOSA_API_ORIGIN=http://localhost:8010 pnpm exec vite --mode api --port 5231 --strictPort
// 3. node scripts/e2e-discussions.mjs [截圖輸出資料夾] [--base=http://localhost:5231]
import { mkdirSync } from "node:fs"
import { createRequire } from "node:module"
const require = createRequire(import.meta.url)
let pw; try { pw = require("playwright") } catch { pw = require("/opt/node-tools/node_modules/playwright") }
const args = process.argv.slice(2)
const BASE = (args.find((a) => a.startsWith("--base="))?.slice(7) ?? "http://localhost:5231").replace(/\/$/, "")
const out = args.find((a) => !a.startsWith("--")) ?? "/tmp/forliosa-e2e"
mkdirSync(out, { recursive: true })
const step = async (name, fn) => { try { const r = await fn(); console.log("✓", name, r ?? ""); return r } catch (e) { console.log("✗", name, "—", String(e.message).split("\n")[0]); throw e } }
const b = await pw.chromium.launch()
const errors = []
const mk = async () => { const c = await b.newContext({ viewport: { width: 1280, height: 900 }, locale: "zh-TW" }); const p = await c.newPage(); p.on("pageerror", (e) => errors.push(String(e))); p.on("response", (r) => { if (r.status() >= 500) errors.push(`${r.status()} ${r.url()}`) }); return [c, p] }
try {
  // A: the dev-login demo user (site admin via ADMIN_EMAILS)
  const [, a] = await mk()
  await step("A opens the list (auto dev login), empty state", async () => { await a.goto(`${BASE}/discussions`, { waitUntil: "networkidle" }); await a.getByRole("heading", { name: "討論", level: 1 }).waitFor({ timeout: 15000 }) })
  await step("A starts a new public topic and is asked for a public name", async () => {
    await a.getByRole("link", { name: "開新主題" }).first().click()
    await a.getByRole("heading", { name: "開新主題" }).waitFor()
    await a.getByRole("radio", { name: /^公開/ }).check()
    await a.getByRole("form", { name: "選公開暱稱" }).waitFor({ timeout: 8000 })
  })
  await step("A sets the public name", async () => {
    const f = a.getByRole("form", { name: "選公開暱稱" })
    await f.getByRole("textbox").fill("測試阿土伯")
    await f.getByRole("button", { name: "用這個暱稱" }).click()
    await a.getByRole("form", { name: "新主題" }).waitFor({ timeout: 8000 })
  })
  const topicUrl = await step("A posts a public topic", async () => {
    await a.getByLabel("標題").fill("實測：0050 要不要改買 006208？")
    await a.getByLabel("內文").fill("第一行\n第二行 https://example.com/x 看看連結")
    await a.getByRole("button", { name: "發表" }).click()
    await a.getByRole("heading", { name: "實測：0050 要不要改買 006208？" }).waitFor({ timeout: 10000 })
    return a.url()
  })
  await step("the link in the body is safe", async () => {
    const l = a.getByRole("link", { name: /example\.com/ })
    const rel = await l.getAttribute("rel")
    if (!rel?.includes("nofollow") || !rel.includes("noopener") || (await l.getAttribute("target")) !== "_blank") throw new Error(`rel=${rel}`)
  })
  // B: another signed-in user
  const [cb, pb] = await mk()
  await step("B signs in (dev login with another email)", async () => {
    const r = await cb.request.post(`${BASE}/api/v1/auth/dev-login`, { data: { email: "other@forliosa.local", display_name: "路人甲" }, headers: { Origin: BASE } })
    if (!r.ok()) throw new Error(`dev-login ${r.status()} ${await r.text()}`)
  })
  await step("B opens the topic, sees the public name only", async () => {
    await pb.goto(topicUrl, { waitUntil: "networkidle" })
    await pb.getByRole("heading", { name: "實測：0050 要不要改買 006208？" }).waitFor({ timeout: 10000 })
    await pb.getByText("測試阿土伯").first().waitFor()
    const html = await pb.content()
    if (html.includes("demo@forliosa.local")) throw new Error("email leaked")
  })
  await step("B must choose a public name before replying, then replies", async () => {
    const f = pb.getByRole("form", { name: "選公開暱稱" })
    await f.waitFor({ timeout: 8000 })
    await f.getByRole("textbox").fill("實測路人")
    await f.getByRole("button", { name: "用這個暱稱" }).click()
    const reply = pb.getByRole("form", { name: "回覆這個主題" })
    await reply.waitFor({ timeout: 8000 })
    await reply.getByRole("textbox").fill("我覺得可以，費用率比較低")
    await reply.getByRole("button", { name: "回覆" }).click()
    await pb.getByText("我覺得可以，費用率比較低").waitFor({ timeout: 10000 })
  })
  await step("B replies again at once and gets the rate-limit message", async () => {
    const reply = pb.getByRole("form", { name: "回覆這個主題" })
    await reply.getByRole("textbox").fill("再補一句")
    await reply.getByRole("button", { name: "回覆" }).click()
    await pb.getByText(/秒後/).first().waitFor({ timeout: 8000 })
    return (await pb.getByText(/秒後/).first().innerText()).slice(0, 40)
  })
  await step("B reacts to the topic and reports it", async () => {
    await pb.getByRole("button", { name: /加表情/ }).first().click()
    await pb.getByRole("button", { name: /👍|讚/ }).first().click()
    await pb.getByRole("button", { name: "檢舉" }).first().click()
    const d = pb.getByRole("dialog")
    await d.getByRole("radio").first().check()
    await d.getByRole("button", { name: "送出檢舉" }).click()
    await pb.getByText("已收到檢舉").waitFor({ timeout: 8000 })
  })
  await step("A (site admin) sees the report and hides the topic", async () => {
    await a.goto(`${BASE}/admin/discussions`, { waitUntil: "networkidle" })
    await a.getByText("實測：0050 要不要改買 006208？").first().waitFor({ timeout: 10000 })
    await a.screenshot({ path: `${out}/admin.png` })
    await a.getByRole("button", { name: "隱藏" }).first().click()
    const dlg = a.getByRole("alertdialog")
    await dlg.getByRole("button", { name: /隱藏/ }).click()
    await a.waitForTimeout(1200)
  })
  await step("B now sees the hidden placeholder, not the title or body", async () => {
    await pb.goto(topicUrl, { waitUntil: "networkidle" })
    await pb.getByText(/已被站方隱藏/).first().waitFor({ timeout: 10000 })
    const text = await pb.locator("main").innerText()
    if (text.includes("第一行") || text.includes("要不要改買")) throw new Error("hidden content visible")
    await pb.screenshot({ path: `${out}/hidden.png` })
  })
  await step("anonymous API read of the list has no identity fields", async () => {
    const r = await (await b.newContext()).request.get(`${BASE}/api/v1/discussions/topics`)
    const body = await r.text()
    if (!r.ok()) throw new Error(`status ${r.status()}`)
    for (const k of ["user_id", "email", "avatar_url", "display_name"]) if (body.includes(k)) throw new Error(`leaks ${k}`)
    return body.slice(0, 80)
  })
  if (errors.length) throw new Error(`page errors / 5xx: ${errors.slice(0, 5).join("; ")}`)
  console.log("全部通過")
} catch {
  process.exitCode = 1
} finally {
  await b.close()
}
