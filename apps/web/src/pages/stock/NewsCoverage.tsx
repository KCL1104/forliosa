import { ChevronDownIcon } from "lucide-react"
import { useState } from "react"
import { appNow } from "@/api"
import { useNews } from "@/api/queries"
import type { InstrumentDetail, NewsItem } from "@/api/types"
import { Section } from "@/components/section"
import { ErrorState } from "@/components/states"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { GDELT_URL, mediaNews, NEWS_PAGE_SIZE, newsSourcesUsed, outletLabel, relativeTime } from "@/lib/news"

const OTHER_SOURCE_LABEL: Record<string, string> = {
  "AI 搜尋": "AI 網路搜尋",
  SearXNG: "SearXNG",
  Yahoo股市: "Yahoo股市 RSS（非商用）",
  FinMind: "FinMind（非商用）",
}

/**
 * 新聞報導（像 Google 財經／Goodinfo）：媒體原標題＋媒體名稱＋時間，標題連到原文（另開新視窗）。
 * 不放圖片、不轉載內文；桌機兩欄、手機一欄，先列 8 則，「顯示更多」每次再加 8 則。
 * 用到 GDELT 時，下方引用 The GDELT Project（使用條款要求連回 gdeltproject.org）。
 */
export function NewsCoverage({ inst }: { inst: InstrumentDetail }) {
  const news = useNews(inst.symbol)
  const [shown, setShown] = useState(NEWS_PAGE_SIZE)
  if (news.isLoading) return <Skeleton className="h-48 w-full rounded-sm" />
  // 請求失敗不能說成「沒有報導」：顯示錯誤與重試（已有資料時照常顯示，背景重抓失敗不打斷）
  if (news.isError && !news.data) {
    return (
      <Section title="新聞報導" titleId="ov-media">
        <ErrorState title="新聞報導沒有載入" error={news.error} onRetry={() => void news.refetch()} />
      </Section>
    )
  }
  const items = mediaNews(news.data)
  const now = appNow()
  const used = newsSourcesUsed(items)
  const others = used.others.map((s) => OTHER_SOURCE_LABEL[s] ?? s)
  return (
    <Section title="新聞報導" titleId="ov-media">
      {items.length === 0 ? (
        <p className="text-md text-ink-2">
          最近沒有找到{inst.name}的媒體報導。新聞大約每小時更新一次，剛開始看的股票稍後就會出現。
        </p>
      ) : (
        <>
          <ul className="-mt-3 grid gap-x-10 lg:grid-cols-2">
            {items.slice(0, shown).map((n) => (
              <NewsRow key={`${n.url}-${n.published_at}`} item={n} now={now} />
            ))}
          </ul>
          {items.length > shown && (
            <Button variant="ghost" size="sm" className="mt-2 -ml-2.5 self-start" onClick={() => setShown((s) => s + NEWS_PAGE_SIZE)}>
              顯示更多
              <ChevronDownIcon aria-hidden />
            </Button>
          )}
          <p className="mt-3 max-w-prose text-xs text-ink-2">
            只列媒體的原標題與連結，內容以各媒體原文為準。
            {used.gdelt && (
              <>
                新聞索引：
                <a href={GDELT_URL} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap underline underline-offset-3 hover:text-ink">
                  The GDELT Project
                  <span className="sr-only">（另開新視窗）</span>
                </a>
                {others.length > 0 ? "；" : "。"}
              </>
            )}
            {others.length > 0 && `${used.gdelt ? "另有 " : "來源："}${others.join("、")}。`}
          </p>
        </>
      )}
    </Section>
  )
}

function NewsRow({ item, now }: { item: NewsItem; now: Date }) {
  const outlet = outletLabel(item)
  const when = relativeTime(item.published_at, now, item.date_only)
  return (
    <li className="border-b border-rule py-3">
      <p className="flex min-w-0 items-baseline gap-1 text-sm text-ink-2">
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
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 block text-base leading-snug break-words underline-offset-3 hover:underline focus-visible:underline"
      >
        {item.title}
        <span className="sr-only">（{outlet}，另開新視窗）</span>
      </a>
    </li>
  )
}
