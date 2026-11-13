// 冒煙測試（新資訊架構，mock 模式）：node scripts/smoke.mjs [--base=http://localhost:5173]
// 走過每個路由，確認關鍵文字出現、沒有 console 錯誤；也測試 AI 草稿→簽名入帳→復原、隱私模式、⌘K、手機的問 AI，
// 以及第二批：出清紀錄、定期定額（設定與扣款日草稿）、公告、1 日走勢的授權說明、資料來源與授權、商用模式沒有示範標記；
// 第三批：法人觀點（展開 → 查詢 → 搜尋中 → 結果／查無／查不到）、持倉的定期定額標記、補記漏記的扣款、已出清依年份分組。
// 第四批：股利自動入帳（交易與股利頁的「自動」、編輯後「自動・已修改」、刪除後不再出現）。
// 第五批：上市股票不顯示逐檔三大法人（空狀態＋問 AI 外資動向，上櫃照常）、補記定期定額用扣款日的收盤價。
// M5 分享：群組（建立、邀請連結、排行與討論串、動態與表情、我的分享、成員分享、頻道）、邀請（沒登入 → 登入 → 選分享 → 加入）、
// 授權查看（授權給別人、查看別人的唯讀模式、授權失效自動退出）、登入頁的錯誤說明。
// mock 預設模擬商用模式（DATA_POLICY=commercial）；`?policy=personal` 的頁面會記在 sessionStorage，下一個路由用 `?policy=commercial` 切回。
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
  ["/?view=transactions", "稅費"],
  ["/?view=dividends", "已入帳"],
  ["/?view=performance", "績效還算不出來"],
  ["/stock/2330.TW", "近四季 EPS"],
  ["/stock/2330.TW?tab=valuation", "各倍數對應的股價"],
  // 友達虧損的年份在商用模式的存檔起點之前：用示範資料（personal）看「本益比沒有意義」
  ["/stock/2409.TW?tab=valuation&policy=personal", "本益比沒有意義"],
  ["/stock/2330.TW?tab=financials&policy=commercial", "營業利益率"],
  ["/stock/2330.TW?tab=chips", "上市股票不顯示逐檔三大法人"],
  ["/stock/3711.TW?tab=chips", "前 20 名第 12 名"],
  ["/stock/6488.TWO?tab=chips", "三大法人買賣超"],
  ["/stock/2603.TW", "過去的持有"],
  ["/data-sources", "上市個股日成交資訊"],
  ["/stock/2330.TW?tab=dividends", "配息紀錄"],
  ["/stock/2330.TW?tab=events", "法說會"],
  ["/stock/0050.TW?tab=financials", "成分股資料來源還在確認"],
  ["/stock/NVDA?tab=chips", "美股沒有台股的法人"],
  ["/stock/NOPE.TW", "找不到"],
  ["/groups", "家族投資"],
  ["/groups/grp_family", "元大台灣50"],
  ["/groups/grp_family?tab=feed", "加入了群組"],
  ["/groups/grp_family?tab=holdings", "共同持股"],
  ["/groups/grp_family?tab=digests", "AI 分析僅供參考，不構成投資建議。"],
  ["/groups/grp_family?tab=members", "邀請連結"],
  ["/groups/grp_friends?tab=channels", "已停用"],
  ["/groups/grp_club", "找不到這個群組"],
  ["/invite/club-2026", "分享什麼"],
  ["/invite/club-expired", "這個邀請已經失效"],
  ["/history", "發起新對話"],
  ["/settings", "券商帳戶"],
  ["/transactions", "稅費"],
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
    if (process.env.SMOKE_SHOTS) await page.screenshot({ path: `${process.env.SMOKE_SHOTS}/smoke-fail-${failed}.png` }).catch(() => {})
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

