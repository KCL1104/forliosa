// 截圖與冒煙測試：node scripts/screenshots.mjs [輸出資料夾] [--base=http://localhost:5173] [--real]
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
const outDir = resolve(args.find((a) => !a.startsWith("--")) ?? (real ? "../../docs/screenshots/real" : "../../docs/screenshots"))
const base = (args.find((a) => a.startsWith("--base="))?.slice(7) ?? "http://localhost:5173").replace(/\/$/, "")
const only = args.find((a) => a.startsWith("--only="))?.slice(7)?.split(",")
mkdirSync(outDir, { recursive: true })

/** 每個畫面：路徑與截圖前要做的動作 */
const SHOTS = [
  { name: "home", path: "/", ready: "text=總資產" },
  { name: "holdings", path: "/holdings", ready: "text=合計" , mobileReady: "text=台積電" },
  { name: "stock-valuation", path: "/stock/2330.TW?tab=valuation", ready: "text=各倍數對應的股價" },
  {
    name: "trade-form",
    path: "/transactions",
    ready: "text=交易紀錄",
    action: async (page) => {
      await page.getByRole("button", { name: "記一筆" }).last().click()
      await page.getByPlaceholder("代號或名稱，例如 2330、台積").fill("台積")
      await page.getByRole("option", { name: /2330/ }).first().click()
      await page.locator("#trade-qty").fill("1")
      await page.locator("#trade-price").fill("1085")
      await page.getByText("應付").first().waitFor({ timeout: 8000 })
    },
  },
  { name: "performance", path: "/performance", ready: "text=最大回撤" },
  { name: "settings", path: "/settings", ready: "text=券商帳戶" },
]

/** 真實後端：總覽、持股、個股頁（估值、K 線）、績效 */
const REAL_SHOTS = [
  { name: "home", path: "/", ready: "text=總資產" },
  { name: "holdings", path: "/holdings", ready: "text=合計", mobileReady: "text=台積電" },
  { name: "stock-2330-valuation", path: "/stock/2330.TW?tab=valuation", ready: "text=各倍數對應的股價" },
  { name: "stock-2330-kline", path: "/stock/2330.TW?tab=kline", ready: "text=MA20" },
  { name: "performance", path: "/performance", ready: "text=最大回撤" },
]
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
    const context = await browser.newContext({ ...variant.ctx, colorScheme: scheme, reducedMotion: "reduce", locale: "zh-TW", timezoneId: "Asia/Taipei" })
    for (const shot of real ? REAL_SHOTS : SHOTS) {
      if (only && !only.includes(shot.name)) continue
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
      if (shot.action) await shot.action(page)
      await page.waitForLoadState("networkidle")
      await page.waitForTimeout(real ? 1200 : 700)
      const file = `${outDir}/${shot.name}-${variant.id}${real ? "" : `-${scheme}`}.png`
      if (!shot.action && variant.id === "desktop") {
        // 整頁截圖：不用 fullPage（Chromium 在截圖時重新排版超出視窗的部分，Recharts 圖表沒有重新量測，
        // 會畫出面板右緣）。改成把視窗拉高到整頁，讓 ResizeObserver 正常觸發後再截。
        const size = page.viewportSize()
        const height = await page.evaluate(() => document.documentElement.scrollHeight)
        await page.setViewportSize({ width: size.width, height })
        await page.waitForTimeout(800)
        await page.screenshot({ path: file })
        await page.setViewportSize(size)
      } else {
        await page.screenshot({ path: file })
      }
      console.log("✓", file)
      await page.close()
    }
    await context.close()
  }
}
await browser.close()
if (errors.length) {
  console.error(`\n${errors.length} 個 console 錯誤：`)
  for (const e of errors) console.error(" ", e)
  process.exitCode = 1
}
