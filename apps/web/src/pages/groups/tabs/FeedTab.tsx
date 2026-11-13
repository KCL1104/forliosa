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

/**
 * 句子裡的連結：觸控時上下各多 12px 的可按範圍（合計 44px 以上；行內元素的上下內距不改變行高）。
 * 下面那一行（筆數・成交價）在觸控時不接收點按（它沒有可以按的東西），所以蓋不到連結的下緣；
 * 下面直接是表情列時，那一列往下讓 12px（見 FeedRow）。
 */
const INLINE_TOUCH = "pointer-coarse:py-3"
/** 兩個字的名字只有 30px 寬：左右各多 8px 的可按範圍（負邊距抵掉，版面不動；`relative` 讓它不被後面的「買進」蓋住） */
const NAME_TOUCH = "pointer-coarse:relative pointer-coarse:-mx-2 pointer-coarse:px-2"

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
    <Link to="/groups/$groupId/members/$userId" params={{ groupId, userId: item.user_id }} className={cn("font-medium hover:underline", INLINE_TOUCH, NAME_TOUCH)}>
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
            {/*
              觸控時每個按鈕 44px 高（看得到的框比較小），所以上面不再另外留空；
              上面直接是句子時（沒有筆數・成交價那一行）留 12px：句子裡的連結往下也有 44px 的可按範圍，不和表情疊在一起
            */}
            <div className={cn("mt-1.5 flex flex-wrap items-center gap-x-4", hasTradeDetail(item) ? "pointer-coarse:mt-0.5" : "pointer-coarse:mt-3")}>
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
    /*
     * 「誰 買進 哪一檔」：三個不拆開的單位排成一行，放不下時整個單位換到下一行（股票名稱不從中間斷開）。
     * 觸控時換了行的兩行之間多 24px：名字和股票的連結各有上下 12px 的可按範圍，疊在相鄰的兩行會互相蓋住；
     * 只有一行時（絕大多數）沒有這段間距。連結包在 span 裡維持行內元素（上下內距不改變行高）。
     */
    <p className="flex min-w-0 flex-wrap items-baseline gap-x-1 text-base pointer-coarse:gap-y-6">
      {name && <span>{name}</span>}
      <span className="font-medium">{item.side === "sell" ? "賣出" : "買進"}</span>
      {/* 名稱比一行還長時才在裡面斷行：先在名稱和代號之間的空白（keep-all），再不行才在字中間（overflow-wrap） */}
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <Link to="/stock/$symbol" params={{ symbol }} className={cn("[word-break:keep-all] underline decoration-ctl decoration-1 underline-offset-4 hover:decoration-ink", INLINE_TOUCH)}>
          {/* 名稱和代號之間是空白字元（不是 margin），底線才連成一條 */}
          {item.name} <span className="num text-ink-2">{codeOf(symbol)}</span>
        </Link>
      </span>
    </p>
  )
}

/** 這一則有沒有「筆數・成交價」那一行 */
const hasTradeDetail = (item: FeedItem) => (item.count ?? 1) > 1 || typeof item.price === "number"

/** 合併筆數與成交價（只有對方開了附上成交價才有；隱私模式遮住） */
function TradeDetail({ item }: { item: FeedItem }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const merged = (item.count ?? 1) > 1
  const hasPrice = typeof item.price === "number"
  if (!hasTradeDetail(item)) return null
  const market = item.currency === "USD" ? "US" : marketOf(item.symbol ?? "")
  return (
    // 觸控時這一行不接收點按：上面句子裡的連結（名字、股票）往下 12px 的可按範圍落在這裡
    <p className="num mt-0.5 text-sm text-ink-2 pointer-coarse:pointer-events-none">
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
