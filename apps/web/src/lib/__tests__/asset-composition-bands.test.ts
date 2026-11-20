import { describe, expect, it } from "vitest"
import { AXIS_FIT_THRESHOLD, compositionAxis, profitBands, type ProfitBand } from "../asset-composition"

/**
 * 資產組成 v2：總資產走勢裡賺（本金線上方）與虧（下方）的塗色，與縱軸要不要把本金放進來。
 * 本金是階梯線：第 i−1 天到第 i 天之間是第 i−1 天的本金，到第 i 天才跳；總資產是直線。
 */
const pts = (...rows: [number, number][]) => rows.map(([v, p]) => ({ v, p }))
const sides = (bands: ProfitBand[]) => bands.map((b) => b.side)
/** 總資產那條直線在位置 x（可以是小數）的值 */
const totalAt = (rows: [number, number][], x: number) => {
  const i = Math.floor(x)
  const t = x - i
  return rows[i]![0] + (rows[Math.min(i + 1, rows.length - 1)]![0] - rows[i]![0]) * t
}

describe("profitBands：賺與虧的塗色", () => {
  it("一直賺：一塊賺的，沿著總資產過去、沿著本金回來", () => {
    expect(profitBands(pts([120, 100], [130, 100], [125, 100]))).toEqual([
      { side: "gain", points: [[0, 120], [1, 130], [2, 125], [2, 100], [1, 100], [0, 100]] },
    ])
  })

  it("一直虧：一塊虧的", () => {
    expect(profitBands(pts([90, 100], [80, 100], [95, 100]))).toEqual([
      { side: "loss", points: [[0, 90], [1, 80], [2, 95], [2, 100], [1, 100], [0, 100]] },
    ])
  })

  it("兩個收盤之間交會：在兩條線交會的那一點換顏色（不是在收盤日上），兩塊剛好接在那一點", () => {
    const rows: [number, number][] = [[130, 100], [90, 100]]
    const bands = profitBands(pts(...rows))
    expect(sides(bands)).toEqual(["gain", "loss"])
    // 130 → 90 經過 100：在 30／40 = 0.75 的地方
    expect(bands[0]!.points).toEqual([[0, 130], [0.75, 100], [0.75, 100], [0, 100]])
    expect(bands[1]!.points).toEqual([[0.75, 100], [1, 90], [1, 100], [0.75, 100]])
    // 交會點真的在總資產那條線上、高度就是本金
    expect(totalAt(rows, 0.75)).toBe(100)
  })

  it("虧轉賺也一樣（交會點照兩邊的差距比例算）", () => {
    const rows: [number, number][] = [[95, 100], [100, 100], [80, 100], [120, 100]]
    const bands = profitBands(pts(...rows))
    expect(sides(bands)).toEqual(["loss", "gain"])
    // 第 2 → 3 天：80 → 120 經過 100，在 2.5
    const switchAt = bands[1]!.points[0]!
    expect(switchAt).toEqual([2.5, 100])
    expect(totalAt(rows, switchAt[0])).toBeCloseTo(100, 9)
    expect(bands[0]!.points.at(-1)).toEqual([0, 100])
  })

  it("本金跳一階、還在同一邊：買賣當作兩條線在那一天一起垂直跳——斜的部分只有價格的漲跌，上下緣在那一天各一段垂直的邊", () => {
    // 第 2 天買進 50：總資產 210 → 260 裡 50 是買進的錢，價格沒有動（買進以前的值 260 − 50 = 210）
    expect(profitBands(pts([200, 100], [210, 100], [260, 150], [255, 150]))).toEqual([
      { side: "gain", points: [[0, 200], [1, 210], [2, 210], [2, 260], [3, 255], [3, 150], [2, 150], [2, 100], [1, 100], [0, 100]] },
    ])
  })

  it("買進讓那一天收盤時變成虧的：收盤左邊就是虧的顏色（交會在那一段裡），不是到收盤日才換", () => {
    // 第 2 天買進 40（本金 100 → 140），總資產 125：收盤時虧 15。買進以前的值是 125 − 40 = 85，第 1 → 2 天 130 → 85 經過 100
    const bands = profitBands(pts([120, 100], [130, 100], [125, 140], [150, 140]))
    expect(sides(bands)).toEqual(["gain", "loss", "gain"])
    const at1 = 1 + 30 / 45
    expect(bands[0]!.points).toEqual([[0, 120], [1, 130], [at1, 100], [at1, 100], [1, 100], [0, 100]])
    // 虧的那一塊：斜到第 2 天買進以前的 85，在第 2 天和本金一起垂直跳 40（85 → 125、100 → 140），再在 2 + 15／25 = 2.6 交會
    expect(bands[1]!.points).toEqual([[at1, 100], [2, 85], [2, 125], [2.6, 140], [2.6, 140], [2, 140], [2, 100], [at1, 100]])
    expect(bands[2]!.points[0]).toEqual([2.6, 140])
  })

  /** 不變的規則：每一個收盤日 k 的左邊一點點，塗的顏色就是那天收盤的賺或虧（v[k] − p[k] 的正負號） */
  const sideLeftOf = (bands: ProfitBand[], x: number) => bands.filter((b) => Math.min(...b.points.map((q) => q[0])) < x && Math.max(...b.points.map((q) => q[0])) >= x).map((b) => b.side)
  const expectCloseSides = (rows: [number, number][]) => {
    const bands = profitBands(pts(...rows))
    for (let k = 1; k < rows.length; k++) {
      const gain = rows[k]![0] - rows[k]![1]
      if (gain === 0) continue
      expect(sideLeftOf(bands, k - 1e-6), `第 ${k} 天（賺 ${gain}）`).toEqual([gain > 0 ? "gain" : "loss"])
    }
  }

  it("不變的規則：虧 2 萬時買進 30 萬（價格沒動）——整段都是虧的，不會有一塊賺的三角形", () => {
    const rows: [number, number][] = [[980_000, 1_000_000], [1_280_000, 1_300_000]]
    expectCloseSides(rows)
    expect(sides(profitBands(pts(...rows)))).toEqual(["loss"])
  })

  it("不變的規則：最後一天買進 50 萬、跌 1.5 萬，從賺 1 萬變成虧 5,000——右邊的盡頭是虧的顏色", () => {
    const rows: [number, number][] = [[1_010_000, 1_000_000], [1_495_000, 1_500_000]]
    expectCloseSides(rows)
    const bands = profitBands(pts(...rows))
    expect(sides(bands)).toEqual(["gain", "loss"])
    // 交會在 1 萬 ／（1 萬 + 5,000）＝ 2／3
    expect(bands[1]!.points[0]![0]).toBeCloseTo(2 / 3, 9)
  })

  it("不變的規則：整批賣出（賣出收到的比本金還多，前後都是賺的）——那一天沒有虧的三角形", () => {
    // 本金 980 萬 → −50 萬（賣出收到 1,030 萬），總資產 1,500 萬 → 460 萬：收盤都是賺的
    const rows: [number, number][] = [[15_000_000, 9_800_000], [4_600_000, -500_000], [4_650_000, -500_000]]
    expectCloseSides(rows)
    expect(sides(profitBands(pts(...rows)))).toEqual(["gain"])
  })

  it("不變的規則：一串有買有賣、有漲有跌的日子，每一個收盤的左邊都是那天收盤的顏色", () => {
    let seed = 7
    const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296)
    const rows: [number, number][] = []
    let p = 1_000_000
    let v = 1_000_000
    for (let i = 0; i < 120; i++) {
      v *= 1 + (rand() - 0.5) * 0.06
      if (rand() < 0.2) {
        const flow = Math.round((rand() - 0.4) * 400_000)
        p += flow
        v += flow
      }
      rows.push([Math.round(v), Math.round(p)])
    }
    expect(new Set(sides(profitBands(pts(...rows))))).toEqual(new Set(["gain", "loss"]))
    expectCloseSides(rows)
  })

  it("只有一點：沒有東西可以塗", () => {
    expect(profitBands(pts([100, 90]))).toEqual([])
    expect(profitBands([])).toEqual([])
  })

  it("兩條線重疊（面積 0）不塗；總資產平平的在本金上面是一個長方形", () => {
    expect(profitBands(pts([100, 100], [100, 100], [100, 100]))).toEqual([])
    expect(profitBands(pts([120, 100], [120, 100]))).toEqual([{ side: "gain", points: [[0, 120], [1, 120], [1, 100], [0, 100]] }])
  })

  it("本金是負的（賣股票收到的錢比買的多）：整塊都是賺的，下緣在負的本金", () => {
    expect(profitBands(pts([500_000, -200_000], [508_000, -200_000]))).toEqual([
      { side: "gain", points: [[0, 500_000], [1, 508_000], [1, -200_000], [0, -200_000]] },
    ])
  })

  it("floor 0（本金已收回）：本金 −20 萬時下緣在 0，不在 −20 萬", () => {
    expect(profitBands(pts([500_000, -200_000], [508_000, -200_000]), { floor: 0 })).toEqual([
      { side: "gain", points: [[0, 500_000], [1, 508_000], [1, 0], [0, 0]] },
    ])
    // 本金是正的時候和沒有 floor 一樣
    const rows = pts([120, 100], [130, 100], [125, 140], [150, 140])
    expect(profitBands(rows, { floor: 0 })).toEqual(profitBands(rows))
  })

  it("floor 0：賣到本金變負、再買回來——總資產照真的本金垂直跳（只有價格的漲跌是斜的），下緣在本金與 0 之間跳，跳的多少可以和總資產不一樣", () => {
    // 第 1 天賣 25 萬（本金 20 萬 → −5 萬，總資產 31 萬 → 6 萬，價格沒動）；第 2 天買 10 萬（本金 → 5 萬，總資產 → 16.4 萬，漲 4,000）；第 3 天漲 6,000
    const bands = profitBands(pts([310_000, 200_000], [60_000, -50_000], [164_000, 50_000], [170_000, 50_000]), { floor: 0 })
    expect(bands).toEqual([
      {
        side: "gain",
        points: [
          // 上緣：第 0 → 1 天斜到賣出以前的 31 萬，垂直跳 25 萬到 6 萬；第 1 → 2 天斜到買進以前的 6.4 萬，垂直跳 10 萬到 16.4 萬
          [0, 310_000], [1, 310_000], [1, 60_000], [2, 64_000], [2, 164_000], [3, 170_000],
          // 下緣（由右到左）：5 萬；第 2 天從 0 跳 5 萬（總資產跳 10 萬）；第 1 → 2 天在 0；第 1 天從 20 萬跳到 0（總資產跳 25 萬）
          [3, 50_000], [2, 50_000], [2, 0], [1, 0], [1, 200_000], [0, 200_000],
        ],
      },
    ])
  })

  it("floor 0 的不變規則：一串有買有賣、本金在正負之間來回的日子——每一個收盤左右兩邊的顏色＝那天收盤 v − max(p, 0) 的正負號（也就是真的賺的 v − p 的正負號），下緣不低於 0", () => {
    let seed = 11
    const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296)
    const rows: [number, number][] = []
    let p = 1_000_000
    let v = 900_000
    for (let i = 0; i < 200; i++) {
      v *= 1 + (rand() - 0.5) * 0.08
      if (rand() < 0.25) {
        // 買賣：買進最多 60 萬；賣出不超過手上的持股（賣出收到的錢同時從總資產與本金扣掉）
        const flow = rand() < 0.5 ? Math.round(rand() * 600_000) : -Math.round(rand() * v)
        p += flow
        v += flow
      }
      rows.push([Math.round(v), Math.round(p)])
    }
    // 真的有本金是負的、也有虧的日子
    expect(rows.some(([, q]) => q < 0)).toBe(true)
    expect(rows.some(([a, q]) => a < q)).toBe(true)
    const bands = profitBands(pts(...rows), { floor: 0 })
    // 上緣是總資產（不會是負的），下緣是 max(本金, 0)：每一個頂點都不低於 0
    for (const b of bands) for (const [, y] of b.points) expect(y).toBeGreaterThanOrEqual(0)
    const sideRightOf = (x: number) => bands.filter((b) => Math.min(...b.points.map((q) => q[0])) <= x && Math.max(...b.points.map((q) => q[0])) > x).map((b) => b.side)
    for (let k = 0; k < rows.length; k++) {
      const [a, q] = rows[k]!
      const shown = a - Math.max(q, 0)
      const real = a - q
      // 塗色的正負號和真的賺的一樣（本金 ≤ 0 時兩個都是賺的）
      if (shown !== 0) expect(Math.sign(shown), `第 ${k} 天`).toBe(Math.sign(real))
      if (shown === 0) continue
      const side = shown > 0 ? "gain" : "loss"
      if (k > 0) expect(sideLeftOf(bands, k - 1e-6), `第 ${k} 天左邊`).toEqual([side])
      if (k < rows.length - 1) expect(sideRightOf(k + 1e-6), `第 ${k} 天右邊`).toEqual([side])
    }
  })

  it("剛好碰到本金再離開（不穿過）：同一邊；碰到後換邊時從碰到的那一點開始", () => {
    // 120 → 100（碰到）→ 80：第一段是賺的，第二段從碰到的那一點開始虧
    const bands = profitBands(pts([120, 100], [100, 100], [80, 100]))
    expect(sides(bands)).toEqual(["gain", "loss"])
    expect(bands[1]!.points[0]).toEqual([1, 100])
  })
})

