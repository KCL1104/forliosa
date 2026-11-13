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

/**
 * 模型寫的長回答（紫色楷體）：mock 模式只有規則版回答，這裡把「真實後端」樣子的對話放進 localStorage
 * （`model: true`、網路來源、一段沒有附來源的段落），再從「紀錄」打開，檢查楷體與數字、行高、無來源標記、出處註腳。
 * `twoTurns`：同一段對話問兩次，免責只在最新一則回答下方出現一次。
 */
const seedModelThread = async (page, mobile, twoTurns) => {
  await page.evaluate((two) => {
    const at = new Date().toISOString()
    const text =
      "台積電今天上漲 4.83%，收在 1,085 元，是你今天貢獻最多的一檔，帳上多了 NT$75,000。\n" +
      "你持有 1 張 500 股，占總資產 43.9%，今天的漲跌大致決定了整個帳本的表現。\n" +
      "外資連續幾天買超，市場在等下個月的法說會。"
    const first = [
      { id: "msg_shot_u", role: "user", text: "台積電今天對我的帳本影響多大？", at },
      {
        id: "msg_shot_a",
        role: "ai",
        model: true,
        text,
        ungrounded: [{ text: "外資連續幾天買超，市場在等下個月的法說會。", reason: "uncited_news_claim" }],
        citations: [
          { url: "https://mops.twse.com.tw/", title: "公開資訊觀測站", cited_text: "台積電 115 年 10 月營收" },
          { url: "https://money.udn.com/money/story/5612/0000001", title: "台積電法說會前夕 外資連三買", cited_text: "外資連續三個交易日買超台積電" },
        ],
        disclaimer: "AI 回答僅供參考，非投資建議。",
        at,
      },
    ]
    const second = [
      { id: "msg_shot_u2", role: "user", text: "那我要不要再加碼？", at },
      {
        id: "msg_shot_a2",
        role: "ai",
        model: true,
        text: "我不替你決定買賣。以現價 1,085 元再加碼 1 張，台積電占總資產會從 43.9% 升到大約 57%，帳本會更集中在一檔。要的話直接說「買 2330 1 張」，我先寫成草稿。",
        citations: [],
        disclaimer: "AI 回答僅供參考，非投資建議。",
        at,
      },
    ]
    const thread = {
      id: "thr_shot_model",
      title: "台積電今天對我的帳本影響多大？",
      updatedAt: at,
      messages: two ? [...first, ...second] : first,
    }
    localStorage.setItem("forliosa:ai", JSON.stringify({ state: { panelOpen: true, threadId: null, threads: [thread], drafts: {} }, version: 1 }))
  }, twoTurns)
  await page.reload({ waitUntil: "networkidle" })
  await page.getByText("總資產").first().waitFor({ timeout: 15000 })
  if (mobile) {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(400)
  }
  await page.getByRole("button", { name: "紀錄", exact: true }).click()
  await page.getByRole("button", { name: /^台積電今天對我的帳本影響多大？/ }).first().click()
  await page.getByText(twoTurns ? /我不替你決定買賣/ : /外資連續幾天買超/).first().waitFor({ timeout: 8000 })
}
const modelAnswer = (page, mobile) => seedModelThread(page, mobile, false)
const modelThread = (page, mobile) => seedModelThread(page, mobile, true)

/** 美股（AAPL，持有中）：面板的提示字用「股」；問「我的成本在河流圖哪裡？」→ 帶 US$ 的均價，照實說沒有河流圖 */
const openAi = async (page, mobile) => {
  if (mobile) {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(500)
  }
}
const aaplRiver = async (page, mobile) => {
  await openAi(page, mobile)
  const box = mobile ? page.getByLabel(/搜尋股票、提問/) : page.getByLabel("提出問題或下指令")
  await box.fill("我的成本在河流圖哪裡？")
  await box.press("Enter")
  await page.getByText(/美股目前沒有可商用的行情來源/).first().waitFor({ timeout: 8000 })
  if (mobile) await box.blur()
}
/** 紀錄：刪除一段對話 → Sonner 通知「已刪除對話」附「復原」 */
const historyUndo = async (page) => {
  await page.getByRole("button", { name: /^刪除對話「00878 下次除息能領多少？」/ }).first().click()
  await page.getByText("已刪除對話").first().waitFor({ timeout: 8000 })
}

