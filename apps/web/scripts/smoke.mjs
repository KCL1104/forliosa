// 冒煙測試（新資訊架構，mock 模式）：node scripts/smoke.mjs [--base=http://localhost:5173]
// 走過每個路由，確認關鍵文字出現、沒有 console 錯誤；也測試 AI 草稿→簽名入帳→復原、隱私模式、⌘K、手機的問 AI，
// 以及第二批：出清紀錄、定期定額（設定與扣款日草稿）、公告、1 日走勢的授權說明、資料來源與授權、商用模式沒有示範標記；
// 第三批：法人觀點（展開 → 查詢 → 搜尋中 → 結果／查無／查不到）、持倉的定期定額標記、補記漏記的扣款、已出清依年份分組。
// 第四批：股利自動入帳（交易與股利頁的「自動」、編輯後「自動・已修改」、刪除後不再出現）。
// 第五批：上市股票沒有逐檔三大法人資料（空狀態＋問 AI 外資動向，上櫃照常）、補記定期定額用扣款日的收盤價。
// M5 分享：群組（建立、邀請連結、排行與討論串、動態與表情、我的分享、成員分享、頻道）、邀請（沒登入 → 登入 → 選分享 → 加入）、
// 授權查看（授權給別人、查看別人的唯讀模式、授權失效自動退出）、登入頁的錯誤說明。
// 討論串（2026-11-13）：沒登入讀公開清單與主題、選公開暱稱 → 發主題 → 回覆（頻率限制）→ 表情 → 檢舉 → 管理後台隱藏、
// 群組主題只在全部與群組的篩選裡、個股與群組的討論分頁、手機的底部列（帳本・市場・群組・討論）與從「問 AI」的時鐘到紀錄。
// mock 的狀態在記憶體裡：同一個流程用站內導覽（不重新載入），重新載入就回到示範資料。
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
// 開發時只跑名稱含某段字的檢查：--only=討論；好幾段用「|」隔開：--only="AI 圖卡|商用模式"（有些檢查接著上一個檢查的畫面，交付前要整份跑過）
const onlyCheck = process.argv.find((a) => a.startsWith("--only="))?.slice(7)

const ROUTES = [
  ["/", "總資產"],
  ["/?view=transactions", "稅費"],
  ["/?view=dividends", "已入帳"],
  ["/?view=performance", "美股沒有報價，含美股的帳戶算不出績效"],
  ["/stock/2330.TW", "近四季 EPS"],
  ["/stock/2330.TW?tab=valuation", "各倍數對應的股價"],
  // 友達虧損的年份在商用模式的存檔起點之前：用示範資料（personal）看「本益比沒有意義」
  ["/stock/2409.TW?tab=valuation&policy=personal", "本益比沒有意義"],
  ["/stock/2330.TW?tab=financials&policy=commercial", "營業利益率"],
  ["/stock/2330.TW?tab=chips", "上市股票沒有逐檔三大法人資料"],
  ["/stock/3711.TW?tab=chips", "前 20 名第 12 名"],
  ["/stock/6488.TWO?tab=chips", "三大法人買賣超"],
  ["/stock/2603.TW", "過去的持有"],
  ["/data-sources", "上市個股日成交資訊"],
  ["/stock/2330.TW?tab=dividends", "配息紀錄"],
  ["/stock/2330.TW?tab=events", "法說會"],
  ["/stock/0050.TW?tab=financials", "收益分配"],
  ["/stock/NVDA?tab=chips", "美股沒有法人與融資融券資料"],
  ["/stock/NOPE.TW", "找不到"],
  ["/market", "收盤重點"],
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
  ["/history", "新對話"],
  ["/discussions", "台積電法說會前，大家怎麼配置？"],
  ["/discussions?scope=group&group_id=grp_family", "我把聯發科的交易補記好了"],
  ["/discussions/top_p_tsmc", "比重超過自己睡得著的程度就調"],
  ["/discussions/top_g_dca", "我明天去問營業員怎麼設定"],
  ["/discussions/top_nope", "找不到這個主題"],
  ["/discussions/new", "發到哪裡"],
  ["/admin", "AI 金鑰"],
  ["/admin/discussions", "停權中"],
  ["/admin/news", "封鎖中"],
  ["/terms", "服務條款"],
  ["/privacy", "隱私權政策"],
  ["/stock/2330.TW?tab=discussions", "台積電法說會前，大家怎麼配置？"],
  ["/groups/grp_family?tab=discussions", "過年的紅包，要不要一起存 0056？"],
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
  if (onlyCheck && !onlyCheck.split("|").some((part) => name.includes(part))) return
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

await check("AI 草稿：買 0050 2 張 52.4 → 合計（不自動算手續費）→ 待簽名 → 簽名入帳 → 復原", async () => {
  await page.getByRole("button", { name: "新對話" }).click()
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("買 0050 2 張 52.4")
  await box.press("Enter")
  await page.getByText("NT$104,800").waitFor({ timeout: 8000 })
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

await check("自由提問：誠實說明現在答不了（不猜、不承諾時程），給手動路徑", async () => {
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("台積電的護城河是什麼")
  await box.press("Enter")
  // 規則版回答用現在式：說明這題要上網查、現在答不了，再給最接近的手動路徑（帳本上是「看持倉」）
  const panel = page.getByRole("complementary", { name: "問 AI" })
  await panel.getByText("這題要查網路資料，現在沒辦法。").last().waitFor({ timeout: 5000 })
  if (await panel.getByText(/下一階段/).count()) throw new Error("fallback must not promise a timeline")
  const path = panel.getByRole("link", { name: /看持倉/ }).last()
  await path.waitFor()
  if ((await path.getAttribute("href")) !== "/") throw new Error(`manual path ${await path.getAttribute("href")}`)
})

await check("AI 圖卡：比較 2330 和 2317 → 兩條線（分類色、線尾代號、圖例與說明）、方向鍵看讀數、不超出面板；畫月營收 → 柱狀", async () => {
  // 單獨跑這一項（--only）時前面沒有開過頁面
  if (!(await page.getByLabel("提出問題或下指令").count())) await page.goto(base + "/", { waitUntil: "networkidle" })
  const box = page.getByLabel("提出問題或下指令")
  const panel = page.getByRole("complementary", { name: "問 AI" })
  await box.fill("比較 2330 和 2317")
  await box.press("Enter")
  const fig = panel.getByRole("figure", { name: /台積電、鴻海 漲跌幅/ })
  await fig.waitFor({ timeout: 8000 })
  const strokes = await fig.locator('svg path[stroke-width="2"]').evaluateAll((els) => els.map((e) => e.getAttribute("stroke")))
  if (strokes.join() !== "var(--series-1),var(--series-2)") throw new Error(`series colours: ${strokes}`)
  // 分類色不是漲跌的紅綠，兩條線的顏色也不一樣
  const painted = await fig.locator('svg path[stroke-width="2"]').evaluateAll((els) => els.map((e) => getComputedStyle(e).stroke))
  const price = await page.evaluate(() => ["--rise", "--fall"].map((v) => { const d = document.createElement("i"); d.style.color = `var(${v})`; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return c }))
  if (painted[0] === painted[1] || painted.some((c) => price.includes(c) || c === "none")) throw new Error(`series paint: ${painted}`)
  for (const code of ["2330", "2317"]) if (!(await fig.getByText(code, { exact: true }).count())) throw new Error(`no end label ${code}`)
  if (!(await fig.getByText("漲跌幅只算價格變動，不含股利").count())) throw new Error("the note is missing")
  if (!(await fig.getByText(/^資料來源：/).count())) throw new Error("the sources line is missing")
  const [pb, fb, sb] = [await panel.boundingBox(), await fig.boundingBox(), await fig.locator("svg").boundingBox()]
  if (fb.x + fb.width > pb.x + pb.width + 0.5 || sb.x + sb.width > fb.x + fb.width + 0.5 || sb.x < fb.x - 0.5) throw new Error("the chart overflows the panel")
  await fig.getByRole("group").focus()
  await page.keyboard.press("ArrowLeft")
  const live = fig.locator("[aria-live]")
  if (!/^\d{4}\/\d{2}\/\d{2}：台積電 .+%、鴻海 .+%$/.test(await live.innerText())) throw new Error(`readout: ${await live.innerText()}`)
  await page.keyboard.press("Escape")
  if ((await live.innerText()) !== "") throw new Error("Escape should close the readout")
  await box.fill("畫台積電的月營收")
  await box.press("Enter")
  const bars = panel.getByRole("figure", { name: "台積電 月營收" })
  await bars.waitFor({ timeout: 8000 })
  if ((await bars.locator("svg g[fill] > path").count()) < 12) throw new Error("the revenue bars are missing")
  if (await bars.locator('svg path[stroke-width="2"]').count()) throw new Error("one series of monthly revenue should be bars, not a line")
})

await check("每日收盤簡報：設定打開 → 面板最上面一塊、問 AI 旁有未讀圓點 → 看過圓點消失；對話紀錄頁有「收盤簡報」段落", async () => {
  await page.goto(base + "/settings", { waitUntil: "networkidle" })
  const sw = page.getByRole("switch", { name: /每日收盤簡報/ })
  await sw.evaluate((el) => el.scrollIntoView({ block: "center" }))
  if ((await sw.getAttribute("aria-checked")) !== "false") throw new Error("the daily briefing is on by default")
  await sw.click()
  for (let i = 0; i < 40 && (await sw.getAttribute("aria-checked")) !== "true"; i++) await page.waitForTimeout(100)
  if ((await sw.getAttribute("aria-checked")) !== "true") throw new Error("the switch did not turn on")
  await page.waitForTimeout(300)
  // 站內換頁（重新載入會讓示範資料回到預設）
  await page.getByRole("link", { name: "Forliosa 帳本" }).first().click()
  const panel = page.getByRole("complementary", { name: "問 AI" })
  // 簡報在面板的首頁：前面的檢查可能留著一段對話
  await panel.getByRole("button", { name: "新對話" }).click()
  await panel.getByText("收盤簡報", { exact: true }).waitFor({ timeout: 8000 })
  // 未讀圓點：一打開簡報就開始算「看過了」，所以只確認這一則原本是沒看過的（標題前的圓點出現過）
  await page.locator("[data-briefing-dot]").first().waitFor({ state: "attached", timeout: 2000 }).catch(() => {
    throw new Error("no unread dot for a new briefing")
  })
  await panel.getByText(/AI 依這些報導整理/).waitFor()
  await page.waitForFunction(() => !document.querySelector("[data-briefing-dot]"), null, { timeout: 6000 })
  // 站內換到紀錄頁（⌘K 的頁面清單）
  await page.getByRole("button", { name: /搜尋股票/ }).first().click()
  await page.keyboard.type("對話紀錄")
  await page.getByRole("option", { name: /^對話紀錄/ }).first().click()
  await page.waitForURL(/\/history/)
  await page.getByRole("heading", { name: "收盤簡報" }).first().waitFor({ timeout: 8000 })
})

await check("深度搜尋：輸入框的切換鈕（文字、沒有圖示）→ 下面一句「用掉 5 題」→ 送出後那一題標「深度搜尋」、回一份有短標題與來源的整理、切換鈕彈回來", async () => {
  if (!(await page.getByLabel("提出問題或下指令").count())) await page.goto(base + "/", { waitUntil: "networkidle" })
  const panel = page.getByRole("complementary", { name: "問 AI" })
  const toggle = panel.getByRole("button", { name: "深度搜尋", exact: true })
  if ((await toggle.getAttribute("aria-pressed")) !== "false") throw new Error("the toggle should start off")
  if (await toggle.locator("svg").count()) throw new Error("the toggle has an icon")
  if (await panel.getByText(/用掉 5 題/).count()) throw new Error("the hint shows while the toggle is off")
  await toggle.click()
  const hint = panel.getByText("多查幾輪資料，寫成一份整理，用掉 5 題。")
  await hint.waitFor()
  const hintSize = await hint.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))
  if (hintSize < 15) throw new Error(`the hint is ${hintSize}px (a sentence to read is 15px)`)
  // 切換鈕、鍵盤提示、送出鈕在同一列，不互相擠
  const boxes = await panel.locator("form[aria-label='問 AI'] > div:last-child").evaluate((row) => [...row.querySelectorAll("button, span[aria-hidden]")].map((el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right), Math.round(r.height)] }).filter(([l, r]) => r > l))
  for (let i = 1; i < boxes.length; i++) if (boxes[i][0] < boxes[i - 1][1]) throw new Error(`composer controls overlap: ${JSON.stringify(boxes)}`)
  const box = page.getByLabel("提出問題或下指令")
  await box.fill("深入研究台積電")
  await box.press("Enter")
  await panel.getByText("最近的消息").waitFor({ timeout: 8000 })
  const asked = panel.locator("p", { hasText: "深入研究台積電" }).first()
  if (!(await asked.getByText("深度搜尋", { exact: true }).count())) throw new Error("the question is not marked 深度搜尋")
  const report = await panel.locator(".ai-voice").last().innerText()
  const lines = report.split("\n").filter(Boolean)
  const points = lines.filter((l) => l.startsWith("・"))
  if (points.length < 3 || points.length > 8) throw new Error(`report points: ${points.length}`)
  if (!lines.includes("營運") || !lines.includes("最近的消息")) throw new Error(`report headings: ${lines.filter((l) => !l.startsWith("・")).join("|")}`)
  if (/\*\*|^#/m.test(report)) throw new Error("the report contains Markdown")
  if (!(await panel.getByText("出處", { exact: true }).count())) throw new Error("the report has no sources")
  if ((await toggle.getAttribute("aria-pressed")) !== "false") throw new Error("the toggle should switch itself off after sending")
  if (await panel.getByText(/用掉 5 題/).count()) throw new Error("the hint stays after sending")
})

await check("帳本工具列的「記一筆」：直接開輸入框（不經過 AI 面板）；選一檔、填兩筆買進 → 新增", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "記一筆", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("heading", { name: "記一筆", exact: true }).waitFor()
  if (await page.getByText(/買賣了什麼/).count()) throw new Error("the toolbar button went through the AI panel")
  if (await dialog.getByText("稅費試算").count()) throw new Error("the simple entry shows the fee estimate")
  await dialog.getByPlaceholder("代號或名稱，例如 2330、台積").fill("2317")
  await page.getByRole("option", { name: /2317/ }).first().click()
  const qty = dialog.locator("#lot-qty-0")
  const inLots = (await qty.getAttribute("aria-label")) === "張數"
  await qty.fill(inLots ? "1" : "1000")
  await dialog.locator("#lot-price-0").fill("230")
  await dialog.getByRole("button", { name: "再加一筆買進" }).click()
  await dialog.getByRole("textbox", { name: /第 2 筆的(張數|股數)/ }).fill(inLots ? "2" : "2000")
  await dialog.getByRole("textbox", { name: "第 2 筆的買進價格" }).fill("228")
  await dialog.getByRole("button", { name: "新增", exact: true }).click()
  await page.getByText(/已記錄：買進 鴻海 3 張（2 筆）/).waitFor({ timeout: 8000 })
  await dialog.waitFor({ state: "detached", timeout: 4000 })
})

await check("減少持股：持倉那一列的選單（加碼・減少持股・全部賣出）→ 只填股數 → 用最新的收盤價記成賣出", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "鴻海的動作" }).click()
  const items = await page.getByRole("menu").getByRole("menuitem").allInnerTexts()
  if (items.join("|") !== "加碼|減少持股|全部賣出") throw new Error(`row menu: ${items}`)
  await page.getByRole("menuitem", { name: "減少持股" }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("heading", { name: "減少持股" }).waitFor()
  await dialog.getByText(/記成賣出。$/).waitFor({ timeout: 8000 })
  if (await dialog.getByText(/手續費|證交稅/).count()) throw new Error("the reduce dialog shows fees")
  const label = await dialog.locator('label[for="reduce-qty"]').innerText()
  await dialog.locator("#reduce-qty").fill(label.endsWith("張數") ? "1" : "1000")
  await dialog.getByRole("button", { name: "賣出", exact: true }).click()
  await page.getByText("已記錄：賣出 鴻海 1 張").waitFor({ timeout: 8000 })
  await dialog.waitFor({ state: "detached", timeout: 4000 })
})

await check("帳本的欄位選單：勾選格排成兩欄，文字是橫的（不會被擠成一個字寬）", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "自訂欄位與顯示" }).click()
  const group = page.getByRole("group", { name: "欄位" })
  await group.waitFor()
  const sizes = await group.locator("label").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)] }))
  if (sizes.length < 6) throw new Error(`only ${sizes.length} column options`)
  const bad = sizes.filter(([w, h]) => w < 90 || h > 48)
  if (bad.length) throw new Error(`column labels squeezed: ${JSON.stringify(sizes)}`)
  await page.keyboard.press("Escape")
})

