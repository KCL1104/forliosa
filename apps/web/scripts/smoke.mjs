// 冒煙測試（新資訊架構，mock 模式）：node scripts/smoke.mjs [--base=http://localhost:5173]
// 走過每個路由，確認關鍵文字出現、沒有 console 錯誤；也測試 AI 草稿→簽名入帳→復原、隱私模式、⌘K、手機的問 AI。
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
  ["/?view=transactions", "數量 × 價格"],
  ["/?view=dividends", "已入帳"],
  ["/?view=performance", "最大回撤"],
  ["/stock/2330.TW", "近四季 EPS"],
  ["/stock/2330.TW?tab=valuation", "各倍數對應的股價"],
  ["/stock/2409.TW?tab=valuation", "本益比沒有意義"],
  ["/stock/2330.TW?tab=financials", "營業利益率"],
  ["/stock/2330.TW?tab=chips", "三大法人買賣超"],
  ["/stock/2330.TW?tab=dividends", "配息紀錄"],
  ["/stock/2330.TW?tab=events", "法說會"],
  ["/stock/0050.TW?tab=financials", "成分股資料來源還在確認"],
  ["/stock/NVDA?tab=chips", "美股沒有台股的法人"],
  ["/stock/NOPE.TW", "找不到"],
  ["/groups", "群組在 M5 開放"],
  ["/history", "發起新對話"],
  ["/settings", "券商帳戶"],
  ["/transactions", "數量 × 價格"],
  ["/does-not-exist", "找不到這個頁面"],
]

const browser = await pw.chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-TW", timezoneId: "Asia/Taipei" })
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

await check("建議問題：點了就用自己的資料回答（誰拖累了我）", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "今天誰拖累了我的報酬？" }).click()
  await page.getByText(/今天拖累最多的是/).waitFor({ timeout: 5000 })
})

await check("AI 草稿：買 0050 2 張 52.4 → 稅費試算 → 待簽名 → 簽名入帳 → 復原", async () => {
  await page.getByRole("button", { name: "新對話" }).click()
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("買 0050 2 張 52.4")
  await box.press("Enter")
  await page.getByText("NT$104,841").waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: /待簽名 1 筆/ }).waitFor({ timeout: 5000 })
  await page.getByRole("button", { name: "簽名：確認入帳" }).click()
  await page.getByText(/已入帳：買進 元大台灣50/).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "復原" }).first().click()
  await page.getByText("已復原，草稿還在等你簽名").waitFor({ timeout: 8000 })
})

await check("股利指令：00878 配息 1,100 寫成草稿", async () => {
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("00878 配息 1,100")
  await box.press("Enter")
  await page.getByRole("heading", { name: /股利入帳 國泰永續高股息/ }).waitFor({ timeout: 8000 })
})

await check("自由提問：誠實說明下一階段，給手動路徑", async () => {
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("台積電的護城河是什麼")
  await box.press("Enter")
  await page.getByText(/完整的 AI 回答在下一階段開放/).last().waitFor({ timeout: 5000 })
})

await check("手動記帳表單（備援路徑）：試算稅費並儲存", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "附件與其他記帳方式" }).click()
  await page.getByRole("menuitem", { name: /改用表單記一筆/ }).click()
  await page.getByPlaceholder("代號或名稱，例如 2330、台積").fill("2454")
  await page.getByRole("option", { name: /2454/ }).first().click()
  await page.locator("#trade-qty").fill("1")
  await page.locator("#trade-price").fill("1435")
  await page.getByRole("dialog").getByText("手續費 0.1425% × 2.8 折").waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "儲存", exact: true }).click()
  await page.getByText(/已記錄：買進 聯發科/).waitFor({ timeout: 8000 })
})

await check("隱私模式遮蔽金額", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "隱私模式：遮蔽金額" }).click()
  await page.getByLabel("已隱藏").first().waitFor({ timeout: 5000 })
  await page.getByRole("button", { name: /隱私模式開啟中/ }).click()
})

await check("⌘K 用中文名稱搜尋並進入個股頁", async () => {
  await page.keyboard.press("Control+k")
  await page.keyboard.type("聯發")
  await page.getByRole("option", { name: /2454/ }).first().click()
  await page.waitForURL(/\/stock\/2454\.TW/)
})

await check("AI 面板收合後記得狀態", async () => {
  await page.getByRole("button", { name: "收合 AI 面板" }).click()
  await page.reload({ waitUntil: "networkidle" })
  await page.getByRole("button", { name: /展開 AI 面板/ }).click()
  await page.getByRole("button", { name: "收合 AI 面板" }).waitFor()
})

await check("頭像選單切換深色", async () => {
  await page.getByRole("button", { name: /帳號選單/ }).click()
  await page.getByRole("menuitemradio", { name: /深色/ }).click()
  await page.waitForFunction(() => document.documentElement.classList.contains("dark"))
})

// 手機：浮動分頁＋問 AI 全螢幕（搜尋住在這裡）
const mctx = await browser.newContext({ ...pw.devices["iPhone 15"], locale: "zh-TW", timezoneId: "Asia/Taipei" })
const m = await mctx.newPage()
m.on("pageerror", (e) => errors.push(`mobile pageerror ${e.message}`))
await check("手機：問 AI 搜尋「台積」進入個股頁", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  await m.getByRole("button", { name: /^問 AI/ }).click()
  await m.getByLabel(/搜尋股票、提問/).fill("台積")
  await m.getByRole("button", { name: /2330 台積電/ }).click()
  await m.waitForURL(/\/stock\/2330\.TW/)
})
await check("手機：底部分頁到紀錄", async () => {
  await m.getByRole("link", { name: "紀錄" }).click()
  await m.getByText("發起新對話").waitFor()
})

await browser.close()
if (errors.length) {
  failed++
  console.error(`\n${errors.length} 個 console 錯誤：\n  ${errors.slice(0, 10).join("\n  ")}`)
}
console.log(failed ? `\n${failed} 項失敗` : "\n全部通過")
process.exitCode = failed ? 1 : 0
