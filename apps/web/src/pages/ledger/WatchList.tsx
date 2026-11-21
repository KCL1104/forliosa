import { Link } from "@tanstack/react-router"
import { useIntraday, useWatchlist } from "@/api/queries"
import type { WatchItem } from "@/api/types"
import { useUi } from "@/app/ui-store"
import { Pct } from "@/components/finance"
import { DemoTag } from "@/components/section"
import { Sparkline } from "@/components/sparkline"
import { EmptyState, ErrorState } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Tray } from "@/components/tray"
import { Skeleton } from "@/components/ui/skeleton"
import { direction } from "@/lib/format"
import { codeOf, formatQuote, marketOf } from "@/lib/tick"

/**
 * 觀察清單（內頁重新設計 2026-11-21：從持倉表的第二個 tbody 搬出來，自己一盤，排在帳本最後）。
 * 每一列兩行：左邊名稱、代號；中間今日走勢小圖（這一盤窄於 20rem 時收起）；右邊收盤價、下面漲跌幅——
 * 手機與桌面同一個樣子（和手機的持倉列同一套）。整列連到個股頁。名稱不截斷：放不下就換行。
 * 查看別人的資產時不放（觀察清單是自己的）。
 */
export function WatchList() {
  const watch = useWatchlist()
  const items = watch.data ?? []
  const demo = items.some((w) => w.quote?.is_demo ?? w.is_demo)
  return (
    <Tray
      title="觀察清單"
      meta={watch.data ? <>{items.length} 檔</> : undefined}
      action={demo ? <DemoTag /> : undefined}
      className="h-full"
    >
      {watch.isError ? (
        <ErrorState flush error={watch.error} onRetry={() => void watch.refetch()} />
      ) : watch.isLoading ? (
        <Skeleton aria-label="觀察清單載入中" className="h-[180px] w-full rounded-sm" />
      ) : items.length === 0 ? (
        <WatchEmpty />
      ) : (
        <ul aria-label="觀察清單" className="@container border-t border-rule">
          {items.map((w) => (
            <WatchRow key={w.symbol} w={w} />
          ))}
        </ul>
      )}
    </Tray>
  )
}

/** 空的時候只有標題和一個動作（打開搜尋股票，在個股頁加入觀察） */
function WatchEmpty() {
  const setSearchOpen = useUi((s) => s.setSearchOpen)
  return (
    <EmptyState
      flush
      title="還沒有觀察的股票"
      action={
        <button type="button" onClick={() => setSearchOpen(true)} className={textAction}>
          搜尋股票
        </button>
      }
    />
  )
}

function WatchRow({ w }: { w: WatchItem }) {
  const market = marketOf(w.symbol)
  // 清單本身就帶盤中點（或最近 20 個收盤）；沒有時改抓 intraday
  const fallback = useIntraday(w.symbol, w.sparkline.length < 2)
  const values = w.sparkline.length >= 2 ? w.sparkline.map((p) => p.price) : (fallback.data?.points ?? []).map((p) => p.price)
  const d = direction(w.quote?.change_pct ?? null)
  return (
    <li>
      <Link
        to="/stock/$symbol"
        params={{ symbol: w.symbol }}
        className="ruled-row grid min-h-[60px] grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 py-2 @min-[20rem]:grid-cols-[minmax(0,1fr)_76px_auto] pointer-coarse:min-h-[72px]"
      >
        <span className="min-w-0">
          <span className="block text-lg leading-6 font-medium [overflow-wrap:anywhere]">{w.name}</span>
          <span className="num block text-sm leading-5 text-ink-2">{codeOf(w.symbol)}</span>
        </span>
        <Sparkline
          className="hidden @min-[20rem]:block"
          width={76}
          height={32}
          values={values}
          baseline={w.sparkline_interval === "1d" ? null : (w.quote?.reference_price ?? w.quote?.prev_close ?? null)}
          tone="ink"
          // 美股與沒有盤中點的是最近 20 個收盤（`1d`），不說「今日」
          label={`${w.name}${w.sparkline_interval === "1d" ? "近 20 個收盤" : "今日"}走勢：${d === "up" ? "上漲" : d === "down" ? "下跌" : "平盤"}`}
        />
        <span className="flex flex-col items-end">
          <span className="num text-lg leading-6 whitespace-nowrap">
            {market === "US" && w.quote && <span className="mr-0.5 text-sm text-ink-2">US$</span>}
            {formatQuote(w.quote?.price, market)}
          </span>
          <Pct value={w.quote?.change_pct ?? null} className="text-base leading-5" />
        </span>
      </Link>
    </li>
  )
}