await check("手動記帳表單（備援路徑）：手續費選填、合計照填的算，並儲存", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  // 「＋」直接打開表單（只有一件事，不做成選單）
  await page.getByRole("button", { name: "用表單記一筆" }).click()
  // 預設是簡單的買進輸入；賣出、股利與選填的手續費在完整表單裡
  await page.getByRole("dialog").getByRole("button", { name: "賣出、股利或其他" }).click()
  await page.getByRole("dialog").getByRole("heading", { name: "記一筆交易" }).waitFor()
  // 從「賣出、股利或其他」進來，類型先選在「賣出」（照填不會記成買進）；這裡要記的是買進，自己改回來
  const types = page.getByRole("dialog").getByRole("radiogroup", { name: "交易類型" })
  if ((await types.getByRole("radio", { name: "賣出" }).getAttribute("aria-checked")) !== "true") throw new Error("full form did not open on 賣出")
  await types.getByRole("radio", { name: "買進" }).click()
  await page.getByPlaceholder("代號或名稱，例如 2330、台積").fill("2454")
  await page.getByRole("option", { name: /2454/ }).first().click()
  await page.locator("#trade-qty").fill("1")
  await page.locator("#trade-price").fill("1435")
  // 不自動算手續費：合計就是成交金額；自己填了手續費才加上去
  await page.getByRole("dialog").getByText("NT$1,435,000").first().waitFor({ timeout: 8000 })
  await page.locator("#trade-fee").fill("204")
  await page.getByRole("dialog").getByText("NT$1,435,204").first().waitFor({ timeout: 8000 })
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
  const note = row.getByText(/^200 股 × 每股/)
  await note.waitFor()
  const clipped = await note.evaluate((el) => el.scrollWidth > el.clientWidth + 1 || getComputedStyle(el).textOverflow === "ellipsis" || getComputedStyle(el).overflow === "hidden")
  if (clipped) throw new Error("the auto-dividend note is truncated")
  if (!(await note.textContent()).includes("發放")) throw new Error("the auto-dividend note lost its ending")
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
await check("數字鍵 1–3 切換帳本分段（持倉・紀錄・績效；aria-keyshortcuts）；在輸入框裡打數字不會切換", async () => {
  await page.goto(base + "/", { waitUntil: "networkidle" })
  await page.getByRole("tab", { name: /紀錄/ }).waitFor({ timeout: 8000 })
  const segments = await page.getByRole("tablist", { name: "帳本內容" }).getByRole("tab").allInnerTexts()
  if (segments.map((t) => t.replace(/[\d\s]/g, "")).join("|") !== "持倉|紀錄|績效") throw new Error(`ledger segments: ${segments}`)
  if ((await page.getByRole("tab", { name: /紀錄/ }).getAttribute("aria-keyshortcuts")) !== "2") throw new Error("missing aria-keyshortcuts")
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
  await page.keyboard.press("2")
  await page.waitForURL(/view=transactions/)
  // 「紀錄」裡的兩個小分頁：交易、股利
  await page.getByRole("tablist", { name: "紀錄的內容" }).getByRole("tab", { name: /股利/ }).click()
  await page.waitForURL(/view=dividends/)
  if ((await page.getByRole("tab", { name: /紀錄/ }).getAttribute("aria-selected")) !== "true") throw new Error("紀錄 is not selected on the dividends view")
  await page.keyboard.press("3")
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
await check("績效：含美股時一打開自動只算新台幣帳戶；選「全部帳戶」才是空狀態（只留帳戶選單、原因說一次、一個動作）→ 只看台幣帳戶就有區間、基準、績效與「績效從 … 開始算」", async () => {
  // 一打開：自動只算新台幣帳戶，上面一行說明（不是空白）
  await page.getByText(/^只算「.+」。美股沒有報價，含美股的帳戶算不出績效。$/).waitFor({ timeout: 8000 })
  await page.getByRole("radiogroup", { name: "績效區間" }).waitFor()
  // 自己選「全部帳戶」：算不出來、換區間或基準也沒有用，不放那兩個控制項，只留帳戶；原因在這一頁只說一次
  await page.getByRole("combobox", { name: "帳戶" }).click()
  await page.getByRole("option", { name: "全部帳戶" }).click()
  await page.getByText("算不出績效", { exact: true }).waitFor({ timeout: 8000 })
  if (await page.getByRole("radiogroup", { name: "績效區間" }).count()) throw new Error("range chips shown while nothing can be computed")
  if (await page.getByRole("combobox", { name: "績效比較基準" }).count()) throw new Error("benchmark select shown while nothing can be computed")
  await page.getByRole("combobox", { name: "帳戶" }).waitFor()
  const reasons = await page.locator("main").getByText(/美股/).count()
  if (reasons !== 1) throw new Error(`the reason should appear once, got ${reasons}`)
  await page.getByRole("button", { name: /^只看「/ }).first().waitFor({ timeout: 8000 })
  if ((await page.getByRole("button", { name: /^只看「/ }).count()) !== 1) throw new Error("the empty state should offer exactly one action")
  await page.getByRole("button", { name: /只看「永豐/ }).click()
  await page.getByText("最大回撤").first().waitFor({ timeout: 8000 })
  await page.getByText(/績效從 2026\/06\/01 收盤開始算，之前沒有資料/).first().waitFor()
  // 畫面上不講授權或系統怎麼存資料
  if (await page.locator("main").getByText(/可商用|起存檔|資料累積中：/).count()) throw new Error("performance notes still talk about licensing or archiving")
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
  await page.getByText(/11\/6 是元大台灣50 定期定額的扣款日，帳本裡還沒有這一筆。/).waitFor()
  // 扣款日已經過去：用那天（11/6）的收盤價，不是最近收盤價（怎麼估的寫在草稿卡的說明行，訊息裡不再說一次）
  await page.getByText(/股數用 11\/6 收盤價/).last().waitFor()
  await page.getByRole("button", { name: "簽名：確認入帳" }).click()
  await page.getByText(/已入帳：買進 元大台灣50/).waitFor({ timeout: 8000 })
  await page.getByRole("button", { name: "新對話" }).click()
  await page.waitForTimeout(1000)
  if (await page.getByRole("button", { name: /補記 11\/06 的 0050/ }).count()) throw new Error("still offered after signing")
})
await check("上市股票的籌碼：三大法人是空狀態、外資持股只有前 20 名，AI 面板與空狀態都能問外資動向；上櫃照常", async () => {
  await page.goto(base + "/stock/2330.TW?tab=chips", { waitUntil: "networkidle" })
  await page.getByText("上市股票沒有逐檔三大法人資料").waitFor({ timeout: 8000 })
  await page.getByText(/證交所只公布外資持股比率前 20 名，台積電不在名單上/).waitFor()
  if (await page.getByText("資料不足。").count()) throw new Error("foreign holding should explain, not say 資料不足")
  const asks = page.getByRole("button", { name: "最近外資對這檔的動向？" })
  if ((await asks.count()) !== 2) throw new Error(`expected the panel chip and the empty-state button, got ${await asks.count()}`)
  await page.locator("main").getByRole("button", { name: "最近外資對這檔的動向？" }).click()
  await page.getByText("台積電沒有逐檔的外資買賣資料。").waitFor({ timeout: 8000 })
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
await check("個股：1 日走勢說明沒有盤中走勢（價格是收盤後公布的收盤價），按「看 5 日走勢」切換", async () => {
  await page.goto(base + "/stock/0050.TW", { waitUntil: "networkidle" })
  await page.getByRole("radio", { name: "1日" }).click()
  await page.getByText("沒有盤中走勢：價格是收盤後公布的收盤價").waitFor()
  const chart = page.getByRole("region", { name: "走勢圖" })
  // 標題已經說完：後端同一句話不再印一次，也不講授權；不承諾「加入觀察就會記錄盤中走勢」
  if (await chart.getByText(/付費授權|沒有盤中走勢，價格是/).count()) throw new Error("the 1-day empty state repeats the note or talks about licensing")
  if (await chart.getByText(/每分鐘|加入觀察後/).count()) throw new Error("the 1-day empty state promises intraday data")
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
await check("ETF 淨值與折溢價：0050 同一天、有走勢與逐日數字；00679B 淨值晚一天寫出兩個日期；00878 資料不到 20 天；估值分頁同一塊；股票沒有", async () => {
  // 總覽：淨值與折溢價在鍵值格裡（同一天 11/12），格子下面接「折溢價走勢」（走勢、追蹤誤差說明、逐日數字）
  await page.goto(base + "/stock/0050.TW", { waitUntil: "networkidle" })
  const band = page.getByRole("region", { name: "關鍵數據" })
  await band.getByRole("term").getByText("淨值（11/12）", { exact: true }).waitFor({ timeout: 8000 })
  const premium = band.locator("dl > div").filter({ has: page.getByRole("term").getByText("折溢價（11/12）", { exact: true }) })
  await premium.getByRole("definition").getByText(/^(溢價|折價) \d\.\d\d%$/).waitFor()
  const trend = band.getByRole("region", { name: "折溢價走勢" })
  await trend.getByRole("img", { name: /^60 個有資料的交易日（\d+\/\d+–11\/12）的折溢價/ }).waitFor()
  if (await trend.getByText(/最新的淨值是/).count()) throw new Error("0050 NAV and close are the same day")
  await trend.getByText("沒有追蹤誤差。").waitFor()
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
  await page.getByRole("region", { name: "折溢價走勢" }).getByText("淨值資料從 2026/11/03 開始").waitFor({ timeout: 8000 })
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
  const said = await main.evaluate((el) => (el.textContent.match(/美股沒有報價/g) ?? []).length)
  if (await main.getByText(/可商用/).count()) throw new Error("the page still talks about licensing")
  if (said !== 1) throw new Error(`the no-quote reason should appear once on the overview, got ${said}`)
  if (await page.getByRole("region", { name: "走勢圖" }).count()) throw new Error("no price chart without a quote")
  const crumb = await page.getByRole("navigation", { name: "位置" }).textContent()
  if (/Consumer Electronics|[A-Za-z]{4,} [A-Za-z]{4,}/.test(crumb.replace("AAPL", ""))) throw new Error(`breadcrumb shows an English industry: ${crumb}`)
  const position = await page.getByRole("region", { name: /的部位$/ }).textContent()
  if (!/US\$143\.41/.test(position) || /未實現/.test(position)) throw new Error(`US position: cost in US$, no unrealized without a quote: ${position}`)
  await page.goto(base + "/stock/AAPL?tab=valuation", { waitUntil: "networkidle" })
  await page.getByText("沒有報價，算不出估值").waitFor({ timeout: 8000 })
  if (await page.getByRole("region", { name: "殖利率走勢" }).count()) throw new Error("yield trend is price-derived")
  const again = await main.evaluate((el) => (el.textContent.match(/美股沒有報價/g) ?? []).length)
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
  // 資料集依提供機關收合：收著列名稱，展開是每個資料集的完整顯名聲明
  const twse = page.getByRole("button", { name: /^臺灣證券交易所/ })
  await twse.waitFor({ timeout: 8000 })
  if ((await twse.getAttribute("aria-expanded")) !== "false") throw new Error("dataset groups should start collapsed")
  await page.getByText(/上市個股日成交資訊、上市個股日本益比/).waitFor()
  await twse.click()
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
await check("AI 面板：設定頁（展開後）沒有建議 → 輸入框在最上面、下面列最近 3 段對話、提示字不是交易例子；開始對話後輸入框在底部，免責只出現一次", async () => {
  await page.goto(base + "/settings", { waitUntil: "networkidle" })
  // 設定是 AI 沒什麼可說的頁面：面板預設收成窄欄，要用才展開。
  // （前面的檢查留下待簽名的草稿時面板本來就開著——有草稿等簽名就不收；「預設是窄欄」在第三輪的檢查用乾淨的分頁驗證）
  await page.getByText("券商帳戶").first().waitFor({ timeout: 8000 })
  const expand = page.getByRole("button", { name: /^展開 AI 面板/ })
  if (await expand.count()) await expand.click()
  const panel = page.getByRole("complementary", { name: "問 AI" })
  await panel.waitFor({ timeout: 8000 })
  const box = panel.getByLabel("提出問題或下指令")
  const placeholder = (await box.getAttribute("placeholder")) ?? ""
  if (/買|張/.test(placeholder)) throw new Error(`settings placeholder suggests a trade: ${placeholder}`)
  const recent = panel.getByRole("list", { name: "最近的對話" })
  if ((await recent.getByRole("listitem").count()) !== 3) throw new Error(`expected 3 recent threads, got ${await recent.getByRole("listitem").count()}`)
  // 還沒有對話：輸入框在面板最上面（標題列正下方），最近的對話接在它下面；鍵盤順序和畫面順序一樣
  const side = await panel.boundingBox()
  const before = await box.boundingBox()
  const listTop = (await recent.boundingBox()).y
  if (before.y - side.y > 110) throw new Error(`empty panel: composer should sit under the header, is ${Math.round(before.y - side.y)}px down`)
  if (before.y > listTop) throw new Error(`empty panel: composer (${before.y}) should be above the list (${listTop})`)
  const domOrder = await panel.evaluate((el) => {
    const ta = el.querySelector("textarea"), list = el.querySelector('ul[aria-label="最近的對話"]')
    return ta && list ? !!(ta.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING) : null
  })
  if (domOrder !== true) throw new Error("empty panel: the composer should come before the list in the DOM too")
  // 按下最近的一段對話 → 接著那段對話（使用者的話出現在面板裡）；輸入框到面板底部、拿到焦點
  const first = recent.getByRole("button").first()
  const title = ((await first.textContent()) ?? "").trim()
  await first.click()
  await panel.locator("p", { hasText: title }).first().waitFor({ timeout: 8000 })
  if (await panel.getByRole("list", { name: "最近的對話" }).count()) throw new Error("still on the panel home after opening a thread")
  const after = await box.boundingBox()
  if (side.y + side.height - (after.y + after.height) > 90) throw new Error(`conversation: composer should sit at the bottom, ends ${Math.round(side.y + side.height - after.y - after.height)}px above it`)
  const talkTop = (await panel.locator("p", { hasText: title }).first().boundingBox()).y
  if (talkTop > after.y) throw new Error("conversation: the composer should be below the messages")
  if (!(await box.evaluate((el) => el === document.activeElement))) throw new Error("the composer lost focus when it moved to the bottom")
  // 同一段對話再問一題：免責只在最新一則回答下方出現一次
  await box.fill("持股會不會太集中")
  await box.press("Enter")
  await panel.getByText("這題要查網路資料，現在沒辦法。").last().waitFor({ timeout: 8000 })
  await page.waitForTimeout(300)
  const disclaimers = await panel.getByText("AI 回答僅供參考，非投資建議。").count()
  if (disclaimers !== 1) throw new Error(`expected one disclaimer per conversation, got ${disclaimers}`)
  // 新對話：輸入框回到最上面，打到一半的字還在
  await box.fill("打到一半")
  await panel.getByRole("button", { name: "新對話" }).click()
  await panel.getByRole("list", { name: "最近的對話" }).waitFor({ timeout: 5000 })
  const again = await box.boundingBox()
  if (again.y - side.y > 110) throw new Error(`new conversation: composer should be back on top, is ${Math.round(again.y - side.y)}px down`)
  if ((await box.inputValue()) !== "打到一半") throw new Error("the composer lost its text when it moved")
  await box.fill("")
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
  await panel.getByText(/你的均價 US\$[\d,.]+。美股沒有報價，算不出本益比，也沒有河流圖。/).waitFor({ timeout: 8000 })
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
  await page.getByText(/這筆股利是除息日自動入帳的。改了之後不會再自動更新/).waitFor({ timeout: 8000 })
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
  // 分享卡的說明是一句話（「AAPL 沒有報價，本月算不出來。」），不是「本月：…：…」
  const note = (await page.getByText(/本月算不出來。/).first().textContent()) ?? ""
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
  // 資料來源頁：標題和第一個區塊（報價）之間沒有副標
  const subtitle = await page.getByRole("heading", { level: 1, name: "資料來源與授權" }).evaluate((h) => {
    const next = document.querySelector("main h2")
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
  await page.getByRole("tab", { name: "分享", exact: true }).click()
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
  await page.getByRole("tab", { name: /紀錄/ }).click()
  await page.locator(".form-head").filter({ hasText: "商品" }).getByText("數量", { exact: true }).waitFor({ timeout: 8000 })
  if (await page.getByRole("button", { name: "記一筆" }).count()) throw new Error("記一筆 visible in view-as")
  await page.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
  await page.getByText("參考價").first().waitFor({ timeout: 8000 })
  if (await page.getByRole("button", { name: /記一筆|加入觀察/ }).count()) throw new Error("write actions on stock page in view-as")
  await page.goto(base + "/stock/2330.TW?tab=events", { waitUntil: "networkidle" })
  await page.getByRole("radio", { name: "只看爸爸的" }).waitFor({ timeout: 8000 })
  if (await page.getByText(/只看我的|你可領/).count()) throw new Error("「我／你」 wording in view-as")
  await page.goto(base + "/groups", { waitUntil: "networkidle" })
  await page.getByText(/群組是你自己的，結束查看後才能用/).waitFor({ timeout: 8000 })
  await page.goto(base + "/history", { waitUntil: "networkidle" })
  await page.getByText(/紀錄是你自己的，結束查看後才能用/).waitFor({ timeout: 8000 })
  if (await page.locator("main").getByRole("button", { name: "新對話", exact: true }).count()) throw new Error("AI history usable in view-as")
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

// ── 第三輪設計修飾：桌面 ───────────────────────────────────────
// 另開一個乾淨的分頁：前面的檢查留下待簽名的草稿與對話，面板在安靜的頁面會因此開著
const rctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-TW", timezoneId: "Asia/Taipei" })
const rp = await rctx.newPage()
rp.on("console", (m) => m.type() === "error" && errors.push(`${rp.url()} ${m.text()}`))
rp.on("pageerror", (e) => errors.push(`${rp.url()} pageerror ${e.message}`))
await check("AI 面板：安靜的頁面（群組、討論、設定、紀錄、資料來源）預設是窄欄，帳本與個股頁照記住的狀態；換頁時內容的左緣不動", async () => {
  await rp.goto(base + "/", { waitUntil: "networkidle" })
  await rp.evaluate(() => document.documentElement.classList.remove("dark"))
  await rp.getByRole("complementary", { name: "問 AI", exact: true }).waitFor({ timeout: 8000 })
  await rp.getByText("總資產").first().waitFor({ timeout: 8000 })
  const edge = () => rp.evaluate(() => {
    const main = document.getElementById("main")
    const first = main.querySelector("h1:not(.sr-only), p, nav")
    return { left: Math.round(first.getBoundingClientRect().left), mainW: Math.round(main.getBoundingClientRect().width), railW: Math.round(document.querySelector("aside")?.getBoundingClientRect().width ?? 0) }
  })
  const ledger = await edge()
  // 用頂部列的導覽換頁（不重新載入）：群組是窄欄，主欄變寬，但第一行字的左緣和帳本一樣
  await rp.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "群組" }).click()
  await rp.getByRole("heading", { level: 1, name: "群組" }).waitFor({ timeout: 8000 })
  await rp.getByRole("button", { name: "展開 AI 面板" }).waitFor({ timeout: 8000 })
  if (await rp.getByRole("complementary", { name: "問 AI", exact: true }).count()) throw new Error("panel open on a quiet page by default")
  const groups = await edge()
  if (groups.railW !== 56) throw new Error(`rail is ${groups.railW}px`)
  if (groups.mainW <= ledger.mainW) throw new Error(`main column did not widen: ${JSON.stringify({ ledger, groups })}`)
  if (Math.abs(groups.left - ledger.left) > 1) throw new Error(`content left edge jumped between ledger and groups: ${JSON.stringify({ ledger, groups })}`)
  // 討論也是安靜的頁面（AI 不讀討論）：頂部列的第三個分頁，窄欄、左緣不動
  const topNav = await rp.getByRole("navigation", { name: "主要" }).getByRole("link").allTextContents()
  if (topNav.join("・") !== "帳本・市場・群組・討論") throw new Error(`top nav: ${topNav.join("・")}`)
  await rp.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "討論" }).click()
  await rp.getByRole("heading", { level: 1, name: "討論" }).waitFor({ timeout: 8000 })
  await rp.getByText("台積電法說會前，大家怎麼配置？").waitFor({ timeout: 8000 })
  if (await rp.getByRole("complementary", { name: "問 AI", exact: true }).count()) throw new Error("panel open on the discussions page by default")
  const discussions = await edge()
  if (discussions.railW !== 56 || Math.abs(discussions.left - ledger.left) > 1) throw new Error(`discussions page: ${JSON.stringify({ ledger, discussions })}`)
  if ((await rp.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "討論" }).getAttribute("aria-current")) !== "page") throw new Error("討論 is not marked current")
  await rp.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "群組" }).click()
  await rp.getByRole("heading", { level: 1, name: "群組" }).waitFor({ timeout: 8000 })
  // 主欄的寬度沒有轉場（不會邊換頁邊滑動）
  const moving = await rp.evaluate(() => [document.getElementById("main"), document.querySelector("aside")].map((el) => getComputedStyle(el).transitionDuration))
  if (moving.some((d) => d !== "0s")) throw new Error(`main/aside animate: ${moving.join(", ")}`)
  // 在安靜的頁面打開：換到別的安靜頁面也開著；回帳本照帳本的狀態
  await rp.getByRole("button", { name: "展開 AI 面板" }).click()
  await rp.getByRole("complementary", { name: "問 AI", exact: true }).waitFor({ timeout: 8000 })
  await rp.getByRole("link", { name: /家族投資/ }).first().click()
  await rp.getByRole("heading", { level: 1, name: "家族投資" }).waitFor({ timeout: 8000 })
  if (!(await rp.getByRole("complementary", { name: "問 AI", exact: true }).count())) throw new Error("panel collapsed again on the next quiet page")
  await rp.getByRole("button", { name: "收合 AI 面板" }).click()
  await rp.getByRole("button", { name: "展開 AI 面板" }).waitFor({ timeout: 8000 })
  await rp.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "帳本" }).click()
  await rp.getByRole("complementary", { name: "問 AI", exact: true }).waitFor({ timeout: 8000 })
})
await check("AI 面板：開著一段對話時換到安靜的頁面不收起來；紀錄頁的面板不重複列對話；設定頁的頭像有導覽的線", async () => {
  await rp.goto(base + "/", { waitUntil: "networkidle" })
  const panel = rp.getByRole("complementary", { name: "問 AI", exact: true })
  await panel.getByRole("button", { name: "今天誰拖累了我的報酬？" }).click()
  await panel.getByText(/今天拖累最多的是/).waitFor({ timeout: 8000 })
  await rp.getByRole("button", { name: /帳號選單/ }).click()
  await rp.getByRole("menuitem", { name: "設定", exact: true }).click()
  await rp.getByRole("heading", { level: 1, name: "設定" }).waitFor({ timeout: 8000 })
  if (!(await panel.count())) throw new Error("panel collapsed while a conversation is open")
  await panel.getByText(/今天拖累最多的是/).waitFor()
  // 設定頁沒有自己的導覽分頁：頭像下面是導覽的那條線（2px 墨色），「帳本／群組」都沒有標
  const mark = await rp.getByRole("button", { name: /帳號選單/ }).evaluate((el) => ({ active: el.hasAttribute("data-active"), line: getComputedStyle(el).borderBottomWidth, color: getComputedStyle(el).borderBottomColor, ink: getComputedStyle(document.documentElement).getPropertyValue("--ink").trim() }))
  if (!mark.active || mark.line !== "2px" || /rgba\(0, 0, 0, 0\)/.test(mark.color)) throw new Error(`avatar is not marked on /settings: ${JSON.stringify(mark)}`)
  if (await rp.locator('header nav [aria-current="page"]').count()) throw new Error("a nav tab is marked on /settings")
  await panel.getByRole("button", { name: "新對話" }).click()
  // 紀錄頁（用 ⌘K 換頁，不重新載入）：面板開著，但不列「最近的對話」——頁面本身就是清單
  await rp.keyboard.press("Control+k")
  await rp.getByRole("option", { name: "對話紀錄" }).click()
  await rp.locator("main").getByRole("button", { name: "新對話", exact: true }).waitFor({ timeout: 8000 })
  await rp.locator("main").getByRole("list", { name: "對話" }).waitFor({ timeout: 8000 })
  if (!(await panel.count())) throw new Error("panel should still be open (opened on a quiet page)")
  if (await panel.getByRole("list", { name: "最近的對話" }).count()) throw new Error("the panel repeats the conversations the history page lists")
  if (await rp.getByRole("button", { name: /帳號選單/ }).evaluate((el) => el.hasAttribute("data-active"))) throw new Error("avatar marked on /history")
  // 紀錄和設定、資料來源同一個欄寬（816px）
  const measure = async (path, ready) => {
    await rp.goto(base + path, { waitUntil: "networkidle" })
    await rp.getByText(ready).first().waitFor({ timeout: 8000 })
    return rp.evaluate(() => Math.round(document.querySelector("main [class*='max-w-measure']")?.getBoundingClientRect().width ?? 0))
  }
  const widths = [await measure("/history", "對話紀錄"), await measure("/settings", "券商帳戶"), await measure("/data-sources", "授權條款")]
  if (new Set(widths).size !== 1 || widths[0] !== 816) throw new Error(`content measures differ: ${widths.join(" / ")}`)
})
await check("楷體只有一種排法：群組週報、AI 公司簡介和對話裡的回答同一個字級與字距（漢字 −0.06em、數字不拆行）", async () => {
  const voice = async (path, ready) => {
    await rp.goto(base + path, { waitUntil: "networkidle" })
    await rp.getByText(ready).first().waitFor({ timeout: 8000 })
    await rp.waitForTimeout(300)
    return rp.locator("main .ai-voice").first().evaluate((el) => {
      const c = getComputedStyle(el)
      const han = el.querySelector(".kai-han")
      const num = el.querySelector(".kai-num")
      return { family: c.fontFamily.split(",")[0].replace(/["']/g, "").trim(), size: c.fontSize, lh: (parseFloat(c.lineHeight) / parseFloat(c.fontSize)).toFixed(1), han: han ? (parseFloat(getComputedStyle(han).letterSpacing) / parseFloat(c.fontSize)).toFixed(2) : null, numWrap: num ? getComputedStyle(num).whiteSpace : null }
    })
  }
  const digest = await voice("/groups/grp_family?tab=digests", "本週報酬")
  const about = await voice("/stock/6488.TWO", "AI 依公開資料整理")
  for (const [name, v] of [["digest", digest], ["about", about]]) {
    if (v.family !== "TW-Kai" || v.size !== "17px" || v.lh !== "1.8" || v.han !== "-0.06") throw new Error(`${name} kai differs from answers: ${JSON.stringify(v)}`)
  }
  if (digest.numWrap !== "nowrap") throw new Error(`digest numbers can split from their unit: ${JSON.stringify(digest)}`)
})
await check("設定：列上的動作一套語法（文字動作＋一顆外框按鈕，沒有只有圖示的按鈕）；設定與資料來源的區塊標題 20px", async () => {
  await rp.goto(base + "/settings", { waitUntil: "networkidle" })
  const plans = rp.getByRole("region", { name: "定期定額" })
  const remove = plans.getByRole("button", { name: "刪除「元大台灣50」定期定額" })
  await remove.waitFor({ timeout: 8000 })
  const look = await remove.evaluate((el) => ({ text: el.textContent.trim(), icon: !!el.querySelector("svg"), border: getComputedStyle(el).borderTopWidth }))
  if (look.text !== "刪除" || look.icon || look.border !== "1px") throw new Error(`plan delete is not a labelled outline button: ${JSON.stringify(look)}`)
  const iconOnly = await rp.locator("main").evaluate((el) => [...el.querySelectorAll("button")].filter((b) => b.querySelector("svg") && !b.textContent.trim() && b.getAttribute("role") !== "switch").map((b) => b.getAttribute("aria-label")))
  if (iconOnly.length) throw new Error(`icon-only buttons on settings: ${iconOnly.join(", ")}`)
  const view = await rp.getByRole("button", { name: "查看爸爸的資產" }).evaluate((el) => ({ bg: getComputedStyle(el).backgroundColor, border: getComputedStyle(el).borderTopWidth }))
  if (view.bg !== "rgba(0, 0, 0, 0)" || view.border !== "1px") throw new Error(`查看 should be an outline button: ${JSON.stringify(view)}`)
  const sizes = async () => rp.locator("main h2").evaluateAll((els) => els.filter((h) => h.getBoundingClientRect().width > 1).map((h) => `${h.textContent.trim().slice(0, 6)}:${getComputedStyle(h).fontSize}`))
  const settings = await sizes()
  await rp.goto(base + "/data-sources", { waitUntil: "networkidle" })
  await rp.getByText("授權條款").first().waitFor({ timeout: 8000 })
  const sources = await sizes()
  const off = [...settings, ...sources].filter((s) => !s.endsWith(":20px"))
  if (settings.length < 7 || sources.length < 4 || off.length) throw new Error(`section titles are not all 20px: ${off.join(", ") || `${settings.length}/${sources.length} titles`}`)
})
await check("估值河流圖（淺色）：5 階是等比的，最便宜的一階對紙、相鄰兩階都 ≥ 1.3:1", async () => {
  await rp.goto(base + "/stock/2330.TW?tab=valuation", { waitUntil: "networkidle" })
  await rp.evaluate(() => document.documentElement.classList.remove("dark"))
  await rp.getByRole("region", { name: "本益比河流圖" }).waitFor({ timeout: 8000 })
  const ramp = await rp.evaluate(() => {
    const read = (name) => {
      const d = document.createElement("div")
      d.style.color = `var(${name})`
      document.body.appendChild(d)
      const c = getComputedStyle(d).color.match(/\d+/g).slice(0, 3).map(Number)
      d.remove()
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
    }
    const lum = ["--paper", "--band-1", "--band-2", "--band-3", "--band-4", "--band-5"].map(read)
    return lum.slice(1).map((l, i) => +((lum[i] + 0.05) / (l + 0.05)).toFixed(2))
  })
  if (ramp.some((r) => r < 1.3)) throw new Error(`light river ramp steps: ${ramp.join(", ")}`)
  if (Math.max(...ramp) - Math.min(...ramp) > 0.06) throw new Error(`light river ramp is uneven: ${ramp.join(", ")}`)
})
await check("美股總覽：沒有分頁列下面那條只有「近四季 EPS」的細帶，併進「關於」的鍵值格", async () => {
  await rp.goto(base + "/stock/AAPL", { waitUntil: "networkidle" })
  const about = rp.getByRole("region", { name: "關於「Apple」" })
  await about.getByRole("term").getByText("近四季 EPS", { exact: true }).waitFor({ timeout: 8000 })
  if (await rp.getByRole("region", { name: "關鍵數據" }).count()) throw new Error("the lone key strip is still there")
  if ((await rp.locator("main").getByText("近四季 EPS").count()) !== 1) throw new Error("EPS should appear once")
  const cells = await about.locator("dl > div").evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().width)))
  if (cells.length !== 6 || new Set(cells).size !== 1) throw new Error(`About grid should be 6 even cells: ${cells.join(", ")}`)
  // 事件是第一塊：緊接在分頁列下面
  const gap = await rp.evaluate(() => document.getElementById("ov-events").getBoundingClientRect().top - document.getElementById("stock-tabpanel").getBoundingClientRect().top)
  if (gap > 48) throw new Error(`events start ${gap}px below the tab bar`)
})
await check("資料來源：固定一段說明都是收盤價、沒有盤中報價；資料集的連結文字是資料集名稱（沒有「資料集網址」）；全部展開後每一筆顯名聲明都在", async () => {
  await rp.goto(base + "/data-sources", { waitUntil: "networkidle" })
  const quotes = rp.getByRole("region", { name: "報價" })
  await quotes.getByText(/Forliosa 的股價都是收盤價，沒有盤中報價。/).waitFor({ timeout: 8000 })
  await quotes.getByText(/通常是當天晚上到隔天清晨/).waitFor()
  await quotes.getByText(/盤中報價要付費授權，Forliosa 沒有買。/).waitFor()
  const mis = quotes.getByRole("link", { name: /基本市況報導/ })
  if ((await mis.getAttribute("target")) !== "_blank" || !/noopener/.test((await mis.getAttribute("rel")) ?? "") || !/^https:\/\/mis\.twse\.com\.tw\//.test((await mis.getAttribute("href")) ?? "")) throw new Error("基本市況報導 link attributes")
  if (await rp.getByText("資料集網址").count()) throw new Error("generic 資料集網址 links are back")
  await rp.getByRole("button", { name: "全部展開" }).click()
  await rp.getByRole("button", { name: "全部收合" }).waitFor()
  const rows = await rp.locator('main section[aria-labelledby="ds-datasets"] ul:not([hidden]) > li').count()
  const count = Number(((await rp.getByText(/個提供機關・\d+ 個資料集/).textContent()) ?? "").match(/・(\d+) 個資料集/)?.[1])
  if (!count || rows !== count) throw new Error(`expanded rows ${rows} ≠ datasets ${count}`)
  await rp.getByText("中央銀行〈銀行間新臺幣對美元收盤匯率〉（2026），依政府資料開放授權條款第 1 版").waitFor()
  // 連結的文字是資料集的名稱：幾乎每一個都不一樣（同一個資料集用在兩處的只有一兩筆）
  const links = await rp.locator('main section[aria-labelledby="ds-datasets"] ul:not([hidden]) > li p:first-child a').evaluateAll((els) => els.map((a) => a.textContent.trim()))
  if (links.length < count || links.some((t) => !t)) throw new Error(`dataset links: ${links.length} for ${count} datasets`)
  if (new Set(links).size < links.length - 3) throw new Error(`dataset links repeat one label: ${links.length - new Set(links).size} duplicates`)
})
await rctx.close()

// 沒有盤中即時報價：價格標「收盤價・日期」，盤中、收盤後今天的還沒公布時多一行（mock 的 ?market= 旗標；另開一個分頁，不影響其他檢查）
const kctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-TW", timezoneId: "Asia/Taipei" })
const kp = await kctx.newPage()
kp.on("pageerror", (e) => errors.push(`market pageerror ${e.message}`))
kp.on("console", (m) => m.type() === "error" && errors.push(`${kp.url()} ${m.text()}`))
await check("收盤價的標示（預設：最新的收盤價已經進來）：個股頁只標「收盤價・11/12（四）」沒有說明；帳本「11/12 收盤」「今日」", async () => {
  await kp.goto(base + "/stock/2330.TW?market=closed", { waitUntil: "networkidle" })
  const head = kp.locator("main header").first()
  await head.getByText("收盤價", { exact: true }).waitFor({ timeout: 8000 })
  if (!((await head.textContent()) ?? "").includes("收盤價・11/12（四）")) throw new Error(`price label: ${await head.textContent()}`)
  if (await kp.getByText(/盤中不更新|還沒公布/).count()) throw new Error("note shown although the latest close is in")
  if (await kp.getByRole("link", { name: /到證交所看即時報價/ }).count()) throw new Error("TWSE link shown although the latest close is in")
  if (/延遲|盤中・/.test((await kp.locator("main").textContent()) ?? "")) throw new Error("the page suggests delayed or intraday quotes")
  await kp.goto(base + "/", { waitUntil: "networkidle" })
  await kp.getByText("11/12 收盤", { exact: true }).waitFor({ timeout: 8000 })
  await kp.locator("main dt").getByText("今日", { exact: true }).waitFor()
  const table = kp.getByRole("table", { name: "持倉" })
  await table.getByRole("columnheader", { name: "今日漲跌" }).waitFor({ timeout: 8000 })
  await table.getByRole("columnheader", { name: "今日損益" }).waitFor()
  await table.getByRole("columnheader", { name: "收盤價" }).waitFor()
})
await check("收盤價的標示（盤中）：個股頁一行「盤中不更新…」＋到證交所的連結（另開新視窗）；帳本「11/12 收盤・盤中不更新」，「今日」換成「11/12」", async () => {
  await kp.goto(base + "/stock/2330.TW?market=open", { waitUntil: "networkidle" })
  // 一行「盤中不更新・到證交所看即時報價 ↗」：不重複上一行已經寫的日期，而且真的排在同一行
  const note = kp.locator("main header p", { hasText: "盤中不更新" })
  await note.waitFor({ timeout: 8000 })
  const noteText = ((await note.textContent()) ?? "").replace(/\s+/g, "")
  if (!/^盤中不更新・到證交所看即時報價/.test(noteText) || /11\/12/.test(noteText)) throw new Error(`market note: ${noteText}`)
  const noteBox = await note.evaluate((el) => ({ h: el.getBoundingClientRect().height, lh: parseFloat(getComputedStyle(el).lineHeight) }))
  if (noteBox.h > noteBox.lh * 1.5) throw new Error(`the market note wraps to more than one line: ${JSON.stringify(noteBox)}`)
  // 大字旁的漲跌是 11/12 那天的：和帳本一樣標日期
  await kp.locator("main header").getByText("11/12 漲跌", { exact: true }).waitFor({ timeout: 8000 })
  const link = kp.getByRole("link", { name: /^到證交所看即時報價/ })
  const attrs = { href: await link.getAttribute("href"), target: await link.getAttribute("target"), rel: await link.getAttribute("rel") }
  if (attrs.href !== "https://mis.twse.com.tw/stock/detail-item?id=tse_2330.tw&ex=tse&lang=zhHant" || attrs.target !== "_blank" || attrs.rel !== "noopener noreferrer") throw new Error(`TWSE link: ${JSON.stringify(attrs)}`)
  if (!(await link.locator("svg").count())) throw new Error("external link without ↗")
  if (!((await kp.locator("main header").first().textContent()) ?? "").includes("收盤價・11/12（四）")) throw new Error("price label missing")
  // 這一行只在價格旁出現一次，其他地方不重複
  if ((await kp.getByText(/盤中不更新/).count()) !== 1) throw new Error("the note is repeated")
  // 上櫃 ETF、上櫃股票也一樣；美股維持「沒有報價」
  await kp.goto(base + "/stock/6488.TWO", { waitUntil: "networkidle" })
  await kp.locator("main header p", { hasText: "盤中不更新" }).waitFor({ timeout: 8000 })
  const otc = await kp.getByRole("link", { name: /^到證交所看即時報價/ }).getAttribute("href")
  if (otc !== "https://mis.twse.com.tw/stock/detail-item?id=otc_6488.tw&ex=otc&lang=zhHant") throw new Error(`TPEx link: ${otc}`)
  await kp.goto(base + "/stock/AAPL", { waitUntil: "networkidle" })
  await kp.getByText("沒有報價", { exact: true }).waitFor({ timeout: 8000 })
  if (await kp.getByText(/盤中不更新/).count()) throw new Error("US stock shows the Taiwan market note")
  await kp.goto(base + "/", { waitUntil: "networkidle" })
  await kp.getByText("11/12 收盤・盤中不更新", { exact: true }).waitFor({ timeout: 8000 })
  await kp.locator("main dt").getByText("11/12", { exact: true }).waitFor()
  if (await kp.locator("main dt").getByText("今日", { exact: true }).count()) throw new Error("hero still says 今日 for yesterday's close")
  const table = kp.getByRole("table", { name: "持倉" })
  await table.getByRole("columnheader", { name: "11/12 漲跌" }).waitFor({ timeout: 8000 })
  await table.getByRole("columnheader", { name: "11/12 損益" }).waitFor()
  if (await table.getByRole("columnheader", { name: /今日/ }).count()) throw new Error("holdings header still says 今日")
})
await check("收盤價的標示（收盤後、今天的還沒公布）：一行說明、沒有連結；帳本「11/12 收盤・今天的還沒公布」；切回預設後說明消失", async () => {
  await kp.goto(base + "/stock/2330.TW?market=pending", { waitUntil: "networkidle" })
  await kp.getByText("今天的收盤價還沒公布", { exact: true }).waitFor({ timeout: 8000 })
  await kp.locator("main header").getByText("11/12 漲跌", { exact: true }).waitFor({ timeout: 8000 })
  if (await kp.getByRole("link", { name: /到證交所看即時報價/ }).count()) throw new Error("TWSE link shown after the close")
  await kp.goto(base + "/", { waitUntil: "networkidle" })
  await kp.getByText("11/12 收盤・今天的還沒公布", { exact: true }).waitFor({ timeout: 8000 })
  await kp.getByRole("table", { name: "持倉" }).getByRole("columnheader", { name: "11/12 漲跌" }).waitFor({ timeout: 8000 })
  await kp.goto(base + "/stock/2330.TW?market=closed", { waitUntil: "networkidle" })
  await kp.getByText("參考價").first().waitFor({ timeout: 8000 })
  await kp.waitForTimeout(400)
  if (await kp.getByText(/盤中不更新|還沒公布/).count()) throw new Error("note still shown after switching back")
})
await kctx.close()

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
await check("登入頁：登入失敗的錯誤代碼有說明（不分 Google、Discord）", async () => {
  await ip.goto(base + "/login?error=oauth_email_conflict", { waitUntil: "networkidle" })
  await ip.getByRole("alert").filter({ hasText: "這個 Email 已經連結到另一個登入帳號，請用原本那個帳號登入。" }).waitFor({ timeout: 8000 })
  await ip.goto(base + "/login?error=oauth_denied", { waitUntil: "networkidle" })
  await ip.getByRole("alert").filter({ hasText: "你按了取消，所以沒有登入。" }).waitFor({ timeout: 8000 })
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
  // 「問 AI」平常只有框線：框線是往內畫的 1px（inset），不是浮起來的陰影
  if (bar.askRadius !== "0px" || !(bar.askShadow === "none" || /inset/.test(bar.askShadow)) || !bar.askInside || bar.askH < 44 || bar.askW < 44) throw new Error(`問 AI is not a square box inside the bar: ${JSON.stringify(bar)}`)
  if (bar.tabs.map((t) => t.text).join("・") !== "帳本・市場・群組・討論") throw new Error(`tabs: ${JSON.stringify(bar.tabs)}`)
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
await check("手機：群組八個分頁（多了「討論」）每個 ≥ 44×44；iPhone 15 上八個剛好放得下、沒有淡出，更窄的手機才捲動、選到的分頁會捲進來", async () => {
  const tabsOf = (p) =>
    p.getByRole("tablist", { name: "群組內容" }).evaluate((el) => {
      const c = el.getBoundingClientRect()
      const tabs = [...el.querySelectorAll('[role="tab"]')].map((t) => ({ r: t.getBoundingClientRect(), text: t.textContent, selected: t.getAttribute("aria-selected") === "true" }))
      return {
        names: tabs.map((t) => t.text).join("・"),
        fadeStart: el.hasAttribute("data-overflow-start"),
        fadeEnd: el.hasAttribute("data-overflow-end"),
        // 沒有完整露出來的分頁（被捲出去，或只露出一部分）
        cut: tabs.filter((t) => t.r.left < c.left - 0.5 || t.r.right > c.right + 0.5).map((t) => t.text),
        small: tabs.filter((t) => t.r.height < 44 || t.r.width < 44).map((t) => `${t.text} ${Math.round(t.r.width)}×${Math.round(t.r.height)}`),
        // 選取中的分頁完整露出來，而且不在淡出的那 28px 裡
        selectedClear: tabs.filter((t) => t.selected).every((t) => t.r.left >= c.left - 0.5 + (el.hasAttribute("data-overflow-start") ? 27 : 0) && t.r.right <= c.right + 0.5 - (el.hasAttribute("data-overflow-end") ? 27 : 0)),
        overflow: el.scrollWidth - el.clientWidth,
        pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      }
    })
  // 從第一個分頁進來：iPhone 15（內容寬 353px）八個分頁（各 44px）剛好放得下，沒有被切到的、也沒有淡出
  await m.goto(base + "/groups/grp_family", { waitUntil: "networkidle" })
  await m.getByRole("tab", { name: "排行" }).waitFor({ timeout: 8000 })
  await m.waitForTimeout(300)
  const first = await tabsOf(m)
  if (first.names !== "排行・動態・討論・持股・週報・分享・成員・頻道") throw new Error(`group tabs: ${first.names}`)
  if (first.small.length) throw new Error(`group tabs under 44×44: ${first.small.join(" | ")}`)
  if (first.cut.length || first.fadeEnd || first.fadeStart || first.overflow > 0) throw new Error(`on an iPhone 15 all eight tabs must fit: ${JSON.stringify(first)}`)
  if (first.pageOverflow > 0) throw new Error(`the page scrolls sideways: ${JSON.stringify(first)}`)
  // 直接打開「成員」：選取中的分頁完整看得到
  await m.goto(base + "/groups/grp_family?tab=members", { waitUntil: "networkidle" })
  await m.getByText("邀請連結").first().waitFor({ timeout: 8000 })
  await m.waitForTimeout(300)
  const members = await tabsOf(m)
  if (!members.selectedClear || members.pageOverflow > 0) throw new Error(`active tab not scrolled into view: ${JSON.stringify(members)}`)
  // 選「頻道」：捲進來，完整看得到
  await m.getByRole("tab", { name: "頻道" }).click()
  await m.locator('[role="tab"][aria-selected="true"]').filter({ hasText: "頻道" }).waitFor({ timeout: 8000 })
  await m.waitForTimeout(500)
  const channels = await tabsOf(m)
  if (!channels.selectedClear || channels.cut.includes("頻道")) throw new Error(`「頻道」 is not scrolled into view when selected: ${JSON.stringify(channels)}`)
  // 夠寬的手機（430px）：八個分頁平分整列，一次看得到全部，沒有淡出
  const wide = await browser.newContext({ viewport: { width: 430, height: 932 }, hasTouch: true, isMobile: true, locale: "zh-TW", timezoneId: "Asia/Taipei" })
  try {
    const w = await wide.newPage()
    await w.goto(base + "/groups/grp_family?tab=members", { waitUntil: "networkidle" })
    await w.getByText("邀請連結").first().waitFor({ timeout: 8000 })
    await w.waitForTimeout(300)
    const at430 = await tabsOf(w)
    if (at430.cut.length || at430.fadeStart || at430.fadeEnd || at430.small.length || at430.pageOverflow > 0) throw new Error(`430px: group tabs do not all fit: ${JSON.stringify(at430)}`)
  } finally {
    await wide.close()
  }
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
  const buttons = [dialog.getByRole("button", { name: "新對話" }), dialog.getByRole("button", { name: "對話紀錄", exact: true }), dialog.getByRole("button", { name: "關閉" })]
  const looks = await Promise.all(
    buttons.map((b) => b.evaluate((el) => { const c = getComputedStyle(el); return [c.width, c.height, c.borderRadius, c.backgroundColor, c.color].join(" ") })),
  )
  if (new Set(looks).size !== 1) throw new Error(`header buttons differ: ${looks.join(" | ")}`)
  if (!looks[0].startsWith("44px 44px")) throw new Error(`header buttons not 44px: ${looks[0]}`)
  await dialog.getByRole("button", { name: "關閉" }).click()
})
await check("手機：AI 對話紀錄從「問 AI」的時鐘進去（底部列沒有「紀錄」分頁）→ 紀錄頁有看得到的標題；底部的「討論」到討論清單", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  if (await m.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "對話紀錄" }).count()) throw new Error("the bottom bar still has a 對話紀錄 tab")
  await m.getByRole("button", { name: /^問 AI/ }).click()
  await m.getByRole("dialog").getByRole("button", { name: "對話紀錄", exact: true }).click()
  await m.waitForURL(/\/history$/, { timeout: 8000 })
  await m.locator("main").getByRole("button", { name: "新對話", exact: true }).waitFor({ timeout: 8000 })
  await m.getByRole("dialog").waitFor({ state: "detached", timeout: 5000 })
  // 沒有分頁告訴你這是哪一頁：標題在手機也看得到
  const title = await m.getByRole("heading", { level: 1, name: "對話紀錄" }).boundingBox()
  if (!title || title.height < 20 || title.width < 20) throw new Error(`the history page has no visible title on mobile: ${JSON.stringify(title)}`)
  // 從紀錄挑一段對話：回到「問 AI」
  await m.getByRole("list", { name: "對話" }).getByRole("button").first().click()
  await m.getByRole("dialog").getByRole("button", { name: "關閉" }).click()
  // 底部列的「討論」
  await m.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "討論" }).click()
  await m.waitForURL(/\/discussions$/, { timeout: 8000 })
  await m.getByRole("heading", { level: 1, name: "討論" }).waitFor({ timeout: 8000 })
  await m.getByText("台積電法說會前，大家怎麼配置？").waitFor({ timeout: 8000 })
  if ((await m.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "討論" }).getAttribute("aria-current")) !== "page") throw new Error("討論 tab is not current")
})

