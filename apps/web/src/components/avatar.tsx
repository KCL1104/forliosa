import { useState } from "react"
import { cn } from "@/lib/utils"

/**
 * 成員頭像：Discord 頭像（有的話），沒有就是名字的第一個字（墨色圓底）。
 * 圖片不帶 referrer；載入失敗時退回第一個字。
 */
export function UserAvatar({ name, url, size = "md", className }: { name: string; url?: string | null; size?: "sm" | "md" | "lg"; className?: string }) {
  const [broken, setBroken] = useState(false)
  const box = size === "sm" ? "size-7 text-sm" : size === "lg" ? "size-12 text-xl" : "size-9 text-base"
  if (url && !broken) {
    return <img src={url} alt="" aria-hidden referrerPolicy="no-referrer" loading="lazy" onError={() => setBroken(true)} className={cn("shrink-0 rounded-full object-cover", box, className)} />
  }
  return (
    <span aria-hidden className={cn("grid shrink-0 place-items-center rounded-full bg-sel font-medium text-ink", box, className)}>
      {Array.from(name.trim())[0] ?? "?"}
    </span>
  )
}
