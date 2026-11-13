import { inText } from "@/lib/cjk"
import { EyeIcon } from "lucide-react"
import { useViewingAs } from "@/api/view-as"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { PageFrame } from "./PageFrame"
import { scopeText, useSyncViewAsTarget, useViewAsControls } from "./view-as"

/** 手機橫幅的高度（兩行：名稱＋範圍）；AppShell 把頁面裡 sticky 分頁列排在它下面 */
export const MOBILE_BANNER_HEIGHT = "3.75rem"

/**
 * 查看別人的資產時，頂部一條墨色的橫幅：「正在查看 ○○ 的資產（唯讀）」＋範圍＋結束查看。
 * 桌面放在頂部列下面（一起 sticky），手機黏在畫面頂端（`sticky`，往下捲也一直看得到是誰的帳本）。
 * 範圍跟著授權者目前的設定（useSyncViewAsTarget），不是進入時的快照。
 */
export function ViewAsBanner({ className }: { className?: string }) {
  const target = useViewingAs()
  const { exit } = useViewAsControls()
  useSyncViewAsTarget()
  if (!target) return null
  return (
    <div
      role="region"
      aria-label="查看模式"
      className={cn("flex h-15 items-center gap-3 bg-act px-5 py-2 text-act-fg lg:h-10 lg:py-0 lg:pr-7 lg:pl-14", className)}
    >
      <EyeIcon aria-hidden className="size-[18px] shrink-0" />
      <p className="min-w-0 flex-1 truncate text-base">
        <b className="font-medium">正在查看 {target.owner.display_name} 的資產（唯讀）</b>
        <span className="ml-3 text-sm opacity-80 max-lg:block max-lg:ml-0 max-lg:truncate">範圍：{scopeText(target)}</span>
      </p>
      <button
        type="button"
        onClick={exit}
        className="press h-8 shrink-0 rounded-sm border border-act-fg/40 px-3 text-sm font-medium hover:bg-act-hover max-lg:hidden"
      >
        結束查看
      </button>
    </div>
  )
}

/** 查看模式不能用的頁面（群組、AI 紀錄、設定）：說明並給「結束查看」 */
export function ViewAsBlocked({ title }: { title: string }) {
  const target = useViewingAs()
  const { exit } = useViewAsControls()
  return (
    <PageFrame className="flex flex-col items-start gap-3">
      <h1 className="text-2xl font-bold tracking-[-0.01em] lg:text-3xl">{title}</h1>
      <p className="max-w-prose text-base text-ink">
        正在查看{inText(target?.owner.display_name ?? "別人")}的資產。{title}是你自己的，結束查看後才能用。
      </p>
      <Button variant="outline" onClick={exit}>
        結束查看
      </Button>
    </PageFrame>
  )
}
