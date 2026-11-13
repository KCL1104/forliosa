import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import type { TopicListFilter } from "@/api/discussion-queries"
import { useViewer } from "@/api/queries"
import { useGroups } from "@/api/sharing-queries"
import type { TopicSort } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { PageHeader } from "@/components/section"
import { RangeChips } from "@/components/segmented"
import { textAction } from "@/components/text-action"
import { buttonVariants } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { DiscussionsSearch } from "@/router"
import { TopicRows } from "./TopicRows"

const SORTS: readonly { value: TopicSort; label: string }[] = [
  { value: "active", label: "最新回覆" },
  { value: "new", label: "最新主題" },
]

/**
 * 討論：公開的主題＋我的群組裡的主題。公開的清單不用登入就能讀（沒登入時只有公開的、沒有篩選）。
 * 標題＋一個主要動作「開新主題」→ 篩選（全部｜公開｜我的每一個群組，選取語法 (b)）與安靜的排序（最新回覆｜最新主題）
 * → 印好表頭的主題清單（格線列）→ 免責。查看別人的資產時擋下（和群組一樣）。
 */
export function DiscussionsPage() {
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="討論" />
  return <Discussions />
}

function Discussions() {
  const { signedIn } = useViewer()
  const search = useSearch({ from: "/discussions" }) as DiscussionsSearch
  const navigate = useNavigate()
  const groups = useGroups(signedIn)
  const sort: TopicSort = search.sort ?? "active"
  // 沒登入只看得到公開的；登入後預設是全部（公開＋我所有群組的）
  const filter: TopicListFilter = !signedIn
    ? { scope: "public", sort }
    : search.scope === "group" && search.group_id
      ? { scope: "group", groupId: search.group_id, sort }
      : { scope: search.scope === "public" ? "public" : "all", sort }
  const scopeKey = filter.scope === "group" ? `group:${filter.groupId}` : filter.scope
  const group = filter.scope === "group" ? groups.data?.find((g) => g.id === filter.groupId) : undefined
  const go = (next: DiscussionsSearch) => void navigate({ to: "/discussions", search: next, replace: true, resetScroll: false })
  const sortParam = sort === "new" ? ("new" as const) : undefined

  const scopes = [
    { value: "all", label: "全部" },
    { value: "public", label: "公開" },
    ...(groups.data ?? []).map((g) => ({ value: `group:${g.id}`, label: g.name })),
  ]

  return (
    <PageFrame>
      {/* 和設定、紀錄同一個欄寬（816px）：一行標題不會拉到 1,000px 寬 */}
      <div className="max-w-measure">
        <PageHeader
          title="討論"
          className="mb-4"
          actions={
            signedIn ? (
              <Link
                to="/discussions/new"
                // 發到哪裡跟著目前的篩選；排序一起帶著，「取消」回來時清單還是原來的樣子
                search={filter.scope === "group" ? { scope: "group", group_id: filter.groupId, sort: sortParam } : filter.scope === "public" ? { scope: "public", sort: sortParam } : { sort: sortParam }}
                className={buttonVariants()}
              >
                開新主題
              </Link>
            ) : (
              <Link to="/login" search={{ next: "/discussions/new" }} className={textAction}>
                登入後發言
              </Link>
            )
          }
        />
        <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-1">
          {signedIn && (
            <RangeChips
              label="範圍"
              className="min-w-0 max-sm:basis-full"
              value={scopeKey}
              options={scopes}
              onChange={(v) =>
                go(v.startsWith("group:") ? { scope: "group", group_id: v.slice(6), sort: sortParam } : { scope: v === "public" ? "public" : undefined, sort: sortParam })
              }
            />
          )}
          <SortToggle
            value={sort}
            // 有篩選時靠右；只有它自己（沒登入）時從內容的左緣開始
            className={signedIn ? "ml-auto" : "-ml-2"}
            onChange={(v) => go({ scope: search.scope, group_id: search.group_id, sort: v === "new" ? "new" : undefined })}
          />
        </div>
        <TopicRows
          filter={filter}
          origin={{ kind: "list", search: { scope: search.scope, group_id: search.group_id, sort: sortParam } }}
          signedIn={signedIn}
          empty={
            filter.scope === "group"
              ? { title: `${group ? `「${group.name}」` : "這個群組"}還沒有主題`, description: "開新主題時選這個群組，只有成員看得到。" }
              : { title: "還沒有主題", description: signedIn ? "開第一個主題，問問大家怎麼看。" : "登入後就能開第一個主題。" }
          }
        />
      </div>
    </PageFrame>
  )
}

/**
 * 排序：安靜的兩個文字選項（選取語法 (a)：墨色、700、字底下 2px 墨色線），不是第二組實心的方格——
 * 同一列已經有篩選的方格，排序只是換個順序看同一份清單。role=radiogroup，方向鍵切換。
 */
function SortToggle({ value, onChange, className }: { value: TopicSort; onChange: (v: TopicSort) => void; className?: string }) {
  return (
    <div role="radiogroup" aria-label="排序" className={cn("-mr-2 flex shrink-0 items-center", className)}>
      {SORTS.map((o, i) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => {
              const d = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0
              if (!d) return
              e.preventDefault()
              onChange(SORTS[(i + d + SORTS.length) % SORTS.length]!.value)
              const group = e.currentTarget.parentElement
              requestAnimationFrame(() => group?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus())
            }}
            onClick={() => onChange(o.value)}
            className="flex h-9 items-center rounded-sm px-2 text-sm text-ink-2 pointer-coarse:h-11"
          >
            <span data-active={active ? "" : undefined} className="sel-tab pb-0.5">
              {o.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