await check("自由提問：誠實說明這裡先不回答（不猜、不承諾時程），給手動路徑", async () => {
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("台積電的護城河是什麼")
  await box.press("Enter")
  // 規則版回答用現在式：說明這題要查資料、這裡先不回答，再給最接近的手動路徑（帳本上是「看持倉」）
  const panel = page.getByRole("complementary", { name: "問 AI" })
  await panel.getByText(/這題要查資料並附來源，這裡先不回答/).last().waitFor({ timeout: 5000 })
  if (await panel.getByText(/下一階段/).count()) throw new Error("fallback must not promise a timeline")
  const path = panel.getByRole("link", { name: /看持倉/ }).last()
  await path.waitFor()
  if ((await path.getAttribute("href")) !== "/") throw new Error(`manual path ${await path.getAttribute("href")}`)
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

// ── 第二輪設計修飾：外殼與帳本 ─────────────────────────────────
await check("交易：欄位是 日期・類型・商品・帳戶・數量・價格・金額・稅費；商品是名稱＋代號；自動入帳的備註整句看得到", async () => {
  await page.goto(base + "/?view=transactions", { waitUntil: "networkidle" })
  const head = page.locator(".form-head").filter({ hasText: "商品" })
  await head.waitFor({ timeout: 8000 })
  const cols = await head.locator("> span").evaluateAll((els) => els.filter((el) => el.getBoundingClientRect().width > 2).map((el) => el.textContent.trim()))
  if (cols.join("・") !== "日期・類型・商品・帳戶・數量・價格・金額・稅費") throw new Error(`columns: ${cols.join("・")}`)
  // 表頭的雙線是畫出來的框線（::after），不是背景漸層
  const rule = await head.evaluate((el) => {
    const after = getComputedStyle(el, "::after")
    return { bg: getComputedStyle(el).backgroundImage, top: after.borderTopWidth, bottom: after.borderBottomWidth, h: after.height }
  })
  if (rule.bg !== "none" || rule.top !== "1px" || rule.bottom !== "1px") throw new Error(`form-head rule ${JSON.stringify(rule)}`)
  const row = page.getByRole("button", { name: /^編輯 10\/8.*聯發科 2454（自動）$/ })
  await row.waitFor({ timeout: 8000 })
  await row.getByRole("link", { name: "聯發科", exact: true }).waitFor()
  await row.getByText("2454", { exact: true }).waitFor()
  const note = row.getByText(/^除息前一日持有 200 股/)
  await note.waitFor()
  const clipped = await note.evaluate((el) => el.scrollWidth > el.clientWidth + 1 || getComputedStyle(el).textOverflow === "ellipsis" || getComputedStyle(el).overflow === "hidden")
  if (clipped) throw new Error("the auto-dividend note is truncated")
  if (!(await note.textContent()).includes("發放日")) throw new Error("the auto-dividend note lost its ending")
  // 數量與價格各自一欄，靠右對齊在各自的表頭下面
  const aligned = await page.evaluate(() => {
    const head = [...document.querySelectorAll(".form-head")].find((el) => el.textContent.includes("商品"))
    const right = (label) => [...head.children].find((c) => c.textContent.trim() === label).getBoundingClientRect().right
    const row = [...document.querySelectorAll('[role="button"]')].find((el) => /^編輯 10\/8.*2454/.test(el.getAttribute("aria-label") ?? ""))
    const cell = (text) => [...row.children].find((c) => c.textContent.trim() === text && c.getBoundingClientRect().width > 0)?.getBoundingClientRect().right
    return { qty: [right("數量"), cell("200 股")], price: [right("價格"), cell("25.00")] }
  })
  for (const [k, [h, c]] of Object.entries(aligned)) if (c === undefined || Math.abs(h - c) > 1) throw new Error(`${k} column not under its head: ${h} vs ${c}`)
})
// 範圍是頂部列與頁面內容（AI 面板裡規則版回答的「看持倉 →」這類連結不在這一項的範圍）
await check('aria-current="page" 只在頂部列的導覽上；字標、本週事項、走勢原因這些連到目前網址的連結沒有', async () => {
  for (const path of ["/", "/?view=dividends", "/?view=performance", "/stock/2330.TW"]) {
    await page.goto(base + path, { waitUntil: "networkidle" })
    await page.getByRole("link", { name: "Forliosa 帳本" }).waitFor({ timeout: 8000 })
    await page.waitForTimeout(300)
    const marks = await page.evaluate(() =>
      [...document.querySelectorAll('header [aria-current="page"], #main [aria-current="page"]')].map((el) => ({ nav: el.closest("nav")?.getAttribute("aria-label") ?? null, text: (el.getAttribute("aria-label") ?? el.textContent ?? "").trim().slice(0, 30) })),
    )
    const outside = marks.filter((m) => m.nav !== "主要")
    if (outside.length) throw new Error(`aria-current outside the nav on ${path}: ${outside.map((m) => m.text).join(" | ")}`)
    if (marks.length !== 1 || marks[0].text !== "帳本") throw new Error(`nav should mark 帳本 on ${path}: ${JSON.stringify(marks)}`)
  }
})
await check("數字鍵 1–4 切換帳本分段（aria-keyshortcuts）；在輸入框裡打數字不會切換", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("tab", { name: /交易/ }).waitFor({ timeout: 8000 })
  if ((await page.getByRole("tab", { name: /交易/ }).getAttribute("aria-keyshortcuts")) !== "2") throw new Error("missing aria-keyshortcuts")
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
  await page.keyboard.press("2")
  await page.waitForURL(/view=transactions/)
  await page.keyboard.press("4")
  await page.waitForURL(/view=performance/)
  const box = page.getByLabel("提出問題或下指令")
  await box.click()
  await page.keyboard.type("13")
  await page.waitForTimeout(200)
  if (!/view=performance/.test(page.url())) throw new Error("typing digits in the composer switched the segment")
  await box.fill("")
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
  await page.keyboard.press("1")
  await page.waitForURL((u) => !u.search.includes("view="))
})

await check("頭像選單切換深色", async () => {
  await page.getByRole("button", { name: /帳號選單/ }).click()
  await page.getByRole("menuitemradio", { name: /深色/ }).click()
  await page.waitForFunction(() => document.documentElement.classList.contains("dark"))
})

// ── 第二批（2026-11-12）────────────────────────────────────────
await check("商用模式：帳本、個股、績效都沒有「示範資料」標記", async () => {
  await page.evaluate(() => document.documentElement.classList.remove("dark"))
  for (const path of ["/", "/stock/2330.TW", "/?view=performance"]) {
    await page.goto(base + path, { waitUntil: "networkidle" })
    await page.waitForTimeout(400)
    if (await page.getByText("示範資料", { exact: true }).count()) throw new Error(`示範資料 on ${path}`)
  }
})
await check("績效：含美股算不出來（只留帳戶選單、原因說一次、一個動作）→ 只看台幣帳戶就有區間、基準、績效與「資料累積中」", async () => {
  // 算不出來、換區間或基準也沒有用：不放那兩個控制項，只留帳戶；原因在這一頁只說一次，沒有夾在兩條線中間的空白
  await page.getByText("績效還算不出來").waitFor({ timeout: 8000 })
  if (await page.getByRole("radiogroup", { name: "績效區間" }).count()) throw new Error("range chips shown while nothing can be computed")
  if (await page.getByRole("combobox", { name: "績效比較基準" }).count()) throw new Error("benchmark select shown while nothing can be computed")
  await page.getByRole("combobox", { name: "帳戶" }).waitFor()
  const reasons = await page.locator("main").getByText(/美股/).count()
  if (reasons !== 1) throw new Error(`the reason should appear once, got ${reasons}`)
  await page.getByRole("button", { name: /^只看「/ }).first().waitFor({ timeout: 8000 })
  if ((await page.getByRole("button", { name: /^只看「/ }).count()) !== 1) throw new Error("the empty state should offer exactly one action")
  await page.getByRole("button", { name: /只看「永豐/ }).click()
  await page.getByText("最大回撤").first().waitFor({ timeout: 8000 })
  await page.getByText(/資料累積中：自 .* 起存檔/).first().waitFor()
  await page.getByRole("radiogroup", { name: "績效區間" }).waitFor()
  await page.getByRole("combobox", { name: "績效比較基準" }).waitFor()
})
await check("扣款日：AI 面板提出定期定額草稿，簽名入帳後不再提出", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  // 前面的股利草稿還在等簽名時，面板會停在那段對話：開新對話回到建議
  await page.getByRole("button", { name: "新對話" }).click()
  await page.getByRole("button", { name: /記下今天的 00878 定期定額/ }).click()
  await page.getByRole("heading", { name: /買進 國泰永續高股息/ }).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "簽名：確認入帳" }).click()
  await page.getByText(/已入帳：買進 國泰永續高股息/).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "新對話" }).click()
  await page.waitForTimeout(1000)
  if (await page.getByRole("button", { name: /記下今天的 00878 定期定額/ }).count()) throw new Error("still offered after signing")
})
await check("補記：11/06 的 0050 扣款沒有記 → 草稿成交日 11/6 → 簽名入帳後不再提出", async () => {
  await page.getByRole("button", { name: "補記 11/06 的 0050 定期定額" }).click()
  await page.getByRole("heading", { name: /買進 元大台灣50/ }).waitFor({ timeout: 8000 })
  await page.getByText(/成交日 11\/6/).last().waitFor()
  await page.getByText(/11\/6 是元大台灣50定期定額的扣款日/).waitFor()
  // 扣款日已經過去：用那天（11/6）的收盤價，不是最近收盤價
  await page.getByText(/我先照那天的收盤價算好股數/).waitFor()
  await page.getByText(/以 11\/6 收盤價/).last().waitFor()
  await page.getByRole("button", { name: "簽名：確認入帳" }).click()
  await page.getByText(/已入帳：買進 元大台灣50/).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "新對話" }).click()
  await page.waitForTimeout(1000)
  if (await page.getByRole("button", { name: /補記 11\/06 的 0050/ }).count()) throw new Error("still offered after signing")
})
await check("上市股票的籌碼：三大法人是空狀態、外資持股只有前 20 名，AI 面板與空狀態都能問外資動向；上櫃照常", async () => {
  await page.goto(base + "/stock/2330.TW?tab=chips", { waitUntil: "networkidle" })
  await page.getByText("上市股票不顯示逐檔三大法人").waitFor({ timeout: 8000 })
  await page.getByText(/證交所只公布外資持股比率前 20 名，台積電目前不在名單上/).waitFor()
  if (await page.getByText("資料不足。").count()) throw new Error("foreign holding should explain, not say 資料不足")
  const asks = page.getByRole("button", { name: "最近外資對這檔的動向？" })
  if ((await asks.count()) !== 2) throw new Error(`expected the panel chip and the empty-state button, got ${await asks.count()}`)
  await page.locator("main").getByRole("button", { name: "最近外資對這檔的動向？" }).click()
  await page.getByText(/逐檔三大法人買賣超與外資持股比，證交所以付費商品提供/).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "新對話" }).click()
  await page.goto(base + "/stock/6488.TWO?tab=chips", { waitUntil: "networkidle" })
  await page.getByRole("heading", { name: "三大法人買賣超" }).waitFor({ timeout: 8000 })
  if (await page.getByRole("button", { name: "最近外資對這檔的動向？" }).count()) throw new Error("TPEx stocks have the data on the page")
  await page.goto(base + "/", { waitUntil: "networkidle" })
})
await check("已出清：依年份分組（新的在前、最近一年展開、有小計），展開 2025 點長榮到「過去的持有」", async () => {
  await page.getByRole("button", { name: /^已出清/ }).click()
  const table = page.getByRole("table", { name: "已出清" })
  const years = await table.getByRole("button", { name: /^\d{4} 年/ }).allTextContents()
  if (years.map((y) => y.slice(0, 4)).join(",") !== "2026,2025,2024") throw new Error(`years ${years.join("|")}`)
  await table.getByText("中華電").waitFor()
  if (await table.getByText("長榮").count()) throw new Error("2025 should start collapsed")
  await table.getByText(/小計/).first().waitFor()
  await table.getByRole("button", { name: /^2025 年/ }).click()
  await table.getByText("長榮").click()
  await page.getByRole("heading", { name: "過去的持有" }).waitFor({ timeout: 8000 })
})
await check("持倉：有定期定額的股票有標記，按下到設定的那個計畫", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  const mark = page.getByRole("table", { name: "持倉" }).getByRole("link", { name: /定期定額：每月 6 日 NT\$10,000/ })
  await mark.hover()
  await page.locator('[data-slot="tooltip-content"]').getByText("定期定額：每月 6 日 NT$10,000").waitFor({ timeout: 5000 })
  await page.getByRole("table", { name: "持倉" }).getByRole("link", { name: /定期定額：每月 12、26 日/ }).waitFor()
  if (await page.getByRole("table", { name: "持倉" }).getByRole("link", { name: /定期定額/ }).count() !== 2) throw new Error("expected 2 markers")
  await mark.click()
  await page.waitForURL(/\/settings#plan-rcp_demo0050/)
  await page.locator('#plan-rcp_demo0050[aria-current="true"]').waitFor({ timeout: 8000 })
})
await check("隱私模式：定期定額標記不露出金額", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "隱私模式：遮蔽金額" }).click()
  await page.getByRole("table", { name: "持倉" }).getByRole("link", { name: "定期定額：每月 6 日 ••••（到設定查看）" }).waitFor()
  await page.getByRole("button", { name: /隱私模式開啟中/ }).click()
})
await check("法人觀點：預設收合；2330 展開就有 3 筆（日期・機構・評等・目標價・來源）與免責", async () => {
  await page.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  const toggle = page.getByRole("button", { name: /法人觀點/ })
  if ((await toggle.getAttribute("aria-expanded")) !== "false") throw new Error("should start collapsed")
  await toggle.click()
  const table = page.getByRole("table", { name: "法人觀點" })
  await table.getByText("外資券商 A", { exact: true }).waitFor({ timeout: 8000 })
  if ((await table.locator("tbody tr").count()) !== 3) throw new Error("expected 3 rows")
  await table.getByText("1,350 元").waitFor()
  await page.getByText("非 Forliosa 建議").first().waitFor()
  for (const banned of ["平均", "上漲空間", "建議買進"]) if (await page.locator("#ov-analyst-body").getByText(banned).count()) throw new Error(`found ${banned}`)
})
await check("法人觀點：2454 沒人查過 → 查詢 → 搜尋中（AI 的話）→ 1–2 筆", async () => {
  await page.goto(base + "/stock/2454.TW", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: /法人觀點/ }).click()
  await page.getByRole("button", { name: "查詢近期法人觀點" }).click()
  await page.getByText(/正在找近期媒體報導的法人觀點/).waitFor({ timeout: 5000 })
  const rows = page.getByRole("table", { name: "法人觀點" }).locator("tbody tr")
  await rows.first().waitFor({ timeout: 15000 })
  const n = await rows.count()
  if (n < 1 || n > 2) throw new Error(`rows ${n}`)
})
await check("法人觀點：2881 查完沒有報導、2409 查不到、ETF 沒有這一塊", async () => {
  await page.goto(base + "/stock/2881.TW", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: /法人觀點/ }).click()
  await page.getByRole("button", { name: "查詢近期法人觀點" }).click()
  await page.getByText("近期查無法人報導").first().waitFor({ timeout: 15000 })
  await page.goto(base + "/stock/2409.TW", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: /法人觀點/ }).click()
  await page.getByRole("button", { name: "查詢近期法人觀點" }).click()
  await page.getByText("法人觀點暫時查不到，稍後再打開看看。").waitFor({ timeout: 15000 })
  await page.goto(base + "/stock/0050.TW", { waitUntil: "networkidle" })
  // ETF 的鍵值帶只列 ETF 有的欄位（沒有近四季 EPS）：等總覽的第三層（法人觀點也在這一層）出現再判斷
  await page.getByRole("region", { name: "關鍵數據" }).getByText(/^淨值（/).first().waitFor({ timeout: 8000 })
  await page.getByRole("region", { name: "新聞報導" }).waitFor({ timeout: 8000 })
  if (await page.getByRole("region", { name: "關鍵數據" }).getByText("近四季 EPS").count()) throw new Error("ETF key band lists EPS")
  if (await page.getByRole("button", { name: /法人觀點/ }).count()) throw new Error("ETF should not have 法人觀點")
})
await check("個股：1 日走勢說明需要授權，按「看 5 日走勢」切換", async () => {
  await page.goto(base + "/stock/0050.TW", { waitUntil: "networkidle" })
  await page.getByRole("radio", { name: "1日" }).click()
  await page.getByText("盤中走勢需要授權行情，目前提供收盤後資料").waitFor()
  await page.getByRole("button", { name: "看 5 日走勢" }).click()
  await page.getByRole("radio", { name: "5日", checked: true }).waitFor()
})
await check("個股總覽：「新聞報導」（媒體原標題＋媒體＋時間，連到原文；先 3 則、看更多）與「事件」裡的官方公告分開；GDELT 在頁尾", async () => {
  await page.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  // 官方公告（重大訊息、證交所公告）併進「事件」表：連到官方原文、另開新視窗；不混進媒體的標題
  const events = page.getByRole("region", { name: "事件" })
  const official = events.getByRole("link", { name: /（在(公開資訊觀測站|證交所)查看，另開新視窗）/ })
  await official.first().waitFor({ timeout: 8000 })
  if ((await official.count()) !== 3) throw new Error(`expected 3 official announcements, got ${await official.count()}`)
  for (const link of await official.all()) {
    if ((await link.getAttribute("target")) !== "_blank") throw new Error("official link must open a new tab")
    if (!/^https:\/\/(mops\.twse|www\.twse)\.com\.tw\//.test((await link.getAttribute("href")) ?? "")) throw new Error(`official link is not an official host: ${await link.getAttribute("href")}`)
  }
  if (await events.locator('a[href*="demo-news"]').count()) throw new Error("media headline in 事件")
  // 新聞報導：媒體原標題＋媒體＋時間，連到原文（另開新視窗、noopener）；不放圖片；先 3 則，「看更多」再加
  const news = page.getByRole("region", { name: "新聞報導" })
  await news.waitFor()
  const headlines = news.getByRole("listitem").getByRole("link")
  if ((await headlines.count()) !== 3) throw new Error(`expected 3 headlines, got ${await headlines.count()}`)
  const rel = await headlines.first().getAttribute("rel")
  if ((await headlines.first().getAttribute("target")) !== "_blank" || !rel?.includes("noopener")) throw new Error(`link attrs ${rel}`)
  await news.getByRole("listitem").first().getByText("示範財經日報", { exact: true }).waitFor()
  await news.getByRole("listitem").first().locator("time").getByText("1 小時前").waitFor()
  if (await news.locator("img").count()) throw new Error("news must not show images")
  if (await news.locator('a[href*="mops.twse.com.tw"], a[href*="www.twse.com.tw"]').count()) throw new Error("official announcement in 新聞報導")
  await news.getByRole("button", { name: "看更多" }).click()
  if ((await headlines.count()) <= 3) throw new Error("看更多 did not add headlines")
  // GDELT 的使用條款要求引用並連回 gdeltproject.org：在頁尾的「資料來源與授權」
  await page.getByRole("button", { name: "資料來源與授權" }).click()
  const gdelt = page.locator("footer").getByRole("link", { name: /The GDELT Project/ })
  await gdelt.waitFor()
  if ((await gdelt.getAttribute("href")) !== "https://www.gdeltproject.org/") throw new Error(`GDELT link ${await gdelt.getAttribute("href")}`)
  await page.goto(base + "/stock/2317.TW", { waitUntil: "networkidle" })
  await page.getByText(/最近沒有找到鴻海的媒體報導/).waitFor()
})
await check("上市股票名列外資持股前 20 名：日月光投控顯示外資持股比、名次與說明（籌碼分頁與總覽）", async () => {
  await page.goto(base + "/stock/3711.TW?tab=chips", { waitUntil: "networkidle" })
  const foreign = page.getByRole("region", { name: "外資持股比" })
  await foreign.getByText(/名列證交所外資及陸資持股前 20 名第 12 名/).waitFor({ timeout: 8000 })
  if (!(await foreign.getByText("75.52%・前 20 名第 12 名").count())) throw new Error("top-20 rank missing in the header")
  // 總覽：籌碼併進鍵值帶——「外資持股」一格（滑過有名次），格子下面一行寫明是前 20 名資料與名次
  await page.goto(base + "/stock/3711.TW", { waitUntil: "networkidle" })
  const band = page.getByRole("region", { name: "關鍵數據" })
  await band.getByText(/外資持股是證交所前 20 名資料（第 12 名）/).waitFor({ timeout: 8000 })
  const cell = band.locator("dl > div").filter({ has: page.getByRole("term").getByText("外資持股", { exact: true }) })
  await cell.getByRole("definition").getByText("75.5%", { exact: true }).waitFor()
  if ((await cell.getAttribute("title")) !== "證交所外資持股前 20 名第 12 名") throw new Error(`rank title ${await cell.getAttribute("title")}`)
})
await check("個股總覽：「相關股票」4 格連到個股頁（基準不寫持有本股）；「關於「台積電」」有維基百科節錄、官方資料、董事長與總經理", async () => {
  await page.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  const related = page.getByRole("region", { name: "相關股票" })
  await related.waitFor({ timeout: 8000 })
  const cells = related.getByRole("listitem")
  if ((await cells.count()) !== 4) throw new Error(`expected 4 related cells, got ${await cells.count()}`)
  if ((await cells.first().getByRole("link").getAttribute("href")) !== "/stock/0050.TW") throw new Error("benchmark cell link")
  if (await related.getByText(/持有本股/).count()) throw new Error("benchmark must not claim holdings")
  const about = page.getByRole("region", { name: "關於「台積電」" })
  await about.getByText("節錄", { exact: true }).waitFor()
  await about.getByRole("link", { name: /維基百科「台積電」條目/ }).waitFor()
  await about.getByRole("link", { name: /CC BY-SA 4.0/ }).waitFor()
  await about.getByText("總裁: 魏哲家").waitFor()
  await about.getByText(/資料日期：2026\/11\/11/).waitFor()
  await cells.nth(1).getByRole("link").click()
  await page.getByRole("heading", { name: /創意/ }).first().waitFor({ timeout: 8000 })
  await page.goto(base + "/stock/AAPL", { waitUntil: "networkidle" })
  await page.getByRole("region", { name: "新聞報導" }).waitFor({ timeout: 8000 })
  if (await page.getByRole("region", { name: "相關股票" }).count()) throw new Error("US stocks have no related row")
})
await check("ETF 淨值與折溢價：0050 同一天、有走勢與逐日數字；00679B 淨值晚一天寫出兩個日期；00878 資料累積中；估值分頁同一塊；股票沒有", async () => {
  // 總覽：淨值與折溢價在鍵值格裡（同一天 11/12），格子下面接「折溢價走勢」（走勢、追蹤誤差說明、逐日數字）
  await page.goto(base + "/stock/0050.TW", { waitUntil: "networkidle" })
  const band = page.getByRole("region", { name: "關鍵數據" })
  await band.getByRole("term").getByText("淨值（11/12）", { exact: true }).waitFor({ timeout: 8000 })
  const premium = band.locator("dl > div").filter({ has: page.getByRole("term").getByText("折溢價（11/12）", { exact: true }) })
  await premium.getByRole("definition").getByText(/^(溢價|折價) \d\.\d\d%$/).waitFor()
  const trend = band.getByRole("region", { name: "折溢價走勢" })
  await trend.getByRole("img", { name: /^60 個有資料的交易日（\d+\/\d+–11\/12）的折溢價/ }).waitFor()
  if (await trend.getByText(/最新的淨值是/).count()) throw new Error("0050 NAV and close are the same day")
  await trend.getByText("追蹤誤差不提供：標的指數的每日資料沒有開放授權。").waitFor()
  await trend.getByText(/逐日數字（60 天）/).click()
  await trend.getByRole("table").getByRole("rowheader", { name: "11/12" }).waitFor()
  if (await band.getByText(/[▲▼]/).count()) throw new Error("premium must not use price arrows")
  // 淨值的來源（金管會證期局）登記到頁尾的「資料來源與授權」
  await page.getByRole("button", { name: "資料來源與授權" }).click()
  await page.locator("footer").getByText(/金融監督管理委員會證券期貨局〈證券投資信託基金每日淨值〉/).waitFor()
  await page.goto(base + "/stock/00679B.TWO", { waitUntil: "networkidle" })
  const bond = page.getByRole("region", { name: "折溢價走勢" })
  await bond.getByText(/最新的淨值是 11\/11、收盤是 11\/12；折溢價用兩者都有的 11\/11 計算/).waitFor({ timeout: 8000 })
  await page.goto(base + "/stock/00878.TW", { waitUntil: "networkidle" })
  await page.getByRole("region", { name: "折溢價走勢" }).getByText("資料累積中：淨值自 2026-11-03 起存檔").waitFor({ timeout: 8000 })
  await page.goto(base + "/stock/0050.TW?tab=valuation", { waitUntil: "networkidle" })
  await page.getByRole("region", { name: "淨值與折溢價" }).getByText("淨值（11/12）").waitFor({ timeout: 8000 })
  await page.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  await page.getByText("參考價").first().waitFor({ timeout: 8000 })
  await page.getByRole("region", { name: "關鍵數據" }).getByText("近四季 EPS").waitFor({ timeout: 8000 })
  if (await page.getByRole("region", { name: /淨值與折溢價|折溢價走勢/ }).count()) throw new Error("stocks have no NAV section")
})
await check("個股（第二輪）：美股沒有報價只在價格那一格說一次、沒有走勢圖與殖利率；麵包屑不寫英文產業；術語說明收在「怎麼看」；報價小數位依升降單位；空狀態不用虛線", async () => {
  await page.goto(base + "/stock/AAPL", { waitUntil: "networkidle" })
  await page.getByRole("heading", { level: 1, name: "Apple" }).waitFor({ timeout: 8000 })
  await page.getByText("沒有報價", { exact: true }).waitFor({ timeout: 8000 })
  await page.getByRole("region", { name: "關於「Apple」" }).waitFor({ timeout: 8000 })
  const main = page.locator("main")
  const said = await main.evaluate((el) => (el.textContent.match(/沒有可商用的(報價|行情)來源/g) ?? []).length)
  if (said !== 1) throw new Error(`the no-quote reason should appear once on the overview, got ${said}`)
  if (await page.getByRole("region", { name: "走勢圖" }).count()) throw new Error("no price chart without a quote")
  const crumb = await page.getByRole("navigation", { name: "位置" }).textContent()
  if (/Consumer Electronics|[A-Za-z]{4,} [A-Za-z]{4,}/.test(crumb.replace("AAPL", ""))) throw new Error(`breadcrumb shows an English industry: ${crumb}`)
  const position = await page.getByRole("region", { name: /的部位$/ }).textContent()
  if (!/US\$143\.41/.test(position) || /未實現/.test(position)) throw new Error(`US position: cost in US$, no unrealized without a quote: ${position}`)
  await page.goto(base + "/stock/AAPL?tab=valuation", { waitUntil: "networkidle" })
  await page.getByText("沒有報價，算不出估值").waitFor({ timeout: 8000 })
  if (await page.getByRole("region", { name: "殖利率走勢" }).count()) throw new Error("yield trend is price-derived")
  const again = await main.evaluate((el) => (el.textContent.match(/沒有可商用的(報價|行情)來源/g) ?? []).length)
  if (again !== 1) throw new Error(`the no-quote reason should appear once on valuation, got ${again}`)
  // 估值：「每條帶是…」「近 12 個月現金股利 ÷ 收盤價」預設收著，按「怎麼看」才出現
  await page.goto(base + "/stock/2330.TW?tab=valuation", { waitUntil: "networkidle" })
  const river = page.getByRole("region", { name: "本益比河流圖" })
  await river.waitFor({ timeout: 8000 })
  if (await river.getByText(/每條帶是/).isVisible()) throw new Error("river explainer should start collapsed")
  if (await page.getByText(/近 12 個月現金股利 ÷ 收盤價/).isVisible()) throw new Error("yield explainer should start collapsed")
  const howTo = river.getByRole("button", { name: /^怎麼看/ })
  if ((await howTo.getAttribute("aria-expanded")) !== "false") throw new Error("怎麼看 should be collapsed")
  await howTo.click()
  await river.getByText(/每條帶是/).waitFor()
  if ((await howTo.getAttribute("aria-expanded")) !== "true") throw new Error("怎麼看 should expand")
  // 河流圖的倍數價、近四季 EPS 和總覽同一個寫法（52.30 元），倍數價依升降單位（837，不是 836.8）
  const now = page.getByRole("region", { name: "現在的本益比" })
  await now.getByText(/^\d+\.\d\d 元$/).first().waitFor()
  if (await now.getByText(/NT\$\d/).count()) throw new Error("per-share amounts use 元, not NT$")
  // 相關股票：台股價格依升降單位，不會是 214.00 這種補零
  await page.goto(base + "/stock/6488.TWO", { waitUntil: "networkidle" })
  const related = page.getByRole("region", { name: "相關股票" })
  await related.waitFor({ timeout: 8000 })
  const prices = await related.locator(".num").allTextContents()
  const padded = prices.filter((t) => /^\d[\d,]*\.00$/.test(t.trim()) && Number(t.replace(/,/g, "")) >= 50)
  if (padded.length) throw new Error(`stock prices padded with .00: ${padded.join(", ")}`)
  // 空狀態一種樣子：個股頁沒有虛線（虛線只給 AI 草稿）
  for (const path of ["/stock/AAPL?tab=valuation", "/stock/0050.TW?tab=valuation", "/stock/2330.TW?tab=chips", "/stock/0050.TW"]) {
    await page.goto(base + path, { waitUntil: "networkidle" })
    await page.locator("#stock-tabpanel").waitFor({ timeout: 8000 })
    await page.waitForTimeout(300)
    const dashed = await page.locator("main").evaluate((el) =>
      [...el.querySelectorAll("*")].filter((n) => ["borderTopStyle", "borderBottomStyle", "borderLeftStyle"].some((k) => getComputedStyle(n)[k] === "dashed")).length,
    )
    if (dashed) throw new Error(`${path}: ${dashed} dashed borders outside AI drafts`)
  }
})
await check("設定：新增定期定額（驗證 → 儲存）、暫停、修改、刪除（確認）", async () => {
  await page.goto(base + "/settings#recurring", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "新增定期定額" }).click()
  await page.getByRole("button", { name: "新增計畫" }).click()
  await page.getByText("至少選一個扣款日").waitFor()
  await page.getByRole("dialog").getByLabel("股票或 ETF").fill("0056")
  await page.getByRole("option", { name: /0056/ }).click()
  await page.getByLabel("每次扣款（新台幣）").fill("3000")
  await page.getByRole("button", { name: "5 日", exact: true }).click()
  await page.getByRole("button", { name: "20 日", exact: true }).click()
  await page.getByRole("button", { name: "新增計畫" }).click()
  await page.getByText("每月 5、20 日・NT$3,000").waitFor({ timeout: 8000 })
  await page.getByRole("switch", { name: /暫停「元大高股息」/ }).click()
  await page.getByText("已暫停").first().waitFor()
  await page.getByRole("button", { name: "修改「元大高股息」定期定額" }).click()
  // 表單帶入原本的商品是非同步的：還沒帶入就按儲存會停在「請選擇台股或 ETF」（機器忙時偶爾發生）
  await page.getByRole("dialog").getByText("元大高股息").waitFor({ timeout: 8000 })
  await page.getByLabel("每次扣款（新台幣）").fill("5000")
  await page.getByRole("button", { name: "儲存" }).click()
  await page.getByText("每月 5、20 日・NT$5,000").waitFor()
  await page.getByRole("button", { name: "刪除「元大高股息」定期定額" }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: "刪除計畫" }).click()
  await page.getByText(/已刪除「元大高股息」/).waitFor()
})
await check("頭像選單：資料來源與授權（完整顯名聲明）", async () => {
  await page.getByRole("button", { name: /帳號選單/ }).click()
  await page.getByRole("menuitem", { name: "資料來源與授權" }).click()
  await page.getByText("臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版").waitFor()
})
await check("紀錄：對話保留 30 天", async () => {
  await page.goto(base + "/history", { waitUntil: "networkidle" })
  await page.getByText("對話紀錄保留 30 天。").first().waitFor()
})
await check("紀錄：刪除對話有「復原」（Sonner 通知），復原後對話回到清單", async () => {
  const main = page.locator("main")
  const name = "刪除對話「00878 下次除息能領多少？」"
  await main.getByRole("button", { name }).click()
  await page.getByText("已刪除對話").first().waitFor({ timeout: 5000 })
  if (await main.getByRole("button", { name }).count()) throw new Error("thread still listed after delete")
  await page.getByRole("button", { name: "復原" }).click()
  await main.getByRole("button", { name }).waitFor({ timeout: 5000 })
  if (await main.getByText("AI 任務").count()) throw new Error("demo AI tasks must not show")
})
await check("AI 面板：設定頁沒有建議 → 輸入框上方列最近 3 段對話、提示字不是交易例子；開始對話後輸入框不跳，免責只出現一次", async () => {
  await page.goto(base + "/settings", { waitUntil: "networkidle" })
  const panel = page.getByRole("complementary", { name: "問 AI" })
  const box = panel.getByLabel("提出問題或下指令")
  const placeholder = (await box.getAttribute("placeholder")) ?? ""
  if (/買|張/.test(placeholder)) throw new Error(`settings placeholder suggests a trade: ${placeholder}`)
  const recent = panel.getByRole("list", { name: "最近的對話" })
  if ((await recent.getByRole("listitem").count()) !== 3) throw new Error(`expected 3 recent threads, got ${await recent.getByRole("listitem").count()}`)
  // 按下最近的一段對話 → 接著那段對話（使用者的話出現在面板裡）；輸入框的位置不變
  const before = (await box.boundingBox()).y
  const first = recent.getByRole("button").first()
  const title = ((await first.textContent()) ?? "").trim()
  await first.click()
  await panel.locator("p", { hasText: title }).first().waitFor({ timeout: 8000 })
  if (await panel.getByRole("list", { name: "最近的對話" }).count()) throw new Error("still on the panel home after opening a thread")
  const after = (await box.boundingBox()).y
  if (Math.abs(after - before) > 1) throw new Error(`composer moved ${before} → ${after}`)
  // 同一段對話再問一題：免責只在最新一則回答下方出現一次
  await box.fill("持股會不會太集中")
  await box.press("Enter")
  await panel.getByText(/這題要查資料並附來源/).last().waitFor({ timeout: 8000 })
  await page.waitForTimeout(300)
  const disclaimers = await panel.getByText("AI 回答僅供參考，非投資建議。").count()
  if (disclaimers !== 1) throw new Error(`expected one disclaimer per conversation, got ${disclaimers}`)
  await panel.getByRole("button", { name: "新對話" }).click()
})
await check("美股：不問河流圖、提示字用「股」；自由提問也照實說（均價寫 US$，沒有「—」，不連到空的估值）", async () => {
  await page.goto(base + "/stock/AAPL", { waitUntil: "networkidle" })
  await page.getByText("關於「Apple」").first().waitFor({ timeout: 8000 })
  const panel = page.getByRole("complementary", { name: "問 AI" })
  const box = panel.getByLabel("提出問題或下指令")
  const placeholder = (await box.getAttribute("placeholder")) ?? ""
  if (!placeholder.includes("買 AAPL 10 股")) throw new Error(`AAPL placeholder ${placeholder}`)
  if (await panel.getByRole("button", { name: "我的成本在河流圖哪裡？" }).count()) throw new Error("river question offered for a US stock")
  await box.fill("我的成本在河流圖哪裡？")
  await box.press("Enter")
  await panel.getByText(/你的均價 US\$[\d,.]+。美股目前沒有可商用的行情來源/).waitFor({ timeout: 8000 })
  if (await panel.getByText(/\d 元，用近四季|現在是 — 倍/).count()) throw new Error("US cost shown in 元 or with a dash")
  if (await panel.getByRole("link", { name: /看河流圖/ }).count()) throw new Error("links to an empty river chart")
  await panel.getByRole("button", { name: "新對話" }).click()
})

