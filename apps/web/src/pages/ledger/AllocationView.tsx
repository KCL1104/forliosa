import { ChevronDownIcon } from "lucide-react"
import { Fragment, useMemo, useRef, useState } from "react"
import { useAccounts, useAllocation } from "@/api/queries"
import type { AllocationGrouping, AllocationLimits, PortfolioAllocation } from "@/api/types"
import { useReadOnly, useWho } from "@/api/view-as"
import { useAskAi } from "@/ai/use-ask"
import { useUi } from "@/app/ui-store"
import { RangeChips } from "@/components/segmented"
import { Masked } from "@/components/finance"
import { DemoTag } from "@/components/section"
import { EmptyState, ErrorState } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { useIsDesktop } from "@/hooks/use-media-query"
import { allocationRows, GROUPINGS, limitOf, limitText, noIndustryText, overNote, topN, UNCLASSIFIED, type AllocRow } from "@/lib/allocation"
import { inText } from "@/lib/cjk"
import { formatMoney, formatMoneyCompact, formatPercent, MASK } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useCanImport } from "@/pages/transactions/import/access"
import { usePrefs } from "@/stores/prefs"
import { AllocationDonut, Swatch } from "./AllocationDonut"
import { LIMITS_EDITOR_ID, LimitsEditor, LimitValues } from "./AllocationLimits"
import { useHeroClose } from "./use-hero-close"

const pct = (w: number) => formatPercent(w, { signed: false, decimals: 1 })
/**
 * 金額（不帶 NT$，前綴另外畫）：圓環中間與清單的金額欄都放得下 8 位數；再大就寫「1.23 億」（清單滑過看完整的數字），
 * 不讓數字跑出圓環或欄位
 */
const AMOUNT_FULL_BELOW = 1e8
const amount = (v: number, max: number) => (Math.abs(v) >= max ? formatMoneyCompact(v, { bare: true }) : formatMoney(v, { bare: true }))

/**
 * 帳本「配置」分段（產品負責人 2026-11-18，全部照建議；延遲載入）：
 * 帳戶選單 → 集中度一行（最大一檔、前 5 大、最大產業；桌面多一格「你設定的上限」）→「持股比例」：
 * 分組切換（每一檔・產業・市場・帳戶・幣別・類型，預設每一檔）→ 圓環＋百分比清單（寬的時候清單在圓環右邊，窄的時候在下面）。
 * 只寫事實：沒設上限就只有數字；自己設了上限才標「超過你設定的 30%」（墨色，不用紅綠）。隱私模式遮金額、百分比照常。
 * 查看別人的資產（唯讀）時看得到授權者的上限，不能改。
 */