// ── 第三輪設計修飾：手機 ───────────────────────────────────────
/** 觸控目標普查：每個看得到、按得到的控制項，實際可按的範圍（用 elementFromPoint 量）寬和高都要 ≥ 44px */
const smallTargets = (p) =>
  p.evaluate(() => {
    const sel = 'a[href], button, [role=button], [role=tab], [role=switch], [role=radio], input:not([type=hidden]), select, textarea, summary'
    const out = []
    for (const el of document.querySelectorAll(sel)) {
      const r0 = el.getBoundingClientRect()
      if (r0.width < 2 || r0.height < 2) continue
      const cs = getComputedStyle(el)
      if (cs.visibility === "hidden" || cs.pointerEvents === "none" || el.disabled) continue
      el.scrollIntoView({ block: "center", inline: "nearest" })
      const r = el.getBoundingClientRect()
      const cx = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 2)
      const cy = r.top + r.height / 2
      const hit = (x, y) => {
        const e = document.elementFromPoint(x, y)
        if (!e) return false
        if (e === el || el.contains(e)) return true
        const l = e.closest("label")
        return !!(l && (l.control === el || l.contains(el)))
      }
      // 換行成兩行的連結：外框的中心點不在連結上，量不出來（每一行各自夠高），略過
      if (!hit(cx, cy)) continue
      let up = 0, down = 0, left = 0, right = 0
      while (up < 60 && hit(cx, cy - up - 1)) up++
      while (down < 60 && hit(cx, cy + down + 1)) down++
      while (left < 60 && hit(cx - left - 1, cy)) left++
      while (right < 60 && hit(cx + right + 1, cy)) right++
      const w = left + right + 1, h = up + down + 1
      if (w < 44 || h < 44) out.push(`${(el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 16)} ${w}×${h}`)
    }
    window.scrollTo(0, 0)
    return out
  })
