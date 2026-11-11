import { Link } from "@tanstack/react-router"
import { ChevronRightIcon, SearchIcon, StarIcon } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { api } from "@/api"
import { useSummary } from "@/api/queries"
import { isActivePath, MORE_ITEMS } from "@/app/nav"
import { useUi } from "@/app/ui-store"
import { Chop, SoonChop } from "@/components/chop"
import { Pct, Price } from "@/components/finance"
import { PageHeader, Panel } from "@/components/section"
import { EmptyState, SkeletonLines } from "@/components/states"
import { Button, buttonVariants } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { formatDateShort, formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"
import { useWatchlist } from "@/stores/watchlist"

/** 規劃中頁面的共用骨架：這裡會有什麼 → 示意 → 現在可以先做什麼 */
function Planned({
  title,
  milestone,
  lead,
  features,
  children,
  now,
}: {
  title: string
  milestone: string
  lead: string
  features: [string, string][]
  children?: React.ReactNode
  now?: React.ReactNode
}) {
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader title={title} meta={<SoonChop milestone={milestone} />} description={lead} />
      <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-3">
        {features.map(([k, v]) => (
          <div key={k} className="border-t border-border pt-3">
            <dt className="font-medium">{k}</dt>
            <dd className="mt-1 text-md text-muted-foreground">{v}</dd>
          </div>
        ))}
      </dl>
      {children}
      {now && (
        <section aria-labelledby="now-title" className="flex flex-col gap-2">
          <h2 id="now-title" className="text-lg font-semibold">現在可以先做的事</h2>
          {now}
        </section>
      )}
    </div>
  )
}