export function AllocationView() {
  const [account, setAccount] = useState<string | undefined>()
  const [grouping, setGrouping] = useState<AllocationGrouping>("holding")
  const [editing, setEditing] = useState(false)
  const accounts = useAccounts()
  const alloc = useAllocation(account)
  const isDesktop = useIsDesktop()
  const editButton = useRef<HTMLButtonElement>(null)
  const a = alloc.data
  const accountOptions = accounts.data ?? []
  // 還沒有帳戶時不放帳戶選單（只有「全部帳戶」一項沒有意義）
  const showAccounts = !(accounts.data && accounts.data.length === 0)

  const closeEditor = () => {
    setEditing(false)
    requestAnimationFrame(() => editButton.current?.focus())
  }

  return (
    <div className="flex flex-col">
      <div className="flex flex-wrap items-center gap-3">
        {showAccounts && (
        <Select
          value={account ?? "all"}
          onValueChange={(v) => setAccount(v === "all" ? undefined : (v as string))}
          items={[{ value: "all", label: "全部帳戶" }, ...accountOptions.map((x) => ({ value: x.id, label: x.name }))]}
        >
          <SelectTrigger size="sm" className="max-w-full min-w-36 pointer-coarse:data-[size=sm]:h-11" aria-label="帳戶">
            <SelectValue />
          </SelectTrigger>
          {/* 選單可以比按鈕寬（長的帳戶名稱看得完），最寬到畫面減兩邊；還是放不下時有省略號 */}
          <SelectContent className="w-auto max-w-[calc(100vw-2rem)] min-w-(--anchor-width)">
            <SelectItem value="all">全部帳戶</SelectItem>
            {accountOptions.map((x) => (
              <SelectItem key={x.id} value={x.id} title={x.name}>
                <span className="min-w-0 truncate">{x.name}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        )}
        {a?.is_demo && <DemoTag className="ml-auto" />}
      </div>

      {alloc.isError ? (
        <ErrorState className="mt-5" error={alloc.error} onRetry={() => void alloc.refetch()} />
      ) : !a ? (
        <AllocationSkeleton />
      ) : a.groups.holding.length === 0 ? (
        <EmptyAllocation account={account} onAll={() => setAccount(undefined)} />
      ) : (
        <div className={cn("flex flex-col transition-opacity", alloc.isPlaceholderData && "opacity-60")}>
          {/* 桌面的「修改」是展開／收合（aria-expanded）；手機的打開抽屜 */}
          <Stats alloc={a} desktop={isDesktop} onEdit={() => setEditing((e) => !e)} editButton={editButton} editing={editing} />
          {isDesktop && a.can_edit_limits && <LimitsEditor limits={a.concentration.limits} mode="inline" open={editing} onClose={closeEditor} />}
          <Breakdown alloc={a} grouping={grouping} onGrouping={setGrouping}>
            {!isDesktop && <LimitsRow alloc={a} onEdit={() => setEditing(true)} editButton={editButton} />}
          </Breakdown>
          {!isDesktop && a.can_edit_limits && <LimitsEditor limits={a.concentration.limits} mode="sheet" open={editing} onClose={closeEditor} />}
        </div>
      )}
    </div>
  )
}

/**
 * 沒有持股：自己的帳本給下一步（記一筆；開了匯入的帳號多一個「匯入庫存或對帳單」，和持倉的空狀態同一套）；
 * 只看某個帳戶時給「看全部帳戶」；查看別人的資產只寫標題。
 */
function EmptyAllocation({ account, onAll }: { account?: string; onAll: () => void }) {
  const ask = useAskAi()
  const readOnly = useReadOnly()
  const canImport = useCanImport()
  const openImport = useUi((s) => s.openImport)
  const className = "mt-5 border-b-0 pb-0"
  if (account) {
    return (
      <EmptyState
        className={className}
        title="這個帳戶沒有持股"
        action={
          <button type="button" className={textAction} onClick={onAll}>
            看全部帳戶
          </button>
        }
      />
    )
  }
  if (readOnly) return <EmptyState className={className} title="目前沒有持股" />
  return (
    <EmptyState
      className={className}
      title="目前沒有持股"
      description="記下持股後，這裡會列出每一檔佔多少。"
      action={
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
          <Button onClick={() => ask.action("form")}>記一筆</Button>
          {canImport && (
            <button type="button" onClick={() => openImport()} className={textAction}>
              匯入庫存或對帳單
            </button>
          )}
        </div>
      }
    />
  )
}

function AllocationSkeleton() {
  return (
    <div aria-busy="true" aria-label="配置載入中">
      <div className="mt-4 grid grid-cols-3 border-t border-rule lg:mt-5 lg:grid-cols-4">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="border-b border-rule py-3 pr-3 lg:py-4">
            <Skeleton className="h-4 w-16" />
            <Skeleton className="mt-2 h-7 w-20" />
          </div>
        ))}
      </div>
      <Skeleton className="mx-auto mt-10 size-44 rounded-full lg:mx-0" />
    </div>
  )
}

type OverText = { long: string; short: string; onTop: boolean }

/**
 * 「超過上限」：墨色細框小字（不用紅綠）；手機寫短的。格子窄（320px、開著 AI 面板的 1024px）或名字長（「爸爸設定的」）時換行，
 * 不撐出格子
 */
function OverTag({ note, who, className }: { note: OverText; who: string; className?: string }) {
  const long = who === "你" ? note.long : note.long.replace("你設定的", `${who}設定的`)
  return (
    <span className={cn("mt-1.5 inline-flex min-h-[22px] w-fit max-w-full items-center rounded-xs border border-ink px-1.5 py-0.5 text-xs leading-tight font-medium text-ink", className)}>
      <span className="lg:hidden" aria-hidden>
        {note.short}
      </span>
      <span className="max-lg:sr-only">{long}</span>
    </span>
  )
}

/**
 * 不是最大那一項超過的（最大一檔是 ETF，台積電超過單一個股上限）：不接在 ETF 的名稱與比例底下，
 * 放到「你設定的上限」那裡（桌面那一格、手機清單下面那一列）
 */
function asideNotes(alloc: PortfolioAllocation): OverText[] {
  const c = alloc.concentration
  return [overNote(c, "holding"), overNote(c, "industry")].filter((n): n is OverText => n !== null && !n.onTop)
}

