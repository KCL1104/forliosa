import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router"
import { PlainLink } from "@/app/links"
import { ArrowLeftIcon } from "lucide-react"
import { lazy, Suspense } from "react"
import { useGroup } from "@/api/sharing-queries"
import { ApiError, type Group } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { ScrollRow } from "@/components/scroll-row"
import { SourcesFooter, SourcesProvider } from "@/components/sources"
import { ErrorState } from "@/components/states"
import { buttonVariants } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { GroupSearch, GroupTab } from "@/router"
import { ROLE_LABEL } from "./labels"
import { RankingTab } from "./tabs/RankingTab"

const FeedTab = lazy(() => import("./tabs/FeedTab").then((m) => ({ default: m.FeedTab })))
const HoldingsTab = lazy(() => import("./tabs/HoldingsTab").then((m) => ({ default: m.HoldingsTab })))
const DigestsTab = lazy(() => import("./tabs/DigestsTab").then((m) => ({ default: m.DigestsTab })))
const ShareTab = lazy(() => import("./tabs/ShareTab").then((m) => ({ default: m.ShareTab })))
const MembersTab = lazy(() => import("./tabs/MembersTab").then((m) => ({ default: m.MembersTab })))
const ChannelsTab = lazy(() => import("./tabs/ChannelsTab").then((m) => ({ default: m.ChannelsTab })))

const TABS: { value: GroupTab; label: string }[] = [
  { value: "ranking", label: "排行" },
  { value: "feed", label: "動態" },
  { value: "holdings", label: "持股" },
  { value: "digests", label: "週報" },
  { value: "share", label: "我的分享" },
  { value: "members", label: "成員" },
  { value: "channels", label: "頻道" },
]

/** 一個群組：名稱與成員數 → sticky 分頁（排行・動態・持股・週報・我的分享・成員・頻道）→ 頁尾資料來源（分頁登記的來源） */
export function GroupPage() {
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="群組" />
  return (
    <SourcesProvider>
      <GroupView />
    </SourcesProvider>
  )
}

function GroupView() {
  const { groupId } = useParams({ from: "/groups/$groupId" })
  const search = useSearch({ from: "/groups/$groupId" }) as GroupSearch
  const tab: GroupTab = search.tab ?? "ranking"
  const group = useGroup(groupId)
  const missing = group.error instanceof ApiError && group.error.status === 404

  return (
    <PageFrame className="lg:pt-6">
      <nav aria-label="位置" className="flex min-h-11 items-center text-sm">
        <PlainLink to="/groups" className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11">
          <ArrowLeftIcon aria-hidden className="size-4" />
          群組
        </PlainLink>
      </nav>
      {missing ? (
        <GroupMissing />
      ) : group.isError ? (
        <ErrorState error={group.error} onRetry={() => void group.refetch()} />
      ) : !group.data ? (
        <div className="flex flex-col gap-3 pt-2" aria-busy="true" aria-label="群組載入中">
          <Skeleton className="h-9 w-56" />
          <Skeleton className="h-4 w-72" />
        </div>
      ) : (
        <Loaded group={group.data} tab={tab} member={search.member} />
      )}
      <SourcesFooter />
    </PageFrame>
  )
}

function GroupMissing() {
  return (
    <div className="flex flex-col items-start gap-3 py-6">
      <h1 className="text-2xl font-bold">找不到這個群組</h1>
      <p className="max-w-prose text-ink-2">群組可能已經刪除，或你已經不在這個群組裡。</p>
      <Link to="/groups" className={buttonVariants({ variant: "outline" })}>
        回到群組
      </Link>
    </div>
  )
}

function Loaded({ group, tab, member }: { group: Group; tab: GroupTab; member?: string }) {
  const navigate = useNavigate()
  const go = (t: GroupTab, focus = false) => {
    void navigate({ to: "/groups/$groupId", params: { groupId: group.id }, search: { tab: t === "ranking" ? undefined : t }, replace: true, resetScroll: false })
    if (focus) requestAnimationFrame(() => document.getElementById(`group-tab-${t}`)?.focus())
  }
  return (
    <>
      <header className="mt-1">
        <h1 className="text-2xl font-bold tracking-[-0.01em] lg:text-3xl">{group.name}</h1>
        <p className="num mt-1.5 text-base text-ink-2">
          {group.members.length} 位成員・你是{ROLE_LABEL[group.my_role]}
          {!group.ranking_enabled && "・不排名次"}
        </p>
      </header>

      <div className="sticky top-(--sticky-top) z-20 -mx-5 mt-6 border-b border-rule bg-paper px-5 md:-mx-8 md:px-8 xl:-mx-14 xl:px-14">
        {/*
          手機（< 640px）：七個分頁平分整列（每個至少左右 4px），336px 以上的手機一次看得到全部——
          「成員」「頻道」不會躲在淡出的那一邊。更窄才橫向捲動（ScrollRow：被遮住的那一邊淡出，選取中的分頁捲進畫面）。
        */}
        <ScrollRow role="tablist" aria-label="群組內容" className="flex sm:gap-1">
          {TABS.map((t, i) => {
            const active = t.value === tab
            return (
              <button
                key={t.value}
                type="button"
                role="tab"
                id={`group-tab-${t.value}`}
                aria-selected={active}
                aria-controls="group-tabpanel"
                tabIndex={active ? 0 : -1}
                onKeyDown={(e) => {
                  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
                  if (!d) return
                  e.preventDefault()
                  go(TABS[(i + d + TABS.length) % TABS.length]!.value, true)
                }}
                onClick={() => go(t.value)}
                className="sel-tab -mb-px flex h-12 shrink-0 items-center justify-center px-1 text-base text-ink-2 max-sm:grow sm:px-3"
              >
                {t.label}
              </button>
            )
          })}
        </ScrollRow>
      </div>

      <div id="group-tabpanel" role="tabpanel" aria-labelledby={`group-tab-${tab}`} className="pt-6">
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-sm" />}>
          {tab === "ranking" && <RankingTab group={group} />}
          {tab === "feed" && <FeedTab group={group} member={member} />}
          {tab === "holdings" && <HoldingsTab group={group} />}
          {tab === "digests" && <DigestsTab group={group} />}
          {tab === "share" && <ShareTab group={group} />}
          {tab === "members" && <MembersTab group={group} />}
          {tab === "channels" && <ChannelsTab group={group} />}
        </Suspense>
      </div>
    </>
  )
}
