// 截圖：node scripts/screenshots.mjs [輸出資料夾] [--base=http://localhost:5173] [--real] [--only=ledger,stock-2330-overview]
// 新資訊架構（聯絡簿）預設輸出到 docs/screenshots/v2/：桌面 1440×900 @2x 與 iPhone 15，淺色與深色。
// mock 預設模擬商用模式（DATA_POLICY=commercial：沒有示範標記、存檔不足處寫「資料累積中」）。
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

/** 已出清：展開持倉底下的區塊（依年份分組，最近一年展開），捲到它的標題 */
const closed = async (page) => {
  await page.getByRole("button", { name: /已出清/ }).click()
  await page.locator("#closed-list").waitFor()
  await page.evaluate(() => {
    const el = document.getElementById("closed-title")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 340 : 90), behavior: "instant" })
  })
}
/** 法人觀點：捲到區塊標題（桌面：頂部列 64＋sticky 分頁列 48；手機：sticky 分頁列） */
const toAnalyst = async (page, mobile) => {
  await page.evaluate((m) => {
    const el = document.getElementById("ov-analyst-title")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (m ? 72 : 136), behavior: "instant" })
  }, mobile)
}
/** 法人觀點：展開總覽的收合區塊（2330 今天已經有人查過，直接有 3 筆），捲到它的標題 */
const analyst = async (page, mobile) => {
  await page.getByRole("button", { name: /法人觀點/ }).click()
  await page.locator("#ov-analyst-body").getByText(/查詢時間/).waitFor({ timeout: 8000 })
  await toAnalyst(page, mobile)
}
/** 法人觀點的其他狀態：展開 → 按「查詢近期法人觀點」→ 等到指定文字（搜尋中／查無報導／查不到） */
const analystSearch = (text) => async (page, mobile) => {
  await page.getByRole("button", { name: /法人觀點/ }).click()
  await page.getByRole("button", { name: "查詢近期法人觀點" }).click()
  await page.locator("#ov-analyst-body").getByText(text).first().waitFor({ timeout: 8000 })
  await toAnalyst(page, mobile)
}
/** 持倉的定期定額標記：桌面滑過 0050 的標記看說明；手機捲到持倉清單 */
const recurringMarks = async (page, mobile) => {
  if (mobile) {
    await page.evaluate(() => {
      const el = document.querySelector('ul[aria-label="持倉"]')
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 140, behavior: "instant" })
    })
    return
  }
  await page.getByRole("table", { name: "持倉" }).getByRole("link", { name: /定期定額：每月 6 日/ }).hover()
  await page.locator('[data-slot="tooltip-content"]').waitFor()
}
/** 設定 → 定期定額 */
const recurring = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("recurring")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}
/** 扣款日：AI 面板提出定期定額草稿（示範資料的 11/12 是 00878 的扣款日） */
const recurringDraft = async (page, mobile) => {
  if (mobile) {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(400)
  }
  await page.getByRole("button", { name: /記下.*00878 定期定額/ }).click()
  await page.getByText("確認入帳").first().waitFor({ timeout: 8000 })
}

