import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import * as apiModule from "@/api"
import { api } from "@/api"
import type { Group, MarketStatus, TwClose } from "@/api/types"
import { kaiSize } from "@/ai/kai-size"
import { RangeChips } from "@/components/segmented"
import { textAction } from "@/components/text-action"
import { createAppRouter } from "@/router"
import { DataSourcesPage } from "@/pages/data-sources/DataSourcesPage"
import { DigestsTab } from "@/pages/groups/tabs/DigestsTab"
import { FeedTab } from "@/pages/groups/tabs/FeedTab"
import { DividendsView } from "@/pages/ledger/DividendsView"
import { AboutCompany } from "@/pages/stock/AboutCompany"
import { KeyGrid, type KeyItem } from "@/pages/stock/tabs/kit"

/**
 * 第三輪（頁面）：楷體只有一種排法、觸控目標、方肩的表情小格、設定列的動作一套語法、
 * 區塊標題一個字級、資料來源收合、手機股利列的每股金額、鍵值格在手機不留半列，
 * 以及「價格是收盤價」的標示（盤中、收盤後還沒公布、其他）。
 */
beforeAll(() => {
  window.scrollTo = () => {}
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
  Element.prototype.scrollIntoView ??= () => {}
  window.matchMedia ??= ((query: string) => ({
    matches: false, media: query, onchange: null, addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const T = { timeout: 8000 }
const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })
function renderInRouter(ui: React.ReactNode) {
  const router = createRouter({ routeTree: createRootRoute({ component: () => <>{ui}</> }), history: createMemoryHistory({ initialEntries: ["/"] }) })
  return render(
    <QueryClientProvider client={client()}>
      <RouterProvider router={router as never} />
    </QueryClientProvider>,
  )
}
function renderApp(path: string) {
  const qc = client()
  const router = createAppRouter(qc, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

describe("楷體只有一種排法（.ai-voice＋KaiText，大小同對話裡的回答）", () => {
  const sameAsAnswers = (p: Element) => {
    expect(p).toHaveClass("ai-voice")
    // 一段話：手機 18px、桌面 17px、行高 1.8（和 AI 面板的回答同一組 class）
    for (const c of kaiSize.page.split(" ")) expect(p).toHaveClass(c)
    expect(p.className).not.toMatch(/\bfont-ai\b|\btext-xl\b|leading-relaxed|leading-snug/)
    // 漢字的片段收字距、數字和單位不拆行
    expect(p.querySelector(".kai-han")).not.toBeNull()
  }

  it("群組週報的摘要", async () => {
    const family: Group = await api.getGroup("grp_family")
    renderInRouter(<DigestsTab group={family} />)
    const figure = await screen.findByText("0.6%", undefined, T)
    expect(figure).toHaveClass("kai-num")
    sameAsAnswers(figure.closest("p")!)
  })

  it("AI 寫的公司簡介（維基百科節錄不是模型寫的，仍是墨色 Noto Sans）", async () => {
    renderInRouter(<AboutCompany inst={await api.getInstrument("6488.TWO")} />)
    const section = await screen.findByRole("region", { name: "關於「環球晶」" }, T)
    sameAsAnswers(section.querySelector(".ai-voice")!)
    cleanup()
    renderInRouter(<AboutCompany inst={await api.getInstrument("2330.TW")} />)
    const tsmc = await screen.findByRole("region", { name: "關於「台積電」" }, T)
    expect(tsmc.querySelector(".ai-voice")).toBeNull()
  })

  it("模型寫的「為什麼」是一行的楷體（20px），一樣經過 KaiText；規則句仍是墨色", async () => {
    const why = await api.getWhy("2330.TW")
    vi.spyOn(api, "getWhy").mockResolvedValue({ ...why, show: true, headline: "台積電今天上漲 4.83%，成交量是近 20 日均量的 2.1 倍。", ai: true } as typeof why)
    renderApp("/stock/2330.TW")
    const figure = await screen.findByText("4.83%", { selector: ".kai-num" }, T)
    const line = figure.closest(".ai-voice")!
    for (const c of kaiSize.line.split(" ")) expect(line).toHaveClass(c)
    expect(line.querySelector(".kai-han")).not.toBeNull()
    expect(line.className).not.toMatch(/leading-snug|\btext-lg\b/)
  })
})

describe("觸控目標與方肩的小格", () => {
  it("文字動作（編輯、修改、移除、留言）：觸控時 44px 高，可按範圍左右各多 10px", () => {
    expect(textAction).toMatch(/\bpointer-coarse:min-h-11\b/)
    expect(textAction).toMatch(/\brelative\b/)
    expect(textAction).toMatch(/pointer-coarse:before:-inset-x-2\.5/)
  })

  it("一個字的選項（股數顯示的「股」）觸控時至少 44px 寬", () => {
    render(<RangeChips label="股數顯示" value="lot" onChange={() => {}} options={[{ value: "lot", label: "張＋股" }, { value: "share", label: "股" }]} />)
    for (const chip of screen.getAllByRole("radio")) {
      expect(chip.className).toMatch(/\bpointer-coarse:h-11\b/)
      expect(chip.className).toMatch(/\bpointer-coarse:min-w-11\b/)
    }
  })

  it("動態：表情是方肩的小格（4px，不是膠囊），自己按過的是選取語法 (b)；名字連結觸控時有 44px", async () => {
    const family: Group = await api.getGroup("grp_family")
    renderInRouter(<FeedTab group={family} />)
    const dad = (await screen.findAllByRole("listitem", undefined, T)).find((li) => /爸爸\s*買進\s*台積電/.test(li.textContent ?? ""))!
    const like = within(dad).getByRole("button", { name: /^讚 2/ })
    expect(like.className).not.toMatch(/rounded-full/)
    expect(like.className).toMatch(/\bpointer-coarse:min-h-11\b/)
    expect(like.className).toMatch(/\bpointer-coarse:min-w-11\b/)
    const chip = like.querySelector("span")!
    expect(chip.className).toMatch(/\brounded-sm\b/)
    expect(chip.className).toMatch(/\bsel-chip\b/)
    expect(chip.className).not.toMatch(/rounded-full/)
    expect(chip).not.toHaveAttribute("data-pressed")
    await userEvent.setup().click(like)
    const mine = await within(dad).findByRole("button", { name: /^讚 3，你按過/ }, T)
    expect(mine).toHaveAttribute("aria-pressed", "true")
    expect(mine.querySelector("span")).toHaveAttribute("data-pressed")
    // 整個動態分頁沒有膠囊（頭像的圓除外）
    const pills = [...document.querySelectorAll("button, button *")].filter((el) => /rounded-full/.test(el.getAttribute("class") ?? ""))
    expect(pills).toHaveLength(0)
    const name = within(dad).getByRole("link", { name: "爸爸" })
    expect(name.className).toMatch(/pointer-coarse:py-3/)
    expect(name.className).toMatch(/pointer-coarse:px-2/)
    expect(name.className).toMatch(/pointer-coarse:-mx-2/)
  })

  it("留言框沒有原生的拖曳把手", async () => {
    const user = userEvent.setup()
    const family: Group = await api.getGroup("grp_family")
    renderInRouter(<FeedTab group={family} />)
    const dad = (await screen.findAllByRole("listitem", undefined, T)).find((li) => /爸爸\s*買進\s*台積電/.test(li.textContent ?? ""))!
    await user.click(within(dad).getByRole("button", { name: /^留言/ }))
    const box = await within(dad).findByRole("textbox", { name: "留言" }, T)
    expect(box.className).toMatch(/\bresize-none\b/)
  })
})

describe("設定：列上的動作一套語法、區塊標題和其他頁面同一級", () => {
  it("定期定額：修改是文字動作、刪除是有字的外框按鈕（沒有只有圖示的按鈕）；區塊標題 20px", async () => {
    renderApp("/settings")
    const section = await screen.findByRole("region", { name: "定期定額" }, T)
    const edit = await within(section).findByRole("button", { name: "修改「元大台灣50」定期定額" }, T)
    expect(edit).toHaveTextContent("修改")
    expect(edit.className).toContain("underline")
    const remove = within(section).getByRole("button", { name: "刪除「元大台灣50」定期定額" })
    expect(remove).toHaveTextContent("刪除")
    expect(remove.querySelector("svg")).toBeNull()
    expect(remove.className).toMatch(/\bborder-ctl\b/)
    const iconOnly = within(section).getAllByRole("button").filter((b) => b.querySelector("svg") && !b.textContent?.trim())
    expect(iconOnly).toHaveLength(0)
    // 區塊標題：全部 20px（text-xl）、底下一條印刷線
    const titles = (await screen.findAllByRole("heading", { level: 2 }, T)).filter((h) => document.getElementById("main")!.contains(h))
    expect(titles.map((h) => h.textContent)).toEqual(expect.arrayContaining(["個人資料", "顯示", "隱私", "計算", "券商帳戶", "定期定額", "授權查看"]))
    for (const h of titles) {
      expect(h.className).toMatch(/\btext-xl\b/)
      expect(h.closest("header")!.className).toMatch(/\bborder-print\b/)
    }
  })

  it("授權查看：修改範圍是文字動作；撤銷／移除（拿掉這一列）和查看是外框按鈕，沒有墨色實心的主要按鈕", async () => {
    renderApp("/settings")
    const section = await screen.findByRole("region", { name: "授權查看" }, T)
    const view = await within(section).findByRole("button", { name: "查看爸爸的資產" }, T)
    expect(view.className).toMatch(/\bborder-ctl\b/)
    expect(view.className).not.toMatch(/\bbg-act\b/)
    const row = view.closest("li")!
    // 「移除」和「撤銷」「刪除」同一種寫法：列尾的外框按鈕（不是只有底線的文字連結）
    const remove = within(row).getByRole("button", { name: "移除爸爸給你的授權" })
    expect(remove).toHaveTextContent("移除")
    expect(remove.className).toMatch(/\bborder-ctl\b/)
    expect(remove.className).not.toContain("underline")
    const buttons = within(row).getAllByRole("button")
    expect(buttons.at(-1)).toBe(remove)
    expect(buttons.filter((b) => /\bbg-act\b/.test(b.className))).toHaveLength(0)
    // 你授權的人那一列：「修改範圍」是文字動作、「撤銷」是列尾的外框按鈕
    const revoke = within(section).getAllByRole("button", { name: "撤銷" })[0]!
    expect(revoke.className).toMatch(/\bborder-ctl\b/)
    expect(within(revoke.closest("li")!).getByRole("button", { name: "修改範圍" }).className).toContain("underline")
  })
})

describe("資料來源與授權", () => {
  it("報價：固定一段——都是收盤價、沒有盤中報價、收盤後公布、到證交所看、付費授權沒有買", async () => {
    renderInRouter(<DataSourcesPage />)
    const quotes = await screen.findByRole("region", { name: "報價" }, T)
    expect(quotes.textContent).toContain("Forliosa 的股價都是收盤價，沒有盤中報價。")
    expect(quotes.textContent).toMatch(/收盤後.*公布/)
    // 平常幾點更新（實測的時間）：證交所的下載網址開著時，上市下午就進來；上櫃晚上
    const times = within(quotes).getByRole("list", { name: "收盤價平常什麼時候更新" })
    expect(times.textContent).toContain("上市：下午 2:00–2:30（證交所在政府資料開放平臺登記的下載網址）；下午拿不到時晚上 8:30–11:45")
    expect(times.textContent).toContain("上櫃：晚上 8:30–11:45，少數日子到半夜 1:30")
    expect(quotes.textContent).toMatch(/還沒更新時，帳本與個股頁會寫預計幾點更新/)
    expect(quotes.textContent).toMatch(/盤中報價要付費授權，Forliosa 沒有買。/)
    const link = within(quotes).getByRole("link", { name: /基本市況報導/ })
    expect(link).toHaveAttribute("href", "https://mis.twse.com.tw/")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
  })

  it("資料集依機關收合：收著只列名稱；展開才是完整顯名聲明，資料集名稱就是連結（沒有幾十個「資料集網址」）", async () => {
    const user = userEvent.setup()
    renderInRouter(<DataSourcesPage />)
    const twse = await screen.findByRole("button", { name: /^臺灣證券交易所/ }, T)
    expect(twse).toHaveAttribute("aria-expanded", "false")
    // 收著：看得到用了哪些資料集，但沒有逐條的顯名聲明
    expect(screen.getByText(/上市個股日成交資訊、上市個股日本益比/)).toBeInTheDocument()
    const statement = "臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版"
    const visible = (text: string) => [...document.querySelectorAll("main li, li")].some((li) => li.textContent?.includes(text) && !li.closest("[hidden]"))
    expect(visible(statement)).toBe(false)
    await user.click(twse)
    expect(twse).toHaveAttribute("aria-expanded", "true")
    expect(visible(statement)).toBe(true)
    const group = twse.closest("section")!
    // 同一份資料的兩個網址（OpenAPI、證交所在政府資料開放平臺登記的下載網址）：報讀時多唸網站，聽得出不同
    const dataset = within(group).getByRole("link", { name: /^上市個股日成交資訊（openapi\.twse\.com\.tw，/ })
    expect(dataset).toHaveAttribute("href", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    expect(dataset).toHaveAttribute("target", "_blank")
    expect(within(group).getByRole("link", { name: /^上市個股日成交資訊（www\.twse\.com\.tw，/ })).toHaveAttribute("href", "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=open_data")
    expect(document.body.textContent).not.toContain("資料集網址")
    // 每個連結報讀的名稱都不一樣（是資料集的名稱）
    const names = within(group).getAllByRole("link").map((a) => a.getAttribute("aria-label") ?? a.textContent)
    expect(new Set(names).size).toBe(names.length)
    // 全部展開：每一個資料集的顯名聲明都在頁面上
    await user.click(screen.getByRole("button", { name: "全部展開" }))
    const all = await api.getAttributions()
    for (const d of all.datasets) expect(visible(d.attribution.slice(0, 24))).toBe(true)
    expect(screen.getByRole("button", { name: "全部收合" })).toBeInTheDocument()
  })

  it("美股收盤價（Databento）有開：報價說紐約的日期與更新時間，授權條款說來源與從哪天開始；「沒有買」不再列美股報價", async () => {
    renderInRouter(<DataSourcesPage />)
    const quotes = await screen.findByRole("region", { name: "報價" }, T)
    expect(quotes.textContent).toContain("美股是紐約的收盤價，日期寫紐約的交易日。")
    expect(quotes.textContent).toMatch(/台北時間清晨 6 點（美國夏令時間清晨 5 點）/)
    expect(quotes.textContent).toMatch(/剛加入的大約 10 分鐘內補上 2024 年 7 月以來的收盤價。/)
    const licence = screen.getByRole("region", { name: "授權條款" })
    expect(licence.textContent).toContain("台股行情、匯率、公司資料與公告來自政府開放資料")
    expect(licence.textContent).toContain("美股的收盤價來自 Databento（Nasdaq NLS Plus 的官方合併收盤），從 2024 年 7 月開始，是沒有還原股票分割與股利的原始價格。")
    // 只說來源，不說可商用或有展示授權
    expect(licence.textContent).not.toMatch(/Databento[^。]*(可商用|授權)/)
    const notUsed = screen.getByRole("region", { name: "沒有使用的來源" })
    expect(notUsed.textContent).toContain("盤中走勢、上市股票的逐檔三大法人要付費授權，Forliosa 沒有買。")
    expect(notUsed.textContent).not.toContain("美股報價")
    // 資料集：Databento 自己一組，顯名聲明照後端的原文
    expect(screen.getByRole("button", { name: /^Databento/ })).toHaveTextContent("1 個資料集")
  })

  it("證交所的下載網址關著（後端沒有列 twse-opendata）：上市寫晚上、晚的時候隔天清晨，不寫下午", async () => {
    const get = api.getAttributions
    vi.spyOn(api, "getAttributions").mockImplementation(async () => {
      const a = await get()
      return { ...a, datasets: a.datasets.filter((d) => !d.key.startsWith("twse-opendata/")) }
    })
    renderInRouter(<DataSourcesPage />)
    const times = await screen.findByRole("list", { name: "收盤價平常什麼時候更新" }, T)
    expect(times.textContent).toContain("上市：晚上 8:30–11:45，晚的時候隔天清晨 5:20–5:45")
    expect(times.textContent).not.toContain("下午")
  })

  it("授權條款裡的網址只在分隔符號後面斷行（不用 break-all），條款文字還在", async () => {
    renderInRouter(<DataSourcesPage />)
    const licence = await screen.findByRole("region", { name: "授權條款" }, T)
    const url = within(licence).getByRole("link", { name: /^https:\/\/data\.gov\.tw\/license/ })
    expect(url.className).not.toMatch(/break-all/)
    expect(url.querySelectorAll("wbr").length).toBeGreaterThan(0)
    expect(licence.textContent).toContain("此開放資料依政府資料開放授權條款")
    for (const h of screen.getAllByRole("heading", { level: 2 })) expect(h.className).toMatch(/\btext-xl\b/)
  })
})

describe("手機的股利列：每股金額一定看得到", () => {
  it("每股金額與來源標示不在名稱那一段裡（放不下時整個換到下一行）；名稱放不下時換行、不截斷（2026-11-21）", async () => {
    renderInRouter(<DividendsView />)
    const received = await screen.findByRole("region", { name: "已入帳" }, T)
    const amounts = await within(received).findAllByText(/^每股 /, undefined, T)
    expect(amounts.length).toBeGreaterThan(5)
    for (const amount of amounts) {
      expect(amount.className).toMatch(/\bwhitespace-nowrap\b/)
      expect(amount.closest(".truncate")).toBeNull()
      expect(amount.parentElement!.className).toMatch(/\bshrink-0\b/)
      const row = amount.closest("li")!
      // 名稱（連結）在自己的那一段裡，放不下時換行（不截斷）
      const name = within(row).getByRole("link").closest("[data-name]")!
      expect(name).not.toBeNull()
      expect(name.className).not.toMatch(/truncate/)
      expect(amount.closest("[data-name]")).toBeNull()
    }
  })
})

describe("鍵值格：手機 2 欄不留半列的孤格", () => {
  const items = (n: number, wide: number[] = []): KeyItem[] => Array.from({ length: n }, (_, i) => ({ label: `項目${i + 1}`, value: String(i + 1), wide: wide.includes(i) }))
  /** 照 class 模擬手機的 2 欄排版：回傳「佔半列、旁邊沒有東西」的格子數 */
  const halfRows = (container: HTMLElement) => {
    let col = 0
    let orphans = 0
    for (const cell of container.querySelectorAll("dl > div")) {
      if (cell.className.includes("max-lg:col-span-2")) {
        if (col === 1) orphans++
        col = 0
      } else col = col === 0 ? 1 : 0
    }
    return orphans + (col === 1 ? 1 : 0)
  }

  it("1 到 24 格、各種 wide 的位置：每一列都排滿（總覽 19 格、15 格也是）", () => {
    for (let n = 1; n <= 24; n++) {
      for (const wide of [[], [0], [n - 1], [Math.floor(n / 2)], [2, 5], [1, 2, 3]]) {
        const { container, unmount } = render(<KeyGrid items={items(n, wide.filter((i) => i >= 0 && i < n))} />)
        expect(halfRows(container), `${n} cells, wide ${wide.join(",")}`).toBe(0)
        unmount()
      }
    }
  })
})

describe("價格是收盤價（沒有盤中即時報價）", () => {
  const status = (o: Partial<MarketStatus["tw"]>): MarketStatus => ({ tw: { date: "2026-11-13", is_trading_day: true, is_open: false, open: "09:00", close: "13:30", ...o } })

  it("預設（最新的收盤價已經進來）：只標「收盤價・11/12（四）」，沒有說明；帳本寫「收盤價・11/12（四）」與「今日」（2026-11-21 起和個股頁同一個寫法）", async () => {
    renderApp("/stock/2330.TW")
    await screen.findByText("參考價", undefined, T)
    expect(await screen.findByText(/^收盤價$/, undefined, T)).toBeInTheDocument()
    expect(document.getElementById("main")!.textContent).toContain("收盤價・11/12（四）")
    expect(screen.queryByText(/盤中不更新|還沒公布/)).toBeNull()
    expect(screen.queryByRole("link", { name: /到證交所看即時報價/ })).toBeNull()
    expect(document.body.textContent).not.toMatch(/延遲/)
    cleanup()
    renderApp("/")
    expect(await screen.findByText("收盤價・11/12（四）", undefined, T)).toBeInTheDocument()
    expect(within(screen.getByRole("region", { name: "總資產" })).getByText("今日")).toBeInTheDocument()
    expect(await screen.findByText("收盤價・今日漲跌", undefined, T)).toBeInTheDocument()
  })

  it("盤中：一行「盤中不更新…」＋到證交所的連結（另開新視窗，只是連結）；帳本的「今日」換成日期", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ is_open: true }))
    renderApp("/stock/2330.TW")
    // 一行：「盤中不更新・到證交所看即時報價 ↗」，不重複收盤價的日期
    const note = (await screen.findByText("盤中不更新", undefined, T)).closest("p")!
    expect(note.textContent).toMatch(/^盤中不更新・到證交所看即時報價/)
    expect(note.textContent).not.toMatch(/11\/12/)
    const link = within(note).getByRole("link", { name: /^到證交所看即時報價/ })
    expect(link).toHaveAttribute("href", "https://mis.twse.com.tw/stock/detail-item?id=tse_2330.tw&ex=tse&lang=zhHant")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(document.getElementById("main")!.textContent).toContain("收盤價・11/12（四）")
    // 大字旁的漲跌是 11/12 那天的，不是今天的：和帳本一樣標日期
    expect(screen.getByText("11/12 漲跌")).toBeInTheDocument()
    cleanup()
    renderApp("/")
    expect(await screen.findByText("收盤價・11/12（四）・盤中不更新", undefined, T)).toBeInTheDocument()
    // 「今日」損益、「今日漲跌」寫成收盤價的日期
    await waitFor(() => expect(screen.queryByText("今日")).toBeNull())
    expect(await screen.findByText("收盤價・11/12 漲跌", undefined, T)).toBeInTheDocument()
    const hero = screen.getByText("收盤價・11/12（四）・盤中不更新").closest("div")!
    expect(within(hero).getByText("11/12", { selector: "dt" })).toBeInTheDocument()
  })

  it("收盤後、今天的收盤價還沒公布（舊版後端，沒有 closes）：一行說明，沒有連結；帳本「收盤價・11/12（四）・今天的還沒公布」", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({}))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-13T15:10:00+08:00"))
    renderApp("/stock/2330.TW")
    expect(await screen.findByText("今天的收盤價還沒公布", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /到證交所看即時報價/ })).toBeNull()
    expect(screen.getByText("11/12 漲跌")).toBeInTheDocument()
    cleanup()
    renderApp("/")
    const label = await screen.findByText("收盤價・11/12（四）", undefined, T)
    expect(label.parentElement!.textContent).toContain("收盤價・11/12（四）・今天的還沒公布")
  })

  /** 上市、上櫃的收盤價各自什麼時候進來（產品負責人 2026-11-16）：`tw.closes` 的時間窗 */
  const closes = (o: { twse?: Partial<TwClose>; tpex?: Partial<TwClose> } = {}): TwClose[] => [
    { market: "TWSE", session: "2026-11-13", stored: false, latest: "2026-11-12", interim: false, expected_from: "2026-11-13T14:00:00+08:00", expected_to: "2026-11-13T14:30:00+08:00", ...o.twse },
    { market: "TPEX", session: "2026-11-13", stored: false, latest: "2026-11-12", interim: false, expected_from: "2026-11-13T20:30:00+08:00", expected_to: "2026-11-13T23:45:00+08:00", ...o.tpex },
  ]

  it("收盤後 13:40：個股頁寫這個市場預計幾點更新（上市下午、上櫃今晚）；帳本一行並列兩個市場", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ closes: closes() }))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-13T13:40:00+08:00"))
    renderApp("/stock/2330.TW")
    expect(await screen.findByText("今天的收盤價預計下午 2:00–2:30 更新", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("11/12 漲跌")).toBeInTheDocument()
    cleanup()
    renderApp("/stock/6488.TWO")
    expect(await screen.findByText("今天的收盤價預計今晚 8:30–11:45 更新", undefined, T)).toBeInTheDocument()
    cleanup()
    renderApp("/")
    const label = await screen.findByText("收盤價・11/12（四）", undefined, T)
    await waitFor(() => expect(label.parentElement!.textContent).toContain("收盤價・11/12（四）・上市預計下午 2:30 前更新・上櫃預計今晚更新"))
    expect(await screen.findByText("收盤價・11/12 漲跌", undefined, T)).toBeInTheDocument()
  })

  it("上市進來了、上櫃還沒：帳本日期分開寫、只說上櫃；「今日」不寫（每一檔是它自己那天的漲跌）", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ closes: closes({ twse: { stored: true, latest: "2026-11-13", expected_from: null, expected_to: null } }) }))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-13T15:00:00+08:00"))
    const getHoldings = api.getHoldings
    vi.spyOn(api, "getHoldings").mockImplementation(async (id) =>
      (await getHoldings(id)).map((h) => ({ ...h, price_date: h.market === "TWSE" && h.price !== null ? "2026-11-13" : h.price_date })),
    )
    renderApp("/")
    const label = await screen.findByText("收盤價・上市 11/13・上櫃 11/12", undefined, T)
    expect(label.parentElement!.textContent).toContain("上櫃預計今晚 8:30–11:45 更新")
    const hero = label.closest("div")!
    await waitFor(() => expect(within(hero).getByText("當日", { selector: "dt" })).toBeInTheDocument())
    expect(hero.textContent).not.toMatch(/今日/)
    expect(await screen.findByText("收盤價・當日漲跌", undefined, T)).toBeInTheDocument()
  })

  it("過了半夜還沒進來：說明不會不見，寫在等的是哪一天（11/13 的收盤價還沒公布，預計清晨 5:20–5:40 更新）", async () => {
    const night = closes({
      twse: { expected_from: "2026-11-14T05:20:00+08:00", expected_to: "2026-11-14T05:40:00+08:00" },
      tpex: { stored: true, latest: "2026-11-13", expected_from: null, expected_to: null },
    })
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ date: "2026-11-14", is_trading_day: false, closes: night }))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-14T01:30:00+08:00"))
    renderApp("/stock/2330.TW")
    expect(await screen.findByText("11/13 的收盤價還沒公布，預計清晨 5:20–5:40 更新", undefined, T)).toBeInTheDocument()
  })

  /**
   * 帳本只有美股有價格（Databento 的收盤）：持股只留有價格的美股（`price_date` 是紐約的日期），
   * 總資產的 `as_of` 是紐約 16:00——台北已經是隔天清晨（後端與 mock 的 summary 都這樣挑）
   */
  const usOnlyLedger = (asOf: string, priceDate: string) => {
    const getHoldings = api.getHoldings
    const getSummary = api.getPortfolioSummary
    vi.spyOn(api, "getHoldings").mockImplementation(async (id) =>
      (await getHoldings(id)).filter((h) => h.market === "US" && h.price !== null).map((h) => ({ ...h, price_date: priceDate })),
    )
    vi.spyOn(api, "getPortfolioSummary").mockImplementation(async (id) => {
      const s = await getSummary(id)
      return { ...s, as_of: asOf, allocation: { ...s.allocation, by_market: s.allocation.by_market.filter((m) => m.key === "US") } }
    })
  }
  /** 主數字旁寫紐約的收盤，「今日」換成那一天；不寫台北的日期，也沒有台股的「盤中不更新／今天的還沒公布」 */
  const expectUsHero = async (day: string, taipeiDay: string) => {
    const label = await screen.findByText(`收盤價・${day}（美東）`, undefined, T)
    const hero = label.closest("div")!
    await waitFor(() => expect(within(hero).getByText(day, { selector: "dt" })).toBeInTheDocument())
    expect(hero.textContent).not.toMatch(/今日|盤中不更新|還沒公布/)
    expect(hero.textContent).not.toContain(taipeiDay)
    // 持倉的表頭（手機的兩行列表頭）也是紐約的日期
    expect(await screen.findByText(`收盤價・${day} 漲跌`, undefined, T)).toBeInTheDocument()
    expect(screen.queryByText(/今日漲跌|今日損益/)).toBeNull()
  }

  it("帳本只有美股・週六早上（台北 11/14）：寫紐約週五的「收盤價・11/13（美東）」與「11/13」，不寫週六的日期或「今日」", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ date: "2026-11-14", is_trading_day: false }))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-14T10:00:00+08:00"))
    usOnlyLedger("2026-11-14T05:00:00+08:00", "2026-11-13")
    renderApp("/")
    await expectUsHero("11/13", "11/14")
  })

  it("帳本只有美股・週一台股盤中（台北 11/16 10:00）：仍是「收盤價・11/13（美東）」，沒有台股的「盤中不更新」", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ date: "2026-11-16", is_open: true }))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-16T10:00:00+08:00"))
    usOnlyLedger("2026-11-14T05:00:00+08:00", "2026-11-13")
    renderApp("/")
    await expectUsHero("11/13", "11/14")
  })

  it("帳本只有美股・週二早上（台北 11/17 07:00）：紐約週一的收盤寫「收盤價・11/16（美東）」與「11/16」，不是「今日」", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ date: "2026-11-17" }))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-17T07:00:00+08:00"))
    usOnlyLedger("2026-11-17T05:00:00+08:00", "2026-11-16")
    renderApp("/")
    await expectUsHero("11/16", "11/17")
  })

  /** 美股的收盤（Databento）：紐約 11/13 的收盤，as_of 是紐約 16:00＝台北 11/14 05:00 */
  const usClose = {
    symbol: "AAPL", price: 356.27, prev_close: 350, change: 6.27, change_pct: 0.0179, open: 351, high: 357, low: 349.5, volume: 41_000_000,
    as_of: "2026-11-14T05:00:00+08:00", trade_date: "2026-11-13", is_realtime: false, is_demo: false, source: "databento-equs",
    reference_price: 350, limit_up: null, limit_down: null,
  }
  const withUsClose = () => {
    const getQuote = api.getQuote
    vi.spyOn(api, "getQuote").mockImplementation((symbol) => (symbol === "AAPL" ? Promise.resolve(usClose) : getQuote(symbol)))
  }

  it("美股：收盤寫紐約的日期「11/13 收盤（美東）」、價格帶 US$；不寫台北的「11/14 05:00」，就算是盤中也沒有台股的說明與連結", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ is_open: true }))
    withUsClose()
    renderApp("/stock/AAPL")
    const label = await screen.findByText("11/13 收盤（美東）", undefined, T)
    const header = label.closest("header")!
    expect(header.textContent).toContain("US$")
    // 美股沒有參考價（台股的平盤價）：寫前一個交易日的收盤
    expect(header.textContent).toContain("昨收 US$350.00")
    expect(header.textContent).not.toContain("參考價")
    expect(header.textContent).not.toMatch(/05:00|11\/14|沒有報價/)
    expect(screen.queryByText(/盤中不更新/)).toBeNull()
    expect(screen.queryByRole("link", { name: /到證交所看即時報價/ })).toBeNull()
    expect(document.body.textContent).not.toContain("美股沒有報價，所以沒有走勢和估值")
  })

  it("美股的 1 日走勢空狀態：收盤寫紐約的日期與 US$", async () => {
    const user = userEvent.setup()
    withUsClose()
    renderApp("/stock/AAPL")
    await screen.findByText("11/13 收盤（美東）", undefined, T)
    await user.click(await screen.findByRole("radio", { name: "1日" }, T))
    await screen.findByText("沒有盤中走勢：價格是收盤後公布的收盤價", undefined, T)
    const chart = screen.getByRole("region", { name: "走勢圖" })
    expect(chart.textContent).toContain("11/13 收盤（美東）US$356.27")
    expect(chart.textContent).not.toMatch(/11\/14|美股沒有走勢/)
  })

  it("1 日走勢的空狀態：同一種說法（收盤後公布的收盤價），不承諾盤中資料", async () => {
    const user = userEvent.setup()
    renderApp("/stock/0050.TW")
    await user.click(await screen.findByRole("radio", { name: "1日" }, T))
    expect(await screen.findByText("沒有盤中走勢：價格是收盤後公布的收盤價", undefined, T)).toBeInTheDocument()
    const chart = screen.getByRole("region", { name: "走勢圖" })
    expect(chart.textContent).toContain("收盤價・11/12（四）")
    expect(chart.textContent).not.toMatch(/每分鐘|加入觀察後/)
    expect(within(chart).getByRole("button", { name: "看 5 日走勢" })).toBeInTheDocument()
  })
})