/**
 * 集中度（只寫事實）：最大一檔（含 ETF）、前 5 大（持股 4–5 檔時是前 3 大，3 檔以下不放）、最大產業（不含 ETF）。
 * 桌面多一格「你設定的上限」（修改在這裡）；手機的上限在清單下面一列。鍵值格，和績效分段同一種格線。
 * 「超過上限」只接在本身超過的那一項底下（最大一檔是 ETF 時不接，見 `asideNotes`）。
 */
function Stats({
  alloc,
  desktop,
  onEdit,
  editButton,
  editing,
}: {
  alloc: PortfolioAllocation
  desktop: boolean
  onEdit: () => void
  editButton: React.Ref<HTMLButtonElement>
  editing: boolean
}) {
  const c = alloc.concentration
  const who = useWho("你")
  const top = topN(c)
  const holdingOver = overNote(c, "holding")
  const industryOver = overNote(c, "industry")
  const cells: { key: string; label: string; value: string; sub: React.ReactNode; wrap?: boolean; tag?: React.ReactNode }[] = [
    {
      key: "top",
      label: "最大一檔",
      value: c.top_holding ? pct(c.top_holding.weight) : "—",
      sub: c.top_holding?.name ?? "",
      tag: holdingOver?.onTop && <OverTag note={holdingOver} who={who} />,
    },
    ...(top ? [{ key: "topn", label: `前 ${top.n} 大`, value: pct(top.weight), sub: `共 ${c.holdings_count} 檔` }] : []),
    {
      key: "industry",
      label: "最大產業",
      value: c.top_industry ? pct(c.top_industry.weight) : "—",
      // 產業名稱與「・不含 ETF」可以換行（窄的桌面格子不截斷）；手機的「不含 ETF」寫在清單下面的說明
      wrap: true,
      sub: c.top_industry ? (
        <>
          {c.top_industry.label}
          <span className="text-ink-2 max-lg:hidden">・不含 ETF</span>
        </>
      ) : (
        <span className="text-ink-2">{noIndustryText(c)}</span>
      ),
      tag: industryOver?.onTop && <OverTag note={industryOver} who={who} />,
    },
  ]
  const cols = cells.length + (desktop ? 1 : 0)
  return (
    <dl
      className={cn("mt-4 grid border-t border-rule lg:mt-5", cols === 4 ? "grid-cols-4" : cols === 3 ? "grid-cols-3" : "grid-cols-2")}
      aria-label="集中度"
    >
      {cells.map((x) => (
        <div key={x.key} className="flex min-w-0 flex-col border-r border-b border-rule py-2.5 pr-2.5 pl-2.5 first:pl-0 last:border-r-0 lg:px-4 lg:py-4 lg:first:pl-0">
          <dt className="text-sm whitespace-nowrap text-ink-2">{x.label}</dt>
          <dd className="num text-[1.375rem] leading-[1.875rem] font-semibold lg:text-2xl">{x.value}</dd>
          <dd className={cn("text-md text-ink", !x.wrap && "truncate")} title={typeof x.sub === "string" ? x.sub : undefined}>
            {x.sub}
          </dd>
          {x.tag && <dd>{x.tag}</dd>}
        </div>
      ))}
      {desktop && (
        <div className="flex min-w-0 flex-col border-b border-rule py-4 pl-4">
          <dt className="text-sm whitespace-nowrap text-ink-2">{who}設定的上限</dt>
          <LimitsCell limits={c.limits} canEdit={alloc.can_edit_limits} onEdit={onEdit} editButton={editButton} editing={editing} aside={asideNotes(alloc)} who={who} />
        </div>
      )}
    </dl>
  )
}

function LimitsCell({
  limits,
  canEdit,
  onEdit,
  editButton,
  editing,
  aside,
  who,
}: {
  limits: AllocationLimits
  canEdit: boolean
  onEdit: () => void
  editButton: React.Ref<HTMLButtonElement>
  editing: boolean
  aside: OverText[]
  who: string
}) {
  const none = limits.holding === null && limits.industry === null
  return (
    <>
      <dd className="mt-1 text-base">
        {none ? <span className="text-ink-2">沒有設定</span> : <LimitValues limits={limits} className="flex-col gap-y-1" />}
      </dd>
      {aside.map((n) => (
        <dd key={n.long}>
          <OverTag note={n} who={who} />
        </dd>
      ))}
      {canEdit && (
        <dd className="mt-1">
          <button
            ref={editButton}
            type="button"
            className={textAction}
            onClick={onEdit}
            aria-expanded={editing}
            aria-controls={editing ? LIMITS_EDITOR_ID : undefined}
          >
            {none ? "設定上限" : "修改"}
          </button>
        </dd>
      )}
    </>
  )
}