// ── 第四批：股利自動入帳 ─────────────────────────────────────
await check("股利頁：台股股利標「自動」（滑過說明除息日自動入帳），美股股利沒有", async () => {
  await page.goto(base + "/?view=dividends", { waitUntil: "networkidle" })
  // 頁面上那行說明拿掉了：改看每一列——自動入帳的都是台股、標籤滑過有說明；美股股利（要自己記）一筆都沒有「自動」
  const received = page.getByRole("region", { name: "已入帳" })
  await received.getByRole("listitem").first().waitFor({ timeout: 8000 })
  const tags = received.getByText("自動", { exact: true })
  if ((await tags.count()) !== 3) throw new Error(`expected 3 自動 tags, got ${await tags.count()}`)
  for (const tag of await tags.all()) {
    if (!(await tag.getAttribute("title"))?.includes("除息日")) throw new Error(`自動 tag without explanation: ${await tag.getAttribute("title")}`)
  }
  const rows = received.getByRole("listitem")
  const auto = rows.filter({ has: page.getByText("自動", { exact: true }) })
  for (const href of await auto.getByRole("link").evaluateAll((els) => els.map((a) => a.getAttribute("href")))) {
    if (!/\.TWO?$/.test(href ?? "")) throw new Error(`自動 on a non-Taiwan dividend ${href}`)
  }
  const us = rows.filter({ has: page.locator('a[href="/stock/AAPL"], a[href="/stock/VOO"], a[href="/stock/NVDA"]') })
  if ((await us.count()) === 0) throw new Error("expected US dividends in the list")
  if (await us.getByText(/^自動/).count()) throw new Error("US dividends must not be automatic")
})
await check("交易：編輯自動入帳的股利（說明）→ 儲存後「自動・已修改」；刪除自動那筆（確認框說明）後不再出現", async () => {
  await page.goto(base + "/?view=transactions", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: /^編輯 10\/8.*2454（自動）$/ }).click()
  await page.getByText(/儲存變更後就是你自己的版本/).waitFor({ timeout: 8000 })
  await page.getByRole("dialog").getByText("聯發科").waitFor({ timeout: 8000 })
  await page.locator("#trade-note").fill("零股")
  await page.getByRole("button", { name: "儲存變更" }).click()
  await page.getByRole("button", { name: /^編輯 10\/8.*2454（自動・已修改）$/ }).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "刪除 9/22（二） 的現金股利" }).click()
  const dialog = page.getByRole("alertdialog")
  await dialog.getByText(/這筆股利之後也不會再自動入帳/).waitFor()
  await dialog.getByRole("button", { name: "刪除" }).click()
  await page.getByText("已刪除這筆交易").waitFor({ timeout: 8000 })
  await page.waitForTimeout(500)
  if (await page.getByRole("button", { name: /6488（自動）$/ }).count()) throw new Error("deleted automatic dividend came back")
})

