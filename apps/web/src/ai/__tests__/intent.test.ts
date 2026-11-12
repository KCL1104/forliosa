import { describe, expect, it } from "vitest"
import { normalize, parseIntent, sharesOf } from "@/ai/intent"

const TODAY = "2026-11-12"

describe("記帳指令解析", () => {
  it("買 0050 2 張 52.4", () => {
    expect(parseIntent("買 0050 2 張 52.4", TODAY)).toEqual({ kind: "trade", side: "buy", target: "0050", quantity: 2, unit: "lot", price: 52.4, date: null })
  })
  it("賣 2330 100 股 2400", () => {
    expect(parseIntent("賣 2330 100 股 2400", TODAY)).toMatchObject({ kind: "trade", side: "sell", target: "2330", quantity: 100, unit: "share", price: 2400 })
  })
  it("黏在一起、全形、千分位、@：買進台積電１張＠1,085", () => {
    expect(parseIntent("買進台積電１張＠1,085", TODAY)).toMatchObject({ kind: "trade", side: "buy", target: "台積電", quantity: 1, unit: "lot", price: 1085 })
  })
  it("美股代號不分大小寫：buy nvda 10 股 186.2 → 買 NVDA", () => {
    expect(parseIntent("買 nvda 10 股 186.2", TODAY)).toMatchObject({ kind: "trade", target: "NVDA", quantity: 10, unit: "share", price: 186.2 })
  })
  it("沒有價格時 price 為 null（草稿以最新價估算）", () => {
    expect(parseIntent("買 0050 2 張", TODAY)).toMatchObject({ kind: "trade", price: null })
  })
  it("日期：昨天、11/10、11月10日", () => {
    expect(parseIntent("昨天 買 0050 1 張 52", TODAY)).toMatchObject({ date: "2026-11-11" })
    expect(parseIntent("11/10 賣 2317 1 張 240", TODAY)).toMatchObject({ date: "2026-11-10" })
    expect(parseIntent("11月10日 買 2330 1 張 1080", TODAY)).toMatchObject({ date: "2026-11-10" })
  })
  it("00878 配息 1,100 → 股利入帳", () => {
    expect(parseIntent("00878 配息 1,100", TODAY)).toEqual({ kind: "dividend", target: "00878", amount: 1100, date: null })
    expect(parseIntent("收到 2330 股利 7500 元", TODAY)).toMatchObject({ kind: "dividend", target: "2330", amount: 7500 })
  })
  it("問句不當成指令（即使提到股利或買）", () => {
    expect(parseIntent("下個月我能領多少股利？", TODAY)).toEqual({ kind: "question", text: "下個月我能領多少股利？" })
    expect(parseIntent("現在可以買 2330 嗎？", TODAY).kind).toBe("question")
    expect(parseIntent("今天誰拖累了我的報酬？", TODAY).kind).toBe("question")
  })
  it("只輸入代號或名稱：查股票", () => {
    expect(parseIntent("2330", TODAY)).toEqual({ kind: "lookup", target: "2330" })
    expect(parseIntent("台積電", TODAY)).toEqual({ kind: "lookup", target: "台積電" })
    expect(parseIntent("aapl", TODAY)).toEqual({ kind: "lookup", target: "AAPL" })
  })
  it("缺少數量的買賣不硬猜：當成提問", () => {
    expect(parseIntent("買 0050", TODAY).kind).not.toBe("trade")
    expect(parseIntent("", TODAY)).toEqual({ kind: "empty" })
  })
  it("normalize：全形轉半形、去千分位、中文與數字之間補空白", () => {
    expect(normalize("買０050　２張５２．４")).toBe("買 0050 2 張 52.4")
    expect(normalize("1,234,567")).toBe("1234567")
  })
})

describe("股數換算", () => {
  it("台股：張 × 1,000；寫「股」就是股數", () => {
    expect(sharesOf(2, "lot", false)).toBe(2000)
    expect(sharesOf(100, "share", false)).toBe(100)
  })
  it("沒寫單位：≥ 1,000 視為股數、以下視為張數", () => {
    expect(sharesOf(2, null, false)).toBe(2000)
    expect(sharesOf(2000, null, false)).toBe(2000)
  })
  it("美股一律股數", () => {
    expect(sharesOf(10, "lot", true)).toBe(10)
  })
})
