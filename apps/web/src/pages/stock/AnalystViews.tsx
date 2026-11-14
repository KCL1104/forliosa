import { useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ChevronDownIcon } from "lucide-react"
import { useCallback, useEffect, useReducer, useState } from "react"
import { ApiError, api, appToday } from "@/api"
import type { AnalystView, InstrumentDetail } from "@/api/types"
import { aiKeys, useAiUsage } from "@/ai/remote-hooks"
import { DataNotes } from "@/components/data-notes"
import { SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import {
  ANALYST_DISCLAIMER_FALLBACK,
  ANALYST_INITIAL,
  ANALYST_POLL_MS,
  analystReducer,
  formatTarget,
  hostOf,
  loadOnOpen,
  nextPoll,
  ratingLine,
  viewDate,
  visibleViews,
  type AnalystEvent,
  type AnalystState,
} from "@/lib/analyst-views"
import { formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

/** 展開 → GET；`none` 時按下才 POST（AI 網路搜尋），`pending` 時輪詢 */
const failed = (during: "get" | "post", err: unknown): AnalystEvent => ({
  type: "failed",
  during,
  message: err instanceof ApiError ? err.message : "可能是網路不穩或伺服器暫時沒有回應。",
  code: err instanceof ApiError ? err.code : null,
})

function useAnalystViews(symbol: string) {
  const [state, dispatch] = useReducer(analystReducer, ANALYST_INITIAL)
  const qc = useQueryClient()
  const get = useCallback(() => {
    dispatch({ type: "load" })
    api.getAnalystViews(symbol).then(
      (data) => dispatch({ type: "loaded", data, at: Date.now() }),
      (err: unknown) => dispatch(failed("get", err)),
    )
  }, [symbol])
  const search = () => {
    if (state.inFlight === "post") return
    dispatch({ type: "search", at: Date.now() })
    api.requestAnalystViews(symbol).then((data) => {
      dispatch({ type: "searched", data, at: Date.now() })
      // 這次搜尋計入使用者的 AI 額度
      void qc.invalidateQueries({ queryKey: aiKeys.usage })
    }, (err: unknown) => dispatch(failed("post", err)))
  }
  useEffect(() => {
    if (nextPoll(state, Date.now()) === null) return
    const id = window.setTimeout(() => {
      if (nextPoll(state, Date.now()) === "timeout") dispatch({ type: "timeout" })
      else get()
    }, ANALYST_POLL_MS)
    return () => window.clearTimeout(id)
  }, [state, get])
  return {
    state,
    /** 第一次展開，或上次查不到／出錯時重新展開，才讀 */
    ensureLoaded: () => {
      if (loadOnOpen(state)) get()
    },
    retry: () => (state.error?.during === "post" ? search() : get()),
    search,
  }
}

/**
 * 法人觀點：個股頁總覽的收合區塊（格線，不是卡片）。第三方已公開的評等與目標價，最多 5 筆，每筆附日期與來源。
 * 不算平均、上漲空間，不排名、不寫買賣提示；評等是文字，不上紅綠。免責文字永遠顯示（後端提供）。沒有個人資料，隱私模式不影響。
 */
export function AnalystViewsCard({ inst }: { inst: InstrumentDetail }) {
  const [open, setOpen] = useState(false)
  const av = useAnalystViews(inst.symbol)
  const { state } = av
  const toggle = () => {
    setOpen(!open)
    if (!open) av.ensureLoaded()
  }
  const busy = state.phase === "loading" || state.phase === "searching"
  return (
    <section aria-labelledby="ov-analyst-title">
      <h2 id="ov-analyst-title" className="m-0">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="ov-analyst-body"
          onClick={toggle}
          className="group flex min-h-10 w-full items-end gap-x-3 border-b border-rule pb-2 text-left pointer-coarse:min-h-11"
        >
          <span className="text-lg font-bold">法人觀點</span>
          <span className="pb-px text-sm font-normal text-ink-2">第三方意見</span>
          <ChevronDownIcon aria-hidden className={cn("mb-0.5 ml-auto size-[18px] shrink-0 text-ink-2 transition-transform duration-200 group-hover:text-ink", open && "rotate-180")} />
        </button>
      </h2>
      {open && (
        <div id="ov-analyst-body" className="note-in pt-3" aria-busy={busy}>
          {state.phase === "loading" || state.phase === "idle" ? (
            <SkeletonLines rows={3} className="py-2" />
          ) : (
            <>
              <p className="max-w-prose text-sm text-ink-2">{state.data?.disclaimer || ANALYST_DISCLAIMER_FALLBACK}</p>
              {/* 只念一句狀態，不把整張表念出來 */}
              <p role="status" className="sr-only">
                {announce(state)}
              </p>
              <div className="mt-3">
                <Body inst={inst} state={state} onSearch={av.search} onRetry={av.retry} />
              </div>
            </>
          )}
        </div>
      )}
    </section>
  )
}

function announce(state: AnalystState): string {
  switch (state.phase) {
    case "searching":
      return "正在搜尋近期的法人觀點"
    case "ready":
      return `找到 ${visibleViews(state.data?.items).length} 筆法人觀點`
    case "empty":
      return "近期查無法人報導"
    case "unavailable":
      return "法人觀點暫時查不到"
    default:
      return ""
  }
}

function Body({ inst, state, onSearch, onRetry }: { inst: InstrumentDetail; state: AnalystState; onSearch: () => void; onRetry: () => void }) {
  const notes = state.data?.notes
  switch (state.phase) {
    case "none":
      return <SearchPrompt onSearch={onSearch} />
    case "searching":
      return (
        <div>
          <p className="max-w-prose text-base text-ink">正在找近期媒體報導的法人觀點…</p>
          <p className="mt-2 flex min-h-6 items-center gap-2 text-sm text-ink-2">
            {/* 靜止的石墨灰點＋寫明正在做什麼（不用脈動假裝即時） */}
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-ai" />
            <span className="min-w-0 truncate">搜尋網路：{inst.name} 法人評等與目標價…</span>
          </p>
        </div>
      )
    case "ready":
      return (
        <>
          <ViewsTable items={visibleViews(state.data?.items)} />
          <ViewsList items={visibleViews(state.data?.items)} />
          <Footer asOf={state.data?.as_of} notes={notes} />
        </>
      )
    case "empty":
      return (
        <>
          <p className="font-medium">近期查無法人報導</p>
          <p className="mt-0.5 max-w-prose text-base text-ink">近期的媒體報導裡，沒有找到附日期與來源的機構評等或目標價。</p>
          <EventsLink symbol={inst.symbol} />
          <Footer asOf={state.data?.as_of} notes={notes} />
        </>
      )
    case "unavailable":
      return (
        <>
          <p className="text-md text-ink">法人觀點暫時查不到，稍後再打開看看。</p>
          <EventsLink symbol={inst.symbol} />
          <DataNotes notes={[...(notes ?? []), ...(state.error ? [state.error.message] : [])]} className="mt-1" />
        </>
      )
    case "error":
      return (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p className="text-md">
            {state.error?.during === "post" ? "這次沒有查成" : "法人觀點沒有載入"}
            <span className="text-ink-2">：{state.error?.message}</span>
          </p>
          {state.error?.code !== "ai_daily_limit" && state.error?.code !== "ai_monthly_budget" && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              再試一次
            </Button>
          )}
        </div>
      )
    default:
      return null
  }
}

/**
 * 查無報導／查不到時唯一的下一步：到「事件」分頁看官方公告（不花 AI 額度；再問 AI 多半同樣查不到）。
 * 站內的文字連結：墨色字＋常駐底線，觸控時 44px 高（textAction）。
 */
function EventsLink({ symbol }: { symbol: string }) {
  return (
    <div className="mt-1.5">
      <Link to="/stock/$symbol" params={{ symbol }} search={{ tab: "events" }} resetScroll={false} className={textAction}>
        看公告
      </Link>
    </div>
  )
}

/** 今天還沒有人查過：一個安靜的查詢按鈕（只有字，不加裝飾圖示） */
function SearchPrompt({ onSearch }: { onSearch: () => void }) {
  const usage = useAiUsage().data
  const off = usage?.available === false || usage?.messages_remaining === 0 || usage?.tokens_remaining === 0
  const hint =
    usage?.available === false
      ? "AI 暫時無法使用，稍後再查。"
      : usage?.messages_remaining === 0 || usage?.tokens_remaining === 0
        ? "今天的提問額度用完了，明天再查。"
        : usage?.messages_remaining !== null && usage?.messages_remaining !== undefined && usage.messages_remaining <= 5
          ? `查詢算一題，今天還可以問 ${usage.messages_remaining} 題。`
          : null
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="max-w-prose text-md text-ink">近期媒體報導的機構評等與目標價，最多 5 筆，每筆附報導日期與原文連結。</p>
      <Button variant="outline" onClick={onSearch} disabled={off}>
        查詢近期法人觀點
      </Button>
      {hint && <p className="text-sm text-ink-2">{hint}</p>}
    </div>
  )
}

