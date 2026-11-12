import { Link } from "@tanstack/react-router"
import { CalendarSyncIcon } from "lucide-react"
import type { RecurringPlan } from "@/api/types"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { recurringLabel } from "@/lib/ledger-display"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"

/**
 * 持倉名稱旁一個安靜的定期定額標記（淡墨日曆圖示）。滑過看「定期定額：每月 6、19 日 NT$5,000」，
 * 按下到設定頁的那個計畫。可點範圍放大到 44px（看不見），不影響列高。
 */
export function RecurringMark({ plans, className }: { plans: RecurringPlan[]; className?: string }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const label = recurringLabel(plans, privacy)
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Link
            to="/settings"
            hash={`plan-${plans[0]!.id}`}
            aria-label={`${label}（到設定查看）`}
            onClick={(e) => e.stopPropagation()}
            className={cn(
              "relative inline-grid size-6 shrink-0 place-items-center rounded-sm text-ink-2 hover:text-ink",
              "before:absolute before:-inset-2.5 before:content-['']",
              className,
            )}
          />
        }
      >
        <CalendarSyncIcon aria-hidden className="size-4" />
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}
