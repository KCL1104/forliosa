import { ArrowUpRightIcon, ChevronDownIcon } from "lucide-react"
import { Fragment, useMemo, useState } from "react"
import { api } from "@/api"
import { useAttributions } from "@/api/queries"
import type { AttributionDataset } from "@/api/types"
import { PageFrame } from "@/app/PageFrame"
import { PageHeader, Section } from "@/components/section"
import { ErrorState, SkeletonLines } from "@/components/states"
import { textAction } from "@/components/text-action"
import { cn } from "@/lib/utils"

/** 離開本站的連結（才用 ↗）：常駐 ctl 色底線、滑過變墨色 */
const EXTERNAL = "underline decoration-ctl underline-offset-3 hover:decoration-ink"
/** 句子裡的連結：觸控時上下各多 12px 的可按範圍（行內元素的上下內距不改變行高） */
const INLINE_TOUCH = "pointer-coarse:py-3"

/** 證交所「基本市況報導」：盤中的即時行情在那裡看（只是連結，本站不擷取） */
const TWSE_MIS_URL = "https://mis.twse.com.tw/"

/**
 * 資料來源與授權：`GET /meta/attributions` 的每一個資料集，照後端給的完整顯名聲明列出
 * （政府資料開放授權條款第 1 版：沒有顯名「視為自始未取得授權」，所以文字不改寫）。
 *
 * 資料集依提供機關分組，每一組是一個收合的區塊：收著時列出這個機關的資料集名稱（看得出用了哪些），
 * 展開是每個資料集的完整顯名聲明、資料集連結與用途——五十幾個資料集全部攤開，手機要捲一萬多 px。
 * 「報價」那一段固定在最上面：沒有盤中即時報價，價格是收盤後公布的收盤價。
 */
