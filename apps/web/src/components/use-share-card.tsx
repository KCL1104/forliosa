import { appToday } from "@/api"
import { usePerformance, useSummary } from "@/api/queries"
import { useLedgerClose } from "@/hooks/use-close"
import { isReferenceNote, REFERENCE_TAIL, referenceLine } from "@/lib/data-notes"
import { direction, directionGlyph, formatDateShort, formatPercent } from "@/lib/format"

/**
 * 分享卡的資料：只有百分比（今日、本月、總報酬），和複製到 LINE 的那一行字。群組頁（`GroupsPage`）與帳本（有加入群組時，
 * 內頁重新設計 2026-11-21）用同一份資料與同一張卡（`components/share-card.tsx`）。
 * 本月用到存檔開始以前的 Yahoo 參考價時（產品負責人 2026-11-18），卡片下面寫後端那一句，分享文字的本月後面也標上。
 */
export function useShareCard() {
  const summary = useSummary()
  const mtd = usePerformance("MTD")
  const s = summary.data
  const month = mtd.data ? mtd.data.twr : undefined
  const today = appToday()
  // 「今日」和帳本同一個詞（2026-11-21）：收盤價都是今天的才寫「今日」「我今天」；盤中、週末寫那一天（「11/12」「我 11/12」），
  // 上市、上櫃不同天寫「當日」；只有美股時是紐約的日期
  const { day } = useLedgerClose()
  const dayLead = day === "今日" ? "我今天" : /\d/.test(day) ? `我 ${day}` : `我${day}`
  // 本月算不出來（有持股還沒有收盤價、資料還不夠）時，分享文字與卡片都不提本月：沒有的值不寫進句子（不出現「本月 —」）
  const monthKnown = month !== null && month !== undefined
  const noMonth = month === null
  const until = monthKnown ? (mtd.data?.reference_until ?? null) : null
  const referenceNote = until
    ? ((mtd.data?.notes ?? []).find(isReferenceNote) ?? referenceLine(until))
    : null
  const monthText = monthKnown ? `本月 ${glyphPct(month)}${until ? `（${formatDateShort(until, false)} ${REFERENCE_TAIL}）` : ""}，` : ""
  const line = s ? `${dayLead} ${glyphPct(s.day_change_pct)}，${monthText}總報酬 ${glyphPct(s.total_return_pct)}（Forliosa ${formatDateShort(today, false)}）` : ""
  const cells: { label: React.ReactNode; key: string; value: number | null | undefined }[] = [
    { key: "day", label: day, value: s?.day_change_pct },
    ...(noMonth ? [] : [{ key: "month", label: "本月", value: month }]),
    // 手機三欄放不下括號：只寫「總報酬」（和手機排行的表頭一樣）
    {
      key: "total",
      label: (
        <>
          總報酬<span className="max-sm:hidden">（含股利）</span>
        </>
      ),
      value: s?.total_return_pct,
    },
  ]
  return { ready: !!s, line, cells, noMonth, today, referenceNote, monthNote: noMonth ? monthMissing(mtd.data?.notes ?? []) : null }
}

export type ShareCardData = ReturnType<typeof useShareCard>

export function glyphPct(r: number | null): string {
  const d = direction(r)
  return `${directionGlyph(d)}${formatPercent(r === null ? null : Math.abs(r), { signed: false, decimals: Math.abs(r ?? 0) >= 0.1 ? 1 : 2 })}`
}

/**
 * 本月算不出來的原因，一句話：有持股還沒有收盤價時「MSFT 還沒有收盤價，本月算不出來。」；其他原因照後端的說明。
 * （後端那句是「MSFT：還沒有收盤價，績效算不出來」——接在「本月算不出來」後面就講了兩次。美股收盤價沒開的環境是
 * 「AAPL、NVDA：美股沒有報價，含美股的績效算不出來」→「AAPL、NVDA 沒有報價，本月算不出來。」）
 */
function monthMissing(notes: string[]): string {
  for (const n of notes) {
    const m = /^(.+?)：(還沒有收盤價|美股沒有報價)/.exec(n)
    if (m) return `${m[1]} ${m[2] === "還沒有收盤價" ? "還沒有收盤價" : "沒有報價"}，本月算不出來。`
  }
  return notes[0] ? `本月算不出來。${withPeriod(notes[0])}` : "本月算不出來。"
}

/** 後端的說明沒有句點時補上（接在另一句後面） */
function withPeriod(note: string): string {
  return /[。！？]$/.test(note) ? note : `${note}。`
}