await check("手機：標題列的放大鏡（44px）打開滿版的搜尋——輸入框在最上面、結果是格線列；搜尋「台積」進入個股頁", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  const open = m.getByRole("button", { name: "搜尋股票", exact: true })
  const size = await open.boundingBox()
  if (size.width < 44 || size.height < 44) throw new Error(`search button ${size.width}×${size.height}`)
  await open.click()
  const dialog = m.getByRole("dialog", { name: "搜尋股票與功能" })
  await dialog.waitFor({ timeout: 8000 })
  const sheet = await dialog.evaluate((el) => {
    const r = el.getBoundingClientRect()
    const input = el.querySelector("input").getBoundingClientRect()
    const c = getComputedStyle(el)
    return { top: r.top, left: r.left, w: r.width, h: r.height, vw: innerWidth, vh: window.visualViewport?.height ?? innerHeight, radius: c.borderRadius, inputTop: input.top, inputH: input.height, focused: document.activeElement === el.querySelector("input"), fontSize: parseFloat(getComputedStyle(el.querySelector("input")).fontSize) }
  })
  if (sheet.top !== 0 || sheet.left !== 0 || sheet.w !== sheet.vw || Math.abs(sheet.h - sheet.vh) > 1 || sheet.radius !== "0px") throw new Error(`search is not a full-height sheet: ${JSON.stringify(sheet)}`)
  // 輸入框在最上面（螢幕鍵盤蓋住的是下半部）、已經有焦點、16px 以上（iOS 不放大頁面）
  if (sheet.inputTop > 20 || sheet.inputH < 44 || !sheet.focused || sheet.fontSize < 16) throw new Error(`search input: ${JSON.stringify(sheet)}`)
  await dialog.getByRole("combobox").fill("台積")
  const hit = dialog.getByRole("option", { name: /2330/ })
  await hit.waitFor({ timeout: 8000 })
  const row = await hit.evaluate((el) => ({ h: el.getBoundingClientRect().height, w: el.getBoundingClientRect().width, radius: getComputedStyle(el).borderRadius, rule: getComputedStyle(el).borderBottomWidth }))
  if (row.h < 44 || row.w !== sheet.vw || row.radius !== "0px" || row.rule !== "1px") throw new Error(`search result is not a full-bleed ruled row: ${JSON.stringify(row)}`)
  await hit.click()
  await m.waitForURL(/\/stock\/2330\.TW/)
  if (await m.getByRole("dialog", { name: "搜尋股票與功能" }).count()) throw new Error("search sheet still open after picking a result")
  // 關閉鈕
  await m.getByRole("button", { name: "搜尋股票", exact: true }).click()
  await m.getByRole("dialog", { name: "搜尋股票與功能" }).getByRole("button", { name: "關閉搜尋" }).click()
  await m.getByRole("dialog", { name: "搜尋股票與功能" }).waitFor({ state: "detached", timeout: 5000 })
})
await check("手機：底部列的分頁從內容的左緣開始（第一個字和它上面的線都在 20px），每個分頁的可按範圍 ≥ 44×44", async () => {
  await m.goto(base + "/", { waitUntil: "networkidle" })
  await m.getByText("總資產").first().waitFor({ timeout: 8000 })
  const bar = await m.evaluate(() => {
    const nav = document.querySelector('.dock nav[aria-label="主要"]')
    const gutter = document.querySelector("#main p, #main h1:not(.sr-only)").getBoundingClientRect().left
    const tabs = [...nav.querySelectorAll("a")].map((a) => {
      const label = a.querySelector("span")
      const l = label.getBoundingClientRect()
      const r = a.getBoundingClientRect()
      const range = document.createRange()
      range.selectNodeContents(label)
      const text = range.getBoundingClientRect()
      return { text: a.textContent, hitW: r.width, hitH: r.height, labelLeft: text.left, lineLeft: l.left, lineW: l.width, textW: text.width, line: getComputedStyle(label).borderTopWidth, lineColor: getComputedStyle(label).borderTopColor, current: a.getAttribute("aria-current") }
    })
    const ask = document.querySelector(".dock .ask-box").getBoundingClientRect()
    return { gutter, tabs, askRight: ask.right, vw: innerWidth }
  })
  const first = bar.tabs[0]
  if (Math.abs(first.labelLeft - bar.gutter) > 0.5 || Math.abs(first.lineLeft - bar.gutter) > 0.5) throw new Error(`first tab is not on the content gutter: ${JSON.stringify(bar)}`)
  if (Math.abs(first.lineW - first.textW) > 1 || first.line !== "2px" || /rgba\(0, 0, 0, 0\)/.test(first.lineColor)) throw new Error(`the indicator is not a 2px line as wide as the label: ${JSON.stringify(first)}`)
  if (bar.tabs.some((t) => t.hitW < 44 || t.hitH < 44)) throw new Error(`tab targets: ${JSON.stringify(bar.tabs)}`)
  if (Math.abs(bar.vw - bar.askRight - bar.gutter) > 0.5) throw new Error(`問 AI is not on the right gutter: ${JSON.stringify(bar)}`)
})
// ── 市場頁（`/market`）：收盤後的指數、AI 收盤重點、類股、排行、重大訊息 ──
await check("市場頁（桌面）：導覽標「市場」、指數帶日期、AI 收盤重點是鉛筆字並附來源、排行連到個股頁、重大訊息可展開；沒有橫向溢出", async () => {
  await page.goto(base + "/market", { waitUntil: "networkidle" })
  await page.getByRole("heading", { level: 1, name: "市場" }).waitFor({ timeout: 8000 })
  if ((await page.title()) !== "市場｜Forliosa") throw new Error(`title: ${await page.title()}`)
  const nav = page.getByRole("navigation", { name: "主要" })
  if ((await nav.getByRole("link", { name: "市場" }).getAttribute("aria-current")) !== "page") throw new Error("市場 is not marked current")
  const cells = await page.getByRole("list", { name: "指數與匯率" }).getByRole("listitem").allInnerTexts()
  if (cells.length < 3 || !/加權指數/.test(cells[0]) || !/\d{1,2}\/\d{1,2}/.test(cells[0]) || !/%/.test(cells[0])) throw new Error(`index cells: ${JSON.stringify(cells)}`)
  if (await page.getByText(/即時|盤中報價/).count()) throw new Error("the market page must not claim live data")
  const summary = page.locator("section", { has: page.getByRole("heading", { name: "收盤重點" }) })
  const voice = await summary.locator(".ai-voice").evaluateAll((els) => els.map((el) => ({ font: getComputedStyle(el).fontFamily, size: parseFloat(getComputedStyle(el).fontSize) })))
  if (voice.length < 3 || voice.some((v) => !/Kai|楷/i.test(v.font) || v.size < 17)) throw new Error(`summary is not in the AI voice: ${JSON.stringify(voice)}`)
  const sources = await summary.getByRole("link").evaluateAll((els) => els.map((a) => ({ target: a.target, rel: a.rel, href: a.href })))
  if (sources.length < 3 || sources.some((a) => a.target !== "_blank" || !/noopener/.test(a.rel) || !/^https:/.test(a.href))) throw new Error(`summary sources: ${JSON.stringify(sources)}`)
  const sectors = page.locator("section", { has: page.getByRole("heading", { name: "類股" }) })
  const pcts = await sectors.locator("li:not([aria-hidden])").evaluateAll((els) => els.filter((li) => li.getBoundingClientRect().height > 0).map((li) => { const m = li.textContent.match(/([\d.]+)%/); return (li.textContent.includes("▼") ? -1 : 1) * parseFloat(m[1]) }))
  if (pcts.length < 20 || pcts.some((v, i) => i > 0 && v > pcts[i - 1] + 1e-9)) throw new Error(`sectors are not sorted high to low: ${JSON.stringify(pcts)}`)
  const movers = page.locator("section", { has: page.getByRole("heading", { name: "排行" }) })
  const lists = await movers.getByRole("list").evaluateAll((els) => els.filter((el) => el.getBoundingClientRect().height > 0).length)
  if (lists !== 3) throw new Error(`desktop shows ${lists} ranking lists, want 3 side by side`)
  if (await movers.getByText(/元大台灣50|國泰永續高股息/).count()) throw new Error("ETFs are ranked")
  const ann = page.locator("section", { has: page.getByRole("heading", { name: "重大訊息" }) })
  const before = await ann.getByRole("link").count()
  await ann.getByRole("button", { name: /^再看 \d+ 則$/ }).click()
  if ((await ann.getByRole("link").count()) <= before) throw new Error("「再看」did not show more announcements")
  const flow = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
  if (flow.sw > flow.cw) throw new Error(`horizontal overflow: ${JSON.stringify(flow)}`)
  await movers.getByRole("link", { name: /台積電/ }).first().click()
  await page.waitForURL(/\/stock\/2330\.TW/, { timeout: 8000 })
})
await check("市場頁（手機）：四個分頁＋「問 AI」在 393px 與 320px 都放得下、每個可按範圍 ≥ 44px；類股先列頭尾、排行一次一張；不橫向溢出", async () => {
  for (const [name, options] of [["iPhone 15", pw.devices["iPhone 15"]], ["320px", { viewport: { width: 320, height: 640 }, hasTouch: true, isMobile: true, deviceScaleFactor: 2 }]]) {
    const c = await browser.newContext({ ...options, locale: "zh-TW", timezoneId: "Asia/Taipei" })
    const p = await c.newPage()
    try {
      await p.goto(base + "/market", { waitUntil: "networkidle" })
      await p.getByRole("heading", { name: "收盤重點" }).waitFor({ timeout: 8000 })
      const bar = await p.evaluate(() => {
        const nav = document.querySelector('.dock nav[aria-label="主要"]')
        const ask = document.querySelector(".dock .ask-box").getBoundingClientRect()
        const tabs = [...nav.querySelectorAll("a")].map((a) => { const r = a.getBoundingClientRect(); return { text: a.textContent.trim(), left: r.left, right: r.right, w: r.width, h: r.height, lines: (() => { const range = document.createRange(); range.selectNodeContents(a.querySelector("span")); return Math.round(range.getBoundingClientRect().height / parseFloat(getComputedStyle(a).lineHeight)) })(), current: a.getAttribute("aria-current") } })
        return { tabs, askLeft: ask.left, askRight: ask.right, vw: innerWidth, sw: document.documentElement.scrollWidth }
      })
      if (bar.tabs.map((t) => t.text).join("・") !== "帳本・市場・群組・討論") throw new Error(`${name} tabs: ${JSON.stringify(bar.tabs)}`)
      if (bar.tabs.some((t) => t.w < 44 || t.h < 44 || t.lines > 1)) throw new Error(`${name} tab targets: ${JSON.stringify(bar.tabs)}`)
      if (bar.tabs.at(-1).right > bar.askLeft + 0.5 || bar.askRight > bar.vw || bar.sw > bar.vw) throw new Error(`${name}: the bottom bar does not fit: ${JSON.stringify(bar)}`)
      if (bar.tabs.filter((t) => t.current === "page").map((t) => t.text).join() !== "市場") throw new Error(`${name} current tab: ${JSON.stringify(bar.tabs)}`)
      const sectors = p.locator("section", { has: p.getByRole("heading", { name: "類股" }) })
      const visible = () => sectors.locator("li:not([aria-hidden])").evaluateAll((els) => els.filter((li) => li.getBoundingClientRect().height > 0).length)
      if ((await visible()) !== 10) throw new Error(`${name}: collapsed sectors show ${await visible()} rows, want 10`)
      await sectors.getByRole("button", { name: /^全部 \d+ 個類股$/ }).click()
      if ((await visible()) < 20) throw new Error(`${name}: 「全部」did not list every sector`)
      const movers = p.locator("section", { has: p.getByRole("heading", { name: "排行" }) })
      const shown = () => movers.getByRole("list").evaluateAll((els) => els.filter((el) => el.getBoundingClientRect().height > 0).length)
      if ((await shown()) !== 1) throw new Error(`${name}: ${await shown()} ranking lists are visible, want one at a time`)
      await movers.getByRole("radio", { name: "成交量" }).click()
      await movers.getByText(/張$/).first().waitFor({ timeout: 4000 })
      const small = await p.evaluate(() => [...document.querySelectorAll("#main a, #main button")].filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && (r.height < 44 || r.width < 44) }).map((el) => `${el.textContent.trim().slice(0, 12)} ${Math.round(el.getBoundingClientRect().width)}×${Math.round(el.getBoundingClientRect().height)}`))
      if (small.length) throw new Error(`${name}: touch targets under 44px: ${small.join("、")}`)
      const flow = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
      if (flow.sw > flow.cw) throw new Error(`${name}: horizontal overflow ${JSON.stringify(flow)}`)
    } finally {
      await c.close()
    }
  }
})
await check("手機：動態、成員、設定、紀錄、帳本的控制項可按範圍都 ≥ 44×44；表情是 4px 方肩的小格、留言框沒有拖曳把手", async () => {
  for (const [path, ready] of [
    ["/groups/grp_family?tab=feed", "加入了群組"],
    ["/groups/grp_family?tab=digests", "本週報酬"],
    ["/groups/grp_family/members/usr_dad", "總損益"],
    ["/settings", "授權給你的人"],
    ["/history", "新對話"],
    ["/", "總資產"],
    ["/?view=dividends", "已入帳"],
    ["/stock/2330.TW", "參考價"],
  ]) {
    await m.goto(base + path, { waitUntil: "networkidle" })
    await m.getByText(ready).first().waitFor({ timeout: 8000 })
    await m.waitForTimeout(500)
    const small = await smallTargets(m)
    if (small.length) throw new Error(`${path}: ${small.length} targets under 44px — ${small.slice(0, 6).join(" | ")}`)
  }
  await m.goto(base + "/groups/grp_family?tab=feed", { waitUntil: "networkidle" })
  const dad = m.getByRole("listitem").filter({ hasText: /爸爸\s*買進\s*台積電/ }).first()
  const chip = await dad.getByRole("button", { name: /^讚 \d/ }).evaluate((el) => {
    const box = el.querySelector("span")
    const c = getComputedStyle(box)
    return { radius: c.borderTopLeftRadius, border: c.borderTopWidth, h: box.getBoundingClientRect().height }
  })
  if (chip.radius !== "4px" || chip.border !== "1px") throw new Error(`reaction chip is not a square 4px chip: ${JSON.stringify(chip)}`)
  const pills = await m.locator("main").evaluate((el) => [...el.querySelectorAll("button, button *")].filter((n) => parseFloat(getComputedStyle(n).borderTopLeftRadius) > 8 && n.getBoundingClientRect().width > 0).length)
  if (pills) throw new Error(`${pills} pill-shaped controls in the feed`)
  await dad.getByRole("button", { name: /^留言/ }).click()
  const grip = await dad.getByRole("textbox", { name: "留言", exact: true }).evaluate((el) => getComputedStyle(el).resize)
  if (grip !== "none") throw new Error(`comment box resize: ${grip}`)
})
await check("手機：股利列的每股金額都看得到（不被截斷成「每股 …」）；長名稱時金額換到下一行", async () => {
  await m.goto(base + "/?view=dividends", { waitUntil: "networkidle" })
  const received = m.locator("section", { has: m.locator("#div-received") })
  await received.getByText(/^每股 /).first().waitFor({ timeout: 8000 })
  const amounts = await received.getByText(/^每股 /).evaluateAll((els) =>
    els.map((el) => {
      const r = el.getBoundingClientRect()
      const row = el.closest("li").getBoundingClientRect()
      const clipper = el.closest(".truncate")
      return { text: el.textContent, clipped: !!clipper || el.scrollWidth > el.clientWidth + 1, inside: r.left >= row.left - 0.5 && r.right <= row.right + 0.5, lines: Math.round(r.height / parseFloat(getComputedStyle(el).lineHeight)) }
    }),
  )
  if (amounts.length < 8) throw new Error(`expected the received rows, got ${amounts.length}`)
  const bad = amounts.filter((a) => a.clipped || !a.inside || a.lines !== 1)
  if (bad.length) throw new Error(`per-share amounts clipped: ${JSON.stringify(bad.slice(0, 3))}`)
  if (await m.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)) throw new Error("dividends page scrolls sideways")
})
await check("手機：鍵值格每一列都排滿（沒有落單的半列）；資料來源頁收合後不到原本的一半長、長網址不撐寬頁面", async () => {
  for (const sym of ["2330.TW", "0050.TW", "6488.TWO", "2317.TW", "AAPL"]) {
    await m.goto(base + `/stock/${sym}`, { waitUntil: "networkidle" })
    await m.getByRole("region", { name: /^關於/ }).waitFor({ timeout: 8000 })
    await m.waitForTimeout(400)
    const half = await m.evaluate(() =>
      [...document.querySelectorAll("main dl")].filter((el) => getComputedStyle(el).display === "grid" && el.children.length >= 2).flatMap((el) => {
        const W = el.getBoundingClientRect().width
        const rows = new Map()
        for (const c of el.children) {
          const r = c.getBoundingClientRect()
          if (!r.width) continue
          const k = Math.round(r.top)
          rows.set(k, (rows.get(k) ?? 0) + r.width)
        }
        return [...rows.values()].filter((w) => w < W * 0.8).map((w) => `${Math.round(w)}/${Math.round(W)}`)
      }),
    )
    if (half.length) throw new Error(`${sym}: half rows in a key grid: ${half.join(", ")}`)
  }
  await m.goto(base + "/data-sources", { waitUntil: "networkidle" })
  await m.getByText("授權條款").first().waitFor({ timeout: 8000 })
  const page1 = await m.evaluate(() => ({ h: document.documentElement.scrollHeight, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, generic: document.body.textContent.includes("資料集網址") }))
  if (page1.h > 5200 || page1.overflow > 0 || page1.generic) throw new Error(`data-sources on a phone: ${JSON.stringify(page1)}`)
  // 網址只在分隔符號後面斷行：每一行都以 / . - ? & = # _ 結尾（最後一行除外）
  const breaks = await m.locator('main section[aria-labelledby="ds-license"] a').evaluateAll((links) =>
    links.flatMap((a) => {
      const range = document.createRange()
      const lines = []
      const walker = document.createTreeWalker(a, NodeFilter.SHOW_TEXT)
      let node, lastTop = null, cur = ""
      while ((node = walker.nextNode())) {
        if (node.parentElement.classList.contains("sr-only")) continue
        for (let i = 0; i < node.length; i++) {
          range.setStart(node, i)
          range.setEnd(node, i + 1)
          const top = Math.round(range.getBoundingClientRect().top)
          if (lastTop !== null && top > lastTop + 4) { lines.push(cur); cur = "" }
          cur += node.data[i]
          lastTop = top
        }
      }
      return lines
    }),
  )
  const midWord = breaks.filter((line) => !/[/.\-?&=#_]$/.test(line))
  if (midWord.length) throw new Error(`URLs break mid-word: ${midWord.join(" | ")}`)
})
await check("手機：帳本主數字旁的時間一行放得下（盤中的寫法最長）；「今日」換成日期後表頭也是一行", async () => {
  const mk = await browser.newContext({ ...pw.devices["iPhone 15"], locale: "zh-TW", timezoneId: "Asia/Taipei" })
  try {
    const p = await mk.newPage()
    await p.goto(base + "/?market=pending", { waitUntil: "networkidle" })
    const asOf = p.getByText("11/12 收盤・今天的還沒公布", { exact: true })
    await asOf.waitFor({ timeout: 8000 })
    const line = await asOf.evaluate((el) => {
      const label = el.parentElement
      const r = el.getBoundingClientRect()
      const first = label.firstElementChild.getBoundingClientRect()
      return { sameLine: Math.abs((r.top + r.bottom) / 2 - (first.top + first.bottom) / 2) < 6, right: r.right, vw: innerWidth }
    })
    if (!line.sameLine || line.right > line.vw - 19) throw new Error(`hero as-of wraps or overflows on a phone: ${JSON.stringify(line)}`)
    const head = p.getByText("收盤價・11/12 漲跌", { exact: true })
    await head.waitFor({ timeout: 8000 })
    if ((await head.evaluate((el) => el.getBoundingClientRect().height)) > 24) throw new Error("holdings header wraps")
    await p.goto(base + "/stock/2330.TW?market=open", { waitUntil: "networkidle" })
    // 手機上也是一行：「盤中不更新・到證交所看即時報價 ↗」（連結觸控時 44px 高，所以量的是字有沒有換行）
    const note = p.locator("main header p", { hasText: "盤中不更新" })
    await note.waitFor({ timeout: 8000 })
    const link = p.getByRole("link", { name: /^到證交所看即時報價/ })
    if ((await link.boundingBox()).height < 44) throw new Error("TWSE link under 44px on touch")
    const tops = await note.evaluate((el) => [...el.querySelectorAll("span:not(.sr-only), a")].map((x) => { const r = x.getBoundingClientRect(); return Math.round((r.top + r.bottom) / 2) }))
    if (Math.max(...tops) - Math.min(...tops) > 4) throw new Error(`the market note wraps on a phone: ${JSON.stringify(tops)}`)
    await p.locator("main header").getByText("11/12 漲跌", { exact: true }).waitFor({ timeout: 8000 })
    if (await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)) throw new Error("stock page scrolls sideways with the market note")
  } finally {
    await mk.close()
  }
})
await check("手機：「問 AI」平常是石墨淡底＋框線＋石墨灰的字（淺色、深色都是），有草稿等簽名才是實心；帳本頁的筆數只寫一次", async () => {
  const dk = await browser.newContext({ ...pw.devices["iPhone 15"], colorScheme: "dark", locale: "zh-TW", timezoneId: "Asia/Taipei" })
  try {
    const p = await dk.newPage()
    await p.goto(base + "/", { waitUntil: "networkidle" })
    await p.getByText("總資產").first().waitFor({ timeout: 8000 })
    const look = (name) =>
      p.getByRole("button", { name }).evaluate((el) => {
        const c = getComputedStyle(el)
        const v = (n) => { const d = document.createElement("div"); d.style.color = `var(${n})`; document.body.appendChild(d); const out = getComputedStyle(d).color; d.remove(); return out }
        return { bg: c.backgroundColor, color: c.color, frame: c.boxShadow, inner: getComputedStyle(el, "::after").borderTopWidth, text: el.textContent.trim(), ai: v("--ai"), wash: v("--ai-wash"), rule: v("--ai-rule"), paper: v("--paper"), dark: document.documentElement.classList.contains("dark") }
      })
    // 格子的底色與字色有 120ms 的過渡：連讀兩次一樣才算（不讀到過渡中間的顏色）
    const settled = async (name) => {
      let prev = await look(name)
      for (let i = 0; i < 20; i++) {
        await p.waitForTimeout(60)
        const next = await look(name)
        if (next.bg === prev.bg && next.color === prev.color) return next
        prev = next
      }
      return prev
    }
    const rest = await settled("問 AI")
    if (!rest.dark) throw new Error("not in dark mode")
    if (rest.bg !== rest.wash || rest.color !== rest.ai || !rest.frame.includes(rest.rule) || rest.inner !== "1px") throw new Error(`dark resting 問 AI is not the outlined box: ${JSON.stringify(rest)}`)
    // 寫一份草稿（不簽名），關掉問 AI
    await p.getByRole("button", { name: "問 AI", exact: true }).click()
    const box = p.getByLabel(/搜尋股票、提問/)
    await box.fill("買 0050 2 張 52.4")
    await box.press("Enter")
    await p.getByText(/NT\$104,800/).first().waitFor({ timeout: 8000 })
    await p.getByRole("dialog").getByRole("button", { name: "關閉" }).click()
    const pending = await settled("問 AI（待簽名 1 筆）")
    if (pending.bg !== pending.ai || pending.color !== pending.paper) throw new Error(`pending 問 AI is not the solid block: ${JSON.stringify(pending)}`)
    // 帳本頁：筆數寫在分段下面那一條，格子裡只有「問 AI」
    if (pending.text !== "問 AI") throw new Error(`the box repeats the count on the ledger: ${pending.text}`)
    const strips = await p.locator("main").getByText(/待簽名 1 筆/).evaluateAll((els) => els.filter((el) => el.getBoundingClientRect().width > 0).length)
    if (strips !== 1) throw new Error(`expected one visible 待簽名 on the ledger, got ${strips}`)
    // 其他頁面沒有那一條：格子裡寫筆數
    await p.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "群組" }).click()
    await p.getByRole("heading", { level: 1, name: "群組" }).waitFor({ timeout: 8000 })
    const elsewhere = await settled("問 AI（待簽名 1 筆）")
    if (!/待簽名 1 筆/.test(elsewhere.text) || elsewhere.bg !== elsewhere.ai) throw new Error(`the box should carry the count off the ledger: ${JSON.stringify(elsewhere)}`)
  } finally {
    await dk.close()
  }
  // 淺色也一樣：平常只有框線（灰色的實心格看起來像停用的按鈕）
  const lt = await browser.newContext({ ...pw.devices["iPhone 15"], colorScheme: "light", locale: "zh-TW", timezoneId: "Asia/Taipei" })
  try {
    const p = await lt.newPage()
    await p.goto(base + "/", { waitUntil: "networkidle" })
    await p.getByText("總資產").first().waitFor({ timeout: 8000 })
    const light = await p.getByRole("button", { name: "問 AI", exact: true }).evaluate((el) => {
      const c = getComputedStyle(el)
      const v = (n) => { const d = document.createElement("div"); d.style.color = `var(${n})`; document.body.appendChild(d); const out = getComputedStyle(d).color; d.remove(); return out }
      return { bg: c.backgroundColor, color: c.color, frame: c.boxShadow, ai: v("--ai"), wash: v("--ai-wash"), rule: v("--ai-rule"), dark: document.documentElement.classList.contains("dark") }
    })
    if (light.dark) throw new Error("expected light mode")
    if (light.bg !== light.wash || light.color !== light.ai || !light.frame.includes(light.rule)) throw new Error(`light resting 問 AI is not the outlined box: ${JSON.stringify(light)}`)
  } finally {
    await lt.close()
  }
})

