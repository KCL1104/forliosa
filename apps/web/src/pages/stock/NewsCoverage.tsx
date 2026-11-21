import { inText } from "@/lib/cjk"
import { ChevronDownIcon } from "lucide-react"
import { useState } from "react"
import { appNow } from "@/api"
import { useNews } from "@/api/queries"
import type { InstrumentDetail } from "@/api/types"
import { Disclaimer } from "@/components/disclaimer"
import { NewsRow } from "@/components/news-row"
import { ErrorState } from "@/components/states"
import { Skeleton } from "@/components/ui/skeleton"
import { useSourceNote } from "@/hooks/use-source-note"
import { mediaNews, NEWS_PAGE_SIZE } from "@/lib/news"
import { NotYet, QuietSection } from "./tabs/kit"
import { sourceNotes } from "./text"

/** 總覽先列這麼多則；「看更多」每次再加 NEWS_PAGE_SIZE 則 */
const NEWS_FIRST = 3

/**
 * 新聞報導（像 Google 財經／Goodinfo）：媒體原標題＋媒體名稱＋時間，標題連到原文（另開新視窗）。
 * 不放圖片、不轉載內文；先列 3 則，「看更多」每次再加 8 則；最下面一句免責（`news`）。
 * 收集方式（GDELT，使用條款要求連回 gdeltproject.org；SearXNG、AI 網路搜尋）登記到頁尾的資料來源。
 */
export function NewsCoverage({ inst }: { inst: InstrumentDetail }) {
  const news = useNews(inst.symbol)
  const [shown, setShown] = useState(NEWS_FIRST)
  const items = mediaNews(news.data)
  useSourceNote(sourceNotes([...new Set(items.flatMap((n) => n.sources ?? []))]))
  if (news.isLoading)
    return (
      <QuietSection title="新聞報導">
        <Skeleton className="h-40 w-full rounded-sm" />
      </QuietSection>
    )
  // 請求失敗不能說成「沒有報導」：顯示錯誤與重試（已有資料時照常顯示，背景重抓失敗不打斷）
  if (news.isError && !news.data) {
    return (
      <QuietSection title="新聞報導">
        <ErrorState title="新聞報導沒有載入" error={news.error} onRetry={() => void news.refetch()} />
      </QuietSection>
    )
  }
  const now = appNow()
  return (
    <QuietSection title="新聞報導">
      {items.length === 0 ? (
        // 只有標題（2026-11-21 評論：「新聞大約每小時更新一次」是機制）
        <NotYet title={`最近沒有找到${inText(inst.name)}的媒體報導`} />
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
          {/* 有報導時最下面一句：標題與內容由各媒體負責，Forliosa 只整理連結 */}
          <Disclaimer kind="news" className="mt-2" />
        </>
      )}
    </QuietSection>
  )
}
