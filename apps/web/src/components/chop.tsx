import { cva, type VariantProps } from "class-variance-authority"
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

/** 示範資料章：回應帶 is_demo 時顯示，滑過說明 */
export function DemoChop({ show = true, className, tone = "ink" }: { show?: boolean; className?: string; tone?: "ink" | "rail" | "muted" }) {
  if (!show) return null
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button type="button" className={cn("chop cursor-help", tone === "rail" ? "text-rail-muted" : tone === "muted" ? "text-muted-foreground" : "text-primary", className)}>
            示範資料
          </button>
        }
      />
      <TooltipContent className="max-w-64 text-pretty">
        這裡的數字是示範用的模擬資料，不是你的真實帳戶或即時行情。
      </TooltipContent>
    </Tooltip>
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