// ── M5 分享：群組、邀請、授權查看 ─────────────────────────────
await check("群組：建立群組 → 產生邀請連結（只顯示一次）", async () => {
  await page.goto(base + "/groups", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "建立群組" }).first().click()
  await page.getByLabel("群組名稱").fill("冒煙測試群")
  await page.getByRole("dialog").getByRole("button", { name: "建立群組" }).click()
  await page.getByRole("heading", { name: "冒煙測試群", exact: true }).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "產生邀請連結" }).click()
  const url = await page.getByRole("textbox", { name: "邀請連結" }).inputValue()
  if (!/\/invite\//.test(url)) throw new Error(`unexpected invite url ${url}`)
  await page.getByText("可以多人使用").or(page.getByText("單次使用")).first().waitFor()
})
await check("排行：沒開報酬率的人不出現、沒有「未分享」；本月顯示期間起點", async () => {
  await page.goto(base + "/groups/grp_family", { waitUntil: "networkidle" })
  const table = page.getByRole("table", { name: "今日排行" })
  await table.getByText("爸爸").waitFor({ timeout: 8000 })
  if (await table.getByText("阿弟").count()) throw new Error("member without returns shown")
  if ((await page.content()).includes("未分享")) throw new Error("未分享 rendered")
  await page.getByRole("radio", { name: "本月" }).click()
  await page.getByText(/10\/30 收盤/).first().waitFor({ timeout: 8000 })
})
await check("排行：名次依期間報酬排——那一欄是主數字、表頭有 aria-sort 與箭頭；總報酬是一般字級；自己的那一列用字標示、沒有底色", async () => {
  await page.goto(base + "/groups/grp_family", { waitUntil: "networkidle" })
  const table = page.getByRole("table", { name: "今日排行" })
  await table.getByText("爸爸").waitFor({ timeout: 8000 })
  const head = table.getByRole("columnheader", { name: "今日報酬" })
  if ((await head.getAttribute("aria-sort")) !== "descending") throw new Error("period column has no aria-sort")
  if (!(await head.locator("svg").count())) throw new Error("no sort arrow in the period column head")
  if ((await table.getByRole("columnheader", { name: "總報酬（含股利）" }).getAttribute("aria-sort")) !== null) throw new Error("total column claims to be sorted")
  const look = await table.getByRole("row").filter({ hasText: "爸爸" }).evaluate((tr) => {
    const cells = [...tr.querySelectorAll("td")]
    const style = (el) => { const c = getComputedStyle(el); return { size: parseFloat(c.fontSize), weight: Number(c.fontWeight), text: el.textContent } }
    return { period: style(cells.at(-2)), total: style(cells.at(-1)) }
  })
  if (!(look.period.size > look.total.size && look.period.weight >= 600 && look.total.weight <= 400)) throw new Error(`period is not the emphasised figure: ${JSON.stringify(look)}`)
  if (!/[▲▼]/.test(look.period.text) || !/[▲▼]/.test(look.total.text)) throw new Error("▲▼ missing on a return column")
  const me = await table.getByRole("row").filter({ hasText: "（你）" }).evaluate((tr) => ({
    bg: getComputedStyle(tr).backgroundColor,
    weight: Number(getComputedStyle(tr.querySelector("a span span")).fontWeight),
  }))
  if (me.bg !== "rgba(0, 0, 0, 0)") throw new Error(`my row is tinted (${me.bg}) — looks like a stuck hover`)
  if (me.weight < 700) throw new Error(`my name is not bold (${me.weight})`)
  // 換期間：排序的表頭跟著換
  await page.getByRole("radio", { name: "本月" }).click()
  const month = page.getByRole("table", { name: "本月排行" }).getByRole("columnheader", { name: "本月報酬" })
  await month.waitFor({ timeout: 8000 })
  if ((await month.getAttribute("aria-sort")) !== "descending") throw new Error("sorted head did not follow the period")
  // 不排名次的群組：沒有箭頭
  await page.goto(base + "/groups/grp_friends", { waitUntil: "networkidle" })
  const plain = page.getByRole("table", { name: "今日排行" }).getByRole("columnheader", { name: "今日報酬" })
  await plain.waitFor({ timeout: 8000 })
  if ((await plain.getAttribute("aria-sort")) !== null || (await plain.locator("svg").count())) throw new Error("unranked board shows a sort indicator")
})
await check("群組、設定、資料來源：空狀態沒有虛線；有字的按鈕沒有圖示；「撤回」是外框按鈕；分享卡說明不疊冒號；資料來源頁沒有副標", async () => {
  const noIcon = async (button) => {
    await button.first().waitFor({ timeout: 8000 })
    if (await button.first().locator("svg").count()) throw new Error(`decorative icon on「${(await button.first().textContent())?.trim()}」`)
  }
  const dashedIn = (root) =>
    root.evaluate((el) => [...el.querySelectorAll("*")].filter((n) => ["borderTopStyle", "borderBottomStyle", "borderLeftStyle"].some((k) => getComputedStyle(n)[k] === "dashed")).length)
  await page.goto(base + "/groups", { waitUntil: "networkidle" })
  await noIcon(page.getByRole("button", { name: "建立群組" }))
  await noIcon(page.getByRole("button", { name: "複製分享文字" }))
  // 分享卡的說明接在一句話後面，不是「本月：…：…」
  const note = (await page.getByText(/^本月算不出來。/).textContent()) ?? ""
  if (/^本月[：:]/.test(note) || !/。$/.test(note)) throw new Error(`share-card note: ${note}`)
  // 新群組：成員分頁的空邀請清單、週報的空狀態——上下實線、沒有外框與底色
  await page.getByRole("button", { name: "建立群組" }).first().click()
  await page.getByLabel("群組名稱").fill("空狀態測試群")
  await page.getByRole("dialog").getByRole("button", { name: "建立群組" }).click()
  await page.getByRole("heading", { name: "空狀態測試群", exact: true }).waitFor({ timeout: 8000 })
  const empty = page.getByText("沒有有效的邀請連結", { exact: true })
  await empty.waitFor({ timeout: 8000 })
  const box = await empty.evaluate((el) => {
    const c = getComputedStyle(el.parentElement)
    const t = getComputedStyle(el)
    return { top: `${c.borderTopWidth} ${c.borderTopStyle}`, bottom: `${c.borderBottomWidth} ${c.borderBottomStyle}`, left: c.borderLeftWidth, bg: c.backgroundColor, radius: c.borderRadius, size: t.fontSize, weight: t.fontWeight }
  })
  if (box.top !== "1px solid" || box.bottom !== "1px solid" || box.left !== "0px" || box.bg !== "rgba(0, 0, 0, 0)" || box.radius !== "0px") throw new Error(`empty state is not two solid rules: ${JSON.stringify(box)}`)
  if (box.size !== "15px" || Number(box.weight) < 600) throw new Error(`empty state title: ${JSON.stringify(box)}`)
  await noIcon(page.getByRole("button", { name: "產生邀請連結" }))
  await page.getByRole("button", { name: "產生邀請連結" }).click()
  const revoke = page.getByRole("list", { name: "有效的邀請" }).getByRole("button", { name: "撤回" })
  await revoke.waitFor({ timeout: 8000 })
  const edge = await revoke.evaluate((el) => { const c = getComputedStyle(el); return { w: c.borderTopWidth, style: c.borderTopStyle, color: c.borderTopColor } })
  if (edge.w !== "1px" || edge.style !== "solid" || /rgba\(0, 0, 0, 0\)|transparent/.test(edge.color)) throw new Error(`撤回 has no visible frame: ${JSON.stringify(edge)}`)
  await page.getByRole("tab", { name: "週報" }).click()
  await page.getByText("還沒有週報", { exact: true }).waitFor({ timeout: 8000 })
  for (const [path, ready] of [
    [null, "還沒有週報"],
    ["/groups/grp_family?tab=feed", "加入了群組"],
    ["/groups/grp_family?tab=holdings", "成員持股"],
    ["/groups/grp_family/members/usr_dad", "總損益"],
    ["/settings", "授權給你的人"],
    ["/data-sources", "上市個股日成交資訊"],
  ]) {
    if (path) await page.goto(base + path, { waitUntil: "networkidle" })
    await page.getByText(ready).first().waitFor({ timeout: 8000 })
    const dashed = await dashedIn(page.locator("main"))
    if (dashed) throw new Error(`${path ?? "new group digests"}: ${dashed} dashed borders outside AI drafts`)
  }
  // 資料來源頁：標題和「授權條款」之間沒有副標
  const subtitle = await page.getByRole("heading", { level: 1, name: "資料來源與授權" }).evaluate((h) => {
    const next = document.getElementById("ds-license")
    const between = [...document.querySelectorAll("main p")].filter((p) => h.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING && p.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING)
    return between.map((p) => p.textContent).join(" | ")
  })
  if (subtitle) throw new Error(`data-sources still has a subtitle: ${subtitle}`)
  await page.goto(base + "/settings", { waitUntil: "networkidle" })
  for (const name of ["新增帳戶", "新增定期定額", "授權給…"]) await noIcon(page.getByRole("button", { name, exact: true }))
  await page.goto(base + "/groups/grp_family?tab=feed", { waitUntil: "networkidle" })
  await noIcon(page.getByRole("button", { name: "加表情" }))
  await noIcon(page.getByRole("button", { name: /^留言/ }))
})
await check("排行的討論串：留言 → 出現 → 刪除", async () => {
  await page.goto(base + "/groups/grp_family", { waitUntil: "networkidle" })
  const thread = page.getByRole("region", { name: /的討論$/ })
  await thread.getByText("今天大家都紅的 🎉").waitFor({ timeout: 8000 })
  await thread.getByLabel("留言", { exact: true }).fill("冒煙測試留言")
  await thread.getByRole("button", { name: "送出" }).click()
  await thread.getByText("冒煙測試留言").waitFor({ timeout: 8000 })
  const row = thread.getByRole("listitem").filter({ hasText: "冒煙測試留言" })
  await row.getByRole("button", { name: "刪除這則留言" }).click()
  await row.getByRole("button", { name: "刪除", exact: true }).click()
  await page.getByText("已刪除留言").waitFor({ timeout: 8000 })
})
await check("動態：按表情（計數加一）；成交價只在對方開了才有；合併筆數", async () => {
  await page.goto(base + "/groups/grp_family?tab=feed", { waitUntil: "networkidle" })
  const dad = page.getByRole("listitem").filter({ hasText: /爸爸\s*買進\s*台積電/ }).first()
  await dad.getByText("成交價").waitFor({ timeout: 8000 })
  await dad.getByRole("button", { name: /^讚 2/ }).click()
  await dad.getByRole("button", { name: /^讚 3，你按過/ }).waitFor({ timeout: 8000 })
  await page.getByRole("listitem").filter({ hasText: /爸爸\s*買進\s*元大台灣50/ }).first().getByText(/2 筆/).waitFor()
  const sis = page.getByRole("listitem").filter({ hasText: /姊姊\s*買進\s*國泰永續高股息/ }).first()
  if (await sis.getByText("成交價").count()) throw new Error("price shown without trade_prices")
})
await check("我的分享：關掉交易動態 → 動態裡自己的買賣立刻消失；持股＋金額提示可推算股數", async () => {
  await page.goto(base + "/groups/grp_family?tab=share", { waitUntil: "networkidle" })
  await page.getByRole("switch", { name: "金額與損益" }).click()
  await page.getByText(/可以推算你大約持有幾股/).waitFor({ timeout: 8000 })
  await page.getByRole("switch", { name: "交易動態" }).click()
  await page.waitForTimeout(600)
  await page.getByRole("tab", { name: "動態" }).click()
  await page.getByRole("list", { name: "動態" }).waitFor({ timeout: 8000 })
  if (await page.getByRole("list", { name: "動態" }).getByText(/示範使用者\s*買進/).count()) throw new Error("own trades still visible")
  // 連續切兩個開關：兩筆設定照順序寫入，回到「我的分享」交易動態還是關的、金額還是開的（不會被先送的那筆蓋回去）
  await page.getByRole("tab", { name: "我的分享" }).click()
  if ((await page.getByRole("switch", { name: "交易動態" }).getAttribute("aria-checked")) !== "false") throw new Error("交易動態 switched back on")
  if ((await page.getByRole("switch", { name: "金額與損益" }).getAttribute("aria-checked")) !== "true") throw new Error("金額與損益 lost")
})
await check("成員分享：什麼都沒開只有「加入了群組」（不說「還沒有資料」）；隱私模式遮住金額", async () => {
  await page.goto(base + "/groups/grp_family/members/usr_bro", { waitUntil: "networkidle" })
  await page.getByText("加入了群組").waitFor({ timeout: 8000 })
  if (await page.getByText("還沒有資料", { exact: true }).count()) throw new Error("「還沒有資料」 shown next to the feed")
  await page.goto(base + "/groups/grp_family/members/usr_dad", { waitUntil: "networkidle" })
  await page.getByText("總損益").waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "隱私模式：遮蔽金額" }).click()
  await page.getByLabel("已隱藏").first().waitFor()
  await page.getByRole("button", { name: /隱私模式開啟中/ }).click()
})
await check("頻道：webhook 網址不對 → 說明；測試訊息失敗 → 說明；Telegram 連結碼 → 已連結", async () => {
  await page.goto(base + "/groups/grp_family?tab=channels", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "換一個 webhook" }).click()
  await page.getByLabel("Webhook 網址").fill("https://example.com/hook")
  await page.getByRole("button", { name: "儲存並送測試訊息" }).click()
  await page.getByText(/請貼上 Discord 頻道設定/).waitFor()
  await page.getByLabel("Webhook 網址").fill("https://discord.com/api/webhooks/123/fail-token")
  await page.getByRole("button", { name: "儲存並送測試訊息" }).click()
  await page.getByText(/測試訊息送不出去/).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "產生連結碼" }).click()
  await page.getByText(/\/link \d{6}/).waitFor({ timeout: 8000 })
  await page.getByText("已連結：").waitFor({ timeout: 15000 })
})
await check("授權查看：授權給姊姊（指定帳戶）→ 列出 → 撤銷", async () => {
  await page.goto(base + "/settings#delegations", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "授權給…" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByText("姊姊").click()
  await dialog.getByRole("radio", { name: "指定帳戶" }).click()
  await dialog.getByText("永豐・一般").click()
  await dialog.getByRole("button", { name: "授權", exact: true }).click()
  await page.getByText("已授權姊姊查看").waitFor({ timeout: 8000 })
  const row = page.getByRole("listitem").filter({ hasText: "姊姊" }).filter({ hasText: "永豐・一般" })
  await row.getByRole("button", { name: "撤銷" }).click()
  await page.getByRole("alertdialog").getByRole("button", { name: "撤銷" }).click()
  await page.getByText("已撤銷姊姊的授權").waitFor({ timeout: 8000 })
})
await check("授權查看：查看爸爸 → 唯讀橫幅、沒有記一筆／加入觀察／AI 面板、稱呼是爸爸、群組與紀錄擋住 → 結束查看", async () => {
  await page.goto(base + "/settings", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "查看爸爸的資產" }).click()
  await page.getByText("正在查看 爸爸 的資產（唯讀）").waitFor({ timeout: 8000 })
  await page.getByText("總資產").first().waitFor({ timeout: 8000 })
  if (await page.getByRole("complementary", { name: "問 AI" }).count()) throw new Error("AI panel visible in view-as")
  if (await page.getByText("觀察", { exact: true }).count()) throw new Error("watchlist visible in view-as")
  await page.getByRole("tab", { name: /交易/ }).click()
  await page.locator(".form-head").filter({ hasText: "商品" }).getByText("數量", { exact: true }).waitFor({ timeout: 8000 })
  if (await page.getByRole("button", { name: "記一筆" }).count()) throw new Error("記一筆 visible in view-as")
  await page.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  await page.getByText("參考價").first().waitFor({ timeout: 8000 })
  if (await page.getByRole("button", { name: /記一筆|加入觀察/ }).count()) throw new Error("write actions on stock page in view-as")
  await page.goto(base + "/stock/2330.TW?tab=events", { waitUntil: "networkidle" })
  await page.getByRole("radio", { name: "只看爸爸的" }).waitFor({ timeout: 8000 })
  if (await page.getByText(/只看我的|你可領/).count()) throw new Error("「我／你」 wording in view-as")
  await page.goto(base + "/groups", { waitUntil: "networkidle" })
  await page.getByText(/結束查看後才能使用/).waitFor({ timeout: 8000 })
  await page.goto(base + "/history", { waitUntil: "networkidle" })
  await page.getByText(/這裡是你自己的紀錄，結束查看後才能使用/).waitFor({ timeout: 8000 })
  if (await page.getByText("發起新對話").count()) throw new Error("AI history usable in view-as")
  await page.getByRole("region", { name: "查看模式" }).getByRole("button", { name: "結束查看" }).click()
  await page.getByText("已回到你的帳本").waitFor({ timeout: 8000 })
  if (await page.getByText("正在查看 爸爸 的資產（唯讀）").count()) throw new Error("banner still visible")
})
await check("授權查看：授權失效（403 delegation_revoked）→ 自動退出、回到自己的帳本", async () => {
  await page.goto(base + "/settings", { waitUntil: "networkidle" })
  await page.evaluate(() =>
    sessionStorage.setItem(
      "forliosa:view-as",
      JSON.stringify({ state: { target: { delegation_id: "dlg_gone", owner: { user_id: "usr_x", display_name: "某人", avatar_url: null }, scope: "all", accounts: [] } }, version: 1 }),
    ),
  )
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByText(/授權已經撤銷，已回到你的帳本/).waitFor({ timeout: 8000 })
  await page.getByText("總資產").first().waitFor({ timeout: 8000 })
  if (await page.getByRole("region", { name: "查看模式" }).count()) throw new Error("still in view-as")
})

