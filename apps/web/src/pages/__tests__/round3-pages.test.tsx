import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from "@tanstack/react-router"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest"
import * as apiModule from "@/api"
import { api } from "@/api"
import type { Group, MarketStatus } from "@/api/types"
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

  it("授權查看：修改範圍／移除是文字動作，撤銷／查看是外框按鈕（一列最多一顆，沒有墨色實心的主要按鈕）", async () => {
    renderApp("/settings")
    const section = await screen.findByRole("region", { name: "授權查看" }, T)
    const view = await within(section).findByRole("button", { name: "查看爸爸的資產" }, T)
    expect(view.className).toMatch(/\bborder-ctl\b/)
    expect(view.className).not.toMatch(/\bbg-act\b/)
    const row = view.closest("li")!
    expect(within(row).getByRole("button", { name: "移除" }).className).toContain("underline")
    expect(within(row).getAllByRole("button").filter((b) => /\bborder-ctl\b/.test(b.className))).toHaveLength(1)
  })
})

describe("資料來源與授權", () => {
  it("報價：固定一段——沒有盤中即時報價、價格是收盤後公布的收盤價、到證交所看、付費授權還沒買", async () => {
    renderInRouter(<DataSourcesPage />)
    const quotes = await screen.findByRole("region", { name: "報價" }, T)
    expect(quotes.textContent).toContain("沒有盤中即時報價")
    expect(quotes.textContent).toMatch(/收盤後.*公布/)
    expect(quotes.textContent).toMatch(/當天晚上到隔天清晨/)
    expect(quotes.textContent).toMatch(/付費授權，目前沒有購買/)
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
    const dataset = within(group).getByRole("link", { name: /^上市個股日成交資訊/ })
    expect(dataset).toHaveAttribute("href", "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    expect(dataset).toHaveAttribute("target", "_blank")
    expect(document.body.textContent).not.toContain("資料集網址")
    // 每個連結的文字都不一樣（是資料集的名稱）
    const names = within(group).getAllByRole("link").map((a) => a.textContent)
    expect(new Set(names).size).toBe(names.length)
    // 全部展開：每一個資料集的顯名聲明都在頁面上
    await user.click(screen.getByRole("button", { name: "全部展開" }))
    const all = await api.getAttributions()
    for (const d of all.datasets) expect(visible(d.attribution.slice(0, 24))).toBe(true)
    expect(screen.getByRole("button", { name: "全部收合" })).toBeInTheDocument()
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
  it("每股金額與來源標示不在會截斷的那一段裡（放不下時整個換到下一行）；只有名稱會截斷", async () => {
    renderInRouter(<DividendsView />)
    const received = await screen.findByRole("region", { name: "已入帳" }, T)
    const amounts = await within(received).findAllByText(/^每股 /, undefined, T)
    expect(amounts.length).toBeGreaterThan(5)
    for (const amount of amounts) {
      expect(amount.className).toMatch(/\bwhitespace-nowrap\b/)
      expect(amount.closest(".truncate")).toBeNull()
      expect(amount.parentElement!.className).toMatch(/\bshrink-0\b/)
      const row = amount.closest("li")!
      // 名稱（連結）在自己的截斷容器裡
      expect(within(row).getByRole("link").closest(".truncate")).not.toBeNull()
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

  it("預設（最新的收盤價已經進來）：只標「收盤價・11/12（四）」，沒有說明；帳本寫「11/12 收盤」與「今日」", async () => {
    renderApp("/stock/2330.TW")
    await screen.findByText("參考價", undefined, T)
    expect(await screen.findByText(/^收盤價$/, undefined, T)).toBeInTheDocument()
    expect(document.getElementById("main")!.textContent).toContain("收盤價・11/12（四）")
    expect(screen.queryByText(/盤中不更新|還沒公布/)).toBeNull()
    expect(screen.queryByRole("link", { name: /到證交所看即時報價/ })).toBeNull()
    expect(document.body.textContent).not.toMatch(/延遲/)
    cleanup()
    renderApp("/")
    expect(await screen.findByText("11/12 收盤", undefined, T)).toBeInTheDocument()
    expect(screen.getByText("今日")).toBeInTheDocument()
    expect(await screen.findByText("收盤價・今日漲跌", undefined, T)).toBeInTheDocument()
  })

  it("盤中：一行「盤中不更新…」＋到證交所的連結（另開新視窗，只是連結）；帳本的「今日」換成日期", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ is_open: true }))
    renderApp("/stock/2330.TW")
    expect(await screen.findByText("盤中不更新：這是 11/12（四）的收盤價。", undefined, T)).toBeInTheDocument()
    const link = screen.getByRole("link", { name: /^到證交所看即時報價/ })
    expect(link).toHaveAttribute("href", "https://mis.twse.com.tw/stock/fibest.jsp?stock=2330")
    expect(link).toHaveAttribute("target", "_blank")
    expect(link).toHaveAttribute("rel", "noopener noreferrer")
    expect(document.getElementById("main")!.textContent).toContain("收盤價・11/12（四）")
    cleanup()
    renderApp("/")
    expect(await screen.findByText("11/12 收盤・盤中不更新", undefined, T)).toBeInTheDocument()
    // 「今日」損益、「今日漲跌」寫成收盤價的日期
    await waitFor(() => expect(screen.queryByText("今日")).toBeNull())
    expect(await screen.findByText("收盤價・11/12 漲跌", undefined, T)).toBeInTheDocument()
    const hero = screen.getByText("11/12 收盤・盤中不更新").closest("div")!
    expect(within(hero).getByText("11/12", { selector: "dt" })).toBeInTheDocument()
  })

  it("收盤後、今天的收盤價還沒公布：一行說明，沒有連結；帳本「11/12 收盤・今天的還沒公布」", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({}))
    vi.spyOn(apiModule, "marketNow").mockReturnValue(new Date("2026-11-13T15:10:00+08:00"))
    renderApp("/stock/2330.TW")
    expect(await screen.findByText("今天的收盤價還沒公布，這是 11/12（四）的收盤價。", undefined, T)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /到證交所看即時報價/ })).toBeNull()
    cleanup()
    renderApp("/")
    expect(await screen.findByText("11/12 收盤・今天的還沒公布", undefined, T)).toBeInTheDocument()
  })

  it("美股：維持「沒有報價」，沒有收盤價的標示與說明（就算是盤中）", async () => {
    vi.spyOn(api, "getMarketStatus").mockResolvedValue(status({ is_open: true }))
    renderApp("/stock/AAPL")
    expect(await screen.findByText("沒有報價", undefined, T)).toBeInTheDocument()
    await screen.findByRole("region", { name: "關於「Apple」" }, T)
    expect(screen.queryByText(/盤中不更新/)).toBeNull()
    expect(screen.queryByRole("link", { name: /到證交所看即時報價/ })).toBeNull()
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