/** 個股頁：按 AI 面板的建議「台積電今天為什麼漲？」→ 規則版回答（句子用字說漲跌、數字列、可以去的地方、墨色的追問連結） */
const whyMove = async (page, mobile) => {
  if (mobile) {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(400)
  }
  await page.getByRole("list", { name: "可以這樣問" }).getByRole("button", { name: /今天為什麼(漲|跌)/ }).click()
  await page.getByRole("list", { name: "接著問" }).waitFor({ timeout: 8000 })
}
/** 草稿還沒簽名就開新對話：面板首頁的第一列是「1 筆草稿等你簽名」（手機從「紀錄」發起新對話） */
const pendingHome = async (page, mobile) => {
  await draft(page, mobile)
  if (mobile) {
    await page.getByRole("button", { name: "紀錄", exact: true }).click()
    await page.getByRole("button", { name: "發起新對話" }).click()
  } else {
    await page.getByRole("button", { name: "新對話" }).click()
  }
  await page.getByRole("button", { name: "1 筆草稿等你簽名" }).waitFor({ timeout: 8000 })
}
/** 手機底部列：有待簽名的草稿時，「問 AI」那一格多一行「待簽名 1 筆」（寫一份草稿、關掉問 AI 回到帳本） */
const pendingDock = async (page) => {
  await draft(page, true)
  await page.getByRole("dialog").getByRole("button", { name: "關閉" }).click()
  await page.getByRole("button", { name: "問 AI（待簽名 1 筆）" }).waitFor({ timeout: 8000 })
}
/** 績效：含美股算不出來 → 只看新台幣帳戶，才有區間、比較基準與圖表 */
const performanceTwd = async (page) => {
  await page.getByRole("button", { name: /只看「永豐/ }).click()
  await page.getByText("最大回撤").first().waitFor({ timeout: 8000 })
}
/** 捲到頁面最底：內容的最後一行在底部列上面，沒有被蓋住 */
const toBottom = async (page) => {
  await page.evaluate(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" }))
}
/** 手機搜尋股票：輸入「00」，符合的股票取代建議、列在輸入框上方（iOS 的鍵盤會蓋住輸入框下方） */
const mobileSearch = async (page) => {
  await page.getByRole("button", { name: /^問 AI/ }).click()
  await page.waitForTimeout(400)
  await page.getByLabel(/搜尋股票、提問/).fill("00")
  await page.getByRole("list", { name: "股票搜尋結果" }).waitFor({ timeout: 8000 })
  await page.waitForTimeout(300)
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

/** 資料來源：捲到「中央銀行」那一段（USD/TWD 匯率） */
const fxSource = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("ds-中央銀行")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}

/** 新聞報導：捲到總覽的「新聞報導」標題（桌面：頂部列 64＋sticky 分頁列 48；手機：sticky 分頁列） */
const toNews = async (page, mobile) => {
  await page.locator("#ov-media").waitFor({ timeout: 8000 })
  await page.evaluate((m) => {
    const el = document.getElementById("ov-media")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (m ? 72 : 136), behavior: "instant" })
  }, mobile)
}
/** 新聞報導：按「看更多」後捲回標題 */
const newsMore = async (page, mobile) => {
  await toNews(page, mobile)
  await page.getByRole("button", { name: /看更多/ }).click()
  await toNews(page, mobile)
}
/** 資料來源頁的 GDELT（新聞報導的授權） */
const gdeltSource = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("ds-The GDELT Project")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}

