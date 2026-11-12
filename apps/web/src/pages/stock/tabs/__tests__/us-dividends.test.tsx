import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { api } from "@/api"
import { DividendsTab } from "../DividendsTab"
import { FinancialsTab } from "../FinancialsTab"

function withQueries(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

// 預設的商用模式：美股沒有可商用的配息來源，股利是空陣列
describe("美股 ETF 的配息空狀態", () => {
  it("股利分頁說「沒有可商用來源」，不說成過去沒有配息", async () => {
    const voo = await api.getInstrument("VOO")
    withQueries(<DividendsTab inst={voo} position={null} />)
    expect(await screen.findByText(/美股目前沒有可商用的配息資料來源/, undefined, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText(/過去沒有配息紀錄/)).toBeNull()
  })
  it("財務分頁不再叫人去看股利分頁", async () => {
    const voo = await api.getInstrument("VOO")
    const { container } = withQueries(<FinancialsTab inst={voo} />)
    expect(container.textContent).toContain("美股目前也沒有可商用的配息資料來源")
    expect(container.textContent).not.toContain("「股利」分頁")
  })
})