describe("compositionAxis：縱軸要不要把本金放進來", () => {
  it("總資產自己的起伏夠大（≥ 兩條線範圍的 35%）：貼著兩條線", () => {
    // 總資產 300 萬–400 萬、本金 250 萬：100 ／ 150 ≈ 0.67
    expect(compositionAxis(pts([3_000_000, 2_500_000], [4_000_000, 2_500_000]))).toEqual({ mode: "both", ratio: 100 / 150 })
  })

  it("不夠大（本金離太遠，放進來總資產會被壓扁）：縱軸只跟總資產", () => {
    // 總資產 380 萬–410 萬、本金 290 萬：30 ／ 120 = 0.25
    const axis = compositionAxis(pts([3_800_000, 2_900_000], [4_100_000, 2_900_000]))
    expect(axis.mode).toBe("total")
    expect(axis.ratio).toBeCloseTo(0.25)
  })

  it("門檻兩邊：剛好 35% 算夠大，差一點就不夠", () => {
    expect(AXIS_FIT_THRESHOLD).toBe(0.35)
    // 兩條線的範圍 100（0–100），總資產 65–100
    expect(compositionAxis(pts([65, 0], [100, 0])).mode).toBe("both")
    expect(compositionAxis(pts([66, 0], [100, 0])).mode).toBe("total")
    // 本金在上面（虧很多）也一樣
    expect(compositionAxis(pts([0, 100], [35, 100])).mode).toBe("both")
    expect(compositionAxis(pts([0, 100], [34, 100])).mode).toBe("total")
  })

  it("本金在總資產的範圍裡：不用放大，貼著兩條線；兩條線都是平的也是", () => {
    expect(compositionAxis(pts([100, 105], [110, 105], [90, 105])).mode).toBe("both")
    expect(compositionAxis(pts([100, 100], [100, 100]))).toEqual({ mode: "both", ratio: 1 })
  })
})
