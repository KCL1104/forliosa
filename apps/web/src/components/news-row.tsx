import type { NewsItem } from "@/api/types"
import { outletLabel, relativeTime } from "@/lib/news"

/**
 * 一則新聞報導一列（個股頁「新聞報導」、市場頁「美股」的新聞共用）：媒體原標題連到原文（另開新視窗），
 * 旁邊是媒體・相對時間。桌面標題在左、媒體・時間靠右；手機媒體・時間在上一行。不放圖片、不轉載內文。
 * 放在 `<ul>` 裡用（本身是 `<li>`）。
 */
export function NewsRow({ item, now }: { item: NewsItem; now: Date }) {
  const outlet = outletLabel(item)
  const when = relativeTime(item.published_at, now, item.date_only)
  return (
    <li className="relative flex flex-col-reverse gap-0.5 border-b border-rule py-2.5 hover:bg-hov sm:grid sm:grid-cols-[minmax(0,1fr)_auto] sm:items-baseline sm:gap-6">
      {/* 連結撐滿整列（手機上整列都按得到）；標題本身滑過才畫底線（一整列標題都畫線太吵） */}
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="block text-base leading-snug break-words underline-offset-3 after:absolute after:inset-0 hover:underline focus-visible:underline"
      >
        {item.title}
        <span className="sr-only">（{outlet}，另開新視窗）</span>
      </a>
      <p className="flex min-w-0 items-baseline gap-1 text-sm text-ink-2 sm:justify-end">
        <span className="truncate">{outlet}</span>
        {when && (
          <>
            <span aria-hidden>・</span>
            <time dateTime={item.published_at} className="num shrink-0">
              {when}
            </time>
          </>
        )}
      </p>
    </li>
  )
}