/** 捲到總覽的某個區塊標題（桌面：頂部列 64＋sticky 分頁列 48；手機：sticky 分頁列） */
const toSection = (id) => async (page, mobile) => {
  await page.locator(`#${id}`).waitFor({ timeout: 8000 })
  await page.evaluate(([el, m]) => {
    const node = document.getElementById(el)
    if (node) window.scrollTo({ top: node.getBoundingClientRect().top + window.scrollY - (m ? 72 : 136), behavior: "instant" })
  }, [id, mobile])
}
/** 估值分頁：打開河流圖的「怎麼看 ⌄」（術語說明預設收著） */
const valuationHowTo = async (page) => {
  await toTabs(page)
  await page.getByRole("region", { name: /河流圖$/ }).getByRole("button", { name: /^怎麼看/ }).click()
}
/** 籌碼分頁捲到「外資持股比」 */
const toForeign = async (page, mobile) => {
  await toTabs(page)
  await toSection("chips-foreign")(page, mobile)
}
/** 資料來源頁的維基百科（「關於」簡介的授權） */
/** 資料來源頁捲到「其他」（新聞報導的收集方式與 SearXNG 的風險說明、法人觀點） */
const otherSources = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("ds-other")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}
const wikiSource = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("ds-維基百科")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}

/** 資料來源頁的證期局（ETF 淨值的授權） */
const navSource = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("ds-金融監督管理委員會證券期貨局")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}

/** 上市股票的籌碼：按空狀態裡的「最近外資對這檔的動向？」交給 AI（mock 是本機規則版的說明） */
const foreignAsk = async (page, mobile) => {
  await toTabs(page)
  await page.locator("main").getByRole("button", { name: "最近外資對這檔的動向？" }).click()
  await page.getByText(/逐檔三大法人買賣超與外資持股比，證交所以付費商品提供/).first().waitFor({ timeout: 8000 })
  // 桌面：頁面停在分頁（只捲面板），空狀態和回答同時出現；手機是全螢幕的問 AI
  if (mobile) await page.waitForTimeout(400)
}

// ── M5 分享 ─────────────────────────────────────────────
/** 邀請：打開交易動態（同時看到「最近 90 天」的說明，附上成交價變成可以打開） */
const m5InviteTrades = async (page) => {
  await page.getByRole("switch", { name: "交易動態" }).click()
  await page.getByText(/最近 90 天的買賣也會出現在動態裡/).first().waitFor()
}
/** 動態：展開爸爸今天買台積電的留言 */
const m5FeedThread = async (page) => {
  const row = page.getByRole("listitem").filter({ hasText: "又加碼" }).or(page.getByRole("listitem").filter({ hasText: "台積電" }).filter({ hasText: "爸爸" })).first()
  await row.getByRole("button", { name: /留言/ }).click()
  await page.getByText("又加碼台積電了！").waitFor({ timeout: 8000 })
  await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
}
/** 我的分享：打開「金額與損益」（持股也開著）→ 旁邊提示可以推算股數 */
const m5ShareAmounts = async (page) => {
  await page.getByRole("switch", { name: "金額與損益" }).click()
  await page.getByText(/可以推算你大約持有幾股/).waitFor({ timeout: 8000 })
}
const m5Privacy = async (page) => {
  await page.getByRole("button", { name: "隱私模式：遮蔽金額" }).click()
  await page.getByLabel("已隱藏").first().waitFor()
}
/** 改了名字之後才出現的簽名格（顯示名稱、群組名稱） */
const editField = (label, text) => async (page) => {
  const input = page.getByLabel(label, { exact: true })
  await input.fill(text)
  await input.evaluate((el) => window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 160 : 120), behavior: "instant" }))
}
const m5Delegations = async (page) => {
  await page.evaluate(() => {
    const el = document.getElementById("delegations")
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - (window.innerWidth >= 1024 ? 88 : 16), behavior: "instant" })
  })
}
/** 授權查看：設定 → 爸爸授權給我的「查看」→ 帳本（唯讀橫幅） */
const m5ViewAs = async (page) => {
  await page.getByRole("button", { name: "查看爸爸的資產" }).click()
  await page.getByText("正在查看 爸爸 的資產（唯讀）").first().waitFor({ timeout: 8000 })
  await page.getByText("總資產").first().waitFor({ timeout: 8000 })
}
const m5ViewAsStock = async (page) => {
  await m5ViewAs(page)
  await page.goto(page.url().replace(/\/(\?.*)?$/, "/stock/2330.TW"), { waitUntil: "networkidle" })
  await page.getByText("參考價").first().waitFor({ timeout: 8000 })
}

