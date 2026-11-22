import { ChevronDownIcon } from "lucide-react"
import { useId, useState } from "react"
import { appToday } from "@/api"
import type { FundRank, Performance, PerformanceMonth } from "@/api/types"
import { Masked, Pct } from "@/components/finance"
import { DemoTag, Section as Panel } from "@/components/section"
import { useSourceNote } from "@/hooks/use-source-note"
import { inText } from "@/lib/cjk"
import { direction, formatDateShort, formatMoney, formatPercent, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { benchmarkGap, fundRankPeriod, monthLabel, monthSpanText } from "./composition-text"

/** 一開始列幾個月；更多的按「看全部」 */
export const MONTHS_SHOWN = 12

/**
 * 「每月報酬率」（資產組成原型；績效分段，跟著整頁的區間）：一個月一列，新的在上面——
 * 本金增減（本金的變化，不是價格：不上色、正負號說方向）、這個月的損益（價格造成的：漲跌色＋正負號）、
 * 報酬率（時間加權，▲▼）、和比較基準差幾個百分點（不是價格：用「多／少」說方向，不用紅綠）。
 * 只列真實紀錄的月份：照估計的買入日算的月份不列，表格下面一行說有幾個月沒列。區間頭尾、被估計切掉的不完整的月份，
 * 月份旁邊寫它算的是哪幾天。印好的表頭（`.form-head`：明體 500、印刷藍，和持倉表、已出清同一種）、格線列、不包卡片。容器寬 ≥ 40rem 一個值一欄；窄的時候兩行一列。
 * 後端沒有 `composition`（舊版）時整塊不放。
 */
export function MonthlyTable({ p }: { p: Performance }) {
  const comp = p.composition
  const privacy = usePrefs((s) => s.privacyMode)
  const [all, setAll] = useState(false)
  const listId = useId()
  if (!comp) return null
  const months = comp.months
  const importMonths = comp.months_import_day ?? 0
  if (months.length === 0 && comp.months_estimated === 0 && importMonths === 0) return null
  const today = appToday()
  const years = months.some((m) => m.month.slice(0, 4) !== today.slice(0, 4))
  const bench = p.benchmark?.name ?? "基準"
  const shown = all ? months : months.slice(0, MONTHS_SHOWN)
  // 表格上面不放「報酬率最好的是…。最差的是…。」那一句（使用者 2026-11-19：讀起來像 AI 寫的，只要表格）
  return (
    <Panel title="每月報酬率" titleId="months-title">
      {months.length === 0 ? (
        <p className="text-base text-ink">
          {comp.months_estimated > 0 && importMonths === 0 ? "這段期間都是用估計的買入日算的，沒有可以比的月份。" : "這段期間沒有可以比的月份。"}
        </p>
      ) : (
        <div className="@container">
          <table className="w-full border-collapse text-base">
            <caption className="sr-only">每個月的本金增減、損益、報酬率，和{bench}比</caption>
            <thead>
              <tr className="form-head text-left">
                <th scope="col" className="h-10 pr-3">
                  月份<span className="@[40rem]:hidden">・本金增減</span>
                </th>
                <th scope="col" className="hidden h-10 pl-3 text-right @[40rem]:table-cell">本金增減</th>
                {/* 窄的時候這一格寫三個欄名，可以換行（表頭預設不換行，會把表格撐出畫面） */}
                <th scope="col" className="h-10 py-1 pl-3 text-right @max-[40rem]:whitespace-normal">
                  損益<span className="@[40rem]:hidden">・報酬率・<span className="whitespace-nowrap">比{inText(bench)}</span></span>
                </th>
                <th scope="col" className="hidden h-10 pl-3 text-right @[40rem]:table-cell">報酬率</th>
                <th scope="col" className="hidden h-10 pl-3 text-right @[40rem]:table-cell">比{inText(bench)}</th>
              </tr>
            </thead>
            <tbody id={listId}>
              {shown.map((m) => (
                <MonthRow key={m.month + m.from} m={m} years={years} privacy={privacy} />
              ))}
            </tbody>
          </table>
          {months.length > MONTHS_SHOWN && (
            <button
              type="button"
              aria-expanded={all}
              aria-controls={listId}
              onClick={() => setAll(!all)}
              className="mt-2 inline-flex min-h-9 items-center gap-1 text-md text-ink underline decoration-ctl underline-offset-4 hover:decoration-ink pointer-coarse:min-h-11"
            >
              {all ? "只看最近 12 個月" : `看全部 ${months.length} 個月`}
              <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", all && "rotate-180")} />
            </button>
          )}
        </div>
      )}
      {/* 表格下面（淡墨小字，和資料說明同一層）：沒列的月份，標籤寫幾個月、為什麼（2026-11-22 評論：只放標籤）。
          「本金增減」的意思與匯入那天的算法在績效分段最下面的「計算方式」 */}
      {(comp.months_estimated > 0 || importMonths > 0) && (
        <ul className="mt-2 flex flex-col gap-0.5 text-sm text-ink-2" data-months-notes>
          {comp.months_estimated > 0 && <li>未列 {comp.months_estimated} 個月・估計的買入日</li>}
          {/* 暫定（產品負責人還沒決定）：找不到買入日、用匯入那天記的那一筆，成本到那天的漲跌都算在那一天 */}
          {importMonths > 0 && <li>未列 {importMonths} 個月・匯入時找不到買入日</li>}
        </ul>
      )}
    </Panel>
  )
}

function MonthRow({ m, years, privacy }: { m: PerformanceMonth; years: boolean; privacy: boolean }) {
  const span = monthSpanText(m)
  const gap = benchmarkGap(m)
  const pnlDir = direction(m.pnl)
  // 本金增減：不是價格，墨色＋正負號；0 是「—」
  const flows = m.flows === 0 ? <span className="text-ink-2">—</span> : privacy ? <Masked /> : <span className="num">{formatMoney(m.flows, { signed: true })}</span>
  const flowsWords = m.flows > 0 ? "本金多了" : m.flows < 0 ? "本金少了" : "本金沒有變"
  const pnl = privacy ? (
    <Masked />
  ) : (
    <span className={cn("num", toneClass(pnlDir))}>
      {formatMoney(m.pnl, { signed: true })}
      <span className="sr-only">{pnlDir === "up" ? "獲利" : pnlDir === "down" ? "虧損" : ""}</span>
    </span>
  )
  const gapText = gap ? (
    <span>
      {gap.word} <span className="num">{gap.points}</span> 個百分點
    </span>
  ) : (
    <span className="text-ink-2">—</span>
  )
  return (
    <tr className="ruled-row align-baseline">
      <th scope="row" className="py-2.5 pr-3 text-left font-normal">
        <span className="num text-lg font-medium whitespace-nowrap">{monthLabel(m.month, years)}</span>
        {/* 空白讓不完整的那幾天在窄的時候換到下一行 */}
        {span && <> <span className="num text-sm whitespace-nowrap text-ink-2">{span}</span></>}
        {/* 窄：第二行是本金增減 */}
        <span className="num mt-0.5 block text-sm text-ink-2 @[40rem]:hidden">
          {flowsWords}
          {m.flows !== 0 && <> {privacy ? <Masked /> : formatMoney(Math.abs(m.flows))}</>}
        </span>
      </th>
      <td className="hidden py-2.5 pl-3 text-right @[40rem]:table-cell">{flows}</td>
      <td className="py-2.5 pl-3 text-right">
        <span className="text-lg">{pnl}</span>
        {/* 窄：第二行是報酬率・和基準差 */}
        <span className="mt-0.5 flex flex-wrap justify-end gap-x-2 text-sm text-ink-2 @[40rem]:hidden">
          <Pct value={m.twr} />
          <span className="whitespace-nowrap">{gapText}</span>
        </span>
      </td>
      <td className="hidden py-2.5 pl-3 text-right @[40rem]:table-cell">
        <Pct value={m.twr} />
      </td>
      <td className="hidden py-2.5 pl-3 text-right whitespace-nowrap @[40rem]:table-cell">{gapText}</td>
    </tr>
  )
}

/**
 * 「贏過的台股基金（今年） 73%」（原型；金管會開放資料的境內基金每日淨值）：標籤＋數字（2026-11-22 評論：原本是一句
 * 「今年贏過 73% 的台股基金」），期間與比了幾檔寫在下面一行 13px 淡墨，來源登記到頁尾（`useSourceNote`）。
 * 怎麼比、後端的說明（基金淨值不含配息…）在績效分段最下面的「計算方式」。沒有資料時整行不放。
 * 今年有估計的那一段時，後端從真實紀錄的第一天比起，標籤就寫「（7/1 以來）」。
 */
export function FundRankLine({ r }: { r: FundRank | null | undefined }) {
  // 示範資料（mock 編的數字）不登記來源：不是那個來源的資料
  useSourceNote(r && !r.is_demo ? r.source : null)
  if (!r) return null
  const today = appToday()
  const period = fundRankPeriod(r.start, today)
  const pct = formatPercent(r.beat, { signed: false, decimals: 0 })
  const years = r.start.slice(0, 4) !== today.slice(0, 4)
  const day = (t: string) => (years ? `${t.slice(0, 4)}/` : "") + formatDateShort(t, false)
  return (
    <div className="flex flex-col gap-0.5" data-fund-rank>
      <p className="flex flex-wrap items-center gap-x-2 text-base text-ink">
        <span>
          贏過的台股基金（{period}） <span className="num font-semibold">{pct}</span>
        </span>
        {/* 示範的數字標「示範資料」（和其他示範資料同一種標記）：截圖傳出去也不會被當成真的 */}
        {r.is_demo && <DemoTag title="這是示範用的數字，不是真的基金排名" />}
      </p>
      <p className="num text-sm text-ink-2">
        {day(r.start)} – {day(r.end)}・{r.funds.toLocaleString("zh-TW")} 檔{r.universe}
      </p>
    </div>
  )
}
