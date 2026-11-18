import type { AllocationGroupSlice, AllocationGrouping, AllocationLimits, Concentration, OverLimit, PortfolioAllocation } from "@/api/types"
import { codeOf } from "@/lib/tick"

/**
 * 帳本「配置」分段的列（產品負責人 2026-11-18，全部照建議）：後端的六種分組（`GET /portfolio/allocation`）→ 清單的列與圓環的塊。
 * 純函式：只整理後端算好的數字（每一塊的金額、比例、超過上限的項目），不自己判斷分類。
 *
 * - 最多 5 塊有顏色（分類色 series-1…5，照大小、不循環）；第 6 塊以後併成「其他 N 檔／項」（鉛筆灰＋斜線），點開看裡面有哪些。
 *   只多出 1 塊時不併：它自己一列，用鉛筆灰（名字照寫，不叫「其他 1 項」）。
 * - 產業：ETF 不算產業、也不拆成分股，所有 ETF 類別收在一列「ETF」底下（國內股票型、海外股票型、債券…）；
 *   「未分類」是真的一塊（判斷不了的），不併進「其他」以外的地方。
 * - 上限（使用者自己設的）：每一檔的個股（ETF 不算）、產業的產業（ETF 與未分類不算）才有直線與「超過上限」；
 *   超過與否看後端的 `over_limits`（和集中度、AI 面板同一個判斷）。
 */

export const GROUPINGS: readonly { value: AllocationGrouping; label: string }[] = [
  { value: "holding", label: "每一檔" },
  { value: "industry", label: "產業" },
  { value: "market", label: "市場" },
  { value: "account", label: "帳戶" },
  { value: "currency", label: "幣別" },
  { value: "type", label: "類型" },
]

/** 圓環最多幾塊有顏色（series-1…5）；其餘併成「其他」 */
export const MAX_SLICES = 5
export const OTHER_KEY = "__other"
export const ETF_KEY = "__etf"
export const UNCLASSIFIED = "unclassified"

/** 一列：名稱、第二行、金額、比例；`tone` 是圓環與色塊的顏色（0–4＝series-1…5，`other`＝鉛筆灰斜線；子列沒有） */
export interface AllocRow {
  key: string
  label: string
  /** 第二行：每一檔是代號；產業是裡面有哪幾檔；其他分組是幾檔 */
  sub: string
  value: number
  weight: number
  /** 這一列適用的上限（畫一條直線）；沒有就是 null */
  limit: number | null
  /** 超過上限（後端的 `over_limits`） */
  over: boolean
  tone: number | "other" | null
  kids?: AllocRow[]
}

const join = (xs: string[]) => xs.join("、")

/** ETF 列底下的類別名稱：「國內股票型 ETF」→「國內股票型」，「ETF（未分類）」→「未分類」 */
export function etfClassLabel(label: string): string {
  if (/^ETF（.+）$/.test(label)) return label.slice(4, -1)
  return label.replace(/\s*ETF$/, "")
}

function overOf(over: OverLimit[], kind: OverLimit["kind"], key: string) {
  return over.some((o) => o.kind === kind && o.key === key)
}

/**
 * 某一種分組的列（還沒併「其他」；由大到小）。產業列的第二行是裡面那幾檔的名稱（每一檔那一組的 label）。
 */
