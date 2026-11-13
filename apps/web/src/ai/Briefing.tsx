import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { useBriefings, useLatestBriefing, useMarkBriefingRead } from "@/api/queries"
import type { Briefing, BriefingMover } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { Masked, Pct } from "@/components/finance"
import { CitedSources } from "@/components/cited-sources"
import { DateCell } from "@/components/date-cell"
import { DemoTag, Section } from "@/components/section"
import { direction, formatDateShort, formatMoney, toneClass } from "@/lib/format"
import { upcomingText } from "@/lib/ledger-display"
import { cn } from "@/lib/utils"
import { usePrefs } from "@/stores/prefs"
import { kaiSize } from "./kai-size"
import { KaiText } from "./kai-text"
import { bleed, bleedPad } from "./panel-helpers"

/**
 * 每日收盤簡報（產品負責人 2026-11-14：固定的一種排程工作，預設關，在設定打開）。
 * 一則有兩部分：規則算出來的事實（總資產、今日損益、漲跌最多的持股、觀察清單裡動得多的、這一週的事項）是印刷的字；
 * AI 依報導補的幾點是鉛筆（石墨灰楷體，和對話裡的回答、市場頁的收盤重點同一套排法），每一點下面列出依據的報導。
 * 這個檔案有三個出口：面板首頁最上面的那一塊、對話紀錄頁的「收盤簡報」、還沒看過時的小圓點（要不要顯示看 `use-briefing-unread.ts`）。
 */

/** 未讀的小圓點（不是數字徽章）：放在「問 AI」的按鈕與面板標題旁邊 */
export function BriefingDot({ className }: { className?: string }) {
  return <span aria-hidden data-briefing-dot className={cn("inline-block size-2 shrink-0 rounded-full bg-ai", className)} />
}

const MARK_READ_AFTER_MS = 1200

/**
 * 面板首頁最上面：最新的一則。還沒看過時展開著；看過之後收成一列，按一下再展開。
 * `besideLedger`：桌面面板在帳本旁邊時，總資產、當日與這一週左邊都看得到，不再列一次（2026-11-14 第六次評分）
 */
export function BriefingBlock({ size, besideLedger = false }: { size: "panel" | "screen"; besideLedger?: boolean }) {
  const readOnly = useReadOnly()
  const latest = useLatestBriefing(!readOnly)
  const mark = useMarkBriefingRead()
  const briefing = readOnly ? null : (latest.data ?? null)
  // 第一次拿到這一則時決定開合（還沒看過＝展開），之後只照使用者按的：讀到一半被記成「看過」時不會自己收起來
  const [shown, setShown] = useState<{ id: string; open: boolean } | null>(null)
  if (briefing && shown?.id !== briefing.id) setShown({ id: briefing.id, open: !briefing.read })
  const open = !!briefing && shown?.id === briefing.id && shown.open
  const bodyId = useId()
  const id = briefing?.id
  const unread = !!briefing && !briefing.read
  const markRead = mark.mutate

  // 展開著而且還沒看過：停一下就算看過（圓點消失；伺服器記下來）
  useEffect(() => {
    if (!id || !unread || !open) return
    const timer = setTimeout(() => markRead(id), MARK_READ_AFTER_MS)
    return () => clearTimeout(timer)
  }, [id, unread, open, markRead])

  if (!briefing) return null
  return (
    <section aria-label="收盤簡報" className={cn("border-b border-rule", bleed[size], bleedPad[size], open ? "pb-3" : "pb-0")}>
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setShown({ id: briefing.id, open: !open })}
          className={cn("group flex w-full items-center gap-2 text-left focus-visible:-outline-offset-2", size === "screen" ? "min-h-14" : "min-h-12")}
        >
          {unread && <BriefingDot />}
          <span className={cn("font-bold", size === "screen" ? "text-lg" : "text-base")}>收盤簡報</span>
          <span className="num text-sm text-ink-2">{formatDateShort(briefing.date)}</span>
          {unread && <span className="sr-only">（還沒看過）</span>}
          {briefing.facts.is_demo && <DemoTag className="ml-1" />}
          <ChevronDownIcon aria-hidden className={cn("ml-auto size-5 shrink-0 text-ink-2 transition-transform duration-150 group-hover:text-ink motion-reduce:transition-none", open && "rotate-180")} />
        </button>
      </h3>
      <div id={bodyId} hidden={!open}>
        <BriefingBody briefing={briefing} size={size} omitLedger={besideLedger} />
      </div>
    </section>
  )
}

