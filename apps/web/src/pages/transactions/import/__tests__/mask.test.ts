import { describe, expect, it } from "vitest"
import { findSensitiveRanges, MASK_TOKEN, maskTextBoxes, type TextBox } from "../mask"

/** 一行字拆成好幾個框（每個字 10px 寬、14px 高，框和框之間隔 `gap`） */
function line(y: number, parts: string[], gap = 12, x0 = 40): TextBox[] {
  const out: TextBox[] = []
  let x = x0
  for (const str of parts) {
    out.push({ str, x, y, w: str.length * 10, h: 14, horizontal: true })
    x += str.length * 10 + gap
  }
  return out
}

const covered = (r: { x: number; w: number }, from: number, to: number) => r.x <= from && r.x + r.w >= to

describe("找個資", () => {
  it("身分證字號、帳號、標籤後面的值；不碰交易列的日期、代號、金額", () => {
    const text = "客戶姓名：王小明　身分證字號：A123456789　帳號：9A99-0123456　分公司：測試分公司"
    const values = findSensitiveRanges(text).map(([s, e]) => text.slice(s, e))
    expect(values).toEqual(["王小明", "A123456789", "9A99-0123456"])
    expect(findSensitiveRanges("2026/10/01  2026/10/03  現股  買  2330  台積電  1,000  1305.00  1,305,000  1,859  0  -1,306,859")).toEqual([])
    // 居留證（第二碼 8、9）也算；英文字母後面接 9 個數字以外的不算
    expect(findSensitiveRanges("統一證號 B812345678")).toEqual([[5, 15]])
    expect(findSensitiveRanges("A1234567890 X12345678")).toEqual([])
  })

  it("全形的號碼、舊式統一證號、戶名、客戶名稱、沒有冒號的客戶帳號（Big5 報表的寫法）", () => {
    const values = (text: string) => findSensitiveRanges(text).map(([s, e]) => text.slice(s, e))
    expect(values("Ａ１２３４５６７８９")).toEqual(["Ａ１２３４５６７８９"])
    expect(values("FA12345678")).toEqual(["FA12345678"])
    expect(values("統一證號 AC01234567")).toEqual(["AC01234567"])
    expect(values("戶名：王小明")).toEqual(["王小明"])
    expect(values("客戶名稱：王小明　電話：02-0000-0000")).toEqual(["王小明", "02-0000-0000"])
    expect(values("客戶帳號 1234567")).toEqual(["1234567"])
    expect(values("證券帳號：9A99 0123456")).toEqual(["9A99 0123456"])
    // 交易列與表頭照舊不碰
    expect(findSensitiveRanges("１１５/１０/０３  現股  買  ２３３０  台積電  １,０００")).toEqual([])
    expect(findSensitiveRanges("帳戶名稱：一般  成交日期")).toEqual([])
  })

  it("地址到全形空白或兩個空白為止（中間的單一空白算地址的一部分）；電話要接冒號", () => {
    const text = "通訊地址：臺北市中正區範例路 1 段 1 號 1 樓　電話：02-0000-0000"
    expect(findSensitiveRanges(text).map(([s, e]) => text.slice(s, e))).toEqual(["臺北市中正區範例路 1 段 1 號 1 樓", "02-0000-0000"])
    // 表頭的「電話」沒有冒號：不塗
    expect(findSensitiveRanges("成交日期  電話  名稱")).toEqual([])
  })

  it("標籤和值分在兩個隔開的框：值照樣塗掉", () => {
    const boxes = [...line(20, ["客戶姓名：", "王小明"], 30), ...line(60, ["2026/10/01", "2330", "台積電"])]
    const res = maskTextBoxes(boxes)
    expect(res.masked).toBe(1)
    expect(res.text.split("\n")[0]).toBe(`客戶姓名：  ${MASK_TOKEN}`)
    expect(res.text).toContain("2330")
    expect(res.rects).toHaveLength(1)
    // 只塗值那個框（x 從 40+50+30=120 到 150），標籤不塗
    expect(covered(res.rects[0]!, 120, 150)).toBe(true)
    expect(res.rects[0]!.x).toBeGreaterThan(90)
  })

  it("值在同一個框的中間：照字數比例只塗那一段", () => {
    const boxes = line(20, ["客戶姓名：王小明　身分證字號：A123456789　帳號：9A99-0123456"])
    const res = maskTextBoxes(boxes)
    expect(res.masked).toBe(3)
    expect(res.text).not.toMatch(/王小明|A123456789|9A99-0123456/)
    expect(res.text).toContain("客戶姓名：")
    expect(res.text).toContain("帳號：")
    // 「王小明」是第 5–7 個字：x 從 40+50 到 40+80
    expect(res.rects.some((r) => covered(r, 90, 120) && r.x > 80 && r.x + r.w < 130)).toBe(true)
  })

  it("一個字一個框的 PDF（框緊貼）：拼起來找得到，塗的是那幾個框", () => {
    const id = "A123456789"
    const boxes = [...line(20, ["身分證字號："], 0), ...[...id].map((ch, i) => ({ str: ch, x: 100 + i * 10, y: 20, w: 10, h: 14, horizontal: true }))]
    const res = maskTextBoxes(boxes)
    expect(res.text).not.toContain(id)
    expect(res.rects.length).toBe(id.length)
  })

  it("直書或旋轉過的頁面：整個框塗掉", () => {
    const res = maskTextBoxes([{ str: "身分證字號：A123456789", x: 10, y: 10, w: 14, h: 200, horizontal: false }])
    expect(res.rects).toEqual([{ x: expect.any(Number), y: expect.any(Number), w: expect.any(Number), h: expect.any(Number) }])
    expect(res.rects[0]!.h).toBeGreaterThanOrEqual(200)
  })

  it("沒有個資：一個框都不塗，文字照原樣分行", () => {
    const res = maskTextBoxes([...line(10, ["成交日期", "代號"]), ...line(40, ["2026/10/01", "2330"])])
    expect(res).toEqual({ rects: [], text: "成交日期  代號\n2026/10/01  2330", masked: 0 })
  })
})
