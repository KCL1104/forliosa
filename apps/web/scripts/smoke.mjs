// 冒煙測試：node scripts/smoke.mjs [--base=http://localhost:5173]
// 走過每個路由，確認關鍵文字出現、沒有 console 錯誤；也測試記一筆交易與隱私模式。
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
let pw
try {
  pw = require("playwright")
} catch {
  pw = require("/opt/node-tools/node_modules/playwright")
}
const base = (process.argv.find((a) => a.startsWith("--base="))?.slice(7) ?? "http://localhost:5173").replace(/\/$/, "")

const ROUTES = [
  ["/", "總資產"],
  ["/holdings", "合計"],
  ["/stock/2330.TW", "公司小卡"],
  ["/stock/2330.TW?tab=kline", "MA20"],
  ["/stock/2330.TW?tab=valuation", "各倍數對應的股價"],
  ["/stock/2409.TW?tab=valuation", "本益比沒有意義"],
  ["/stock/2330.TW?tab=financials", "月營收明細"],
  ["/stock/2330.TW?tab=dividends", "配息紀錄"],
  ["/stock/2330.TW?tab=mine", "我的持有"],
  ["/stock/NOPE.TW", "找不到"],
  ["/transactions", "交易紀錄"],
  ["/performance", "最大回撤"],
  ["/settings", "券商帳戶"],
  ["/watchlist", "自選"],
  ["/ai", "回答的樣子"],
  ["/reports", "盤後報告"],
  ["/groups", "你可以控制分享什麼"],
  ["/import", "匯入流程"],
  ["/more", "更多"],
  ["/does-not-exist", "找不到這個頁面"],
]

const browser = await pw.chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, locale: "zh-TW", timezoneId: "Asia/Taipei" })
const page = await ctx.newPage()
const errors = []
page.on("console", (m) => m.type() === "error" && errors.push(`${page.url()} ${m.text()}`))
page.on("pageerror", (e) => errors.push(`${page.url()} pageerror ${e.message}`))
let failed = 0
const check = async (name, fn) => {
  try {
    await fn()
    console.log("✓", name)
  } catch (e) {
    failed++
    console.error("✗", name, "—", e.message.split("\n")[0])
  }
}

for (const [path, text] of ROUTES) {
  await check(`${path} 顯示「${text}」`, async () => {
    await page.goto(base + path, { waitUntil: "networkidle" })
    await page.getByText(text).first().waitFor({ timeout: 10000 })
  })
}

await check("記一筆交易：試算稅費並儲存，出現「已入帳」章", async () => {
  await page.goto(base + "/transactions", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "記一筆" }).last().click()
  await page.getByPlaceholder("代號或名稱，例如 2330、台積").fill("2454")
  await page.getByRole("option", { name: /2454/ }).first().click()
  await page.locator("#trade-qty").fill("1")
  await page.locator("#trade-price").fill("1435")
  await page.getByText("手續費 0.1425% × 2.8 折").waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "儲存", exact: true }).click()
  await page.getByText("已入帳").waitFor({ timeout: 8000 })
})

await check("隱私模式遮蔽金額", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByText("總資產").first().waitFor()
  await page.getByRole("button", { name: /開啟隱私模式/ }).click()
  await page.getByLabel("已隱藏").first().waitFor({ timeout: 5000 })
})

await check("⌘K 用中文名稱搜尋並進入個股頁", async () => {
  await page.keyboard.press("Control+k")
  await page.keyboard.type("聯發")
  await page.getByRole("option", { name: /2454/ }).first().click()
  await page.waitForURL(/\/stock\/2454\.TW/)
})

await browser.close()
if (errors.length) {
  failed++
  console.error(`\n${errors.length} 個 console 錯誤：\n  ${errors.slice(0, 10).join("\n  ")}`)
}
console.log(failed ? `\n${failed} 項失敗` : "\n全部通過")
process.exitCode = failed ? 1 : 0
