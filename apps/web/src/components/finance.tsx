import NumberFlow from "@number-flow/react"
import type { Currency, Market, QuantityUnit, TransactionSource } from "@/api/types"
import {
  direction,
  directionGlyph,
  formatMoney,
  formatMoneyCompact,
  formatPercent,
  formatPrice,
  formatQuantity,
  MASK,
  MINUS,
  toneClass,
  type Direction,
} from "@/lib/format"
import { SOURCE_TAG } from "@/lib/labels"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

/** 隱私模式遮罩：固定寬度、螢幕閱讀器讀「已隱藏」 */
export function Masked({ className }: { className?: string }) {
  return (
    <span className={cn("num tracking-widest text-muted-foreground", className)} aria-label="已隱藏">
      {MASK}
    </span>
  )
}

interface MoneyProps {
  value: number
  currency?: Currency
  signed?: boolean
  /** 空間不足時用萬／億縮寫（仍受「數字縮寫」偏好控制） */
  compact?: boolean
  decimals?: number
  /** 依正負上色（損益） */
  tone?: boolean
  /** 忽略隱私模式（例如百分比以外的公開資訊：股價） */
  publicValue?: boolean
  className?: string
}

/** 金額：處理隱私模式、萬／億縮寫、漲跌色 */
export function Money({ value, currency = "TWD", signed, compact, decimals, tone, publicValue, className }: MoneyProps) {
  const privacy = usePrefs((s) => s.privacyMode)
  const allowCompact = usePrefs((s) => s.compactNumbers)
  if (privacy && !publicValue) return <Masked className={className} />
  const text =
    compact && allowCompact ? formatMoneyCompact(value, { currency, signed }) : formatMoney(value, { currency, signed, decimals })
  const full = formatMoney(value, { currency, signed, decimals })
  return (
    <span className={cn("num whitespace-nowrap", tone && toneClass(direction(value)), className)} title={text !== full ? full : undefined}>
      {text}
    </span>
  )
}

/** 漲跌幅：顏色＋▲▼（色弱可辨），百分比不受隱私模式影響 */
export function Pct({ value, className, glyph = true, decimals = 2 }: { value: number | null | undefined; className?: string; glyph?: boolean; decimals?: number }) {
  const d = direction(value)
  return (
    <span className={cn("num inline-flex items-baseline gap-0.5 whitespace-nowrap", toneClass(d), className)}>
      {glyph && d !== "flat" && <span aria-hidden className="leading-none">{directionGlyph(d)}</span>}
      {/* 有 ▲▼ 時不再加正負號（台灣慣例：▲4.81%） */}
      <span>{formatPercent(glyph && value !== null && value !== undefined ? Math.abs(value) : value, { decimals, signed: !glyph })}</span>
      {glyph && <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>}
    </span>
  )
}

/** 價格（公開資訊，不遮蔽）；沒有報價時顯示「—」 */
export function Price({ value, market, className }: { value: number | null | undefined; market: Market; className?: string }) {
  return <span className={cn("num whitespace-nowrap", className)}>{formatPrice(value, market)}</span>
}

/** 漲跌點數＋幅度，例如「▲ 15.00（+1.40%）」；沒有昨收時無法計算，顯示「—」 */
export function PriceChange({ change, pct, market, className }: { change: number | null; pct: number | null; market: Market; className?: string }) {
  if (change === null) {
    return (
      <span className={cn("num text-muted-foreground", className)} title="資料源沒有提供昨收，無法計算漲跌">
        —
      </span>
    )
  }
  const d = direction(change)
  const abs = formatPrice(Math.abs(change), market)
  return (
    <span className={cn("num inline-flex items-baseline gap-1.5 whitespace-nowrap", toneClass(d), className)}>
      <span>
        {d !== "flat" && <span aria-hidden className="mr-0.5">{directionGlyph(d)}</span>}
        {d === "down" ? MINUS : d === "up" ? "+" : ""}
        {abs}
      </span>
      <span>（{formatPercent(pct)}）</span>
      <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>
    </span>
  )
}

/** 股數：依偏好顯示「X 張 Y 股」或「X 股」，隱私模式遮蔽 */
export function Quantity({ shares, market, className, unit }: { shares: number; market: Market; className?: string; unit?: QuantityUnit }) {
  const pref = usePrefs((s) => s.quantityUnit)
  const privacy = usePrefs((s) => s.privacyMode)
  if (privacy) return <Masked className={className} />
  return <span className={cn("num whitespace-nowrap", className)}>{formatQuantity(shares, unit ?? pref, market)}</span>
}

/**
 * 大數字（NumberFlow）：總資產、今日損益、現價。
 * 負號與幣別前綴自己處理（Intl 的負號是連字號，且 TWD 會顯示成 $）。
 */
export function FlowMoney({
  value,
  currency = "TWD",
  signed,
  decimals,
  tone,
  publicValue,
  className,
}: {
  value: number
  currency?: Currency
  signed?: boolean
  decimals?: number
  tone?: boolean
  publicValue?: boolean
  className?: string
}) {
  const privacy = usePrefs((s) => s.privacyMode)
  if (privacy && !publicValue) return <Masked className={className} />
  const d: Direction = direction(value)
  const sign = d === "down" ? MINUS : signed && d === "up" ? "+" : ""
  const prefix = `${sign}${currency === "USD" ? "US$" : "NT$"}`
  const digits = decimals ?? (currency === "USD" ? 2 : 0)
  return (
    <span className={cn("num whitespace-nowrap", tone && toneClass(d), className)}>
      <NumberFlow
        value={Math.abs(value)}
        prefix={prefix}
        locales="zh-TW"
        format={{ minimumFractionDigits: digits, maximumFractionDigits: digits }}
      />
    </span>
  )
}

export function FlowPct({ value, className }: { value: number | null; className?: string }) {
  if (value === null) return <span className={cn("num text-muted-foreground", className)}>—</span>
  const d = direction(value)
  return (
    <span className={cn("num inline-flex items-baseline gap-0.5 whitespace-nowrap", toneClass(d), className)}>
      {d !== "flat" && <span aria-hidden className="leading-none">{directionGlyph(d)}</span>}
      <NumberFlow
        value={Math.abs(value)}
        prefix={d === "down" ? MINUS : d === "up" ? "+" : ""}
        locales="zh-TW"
        format={{ style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 }}
      />
      <span className="sr-only">{d === "up" ? "上漲" : d === "down" ? "下跌" : "持平"}</span>
    </span>
  )
}

/**
 * 交易來源標示：自動入帳（「自動」「自動・已修改」）與匯入是淡墨細框小字，可滑過看說明；
 * AI 建立的是紫色「由 AI 建立」（AI 做的事＝紫色；這是固定標籤不是模型寫的字，所以不用楷體）；自己記的不標示。
 */
export function SourceTag({ source, className }: { source: TransactionSource; className?: string }) {
  const tag = SOURCE_TAG[source]
  if (!tag) return null
  if (tag.ai) return <span className={cn("text-sm font-medium text-ai", className)}>{tag.label}</span>
  return (
    <span className={cn("demo-tag text-ink-2", className)} title={tag.title}>
      {tag.label}
    </span>
  )
}
