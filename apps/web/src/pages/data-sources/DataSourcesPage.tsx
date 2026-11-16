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
import { usePageTitle } from "@/app/page-title"

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
 * 「報價」那一段固定在最上面：沒有盤中即時報價，價格是收盤後公布的收盤價；上市、上櫃平常幾點更新（實測的時間）。
 * 美股收盤價（Databento，`databento-equs/` 的資料集）有開的時候，報價與授權條款各多一段美股的說明。
 */
export function DataSourcesPage() {
  usePageTitle("資料來源與授權")
  const q = useAttributions()
  const a = q.data
  const groups = useMemo(() => {
    const map = new Map<string, AttributionDataset[]>()
    for (const d of a?.datasets ?? []) map.set(d.agency, [...(map.get(d.agency) ?? []), d])
    return [...map.entries()]
  }, [a])
  const mainLicense = a?.datasets.find((d) => d.commercial)?.license_url
  // 美股收盤價：後端只在美股收盤價有開的時候列出這個資料集
  const usCloses = !!a?.datasets.some((d) => d.key.startsWith("databento-equs/"))
  // 上市收盤價下午就進來：證交所在政府資料開放平臺登記的下載網址（產品負責人 2026-11-16）開著時，後端列出 `twse-opendata/` 的資料集
  const twseAfternoon = !!a?.datasets.some((d) => d.key.startsWith("twse-opendata/"))
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
              <p className="max-w-prose text-base">
                Forliosa 的股價都是收盤價，沒有盤中報價。證交所與櫃買中心收盤後公布當天的收盤價，我們拿到就更新；公布前看到的是上一個交易日的收盤價。平常大約是：
              </p>
              {/* 什麼時候更新（2026-11 實測；兩個交易所都沒有公布固定的時間）：上市下午那一批只在證交所的下載網址開著時才有 */}
              <ul aria-label="收盤價平常什麼時候更新" className="flex max-w-prose list-disc flex-col gap-1 pl-5 text-base marker:text-ctl">
                {/* 下午那一批不一定拿得到（2026-11-16 實測：指數檔被擋過一次），拿不到時是晚上那一批：照實寫 */}
                <li className="num">
                  {twseAfternoon ? "上市：下午 2:00–2:30（證交所在政府資料開放平臺登記的下載網址）；下午拿不到時晚上 8:30–11:45" : "上市：晚上 8:30–11:45，晚的時候隔天清晨 5:20–5:45"}
                </li>
                <li className="num">上櫃：晚上 8:30–11:45，少數日子到半夜 1:30</li>
              </ul>
              <p className="max-w-prose text-base">
                這是我們量到的時間，交易所沒有公布固定的時間；還沒更新時，帳本與個股頁會寫預計幾點更新。晚上先進來的收盤價沒有開盤、最高、最低與成交量，官方的完整資料進來後補上（上櫃晚上 11:30 左右，上市隔天清晨 5:30 左右）。
              </p>
              <p className="max-w-prose text-base">盤中報價要付費授權，Forliosa 沒有買。想看盤中的價格，請到證交所的網站：</p>
              {/* 連結自己一行（觸控時 44px 高），不夾在句子中間 */}
              <p className="-mt-2 text-base">
                <a href={TWSE_MIS_URL} target="_blank" rel="noopener noreferrer" className={cn(EXTERNAL, "inline-flex min-h-9 items-center gap-0.5 pointer-coarse:min-h-11")}>
                  證交所「基本市況報導」
                  <ArrowUpRightIcon aria-hidden className="size-3.5 shrink-0" />
                  <span className="sr-only">（另開新視窗）</span>
                </a>
              </p>
              {/* 美股收盤價有開時：美股的日期、更新時間與哪些美股有收盤價 */}
              {usCloses && (
                <p className="max-w-prose text-base">
                  美股是紐約的收盤價，日期寫紐約的交易日。美股收盤一小時後開始更新，大約是台北時間清晨 6 點（美國夏令時間清晨 5 點）。只有有人持有或觀察的美股才有收盤價；剛加入的大約 10 分鐘內補上 2024 年 7 月以來的收盤價。
                </p>
              )}
            </Section>

            {/* 觸控時段落之間多一點：只有一行的段落裡的網址連結上下各有 12px 的可按範圍 */}
            <Section title="授權條款" titleId="ds-license" bodyClassName="flex flex-col gap-2 pointer-coarse:gap-3">
              {/* 跟著資料走：正式環境開了 Yahoo 的歷史日線回補時，不能說「都來自政府開放資料」（2026-11-14 第七次評分） */}
              <p className="max-w-prose text-base">
                {usCloses ? "台股行情" : "行情"}、匯率、公司資料與公告來自政府開放資料，以及我們每天從這些資料存下來的紀錄。
                {a.datasets.some((d) => d.key === "yahoo-history") && "走勢圖裡較早的日線來自 Yahoo Finance，不是官方資料，也沒有轉載授權。"}
              </p>
              {usCloses && (
                <p className="max-w-prose text-base">
                  美股的收盤價來自 Databento（Nasdaq NLS Plus 的官方合併收盤），從 2024 年 7 月開始，是沒有還原股票分割與股利的原始價格。
                </p>
              )}
              {a.notice.map((n) => (
                // 網址只在 / . ? & = - _ 後面斷行（Linkified）；整段另外允許在放不下時斷開，長網址不會撐寬頁面
                <p key={n} className="max-w-prose text-base [overflow-wrap:anywhere]">
                  <Linkified text={n} />
                </p>
              ))}
              {a.policy === "personal" && <p className="text-base">這個環境明確開啟了個人模式：標示「非商用」的來源只供個人使用。</p>}
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
                <ul className="flex max-w-prose list-disc flex-col gap-1 pl-5 text-base marker:text-ctl">
                  {a.not_used.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
                <p className="max-w-prose text-base">盤中走勢、上市股票的逐檔三大法人{usCloses ? "" : "、美股報價"}要付費授權，Forliosa 沒有買。</p>
              </Section>
            )}

            <Section title="其他" titleId="ds-other" bodyClassName="flex flex-col gap-2">
              <p className="max-w-prose text-base">
                你的交易、持股與定期定額是你自己記的帳（來源標示為「帳本紀錄」）。走勢圖使用 TradingView Lightweight Charts™（Apache-2.0）；字型為 Noto Sans TC（SIL Open Font License 1.1）。
              </p>
              <p className="max-w-prose text-base">
                個股頁的「新聞報導」只列原標題、媒體名稱、時間與原文連結，不轉載內文或圖片。標題來自 The GDELT Project 的新聞索引和我們自架的 SearXNG（只查新聞），兩者太少時用 AI 搜尋補。SearXNG 被搜尋引擎擋下時就停止查詢，不會設法繞過。媒體要求下架時，我們會移除該媒體的標題。
              </p>
              <p className="max-w-prose text-base">
                個股頁的「法人觀點」來自媒體報導：有人按查詢時，AI 搜尋近期的公開報導，列出機構、評等、目標價、日期與原文連結。同一檔當天共用一份，隔天刪除。這些是第三方意見，以原始報導為準，不是 Forliosa 的建議。
              </p>
              {api.kind === "mock" && <p className="max-w-prose text-base">沒有連到伺服器：這一頁的清單與畫面上的數字都是示範資料。</p>}
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
      {/* 同一個資料集有兩個網址（上市個股日成交資訊：OpenAPI 與證交所在政府資料開放平臺登記的下載網址）時只列一次 */}
      {!open && <p className="-mt-1 pb-3 text-md text-ink-2">{[...new Set(rows.map((d) => d.dataset))].join("、")}</p>}
      <ul id={panelId} hidden={!open}>
        {rows.map((d) => (
          <li key={d.key} className="grid gap-x-6 gap-y-1 border-t border-rule py-3 md:grid-cols-[minmax(0,1fr)_200px]">
            <div className="min-w-0">
              <p className="text-base">
                <Attribution d={d} twin={rows.some((o) => o !== d && o.dataset === d.dataset)} />
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
function Attribution({ d, twin = false }: { d: AttributionDataset; twin?: boolean }) {
  // 同一組裡有同名的資料集（同一份資料的兩個網址）：報讀時多唸網站，兩個連結聽得出不同
  const host = twin ? hostOf(d.url) : ""
  const link = (
    // 「另開新視窗」寫在 aria-label：聲明的文字（textContent）保持後端給的原文，中間不插別的字
    <a href={d.url} target="_blank" rel="noopener noreferrer" aria-label={`${d.dataset}（${host ? `${host}，` : ""}資料集，另開新視窗）`} className={cn(EXTERNAL, INLINE_TOUCH)}>
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

function hostOf(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return ""
  }
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