// ── 自選（M2）：先用本機清單 ───────────────────────────────
export function WatchlistPage() {
  const symbols = useWatchlist((s) => s.symbols)
  const toggle = useWatchlist((s) => s.toggle)
  const setSearchOpen = useUi((s) => s.setSearchOpen)
  const quotes = useQuery({ queryKey: ["quotes", symbols], queryFn: () => api.getQuotes(symbols), enabled: symbols.length > 0 })
  const names = useQuery({
    queryKey: ["watch-names", symbols],
    queryFn: async () => Object.fromEntries(await Promise.all(symbols.map(async (s) => [s, await api.getInstrument(s)] as const))),
    enabled: symbols.length > 0,
  })
  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <PageHeader
        title="自選"
        meta={<SoonChop milestone="M2" />}
        description="先把想追蹤的股票存在這台裝置上；M2 會加入迷你走勢圖、排序、備註與跨裝置同步。"
        actions={
          <Button variant="outline" onClick={() => setSearchOpen(true)}>
            <SearchIcon />
            搜尋並加入
          </Button>
        }
      />
      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        className="press flex h-12 items-center gap-3 rounded-xl border border-input bg-card px-4 text-left text-muted-foreground md:hidden"
      >
        <SearchIcon className="size-4.5" aria-hidden />
        搜尋股票代號或名稱
      </button>
      {symbols.length === 0 ? (
        <EmptyState
          title="自選清單是空的"
          description={
            <>
              在任何個股頁按「<StarIcon className="inline size-3.5 align-[-2px]" aria-hidden /> 加入自選」，就會出現在這裡。試試搜尋 2330 或 0056。
            </>
          }
          action={<Button onClick={() => setSearchOpen(true)}>搜尋股票</Button>}
        />
      ) : (
        <ul className="flex flex-col divide-y divide-hairline rounded-xl border bg-card">
          {symbols.map((s) => {
            const q = quotes.data?.find((x) => x.symbol === s)
            const i = names.data?.[s]
            return (
              <li key={s} className="flex items-center gap-3 px-4 py-3">
                <Link to="/stock/$symbol" params={{ symbol: s }} className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{i?.name ?? s}</span>
                  <span className="num block text-sm text-muted-foreground">{i?.code ?? s}</span>
                </Link>
                {q && i ? (
                  <span className="flex flex-col items-end">
                    <Price value={q.price} market={i.market} className="font-medium" />
                    <Pct value={q.change_pct} className="text-sm" />
                  </span>
                ) : (
                  <SkeletonLines rows={1} className="w-20" />
                )}
                <Button variant="ghost" size="icon-sm" aria-label={`從自選移除 ${i?.name ?? s}`} onClick={() => toggle(s)}>
                  <StarIcon className="fill-current text-amber" />
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ── AI 助理（M4） ─────────────────────────────────────────
export function AiPage() {
  const summary = useSummary()
  const top = summary.data?.allocation.by_industry[0]
  const asOf = summary.data ? formatDateShort(summary.data.as_of.slice(0, 10), false) : ""
  return (
    <Planned
      title="AI 助理"
      milestone="M4"
      lead="用中文問你的持股、績效或任何一檔股票。AI 只會查詢你有權限看的資料，回答裡的數字都附資料日期。"
      features={[
        ["自由提問", "「我今年賺多少？」「台積電現在貴嗎？」，在個股頁開啟會自動帶入那檔股票。"],
        ["一鍵持倉健檢", "集中度、產業與題材曝險、與大盤比較，整理成可以回頭比對的報告。"],
        ["引用資料", "每個數字都來自查詢結果，不讓模型憑記憶給數字。"],
      ]}
      now={
        <div className="flex flex-wrap gap-2">
          <Link to="/performance" className={buttonVariants({ variant: "outline" })}>看績效分析</Link>
          <Link to="/holdings" className={buttonVariants({ variant: "ghost" })}>看持股</Link>
        </div>
      }
    >
      <Panel title="回答的樣子" titleId="ai-sample" aside={<Chop tone="muted">示範</Chop>}>
        <div className="flex flex-col gap-3">
          <p className="ml-auto max-w-[85%] rounded-lg rounded-br-sm bg-primary px-3.5 py-2.5 text-md text-primary-foreground">我的持股集中在哪個產業？</p>
          <div className="max-w-[85%] rounded-lg rounded-bl-sm bg-muted px-3.5 py-2.5 text-md">
            {top ? (
              <p>
                依你目前的持股（資料日期 {asOf}），<span className="font-medium">{top.label}</span>佔市值{" "}
                <span className="num font-medium">{formatPercent(top.weight, { signed: false, decimals: 1 })}</span>，是比重最高的產業。
              </p>
            ) : (
              <SkeletonLines rows={2} />
            )}
            <p className="mt-2 text-xs text-muted-foreground">這段示範只用你的持股資料計算，沒有 AI 判斷。AI 分析僅供參考，不構成投資建議。</p>
          </div>
        </div>
      </Panel>
    </Planned>
  )
}

// ── 報告（M4） ────────────────────────────────────────────
export function ReportsPage() {
  return (
    <Planned
      title="報告"
      milestone="M4"
      lead="AI 產生的報告都會存在這裡，可以回頭比對每一次的判斷。"
      features={[
        ["盤後報告", "每個交易日收盤後：持股漲跌原因、法人動向、新聞重點，也可推播到 Telegram 或 Discord。"],
        ["持倉健檢", "按一下或每週自動：集中度、曝險、風險與調整建議。"],
        ["個股深度報告", "基本面、技術面、籌碼、新聞四位分析師研究後多空辯論，幾分鐘後通知你。"],
      ]}
    >
      <EmptyState title="還沒有報告" description="AI 功能上線後，第一份盤後報告會在下一個交易日收盤後出現在這裡。" />
    </Planned>
  )
}

// ── 群組（M5） ────────────────────────────────────────────
export function GroupsPage() {
  const shares: [string, string, boolean][] = [
    ["報酬率（只有 %）", "今日、本月、今年報酬率", true],
    ["持股清單與權重", "持有哪些股票、各佔幾 %，不含股數與金額", false],
    ["實際金額與損益", "市值、今日損益金額、總損益", false],
    ["交易動態", "「○○ 買進 2330」，可另外選擇是否附上價格與理由", false],
  ]
  return (
    <Planned
      title="群組"
      milestone="M5"
      lead="和家人朋友互相分享績效。每個人在每個群組自己決定分享什麼，預設只分享報酬率。"
      features={[
        ["排行榜", "今日、本月、今年報酬率排名，對照大盤與 0050。"],
        ["動態與留言", "對交易動態和排行留言、按表情。"],
        ["群組 AI 週報", "每週總結群組表現與共同持股，只使用成員開放的資料。"],
      ]}
    >
      <Panel title="你可以控制分享什麼" titleId="share-title" aside={<Chop tone="muted">預設值</Chop>}>
        <ul className="flex flex-col divide-y divide-hairline">
          {shares.map(([k, v, on]) => (
            <li key={k} className="flex items-center justify-between gap-4 py-3">
              <div>
                <p className="font-medium">{k}</p>
                <p className="text-md text-muted-foreground">{v}</p>
              </div>
              <Switch checked={on} disabled aria-label={`${k}（預設${on ? "開" : "關"}）`} />
            </li>
          ))}
        </ul>
      </Panel>
    </Planned>
  )
}

// ── 匯入（M3） ────────────────────────────────────────────
export function ImportPage() {
  const openTradeForm = useUi((s) => s.openTradeForm)
  const steps = ["上傳對帳單", "辨識券商", "預覽：新增、重複、可能有誤", "確認入帳", "對帳差異"]
  return (
    <Planned
      title="匯入對帳單"
      milestone="M3"
      lead="把券商的 Excel、CSV、PDF（含密碼保護）或截圖交給 Forliosa，辨識後由你逐筆確認才入帳。"
      features={[
        ["券商專屬解析", "先支援家人朋友實際使用的券商，需要先收集對帳單樣本。"],
        ["欄位對應精靈", "不支援的格式，可以自己把欄位對應到日期、代號、買賣別、數量、價格。"],
        ["AI 解析", "任何格式都能交給 AI 抽出交易，你逐筆確認後才入帳。"],
      ]}
      now={
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => openTradeForm()}>手動輸入目前持股</Button>
          <Link to="/transactions" className={buttonVariants({ variant: "outline" })}>逐筆記交易</Link>
        </div>
      }
    >
      <Panel title="匯入流程" titleId="import-steps">
        <ol className="grid gap-2 sm:grid-cols-5">
          {steps.map((s, i) => (
            <li key={s} className="flex items-start gap-2 text-md sm:flex-col">
              <span className="chop shrink-0 text-muted-foreground">{i + 1}</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-sm text-muted-foreground">原始檔加密存放，解析完成後預設 30 天自動刪除；PDF 密碼不會被保存。</p>
      </Panel>
    </Planned>
  )
}

// ── 手機「更多」 ──────────────────────────────────────────
export function MorePage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">更多</h1>
      <ul className="flex flex-col divide-y divide-hairline rounded-xl border bg-card">
        {MORE_ITEMS.map((item) => (
          <li key={item.to}>
            <Link to={item.to} className={cn("press flex min-h-13 items-center gap-3 px-4 py-3 active:bg-muted", isActivePath("", item.to) && "font-medium")}>
              <item.icon className="size-5 text-muted-foreground" aria-hidden />
              <span className="flex-1">{item.label}</span>
              {item.milestone && <span className="text-sm text-muted-foreground">{item.milestone} 推出</span>}
              <ChevronRightIcon className="size-4 text-muted-foreground" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
