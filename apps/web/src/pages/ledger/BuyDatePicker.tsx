import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { appToday } from "@/api"
import { useTradedHistory, useUpdateTransaction } from "@/api/queries"
import type { Candle, InstrumentType, Market, Transaction } from "@/api/types"
import { DataNotes } from "@/components/data-notes"
import { RangeChips } from "@/components/segmented"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsDesktop } from "@/hooks/use-media-query"
import { useSourceNote } from "@/hooks/use-source-note"
import { candidateDays, indexOnOrBefore } from "@/lib/buy-date"
import { formatPrice, formatPriceLevel, formatQuantity } from "@/lib/format"
import { trendDomain } from "@/lib/trend-range"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { pickDay, pickFromLine, readoutLine } from "./buy-date-text"

/**
 * 在走勢圖上選買入日（資產組成原型；`docs/proposals/asset-composition.md`〈估計買入日的算法〉）：
 * 匯入庫存時估的買入日（或找不到、用了匯入那天的）可以自己改。
 * - 圖：這一檔五年的收盤（當時的成交價，`getHistory(…, { asTraded: true, until: 匯入那天 })`），一條墨色疏點橫線是成本
 *   （和個股走勢圖的均價線同一種線），股價經過成本的日子（`lib/buy-date.ts`，用最高、最低價判斷，跳空也算）是橫線上的空心圈。
 * - 候選的日子也列成一排可以按的列（手機 44px 高）：五年的圖在 360px 的手機上一天不到 1px，用手指點不到；
 *   自動估的那天標「估計」，現在記的那天標「目前的日期」，打開時先選現在記的那天。
 * - 點圖上任何一天、按住橫拖、或用鍵盤（← → 一天、Page Up／Page Down 跳到上一個／下一個候選、Home／End 到頭尾）都可以選。
 * - 選的那天收盤和成本差 3% 以上時照實說（「這天收盤 580，和你的成本 612.4 差 5.2%。」）。
 * - 「改成 2024/8/14」只改日期（價格、股數、手續費照舊），之後這一筆標「自己選的日期」。
 * - 匯入以前最近一次股票分割、減資、配股（`pick_from`）以前的日子不在圖上、不能選：券商的股數與均價已經算進那一次，
 *   買在那天以前的話帳本會多算一次配股、拿現在的股數乘當時的價格。資料說明多一行「2025/6/18 股票分割，之前的日子不能選」。
 * 隱私模式：成本是自己的數字，遮掉（圖的縱軸、成本線的標籤、說明裡的成本都不寫），收盤價照常。
 */

type Span = "1Y" | "3Y" | "5Y"
const SPANS: readonly { value: Span; label: string }[] = [
  { value: "1Y", label: "1年" },
  { value: "3Y", label: "3年" },
  { value: "5Y", label: "5年" },
]
const YEARS: Record<Span, number> = { "1Y": 1, "3Y": 3, "5Y": 5 }
/** 一開始列幾個候選；更早的按「看更早的」 */
const CANDIDATES_SHOWN = 5
/** 按住橫向拖超過這麼多 px 才開始選（直向照常捲動對話框） */
const DRAG_SLOP = 8
/** 點的位置離候選的日子幾 px 以內就選那個候選 */
const SNAP = 8
const TOP = 10
const AXIS = 22
const TICK_FONT = 12

/** 往前推 n 年（2026-11-12 → 2023-11-12） */
const minusYears = (day: string, n: number) => `${Number(day.slice(0, 4)) - n}${day.slice(4)}`