/** 手機：清單下面一列「你設定的上限・單一個股 30%・單一產業 50%・修改」（最大一檔是 ETF 而別檔超過時，「1 檔超過上限」也在這裡） */
function LimitsRow({ alloc, onEdit, editButton }: { alloc: PortfolioAllocation; onEdit: () => void; editButton: React.Ref<HTMLButtonElement> }) {
  const who = useWho("你")
  const limits = alloc.concentration.limits
  const none = limits.holding === null && limits.industry === null
  return (
    <div className="mt-4 flex min-h-[52px] flex-wrap items-center gap-x-3.5 gap-y-1 border-y border-rule py-1.5 text-base">
      <span className="text-sm text-ink-2">{who}設定的上限</span>
      {none ? <span className="text-ink-2">沒有設定</span> : <LimitValues limits={limits} />}
      {asideNotes(alloc).map((n) => (
        <OverTag key={n.long} note={n} who={who} className="mt-0" />
      ))}
      {alloc.can_edit_limits && (
        <button ref={editButton} type="button" className={cn(textAction, "ml-auto")} onClick={onEdit} aria-haspopup="dialog">
          {none ? "設定上限" : "修改"}
        </button>
      )}
    </div>
  )
}

/** 「持股比例」：分組切換、圓環、清單與說明 */
function Breakdown({
  alloc,
  grouping,
  onGrouping,
  children,
}: {
  alloc: PortfolioAllocation
  grouping: AllocationGrouping
  onGrouping: (g: AllocationGrouping) => void
  children?: React.ReactNode
}) {
  const privacy = usePrefs((s) => s.privacyMode)
  // 和總資產那一行同一個寫法（「收盤價・11/12（四）」）
  const close = useHeroClose()
  const [active, setActive] = useState<string | null>(null)
  const rows = useMemo(() => allocationRows(alloc, grouping), [alloc, grouping])
  const activeRow = rows.find((r) => r.key === active)
  const count = alloc.concentration.holdings_count
  return (
    <section aria-labelledby="alloc-title" className="mt-10 flex min-w-0 flex-col">
      <header className="flex min-h-11 flex-wrap items-end gap-x-3 gap-y-1 border-b border-print pb-2">
        <h2 id="alloc-title" className="text-xl font-bold">
          持股比例
        </h2>
        <span className="num text-sm text-ink-2">
          {count} 檔・{close.label}
        </span>
      </header>
      <RangeChips className="mt-2" label="分組" value={grouping} options={GROUPINGS} onChange={(g) => { setActive(null); onGrouping(g) }} />
      <div className="@container/alloc mt-2">
        <div className="flex flex-col @2xl/alloc:grid @2xl/alloc:grid-cols-[13rem_minmax(0,1fr)] @2xl/alloc:items-start @2xl/alloc:gap-x-9">
          <AllocationDonut
            rows={rows}
            active={active}
            onActive={setActive}
            className="mx-auto my-3 w-46 @2xl/alloc:mx-0 @2xl/alloc:mt-12 @2xl/alloc:w-52"
            center={
              <>
                <span className="text-sm text-ink-2">{count} 檔</span>
                <span className="num mt-0.5 text-base leading-snug font-medium whitespace-nowrap">
                  {privacy ? (
                    MASK
                  ) : (
                    <>
                      <span className="mr-0.5 text-xs font-normal text-ink-2">NT$</span>
                      {amount(alloc.market_value, AMOUNT_FULL_BELOW)}
                    </>
                  )}
                </span>
              </>
            }
            activeCenter={
              activeRow && (
                <>
                  <span className="line-clamp-2 max-w-full text-sm leading-tight break-all text-ink">{activeRow.label}</span>
                  <span className="num mt-0.5 text-xl leading-tight font-semibold">{pct(activeRow.weight)}</span>
                </>
              )
            }
          />
          <div className="min-w-0">
            <AllocationList rows={rows} grouping={grouping} onActive={setActive} privacy={privacy} />
            {children}
            <Notes alloc={alloc} grouping={grouping} />
          </div>
        </div>
      </div>
    </section>
  )
}