/** 一則簡報的內容：事實（印刷）＋AI 補充（鉛筆） */
export function BriefingBody({ briefing, size, omitLedger = false }: { briefing: Briefing; size: "panel" | "screen" | "page"; omitLedger?: boolean }) {
  const privacy = usePrefs((s) => s.privacyMode)
  const f = briefing.facts
  return (
    <div className="flex flex-col">
      <dl className="grid grid-cols-[4.75rem_minmax(0,1fr)] gap-x-3 text-base">
        {f.holdings > 0 && !omitLedger && (
          <>
            <Fact label="總資產">{privacy ? <Masked /> : <span className="num">{formatMoney(f.market_value)}</span>}</Fact>
            <Fact label="當日">
              <span className="inline-flex flex-wrap items-baseline gap-x-2">
                {privacy ? <Masked /> : <span className={cn("num", toneClass(direction(f.day_change)))}>{formatMoney(f.day_change, { signed: true })}</span>}
                <Pct value={f.day_change_pct} />
              </span>
            </Fact>
          </>
        )}
        {f.gainers.length > 0 && (
          <Fact label="漲最多">
            <Movers items={f.gainers} />
          </Fact>
        )}
        {f.losers.length > 0 && (
          <Fact label="跌最多">
            <Movers items={f.losers} />
          </Fact>
        )}
        {f.watchlist.length > 0 && (
          <Fact label="觀察清單">
            <Movers items={f.watchlist} />
          </Fact>
        )}
        {f.upcoming.length > 0 && !omitLedger && (
          <Fact label="這一週">
            <ul className="flex flex-col gap-0.5">
              {f.upcoming.map((u, i) => (
                <li key={`${u.date}-${u.type}-${u.symbol ?? ""}-${i}`} className="grid grid-cols-[3rem_minmax(0,1fr)] items-baseline gap-x-2">
                  <span className="num text-ink-2">{formatDateShort(u.date, false)}</span>
                  <span>{upcomingText(u, privacy)}</span>
                </li>
              ))}
            </ul>
          </Fact>
        )}
      </dl>
      {f.unpriced > 0 && !omitLedger && <p className="mt-2 text-sm text-ink-2">{f.unpriced} 檔沒有收盤價，不算在當日。</p>}
      {briefing.points.length > 0 && (
        <>
          <ul className="mt-1">
            {briefing.points.map((p, n) => (
              <li key={n} className="border-t border-rule py-2.5 first:border-t-0">
                <p className={cn("ai-voice", size === "page" ? kaiSize.page : kaiSize[size])}>
                  <KaiText text={p.text} />
                </p>
                <CitedSources sources={p.sources} />
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-2">AI 依這些報導整理，內容以原報導為準。</p>
        </>
      )}
    </div>
  )
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="col-span-2 grid grid-cols-subgrid items-baseline border-b border-rule py-2 last:border-b-0">
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  )
}

/** 「台積電 ▲4.83%」一檔一段，放不下就換行（名稱和漲跌幅不拆開） */
function Movers({ items }: { items: BriefingMover[] }) {
  return (
    <span className="flex flex-wrap gap-x-4 gap-y-0.5">
      {items.map((m) => (
        <span key={m.symbol} className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
          {m.name}
          <Pct value={m.change_pct} />
        </span>
      ))}
    </span>
  )
}

/** 這一點依據的報導：媒體名稱（同一家只列一次），13px 淡墨、常駐底線；連到原文、另開視窗（和市場頁的收盤重點同一種寫法） */
/** 對話紀錄頁的「收盤簡報」：最近 14 則，一列一則（日期、當天的損益），按一下展開。沒有簡報就整段不出現 */
export function BriefingHistory() {
  const list = useBriefings()
  const privacy = usePrefs((s) => s.privacyMode)
  const [openId, setOpenId] = useState<string | null>(null)
  const items = list.data ?? []
  if (items.length === 0) return null
  return (
    <Section title="收盤簡報" titleId="briefing-history" bodyClassName="pt-0">
      <ul className="border-b border-rule">
        {items.map((b) => {
          const open = openId === b.id
          return (
            <li key={b.id} className="border-t border-rule first:border-t-0">
              <button
                type="button"
                aria-expanded={open}
                aria-controls={`briefing-${b.id}`}
                onClick={() => setOpenId(open ? null : b.id)}
                className="group flex min-h-12 w-full items-stretch gap-3 py-2 text-left text-base focus-visible:-outline-offset-2"
              >
                {/* 和上面的對話清單同一種日期格（日期墨色、星期小字淡墨，右邊一條格線） */}
                <DateCell date={b.date} inline pad="-my-2 py-2" className="num w-24 shrink-0" />
                {/* 展開時當日損益就在內文裡，標題列不再寫一次 */}
                {b.facts.holdings > 0 && !open && (
                  <span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-2 self-center">
                    <span className="text-sm text-ink-2">當日</span>
                    {privacy ? <Masked /> : <span className={cn("num", toneClass(direction(b.facts.day_change)))}>{formatMoney(b.facts.day_change, { signed: true })}</span>}
                    <Pct value={b.facts.day_change_pct} />
                  </span>
                )}
                <ChevronDownIcon aria-hidden className={cn("ml-auto size-5 shrink-0 self-center text-ink-2 transition-transform duration-150 group-hover:text-ink motion-reduce:transition-none", open && "rotate-180")} />
              </button>
              <div id={`briefing-${b.id}`} hidden={!open} className="max-w-[46rem] pb-3">
                {open && <BriefingBody briefing={b} size="page" />}
              </div>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}
