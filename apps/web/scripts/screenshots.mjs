// 截圖與冒煙測試：node scripts/screenshots.mjs [輸出資料夾] [--base=http://localhost:5173]
// 需要先啟動 dev server（pnpm dev）。使用預先安裝的 Playwright，不執行 playwright install。
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
const outDir = resolve(args.find((a) => !a.startsWith("--")) ?? "../../docs/screenshots")
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

const VARIANTS = [
  { id: "desktop", ctx: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 } },
  { id: "iphone", ctx: { ...devices["iPhone 15"] } },
]

const errors = []
const browser = await chromium.launch()
for (const variant of VARIANTS) {
  for (const scheme of ["light", "dark"]) {
    const context = await browser.newContext({ ...variant.ctx, colorScheme: scheme, reducedMotion: "reduce", locale: "zh-TW", timezoneId: "Asia/Taipei" })
    for (const shot of SHOTS) {
      if (only && !only.includes(shot.name)) continue
      const page = await context.newPage()
      page.on("console", (m) => m.type() === "error" && errors.push(`[${variant.id}/${scheme}/${shot.name}] ${m.text()}`))
      page.on("pageerror", (e) => errors.push(`[${variant.id}/${scheme}/${shot.name}] pageerror ${e.message}`))
      await page.goto(base + shot.path, { waitUntil: "networkidle" })
      const ready = variant.id === "iphone" && shot.mobileReady ? shot.mobileReady : shot.ready
      await page.locator(`${ready} >> visible=true`).first().waitFor({ timeout: 15000 })
      if (shot.action) await shot.action(page)
      await page.waitForTimeout(700)
      const file = `${outDir}/${shot.name}-${variant.id}-${scheme}.png`
      await page.screenshot({ path: file, fullPage: !shot.action && variant.id === "desktop" })
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
