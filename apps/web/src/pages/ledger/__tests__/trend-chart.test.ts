import { describe, expect, it } from "vitest"
import { flowPathOf, segmentHitsBox } from "../trend-chart"

/** 總資產走勢的小工具：買賣那一天垂直跳的總資產線、圖裡那一行字的方框會不會碰到線（第二審 1、3） */
describe("flowPathOf：總資產線在買賣那一天垂直跳", () => {
  const x = (i: number) => i * 10
  const y = (v: number) => 100 - v

  it("沒有買賣的日子是一般的折線；有買賣的那一天先斜到買賣以前的值，再垂直到收盤", () => {
    const close = [10, 20, 60, 65]
    const pre = [10, 20, 30, 65] // 第 2 天買進 30：買賣以前是 30，收盤 60
    expect(flowPathOf([0, 1, 2, 3], x, (i) => y(close[i]!), (i) => y(pre[i]!))).toBe("M0.0 90.0L10.0 80.0L20.0 70.0V40.0L30.0 35.0")
  })

  it("從中間開始的一段（估計那一段的細線）：第一點用收盤的值", () => {
    const close = [10, 20, 60]
    const pre = [10, 20, 30]
    expect(flowPathOf([2], x, (i) => y(close[i]!), (i) => y(pre[i]!))).toBe("M20.0 40.0")
  })
})

describe("segmentHitsBox：線段碰不碰得到方框（四邊各往外 pad）", () => {
  const box = { x0: 100, y0: 50, x1: 160, y1: 63 }

  it("穿過、在裡面、剛好碰到邊都算碰到", () => {
    expect(segmentHitsBox(80, 56, 180, 56, box, 0)).toBe(true)
    expect(segmentHitsBox(110, 55, 120, 58, box, 0)).toBe(true)
    expect(segmentHitsBox(90, 50, 99, 50, box, 1)).toBe(true)
  })

  it("離得夠遠就沒碰到；pad 讓「差一點」也算碰到", () => {
    // 方框下面 6px 的水平線
    expect(segmentHitsBox(80, 69, 180, 69, box, 5)).toBe(false)
    expect(segmentHitsBox(80, 67, 180, 67, box, 5)).toBe(true)
    // 斜線從方框角落外面擦過
    expect(segmentHitsBox(165, 70, 175, 60, box, 0)).toBe(false)
    expect(segmentHitsBox(165, 70, 175, 60, box, 6)).toBe(true)
  })

  it("垂直的一段（買賣那一天的跳）和一個點也算", () => {
    expect(segmentHitsBox(130, 0, 130, 200, box, 0)).toBe(true)
    expect(segmentHitsBox(170, 0, 170, 200, box, 5)).toBe(false)
    expect(segmentHitsBox(130, 56, 130, 56, box, 0)).toBe(true)
    expect(segmentHitsBox(130, 80, 130, 80, box, 5)).toBe(false)
  })
})