// 邀請（還沒登入）：預覽 → 登入（回到邀請）→ 選分享 → 加入
const ictx = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "zh-TW", timezoneId: "Asia/Taipei" })
const ip = await ictx.newPage()
ip.on("pageerror", (e) => errors.push(`invite pageerror ${e.message}`))
await check("邀請：沒登入看得到預覽 → 登入後回到邀請 → 預設只開報酬率 → 加入群組", async () => {
  await ip.goto(base + "/invite/club-2026?auth=signed-out", { waitUntil: "networkidle" })
  await ip.getByRole("heading", { name: "投資讀書會", exact: true }).waitFor({ timeout: 8000 })
  await ip.getByRole("link", { name: /登入後加入/ }).click()
  await ip.waitForURL(/\/login\?next=%2Finvite%2Fclub-2026/)
  await ip.getByRole("button", { name: "用 Discord 登入" }).click()
  await ip.waitForURL(/\/invite\/club-2026/)
  await ip.getByText(/你要在「投資讀書會」分享什麼/).waitFor({ timeout: 8000 })
  const on = await ip.getByRole("switch", { name: "報酬率" }).getAttribute("aria-checked")
  const off = await ip.getByRole("switch", { name: "交易動態" }).getAttribute("aria-checked")
  if (on !== "true" || off !== "false") throw new Error("defaults are not returns-only")
  await ip.getByRole("switch", { name: "交易動態" }).click()
  await ip.getByText(/最近 90 天的買賣也會出現在動態裡/).first().waitFor()
  await ip.getByRole("button", { name: "加入群組" }).click()
  await ip.waitForURL(/\/groups\/grp_club/, { timeout: 8000 })
  await ip.getByRole("heading", { name: "投資讀書會", exact: true }).waitFor({ timeout: 8000 })
})
await check("登入頁：Discord 錯誤代碼的說明", async () => {
  await ip.goto(base + "/login?error=oauth_email_conflict", { waitUntil: "networkidle" })
  await ip.getByText(/這個 Email 已經連結到另一個 Discord 帳號/).waitFor({ timeout: 8000 })
})
await ictx.close()