export function BuyDatePicker({
  lot,
  name,
  market,
  type,
  open,
  onOpenChange,
}: {
  lot: Transaction
  name: string
  market: Market
  type?: InstrumentType
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-[640px]">
        {open && <PickerBody lot={lot} name={name} market={market} type={type} onClose={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function PickerBody({ lot, name, market, type, onClose }: { lot: Transaction; name: string; market: Market; type?: InstrumentType; onClose: () => void }) {
  const history = useTradedHistory(lot.symbol!, lot.imported_on)
  // 日線的來源（存檔以前是 Yahoo 回補）登記到頁尾的資料來源
  useSourceNote(history.data?.sources)
  const update = useUpdateTransaction()
  const privacy = usePrefs((s) => s.privacyMode)
  const unit = usePrefs((s) => s.quantityUnit)
  const cost = lot.price ?? 0
  const until = lot.imported_on ?? appToday()
  const usd = market === "US" ? "US$" : ""
  const price = (p: number) => `${usd}${formatPrice(p, market, type)}`
  const costText = price(cost)
  // 匯入以前最近一次分割、減資、配股（`pick_from`）：券商的股數與均價已經算進去了，更早的日子不能選
  const pickFrom = history.data?.pick_from ?? null
  // 只看匯入那天（含）以前（買進一定在匯入以前），而且不早於 `pick_from`（那天本身可以）
  const candles = useMemo(() => (history.data?.candles ?? []).filter((c) => c.t <= until && (!pickFrom || c.t >= pickFrom.date)), [history.data, until, pickFrom])
  // `pick_from` 真的拿掉了一些日子才說（一行，講事實）
  const limitLine = pickFrom && (history.data?.candles ?? []).some((c) => c.t < pickFrom.date) ? pickFromLine(pickFrom) : null
  const candidates = useMemo(() => candidateDays(candles, cost), [candles, cost])
  // 帳本上現在的日期在 K 線裡的位置：那一天，或那天沒有收盤（週末、假日、收盤前匯入）時前一個收盤日。
  // 打開時選的就是它；「改成…」只在選了別的收盤日時才能按——不會替使用者把星期六改成星期五。
  // 帳本上的日期比能選的第一天還早（`pick_from` 以前的舊紀錄）：圖上沒有它，什麼都不先選
  const initialIdx = candles.length && lot.trade_date >= candles[0]!.t ? indexOnOrBefore(candles, lot.trade_date) : -1
  const [picked, setPicked] = useState<number | null>(null)
  const [span, setSpan] = useState<Span | null>(null)
  const [more, setMore] = useState(false)
  const listId = useId()
  const sel = picked ?? initialIdx
  const selCandle = sel >= 0 ? candles[sel] : undefined
  // 有資料的區間才放（美股只有 2024/7/1 以後的：3 年、5 年和 1 年一樣時不放）；只剩一個就整排不放
  const lastDay = candles.at(-1)?.t ?? until
  const spans = SPANS.filter((_, i) => i === 0 || (candles[0] !== undefined && candles[0].t < minusYears(lastDay, YEARS[SPANS[i - 1]!.value])))
  const fit = (t: string) => spans.find((s) => t >= minusYears(lastDay, YEARS[s.value]))?.value ?? spans.at(-1)!.value
  // 區間：預設是包得住現在那天的最短一個
  const shownSpan = span && spans.some((s) => s.value === span) ? span : fit(candles[initialIdx]?.t ?? lot.trade_date)

  const choose = (i: number) => {
    setPicked(i)
    // 選的那天不在現在的區間裡：換成包得住它的最短一個
    const t = candles[i]!.t
    if (t < minusYears(lastDay, YEARS[shownSpan])) setSpan(fit(t))
  }

  const changed = !!selCandle && sel !== initialIdx
  const confirm = () => {
    if (!selCandle) return
    const day = selCandle.t
    // 只改日期：手續費、稅照原本的一起送（後端改了輸入時，沒送的費用當 0）
    update.mutate(
      { id: lot.id, patch: { trade_date: day, fee: lot.fee, tax: lot.tax, date_basis: "picked" } },
      {
        onSuccess: () => {
          toast.success(`已改成 ${pickDay(day)} 買進`)
          onClose()
        },
        onError: (err) => toast.error("沒有改成功，日期照舊。", { description: err.message }),
      },
    )
  }

  const shown = more ? candidates : candidates.slice(0, CANDIDATES_SHOWN)
  const facts = [privacy ? null : `成本 ${costText}`, lot.quantity ? (privacy ? null : formatQuantity(lot.quantity, unit, market)) : null, lot.imported_on ? `${pickDay(lot.imported_on)} 匯入` : null].filter(Boolean)

  return (
    <>
      <DialogHeader>
        <DialogTitle>{name}的買入日</DialogTitle>
        {facts.length > 0 && <p className="num text-sm text-ink-2">{facts.join("・")}</p>}
      </DialogHeader>

      {history.isError ? (
        <ErrorState error={history.error} onRetry={() => void history.refetch()} />
      ) : !history.data ? (
        <div aria-busy="true" aria-label="走勢載入中" className="flex flex-col gap-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-[168px] w-full sm:h-[200px]" />
        </div>
      ) : candles.length === 0 ? (
        <p className="text-base text-ink">沒有這一檔的走勢，沒辦法在圖上選日期。</p>
      ) : (
        <div className="flex min-w-0 flex-col gap-3">
          <Readout candles={candles} sel={sel} initialIdx={initialIdx} cost={cost} costText={costText} price={price} lot={lot} privacy={privacy} />
          <PriceChart
            candles={candles}
            cost={cost}
            costText={costText}
            span={shownSpan}
            candidates={candidates}
            sel={sel}
            privacy={privacy}
            market={market}
            type={type}
            onSelect={choose}
          />
          {spans.length > 1 && <RangeChips label="走勢的長度" value={shownSpan} options={spans} onChange={setSpan} />}
          {/* 分割、減資、配股以前的日子不能選：一行（「2025/6/18 股票分割，之前的日子不能選」），和資料說明放在一起 */}
          <DataNotes notes={[...(limitLine ? [limitLine] : []), ...(history.data.notes ?? [])]} />

          <div>
            <h3 className="form-head pb-1.5">股價經過成本的日子</h3>
            {candidates.length === 0 ? (
              // 照實寫有資料的那幾年（美股只從 2024/7/1 開始，不是五年）
              <p className="py-3 text-base text-ink">
                {pickDay(candles[0]!.t)} – {pickDay(candles.at(-1)!.t)} 的股價都沒有經過成本{privacy ? "" : ` ${costText}`}。
              </p>
            ) : (
              <>
                <CandidateList id={listId} candles={candles} indexes={shown} sel={sel} initialIdx={initialIdx} lot={lot} price={price} onSelect={choose} />
                {candidates.length > CANDIDATES_SHOWN && (
                  <button
                    type="button"
                    aria-expanded={more}
                    aria-controls={listId}
                    onClick={() => setMore(!more)}
                    className="mt-1 inline-flex min-h-9 items-center gap-1 text-md text-ink underline decoration-ctl underline-offset-4 hover:decoration-ink pointer-coarse:min-h-11"
                  >
                    {more ? "只看最近的" : `看更早的 ${candidates.length - CANDIDATES_SHOWN} 次`}
                    <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", more && "rotate-180")} />
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* 頁尾黏在對話框的下緣：手機上候選很多、要捲的時候「改成…」也一直看得到 */}
      <DialogFooter className="sticky -bottom-5 z-10 -mx-5 -mb-5 bg-raised px-5 pb-5">
        <Button type="button" variant="outline" onClick={onClose}>
          取消
        </Button>
        <Button type="button" variant="sign" disabled={!changed || update.isPending} onClick={confirm}>
          {update.isPending ? "儲存中" : changed ? `改成 ${pickDay(selCandle.t)}` : "改日期"}
        </Button>
      </DialogFooter>
    </>
  )
}

/**
 * 標記：自動估的那天「估計」、帳本上現在的日期「目前的日期」（和持倉展開的標記同一種細框小字）。
 * 帳本上的日期那天沒有收盤時，「目前的日期」標在它前一個收盤日（`initialIdx`）。
 */
function DayTags({ candles, i, initialIdx, lot }: { candles: Candle[]; i: number; initialIdx: number; lot: Transaction }) {
  const auto = !!lot.estimated_date && candles[i]?.t === lot.estimated_date
  const current = i === initialIdx
  return (
    <>
      {auto && <span className="status-tag">估計</span>}
      {current && <span className="status-tag">目前的日期</span>}
    </>
  )
}

/**
 * 讀數（圖上方、固定高度，畫面不跳）：選的那一天與收盤價、標記；下一行見 `readoutLine`。
 */
function Readout({
  candles,
  sel,
  initialIdx,
  cost,
  costText,
  price,
  lot,
  privacy,
}: {
  candles: Candle[]
  sel: number
  initialIdx: number
  cost: number
  costText: string
  price: (p: number) => string
  lot: Transaction
  privacy: boolean
}) {
  const candle = candles[sel]
  if (!candle) return <div className="h-[4.5rem] sm:h-12" />
  const line = readoutLine(candles, sel, { cost, costText, price, lotDate: lot.trade_date, initialIdx, privacy })
  return (
    // 高度固定（換日子時圖不會上下跳）：手機上那一句可能要兩行（美股的價格比較長），所以留三行
    <div className="h-[4.5rem] sm:h-12" aria-live="polite" data-picker-readout>
      <p className="num flex items-baseline gap-x-3 overflow-hidden text-base leading-6 whitespace-nowrap">
        <span className="min-w-0 truncate text-ink">{pickDay(candle.t)}</span>
        <span className="shrink-0 text-ink-2">
          收盤 <span className="font-semibold text-ink">{price(candle.c)}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <DayTags candles={candles} i={sel} initialIdx={initialIdx} lot={lot} />
        </span>
      </p>
      {line && <p className={cn("leading-6", line.strong ? "text-base text-ink" : "text-sm text-ink-2")}>{line.text}</p>}
    </div>
  )
}

/** 候選的日子：一個一列（radio），手機 44px 高；選取是清單的選取語法 (c)（淡墨底＋開頭 2px 墨色線） */
function CandidateList({
  id,
  candles,
  indexes,
  sel,
  initialIdx,
  lot,
  price,
  onSelect,
}: {
  id: string
  candles: Candle[]
  indexes: number[]
  sel: number
  initialIdx: number
  lot: Transaction
  price: (p: number) => string
  onSelect: (i: number) => void
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const focusable = indexes.includes(sel) ? sel : indexes[0]
  const onKeyDown = (e: React.KeyboardEvent, k: number) => {
    const delta = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = (k + delta + indexes.length) % indexes.length
    onSelect(indexes[next]!)
    refs.current[next]?.focus()
  }
  return (
    <div id={id} role="radiogroup" aria-label="股價經過成本的日子">
      {indexes.map((i, k) => {
        const c = candles[i]!
        const checked = i === sel
        return (
          <button
            key={c.t}
            ref={(el) => {
              refs.current[k] = el
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={i === focusable ? 0 : -1}
            onKeyDown={(e) => onKeyDown(e, k)}
            onClick={() => onSelect(i)}
            className="num flex min-h-11 w-full flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule px-2 py-1.5 text-left text-base outline-offset-[-2px] hover:bg-hov aria-checked:bg-hov aria-checked:shadow-[inset_2px_0_0_var(--ink)] lg:min-h-10"
          >
            <span className="whitespace-nowrap text-ink">{pickDay(c.t)}</span>
            <span className="text-sm whitespace-nowrap text-ink-2">收盤 {price(c.c)}</span>
            {/* 標記放不下時換到下一行（列跟著變高，不擠掉日期） */}
            <span className="ml-auto flex items-center gap-1.5">
              <DayTags candles={candles} i={i} initialIdx={initialIdx} lot={lot} />
            </span>
          </button>
        )
      })}
    </div>
  )
}

function useWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(fallback)
  useLayoutEffect(() => {
    const w = Math.floor(ref.current?.clientWidth ?? 0)
    if (w > 0) setWidth(w)
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === "undefined") return
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.floor(entry!.contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

/**
 * 價格走勢（自己畫的 SVG，不載 Lightweight Charts）：收盤 2px 墨色線＋底下淡出的墨色面積（上緣 10%、到下緣 0%；和個股走勢圖、
 * 總資產走勢同一個規格，2026-11-20）、成本 1px 墨色疏點橫線（右邊寫「成本 612.4」）、
 * 經過成本的日子是橫線上的空心圈、選的那天一條鉛筆灰直線＋墨色圓點。可以聚焦，鍵盤逐日、跳候選。
 */
function PriceChart({
  candles,
  cost,
  costText,
  span,
  candidates,
  sel,
  privacy,
  market,
  type,
  onSelect,
}: {
  candles: Candle[]
  cost: number
  costText: string
  span: Span
  candidates: number[]
  sel: number
  privacy: boolean
  market: Market
  type?: InstrumentType
  onSelect: (i: number) => void
}) {
  const desktop = useIsDesktop()
  const height = desktop ? 200 : 168
  const [wrapRef, width] = useWidth(desktop ? 600 : 288)
  const drag = useRef<{ id: number; x: number; y: number; on: boolean } | null>(null)
  const areaId = `picker-area-${useId().replace(/[^\w-]/g, "")}`
  const last = candles.at(-1)!.t
  const start = indexOnOrBefore(candles, minusYears(last, YEARS[span]))
  // 不手寫 useMemo：交給 React Compiler（這裡的計算很便宜，五年約 1,250 點）
  const view = candles.slice(start)
  const n = view.length
  const { ticks, min, max } = trendDomain([...view.map((c) => c.c), cost], { minSpan: 0.05, pad: 0.1 })
  const labels = ticks.map((v) => formatPriceLevel(v, market, type))
  const left = privacy ? 4 : Math.max(...labels.map((s) => s.length * 7)) + 10
  const plotW = Math.max(40, width - left - 6)
  const plotH = height - TOP - AXIS
  const y = (v: number) => TOP + (1 - (v - min) / (max - min || 1)) * plotH
  const x = (i: number) => left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW)
  const line = view.map((c, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(c.c).toFixed(1)}`).join("")
  // 線底下淡出的墨色面積（收到圖的下緣）
  const area = n > 1 ? `${line}L${x(n - 1).toFixed(1)} ${(TOP + plotH).toFixed(1)}L${x(0).toFixed(1)} ${(TOP + plotH).toFixed(1)}Z` : null
  // 橫軸：一年以內標每季第一個交易日（「2025/7」），更長的標每年第一個交易日（「2024」）
  const xLabels: { i: number; text: string }[] = []
  for (let i = 1; i < n; i++) {
    const prev = view[i - 1]!.t
    const t = view[i]!.t
    if (span === "1Y" ? t.slice(5, 7) !== prev.slice(5, 7) && ["01", "04", "07", "10"].includes(t.slice(5, 7)) : t.slice(0, 4) !== prev.slice(0, 4)) {
      xLabels.push({ i, text: span === "1Y" ? `${t.slice(0, 4)}/${Number(t.slice(5, 7))}` : t.slice(0, 4) })
    }
  }
  const visible = candidates.filter((i) => i >= start).map((i) => i - start)
  const local = sel - start

  const pick = (clientX: number, box: DOMRect, snap: boolean) => {
    const px = clientX - box.left
    let i = Math.max(0, Math.min(n - 1, n === 1 ? 0 : Math.round(((px - left) / plotW) * (n - 1))))
    if (snap) {
      let best = -1
      for (const c of visible) if (Math.abs(x(c) - px) <= SNAP && (best < 0 || Math.abs(x(c) - px) < Math.abs(x(best) - px))) best = c
      if (best >= 0) i = best
    }
    onSelect(i + start)
  }
  const onKey = (e: React.KeyboardEvent) => {
    let next: number | undefined
    const cur = Math.max(0, local)
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") next = Math.max(0, Math.min(n - 1, cur + (e.key === "ArrowRight" ? 1 : -1)))
    else if (e.key === "Home") next = 0
    else if (e.key === "End") next = n - 1
    else if (e.key === "PageUp") next = [...visible].sort((a, b) => b - a).find((c) => c < cur) ?? cur
    else if (e.key === "PageDown") next = [...visible].sort((a, b) => a - b).find((c) => c > cur) ?? cur
    if (next === undefined) return
    e.preventDefault()
    onSelect(next + start)
  }
  const costY = y(cost)
  const selDay = candles[sel]?.t
  return (
    <div
      ref={wrapRef}
      className="relative touch-pan-y rounded-xs outline-offset-2 select-none [-webkit-touch-callout:none] focus-visible:outline-2 focus-visible:outline-ring"
      tabIndex={0}
      role="group"
      aria-label="價格走勢：用左右方向鍵逐日選，Page Up、Page Down 跳到股價經過成本的日子"
      onKeyDown={onKey}
      onPointerDown={(e) => {
        if (e.pointerType === "mouse") return pick(e.clientX, e.currentTarget.getBoundingClientRect(), true)
        drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, on: false }
      }}
      onPointerMove={(e) => {
        if (e.pointerType === "mouse") {
          if (e.buttons === 1) pick(e.clientX, e.currentTarget.getBoundingClientRect(), false)
          return
        }
        const d = drag.current
        if (!d || d.id !== e.pointerId) return
        if (!d.on) {
          const dx = Math.abs(e.clientX - d.x)
          if (dx < DRAG_SLOP || dx < Math.abs(e.clientY - d.y)) return
          d.on = true
          e.currentTarget.setPointerCapture?.(e.pointerId)
        }
        pick(e.clientX, e.currentTarget.getBoundingClientRect(), false)
      }}
      onPointerUp={(e) => {
        if (e.pointerType === "mouse") return
        const d = drag.current
        drag.current = null
        // 點一下（沒有拖）：選那一天，離候選近的話就選候選
        if (d && !d.on) pick(e.clientX, e.currentTarget.getBoundingClientRect(), true)
      }}
      onPointerCancel={() => {
        drag.current = null
      }}
    >
      <svg
        role="img"
        aria-label={`收盤價走勢，${view[0]!.t.replaceAll("-", "/")} 到 ${last.replaceAll("-", "/")}，股價經過成本的日子有 ${candidates.length} 次${selDay ? `，選了 ${selDay.replaceAll("-", "/")}` : ""}`}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="block max-w-full overflow-visible"
      >
        {ticks.map((v, i) => (
          <g key={v}>
            <line x1={left} x2={left + plotW} y1={y(v)} y2={y(v)} stroke="var(--chart-grid)" strokeWidth={1} />
            {!privacy && (
              <text x={left - 8} y={y(v)} textAnchor="end" dominantBaseline="central" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
                {labels[i]}
              </text>
            )}
          </g>
        ))}
        {xLabels.map((l) => (
          <text key={l.i} x={Math.min(x(l.i), width - 20)} y={height - 5} textAnchor="middle" fontSize={TICK_FONT} fill="var(--muted-foreground)" className="num">
            {l.text}
          </text>
        ))}
        {local >= 0 && local < n && <line x1={x(local)} x2={x(local)} y1={TOP} y2={TOP + plotH} stroke="var(--ctl)" strokeWidth={1} />}
        {area && (
          <>
            <defs>
              <linearGradient id={areaId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--chart-mine)" stopOpacity={0.1} />
                <stop offset="100%" stopColor="var(--chart-mine)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <path d={area} fill={`url(#${areaId})`} data-series="area" />
          </>
        )}
        <path d={line} fill="none" stroke="var(--chart-mine)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" data-series="close" />
        {/* 成本：墨色疏點橫線（和個股走勢圖的均價線同一種），隱私模式也畫線、只是不寫數字 */}
        <line x1={left} x2={left + plotW} y1={costY} y2={costY} stroke="var(--chart-mine)" strokeWidth={1} strokeDasharray="1 3" strokeLinecap="round" data-series="cost" />
        {visible.map((i) => (
          <circle key={view[i]!.t} cx={x(i)} cy={costY} r={3.5} fill="var(--background)" stroke="var(--chart-mine)" strokeWidth={1.25} data-candidate={view[i]!.t} />
        ))}
        {local >= 0 && local < n && <circle cx={x(local)} cy={y(view[local]!.c)} r={4} fill="var(--chart-mine)" stroke="var(--background)" strokeWidth={2} data-selected />}
      </svg>
      {/* 成本線的標籤（HTML）：右邊、線的上方；隱私模式只寫「成本」 */}
      <span
        aria-hidden
        className="num pointer-events-none absolute right-1.5 bg-raised px-1 text-xs leading-4 text-ink"
        style={{ top: Math.max(0, costY - 17) }}
      >
        {privacy ? "成本" : `成本 ${costText}`}
      </span>
    </div>
  )
}

