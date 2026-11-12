import { cn } from "@/lib/utils"

/** 字標：Noto Sans TC 700，字距 −0.01em。沒有圖形標誌（聯絡簿世界不用印章或徽記）。 */
export function Wordmark({ className }: { className?: string }) {
  return <span className={cn("text-xl font-bold tracking-[-0.01em] text-ink", className)}>Forliosa</span>
}