/**
 * 百分比清單（要讀的是這個；圓環只是幫忙看）：每一列 色塊・名稱（第二行：代號／裡面有哪幾檔／幾檔）・細比例條・百分比・金額。
 * 比例條是 0–100%（佔總市值），使用者設了上限的那一組多一條墨色直線。「其他」與產業的「ETF」可以點開。
 * 窄的時候兩行：名稱整行（只讓出百分比）｜第二行 代號・比例條・金額，320px 也看得出是哪一檔、哪個帳戶；寬的時候一行。
 * 名稱放不下時截斷，滑過（title）看全名。
 */
function AllocationList({ rows, grouping, onActive, privacy }: { rows: AllocRow[]; grouping: AllocationGrouping; onActive: (k: string | null) => void; privacy: boolean }) {
  // 產業的「ETF」預設打開（看得到國內股票型、海外、債券…）；「其他」預設收起來
  const [open, setOpen] = useState<Set<string>>(() => new Set(["__etf"]))
  const toggle = (key: string) => setOpen((s) => {
    const next = new Set(s)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })
  const label = GROUPINGS.find((g) => g.value === grouping)!.label
  return (
    <div className="@container/list min-w-0">
      <div className="form-head grid h-9 grid-cols-[minmax(0,1fr)_auto] items-end gap-x-3 pb-1.5 @md/list:grid-cols-[minmax(0,1fr)_6.5rem_7.5rem]">
        <span>名稱</span>
        <span className="text-right">佔比</span>
        <span className="hidden text-right @md/list:block">市值</span>
      </div>
      <ul aria-label={`持股比例（${label}）`} onPointerLeave={() => onActive(null)}>
        {rows.map((r) => (
          <Fragment key={r.key}>
            <Row row={r} privacy={privacy} open={open.has(r.key)} onToggle={r.kids ? () => toggle(r.key) : undefined} onActive={onActive} />
            {r.kids && open.has(r.key) && (
              <li>
                <ul id={`alloc-kids-${r.key}`} aria-label={`${r.label}裡面`}>
                  {r.kids.map((k) => (
                    <Row key={k.key} row={k} privacy={privacy} kid onActive={(x) => onActive(x === null ? null : r.key)} />
                  ))}
                </ul>
              </li>
            )}
          </Fragment>
        ))}
      </ul>
    </div>
  )
}

const ROW =
  "grid w-full grid-cols-[0.625rem_minmax(0,1fr)_4.5rem_2.75rem_3.75rem] [grid-template-areas:'sw_nm_nm_nm_pc'_'sw_sub_bar_amt_amt'] items-center gap-x-2.5 border-b border-rule py-2.5 text-left @md/list:grid-cols-[0.625rem_minmax(0,1fr)_7.5rem_3.75rem_7.5rem] @md/list:[grid-template-areas:'sw_nm_bar_pc_amt'_'sw_sub_bar_pc_amt'] @md/list:gap-x-3 @md/list:py-2"

function Row({ row, privacy, open, onToggle, onActive, kid }: { row: AllocRow; privacy: boolean; open?: boolean; onToggle?: () => void; onActive: (k: string | null) => void; kid?: boolean }) {
  const who = useWho("你")
  const body = (
    <>
      <span className={cn("[grid-area:sw] self-start", kid ? "-my-2.5 h-[calc(100%+1.25rem)] w-px justify-self-center bg-rule @md/list:-my-2 @md/list:h-[calc(100%+1rem)]" : "mt-[7px]")}>
        {!kid && <Swatch tone={row.tone} />}
      </span>
      <span className="flex min-w-0 items-center gap-2 [grid-area:nm]">
        <span className={cn("min-w-0 [overflow-wrap:anywhere]", kid ? "text-base" : "text-lg leading-6 font-medium")}>
          {row.label}
        </span>
        {row.over && row.limit !== null && (
          <span className="inline-flex h-5 shrink-0 items-center rounded-xs border border-ink px-1 text-xs font-medium text-ink">
            超過上限<span className="sr-only">：{who}設定的 {limitText(row.limit)}</span>
          </span>
        )}
        {onToggle && <ChevronDownIcon aria-hidden className={cn("size-4 shrink-0 text-ink-2", open && "rotate-180")} />}
      </span>
      <span className="truncate text-sm leading-5 text-ink-2 [grid-area:sub]">{row.sub}</span>
      <Bar weight={row.weight} limit={row.limit} />
      <span className={cn("num text-right whitespace-nowrap [grid-area:pc]", kid ? "text-base" : "text-lg leading-6 font-medium")}>{pct(row.weight)}</span>
      <span className="num text-right text-sm leading-5 whitespace-nowrap text-ink-2 [grid-area:amt] @md/list:text-base @md/list:text-ink">
        {privacy ? (
          <Masked className="text-ink-2" />
        ) : (
          <span title={Math.abs(row.value) >= AMOUNT_FULL_BELOW ? formatMoney(row.value) : undefined}>
            <span className="mr-0.5 text-xs text-ink-2">NT$</span>
            {amount(row.value, AMOUNT_FULL_BELOW)}
          </span>
        )}
      </span>
    </>
  )
  const hover = { onPointerEnter: () => onActive(row.key), onFocus: () => onActive(row.key), onBlur: () => onActive(null) }
  if (onToggle) {
    return (
      <li>
        <button
          type="button"
          className={cn(ROW, "press ruled-row")}
          aria-expanded={open}
          aria-controls={open ? `alloc-kids-${row.key}` : undefined}
          onClick={onToggle}
          {...hover}
        >
          {body}
        </button>
      </li>
    )
  }
  return (
    <li className={cn(ROW, kid && "min-h-14")} {...hover}>
      {body}
    </li>
  )
}

