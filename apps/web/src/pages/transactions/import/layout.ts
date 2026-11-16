import { cn } from "@/lib/utils"

/** 對話框裡捲動的內文、貼底的動作列（匯入的每一步共用；手機抽屜的動作列貼在畫面底部、留 safe area） */
export const bodyClass = (sheet: boolean) => cn("min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 sm:px-6", sheet ? "pb-4" : "pb-5")
export const footerClass = (sheet: boolean) =>
  cn("flex shrink-0 flex-wrap items-center gap-x-4 gap-y-3 border-t border-rule bg-popover px-4 py-3 sm:px-6", sheet && "safe-bottom")