// 手機：底部列（文字分頁＋「問 AI」方格）＋問 AI 全螢幕（搜尋住在這裡）
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
await check("手機：底部列是平的、滿版、貼齊畫面底部（沒有圓角、陰影），「問 AI」是直角方格；捲到最底內容不被蓋住", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  await m.getByRole("navigation", { name: "主要" }).waitFor({ timeout: 8000 })
  const bar = await m.evaluate(() => {
    const nav = document.querySelector('nav[aria-label="主要"]')
    const dock = nav.closest(".dock")
    const ask = [...dock.querySelectorAll("button")].find((b) => b.textContent.includes("問 AI"))
    const cs = getComputedStyle(dock)
    const r = dock.getBoundingClientRect()
    const a = getComputedStyle(ask)
    const ar = ask.getBoundingClientRect()
    return {
      position: cs.position, left: r.left, right: r.right, bottom: r.bottom, vw: innerWidth, vh: innerHeight,
      radius: cs.borderRadius, shadow: cs.boxShadow, bg: cs.backgroundImage, edge: getComputedStyle(dock, "::before").borderTopWidth,
      askRadius: a.borderRadius, askShadow: a.boxShadow, askW: ar.width, askH: ar.height, askInside: ar.top >= r.top && ar.bottom <= r.bottom,
      tabs: [...nav.querySelectorAll("a")].map((x) => ({ text: x.textContent.trim(), h: x.getBoundingClientRect().height, current: x.getAttribute("aria-current"), icon: !!x.querySelector("svg") })),
    }
  })
  if (bar.position !== "fixed" || bar.left !== 0 || bar.right !== bar.vw || Math.abs(bar.bottom - bar.vh) > 0.5) throw new Error(`bar is not flush with the viewport: ${JSON.stringify(bar)}`)
  if (bar.radius !== "0px" || bar.shadow !== "none" || bar.bg !== "none" || bar.edge !== "1px") throw new Error(`bar is not flat and ruled: ${JSON.stringify(bar)}`)
  if (bar.askRadius !== "0px" || bar.askShadow !== "none" || !bar.askInside || bar.askH < 44 || bar.askW < 44) throw new Error(`問 AI is not a square box inside the bar: ${JSON.stringify(bar)}`)
  if (bar.tabs.map((t) => t.text).join("・") !== "帳本・群組・紀錄") throw new Error(`tabs: ${JSON.stringify(bar.tabs)}`)
  if (bar.tabs.some((t) => t.h < 44 || t.icon)) throw new Error(`tabs must be text, ≥ 44px: ${JSON.stringify(bar.tabs)}`)
  if (bar.tabs.filter((t) => t.current === "page").map((t) => t.text).join() !== "帳本") throw new Error(`current tab: ${JSON.stringify(bar.tabs)}`)
  // 捲到最底：頁面最後的內容在底部列上面（下方留的是底部列的實際高度）
  await m.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }))
  await m.waitForTimeout(300)
  const end = await m.evaluate(() => {
    const dock = document.querySelector(".dock").getBoundingClientRect()
    const content = document.querySelector("#main").firstElementChild.getBoundingClientRect()
    return { contentBottom: content.bottom, dockTop: dock.top, dockH: dock.height }
  })
  if (end.contentBottom > end.dockTop + 0.5) throw new Error(`content hidden behind the bar: ${JSON.stringify(end)}`)
  if (end.dockTop - end.contentBottom > 8) throw new Error(`the reserve under the content is not the bar's height: ${JSON.stringify(end)}`)
})
await check("手機：主數字是平的（沒有卡片、沒有展開鈕），今日與總損益直接看得到；本週事項的第一格是日期格；分段每一段 44px", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  await m.getByText("總損益（含股利）").waitFor({ timeout: 8000 })
  await m.getByText("今日", { exact: true }).waitFor()
  if (await m.getByRole("button", { name: /總損益與走勢/ }).count()) throw new Error("the hero still has an expand button")
  const week = m.getByRole("link", { name: /^本週 \d+ 件事，查看全部$/ })
  if (!(await week.evaluate((el) => el.firstElementChild.classList.contains("date-cell")))) throw new Error("week line does not start with a date cell")
  const heights = await m.getByRole("tablist", { name: "帳本內容" }).getByRole("tab").evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height))
  if (heights.some((h) => h < 44)) throw new Error(`segments under 44px: ${heights.join(", ")}`)
})
await check("手機：股利清單整列都可以按（按在金額上也到個股頁）", async () => {
  await m.goto(base + "/?view=dividends", { waitUntil: "networkidle" })
  const received = m.locator("section", { has: m.locator("#div-received") })
  const row = received.locator("li").filter({ has: m.getByRole("link") }).first()
  await row.waitFor({ timeout: 8000 })
  await row.evaluate((el) => el.scrollIntoView({ block: "center" }))
  const href = await row.getByRole("link").first().getAttribute("href")
  const box = await row.boundingBox()
  if (box.height < 44) throw new Error(`dividend row ${box.height}px`)
  await m.mouse.click(box.x + box.width - 24, box.y + box.height / 2)
  await m.waitForURL((u) => u.pathname === href, { timeout: 8000 })
})
await check("手機：持倉列有定期定額標記，按標記到設定、按列到個股頁", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  const list = m.getByRole("list", { name: "持倉" })
  await list.getByRole("link", { name: /定期定額：每月 6 日/ }).click()
  await m.waitForURL(/\/settings#plan-rcp_demo0050/)
  await m.goto(base + "/", { waitUntil: "networkidle" })
  // 按在列的右半邊（現價），不是名稱
  const row = list.locator("li").filter({ hasText: "元大台灣50" })
  await row.evaluate((el) => el.scrollIntoView({ block: "center" }))
  const box = await row.boundingBox()
  await m.mouse.click(box.x + box.width - 30, box.y + box.height / 2)
  await m.waitForURL(/\/stock\/0050\.TW/)
})
await check("手機：法人觀點三行列＋免責", async () => {
  await m.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  await m.getByRole("button", { name: /法人觀點/ }).click()
  await m.getByRole("list", { name: "法人觀點" }).getByText("外資券商 A", { exact: true }).waitFor({ timeout: 8000 })
  await m.getByText("非 Forliosa 建議").first().waitFor()
})
await check("手機：查看爸爸時「問 AI」換成「結束查看」；橫幅往下捲也在頂端，個股分頁列排在它下面", async () => {
  await m.goto(base + "/settings", { waitUntil: "networkidle" })
  await m.getByRole("button", { name: "查看爸爸的資產" }).click()
  await m.getByText("正在查看 爸爸 的資產（唯讀）").waitFor({ timeout: 8000 })
  if (await m.getByRole("button", { name: /^問 AI/ }).count()) throw new Error("ask AI visible in view-as")
  await m.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  await m.getByText("參考價").first().waitFor({ timeout: 8000 })
  await m.evaluate(() => window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" }))
  await m.waitForTimeout(300)
  const layout = await m.evaluate(() => {
    const banner = document.querySelector('[aria-label="查看模式"]').getBoundingClientRect()
    const tabs = document.querySelector('[aria-label="個股資料"]')?.closest(".sticky")?.getBoundingClientRect()
    return { bannerTop: banner.top, bannerBottom: banner.bottom, tabsTop: tabs?.top ?? null }
  })
  if (Math.abs(layout.bannerTop) > 1) throw new Error(`banner scrolled away (top ${layout.bannerTop})`)
  if (layout.tabsTop === null || Math.abs(layout.tabsTop - layout.bannerBottom) > 1) throw new Error(`tab bar not under the banner (${JSON.stringify(layout)})`)
  await m.getByRole("button", { name: /結束查看$/ }).click()
  await m.getByRole("button", { name: /^問 AI/ }).waitFor({ timeout: 8000 })
})
await check("手機：群組七個分頁一次看得到（「成員」「頻道」不在淡出的那一邊）；更窄的螢幕才橫向捲動，直接打開「成員」時捲到那個分頁", async () => {
  await m.goto(base + "/groups/grp_family?tab=members", { waitUntil: "networkidle" })
  await m.getByText("邀請連結").first().waitFor({ timeout: 8000 })
  const visible = await m.getByRole("tab", { name: "成員" }).evaluate((el) => {
    const r = el.getBoundingClientRect()
    return r.left >= 0 && r.right <= window.innerWidth
  })
  if (!visible) throw new Error("active tab not scrolled into view")
  const row = await m.getByRole("tablist", { name: "群組內容" }).evaluate((el) => ({
    faded: el.hasAttribute("data-overflow-start") || el.hasAttribute("data-overflow-end"),
    hidden: [...el.querySelectorAll('[role="tab"]')].filter((t) => { const r = t.getBoundingClientRect(); return r.left < 0 || r.right > window.innerWidth }).map((t) => t.textContent),
    small: [...el.querySelectorAll('[role="tab"]')].filter((t) => t.getBoundingClientRect().height < 44).length,
  }))
  if (row.faded || row.hidden.length) throw new Error(`group tabs do not all fit on an iPhone 15: ${JSON.stringify(row)}`)
  if (row.small) throw new Error(`${row.small} group tabs under 44px tall`)
  // 320px 寬：放不下才捲動，選取中的「成員」捲進畫面，頁面本身不橫向捲動
  const narrow = await browser.newContext({ viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true, locale: "zh-TW", timezoneId: "Asia/Taipei" })
  try {
    const n = await narrow.newPage()
    await n.goto(base + "/groups/grp_family?tab=members", { waitUntil: "networkidle" })
    await n.getByText("邀請連結").first().waitFor({ timeout: 8000 })
    await n.waitForTimeout(300)
    const at320 = await n.getByRole("tab", { name: "成員" }).evaluate((el) => {
      const r = el.getBoundingClientRect()
      const c = el.parentElement.getBoundingClientRect()
      return { inside: r.left >= c.left && r.right <= c.right, scrolls: el.parentElement.scrollWidth > el.parentElement.clientWidth, pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth }
    })
    if (!at320.scrolls || !at320.inside || at320.pageOverflow > 0) throw new Error(`320px: ${JSON.stringify(at320)}`)
  } finally {
    await narrow.close()
  }
})
await check("手機：動態的表情・加表情・留言・刪除確認都 ≥ 44px；成員頁是格線鍵值列（不是指標磚），持股整列可點", async () => {
  await m.goto(base + "/groups/grp_family?tab=feed", { waitUntil: "networkidle" })
  const dad = m.getByRole("listitem").filter({ hasText: /爸爸\s*買進\s*台積電/ }).first()
  await dad.getByText("成交價").waitFor({ timeout: 8000 })
  const heights = async (loc) => loc.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().height)))
  const actions = [
    ...(await heights(dad.getByRole("button", { name: /^(讚|厲害|恭喜) \d/ }))),
    ...(await heights(dad.getByRole("button", { name: "加表情" }))),
    ...(await heights(dad.getByRole("button", { name: /^留言/ }))),
  ]
  if (actions.length < 3 || actions.some((h) => h < 44)) throw new Error(`feed actions under 44px: ${actions.join(", ")}`)
  await dad.getByRole("button", { name: /^留言/ }).click()
  await dad.getByRole("button", { name: "刪除這則留言" }).first().click()
  const confirm = [...(await heights(dad.getByRole("button", { name: "刪除", exact: true }))), ...(await heights(dad.getByRole("button", { name: "取消" })))]
  if (confirm.length < 2 || confirm.some((h) => h < 44)) throw new Error(`delete confirm under 44px: ${confirm.join(", ")}`)
  await dad.getByRole("button", { name: "取消" }).click()
  await m.goto(base + "/groups/grp_family/members/usr_dad", { waitUntil: "networkidle" })
  const returns = m.getByRole("region", { name: "報酬率" })
  await returns.getByText("總報酬（含股利）").waitFor({ timeout: 8000 })
  const rows = await returns.locator("dl > div").evaluateAll((els) =>
    els.map((el) => { const c = getComputedStyle(el); const r = el.getBoundingClientRect(); return { h: r.height, w: r.width, left: c.borderLeftWidth, top: c.borderTopWidth, bottom: c.borderBottomWidth, bg: c.backgroundColor } }),
  )
  if (rows.length !== 4) throw new Error(`expected 4 return rows, got ${rows.length}`)
  // 每一列：只有下面一條格線（沒有外框、沒有底色），整列寬，44px 以上
  if (rows.some((r) => r.left !== "0px" || r.top !== "0px" || r.bottom !== "1px" || r.bg !== "rgba(0, 0, 0, 0)" || r.h < 44 || r.w < 300)) throw new Error(`member returns are not ruled key-value rows: ${JSON.stringify(rows)}`)
  const holding = m.getByRole("region", { name: /持股/ }).getByRole("listitem").first()
  const hit = await holding.evaluate((li) => {
    const a = li.querySelector("a")
    li.scrollIntoView({ block: "center" })
    const r = li.getBoundingClientRect()
    // 列的右邊（百分比那一欄）也按得到同一個連結
    const at = document.elementFromPoint(r.right - 8, r.top + r.height / 2)
    return { height: r.height, covers: at === a || a.contains(at) }
  })
  if (hit.height < 44 || !hit.covers) throw new Error(`holding row link does not cover the row: ${JSON.stringify(hit)}`)
})
await check("手機：問 AI 頂端的三個圖示鈕（新對話・紀錄・關閉）同一個樣式、都是 44px", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  await m.getByRole("button", { name: /^問 AI/ }).click()
  const dialog = m.getByRole("dialog")
  const buttons = [dialog.getByRole("button", { name: "新對話" }), dialog.getByRole("button", { name: "紀錄", exact: true }), dialog.getByRole("button", { name: "關閉" })]
  const looks = await Promise.all(
    buttons.map((b) => b.evaluate((el) => { const c = getComputedStyle(el); return [c.width, c.height, c.borderRadius, c.backgroundColor, c.color].join(" ") })),
  )
  if (new Set(looks).size !== 1) throw new Error(`header buttons differ: ${looks.join(" | ")}`)
  if (!looks[0].startsWith("44px 44px")) throw new Error(`header buttons not 44px: ${looks[0]}`)
  await dialog.getByRole("button", { name: "關閉" }).click()
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
