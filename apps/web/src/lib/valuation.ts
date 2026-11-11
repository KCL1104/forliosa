import type { ValuationPoint } from "@/api/types"

export type Mode = "per" | "pbr"

export interface RiverRow {
  t: string
  close: number
  ratio: number | null
  base: number | null
  /** 堆疊用：b0 = base×m0，bi = base×(mi − mi−1)；base ≤ 0 時為 null（留白） */
  bands: (number | null)[]
}

/** 河流圖資料：eps_ttm × 倍數 或 bvps × 倍數。基準 ≤ 0 時整段留白。 */
export function buildRiver(series: ValuationPoint[], multiples: number[], mode: Mode): RiverRow[] {
  return series.map((p) => {
    const base = mode === "per" ? p.eps_ttm : p.bvps
    const valid = base !== null && base > 0
    return {
      t: p.t,
      close: p.close,
      ratio: mode === "per" ? p.per : p.pbr,
      base,
      bands: multiples.map((m, i) => (valid ? base! * (i === 0 ? m : m - multiples[i - 1]!) : null)),
    }
  })
}

/** 找出基準 ≤ 0 的連續期間 */
export function invalidRuns(rows: RiverRow[]): { from: string; to: string }[] {
  const runs: { from: string; to: string }[] = []
  let start: string | null = null
  rows.forEach((r, i) => {
    const bad = r.base === null || r.base <= 0
    if (bad && start === null) start = r.t
    if ((!bad || i === rows.length - 1) && start !== null) {
      runs.push({ from: start, to: bad ? r.t : rows[i - 1]!.t })
      start = null
    }
  })
  return runs
}