/** 股利自動入帳：改一筆自動入帳的股利（2454 10/8），交易列表同時看到「自動」與「自動・已修改」 */
const autoEdited = async (page) => {
  await page.getByRole("button", { name: /^編輯 10\/8.*2454（自動）$/ }).click()
  // 等股票帶入表單（非同步）再改
  await page.getByRole("dialog").getByText("聯發科").waitFor({ timeout: 8000 })
  await page.locator("#trade-note").fill("零股，券商入帳 5,000")
  await page.getByRole("button", { name: "儲存變更" }).click()
  await page.getByText("自動・已修改").first().waitFor({ timeout: 8000 })
  await page.getByText("已更新這筆交易").waitFor({ state: "hidden", timeout: 10000 })
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
  // 捲到改過的那一列：下面接著 9/22、9/16 的「自動」
  await page.getByRole("button", { name: /^編輯 10\/8.*2454（自動・已修改）$/ }).evaluate((el) => {
    window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 200 : 120), behavior: "instant" })
  })
}
/** 股利頁：捲到「已入帳」 */
const received = async (page, mobile) => {
  await page.evaluate((m) => {
    const el = document.getElementById("div-received")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (m ? 16 : 96), behavior: "instant" })
  }, mobile)
}
/** 編輯自動入帳的股利（2330 9/16）：表單上方說明儲存與刪除之後會怎樣（列表是虛擬化的：手機要往下捲才會出現那一列） */
const autoEdit = async (page) => {
  const row = page.getByRole("button", { name: /^編輯 9\/16.*2330（自動）$/ })
  for (let i = 0; i < 20 && !(await row.count()); i++) {
    await page.evaluate(() => window.scrollBy(0, 400))
    await page.waitForTimeout(150)
  }
  await row.click()
  await page.getByText(/儲存變更後就是你自己的版本/).waitFor({ timeout: 8000 })
  await page.getByRole("dialog").getByText("台積電").waitFor({ timeout: 8000 })
}

/** 每個畫面：路徑、就緒條件、截圖前要做的動作 */
const SHOTS = [
  { name: "ledger", path: "/", ready: "text=總資產" },
  { name: "ledger-draft", path: "/", ready: "text=總資產", action: (page, mobile) => draft(page, mobile) },
  { name: "ledger-transactions", path: "/?view=transactions", ready: "text=月" },
  { name: "stock-2330-overview", path: "/stock/2330.TW", ready: "text=參考價" },
  { name: "stock-2330-analyst", path: "/stock/2330.TW", ready: "text=參考價", action: analyst },
  { name: "stock-2454-analyst-searching", path: "/stock/2454.TW", ready: "text=參考價", action: analystSearch(/正在找近期媒體報導/) },
  { name: "stock-2881-analyst-empty", path: "/stock/2881.TW", ready: "text=參考價", action: analystSearch("近期查無法人報導") },
  { name: "stock-2409-analyst-unavailable", path: "/stock/2409.TW", ready: "text=參考價", action: analystSearch(/法人觀點暫時查不到/) },
  { name: "ledger-recurring-marks", path: "/", ready: "text=總資產", action: recurringMarks },
  { name: "stock-2330-valuation", path: "/stock/2330.TW?tab=valuation", ready: "text=各倍數對應的股價", action: toTabs },
  { name: "stock-2330-chips", path: "/stock/2330.TW?tab=chips", ready: "text=三大法人資料累積中", action: toTabs },
  { name: "ledger-closed", path: "/", ready: "text=總資產", action: closed },
  { name: "ledger-recurring-draft", path: "/", ready: "text=總資產", action: recurringDraft },
  { name: "stock-2603-past", path: "/stock/2603.TW", ready: "text=過去的持有" },
  // 美股：SEC EDGAR 的季報（美元、公司會計年度）與 8-K／10-Q／10-K 申報
  { name: "stock-aapl-financials", path: "/stock/AAPL?tab=financials", ready: "text=FY2026Q4", action: toTabs },
  { name: "stock-aapl-events", path: "/stock/AAPL?tab=events", ready: "text=10-K 年度報告", action: toTabs },
  { name: "settings-recurring", path: "/settings", ready: "text=新增定期定額", action: recurring },
  { name: "data-sources", path: "/data-sources", ready: "text=上市個股日成交資訊" },
  { name: "history", path: "/history", ready: "text=發起新對話" },
  { name: "ledger-auto-dividends-transactions", path: "/?view=transactions", ready: "text=月", action: autoEdited },
  { name: "ledger-auto-dividends-dividends", path: "/?view=dividends", ready: "text=已入帳", action: received },
  { name: "ledger-auto-dividends-edit", path: "/?view=transactions", ready: "text=月", action: autoEdit },
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
