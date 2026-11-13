import type { MarketIndex } from "@/api/types"
import { Pct } from "@/components/finance"
import { Sparkline } from "@/components/sparkline"
import { direction, directionGlyph, formatDateShort, formatNumber, toneClass } from "@/lib/format"
import { cn } from "@/lib/utils"

/** 小數位：指數 2 位、期貨是整數點、匯率 3 位（央行公布到小數第三位） */
const DECIMALS: Record<MarketIndex["key"], number> = { taiex: 2, tpex: 2, tx: 0, usdtwd: 3 }

/**
 * 指數那一列：加權、櫃買、（授權開了才有的）台指期近月、美元兌新台幣。
 * 不是卡片：寬的時候是一列印好的格子（上下各一條格線、格與格之間一條直線），窄的時候是和持倉表同一種的兩行列。
 * 每一格帶自己的日期：上市、上櫃、匯率公布的時間不一樣。走勢小圖是最近 20 個收盤（墨色，不跟著當天漲跌換色）；
 * 不到兩點就不畫。這些不是連結（沒有指數頁）。
 */
export function IndexStrip({ indices }: { indices: MarketIndex[] }) {
  const wide = indices.length >= 4 ? "@2xl:grid-cols-2 @4xl:grid-cols-4" : indices.length === 3 ? "@2xl:grid-cols-3" : indices.length === 2 ? "@2xl:grid-cols-2" : ""
  return (
    <ul aria-label="指數與匯率" className={cn("border-t border-rule @2xl:grid @2xl:border-b", wide)}>
      {indices.map((i, n) => (
        <IndexCell key={i.key} index={i} first={n === 0} four={indices.length >= 4} position={n} />
      ))}
    </ul>
  )
}

function IndexCell({ index: i, first, four, position }: { index: MarketIndex; first: boolean; four: boolean; position: number }) {
  const decimals = DECIMALS[i.key] ?? 2
  const values = i.sparkline.map((p) => p.v).filter((v): v is number => v !== null)
  const d = direction(i.change)
  return (
    <li
      className={cn(
        // 窄：兩行列（名稱・日期｜小圖｜數值・漲跌）
        "grid min-h-[72px] grid-cols-[minmax(0,1fr)_76px_auto] content-center items-center gap-x-3 border-b border-rule py-2",
        // 寬：一格（名稱、數值、漲跌；小圖在右邊），格與格之間一條直線
        "@2xl:block @2xl:min-h-0 @2xl:border-b-0 @2xl:py-4 @2xl:pr-5",
        !first && "@2xl:border-l @2xl:border-rule @2xl:pl-5",
        // 四格在中等寬度排成 2×2：第二列上面一條線，每列第一格不畫直線
        four && position >= 2 && "@2xl:border-t @4xl:border-t-0",
        four && position === 2 && "@2xl:border-l-0 @2xl:pl-0 @4xl:border-l @4xl:pl-5",
      )}
    >
      <div className="min-w-0 @2xl:flex @2xl:items-baseline @2xl:gap-2">
        <p className="truncate text-lg leading-6 font-medium @2xl:text-base @2xl:font-normal">{i.name}</p>
        <p className="num text-sm leading-5 text-ink-2">{formatDateShort(i.date, false)}</p>
      </div>
      {values.length >= 2 ? (
        <Sparkline
          className="@2xl:hidden"
          width={76}
          height={32}
          values={values}
          tone="ink"
          label={`${i.name}最近 ${values.length} 個交易日的收盤`}
        />
      ) : (
        <span aria-hidden className="@2xl:hidden" />
      )}
      <div className="text-right @2xl:mt-1 @2xl:flex @2xl:items-end @2xl:justify-between @2xl:gap-3 @2xl:text-left">
        <div className="min-w-0">
          <p className="num text-lg leading-6 @2xl:text-2xl @2xl:leading-8 @2xl:font-medium">
            {i.value === null ? "—" : formatNumber(i.value, decimals)}
            <span className="sr-only"> {i.unit}</span>
          </p>
          <p className="flex items-baseline justify-end gap-2 text-base leading-5 @2xl:justify-start">
            {i.change !== null && (
              <span className={cn("num whitespace-nowrap max-[23rem]:hidden @2xl:inline", toneClass(d))}>
                {d !== "flat" && <span aria-hidden>{directionGlyph(d)}</span>}
                {formatNumber(Math.abs(i.change), decimals)}
              </span>
            )}
            <Pct value={i.change_pct} />
          </p>
        </div>
        {values.length >= 2 && (
          <Sparkline
            className="hidden shrink-0 @2xl:block"
            width={84}
            height={36}
            values={values}
            tone="ink"
            label={`${i.name}最近 ${values.length} 個交易日的收盤`}
          />
        )}
      </div>
    </li>
  )
}
