import { Link } from "@tanstack/react-router"
import { appNow } from "@/api"
import type { MarketUs, MarketUsEtf } from "@/api/types"
import { Pct } from "@/components/finance"
import { NewsRow } from "@/components/news-row"
import { Sparkline } from "@/components/sparkline"
import { Tray, type TrayTint } from "@/components/tray"
import { inText } from "@/lib/cjk"
import { direction, directionGlyph, formatDateShort, formatPrice, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"

/** 美股新聞最多列幾則（後端最多給 6 則） */
const NEWS_MAX = 6

/** 「11/13 收盤（美東）」：美股收盤時台北已經是隔天早上，所以寫紐約的日期，不寫台北的時間 */
function usCloseLabel(date: string): string {
  return `${formatDateShort(date, false)} 收盤（美東）`
}

/**
 * 美股（產品負責人 2026-11-15）：SPY、DIA、ONEQ 的收盤，各自連到個股頁；下面是幾則美股新聞（GDELT，只有標題與連結）。
 * 這三檔是 ETF，不是指數：名稱是代號（寬的時候加上基金全名），下一行寫「追蹤 S&P 500」，不寫成指數本身。
 * 日期是紐約的交易日（標題旁「11/13 收盤（美東）」）；某一檔的日期和其他檔不同時，那一格自己再寫一次。
 * 一盤（托盤）：托盤夠寬（≥ 672px）時三檔是一列印好的格子（格與格之間一條直線），窄的時候（手機，或和重大訊息並排）
 * 是兩行列（代號・追蹤｜小圖｜收盤價・漲跌）。
 * 價格前面一律是 US$；走勢小圖是最近 20 個收盤，墨色。沒有收盤價、只有新聞時只列新聞；都沒有時整塊不出現。
 */
export function UsBlock({ us, tint, className }: { us: MarketUs; tint?: TrayTint; className?: string }) {
  const news = us.news.slice(0, NEWS_MAX)
  const etfs = us.items
  if (etfs.length === 0 && news.length === 0) return null
  const now = appNow()
  return (
    <Tray
      title="美股"
      meta={us.date && etfs.length > 0 ? usCloseLabel(us.date) : undefined}
      tint={tint}
      className={className}
      bodyClassName="@container"
    >
      {etfs.length > 0 && <EtfStrip items={etfs} date={us.date} />}
      {news.length > 0 && (
        <div className={cn("max-w-[46rem]", etfs.length > 0 && "mt-5")}>
          {/* 上面有 ETF 時才有自己的表頭；只有新聞時，區塊標題下面直接是新聞 */}
          {etfs.length > 0 && (
            <h3 id="market-us-news" className="form-head flex h-9 items-end pb-2">
              新聞
            </h3>
          )}
          <ul {...(etfs.length > 0 ? { "aria-labelledby": "market-us-news" } : { "aria-label": "美股新聞" })}>
            {news.map((n) => (
              <NewsRow key={`${n.url}-${n.published_at}`} item={n} now={now} />
            ))}
          </ul>
        </div>
      )}
    </Tray>
  )
}

function EtfStrip({ items, date }: { items: MarketUsEtf[]; date: string | null }) {
  const wide = items.length >= 3 ? "@2xl:grid-cols-3" : items.length === 2 ? "@2xl:grid-cols-2" : ""
  return (
    <ul aria-label="美股 ETF" className={cn("@2xl:grid", wide)}>
      {items.map((e, n) => (
        <EtfCell key={e.key} etf={e} first={n === 0} last={n === items.length - 1} ownDate={e.date !== date} />
      ))}
    </ul>
  )
}

function EtfCell({ etf: e, first, last, ownDate }: { etf: MarketUsEtf; first: boolean; last: boolean; ownDate: boolean }) {
  const values = e.sparkline.map((p) => p.v).filter((v): v is number => v !== null)
  const d = direction(e.change)
  return (
    <li className="min-w-0">
      <Link
        to="/stock/$symbol"
        params={{ symbol: e.symbol }}
        className={cn(
          // 窄：兩行列（代號・追蹤｜小圖｜收盤價・漲跌）；第三欄固定寬，三列的小圖對在同一條直線上。
          // 很窄的托盤（< 320px，320px 的手機）不放小圖與漲跌金額：代號・追蹤｜收盤價・漲跌幅（「追蹤那斯達克綜合指數」才放得下）。
          // 最後一列沒有底線：托盤的邊就是這一組的邊
          "ruled-row grid min-h-[72px] grid-cols-[minmax(0,1fr)_auto] content-center items-center gap-x-3 py-2 focus-visible:-outline-offset-2 @xs:grid-cols-[minmax(0,1fr)_64px_7.5rem]",
          last && "border-b-0",
          // 寬：一格（代號與基金名稱、追蹤、收盤價、漲跌；小圖在右邊），格與格之間一條直線
          "@2xl:block @2xl:h-full @2xl:min-h-0 @2xl:border-b-0 @2xl:py-2 @2xl:pr-5",
          !first && "@2xl:border-l @2xl:border-rule @2xl:pl-5",
        )}
      >
        <div className="min-w-0">
          <p className="flex min-w-0 items-baseline gap-2">
            <span className="text-lg leading-6 font-medium @2xl:text-base">{e.symbol}</span>
            {/* 基金全名很長：托盤窄於 448px（手機）時只給螢幕報讀器 */}
            <span className="min-w-0 truncate text-sm leading-5 text-ink-2 @max-md:sr-only" title={e.name}>
              {e.name}
            </span>
          </p>
          {/* 「追蹤」和指數名稱各自不拆開：放不下時整個指數名稱換到下一行 */}
          <p className="text-sm leading-5 text-ink-2">
            <span className="whitespace-nowrap">追蹤</span><span className="whitespace-nowrap">{inText(e.tracks, "end")}</span>
          </p>
          {ownDate && <p className="num text-sm leading-5 text-ink-2">{usCloseLabel(e.date)}</p>}
        </div>
        {/* 小圖在連結裡只給眼睛看：連結的名稱是代號、追蹤、收盤價與漲跌，不再唸一次「最近 20 個交易日」 */}
        <span aria-hidden className="hidden @xs:flex @2xl:hidden">
          {values.length >= 2 && <Sparkline width={64} height={32} values={values} tone="ink" label="" />}
        </span>
        <div className="text-right @2xl:mt-1 @2xl:flex @2xl:items-end @2xl:justify-between @2xl:gap-3 @2xl:text-left">
          <div className="min-w-0">
            <p className="num text-lg leading-6 whitespace-nowrap @2xl:text-2xl @2xl:leading-8 @2xl:font-medium">
              {e.value === null ? (
                "—"
              ) : (
                <>
                  <span className="mr-0.5 text-sm font-normal text-ink-2 @2xl:text-base">US$</span>
                  {formatPrice(e.value, "US")}
                </>
              )}
            </p>
            <p className="flex items-baseline justify-end gap-2 text-base leading-5 @2xl:justify-start">
              {e.change !== null && (
                <span className={cn("num whitespace-nowrap @max-xs:hidden @2xl:inline", toneClass(d))}>
                  {d !== "flat" && <span aria-hidden>{directionGlyph(d)}</span>}
                  {formatPrice(Math.abs(e.change), "US")}
                </span>
              )}
              <Pct value={e.change_pct} />
            </p>
          </div>
          {values.length >= 2 && (
            <span aria-hidden className="hidden shrink-0 @2xl:flex">
              <Sparkline width={84} height={36} values={values} tone="ink" label="" />
            </span>
          )}
        </div>
      </Link>
    </li>
  )
}