// ── 討論串（2026-11-13）──────────────────────────────────────
// 每個檢查用全新的瀏覽器狀態；mock 的資料在記憶體裡，同一個流程只用站內導覽（重新載入會回到示範資料）
const fresh = async (options, fn) => {
  const c = await browser.newContext({ locale: "zh-TW", timezoneId: "Asia/Taipei", ...options })
  const p = await c.newPage()
  p.on("console", (msg) => msg.type() === "error" && errors.push(`${p.url()} ${msg.text()}`))
  p.on("pageerror", (e) => errors.push(`${p.url()} pageerror ${e.message}`))
  try {
    await fn(p)
  } finally {
    await c.close()
  }
}
const DESKTOP = { viewport: { width: 1440, height: 900 } }
const DISCLAIMER = "使用者言論，不代表本站立場，也不是投資建議。"
const overflowX = (p) => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)

await check("討論（沒登入）：公開清單與主題不用登入就能讀，外殼只有字標（連到首頁）、「討論」與「登入」；群組主題看不到；「登入後發言」→ 登入 → 回到這個主題、可以回覆", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/discussions?auth=signed-out", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "討論" }).waitFor({ timeout: 8000 })
    await p.getByText("台積電法說會前，大家怎麼配置？").waitFor({ timeout: 8000 })
    if (!/\/discussions$/.test(new URL(p.url()).pathname)) throw new Error(`redirected to ${p.url()}`)
    const shell = await p.evaluate(() => ({
      // 外殼的導覽只有「討論」一項（選取中）；字標連到首頁（沒登入是介紹頁）
      nav: [...document.querySelectorAll('nav[aria-label="主要"] a')].map((a) => `${a.getAttribute("href")}:${a.getAttribute("aria-current") ?? ""}`).join(","),
      wordmark: document.querySelector('a[aria-label="Forliosa 首頁"]').getAttribute("href"),
      dock: !!document.querySelector(".dock"),
      panel: !!document.querySelector("aside"),
      ledgerLinks: [...document.querySelectorAll("a:not([aria-label='Forliosa 首頁'])")].map((a) => a.getAttribute("href")).filter((h) => h === "/" || /^\/(stock|groups|settings|history|admin)/.test(h ?? "")),
      rows: document.querySelectorAll('ul[aria-label="主題"] > li').length,
      wordmarkLeft: Math.round(document.querySelector('a[aria-label="Forliosa 首頁"]').getBoundingClientRect().left),
      titleLeft: Math.round(document.querySelector("#main h1").getBoundingClientRect().left),
    }))
    if (shell.nav !== "/discussions:page" || shell.wordmark !== "/" || shell.dock || shell.panel || shell.ledgerLinks.length) throw new Error(`signed-out shell is not minimal: ${JSON.stringify(shell)}`)
    if (shell.rows !== 8) throw new Error(`expected the 8 public topics, got ${shell.rows}`)
    if (shell.wordmarkLeft !== shell.titleLeft) throw new Error(`wordmark and content are not on one left edge: ${JSON.stringify(shell)}`)
    if (await p.getByText("我把聯發科的交易補記好了").count()) throw new Error("a group topic is listed for a signed-out visitor")
    if (await p.getByRole("radiogroup", { name: "範圍" }).count()) throw new Error("scope filter shown when signed out")
    await p.getByText(DISCLAIMER).waitFor()
    const login = p.getByRole("banner").getByRole("link", { name: "登入", exact: true })
    const border = await login.evaluate((el) => getComputedStyle(el).borderTopColor)
    if (/rgba\(0, 0, 0, 0\)/.test(border)) throw new Error("the 登入 button has no visible outline")
    // 「登入」在內容的欄寬裡：右緣和下面的內容（主題清單）對齊，不是掛在畫面最右邊
    const edges = await p.evaluate(() => ({
      login: Math.round(document.querySelector("header a[href^='/login']").getBoundingClientRect().right),
      list: Math.round(document.querySelector('ul[aria-label="主題"]').getBoundingClientRect().right),
    }))
    if (Math.abs(edges.login - edges.list) > 1) throw new Error(`登入 is not on the content's right edge: ${JSON.stringify(edges)}`)
    // 免責旁邊一行：Forliosa 是什麼＋「登入」
    const about = p.locator("main p", { hasText: "Forliosa 是股票帳本" })
    await about.waitFor({ timeout: 8000 })
    // 連結在句子下面自己一列（「登入」「服務條款」「隱私權政策」），不夾在句子裡
    const aboutLinks = about.locator("xpath=following-sibling::p[1]")
    if (!/^\/login/.test((await aboutLinks.getByRole("link", { name: "登入", exact: true }).getAttribute("href")) ?? "")) throw new Error("the about line has no 登入 link")
    if (await about.getByRole("link").count()) throw new Error("links are back inside the about sentence")
    // 主題頁（站內導覽）：內文、回覆、被隱藏的回覆只有說明、表情只有計數、股票是純文字
    await p.getByRole("link", { name: "台積電法說會前，大家怎麼配置？" }).click()
    await p.getByRole("heading", { level: 1, name: "台積電法說會前，大家怎麼配置？" }).waitFor({ timeout: 8000 })
    await p.getByText("比重超過自己睡得著的程度就調，不用等法說會。").waitFor({ timeout: 8000 })
    await p.getByText("這則內容已被站方隱藏。", { exact: true }).waitFor()
    if (await p.getByText(/保證獲利/).count()) throw new Error("hidden reply body leaked to a visitor")
    if (await p.getByRole("button", { name: /加表情|^檢舉|^刪除|更多動作/ }).count()) throw new Error("write actions shown to a signed-out visitor")
    await p.locator("main p", { hasText: "Forliosa 是股票帳本" }).locator("xpath=following-sibling::p[1]").getByRole("link", { name: "登入", exact: true }).waitFor()
    if (await p.getByRole("textbox").count()) throw new Error("a composer is shown to a signed-out visitor")
    if (await p.locator("main").getByRole("link", { name: /台積電 2330/ }).count()) throw new Error("stock tags are links for a signed-out visitor")
    await p.getByText(DISCLAIMER).waitFor()
    // 群組的主題：找不到（不透露存在）
    await p.goto(base + "/discussions/top_g_dca", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "找不到這個主題" }).waitFor({ timeout: 8000 })
    // 登入後發言 → 登入頁 → 回到主題（已登入：一般的外殼、回覆區是選暱稱或回覆框）
    await p.goto(base + "/discussions/top_p_tsmc", { waitUntil: "networkidle" })
    await p.getByRole("link", { name: "登入後發言" }).click()
    await p.waitForURL(/\/login\?next=%2Fdiscussions%2Ftop_p_tsmc/, { timeout: 8000 })
    await p.getByRole("button", { name: "用 Discord 登入" }).click()
    await p.waitForURL(/\/discussions\/top_p_tsmc/, { timeout: 8000 })
    await p.getByRole("form", { name: "選公開暱稱" }).waitFor({ timeout: 8000 })
    await p.getByRole("navigation", { name: "主要" }).waitFor({ timeout: 8000 })
  })
})

