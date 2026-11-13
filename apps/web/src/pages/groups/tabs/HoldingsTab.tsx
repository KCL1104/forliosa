import { Link } from "@tanstack/react-router"
import { useGroupHoldings } from "@/api/sharing-queries"
import type { Group, SharedHolding } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { DemoTag, Section } from "@/components/section"
import { EmptyState, ErrorState, SkeletonLines } from "@/components/states"
import { formatPercent } from "@/lib/format"
import { codeOf } from "@/lib/tick"
import { cn } from "@/lib/utils"

/** 整列可點：連結的 ::after 蓋滿所在的列（列要 `relative`），焦點框也畫在整列上 */
const ROW_LINK =
  "after:absolute after:inset-0 after:content-[''] focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-ink"

/** 持股：共同持股（兩人以上）、產業、每位分享了持股的成員的權重（沒有股數與金額） */
export function HoldingsTab({ group }: { group: Group }) {
  const data = useGroupHoldings(group.id)
  if (data.isError) return <ErrorState error={data.error} onRetry={() => void data.refetch()} />
  if (!data.data) return <SkeletonLines rows={6} />
  const h = data.data
  if (h.members.length === 0) return <EmptyState title="還沒有資料" />
  return (
    <div className="flex flex-col gap-10">
      <div className="grid gap-10 md:grid-cols-2">
        <Section title="共同持股" titleId="gh-common" aside={h.is_demo ? <DemoTag /> : undefined}>
          {h.common.length === 0 ? (
            <EmptyState flush title="還沒有共同持股" description="要兩人以上都持有才算。" />
          ) : (
            <ul className="-mt-3">
              {h.common.map((c) => (
                // 整列可點（名稱連結的 ::after 蓋滿整列）
                <li key={c.symbol} className="ruled-row relative flex h-12 items-center justify-between gap-3">
                  <Link to="/stock/$symbol" params={{ symbol: c.symbol }} className={cn("min-w-0 truncate", ROW_LINK)}>
                    <span className="font-medium">{c.name}</span>
                    <span className="num ml-1.5 text-sm text-ink-2">{codeOf(c.symbol)}</span>
                  </Link>
                  <span className="num shrink-0 text-base">{c.holder_count} 人</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="產業" titleId="gh-industries">
          {h.industries.length === 0 ? (
            <EmptyState flush title="還沒有資料" />
          ) : (
            <ul className="-mt-3">
              {h.industries.map((i) => (
                <li key={i.industry} className="flex h-12 items-center justify-between gap-3 border-b border-rule">
                  <span className="truncate">{i.industry}</span>
                  <span className="num shrink-0 text-base">{i.holder_count} 人</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <Section title="成員持股" titleId="gh-members" aside="權重，不含股數與金額">
        <div className="grid gap-x-10 gap-y-8 md:grid-cols-2">
          {h.members.map((m) => (
            <section key={m.user_id} aria-label={`${m.display_name}的持股`}>
              <Link to="/groups/$groupId/members/$userId" params={{ groupId: group.id, userId: m.user_id }} className="flex items-center gap-2 hover:underline pointer-coarse:min-h-11">
                <UserAvatar name={m.display_name} url={m.avatar_url} size="sm" />
                <span className="text-lg font-medium">{m.display_name}</span>
              </Link>
              <WeightList holdings={m.holdings} className="mt-2 pointer-coarse:mt-0" />
            </section>
          ))}
        </div>
      </Section>
    </div>
  )
}

/** 權重清單：名稱、代號、細長的比例條、百分比。最寬 720px，寬螢幕上長條和百分比不會離名稱太遠；整列連到個股頁 */
export function WeightList({ holdings, className }: { holdings: SharedHolding[]; className?: string }) {
  const max = Math.max(...holdings.map((x) => x.weight), 0.0001)
  return (
    <ul className={cn("max-w-[720px]", className)}>
      {holdings.map((x) => (
        <li key={x.symbol} className="ruled-row relative grid h-11 grid-cols-[minmax(0,1fr)_88px_56px] items-center gap-3">
          <Link to="/stock/$symbol" params={{ symbol: x.symbol }} className={cn("min-w-0 truncate", ROW_LINK)}>
            {x.name}
            <span className="num ml-1.5 text-sm text-ink-2">{codeOf(x.symbol)}</span>
          </Link>
          <span aria-hidden className="h-1.5 rounded-full bg-hov">
            <span className="block h-full rounded-full bg-ink-2" style={{ width: `${Math.max(4, (x.weight / max) * 100)}%` }} />
          </span>
          <span className="num text-right">{formatPercent(x.weight, { decimals: 0, signed: false })}</span>
        </li>
      ))}
    </ul>
  )
}
