import { ChevronDownIcon } from "lucide-react"
import { useState } from "react"
import { appNow } from "@/api"
import { useNews } from "@/api/queries"
import type { InstrumentDetail, NewsItem } from "@/api/types"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { mediaNews, NEWS_PAGE_SIZE, outletLabel, relativeTime } from "@/lib/news"
import { NotYet, QuietSection } from "./tabs/kit"
import { sourceNotes } from "./text"

/** 總覽先列這麼多則；「看更多」每次再加 NEWS_PAGE_SIZE 則 */
const NEWS_FIRST = 3

/**
 * 新聞報導（像 Google 財經／Goodinfo）：媒體原標題＋媒體名稱＋時間，標題連到原文（另開新視窗）。
 * 不放圖片、不轉載內文；先列 3 則，「看更多」每次再加 8 則。
 * 收集方式（GDELT，使用條款要求連回 gdeltproject.org；SearXNG、AI 網路搜尋）登記到頁尾的資料來源。
 */
export function NewsCoverage({ inst }: { inst: InstrumentDetail }) {
  const news = useNews(inst.symbol)
  const [shown, setShown] = useState(NEWS_FIRST)
  const items = mediaNews(news.data)
  useSourceNote(sourceNotes([...new Set(items.flatMap((n) => n.sources ?? []))]))
  if (news.isLoading) return <Skeleton className="h-40 w-full rounded-sm" />
  // 請求失敗不能說成「沒有報導」：顯示錯誤與重試（已有資料時照常顯示，背景重抓失敗不打斷）
  if (news.isError && !news.data) {
    return (
      <QuietSection title="新聞報導" titleId="ov-media">
        <ErrorState className="mt-2" title="新聞報導沒有載入" error={news.error} onRetry={() => void news.refetch()} />
      </QuietSection>
    )
  }
  const now = appNow()
  return (
    <QuietSection title="新聞報導" titleId="ov-media">
      {items.length === 0 ? (
        <NotYet className="-mt-1 border-t-0" title={`最近沒有找到${inst.name}的媒體報導`}>
          新聞大約每小時更新一次。
        </NotYet>
      ) : (
        <>
          <ul>
            {items.slice(0, shown).map((n) => (
              <NewsRow key={`${n.url}-${n.published_at}`} item={n} now={now} />
            ))}
          </ul>
          {/* 文字按鈕：墨色、常駐底線（不是只有淡墨字），⌄ 表示在這裡往下展開 */}
          {items.length > shown && (
            <button
              type="button"
              onClick={() => setShown((s) => s + NEWS_PAGE_SIZE)}
              className="mt-1 inline-flex min-h-10 items-center gap-0.5 self-start rounded-xs text-sm text-ink underline decoration-ctl underline-offset-3 hover:decoration-ink pointer-coarse:min-h-11"
            >
              看更多
              <ChevronDownIcon aria-hidden className="size-3.5" />
            </button>
          )}
        </>
      )}
    </QuietSection>
  )
}

/** 一則一列：桌面標題在左、媒體・時間靠右；手機媒體・時間在上一行 */
function NewsRow({ item, now }: { item: NewsItem; now: Date }) {
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
