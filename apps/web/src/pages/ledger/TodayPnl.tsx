import { useState } from "react"
import { useHoldings, useSummary } from "@/api/queries"
import { CentreBars, type CentreBarRow } from "@/components/centre-bars"
import { Tray } from "@/components/tray"
import { textAction } from "@/components/text-action"
import { withDayWord } from "@/lib/as-of"
import { cn } from "@/lib/utils"
import { pnlDates } from "./close-label"
import { useHeroClose } from "./use-hero-close"

/** 超過這麼多檔時先只列賺最多與賠最多的各 5 檔（中間是動得最少的），「全部 N 檔」打開 */
const FOLD_OVER = 10
const FOLD_KEEP = 5

/**
 * 今日損益（內頁重新設計 2026-11-21，方向 C「以 0 為中線的長條」）：每一檔今天賺賠多少，排在持倉後面，不把持倉擠出第一屏。
 * - 標題和持倉表頭同一個詞（`withDayWord`）：收盤價都是今天的才是「今日損益」，否則「11/12 損益」「當日損益」。
 * - meta 是每個市場各自的收盤日（`pnlDates`）：「台股 11/12・美股 11/11（美東）」——美股的漲跌是紐約前一個交易日的。
 * - 由賺最多排到賠最多；沒有收盤價的持股不列（它的今日損益不是 0，是不知道）；一檔都沒有收盤價時整盤不放。
 * - 數字由 `CentreBars` 印（+NT$75,000、−NT$7,500，隱私模式遮蔽；橫條照樣畫，和總資產走勢在隱私模式照樣畫線一樣）。
 * - 名稱不截斷：放不下就換行，這張圖窄於 18rem（320px 的手機）時換成代號、全名給螢幕閱讀器。
 */
export function TodayPnl() {
  const holdings = useHoldings()
  const summary = useSummary()
  const { day } = useHeroClose()
  const [all, setAll] = useState(false)
  const priced = (holdings.data ?? []).filter((h) => h.price !== null)
  if (!priced.length) return null
  const rows: CentreBarRow[] = [...priced]
    .sort((a, b) => b.day_change - a.day_change || a.name.localeCompare(b.name, "zh-TW"))
    .map((h) => ({ id: h.symbol, label: h.name, short: h.code, value: h.day_change }))
  const fold = rows.length > FOLD_OVER
  const shown = fold && !all ? [...rows.slice(0, FOLD_KEEP), ...rows.slice(-FOLD_KEEP)] : rows
  const title = withDayWord("今日損益", day)
  return (
    <Tray
      title={title}
      meta={pnlDates(priced, summary.data?.as_of)}
      action={
        fold ? (
          <button type="button" aria-expanded={all} onClick={() => setAll(!all)} className={cn(textAction, "num")}>
            {all ? "收起" : `全部 ${rows.length} 檔`}
          </button>
        ) : undefined
      }
    >
      <CentreBars rows={shown} unit="money" currency="TWD" label={fold && !all ? `${title}，賺最多與賠最多的各 ${FOLD_KEEP} 檔` : title} />
    </Tray>
  )
}