export function DataSourcesPage() {
  const q = useAttributions()
  const a = q.data
  const groups = useMemo(() => {
    const map = new Map<string, AttributionDataset[]>()
    for (const d of a?.datasets ?? []) map.set(d.agency, [...(map.get(d.agency) ?? []), d])
    return [...map.entries()]
  }, [a])
  const mainLicense = a?.datasets.find((d) => d.commercial)?.license_url
  // 展開的機關（預設全部收著）
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set())
  const allOpen = groups.length > 0 && groups.every(([agency]) => open.has(agency))
  const toggle = (agency: string) =>
    setOpen((cur) => {
      const next = new Set(cur)
      if (!next.delete(agency)) next.add(agency)
      return next
    })

  return (
    // 左緣和帳本相同；這一頁是長文，閱讀寬度限制在 816px（原本的版心）
    <PageFrame>
      <div className="flex max-w-measure flex-col gap-10">
        {/* 頁面標題下面不放副標；「只用哪些資料」這句是內容，放在授權條款的第一段 */}
        <PageHeader title="資料來源與授權" className="mb-0" />
        {q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !a ? (
          <SkeletonLines rows={8} />
        ) : (
          <>
            <Section title="報價" titleId="ds-quotes" bodyClassName="flex flex-col gap-2">
              <p className="max-w-prose text-md">
                Forliosa 沒有盤中即時報價。畫面上的股價都是收盤價：每個交易日收盤後由證交所與櫃買中心公布（通常在當天晚上到隔天清晨之間），公布之後才會更新。盤中看到的是上一個交易日的收盤價。
              </p>
              <p className="max-w-prose text-md">要合法取得盤中報價需要付費授權，目前沒有購買。想看盤中的價格，請到證交所的網站：</p>
              {/* 連結自己一行（觸控時 44px 高），不夾在句子中間 */}
              <p className="-mt-2 text-md">
                <a href={TWSE_MIS_URL} target="_blank" rel="noopener noreferrer" className={cn(EXTERNAL, "inline-flex min-h-9 items-center gap-0.5 pointer-coarse:min-h-11")}>
                  證交所「基本市況報導」
                  <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0" />
                  <span className="sr-only">（另開新視窗）</span>
                </a>
              </p>
            </Section>

            {/* 觸控時段落之間多一點：只有一行的段落裡的網址連結上下各有 12px 的可按範圍 */}
            <Section title="授權條款" titleId="ds-license" bodyClassName="flex flex-col gap-2 pointer-coarse:gap-3">
              <p className="max-w-prose text-md">行情、匯率、公司資料與公告只用可合法商用的政府開放資料，以及我們從這些資料自建的每日存檔。</p>
              {a.notice.map((n) => (
                // 網址只在 / . ? & = - _ 後面斷行（Linkified）；整段另外允許在放不下時斷開，長網址不會撐寬頁面
                <p key={n} className="max-w-prose text-md [overflow-wrap:anywhere]">
                  <Linkified text={n} />
                </p>
              ))}
              {a.policy === "personal" && <p className="text-md text-ink-2">這個環境明確開啟了個人模式：標示「非商用」的來源只供個人使用。</p>}
            </Section>

            <section aria-labelledby="ds-datasets" className="flex flex-col">
              <header className="flex min-h-11 flex-wrap items-end gap-x-3 gap-y-1 border-b border-print pb-2">
                <h2 id="ds-datasets" className="text-xl font-bold">
                  資料集
                </h2>
                <span className="num text-sm text-ink-2">
                  {groups.length} 個提供機關・{a.datasets.length} 個資料集
                </span>
                <button
                  type="button"
                  onClick={() => setOpen(allOpen ? new Set() : new Set(groups.map(([agency]) => agency)))}
                  className={cn(textAction, "ml-auto")}
                >
                  {allOpen ? "全部收合" : "全部展開"}
                </button>
              </header>
              {groups.map(([agency, rows]) => (
                <AgencyGroup key={agency} agency={agency} rows={rows} open={open.has(agency)} onToggle={() => toggle(agency)} mainLicense={mainLicense} />
              ))}
            </section>

            {a.not_used.length > 0 && (
              <Section title="沒有使用的來源" titleId="ds-not-used" bodyClassName="flex flex-col gap-2">
                <ul className="flex max-w-prose list-disc flex-col gap-1 pl-5 text-md text-ink-2 marker:text-ctl">
                  {a.not_used.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
                <p className="max-w-prose text-md text-ink-2">盤中走勢、上市股票的個股三大法人與美股報價需要付費授權，目前不提供；畫面上會說明為什麼沒有。</p>
              </Section>
            )}

            <Section title="其他" titleId="ds-other" bodyClassName="flex flex-col gap-2">
              <p className="max-w-prose text-md text-ink-2">
                你的交易、持股與定期定額是你自己記下的帳（標示為「本系統帳本」）。走勢圖使用 TradingView Lightweight Charts™（Apache-2.0）；字型為 Noto Sans TC（SIL Open Font License 1.1）與數位發展部全字庫正楷體（擇用 SIL Open Font License 1.1）。
              </p>
              <p className="max-w-prose text-md text-ink-2">
                個股頁的「新聞報導」只列媒體的原標題、媒體名稱、時間與原文連結，不轉載內文或圖片。標題主要來自 The GDELT Project 的新聞索引，以及我們自己架設、只供系統內部使用的 SearXNG 元搜尋（只查新聞）；兩者合計太少時才用 AI 網路搜尋補充。SearXNG 會自動查詢 Bing、DuckDuckGo、Brave 等搜尋引擎，這些搜尋引擎的條款不允許自動查詢：這個風險由 Forliosa 的營運者承擔，被搜尋引擎擋下時就停止查詢，不會設法繞過。媒體要求下架時，我們會移除該媒體的標題。
              </p>
              <p className="max-w-prose text-md text-ink-2">
                個股頁的「法人觀點」不是授權的資料庫：有人按下查詢時，AI 才搜尋近期公開的媒體報導，列出機構、評等、目標價、日期與原文連結；同一檔當天共用一份，隔天刪除。這些是第三方意見，以原始報導為準，不是 Forliosa 的建議。
              </p>
              {api.kind === "mock" && <p className="max-w-prose text-md text-ink-2">目前沒有連到伺服器：這一頁的清單與畫面上的數字由瀏覽器內的模擬資料產生。</p>}
            </Section>
          </>
        )}
      </div>
    </PageFrame>
  )
}

/**
 * 一個提供機關的資料集：標題列是開關（整列可以按，`aria-expanded`）。
 * 收著：一段資料集名稱（淡墨，「、」分隔）。展開：每個資料集一列——完整顯名聲明（資料集名稱就是連到資料集的連結）＋用途。
 */
