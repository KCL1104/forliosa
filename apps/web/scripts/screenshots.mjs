// 截圖：node scripts/screenshots.mjs [輸出資料夾] [--base=http://localhost:5173] [--real] [--only=ledger,stock-2330-overview]
// 新資訊架構（聯絡簿）預設輸出到 docs/screenshots/v2/：桌面 1440×900 @2x 與 iPhone 15，淺色與深色。
// 需要先啟動 dev server（pnpm dev）。使用預先安裝的 Playwright，不執行 playwright install。
// --real：真實後端的截圖（先啟動 apps/api 與 pnpm dev:api），只拍淺色、輸出到 docs/screenshots/real/。
import { mkdirSync } from "node:fs"
import { createRequire } from "node:module"
import { resolve } from "node:path"

const require = createRequire(import.meta.url)
let pw
try {
  pw = require("playwright")
} catch {
  pw = require("/opt/node-tools/node_modules/playwright")
}
const { chromium, devices } = pw

const args = process.argv.slice(2)
const real = args.includes("--real")
const outDir = resolve(args.find((a) => !a.startsWith("--")) ?? (real ? "../../docs/screenshots/real" : "../../docs/screenshots/v2"))
const base = (args.find((a) => a.startsWith("--base="))?.slice(7) ?? "http://localhost:5173").replace(/\/$/, "")
const only = args.find((a) => a.startsWith("--only="))?.slice(7)?.split(",")
mkdirSync(outDir, { recursive: true })

/** 個股分頁：把分頁列捲到頂端，讓分頁內容出現在第一屏 */
const toTabs = async (page) => {
  await page.evaluate(() => {
    const bar = document.querySelector('[aria-label="個股資料"]')
    if (bar) window.scrollTo({ top: bar.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 64 : 0) - 8, behavior: "instant" })
  })
}
const draft = async (page, mobile) => {
  if (mobile) {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(400)
  }
  const box = mobile ? page.getByLabel(/搜尋股票、提問/) : page.getByLabel("提出問題或下指令")
  await box.fill("買 0050 2 張 52.4")
  await box.press("Enter")
  await page.getByText(/NT\$104,841/).first().waitFor({ timeout: 8000 })
  if (mobile) await page.getByLabel(/搜尋股票、提問/).blur()
}

/** 每個畫面：路徑、就緒條件、截圖前要做的動作 */
const SHOTS = [
  { name: "ledger", path: "/", ready: "text=總資產" },
  { name: "ledger-draft", path: "/", ready: "text=總資產", action: (page, mobile) => draft(page, mobile) },
  { name: "ledger-transactions", path: "/?view=transactions", ready: "text=月" },
  { name: "stock-2330-overview", path: "/stock/2330.TW", ready: "text=參考價" },
  { name: "stock-2330-valuation", path: "/stock/2330.TW?tab=valuation", ready: "text=各倍數對應的股價", action: toTabs },
  { name: "stock-2330-chips", path: "/stock/2330.TW?tab=chips", ready: "text=三大法人買賣超", action: toTabs },
  { name: "history", path: "/history", ready: "text=發起新對話" },
  { name: "ai", path: "/", ready: "text=總資產", mobileOnly: true, action: async (page) => {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(500)
  } },
]
const REAL_SHOTS = SHOTS.filter((s) => !s.action)

/** 第一次 GET /me 在開發登入前是 401（預期中），其他 console 錯誤都算失敗 */
const EXPECTED = [/status of 401 \(Unauthorized\)/]

const VARIANTS = [
  { id: "desktop", ctx: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 } },
  { id: "iphone", ctx: { ...devices["iPhone 15"] } },
]

const errors = []
const browser = await chromium.launch()
for (const variant of VARIANTS) {
  for (const scheme of real ? ["light"] : ["light", "dark"]) {
    for (const shot of real ? REAL_SHOTS : SHOTS) {
      if (only && !only.includes(shot.name)) continue
      if (shot.mobileOnly && variant.id !== "iphone") continue
      // 每張截圖用全新的瀏覽器狀態（AI 對話與草稿存在 localStorage）
      const context = await browser.newContext({ ...variant.ctx, colorScheme: scheme, reducedMotion: "reduce", locale: "zh-TW", timezoneId: "Asia/Taipei" })
      const page = await context.newPage()
      page.on("console", (m) => {
        if (m.type() === "error" && !(real && EXPECTED.some((re) => re.test(m.text())))) errors.push(`[${variant.id}/${scheme}/${shot.name}] ${m.text()}`)
      })
      page.on("requestfailed", (r) => {
        if (!r.failure()?.errorText.includes("ERR_ABORTED")) errors.push(`[${variant.id}/${scheme}/${shot.name}] request failed ${r.url()}`)
      })
      page.on("pageerror", (e) => errors.push(`[${variant.id}/${scheme}/${shot.name}] pageerror ${e.message}`))
      await page.goto(base + shot.path, { waitUntil: "networkidle" })
      const ready = variant.id === "iphone" && shot.mobileReady ? shot.mobileReady : shot.ready
      await page.locator(`${ready} >> visible=true`).first().waitFor({ timeout: 15000 })
      if (shot.action) await shot.action(page, variant.id === "iphone")
      await page.waitForLoadState("networkidle")
      await page.waitForTimeout(real ? 1200 : 700)
      const file = `${outDir}/${shot.name}-${variant.id}${real ? "" : `-${scheme}`}.png`
      await page.screenshot({ path: file })
      console.log("✓", file)
      await page.close()
      await context.close()
    }
  }
}
await browser.close()
if (errors.length) {
  console.error(`\n${errors.length} 個 console 錯誤：`)
  for (const e of errors) console.error(" ", e)
  process.exitCode = 1
}