function Footer({ asOf, notes }: { asOf?: string | null; notes?: string[] }) {
  return (
    <div className="mt-2.5 flex flex-col gap-0.5">
      {asOf && <p className="num text-sm text-ink-2">查詢時間 {formatDateTime(asOf)}・以原始報導為準</p>}
      <DataNotes notes={notes} />
    </div>
  )
}

function SourceLink({ v, className }: { v: AnalystView; className?: string }) {
  const host = hostOf(v.url)
  return (
    <a href={v.url} target="_blank" rel="noopener noreferrer" className={cn("group inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-sm", className)}>
      <span className="min-w-0 truncate underline decoration-ctl underline-offset-3 group-hover:decoration-ink">{v.source_title}</span>
      {host && <span className="num shrink-0 text-sm text-ink-2">{host}</span>}
      <span className="sr-only">（另開新視窗）</span>
    </a>
  )
}

/** 桌面：格線表（日期・機構・評等・目標價・來源），評等與目標價照原文，不上色、不排序以外的加工 */
function ViewsTable({ items }: { items: AnalystView[] }) {
  const today = appToday()
  const th = "h-10"
  return (
    <table className="w-full table-fixed border-collapse max-md:hidden" aria-label="法人觀點">
      <thead className="form-head">
        <tr>
          <th scope="col" className={cn(th, "w-[76px] text-left")}>日期</th>
          <th scope="col" className={cn(th, "w-[18%] text-left")}>機構</th>
          <th scope="col" className={cn(th, "w-[19%] text-left")}>評等</th>
          <th scope="col" className={cn(th, "w-[128px] pr-6 text-right")}>目標價</th>
          <th scope="col" className={cn(th, "text-left")}>來源</th>
        </tr>
      </thead>
      <tbody>
        {items.map((v) => (
          <tr key={`${v.date}-${v.institution}-${v.url}`} className="border-b border-rule">
            <td className="num h-[52px] py-2 text-md">{viewDate(v.date, today)}</td>
            <th scope="row" className="truncate py-2 pr-3 text-left font-medium">{v.institution}</th>
            <td className="truncate py-2 pr-3">{ratingLine(v)}</td>
            <td className="num py-2 pr-6 text-right whitespace-nowrap">{formatTarget(v.target_price, v.currency)}</td>
            <td className="py-2 text-md">
              <SourceLink v={v} className="h-8 pointer-coarse:h-11" />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** 手機：三行列（機構＋目標價、評等＋日期、來源連結） */
function ViewsList({ items }: { items: AnalystView[] }) {
  const today = appToday()
  return (
    <ul className="border-t border-rule md:hidden" aria-label="法人觀點">
      {items.map((v) => (
        <li key={`${v.date}-${v.institution}-${v.url}`} className="border-b border-rule pt-3 pb-1">
          <div className="grid grid-cols-[1fr_auto] items-baseline gap-x-3 gap-y-0.5">
            <span className="truncate text-lg leading-6 font-medium">{v.institution}</span>
            <span className="num text-right text-lg leading-6">
              <span className="mr-1 text-sm text-ink-2">目標價</span>
              {formatTarget(v.target_price, v.currency)}
            </span>
            <span className="text-base leading-5">{ratingLine(v)}</span>
            <span className="num text-right text-sm leading-5 text-ink-2">{viewDate(v.date, today)}</span>
          </div>
          <SourceLink v={v} className="min-h-11 text-md text-ink-2" />
        </li>
      ))}
    </ul>
  )
}
