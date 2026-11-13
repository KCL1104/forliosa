import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api"
import { ChipsTab } from "../tabs/ChipsTab"

vi.mock("@/ai/use-ask", () => ({ useAskAi: () => ({ submit: () => {}, action: () => {}, showDraft: () => {} }) }))

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe("籌碼分頁：上市股票的外資持股比", () => {
  it("掉出最新的前 20 名名單：標題旁不顯示以前在榜的持股比，內文說明不在名單上", async () => {
    const tsmc = await api.getInstrument("2330.TW")
    const real = await api.getChips("2330.TW", "3M")
    // 舊版後端的回應：區間內曾在榜（11/10），最新名單沒有
    vi.spyOn(api, "getChips").mockResolvedValue({ ...real, foreign_holding_pct: [{ t: "2026-11-10", pct: 0.721 }], foreign_top20: null })
    withQueries(<ChipsTab inst={tsmc} />)
    const section = await screen.findByRole("region", { name: "外資持股比" }, { timeout: 3000 })
    expect(section.textContent).not.toContain("72.1")
    expect(within(section).getByText(/不在名單上/)).toBeInTheDocument()
  })
  it("名列前 20 名：標題旁是名次；三大法人的空狀態仍說明原因", async () => {
    const ase = await api.getInstrument("3711.TW")
    withQueries(<ChipsTab inst={ase} />)
    const foreign = await screen.findByRole("region", { name: "外資持股比" }, { timeout: 3000 })
    expect(foreign.textContent).toContain("75.52%・前 20 名第 12 名")
    const inst = screen.getByRole("region", { name: "三大法人買賣超" })
    expect(inst.textContent).toContain("上市股票沒有逐檔三大法人資料")
    // 後端的長說明（OpenAPI、付費商品、上櫃怎麼存檔）不照印
    expect(document.body.textContent).not.toContain("上櫃股票由櫃買中心")
  })
  it("不在前 20 名：三大法人的空狀態只有一句，也說外資持股只有前 20 名", async () => {
    const tsmc = await api.getInstrument("2330.TW")
    withQueries(<ChipsTab inst={tsmc} />)
    const inst = await screen.findByRole("region", { name: "三大法人買賣超" }, { timeout: 3000 })
    expect(inst.textContent).toContain("上市股票沒有逐檔三大法人資料")
    expect(inst.textContent).toContain("外資持股只公布前 20 名。")
    expect(document.body.textContent).not.toContain("OpenAPI")
  })
})