function AgencyGroup({ agency, rows, open, onToggle, mainLicense }: { agency: string; rows: AttributionDataset[]; open: boolean; onToggle: () => void; mainLicense?: string }) {
  const headId = `ds-${agency}`
  const panelId = `ds-list-${agency}`
  return (
    <section aria-labelledby={headId} className="border-b border-rule">
      <h3 id={headId}>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
          className="group flex min-h-12 w-full items-center gap-x-3 py-2 text-left focus-visible:-outline-offset-2"
        >
          <span className="min-w-0 flex-1 text-base font-bold lg:text-lg">{agency}</span>
          <span className="num shrink-0 text-sm font-normal text-ink-2">{rows.length} 個資料集</span>
          <ChevronDownIcon aria-hidden className={cn("size-5 shrink-0 text-ink-2 transition-transform duration-150 group-hover:text-ink motion-reduce:transition-none", open && "rotate-180")} />
        </button>
      </h3>
      {!open && <p className="-mt-1 pb-3 text-md text-ink-2">{rows.map((d) => d.dataset).join("、")}</p>}
      <ul id={panelId} hidden={!open}>
        {rows.map((d) => (
          <li key={d.key} className="grid gap-x-6 gap-y-1 border-t border-rule py-3 md:grid-cols-[minmax(0,1fr)_200px]">
            <div className="min-w-0">
              <p className="text-base">
                <Attribution d={d} />
              </p>
              {(d.license_url !== mainLicense || !d.commercial) && (
                <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-ink-2 pointer-coarse:mt-3">
                  {/* 政府資料開放授權條款已列在最上面；授權不同的資料集（例如非商用來源）才逐筆連結 */}
                  {d.license_url !== mainLicense && (
                    <a href={d.license_url} target="_blank" rel="noopener noreferrer" className={cn(EXTERNAL, "inline-flex items-center gap-0.5 hover:text-ink pointer-coarse:min-h-11")}>
                      {d.license}
                      <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0" />
                      <span className="sr-only">（另開新視窗）</span>
                    </a>
                  )}
                  {!d.commercial && <span className="text-ink">非商用</span>}
                </p>
              )}
            </div>
            {/* 觸控時這一行不接收點按：上面資料集連結往下的可按範圍（合計 44px）落在這裡 */}
            <p className="text-sm text-ink-2 md:text-right pointer-coarse:pointer-events-none">用在：{d.used_for}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * 完整顯名聲明（文字照後端給的，不改寫）；聲明裡的資料集名稱就是連到那個資料集的連結（離開本站，所以有 ↗）。
 * 聲明裡找不到資料集名稱時（格式不同的來源），聲明照原文，後面另外接一個以資料集名稱為文字的連結。
 */
function Attribution({ d }: { d: AttributionDataset }) {
  const link = (
    // 「另開新視窗」寫在 aria-label：聲明的文字（textContent）保持後端給的原文，中間不插別的字
    <a href={d.url} target="_blank" rel="noopener noreferrer" aria-label={`${d.dataset}（資料集，另開新視窗）`} className={cn(EXTERNAL, INLINE_TOUCH)}>
      {d.dataset}
      <ArrowUpRightIcon aria-hidden className="ml-0.5 inline size-3.5 align-[-0.125em]" />
    </a>
  )
  const at = d.dataset ? d.attribution.indexOf(d.dataset) : -1
  if (at < 0) {
    return (
      <>
        <Linkified text={d.attribution} /> {link}
      </>
    )
  }
  return (
    <>
      {d.attribution.slice(0, at)}
      {link}
      <Linkified text={d.attribution.slice(at + d.dataset.length)} />
    </>
  )
}

/** 授權條款文字裡的網址變成連結（網址在全形標點前結束，例如「（https://…）」的右括號不算網址） */
const URL_RE = /(https?:\/\/[^\s（）「」『』〈〉，。；、]+)/
function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE)
  return (
    <>
      {parts.map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noopener noreferrer" className={cn(EXTERNAL, INLINE_TOUCH)}>
            <BreakableUrl url={p} />
            <span className="sr-only">（另開新視窗）</span>
          </a>
        ) : (
          p
        ),
      )}
    </>
  )
}

/** 網址只在分隔符號（/ . ? & = # - _）後面可以斷行，不在字的中間斷 */
function BreakableUrl({ url }: { url: string }) {
  const pieces = url.split(/(?<=[/.?&=#_-])(?=[^/])/)
  return (
    <>
      {pieces.map((piece, i) => (
        <Fragment key={i}>
          {i > 0 && <wbr />}
          {piece}
        </Fragment>
      ))}
    </>
  )
}
