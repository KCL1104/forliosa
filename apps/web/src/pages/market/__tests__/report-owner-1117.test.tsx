import { describe, expect, it } from "vitest"
import { problemText } from "@/pages/market/reports/report-context"

/**
 * 負責人 2026-11-17 決定（第二次試跑後）：驗證器多了私生活、同一段重複、風險不是之後的事、籌碼段離題四種問題，
 * 管理員檢視要看得懂。
 */
describe("管理員檢視的問題代碼", () => {
  it("新的檢查有白話說明", () => {
    expect(problemText("private_life")).toBe("寫了私生活細節")
    expect(problemText("repeated_fact")).toBe("同一件事在同一段重複")
    expect(problemText("risk_not_ahead")).toBe("風險不是之後才會發生的事")
    expect(problemText("chips_off_topic")).toBe("籌碼段寫了法人與資金以外的事")
  })
})