await check("討論（主要流程）：選公開暱稱 → 發公開主題（標記股票）→ 馬上回覆被頻率限制擋下（說幾秒後）→ 等到了再送 → 按表情 → 檢舉別人的回覆 → 管理後台隱藏它", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/discussions", { waitUntil: "networkidle" })
    await p.getByText("台積電法說會前，大家怎麼配置？").waitFor({ timeout: 8000 })
    // 篩選「公開」後開新主題：預先選好公開
    await p.getByRole("radiogroup", { name: "範圍" }).getByRole("radio", { name: "公開" }).click()
    await p.getByRole("link", { name: "開新主題" }).click()
    await p.waitForURL(/\/discussions\/new\?scope=public/, { timeout: 8000 })
    if (!(await p.getByRole("radio", { name: /^公開/ }).isChecked())) throw new Error("公開 is not preselected")
    // 還沒有公開暱稱：先選（保留字就地擋下、重複的由伺服器擋下）
    const prompt = p.getByRole("form", { name: "選公開暱稱" })
    await prompt.getByRole("textbox").fill("站方小幫手")
    await prompt.getByRole("button", { name: "用這個暱稱" }).click()
    await prompt.getByText("公開暱稱不能含「站方」。").waitFor({ timeout: 5000 })
    await prompt.getByRole("textbox").fill("阿土伯")
    await prompt.getByRole("button", { name: "用這個暱稱" }).click()
    await prompt.getByText("這個暱稱已經有人用了，換一個試試。").waitFor({ timeout: 5000 })
    await prompt.getByRole("textbox").fill("煙霧測試員")
    await prompt.getByRole("button", { name: "用這個暱稱" }).click()
    await p.getByText("公開暱稱是「煙霧測試員」").waitFor({ timeout: 8000 })
    await prompt.waitFor({ state: "detached", timeout: 5000 })
    await p.getByRole("form", { name: "新主題" }).getByText("以「煙霧測試員」公開發言").waitFor({ timeout: 5000 })
    // 空的不送出
    await p.getByRole("button", { name: "發表", exact: true }).click()
    await p.getByText("請寫標題。").waitFor({ timeout: 5000 })
    await p.getByText("請寫內文。").waitFor()
    await p.getByLabel("標題").fill("煙霧測試：年底要不要再平衡？")
    await p.getByLabel("內文").fill("今年股票漲很多，比重跑掉了。\n\n大家是固定每年調一次，還是差太多才調？\n參考：https://www.twse.com.tw/，謝謝。")
    await p.getByPlaceholder("代號或名稱，例如 2330、台積").fill("2330")
    await p.getByRole("option", { name: /2330/ }).first().click()
    await p.getByRole("list", { name: "已標記的股票" }).getByText("台積電").waitFor({ timeout: 5000 })
    await p.getByRole("button", { name: "發表", exact: true }).click()
    // 新主題記著是從「公開」的清單來的（← 討論 回去時篩選還在）
    await p.waitForURL(/\/discussions\/top_\d+\?scope=public$/, { timeout: 8000 })
    await p.getByRole("heading", { level: 1, name: "煙霧測試：年底要不要再平衡？" }).waitFor({ timeout: 8000 })
    await p.getByText("已發表").waitFor({ timeout: 8000 })
    // 內文：換行保留、網址是另開新視窗的連結（後面的全形逗號不算在網址裡）
    const link = p.locator("article").getByRole("link", { name: /^https:\/\/www\.twse\.com\.tw\// })
    const a = await link.evaluate((el) => ({ href: el.getAttribute("href"), target: el.target, rel: el.rel, text: el.firstChild.textContent, pre: getComputedStyle(el.parentElement).whiteSpace }))
    if (a.href !== "https://www.twse.com.tw/" || a.target !== "_blank" || a.rel !== "nofollow ugc noopener noreferrer" || a.text !== "https://www.twse.com.tw/" || !/pre-wrap/.test(a.pre)) throw new Error(`body link: ${JSON.stringify(a)}`)
    if ((await p.locator("article").getByRole("link", { name: /台積電 2330/ }).getAttribute("href")) !== "/stock/2330.TW") throw new Error("tagged stock is not a link to the stock page")
    await p.getByText(DISCLAIMER).waitFor()
    // 自己的主題：「更多動作」裡可以刪除、不能檢舉
    await p.getByRole("button", { name: "主題的更多動作" }).click()
    await p.getByRole("menuitem", { name: "刪除" }).waitFor({ timeout: 5000 })
    if (await p.getByRole("menuitem", { name: /檢舉/ }).count()) throw new Error("can report my own topic")
    await p.keyboard.press("Escape")
    await p.getByRole("menu").waitFor({ state: "detached", timeout: 5000 })
    // 馬上回覆：任兩則公開發言至少間隔 10 秒 → 就地說幾秒後可以再送，內容留著
    const box = p.getByRole("textbox", { name: "回覆內容" })
    await box.fill("自己先回：我是每年年底調一次。")
    await p.getByRole("button", { name: "回覆", exact: true }).click()
    const limited = p.getByRole("alert").filter({ hasText: /發言太頻繁，\d+ 秒後可以再送出。內容還在。/ })
    await limited.waitFor({ timeout: 8000 })
    if ((await box.inputValue()) !== "自己先回：我是每年年底調一次。") throw new Error("the reply text was lost on a rate limit")
    const seconds = Number(/(\d+) 秒後/.exec(await limited.textContent())[1])
    if (!(seconds >= 1 && seconds <= 10)) throw new Error(`retry after ${seconds}s`)
    await p.waitForTimeout(seconds * 1000 + 300)
    await p.getByRole("button", { name: "回覆", exact: true }).click()
    const mine = p.getByRole("list", { name: "回覆" }).getByRole("listitem").filter({ hasText: "自己先回：我是每年年底調一次。" })
    await mine.waitFor({ timeout: 8000 })
    await mine.getByText("煙霧測試員（你）").waitFor()
    await p.getByText("已送出回覆").waitFor({ timeout: 8000 })
    if ((await box.inputValue()) !== "") throw new Error("the composer was not cleared after posting")
    // 表情：加一個讚，立刻是自己按過的小格；再按一次收回
    await p.locator("article > div").getByRole("button", { name: "加表情" }).first().click()
    await p.getByRole("button", { name: "讚", exact: true }).click()
    const chip = p.getByRole("button", { name: "讚 1，你按過" })
    await chip.waitFor({ timeout: 5000 })
    if ((await chip.getAttribute("aria-pressed")) !== "true") throw new Error("reaction chip not pressed")
    // 回清單（站內導覽）：新的主題在最上面、寫著我的暱稱與 1 則回覆
    await p.getByRole("navigation", { name: "位置" }).getByRole("link", { name: "討論" }).click()
    const first = p.getByRole("list", { name: "主題" }).getByRole("listitem").first()
    await first.getByText("煙霧測試：年底要不要再平衡？").waitFor({ timeout: 8000 })
    const meta = await first.locator(".meta-line > div > *").allTextContents()
    if (meta.join("|") !== "煙霧測試員（你）|1 則回覆|台積電 2330") throw new Error(`meta line: ${meta.join("|")}`)
    if (!/scope=public/.test(p.url())) throw new Error(`← 討論 lost the list's filter: ${p.url()}`)
    // 檢舉別人的回覆
    await p.getByRole("link", { name: "0050 要不要改買 006208？" }).click()
    await p.getByRole("heading", { level: 1, name: "0050 要不要改買 006208？" }).waitFor({ timeout: 8000 })
    await p.getByRole("button", { name: "定期定額派的回覆的更多動作" }).click()
    if (await p.getByRole("menuitem", { name: "刪除" }).count()) throw new Error("can delete someone else's public reply")
    await p.getByRole("menuitem", { name: "檢舉…" }).click()
    const dialog = p.getByRole("dialog")
    await dialog.getByRole("button", { name: "送出檢舉" }).click()
    await dialog.getByText("請選一個理由。").waitFor({ timeout: 5000 })
    await dialog.getByRole("radio", { name: "廣告或洗版" }).check()
    await dialog.getByLabel("補充說明（選填）").fill("煙霧測試的檢舉")
    await dialog.getByRole("button", { name: "送出檢舉" }).click()
    await p.getByText("已收到檢舉").waitFor({ timeout: 8000 })
    await dialog.waitFor({ state: "detached", timeout: 5000 })
    // 管理後台（⌘K 的「管理後台」→「討論」分頁）：那一則在待處理的最上面 → 隱藏（先確認）→ 離開待處理
    await p.getByRole("button", { name: /搜尋股票/ }).click()
    await p.getByRole("option", { name: "管理後台" }).click()
    await p.waitForURL(/\/admin$/, { timeout: 8000 })
    await p.getByRole("navigation", { name: "管理後台" }).getByRole("link", { name: "討論" }).click()
    await p.waitForURL(/\/admin\/discussions$/, { timeout: 8000 })
    const open = p.getByRole("list", { name: "待處理的檢舉" })
    const row = open.getByRole("listitem").filter({ hasText: "我是舊的不動、新的錢改買。" })
    await row.waitFor({ timeout: 8000 })
    await row.getByText(/定期定額派・檢舉 1 次：廣告或洗版 1/).waitFor()
    await row.getByText("「煙霧測試的檢舉」").waitFor()
    await row.getByRole("button", { name: /^隱藏/ }).click()
    const confirm = p.getByRole("alertdialog")
    await confirm.getByText("隱藏這則回覆？").waitFor({ timeout: 5000 })
    await confirm.getByRole("button", { name: "隱藏", exact: true }).click()
    await p.getByText("已隱藏這則回覆").waitFor({ timeout: 8000 })
    await row.waitFor({ state: "detached", timeout: 8000 })
    await p.getByRole("radio", { name: "已處理" }).click()
    await p.getByRole("list", { name: "已處理的檢舉" }).getByRole("listitem").filter({ hasText: "我是舊的不動、新的錢改買。" }).getByText("已隱藏").waitFor({ timeout: 8000 })
    // 回到那個主題：那一則寫著已被站方隱藏（我是站方管理員，所以還看得到原文）
    await p.getByRole("list", { name: "已處理的檢舉" }).getByRole("listitem").filter({ hasText: "我是舊的不動、新的錢改買。" }).getByRole("link", { name: /看主題/ }).click()
    await p.getByRole("heading", { level: 1, name: "0050 要不要改買 006208？" }).waitFor({ timeout: 8000 })
    await p.getByRole("list", { name: "回覆" }).getByText("這則內容已被站方隱藏，其他人看不到下面的原文。").waitFor({ timeout: 8000 })
  })
})

await check("討論（群組）：群組主題只在「全部」與那個群組的篩選裡，公開的篩選看不到；在群組裡用顯示名稱發言、不需要公開暱稱、沒有檢舉；刪除可以復原、通知結束才真的刪掉", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/discussions", { waitUntil: "networkidle" })
    const scope = p.getByRole("radiogroup", { name: "範圍" })
    await scope.getByRole("radio", { name: "家族投資" }).waitFor({ timeout: 8000 })
    await p.getByText("我把聯發科的交易補記好了").waitFor({ timeout: 8000 })
    const rows = () => p.locator('ul[aria-label="主題"] > li').count()
    if ((await rows()) !== 12) throw new Error(`全部: ${await rows()} rows`)
    await scope.getByRole("radio", { name: "公開" }).click()
    await p.getByText("我把聯發科的交易補記好了").waitFor({ state: "detached", timeout: 8000 })
    if ((await rows()) !== 8) throw new Error(`公開: ${await rows()} rows`)
    await scope.getByRole("radio", { name: "家族投資" }).click()
    await p.getByText("我把聯發科的交易補記好了").waitFor({ timeout: 8000 })
    await p.getByText("台積電法說會前，大家怎麼配置？").waitFor({ state: "detached", timeout: 8000 })
    if ((await rows()) !== 3) throw new Error(`家族投資: ${await rows()} rows`)
    if (await p.getByText(DISCLAIMER).count()) throw new Error("the public disclaimer is shown on group-only content")
    // 排序：最新主題（記在網址）
    await p.getByRole("radiogroup", { name: "排序" }).getByRole("radio", { name: "最新主題" }).click()
    await p.waitForURL(/sort=new/, { timeout: 8000 })
    await p.locator(".form-head").getByText("發表", { exact: true }).waitFor({ timeout: 8000 })
    // 群組主題：用顯示名稱、頭像；沒有公開暱稱也能回覆；沒有檢舉
    await p.getByRole("link", { name: "這個月的定期定額，大家扣了嗎？" }).click()
    await p.getByRole("heading", { level: 1, name: "這個月的定期定額，大家扣了嗎？" }).waitFor({ timeout: 8000 })
    await p.getByText("已離開的成員").waitFor({ timeout: 8000 })
    // 群組範圍沒有檢舉：別人的回覆的「更多動作」裡只有「刪除」（我是這個群組的擁有者）
    await p.getByRole("button", { name: /回覆的更多動作$/ }).first().click()
    await p.getByRole("menuitem", { name: "刪除" }).waitFor({ timeout: 5000 })
    if (await p.getByRole("menuitem", { name: /檢舉/ }).count()) throw new Error("group content can be reported")
    await p.keyboard.press("Escape")
    await p.getByRole("menu").waitFor({ state: "detached", timeout: 5000 })
    if (await p.getByText(DISCLAIMER).count()) throw new Error("the public disclaimer is shown on a group topic")
    // 作者那一行的群組名稱是連到群組「討論」分頁的連結
    if ((await p.locator("article header").getByRole("link", { name: "家族投資" }).getAttribute("href")) !== "/groups/grp_family?tab=discussions") throw new Error("the group name is not a link to the group's discussions")
    const form = p.getByRole("form", { name: "回覆這個主題" })
    await form.getByText("以「示範使用者」在「家族投資」發言").waitFor({ timeout: 8000 })
    const box = form.getByRole("textbox", { name: "回覆內容" })
    const before = await box.evaluate((el) => ({ h: el.getBoundingClientRect().height, resize: getComputedStyle(el).resize }))
    await box.fill("我這個月也扣了。\n\n下個月想加碼一點。\n\n再想想。\n\n先這樣。")
    const after = await box.evaluate((el) => el.getBoundingClientRect().height)
    if (before.resize !== "none" || after <= before.h) throw new Error(`the reply box should grow with its content and have no resize grip: ${JSON.stringify({ before, after })}`)
    await form.getByRole("button", { name: "回覆", exact: true }).click()
    const mine = p.getByRole("list", { name: "回覆" }).getByRole("listitem").filter({ hasText: "我這個月也扣了。" })
    await mine.waitFor({ timeout: 8000 })
    await mine.getByText("示範使用者（你）").waitFor()
    // 刪除：不先確認——那一則立刻不見、回覆數少一，通知附「復原」；「刪除」是墨色，不是紅色
    const count = () => p.locator("#topic-replies").locator("xpath=..").getByText(/^\d+ 則$/).textContent()
    const beforeCount = await count()
    const remove = async () => {
      await mine.getByRole("button", { name: /更多動作$/ }).click()
      const item = p.getByRole("menuitem", { name: "刪除" })
      await item.waitFor({ timeout: 5000 })
      const tone = await item.evaluate((el) => {
        const v = (n) => { const d = document.createElement("div"); d.style.color = `var(${n})`; document.body.appendChild(d); const out = getComputedStyle(d).color; d.remove(); return out }
        return { color: getComputedStyle(el).color, red: v("--red") }
      })
      if (tone.color === tone.red) throw new Error(`the delete item is red: ${JSON.stringify(tone)}`)
      await item.click()
    }
    await remove()
    if (await p.getByRole("alertdialog").count()) throw new Error("deleting a reply still asks for confirmation")
    await mine.waitFor({ state: "detached", timeout: 5000 })
    // 焦點不掉回頁首：移到旁邊的一則回覆（沒有就回覆框）
    await p.waitForTimeout(250)
    const focus = await p.evaluate(() => { const a = document.activeElement; return a === document.body ? "body" : a?.id?.startsWith("reply-") ? "reply" : a?.tagName === "TEXTAREA" ? "composer" : (a?.tagName ?? "none") })
    if (focus !== "reply" && focus !== "composer") throw new Error(`focus after deleting a reply is on ${focus}`)
    const toast = p.locator("[data-sonner-toast]").filter({ hasText: "已刪除回覆" })
    await toast.waitFor({ timeout: 5000 })
    if ((await count()) === beforeCount) throw new Error("the reply count did not change after deleting")
    // 復原：回到原位、回覆數也回來
    await toast.getByRole("button", { name: "復原" }).click()
    await mine.waitFor({ timeout: 5000 })
    if ((await count()) !== beforeCount) throw new Error(`undo did not restore the count: ${await count()} vs ${beforeCount}`)
    await toast.waitFor({ state: "detached", timeout: 8000 })
    // 再刪一次、不復原：通知結束之後真的刪掉（重新讀取後還是不在）
    await remove()
    await mine.waitFor({ state: "detached", timeout: 5000 })
    await toast.waitFor({ timeout: 5000 })
    // 可以復原的時間是 10 秒
    await toast.waitFor({ state: "detached", timeout: 16000 })
    await p.waitForTimeout(600)
    if (await mine.count()) throw new Error("the reply came back after the undo window")
    if ((await count()) === beforeCount) throw new Error("the reply count came back after the undo window")
    // ← 回到清單：篩選（家族投資）與排序（最新主題）都還在
    await p.getByRole("navigation", { name: "位置" }).getByRole("link", { name: "討論" }).click()
    await p.waitForURL(/\/discussions\?scope=group&group_id=grp_family&sort=new$/, { timeout: 8000 })
    if (!(await p.getByRole("radiogroup", { name: "範圍" }).getByRole("radio", { name: "家族投資" }).isChecked())) throw new Error("the list forgot its filter")
  })
})

