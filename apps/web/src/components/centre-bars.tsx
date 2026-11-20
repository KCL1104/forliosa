import type { Currency } from "@/api/types"
import { Money, Pct } from "@/components/finance"
import { centreBars } from "@/lib/centre-bars"
import { cn } from "@/lib/utils"

export interface CentreBarRow {
  /** React key（代號、類股名稱） */
  id: string
  /** 全名：寬的時候顯示（放不下就換行，不截斷）；任何寬度都給螢幕閱讀器 */
  label: string
  /** 窄的時候（這張圖 < 18rem，320px 的手機）顯示的代號或簡稱；滑過看得到全名。沒給就照樣顯示全名 */
  short?: string
  /** 有正負的數值：決定往哪邊、多長，也是右邊印出來的數字（漲跌幅 0.0123＝1.23%；金額是元） */
  value: number
}

/** 金額的方向：螢幕閱讀器在數字後面念（漲跌幅由 `Pct` 念「上漲／下跌／持平」） */
const PNL_WORD = { up: "獲利", down: "虧損", flat: "持平" } as const

/**
 * 中線橫條（產品負責人 2026-11-21，方向 C 的「以 0 為中線的長條」）：帳本每一檔的今日損益、市場的類股漲跌。
 *
 * 每列是名稱、一條從中線往右（漲、獲利）或往左（跌、虧損）的橫條、右邊印好的數字。所有列共用一個比例
 * （最大的絕對值佔滿半邊，`lib/centre-bars.ts`），中線固定在正中間、一列接一列連成一條 1px `ctl` 線。
 * 橫條和市場頁的類股同一種：高 6px、漲跌色 65%、最短 3px；顏色跟著紅漲綠跌／綠漲紅跌的設定（`--rise`／`--fall`）。
 * 方向不只靠顏色：靠位置、數字的 ▲▼（漲跌幅）或 +／−（金額），螢幕閱讀器另外念「上漲／下跌」或「獲利／虧損」。
 * 數字是主角，橫條只幫忙比大小：橫條對螢幕閱讀器隱藏，每列念「名稱 數字 方向」；沒有提示框、沒有動畫。
 *
 * 數字由這個元件印，不由呼叫端格式化：`unit="pct"` 是 `Pct`（▲4.81%，不受隱私模式影響），
 * `unit="money"` 是 `Money`（+NT$1,234，帶正負號、隱私模式遮蔽）。
 * 列的順序照傳進來的（通常由大到小）；要收起中間幾列、要「全部 N 個」由呼叫端決定。
 */
export function CentreBars({
  rows,
  unit,
  currency = "TWD",
  decimals,
  scale,
  label,
  className,
}: {
  rows: readonly CentreBarRow[]
  unit: "pct" | "money"
  /** `unit="money"` 的幣別 */
  currency?: Currency
  /** 小數位（漲跌幅預設 2 位；金額照幣別：NT$ 0 位、US$ 2 位） */
  decimals?: number
  /** 共用的比例：一份清單分成幾欄、每欄各畫一張時，傳整份清單最大的絕對值（見 `centreBars`）；沒給就用這幾列自己的 */
  scale?: number
  /** 清單的名稱（給螢幕閱讀器；托盤的標題已經說了就不用） */
  label?: string
  className?: string
}) {
  if (rows.length === 0) return null
  const bars = centreBars(rows.map((r) => r.value), scale)
  const short = rows.some((r) => r.short)
  return (
    <div className={cn("@container", className)}>
      {/* 名稱欄最寬 9em（窄的時候換成代號，最寬 5em），再長就換行；橫條欄至少 2.5rem；數字欄照最長的數字。
          各列用同一組欄（subgrid），中線對齊。沒有代號的清單（類股）窄的時候照樣 9em：換成 5em 只會讓名稱斷成兩行 */}
      <ol
        role="list"
        aria-label={label}
        className={cn(
          "grid grid-cols-[fit-content(9em)_minmax(2.5rem,1fr)_max-content] gap-x-3",
          short && "@max-2xs:grid-cols-[fit-content(5em)_minmax(2.5rem,1fr)_max-content]",
        )}
      >
        {rows.map((r, i) => {
          const bar = bars[i]!
          return (
            <li key={r.id} className="group col-span-full grid min-h-10 grid-cols-subgrid items-center border-b border-rule last:border-b-0">
              <span className="min-w-0 py-2 text-base text-ink [overflow-wrap:anywhere]">
                {r.short ? (
                  <>
                    <span className="@max-2xs:sr-only">{r.label}</span>
                    <span aria-hidden title={r.label} className="num hidden whitespace-nowrap @max-2xs:inline">
                      {r.short}
                    </span>
                  </>
                ) : (
                  r.label
                )}
              </span>
              <span aria-hidden className="relative self-stretch">
                {bar.share > 0 && (
                  <span
                    data-bar={bar.side}
                    className={cn(
                      "absolute top-1/2 h-1.5 w-[max(3px,var(--bar))] -translate-y-1/2 rounded-xs",
                      bar.side === "up" ? "left-1/2 bg-rise/65" : "right-1/2 bg-fall/65",
                    )}
                    style={{ "--bar": `${+(bar.share * 50).toFixed(3)}%` } as React.CSSProperties}
                  />
                )}
                {/* 中線：蓋過列底的格線，一列接一列連成一條 */}
                <span data-zero-line="" className="absolute top-0 -bottom-px left-1/2 w-px bg-ctl group-last:bottom-0" />
              </span>
              <span className="justify-self-end">
                {unit === "pct" ? (
                  <Pct value={r.value} decimals={decimals} className="text-base" />
                ) : (
                  <>
                    <Money value={r.value} currency={currency} decimals={decimals} signed tone className="text-base" />
                    <span className="sr-only">{PNL_WORD[bar.side]}</span>
                  </>
                )}
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