export function rowsFor(alloc: PortfolioAllocation, grouping: AllocationGrouping): AllocRow[] {
  const slices = alloc.groups[grouping] ?? []
  const { limits, over_limits: over } = alloc.concentration
  const names = new Map(alloc.groups.holding.map((s) => [s.key, s.label]))
  const nameList = (s: AllocationGroupSlice) => join(s.symbols.map((sym) => names.get(sym) ?? codeOf(sym)))
  const count = (s: AllocationGroupSlice) => `${s.symbols.length} 檔`
  const base = { tone: null } as const

  if (grouping === "holding") {
    return slices.map((s) => ({
      ...base, key: s.key, label: s.label, sub: codeOf(s.key), value: s.value, weight: s.weight,
      limit: s.is_etf ? null : limits.holding, over: !s.is_etf && overOf(over, "holding", s.key),
    }))
  }
  if (grouping === "industry") {
    const etfs = slices.filter((s) => s.is_etf)
    const rows: AllocRow[] = slices
      .filter((s) => !s.is_etf)
      .map((s) => {
        const counted = s.key !== UNCLASSIFIED
        return {
          ...base, key: s.key, label: s.label, sub: nameList(s), value: s.value, weight: s.weight,
          limit: counted ? limits.industry : null, over: counted && overOf(over, "industry", s.key),
        }
      })
    if (etfs.length > 0) {
      rows.push({
        ...base, key: ETF_KEY, label: "ETF", sub: "不算進產業",
        value: etfs.reduce((a, s) => a + s.value, 0), weight: etfs.reduce((a, s) => a + s.weight, 0),
        limit: null, over: false,
        kids: etfs.map((s) => ({ ...base, key: s.key, label: etfClassLabel(s.label), sub: join(s.symbols.map(codeOf)), value: s.value, weight: s.weight, limit: null, over: false })),
      })
    }
    // 由大到小（一樣大時照 key，和後端一樣）
    return rows.sort((a, b) => b.value - a.value || a.key.localeCompare(b.key))
  }
  return slices.map((s) => ({ ...base, key: s.key, label: s.label, sub: count(s), value: s.value, weight: s.weight, limit: null, over: false }))
}

/** 前 5 塊有顏色；6 塊以上時第 6 塊起併成「其他」（只多 1 塊就不併，那一塊用鉛筆灰） */
export function foldRows(rows: AllocRow[], grouping: AllocationGrouping): AllocRow[] {
  const head = rows.slice(0, MAX_SLICES).map((r, i) => ({ ...r, tone: i }))
  const tail = rows.slice(MAX_SLICES)
  if (tail.length === 0) return head
  if (tail.length === 1) return [...head, { ...tail[0]!, tone: "other" }]
  return [
    ...head,
    {
      key: OTHER_KEY,
      label: `其他 ${tail.length} ${grouping === "holding" ? "檔" : "項"}`,
      sub: join(tail.map((r) => r.label)),
      value: tail.reduce((a, r) => a + r.value, 0),
      weight: tail.reduce((a, r) => a + r.weight, 0),
      limit: null,
      over: false,
      tone: "other",
      // 「其他」裡只展開一層：ETF 那一列在這裡不再展開它的類別
      kids: tail.map(({ kids: _kids, ...r }) => ({ ...r, tone: null })),
    },
  ]
}

/** 這一組在清單上的列（已併「其他」） */
export function allocationRows(alloc: PortfolioAllocation, grouping: AllocationGrouping): AllocRow[] {
  return foldRows(rowsFor(alloc, grouping), grouping)
}

/** 這一組適用哪一個上限（清單下面的說明「直線是你設定的…」）；沒有就是 null */
export function limitOf(grouping: AllocationGrouping, limits: AllocationLimits): { kind: "holding" | "industry"; value: number } | null {
  if (grouping === "holding" && limits.holding !== null) return { kind: "holding", value: limits.holding }
  if (grouping === "industry" && limits.industry !== null) return { kind: "industry", value: limits.industry }
  return null
}

/** 上限的寫法：30%（整數；有小數時最多 1 位） */
export function limitText(v: number): string {
  const pct = Math.round(v * 1000) / 10
  return `${Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(1)}%`
}

/** 「30」「30%」「12.5」→ 0.3、0.125；空的＝不設（null）；不是 1–100 的數字＝錯（undefined） */
export function parseLimit(text: string): number | null | undefined {
  const t = text.trim().replace(/[％%]$/, "").trim()
  if (t === "") return null
  if (!/^\d+(\.\d+)?$/.test(t)) return undefined
  const n = Number(t)
  if (n < 1 || n > 100) return undefined
  return Math.round(n * 100) / 10000
}

/**
 * 集中度的「超過上限」：最大的那一檔（或產業）超過時寫「超過你設定的 30%」，其他項目也超過時寫「2 檔超過…」。
 * `onTop`：最大的那一項本身在超過的清單裡，小標才可以接在它的名稱與比例後面。最大一檔是 ETF（0050 佔 45%）而台積電超過時是 false：
 * ETF 不算個股、不會超過單一個股上限，小標要另外放（「1 檔超過上限」），不能看起來像是 ETF 超過了。
 */
