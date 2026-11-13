import { Link, useNavigate } from "@tanstack/react-router"
import { XIcon } from "lucide-react"
import { useState } from "react"
import { useFeed } from "@/api/sharing-queries"
import type { FeedItem, Group } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { Masked } from "@/components/finance"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { Button } from "@/components/ui/button"
import { formatDateShort, formatPrice } from "@/lib/format"
import { codeOf, marketOf } from "@/lib/tick"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { CommentsToggle, CommentThread, Reactions } from "../Discussion"

/** 句子裡的連結：觸控時上下各多 12px 的可按範圍（合計 44px 以上）（行內元素的上下內距不改變行高） */
const INLINE_TOUCH = "pointer-coarse:py-3"

/**
 * 動態：成員的買賣（同一人同一天同一檔同方向合併成一則）與「加入了群組」。
 * 只顯示伺服器給的；成交價只有對方開了才有，隱私模式遮住。沒有理由欄位。
 */
export function FeedTab({ group, member }: { group: Group; member?: string }) {
  const feed = useFeed(group.id, member)
  const navigate = useNavigate()
  const items = feed.data?.pages.flatMap((p) => p.items) ?? []
  const who = member ? group.members.find((m) => m.user_id === member) : undefined
  return (
    <section aria-labelledby="feed-title" className="flex flex-col gap-3">
      <h2 id="feed-title" className="sr-only">
        動態
      </h2>
      {member && (
        <button
          type="button"
          onClick={() => void navigate({ to: "/groups/$groupId", params: { groupId: group.id }, search: { tab: "feed" }, replace: true })}
          // 篩選中＝選取語法 (b)；再按一次（或按 ×）取消
          aria-pressed="true"
          title="取消篩選"
          className="press sel-chip inline-flex h-8 items-center gap-1.5 self-start rounded-sm px-2.5 text-sm text-ink-2 pointer-coarse:h-11 pointer-coarse:px-3"
        >
          只看{who?.display_name ?? "這位成員"}
          <XIcon aria-hidden className="size-3.5" />
        </button>
      )}
      {feed.isError ? (
        <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
      ) : feed.isLoading ? (
        <SkeletonLines rows={6} />
      ) : items.length === 0 ? (
        <EmptyState title="還沒有資料" />
      ) : (
        <ol aria-label="動態" className="border-t border-rule">
          {items.map((item) => (
            <FeedRow key={item.id} item={item} groupId={group.id} />
          ))}
        </ol>
      )}
      {feed.hasNextPage && (
        <Button variant="outline" className="self-start" disabled={feed.isFetchingNextPage} onClick={() => void feed.fetchNextPage()}>
          {feed.isFetchingNextPage ? "載入中…" : "載入更多"}
        </Button>
      )}
    </section>
  )
}

export function FeedRow({ item, groupId, showName = true }: { item: FeedItem; groupId: string; showName?: boolean }) {
  const [open, setOpen] = useState(false)
  const day = item.trade_date ?? item.created_at.slice(0, 10)
  const threadId = `thread-${item.id}`
  const name = (
    <Link to="/groups/$groupId/members/$userId" params={{ groupId, userId: item.user_id }} className={cn("font-medium hover:underline", INLINE_TOUCH)}>
      {item.display_name}
    </Link>
  )
  return (
    <li className="flex gap-3 border-b border-rule py-3">
      <UserAvatar name={item.display_name} url={item.avatar_url} size="sm" className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          {item.type === "member_joined" ? (
            <p className="min-w-0 text-base">
              {showName ? name : null}
              {showName ? " 加入了群組" : "加入了群組"}
            </p>
          ) : (
            <TradeLine item={item} name={showName ? name : null} />
          )}
          <time dateTime={day} className="num shrink-0 text-sm text-ink-2">
            {formatDateShort(day)}
          </time>
        </div>
        {item.type === "trade" && (
          <>
            <TradeDetail item={item} />
            {/* 觸控時每個按鈕 44px 高（看得到的框比較小），所以上面不再另外留空 */}
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 pointer-coarse:mt-0.5">
              <Reactions groupId={groupId} target={`trade:${item.id}`} reactions={item.reactions} />
              <CommentsToggle count={item.comment_count} open={open} onToggle={() => setOpen(!open)} controls={threadId} />
            </div>
            {open && <CommentThread id={threadId} groupId={groupId} target={`trade:${item.id}`} className="mt-2 border-l border-rule pl-3" />}
          </>
        )}
      </div>
    </li>
  )
}

function TradeLine({ item, name }: { item: FeedItem; name: React.ReactNode }) {
  const symbol = item.symbol ?? ""
  return (
    <p className="min-w-0 text-base">
      {name}
      {name && " "}
      <span className="font-medium">{item.side === "sell" ? "賣出" : "買進"}</span>{" "}
      <Link to="/stock/$symbol" params={{ symbol }} className={cn("underline decoration-ctl decoration-1 underline-offset-4 hover:decoration-ink", INLINE_TOUCH)}>
        {/* 名稱和代號之間是空白字元（不是 margin），底線才連成一條 */}
        {item.name} <span className="num text-ink-2">{codeOf(symbol)}</span>
      </Link>
    </p>
  )
}

/** 合併筆數與成交價（只有對方開了附上成交價才有；隱私模式遮住） */
function TradeDetail({ item }: { item: FeedItem }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const merged = (item.count ?? 1) > 1
  const hasPrice = typeof item.price === "number"
  if (!merged && !hasPrice) return null
  const market = item.currency === "USD" ? "US" : marketOf(item.symbol ?? "")
  return (
    <p className="num mt-0.5 text-sm text-ink-2">
      {merged && <span>{item.count} 筆</span>}
      {merged && hasPrice && "・"}
      {hasPrice && (
        <span>
          {merged ? "均價" : "成交價"}{" "}
          {privacy ? <Masked /> : <span className="text-ink">{item.currency === "USD" ? "US$" : ""}{formatPrice(item.price!, market)}</span>}
        </span>
      )}
    </p>
  )
}
