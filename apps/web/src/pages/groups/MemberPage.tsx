import { Link, useParams } from "@tanstack/react-router"
import { PlainLink } from "@/app/links"
import { ArrowLeftIcon } from "lucide-react"
import { useFeed, useGroup, useSharedPortfolio } from "@/api/sharing-queries"
import { ApiError, type SharedPortfolio } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { UserAvatar } from "@/components/avatar"
import { Money, Pct } from "@/components/finance"
import { DemoTag, Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { buttonVariants } from "@/components/ui/button"
import { ROLE_LABEL } from "./labels"
import { FeedRow } from "./tabs/FeedTab"
import { WeightList } from "./tabs/HoldingsTab"
import { usePageTitle } from "@/app/page-title"

/**
 * 一位成員分享給這個群組的內容（SharedPortfolio）：只顯示存在的區塊——
 * 報酬率、金額、持股，以及他的動態。什麼都沒有時是中性的「還沒有資料」，不寫「未分享」。
 */
export function MemberPage() {
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="群組" />
  return <Member />
}

function Member() {
  const { groupId, userId } = useParams({ from: "/groups/$groupId/members/$userId" })
  const group = useGroup(groupId)
  const shared = useSharedPortfolio(groupId, userId)
  const member = group.data?.members.find((m) => m.user_id === userId)
  usePageTitle(member?.display_name ?? "群組")
  const missing = (shared.error instanceof ApiError && shared.error.status === 404) || (group.error instanceof ApiError && group.error.status === 404)
  return (
    <PageFrame className="lg:pt-6">
      <nav aria-label="位置" className="flex min-h-11 items-center text-sm">
        <PlainLink
          to="/groups/$groupId"
          params={{ groupId }}
          search={{ tab: "members" }}
          className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11"
        >
          <ArrowLeftIcon aria-hidden className="size-4" />
          {group.data?.name ?? "群組"}
        </PlainLink>
      </nav>
      {missing ? (
        <div className="flex flex-col items-start gap-3 py-6">
          <h1 className="text-2xl font-bold">找不到這位成員</h1>
          <p className="text-ink-2">他可能已經離開這個群組。</p>
          <Link to="/groups/$groupId" params={{ groupId }} className={buttonVariants({ variant: "outline" })}>
            回到群組
          </Link>
        </div>
      ) : shared.isError ? (
        <ErrorState error={shared.error} onRetry={() => void shared.refetch()} />
      ) : !shared.data ? (
        <SkeletonLines rows={6} />
      ) : (
        <SharedPortfolioView p={shared.data} groupId={groupId} role={member ? ROLE_LABEL[member.role] : undefined} isMe={member?.is_me ?? false} />
      )}
    </PageFrame>
  )
}

/** 只顯示存在的區塊（測試也用它驗證「不顯示未分享」） */
export function SharedPortfolioView({ p, groupId, role, isMe }: { p: SharedPortfolio; groupId: string; role?: string; isMe: boolean }) {
  const feed = useFeed(groupId, p.user_id)
  const items = feed.data?.pages.flatMap((x) => x.items) ?? []
  const sections = !!p.returns || !!p.amounts || !!p.holdings
  // 「還沒有資料」只在真的什麼都沒有時：沒有任何區塊，動態也載入完而且是空的（「加入了群組」每個人都看得到，也算）
  const feedLoading = feed.isPending
  const nothing = !sections && !feedLoading && items.length === 0
  return (
    <>
      <header className="mt-1 flex items-center gap-4">
        <UserAvatar name={p.display_name} url={p.avatar_url} size="lg" />
        <div>
          <h1 className="flex items-center gap-2.5 text-2xl font-bold tracking-[-0.01em] lg:text-3xl">
            {p.display_name}
            {p.is_demo && <DemoTag />}
          </h1>
          <p className="text-base text-ink-2">
            {role}
            {isMe && "・這是你"}
          </p>
        </div>
      </header>
      {isMe && (
        <p className="mt-2">
          <Link to="/groups/$groupId" params={{ groupId }} search={{ tab: "share" }} className={textAction}>
            調整我在這個群組的分享
          </Link>
        </p>
      )}

      <div className="mt-8 flex flex-col gap-10">
        {!sections && feedLoading && <SkeletonLines rows={3} />}
        {nothing && <EmptyState title="還沒有資料" />}
        {(p.returns || p.amounts) && (
          // 報酬率與金額：兩欄格線鍵值列（和帳本同一套：標籤在左、數字靠右），沒有外框與格子；手機上下排
          <div className="grid max-w-[720px] gap-x-8 gap-y-10 md:grid-cols-2">
            {p.returns && (
              <Section title="報酬率" titleId="mp-returns">
                <KeyRows
                  rows={(
                    [
                      ["今日", p.returns.day],
                      ["本月", p.returns.month],
                      ["今年", p.returns.year],
                      ["總報酬（含股利）", p.returns.total],
                    ] as const
                  ).map(([label, v]) => [label, v === null ? <span className="num font-normal text-ink-2">—</span> : <Pct value={v} />])}
                />
              </Section>
            )}
            {p.amounts && (
              <Section title="金額" titleId="mp-amounts">
                <KeyRows
                  rows={[
                    ["市值", <Money value={p.amounts.market_value} decimals={0} />],
                    ["今日損益", <Money value={p.amounts.day_change} decimals={0} signed tone />],
                    ["總損益", <Money value={p.amounts.total_pnl} decimals={0} signed tone />],
                  ]}
                />
              </Section>
            )}
          </div>
        )}
        {p.holdings && (
          // 權重清單最寬 720px：標題的格線跟著清單一樣寬
          <Section title="持股" titleId="mp-holdings" aside="權重，不含股數與金額" className="max-w-[720px]">
            {p.holdings.length === 0 ? <EmptyState flush title="目前沒有持股" /> : <WeightList holdings={p.holdings} className="-mt-3" />}
          </Section>
        )}
        {items.length > 0 && (
          <Section title="動態" titleId="mp-feed">
            <ol className="-mt-3">
              {items.map((item) => (
                <FeedRow key={item.id} item={item} groupId={groupId} showName={false} />
              ))}
            </ol>
          </Section>
        )}
      </div>
    </>
  )
}

/** 鍵值列：格線分隔，標籤淡墨在左、數字靠右（等寬數字，上下對齊）；每列 44px 以上 */
function KeyRows({ rows }: { rows: (readonly [label: string, value: React.ReactNode])[] }) {
  return (
    <dl className="-mt-3">
      {rows.map(([label, value]) => (
        <div key={label} className="flex min-h-11 items-baseline justify-between gap-4 border-b border-rule py-2.5">
          <dt className="text-md text-ink-2">{label}</dt>
          <dd className="text-lg font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  )
}
