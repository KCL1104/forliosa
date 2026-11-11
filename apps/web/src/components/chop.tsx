import { cva, type VariantProps } from "class-variance-authority"
import type { Holding } from "@/api/types"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

/**
 * 「章」：資料狀態標記。Forliosa 的招牌元件——像銀行臨櫃蓋在存摺上的章，
 * 標示一筆資料的狀態（示範資料、預估、延遲、即將推出、已入帳）。
 */
const chopVariants = cva("chop", {
  variants: {
    tone: {
      ink: "text-primary",
      muted: "text-muted-foreground",
      amber: "text-amber",
      rail: "text-rail-muted",
    },
    press: { true: "chop-press", false: "" },
  },
  defaultVariants: { tone: "ink", press: false },
})

export function Chop({ className, tone, press, children, ...props }: React.ComponentProps<"span"> & VariantProps<typeof chopVariants>) {
  return (
    <span className={cn(chopVariants({ tone, press }), className)} {...props}>
      {children}
    </span>
  )
}

/** 示範資料章：回應帶 is_demo 時顯示，滑過說明（部分資料是模擬時可改標籤與說明，例如「含示範資料」） */
export function DemoChop({
  show = true,
  className,
  tone = "ink",
  label = "示範資料",
  description = "這裡的數字是示範用的模擬資料，不是你的真實帳戶或即時行情。",
}: {
  show?: boolean
  className?: string
  tone?: "ink" | "rail" | "muted"
  label?: string
  description?: string
}) {
  if (!show) return null
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button type="button" className={cn("chop cursor-help", tone === "rail" ? "text-rail-muted" : tone === "muted" ? "text-muted-foreground" : "text-primary", className)}>
            {label}
          </button>
        }
      />
      <TooltipContent className="max-w-64 text-pretty">{description}</TooltipContent>
    </Tooltip>
  )
}

/**
 * 投資組合層級的示範資料章：回應 is_demo 時，若只有部分持股的報價是模擬的（例如美股），
 * 標「含示範資料」並列出是哪幾檔，避免讓真實的台股數字看起來也像假的。
 */
export function PortfolioDemoChop({ isDemo, holdings, className }: { isDemo: boolean; holdings?: Holding[]; className?: string }) {
  if (!isDemo) return null
  const demo = (holdings ?? []).filter((h) => h.is_demo)
  if (!holdings || demo.length === 0 || demo.length === holdings.length) return <DemoChop className={className} />
  const names = demo.map((h) => h.code).join("、")
  const allUs = demo.every((h) => h.market === "US")
  return (
    <DemoChop
      className={className}
      label="含示範資料"
      description={`${names} 的報價是模擬資料${allUs ? "（美股還沒有授權的資料源）" : "（資料源暫時無法取得）"}；其餘持股為真實收盤價。`}
    />
  )
}

/** 里程碑章：「M4 推出」等 */
export function SoonChop({ milestone, className }: { milestone: string; className?: string }) {
  return (
    <Chop tone="muted" className={className}>
      {milestone} 推出
    </Chop>
  )
}
