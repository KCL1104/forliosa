import { useState } from "react"
import { kaiSize } from "@/ai/kai-size"
import { KaiText } from "@/ai/kai-text"
import { useDigests } from "@/api/sharing-queries"
import type { Digest, Group } from "@/api/types"
import { Pct } from "@/components/finance"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { useSourceNote } from "@/hooks/use-source-note"
import { formatDateShort, formatDateTime } from "@/lib/format"
import { codeOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { CommentsToggle, CommentThread, Reactions } from "../Discussion"

const FALLBACK_DISCLAIMER = "AI 分析僅供參考，不構成投資建議。"

/**
 * 群組 AI 週報（新到舊）：AI 寫的群組整體摘要（紫色楷體，和對話裡的回答同一套排版：`.ai-voice`＋`KaiText`）
 * ＋伺服器算的數字（依目前的分享設定過濾）＋免責。
 * 每一份都可以按表情、留言。
 */
export function DigestsTab({ group }: { group: Group }) {
  const digests = useDigests(group.id)
  const items = digests.data?.pages.flatMap((p) => p.items) ?? []
  if (digests.isError) return <ErrorState error={digests.error} onRetry={() => void digests.refetch()} />
  if (digests.isLoading) return <SkeletonLines rows={6} />
  if (items.length === 0) {
    return <EmptyState title="還沒有週報" description="每週六晚上整理這一週（週一到週五）的群組表現。" />
  }
  return (
    <div className="flex flex-col gap-12">
      {items.map((d) => (
        <DigestArticle key={d.id} d={d} groupId={group.id} />
      ))}
      {digests.hasNextPage && (
        <Button variant="outline" className="self-start" disabled={digests.isFetchingNextPage} onClick={() => void digests.fetchNextPage()}>
          {digests.isFetchingNextPage ? "載入中…" : "較早的週報"}
        </Button>
      )}
    </div>
  )
}

function DigestArticle({ d, groupId }: { d: Digest; groupId: string }) {
  const [open, setOpen] = useState(false)
  const titleId = `digest-${d.id}`
  const threadId = `thread-${d.id}`
  const f = d.facts
  // 資料來源放到頁尾（一頁一次）
  useSourceNote(d.sources)
  return (
    <article aria-labelledby={titleId} className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end gap-x-3 gap-y-1 border-b border-rule pb-2">
        <h2 id={titleId} className="num text-xl font-bold">
          {formatDateShort(d.week_start, false)}–{formatDateShort(d.week_end, false)} 週報
        </h2>
        <span className="num text-sm text-ink-2">{formatDateTime(d.created_at)}</span>
      </header>
      {d.status === "pending" ? (
        <p className="text-ink-2">週報整理中，好了會出現在這裡。</p>
      ) : d.status === "failed" ? (
        <p className="text-ink-2">這週的週報沒有產生成功。</p>
      ) : (
        <>
          {d.summary && (
            <p className={cn("ai-voice max-w-prose", kaiSize.page)}>
              <KaiText text={d.summary} />
            </p>
          )}
          {f && (
            <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
              {f.returns.length > 0 && (
                <div>
                  <h3 className="text-sm text-ink-2">本週報酬</h3>
                  <ul className="mt-1">
                    {f.returns.map((r) => (
                      <li key={r.user_id} className="flex h-10 items-center justify-between border-b border-rule">
                        <span>{r.display_name}</span>
                        {r.week_return_pct === null ? <span className="num text-ink-2">—</span> : <Pct value={r.week_return_pct} />}
                      </li>
                    ))}
                    {f.benchmarks.map((b) => (
                      <li key={b.symbol} className="flex h-10 items-center justify-between border-b border-rule text-ink-2">
                        <span>{b.name}</span>
                        {b.week_return_pct === null ? <span className="num">—</span> : <Pct value={b.week_return_pct} />}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="flex flex-col gap-4">
                {f.common_holdings.length > 0 && (
                  <div>
                    <h3 className="text-sm text-ink-2">共同持股</h3>
                    <p className="mt-1">
                      {f.common_holdings.map((c) => `${c.name} ${codeOf(c.symbol)}（${c.holder_count} 人）`).join("、")}
                    </p>
                  </div>
                )}
                {f.industries.length > 0 && (
                  <div>
                    <h3 className="text-sm text-ink-2">產業</h3>
                    <p className="mt-1">{f.industries.map((i) => `${i.industry}（${i.holder_count} 人）`).join("、")}</p>
                  </div>
                )}
                <div>
                  <h3 className="text-sm text-ink-2">交易</h3>
                  <p className="num mt-1">{f.trades_count} 筆</p>
                </div>
              </div>
            </div>
          )}
        </>
      )}
      <p className="text-xs text-ink-2">{d.disclaimer || FALLBACK_DISCLAIMER}</p>
      <div className="flex flex-wrap items-center gap-x-4">
        <Reactions groupId={groupId} target={`digest:${d.id}`} reactions={d.reactions} />
        <CommentsToggle count={d.comment_count} open={open} onToggle={() => setOpen(!open)} controls={threadId} />
      </div>
      {open && <CommentThread id={threadId} groupId={groupId} target={`digest:${d.id}`} className="border-l border-rule pl-3" />}
    </article>
  )
}