await check("分頁標題：每一頁自己的名字在前、站名在後（個股是名稱＋代號、公開主題是主題的標題）；手機的通知在底部列上方", async () => {
  await fresh(DESKTOP, async (p) => {
    const want = [
      ["/", "帳本｜Forliosa"],
      ["/stock/2330.TW", "台積電 2330｜Forliosa"],
      ["/groups", "群組｜Forliosa"],
      ["/groups/grp_family", "家族投資｜Forliosa"],
      ["/discussions", "討論｜Forliosa"],
      ["/discussions/top_p_tsmc", "台積電法說會前，大家怎麼配置？｜Forliosa"],
      ["/settings", "設定｜Forliosa"],
      ["/history", "對話紀錄｜Forliosa"],
      ["/data-sources", "資料來源與授權｜Forliosa"],
      ["/terms", "服務條款｜Forliosa"],
      ["/no-such-page", "找不到這個頁面｜Forliosa"],
    ]
    for (const [path, title] of want) {
      await p.goto(base + path, { waitUntil: "networkidle" })
      await p.waitForFunction((t) => document.title === t, title, { timeout: 8000 }).catch(async () => { throw new Error(`${path}: title is “${await p.title()}”, want “${title}”`) })
    }
  })
  await fresh({ ...pw.devices["iPhone 15"] }, async (p) => {
    await p.goto(base + "/settings", { waitUntil: "networkidle" })
    await p.getByRole("region", { name: "帳號與資料" }).getByRole("button", { name: "匯出", exact: true }).click()
    const toast = p.locator("[data-sonner-toast]").filter({ hasText: "已下載匯出檔" })
    await toast.waitFor({ timeout: 8000 })
    await p.waitForTimeout(500)
    const box = await toast.boundingBox()
    const dock = await p.locator(".dock").boundingBox()
    if (box.y < 300 || box.y + box.height > dock.y) throw new Error(`phone toast should sit just above the bottom bar: toast ${Math.round(box.y)}–${Math.round(box.y + box.height)}, bar top ${Math.round(dock.y)}`)
    // 打開刪除帳號的對話框：通知先收掉，不蓋在對話框上
    await p.getByRole("button", { name: "刪除帳號…" }).click()
    await p.getByRole("alertdialog").or(p.getByRole("dialog")).first().waitFor({ timeout: 5000 })
    await toast.waitFor({ state: "detached", timeout: 3000 })
  })
})
await check("首頁（沒登入）：是簡短的介紹頁，不是登入頁——一句話、三個標「示範資料」的畫面（帳本・個股・問 AI）、頁尾條款；「登入」→ 登入頁 → 帳本；其他頁面照舊導到登入頁", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/?auth=signed-out", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "股票帳本" }).waitFor({ timeout: 8000 })
    // 沒登入的狀態記在 sessionStorage：再開一次乾淨的網址（「登入」才不會帶著 ?auth=…）
    await p.goto(base + "/", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "股票帳本" }).waitFor({ timeout: 8000 })
    if (new URL(p.url()).pathname !== "/") throw new Error(`the home page redirected to ${p.url()}`)
    if ((await p.title()) !== "Forliosa") throw new Error(`home page title: ${await p.title()}`)
    if (await p.getByRole("button", { name: /^用 (Google|Discord) 登入$/ }).count()) throw new Error("the sign-in buttons are on the home page")
    const home = await p.evaluate(() => {
      const figs = [...document.querySelectorAll("#main figure")]
      const caps = figs.map((f) => f.querySelector("figcaption").getBoundingClientRect())
      return {
        h1: document.querySelectorAll("h1").length,
        titles: figs.map((f) => f.querySelector("h2")?.textContent.trim()).join("|"),
        tags: figs.map((f) => f.querySelectorAll("figcaption .demo-tag").length).join(""),
        described: figs.every((f) => (f.querySelector("figcaption .sr-only")?.textContent ?? "").startsWith("示範畫面")),
        // 示範畫面裡沒有可以按、可以 Tab 到的東西，也不讀給螢幕報讀器
        hidden: figs.every((f) => f.querySelector(":scope > [aria-hidden='true']")),
        controls: document.querySelectorAll("#main figure a, #main figure button, #main figure input, #main figure [tabindex]").length,
        // 三個標題坐在同一條印刷線上：同一個高度、欄與欄之間沒有縫
        tops: [...new Set(caps.map((r) => Math.round(r.bottom)))].length,
        seams: caps.slice(1).map((r, i) => Math.round(r.left - caps[i].right)).join(","),
        // 三欄的內容一樣寬
        widths: [...new Set(figs.map((f) => Math.round(f.querySelector(":scope > [aria-hidden]").firstElementChild.getBoundingClientRect().width)))].length,
        nav: [...document.querySelectorAll('header nav[aria-label="主要"] a')].map((a) => `${a.textContent.trim()}:${a.getAttribute("href")}:${a.getAttribute("aria-current") ?? ""}`).join(","),
        wordmark: document.querySelector('a[aria-label="Forliosa 首頁"]')?.getAttribute("href"),
        login: [...document.querySelectorAll("a[href^='/login']")].map((a) => `${a.textContent.trim()}:${a.getAttribute("href")}:${getComputedStyle(a).backgroundColor !== "rgba(0, 0, 0, 0)"}`).join(","),
        footer: [...document.querySelectorAll("#main footer a")].map((a) => `${a.textContent.trim()}:${a.getAttribute("href")}`).join(","),
        shell: document.querySelectorAll(".dock, aside").length,
        paragraphs: [...document.querySelectorAll("#main > div > p")].length,
        wide: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      }
    })
    if (home.h1 !== 1 || home.titles !== "帳本|個股|問 AI" || home.tags !== "111" || !home.described || !home.hidden || home.controls) throw new Error(`home specimens: ${JSON.stringify(home)}`)
    if (home.tops !== 1 || home.seams !== "0,0" || home.widths !== 1) throw new Error(`the three specimens are not one ruled sheet: ${JSON.stringify(home)}`)
    // 頁首：字標、討論、登入（這一頁唯一的動作：墨色的主要按鈕，只有一顆）；頁尾只有兩份條款；沒有其他說明的段落
    if (home.wordmark !== "/" || home.nav !== "討論:/discussions:" || home.login !== "登入:/login:true" || home.footer !== "服務條款:/terms,隱私權政策:/privacy" || home.shell || home.paragraphs || home.wide > 0) throw new Error(`home page chrome: ${JSON.stringify(home)}`)
    // 「登入」→ 登入頁（沒有 next）→ 登入後是帳本
    await p.getByRole("banner").getByRole("link", { name: "登入", exact: true }).click()
    await p.waitForURL(/\/login$/, { timeout: 8000 })
    await p.getByRole("button", { name: "用 Google 登入" }).click()
    await p.getByText("總資產").first().waitFor({ timeout: 8000 })
    if (new URL(p.url()).pathname !== "/" || (await p.getByRole("heading", { level: 1, name: "股票帳本" }).count())) throw new Error("signing in from the home page does not land on the ledger")
    if ((await p.title()) !== "帳本｜Forliosa") throw new Error(`ledger title after sign-in: ${await p.title()}`)
  })
  // 其他要登入的頁面照舊：導到登入頁，帶著原本的網址
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/settings?auth=signed-out", { waitUntil: "networkidle" })
    await p.waitForURL(/\/login\?next=%2Fsettings/, { timeout: 8000 })
    // 帶著參數的首頁（舊網址 /transactions 會導到這裡）：也是介紹頁，「登入」帶著原本的網址
    await p.goto(base + "/?view=transactions", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "股票帳本" }).waitFor({ timeout: 8000 })
    const href = await p.getByRole("banner").getByRole("link", { name: "登入", exact: true }).getAttribute("href")
    if (!/^\/login\?next=%2F%3Fview%3Dtransactions$/.test(href ?? "")) throw new Error(`登入 on /?view=transactions does not carry the page: ${href}`)
  })
  // 手機：一欄直排、不橫向捲動、可按的東西都 ≥ 44px；頁首跟著捲動，捲到最底「登入」還按得到
  await fresh({ ...pw.devices["iPhone 15"] }, async (p) => {
    await p.goto(base + "/?auth=signed-out", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "股票帳本" }).waitFor({ timeout: 8000 })
    const wide = await overflowX(p)
    if (wide > 0) throw new Error(`the home page scrolls sideways by ${wide}px`)
    const small = await smallTargets(p)
    if (small.length) throw new Error(`home page: ${small.length} targets under 44px — ${small.slice(0, 6).join(" | ")}`)
    const stacked = await p.evaluate(() => [...document.querySelectorAll("#main figure")].map((f) => Math.round(f.getBoundingClientRect().left)))
    if (new Set(stacked).size !== 1) throw new Error(`the specimens are not stacked in one column on a phone: ${stacked}`)
    await p.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
    await p.waitForTimeout(200)
    const login = await p.getByRole("banner").getByRole("link", { name: "登入", exact: true }).boundingBox()
    if (!login || login.y < 0 || login.y > 60) throw new Error(`登入 is not reachable after scrolling to the bottom: ${JSON.stringify(login)}`)
  })
})
await check("帳號：條款頁不用登入就能讀（草稿標示、一行不超過 40 個字、表格不撐寬頁面）；登入頁寫明同意；設定頁可以匯出與刪除帳號；條款更新時有一行", async () => {
  // 沒登入：兩份文件都讀得到，是精簡的外殼
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/privacy?auth=signed-out", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: /隱私權政策/ }).waitFor({ timeout: 8000 })
    if (!/\/privacy$/.test(new URL(p.url()).pathname)) throw new Error(`redirected to ${p.url()}`)
    if (await p.locator('nav[aria-label="主要"] a[href="/groups"], .dock, aside').count()) throw new Error("the signed-in shell is shown on a public legal page")
    if ((await p.locator('a[aria-label="Forliosa 首頁"]').getAttribute("href")) !== "/") throw new Error("the wordmark of the public shell does not link to the home page")
    await p.getByRole("note").filter({ hasText: "草稿" }).waitFor({ timeout: 5000 })
    if (await p.getByText(/供產品負責人與律師審閱/).count()) throw new Error("the reviewers' note is shown to visitors")
    const doc = await p.evaluate(() => {
      const article = document.querySelector("article")
      const ps = [...article.querySelectorAll("p, li")].filter((el) => !el.closest("table") && el.textContent.trim().length > 60)
      const widest = Math.max(...ps.map((el) => el.getBoundingClientRect().width / parseFloat(getComputedStyle(el).fontSize)))
      return { widest: Math.round(widest * 10) / 10, tables: article.querySelectorAll("table").length, scripts: article.querySelectorAll("script, iframe").length, h2Rule: getComputedStyle(article.querySelector("h2")).borderBottomWidth }
    })
    if (doc.widest > 40.5) throw new Error(`a line of the policy is wider than 40em: ${JSON.stringify(doc)}`)
    if (!doc.tables || doc.scripts || doc.h2Rule !== "1px") throw new Error(`policy structure: ${JSON.stringify(doc)}`)
    // 分頁標題是文件名稱；桌面右邊有目錄，按了捲到那一節
    if ((await p.title()) !== "隱私權政策｜Forliosa") throw new Error(`privacy page title: ${await p.title()}`)
    const toc = p.getByRole("navigation", { name: "目錄" })
    await toc.getByRole("link", { name: "7. 資料保存多久" }).click()
    await p.waitForFunction(() => { const h = document.getElementById("sec-7"); const y = h?.getBoundingClientRect().top ?? 9999; return y >= 0 && y < 200 }, null, { timeout: 5000 })
    if (await p.locator("article").getByText(/草稿日期/).count()) throw new Error("the drafting date line is shown")
    // 「見第 N 節」是頁內連結
    if ((await p.locator("article").getByRole("link", { name: "第 10 節" }).first().getAttribute("href")) !== "#sec-10") throw new Error("section references are not links")
    await p.locator("article").getByRole("link", { name: "服務條款", exact: true }).last().click()
    await p.getByRole("heading", { level: 1, name: /服務條款/ }).waitFor({ timeout: 8000 })
    // 服務條款裡的〈隱私權政策〉第 6 節：連到那一頁的那一節，載入後捲過去
    await p.locator("article").getByRole("link", { name: "〈隱私權政策〉第 6 節" }).click()
    await p.getByRole("heading", { level: 1, name: /隱私權政策/ }).waitFor({ timeout: 8000 })
    await p.waitForFunction(() => { const h = document.getElementById("sec-6"); const y = h?.getBoundingClientRect().top ?? 9999; return y >= 0 && y < 200 }, null, { timeout: 5000 })
    // 登入頁：只有登入——字標、「登入」、Google 與 Discord 兩顆一樣重的按鈕（有商標），全部置中；沒有說明的句子、沒有示範畫面；分頁標題
    await p.goto(base + "/login", { waitUntil: "networkidle" })
    await p.getByRole("button", { name: "用 Google 登入" }).waitFor({ timeout: 8000 })
    if ((await p.title()) !== "登入｜Forliosa") throw new Error(`login page title: ${await p.title()}`)
    if (await p.locator("figure").count()) throw new Error("the ledger specimen is back on the login page")
    const signIn = await p.getByRole("button", { name: /^用 (Google|Discord) 登入$/ }).evaluateAll((els) => els.map((el) => { const r = el.getBoundingClientRect(); const c = getComputedStyle(el); return { text: el.textContent.trim(), w: Math.round(r.width), h: Math.round(r.height), bg: c.backgroundColor, mark: !!el.querySelector("svg") } }))
    if (signIn.map((b) => b.text).join("|") !== "用 Google 登入|用 Discord 登入") throw new Error(`login buttons: ${JSON.stringify(signIn)}`)
    if (signIn[0].w !== signIn[1].w || signIn[0].bg !== signIn[1].bg || !signIn.every((b) => b.mark && b.h >= 44)) throw new Error(`the two sign-in buttons should look the same: ${JSON.stringify(signIn)}`)
    const page1 = await p.locator("main").evaluate((el) => {
      const mid = (x) => { const r = x.getBoundingClientRect(); return Math.round(r.left + r.width / 2) }
      const centre = Math.round(innerWidth / 2)
      return {
        width: Math.round(el.getBoundingClientRect().width), centre,
        off: [el.querySelector("span"), el.querySelector("h1"), ...el.querySelectorAll("button"), el.querySelector("p")].map((x) => Math.abs(mid(x) - centre)),
        paragraphs: [...el.querySelectorAll("p")].map((x) => x.textContent.trim()),
      }
    })
    if (page1.width > 400) throw new Error(`the login page should be one narrow column, main is ${page1.width}px wide`)
    if (page1.off.some((d) => d > 2)) throw new Error(`the login page is not centred: ${JSON.stringify(page1)}`)
    // 畫面上唯一的一行字是同意條款
    if (page1.paragraphs.length !== 1 || !page1.paragraphs[0].startsWith("登入即表示你同意")) throw new Error(`extra sentences on the login page: ${JSON.stringify(page1.paragraphs)}`)
    await p.goto(base + "/login", { waitUntil: "networkidle" })
    const consent = p.locator("p", { hasText: "登入即表示你同意" })
    await consent.waitFor({ timeout: 8000 })
    if ((await consent.getByRole("link", { name: "服務條款" }).getAttribute("href")) !== "/terms" || (await consent.getByRole("link", { name: "隱私權政策" }).getAttribute("href")) !== "/privacy") throw new Error("login consent links")
  })
  // 手機：頁面不橫向捲動；表格也不橫向捲動（兩欄的換行、三欄以上改成一列一塊），沒有字被切掉；有收合的目錄
  await fresh({ ...pw.devices["iPhone 15"] }, async (p) => {
    for (const path of ["/privacy", "/terms"]) {
      await p.goto(base + path, { waitUntil: "networkidle" })
      await p.getByRole("heading", { level: 1 }).first().waitFor({ timeout: 8000 })
      const wide = await overflowX(p)
      if (wide > 0) throw new Error(`${path}: the page scrolls sideways by ${wide}px`)
      const clipped = await p.evaluate(() => {
        const vw = document.documentElement.clientWidth
        return [...document.querySelectorAll("article table, article ul[aria-label$='（表格）']")]
          .filter((el) => el.getBoundingClientRect().width > 0)
          .flatMap((el) => [...el.querySelectorAll("td, th, dd, dt, p")].filter((c) => { const r = c.getBoundingClientRect(); return r.width > 0 && (r.right > vw + 0.5 || r.left < -0.5) }).map((c) => c.textContent.slice(0, 20)))
      })
      if (clipped.length) throw new Error(`${path}: table cells run off the screen on a phone: ${clipped.slice(0, 3).join(" | ")}`)
      if (await p.evaluate(() => [...document.querySelectorAll("article *")].some((el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== "visible" && el.getBoundingClientRect().width > 0 && el.tagName !== "PRE"))) throw new Error(`${path}: something in the document scrolls sideways`)
    }
    // 隱私權政策的「廠商」表（四欄）在手機是一列一塊
    await p.goto(base + "/privacy", { waitUntil: "networkidle" })
    const vendors = p.locator("article ul[aria-label$='（表格）']").first()
    await vendors.getByText("Railway", { exact: true }).waitFor({ timeout: 8000 })
    await vendors.getByText(/^所在地：/).first().waitFor()
    // 目錄：收合著，打開後每一列 44px、按了捲到那一節
    const tocToggle = p.locator("article summary", { hasText: "目錄" })
    await tocToggle.click()
    const row = p.locator("article details").getByRole("link", { name: "8. Cookie 與瀏覽器裡的儲存" })
    if ((await row.boundingBox()).height < 44) throw new Error("the contents rows are under 44px on a phone")
    await row.click()
    await p.waitForFunction(() => { const h = document.getElementById("sec-8"); const y = h?.getBoundingClientRect().top ?? 9999; return y >= 0 && y < 260 }, null, { timeout: 5000 })
  })
  // 手機的登入頁：兩顆登入按鈕都在第一個畫面裡，不用捲
  await fresh({ ...pw.devices["iPhone 15"] }, async (p) => {
    await p.goto(base + "/login?auth=signed-out", { waitUntil: "networkidle" })
    await p.getByRole("button", { name: "用 Discord 登入" }).waitFor({ timeout: 8000 })
    await p.getByRole("button", { name: "用 Google 登入" }).waitFor()
    const fits = await p.evaluate(() => ({ lastButton: Math.max(...[...document.querySelectorAll("button")].filter((b) => /登入$/.test(b.textContent.trim())).map((b) => b.getBoundingClientRect().bottom)), consent: [...document.querySelectorAll("p")].find((el) => el.textContent.includes("登入即表示你同意")).getBoundingClientRect().bottom, vh: innerHeight, wide: document.documentElement.scrollWidth - document.documentElement.clientWidth, scrolls: document.documentElement.scrollHeight > innerHeight + 1 }))
    if (fits.lastButton > fits.vh || fits.consent > fits.vh || fits.wide > 0 || fits.scrolls) throw new Error(`phone login should fit one screen: ${JSON.stringify(fits)}`)
  })
  // 登入後：設定頁的「帳號與資料」
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/settings", { waitUntil: "networkidle" })
    const section = p.getByRole("region", { name: "帳號與資料" })
    await section.waitFor({ timeout: 8000 })
    const download = p.waitForEvent("download", { timeout: 8000 })
    await section.getByRole("button", { name: "匯出", exact: true }).click()
    const file = await download
    if (!/^forliosa-export-\d{8}\.json$/.test(file.suggestedFilename())) throw new Error(`export filename: ${file.suggestedFilename()}`)
    await p.getByText("已下載匯出檔").waitFor({ timeout: 8000 })
    // 刪除帳號：沒輸入那句話不能按；取消就什麼都沒發生
    await section.getByRole("button", { name: "刪除帳號…" }).click()
    const dialog = p.getByRole("dialog")
    await dialog.getByRole("heading", { name: "刪除帳號？" }).waitFor({ timeout: 5000 })
    const confirm = dialog.getByRole("button", { name: "永久刪除帳號" })
    if (!(await confirm.isDisabled())) throw new Error("the delete button is enabled before typing the phrase")
    await dialog.getByRole("textbox").fill("刪除")
    if (!(await confirm.isDisabled())) throw new Error("the delete button is enabled with the wrong phrase")
    await dialog.getByRole("button", { name: "取消" }).click()
    await dialog.waitFor({ state: "detached", timeout: 5000 })
    // 真的刪除：回到登入頁，寫一句帳號已刪除
    await section.getByRole("button", { name: "刪除帳號…" }).click()
    await p.getByRole("dialog").getByRole("textbox").fill("刪除我的帳號")
    await p.getByRole("dialog").getByRole("button", { name: "永久刪除帳號" }).click()
    await p.waitForURL(/\/login\?deleted=1/, { timeout: 8000 })
    await p.getByText("你的帳號已經刪除。").waitFor({ timeout: 8000 })
  })
  // 條款更新：一行說明，按「知道了」之後消失、換頁也不再出現
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/settings?terms=updated", { waitUntil: "networkidle" })
    // 站方有填生效日與變更摘要：那一行寫哪一天起適用、改了什麼
    const notice = p.getByRole("status").filter({ hasText: "12/1 起適用新版服務條款與隱私權政策：新增匯出資料與刪除帳號的說明。" })
    await notice.waitFor({ timeout: 8000 })
    await notice.getByRole("button", { name: "知道了" }).click()
    await notice.waitFor({ state: "detached", timeout: 8000 })
    await p.getByRole("navigation", { name: "主要" }).getByRole("link", { name: "帳本" }).click()
    await p.getByText("總資產").first().waitFor({ timeout: 8000 })
    if (await p.getByText(/新版服務條款與隱私權政策|服務條款與隱私權政策已更新/).count()) throw new Error("the terms notice came back after acknowledging")
  })
})