/** 每個畫面：路徑、就緒條件、截圖前要做的動作 */
const SHOTS = [
  { name: "ledger", path: "/", ready: "text=總資產" },
  { name: "ledger-draft", path: "/", ready: "text=總資產", action: (page, mobile) => draft(page, mobile) },
  { name: "ledger-transactions", path: "/?view=transactions", ready: "text=月" },
  { name: "ledger-transactions-symbol", path: "/?view=transactions&symbol=2330.TW", ready: "text=只看 2330" },
  { name: "ledger-dividends", path: "/?view=dividends", ready: "text=已入帳" },
  // 績效：示範帳本含美股（沒有可商用的價格）→ 一開始是空狀態（只留帳戶選單）；只看新台幣帳戶才有區間、基準與圖表
  { name: "performance-empty", path: "/?view=performance", ready: "text=績效還算不出來" },
  { name: "ledger-performance", path: "/?view=performance", ready: "text=績效還算不出來", action: performanceTwd },
  // 手機底部列的其他狀態：待簽名、捲到最底（最後一行沒有被底部列蓋住）
  { name: "shell-dock-pending", path: "/", ready: "text=總資產", mobileOnly: true, action: pendingDock },
  { name: "shell-dock-bottom", path: "/stock/2330.TW", ready: "text=參考價", mobileOnly: true, action: toBottom },
  { name: "stock-2330-overview", path: "/stock/2330.TW", ready: "text=參考價" },
  // 總覽第一層（估值句、刻度尺、鍵值格）與第二層（事件表）；2317 持有中、成本在區間外、現在在中段（成本標籤要換到第二行）
  { name: "stock-2330-key", path: "/stock/2330.TW", ready: "text=參考價", action: toSection("ov-key") },
  { name: "stock-2317-key", path: "/stock/2317.TW", ready: "text=參考價", action: toSection("ov-key") },
  { name: "stock-2330-events", path: "/stock/2330.TW", ready: "text=參考價", action: toSection("ov-events") },
  { name: "stock-aapl-overview", path: "/stock/AAPL", ready: "text=關於「Apple」" },
  { name: "stock-2330-analyst", path: "/stock/2330.TW", ready: "text=參考價", action: analyst },
  { name: "stock-2454-analyst-searching", path: "/stock/2454.TW", ready: "text=參考價", action: analystSearch(/正在找近期媒體報導/) },
  { name: "stock-2881-analyst-empty", path: "/stock/2881.TW", ready: "text=參考價", action: analystSearch("近期查無法人報導") },
  { name: "stock-2409-analyst-unavailable", path: "/stock/2409.TW", ready: "text=參考價", action: analystSearch(/法人觀點暫時查不到/) },
  { name: "ledger-recurring-marks", path: "/", ready: "text=總資產", action: recurringMarks },
  { name: "stock-2330-valuation", path: "/stock/2330.TW?tab=valuation", ready: "text=各倍數對應的股價", action: toTabs },
  { name: "stock-2330-valuation-howto", path: "/stock/2330.TW?tab=valuation", ready: "text=各倍數對應的股價", action: valuationHowTo },
  // 沒有報價（商用模式的美股）：估值只有一個空狀態；ETF 沒有河流圖，空狀態下面接淨值與殖利率
  { name: "stock-aapl-valuation", path: "/stock/AAPL?tab=valuation", ready: "text=沒有報價，算不出估值", action: toTabs },
  { name: "stock-0050-valuation", path: "/stock/0050.TW?tab=valuation", ready: "text=ETF 沒有本益比與股價淨值比河流圖", action: toTabs },
  { name: "stock-2330-chips", path: "/stock/2330.TW?tab=chips", ready: "text=上市股票不顯示逐檔三大法人", action: toTabs },
  { name: "stock-6488-chips", path: "/stock/6488.TWO?tab=chips", ready: "text=三大法人買賣超", action: toTabs },
  { name: "stock-2330-foreign-ask", path: "/stock/2330.TW?tab=chips", ready: "text=上市股票不顯示逐檔三大法人", action: foreignAsk },
  { name: "ledger-closed", path: "/", ready: "text=總資產", action: closed },
  { name: "ledger-recurring-draft", path: "/", ready: "text=總資產", action: recurringDraft },
  { name: "ai-model-answer", path: "/", ready: "text=總資產", action: modelAnswer },
  { name: "ai-model-thread", path: "/", ready: "text=總資產", action: modelThread },
  // 美股的面板（提示字「買 AAPL 10 股」）與河流圖提問；沒有建議的頁面（設定）：輸入框上方是最近的對話
  { name: "ai-aapl-home", path: "/stock/AAPL", ready: "text=關於「Apple」", action: openAi },
  { name: "ai-aapl-river", path: "/stock/AAPL", ready: "text=關於「Apple」", action: aaplRiver },
  { name: "ai-settings-recent", path: "/settings", ready: "text=新增定期定額", action: openAi },
  { name: "history-undo", path: "/history", ready: "text=發起新對話", action: historyUndo },
  { name: "stock-2330-why-answer", path: "/stock/2330.TW", ready: "text=參考價", action: whyMove },
  { name: "ledger-pending-home", path: "/", ready: "text=總資產", action: pendingHome },
  { name: "ai-search", path: "/", ready: "text=總資產", mobileOnly: true, action: mobileSearch },
  { name: "stock-2603-past", path: "/stock/2603.TW", ready: "text=過去的持有" },
  // 新聞報導：媒體原標題＋媒體＋時間＋原文連結（GDELT＋SearXNG、兩者不足時 AI 搜尋補缺），沒有報導時的空狀態，美股英文媒體；資料來源頁的收集方式說明
  { name: "stock-2330-news", path: "/stock/2330.TW", ready: "text=參考價", action: toNews },
  { name: "stock-2330-news-more", path: "/stock/2330.TW", ready: "text=參考價", action: newsMore },
  { name: "stock-2317-news-empty", path: "/stock/2317.TW", ready: "text=參考價", action: toNews },
  { name: "stock-nvda-news", path: "/stock/NVDA", ready: "text=新聞報導", action: toNews },
  { name: "data-sources-gdelt", path: "/data-sources", ready: "text=GDELT DOC 2.0 新聞索引", action: gdeltSource },
  { name: "data-sources-news", path: "/data-sources", ready: "text=GDELT DOC 2.0 新聞索引", action: otherSources },
  // 相關股票（基準／成分股、關係企業、同業；ETF 頁同指數）、關於〈公司〉（維基百科節錄／AI 簡介＋官方資料）、上市股票外資持股前 20 名
  { name: "stock-2330-related", path: "/stock/2330.TW", ready: "text=參考價", action: toSection("ov-related") },
  { name: "stock-6488-related", path: "/stock/6488.TWO", ready: "text=參考價", action: toSection("ov-related") },
  { name: "stock-0050-related", path: "/stock/0050.TW", ready: "text=參考價", action: toSection("ov-related") },
  { name: "stock-2330-about", path: "/stock/2330.TW", ready: "text=參考價", action: toSection("ov-company") },
  { name: "stock-6488-about", path: "/stock/6488.TWO", ready: "text=參考價", action: toSection("ov-company") },
  { name: "stock-aapl-about", path: "/stock/AAPL", ready: "text=關於「Apple」", action: toSection("ov-company") },
  { name: "stock-3711-chips", path: "/stock/3711.TW?tab=chips", ready: "text=前 20 名第 12 名", action: toForeign },
  { name: "data-sources-wikipedia", path: "/data-sources", ready: "text=中文維基百科條目（開頭節錄）", action: wikiSource },
  // ETF 淨值與折溢價（證期局〈證券投資信託基金每日淨值〉＋同一天的收盤）：0050 有走勢、00878 資料累積中、00679B 淨值晚一天
  { name: "stock-0050-nav", path: "/stock/0050.TW", ready: "text=參考價", action: toSection("ov-key") },
  { name: "stock-00878-nav", path: "/stock/00878.TW", ready: "text=參考價", action: toSection("ov-key") },
  { name: "stock-00679b-nav", path: "/stock/00679B.TWO", ready: "text=參考價", action: toSection("ov-key") },
  { name: "data-sources-nav", path: "/data-sources", ready: "text=證券投資信託基金每日淨值", action: navSource },
  // 美股：SEC EDGAR 的季報（美元、公司會計年度）與 8-K／10-Q／10-K 申報
  { name: "stock-aapl-financials", path: "/stock/AAPL?tab=financials", ready: "text=FY2026Q4", action: toTabs },
  { name: "stock-aapl-events", path: "/stock/AAPL?tab=events", ready: "text=10-K 年度報告", action: toTabs },
  { name: "settings", path: "/settings", ready: "text=新增定期定額" },
  { name: "settings-recurring", path: "/settings", ready: "text=新增定期定額", action: recurring },
  { name: "settings-profile-edited", path: "/settings", ready: "text=新增定期定額", action: editField("顯示名稱", "示範使用者二") },
  { name: "data-sources", path: "/data-sources", ready: "text=上市個股日成交資訊" },
  { name: "data-sources-fx", path: "/data-sources", ready: "text=銀行間新臺幣對美元收盤匯率", action: fxSource },
  { name: "history", path: "/history", ready: "text=發起新對話" },
  { name: "ledger-auto-dividends-transactions", path: "/?view=transactions", ready: "text=月", action: autoEdited },
  { name: "ledger-auto-dividends-dividends", path: "/?view=dividends", ready: "text=已入帳", action: received },
  { name: "ledger-auto-dividends-edit", path: "/?view=transactions", ready: "text=月", action: autoEdit },
  { name: "ai", path: "/", ready: "text=總資產", mobileOnly: true, action: async (page) => {
    await page.getByRole("button", { name: /^問 AI/ }).click()
    await page.waitForTimeout(500)
  } },
  // ── M5 分享：登入、邀請、群組（排行・動態・持股・週報・我的分享・成員・頻道）、成員分享、授權查看 ──
  // mock：`?auth=signed-out` 模擬還沒登入；家族投資（我是擁有者）、大學同學（我是成員、不排名次）、投資讀書會（邀請 club-2026）
  { name: "m5-login", path: "/login?auth=signed-out", ready: "text=用 Discord 登入" },
  { name: "m5-login-error", path: "/login?auth=signed-out&error=oauth_email_unverified", ready: "text=還沒有驗證" },
  { name: "m5-invite-signed-out", path: "/invite/club-2026?auth=signed-out", ready: "text=登入後加入" },
  { name: "m5-invite", path: "/invite/club-2026", ready: "text=分享什麼", action: m5InviteTrades },
  { name: "m5-groups", path: "/groups", ready: "text=大學同學" },
  { name: "m5-group-ranking", path: "/groups/grp_family", ready: "text=元大台灣50" },
  { name: "m5-group-ranking-unranked", path: "/groups/grp_friends", ready: "text=依加入順序列出" },
  { name: "m5-group-feed", path: "/groups/grp_family?tab=feed", ready: "text=加入了群組", action: m5FeedThread },
  { name: "m5-group-holdings", path: "/groups/grp_family?tab=holdings", ready: "text=成員持股" },
  { name: "m5-group-digests", path: "/groups/grp_family?tab=digests", ready: "text=本週報酬" },
  { name: "m5-group-share", path: "/groups/grp_family?tab=share", ready: "text=附上成交價", action: m5ShareAmounts },
  { name: "m5-group-members", path: "/groups/grp_family?tab=members", ready: "text=邀請連結" },
  { name: "m5-group-rename", path: "/groups/grp_family?tab=members", ready: "text=邀請連結", action: editField("群組名稱", "家族投資（2026）") },
  { name: "m5-group-feed-member", path: "/groups/grp_family?tab=feed&member=usr_dad", ready: "text=只看爸爸" },
  { name: "m5-group-channels", path: "/groups/grp_family?tab=channels", ready: "text=Webhook 網址結尾" },
  { name: "m5-member", path: "/groups/grp_family/members/usr_dad", ready: "text=總損益" },
  { name: "m5-member-privacy", path: "/groups/grp_family/members/usr_dad", ready: "text=總損益", action: m5Privacy },
  { name: "m5-member-empty", path: "/groups/grp_family/members/usr_bro", ready: "text=加入了群組" },
  { name: "m5-settings-delegations", path: "/settings", ready: "text=授權給你的人", action: m5Delegations },
  { name: "m5-view-as", path: "/settings", ready: "text=授權給你的人", action: m5ViewAs },
  { name: "m5-view-as-stock", path: "/settings", ready: "text=授權給你的人", action: m5ViewAsStock },
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