/** 細比例條：3px，0–100%；使用者設的上限是一條墨色細直線 */
function Bar({ weight, limit }: { weight: number; limit: number | null }) {
  return (
    <span aria-hidden className="relative h-[3px] self-center bg-rule [grid-area:bar]">
      <span className="absolute inset-y-0 left-0 bg-ink" style={{ width: `${Math.min(Math.max(weight, 0), 1) * 100}%` }} />
      {limit !== null && <span className="absolute -inset-y-[5px] w-px bg-ink" style={{ left: `${limit * 100}%` }} />}
    </span>
  )
}

/**
 * 清單下面的說明：直線的圖例、ETF 不算產業（每一檔：最大產業不含 ETF，手機的集中度格子沒地方寫）、未分類、
 * 沒有收盤價照成本算、美股的匯率（後端給的、和持倉同一個；這個範圍裡有美元持股才寫）
 */
function Notes({ alloc, grouping }: { alloc: PortfolioAllocation; grouping: AllocationGrouping }) {
  const who = useWho("你")
  const limit = limitOf(grouping, alloc.concentration.limits)
  const names = new Map(alloc.groups.holding.map((s) => [s.key, s.label]))
  const nameList = (syms: string[]) => inText(syms.map((s) => names.get(s) ?? s).join("、"), "start")
  const unclassified = alloc.groups.industry.find((s) => s.key === UNCLASSIFIED)
  const hasEtf = alloc.groups.holding.some((s) => s.is_etf)
  const rate = alloc.groups.currency.some((s) => s.key === "USD") ? alloc.fx.USD : undefined
  const notes: React.ReactNode[] = []
  if (grouping === "industry" && hasEtf) notes.push("ETF 不算進產業，也不拆成分股。")
  if (grouping === "holding" && hasEtf) notes.push(`${alloc.concentration.top_industry ? "最大產業不含 ETF。" : ""}ETF 算一檔，不拆成分股。`)
  if (grouping === "industry" && unclassified) notes.push(`${nameList(unclassified.symbols)}還沒有產業資料，列在「未分類」。`)
  if (alloc.valued_at_cost.length > 0) notes.push(`${nameList(alloc.valued_at_cost)}還沒有收盤價，先照成本算。`)
  const meta: string[] = []
  if (rate !== undefined) meta.push(`美股依匯率 ${rate.toFixed(2)} 換成新台幣。`)
  if (!limit && notes.length === 0 && meta.length === 0) return null
  return (
    <div className="mt-3.5 flex flex-col gap-1">
      {limit && (
        <p className="flex items-center gap-2.5 text-sm text-ink-2">
          <span aria-hidden className="relative h-[3px] w-8 shrink-0 bg-rule">
            <span className="absolute inset-y-0 left-0 w-5 bg-ink" />
            <span className="absolute -inset-y-[5px] left-3.5 w-px bg-ink" />
          </span>
          直線是{who}設定的{limit.kind === "holding" ? "單一個股" : "單一產業"}上限 {limitText(limit.value)}
        </p>
      )}
      {notes.map((n, i) => (
        <p key={i} className="text-base text-ink">
          {n}
        </p>
      ))}
      {meta.map((m) => (
        <p key={m} className="num text-sm text-ink-2">
          {m}
        </p>
      ))}
    </div>
  )
}