await check("討論（草稿）：回覆打到一半按「改」去設定，上一頁回來字還在、可以清除；開新主題按「取消」再回來也還在", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/discussions/top_p_etf?discuss=named", { waitUntil: "networkidle" })
    const box = p.getByRole("textbox", { name: "回覆內容" })
    await box.waitFor({ timeout: 8000 })
    await box.fill("寫到一半的回覆，先去改個暱稱。")
    if (await p.getByRole("button", { name: "清除草稿" }).count()) throw new Error("清除草稿 is shown while typing")
    await p.getByRole("form", { name: "回覆這個主題" }).getByRole("link", { name: "改" }).click()
    await p.waitForURL(/\/settings/, { timeout: 8000 })
    await p.goBack()
    await box.waitFor({ timeout: 8000 })
    if ((await box.inputValue()) !== "寫到一半的回覆，先去改個暱稱。") throw new Error(`the reply draft was lost: “${await box.inputValue()}”`)
    // 別的主題的框是空的
    await p.goto(base + "/discussions/top_p_us", { waitUntil: "networkidle" })
    await box.waitFor({ timeout: 8000 })
    if ((await box.inputValue()) !== "") throw new Error("another topic shows this topic's draft")
    await p.goto(base + "/discussions/top_p_etf", { waitUntil: "networkidle" })
    await p.getByRole("button", { name: "清除草稿" }).click()
    if ((await box.inputValue()) !== "") throw new Error("清除草稿 did not clear the box")
    await p.reload({ waitUntil: "networkidle" })
    await box.waitFor({ timeout: 8000 })
    if ((await box.inputValue()) !== "") throw new Error("the cleared draft came back")
    // 開新主題：取消（回到來的地方）之後再進來，內容還在
    await p.goto(base + "/stock/0050.TW?tab=discussions", { waitUntil: "networkidle" })
    await p.getByRole("link", { name: "開新主題" }).click()
    await p.waitForURL(/\/discussions\/new\?symbol=0050\.TW&from=stock/, { timeout: 8000 })
    await p.getByRole("navigation", { name: "位置" }).getByRole("link", { name: "元大台灣50" }).waitFor({ timeout: 8000 })
    await p.getByRole("radio", { name: /^公開/ }).check()
    await p.getByLabel("標題").fill("寫到一半的主題")
    await p.getByLabel("內文").fill("先放著，等等再寫。")
    const cancel = p.getByRole("link", { name: "取消" })
    if (await cancel.getAttribute("aria-current")) throw new Error("取消 is marked aria-current")
    await cancel.click()
    await p.waitForURL(/\/stock\/0050\.TW\?tab=discussions/, { timeout: 8000 })
    await p.getByRole("link", { name: "開新主題" }).click()
    await p.getByText("這是上次還沒發表的內容。").waitFor({ timeout: 8000 })
    if ((await p.getByLabel("標題").inputValue()) !== "寫到一半的主題" || (await p.getByLabel("內文").inputValue()) !== "先放著，等等再寫。") throw new Error("the new-topic draft was lost")
    if (!(await p.getByRole("radio", { name: /^公開/ }).isChecked())) throw new Error("the draft forgot where to post")
    await p.getByRole("button", { name: "清除草稿" }).click()
    if ((await p.getByLabel("標題").inputValue()) !== "") throw new Error("清除草稿 did not clear the form")
  })
})

await check("討論（入口與設定）：個股的「討論」分頁（開新主題預先標記這一檔）、群組的「討論」分頁（預先選好群組）、設定的公開暱稱、停權時的說明、不是管理員看不到管理後台", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/stock/0050.TW", { waitUntil: "networkidle" })
    const tabs = await p.getByRole("tablist", { name: "個股資料" }).getByRole("tab").allTextContents()
    if (tabs.join("・") !== "總覽・估值・財務・籌碼・股利・事件・討論") throw new Error(`stock tabs: ${tabs.join("・")}`)
    await p.getByRole("tab", { name: "討論" }).click()
    await p.getByText("0050 要不要改買 006208？").waitFor({ timeout: 8000 })
    await p.getByText("這個月的定期定額，大家扣了嗎？").waitFor()
    if (await p.getByText("第一次買零股，手續費怎麼算？").count()) throw new Error("an untagged topic is listed on the stock tab")
    await p.getByRole("link", { name: "開新主題" }).click()
    await p.waitForURL(/\/discussions\/new\?symbol=0050\.TW/, { timeout: 8000 })
    await p.getByRole("list", { name: "已標記的股票" }).getByText("元大台灣50").waitFor({ timeout: 8000 })
    // 沒有預先選發到哪裡：不替使用者決定
    if (await p.getByRole("radio", { checked: true }).count()) throw new Error("a destination is preselected without a preset")
    // 群組的討論分頁
    await p.goto(base + "/groups/grp_family", { waitUntil: "networkidle" })
    await p.getByRole("tab", { name: "討論" }).click()
    await p.getByText("過年的紅包，要不要一起存 0056？").waitFor({ timeout: 8000 })
    await p.getByRole("link", { name: "開新主題" }).click()
    await p.waitForURL(/\/discussions\/new\?scope=group&group_id=grp_family/, { timeout: 8000 })
    if (!(await p.getByRole("radio", { name: /^家族投資/ }).isChecked())) throw new Error("the group is not preselected")
    await p.getByRole("form", { name: "新主題" }).getByText("以「示範使用者」在「家族投資」發言").waitFor({ timeout: 8000 })
    // 設定：公開暱稱（改過才有簽名格）；個人資料的錨點
    await p.goto(base + "/settings#profile", { waitUntil: "networkidle" })
    const name = p.getByLabel("公開暱稱")
    await name.waitFor({ timeout: 8000 })
    const form = p.locator("form").filter({ has: name })
    if (await form.getByRole("button", { name: "儲存", exact: true }).count()) throw new Error("save shown before the public name changed")
    await name.fill("煙霧測試員")
    await form.getByRole("button", { name: "儲存", exact: true }).click()
    await p.getByText("公開暱稱是「煙霧測試員」").waitFor({ timeout: 8000 })
    await p.getByText(/2 到 20 個字，7 天內只能改一次。/).waitFor({ timeout: 8000 })
    // 第一次改名不用等；再改就要等 7 天
    await name.fill("煙霧測試員二")
    await form.getByRole("button", { name: "儲存", exact: true }).click()
    await p.getByText("公開暱稱是「煙霧測試員二」").waitFor({ timeout: 8000 })
    await name.fill("煙霧測試員三")
    await form.getByRole("button", { name: "儲存", exact: true }).click()
    await p.getByText("公開暱稱 7 天內只能改一次，7 天後可以再改。").waitFor({ timeout: 8000 })
    // 停權：設定與回覆區都寫到什麼時候；群組照常
    await p.goto(base + "/settings?discuss=suspended", { waitUntil: "networkidle" })
    await p.getByText("你的公開發言已被站方暫停到 11/19（四）13:30。原因：重複張貼同樣的內容。群組裡的發言不受影響。").waitFor({ timeout: 8000 })
    await p.goto(base + "/discussions/top_p_etf", { waitUntil: "networkidle" })
    await p.getByText("你的公開發言已被站方暫停到 11/19（四）13:30。原因：重複張貼同樣的內容。群組裡的發言不受影響。").waitFor({ timeout: 8000 })
    if (await p.getByRole("textbox", { name: "回覆內容" }).count()) throw new Error("composer shown while suspended")
    await p.goto(base + "/discussions/top_g_dca", { waitUntil: "networkidle" })
    await p.getByRole("textbox", { name: "回覆內容" }).waitFor({ timeout: 8000 })
    // 不是站方管理員：管理後台的每一頁都是一般外殼裡的「找不到這個頁面」，⌘K 也沒有「管理後台」
    for (const path of ["/admin?discuss=member", "/admin/discussions", "/admin/news"]) {
      await p.goto(base + path, { waitUntil: "networkidle" })
      await p.getByRole("heading", { level: 1, name: "找不到這個頁面" }).waitFor({ timeout: 8000 })
      if (await p.getByRole("navigation", { name: "管理後台" }).count()) throw new Error("admin nav shown to a non-admin")
    }
    await p.getByRole("button", { name: /搜尋股票/ }).click()
    await p.getByRole("option", { name: "設定" }).waitFor({ timeout: 5000 })
    if (await p.getByRole("option", { name: "管理後台" }).count()) throw new Error("管理後台 in ⌘K for a non-admin")
  })
})

await check("討論（查看別人的資產）：討論的每一頁都擋下，個股頁沒有「討論」分頁", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/settings", { waitUntil: "networkidle" })
    await p.getByRole("button", { name: "查看爸爸的資產" }).click()
    await p.getByText("正在查看 爸爸 的資產（唯讀）").waitFor({ timeout: 8000 })
    for (const path of ["/discussions", "/discussions/top_p_etf", "/discussions/new"]) {
      await p.goto(base + path, { waitUntil: "networkidle" })
      await p.getByText(/討論是你自己的，結束查看後才能用/).waitFor({ timeout: 8000 })
    }
    await p.goto(base + "/admin/discussions", { waitUntil: "networkidle" })
    await p.getByText(/管理後台是你自己的，結束查看後才能用/).waitFor({ timeout: 8000 })
    await p.goto(base + "/stock/2330.TW?tab=discussions", { waitUntil: "networkidle" })
    await p.getByText("參考價").first().waitFor({ timeout: 8000 })
    if (await p.getByRole("tab", { name: "討論" }).count()) throw new Error("the stock page has a 討論 tab in view-as mode")
  })
})

await check("持倉展開每一筆買賣（2026-11-14）：日期（不是今年寫年份）、股數、價格、金額、買進後漲跌；⋯ 修改打開編輯交易；手機的展開鈕 ≥ 44×44、展開後不橫向捲動", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/", { waitUntil: "networkidle" })
    const table = p.getByRole("table", { name: "持倉" })
    await table.getByRole("button", { name: "展開台積電的每一筆買賣" }).click()
    const list = table.getByRole("list", { name: "台積電的每一筆買賣" })
    await list.getByRole("listitem").first().waitFor({ timeout: 8000 })
    const first = await list.getByRole("listitem").first().innerText()
    if (!/2024\/8\/6/.test(first) || !/33\.13%/.test(first) || !/NT\$407,500/.test(first)) throw new Error(`first record: ${first}`)
    await list.getByRole("button", { name: "2024/8/6（二） 買進的動作" }).click()
    await p.getByRole("menuitem", { name: "修改" }).click()
    await p.getByRole("dialog", { name: "編輯交易" }).waitFor({ timeout: 8000 })
  })
  await fresh({ ...pw.devices["iPhone SE"] }, async (p) => {
    await p.goto(base + "/", { waitUntil: "networkidle" })
    const btn = p.getByRole("list", { name: "持倉" }).getByRole("button", { name: "展開台積電的每一筆買賣" })
    const box = await btn.boundingBox()
    if (!box || box.width < 44 || box.height < 44) throw new Error(`expand button ${JSON.stringify(box)}`)
    await btn.click()
    await p.getByRole("list", { name: "台積電的每一筆買賣" }).getByRole("listitem").first().waitFor({ timeout: 8000 })
    const over = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    if (over > 0) throw new Error(`horizontal scroll ${over}px`)
  })
})

await check("管理後台（桌面）：自己的外殼（總覽・討論・新聞下架、回到帳本；沒有頭像選單）、總覽的四個區塊、新聞下架的封鎖與解除都先確認", async () => {
  await fresh(DESKTOP, async (p) => {
    await p.goto(base + "/admin", { waitUntil: "networkidle" })
    await p.getByRole("heading", { level: 1, name: "總覽" }).waitFor({ timeout: 8000 })
    const nav = p.getByRole("navigation", { name: "管理後台" })
    const tabs = await nav.getByRole("link").allTextContents()
    if (tabs.join("|") !== "總覽|討論|新聞下架") throw new Error(`admin tabs: ${tabs.join("|")}`)
    if (await p.getByRole("button", { name: /帳號選單/ }).count()) throw new Error("avatar menu inside the admin shell")
    for (const name of ["使用者", "AI 金鑰", "資料", "歷史日線回補"]) await p.getByRole("heading", { level: 2, name, exact: true }).waitFor({ timeout: 5000 })
    await p.getByText("冷卻中，38 秒後再試").waitFor({ timeout: 5000 })
    await nav.getByRole("link", { name: "新聞下架" }).click()
    await p.waitForURL(/\/admin\/news$/, { timeout: 8000 })
    await p.getByRole("textbox", { name: "網域" }).fill("https://www.example.com/demo-news/1")
    await p.getByRole("button", { name: "封鎖", exact: true }).click()
    await p.getByRole("alertdialog").getByRole("button", { name: "封鎖", exact: true }).click()
    await p.getByText("已封鎖 example.com").waitFor({ timeout: 8000 })
    await p.getByRole("list", { name: "封鎖中的網域" }).getByRole("listitem").filter({ hasText: /^example\.com/ }).waitFor({ timeout: 8000 })
    if (await p.getByRole("button", { name: "解除封鎖 sample-wire.example" }).count()) throw new Error("an env-set domain can be unblocked")
    await p.getByRole("button", { name: "解除封鎖 example.com" }).click()
    await p.getByRole("alertdialog").getByRole("button", { name: "解除", exact: true }).click()
    await p.getByText("已解除封鎖 example.com").waitFor({ timeout: 8000 })
    await p.getByRole("link", { name: "回到帳本" }).click()
    await p.waitForURL((u) => new URL(u).pathname === "/", { timeout: 8000 })
  })
})

await check("手機：討論的清單、主題、開新主題、管理後台——可按範圍都 ≥ 44×44、頁面不橫向捲動；清單整列可以按、日期格是窄的一欄；沒登入也一樣", async () => {
  await fresh({ ...pw.devices["iPhone 15"] }, async (p) => {
    for (const [path, ready] of [
      ["/discussions", "台積電法說會前，大家怎麼配置？"],
      ["/discussions?scope=group&group_id=grp_family", "我把聯發科的交易補記好了"],
      ["/discussions/top_p_tsmc", "比重超過自己睡得著的程度就調"],
      ["/discussions/top_p_tsmc?discuss=named", "比重超過自己睡得著的程度就調"],
      ["/discussions/top_p_odd", "每家券商的最低手續費不一樣"],
      ["/discussions/top_g_dca?discuss=default", "我明天去問營業員怎麼設定"],
      ["/discussions/new?scope=public&symbol=2330.TW", "先選一個公開暱稱"],
      ["/discussions/new?discuss=named&symbol=2330.TW", "標記的主題也會出現"],
      ["/admin/discussions?discuss=default", "停權中"],
      ["/admin/discussions?status=resolved", "已隱藏"],
      ["/admin", "AI 金鑰"],
      ["/admin/news", "封鎖中"],
      ["/stock/2330.TW?tab=discussions", "台積電法說會前，大家怎麼配置？"],
      ["/groups/grp_family?tab=discussions", "過年的紅包，要不要一起存 0056？"],
      ["/settings", "公開暱稱"],
    ]) {
      await p.goto(base + path, { waitUntil: "networkidle" })
      await p.getByText(ready).first().waitFor({ timeout: 8000 })
      await p.waitForTimeout(400)
      const wide = await overflowX(p)
      if (wide > 0) throw new Error(`${path}: the page scrolls sideways by ${wide}px`)
      const small = await smallTargets(p)
      if (small.length) throw new Error(`${path}: ${small.length} targets under 44px — ${small.slice(0, 6).join(" | ")}`)
    }
    // 個股頁的分頁列：七個分頁在 iPhone 15（393px）上全部看得到，「討論」不用捲動就在畫面裡
    await p.goto(base + "/stock/2330.TW", { waitUntil: "networkidle" })
    await p.getByRole("tablist", { name: "個股資料" }).waitFor({ timeout: 8000 })
    const tabRow = await p.getByRole("tablist", { name: "個股資料" }).evaluate((row) => ({
      scroll: row.scrollWidth - row.clientWidth,
      tabs: [...row.querySelectorAll("[role=tab]")].map((t) => { const r = t.getBoundingClientRect(); return { text: t.textContent, left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width) } }),
      vw: innerWidth,
    }))
    if (tabRow.tabs.length !== 7 || tabRow.scroll > 0 || tabRow.tabs.some((t) => t.left < 0 || t.right > tabRow.vw || t.w < 44)) throw new Error(`stock tabs do not all fit on a 393px phone: ${JSON.stringify(tabRow)}`)
    // 主題頁：每一則發言左邊是日期格，字的左緣和清單的標題是同一條
    await p.goto(base + "/discussions", { waitUntil: "networkidle" })
    await p.getByText("台積電法說會前，大家怎麼配置？").first().waitFor({ timeout: 8000 })
    const listLeft = await p.locator('ul[aria-label="主題"] > li a').first().evaluate((a) => Math.round(a.getBoundingClientRect().left))
    await p.goto(base + "/discussions/top_p_tsmc", { waitUntil: "networkidle" })
    await p.getByText("比重超過自己睡得著的程度就調").waitFor({ timeout: 8000 })
    const topic = await p.evaluate(() => ({
      title: Math.round(document.querySelector("article h1").getBoundingClientRect().left),
      replies: [...document.querySelectorAll('ol[aria-label="回覆"] > li')].map((li) => ({ date: !!li.querySelector(".date-cell time"), text: Math.round(li.querySelector("p").getBoundingClientRect().left) })),
      topicDate: !!document.querySelector("article > div .date-cell time"),
    }))
    if (!topic.topicDate || topic.title !== listLeft || topic.replies.some((r) => !r.date || r.text !== listLeft)) throw new Error(`the topic page is not on the list's date gutter: ${JSON.stringify({ listLeft, topic })}`)
    // 清單：整列可以按（按在列的右邊也到主題）、日期格是窄的一欄（標題有地方寫）
    await p.goto(base + "/discussions", { waitUntil: "networkidle" })
    const row = p.locator('ul[aria-label="主題"] > li').filter({ hasText: "定期定額的扣款日，選幾號有差嗎？" })
    await row.waitFor({ timeout: 8000 })
    const hit = await row.evaluate((li) => {
      const a = li.querySelector("a")
      const r = li.getBoundingClientRect()
      li.scrollIntoView({ block: "center" })
      const b = li.getBoundingClientRect()
      const at = document.elementFromPoint(b.right - 6, b.top + b.height / 2)
      const date = li.querySelector(".date-cell").getBoundingClientRect()
      return { h: r.height, covers: at === a || a.contains(at), dateW: Math.round(date.width), titleLines: Math.round(a.getBoundingClientRect().height / parseFloat(getComputedStyle(a).lineHeight)) }
    })
    if (hit.h < 44 || !hit.covers) throw new Error(`the topic row is not one link: ${JSON.stringify(hit)}`)
    if (hit.dateW > 56 || hit.titleLines !== 1) throw new Error(`the date column leaves too little room for the title: ${JSON.stringify(hit)}`)
    // 按在那一行 meta 的字上也是打開主題（分隔符號與 meta 不擋住整列的連結）
    const metaHit = await row.evaluate((li) => {
      const a = li.querySelector("a")
      const m = li.querySelector(".meta-line > div > *").getBoundingClientRect()
      const at = document.elementFromPoint(m.left + m.width / 2, m.top + m.height / 2)
      return at === a || a.contains(at)
    })
    if (!metaHit) throw new Error("tapping the meta line does not open the topic")
    await row.click({ position: { x: 300, y: 20 } })
    await p.waitForURL(/\/discussions\/top_p_day$/, { timeout: 8000 })
  })
  await fresh({ ...pw.devices["iPhone 15"] }, async (p) => {
    for (const [path, ready] of [
      ["/discussions?auth=signed-out", "台積電法說會前，大家怎麼配置？"],
      ["/discussions/top_p_tsmc", "比重超過自己睡得著的程度就調"],
    ]) {
      await p.goto(base + path, { waitUntil: "networkidle" })
      await p.getByText(ready).first().waitFor({ timeout: 8000 })
      await p.waitForTimeout(400)
      if (await p.locator(".dock").count()) throw new Error(`${path}: the bottom bar is shown to a signed-out visitor`)
      const wide = await overflowX(p)
      if (wide > 0) throw new Error(`${path}: the page scrolls sideways by ${wide}px`)
      const small = await smallTargets(p)
      if (small.length) throw new Error(`${path} (signed out): ${small.length} targets under 44px — ${small.slice(0, 6).join(" | ")}`)
    }
  })
})

await browser.close()
if (errors.length) {
  failed++
  console.error(`\n${errors.length} 個 console 錯誤：\n  ${errors.slice(0, 10).join("\n  ")}`)
}
console.log(failed ? `\n${failed} 項失敗` : onlyCheck ? `\n名稱含「${onlyCheck}」的檢查通過（不是整份）` : "\n全部通過")
process.exitCode = failed ? 1 : 0