export function overNote(conc: Concentration, kind: OverLimit["kind"]): { long: string; short: string; onTop: boolean } | null {
  const list = conc.over_limits.filter((o) => o.kind === kind)
  const limit = conc.limits[kind]
  if (list.length === 0 || limit === null) return null
  const lim = limitText(limit)
  const topKey = kind === "holding" ? (conc.top_holding && !conc.top_holding.is_etf ? conc.top_holding.symbol : undefined) : conc.top_industry?.key
  const onTop = topKey !== undefined && list.some((o) => o.key === topKey)
  if (list.length === 1 && onTop) return { long: `超過你設定的 ${lim}`, short: `超過上限 ${lim}`, onTop }
  const unit = kind === "holding" ? "檔" : "個產業"
  return { long: `${list.length} ${unit}超過你設定的 ${lim}`, short: `${list.length} ${unit}超過上限`, onTop }
}

/** 「最大產業」空白時的說明：持股全是 ETF 才寫「都是 ETF」；有個股只是還沒有產業資料時寫「沒有產業資料」 */
export function noIndustryText(conc: Concentration): string {
  return conc.etf_weight >= 0.9999 ? "都是 ETF" : "沒有產業資料"
}

/** 集中度第二格：持股 6 檔以上是前 5 大；4–5 檔是前 3 大；3 檔以下不放（前 N 大就是全部） */
export function topN(conc: Concentration): { n: 3 | 5; weight: number } | null {
  if (conc.holdings_count > 5) return { n: 5, weight: conc.top5_weight }
  if (conc.holdings_count > 3) return { n: 3, weight: conc.top3_weight }
  return null
}

// ── 圓環的幾何 ───────────────────────────────────────────
export interface Arc {
  key: string
  tone: number | "other"
  /** SVG path（外圈 R、內圈 r、圓心在 (R, R)） */
  d: string
  start: number
  end: number
}

/**
 * 圓環：12 點鐘方向開始、順時針，照清單的順序（由大到小，「其他」在最後）。角度照金額算（加起來剛好一圈）。
 * 塊與塊之間的 2px 紙色空隙由 `stroke` 畫（dataviz：surface gap），這裡只算形狀。只有一塊時是整個圓環。
 */
export function donutArcs(rows: { key: string; value: number; tone: number | "other" | null }[], R = 100, r = 64): Arc[] {
  const total = rows.reduce((a, x) => a + Math.max(x.value, 0), 0)
  if (total <= 0) return []
  const cx = R
  const cy = R
  const pt = (rad: number, ang: number) => `${(cx + rad * Math.cos(ang)).toFixed(3)} ${(cy + rad * Math.sin(ang)).toFixed(3)}`
  let a0 = -Math.PI / 2
  const out: Arc[] = []
  for (const row of rows) {
    if (row.value <= 0) continue
    const sweep = (row.value / total) * Math.PI * 2
    const a1 = a0 + sweep
    const tone = row.tone ?? "other"
    if (sweep >= Math.PI * 2 - 1e-6) {
      // 一整圈：兩個半圓（SVG 的弧不能起點等於終點）
      const d = `M ${pt(R, -Math.PI / 2)} A ${R} ${R} 0 1 1 ${pt(R, Math.PI / 2)} A ${R} ${R} 0 1 1 ${pt(R, -Math.PI / 2)} Z M ${pt(r, -Math.PI / 2)} A ${r} ${r} 0 1 0 ${pt(r, Math.PI / 2)} A ${r} ${r} 0 1 0 ${pt(r, -Math.PI / 2)} Z`
      out.push({ key: row.key, tone, d, start: a0, end: a1 })
    } else {
      const large = sweep > Math.PI ? 1 : 0
      const d = `M ${pt(R, a0)} A ${R} ${R} 0 ${large} 1 ${pt(R, a1)} L ${pt(r, a1)} A ${r} ${r} 0 ${large} 0 ${pt(r, a0)} Z`
      out.push({ key: row.key, tone, d, start: a0, end: a1 })
    }
    a0 = a1
  }
  return out
}
