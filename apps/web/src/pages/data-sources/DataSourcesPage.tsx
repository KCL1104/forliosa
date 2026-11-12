import { ArrowUpRightIcon } from "lucide-react"
import { useMemo } from "react"
import { api } from "@/api"
import { useAttributions } from "@/api/queries"
import type { AttributionDataset } from "@/api/types"
import { PageHeader } from "@/components/section"
import { ErrorState, SkeletonLines } from "@/components/states"

/**
 * 資料來源與授權：`GET /meta/attributions` 的每一個資料集，照後端給的完整顯名聲明列出
 * （政府資料開放授權條款第 1 版：沒有顯名「視為自始未取得授權」，所以文字不改寫）。
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

  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-10 px-5 pt-2 pb-10 md:px-8 lg:pt-10">
      <PageHeader
        title="資料來源與授權"
        description="行情、匯率、公司資料與公告只用可合法商用的政府開放資料，以及我們從這些資料自建的每日存檔。下面是每個資料集的顯名聲明。"
      />
      {q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : !a ? (
        <SkeletonLines rows={8} />
      ) : (
        <>
          <section aria-labelledby="ds-license" className="flex flex-col gap-2">
            <h2 id="ds-license" className="border-b border-rule pb-2 text-lg font-bold">
              授權條款
            </h2>
            {a.notice.map((n) => (
              <p key={n} className="max-w-prose text-md">
                <Linkified text={n} />
              </p>
            ))}
            {a.policy === "personal" && <p className="text-md text-ink-2">這個環境明確開啟了個人模式：標示「非商用」的來源只供個人使用。</p>}
          </section>

          {groups.map(([agency, rows]) => (
            <section key={agency} aria-labelledby={`ds-${agency}`} className="flex flex-col">
              <h2 id={`ds-${agency}`} className="flex items-baseline gap-2 border-b border-rule pb-2 text-lg font-bold">
                {agency}
                <span className="num text-sm font-normal text-ink-2">{rows.length} 個資料集</span>
              </h2>
              <ul>
                {rows.map((d) => (
                  <li key={d.key} className="grid gap-x-6 gap-y-1 border-b border-rule py-3 md:grid-cols-[minmax(0,1fr)_200px]">
                    <div className="min-w-0">
                      <p className="text-base">{d.attribution}</p>
                      <p className="mt-0.5 flex flex-wrap gap-x-3 text-sm text-ink-2">
                        <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline-offset-3 hover:text-ink hover:underline">
                          資料集網址
                          <ArrowUpRightIcon aria-hidden className="size-3.5" />
                          <span className="sr-only">（另開新視窗）</span>
                        </a>
                        {/* 政府資料開放授權條款已列在最上面；授權不同的資料集（例如非商用來源）才逐筆連結 */}
                        {d.license_url !== mainLicense && (
                          <a href={d.license_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 underline-offset-3 hover:text-ink hover:underline">
                            {d.license}
                            <ArrowUpRightIcon aria-hidden className="size-3.5" />
                            <span className="sr-only">（另開新視窗）</span>
                          </a>
                        )}
                        {!d.commercial && <span className="text-ink">非商用</span>}
                      </p>
                    </div>
                    <p className="text-sm text-ink-2 md:text-right">用在：{d.used_for}</p>
                  </li>
                ))}
              </ul>
            </section>
          ))}

          {a.not_used.length > 0 && (
            <section aria-labelledby="ds-not-used" className="flex flex-col gap-2">
              <h2 id="ds-not-used" className="border-b border-rule pb-2 text-lg font-bold">
                沒有使用的來源
              </h2>
              <ul className="flex max-w-prose list-disc flex-col gap-1 pl-5 text-md text-ink-2 marker:text-ctl">
                {a.not_used.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
              <p className="max-w-prose text-md text-ink-2">盤中走勢、上市股票的個股三大法人與美股報價需要付費授權，目前不提供；畫面上會說明為什麼沒有。</p>
            </section>
          )}

          <section aria-labelledby="ds-other" className="flex flex-col gap-2">
            <h2 id="ds-other" className="border-b border-rule pb-2 text-lg font-bold">
              其他
            </h2>
            <p className="max-w-prose text-md text-ink-2">
              你的交易、持股與定期定額是你自己記下的帳（標示為「本系統帳本」）。走勢圖使用 TradingView Lightweight Charts™（Apache-2.0）；字型為 Noto Sans TC 與霞鶩文楷 TC（SIL Open Font License 1.1）。
            </p>
            <p className="max-w-prose text-md text-ink-2">
              個股頁的「新聞報導」只列媒體的原標題、媒體名稱、時間與原文連結，不轉載內文或圖片。標題主要來自 The GDELT Project 的新聞索引，以及我們自己架設、只供系統內部使用的 SearXNG 元搜尋（只查新聞）；兩者合計太少時才用 AI 網路搜尋補充。SearXNG 會自動查詢 Bing、DuckDuckGo、Brave 等搜尋引擎，這些搜尋引擎的條款不允許自動查詢：這個風險由 Forliosa 的營運者承擔，被搜尋引擎擋下時就停止查詢，不會設法繞過。媒體要求下架時，我們會移除該媒體的標題。
            </p>
            <p className="max-w-prose text-md text-ink-2">
              個股頁的「法人觀點」不是授權的資料庫：有人按下查詢時，AI 才搜尋近期公開的媒體報導，列出機構、評等、目標價、日期與原文連結；同一檔當天共用一份，隔天刪除。這些是第三方意見，以原始報導為準，不是 Forliosa 的建議。
            </p>
            {api.kind === "mock" && <p className="max-w-prose text-md text-ink-2">目前沒有連到後端：這一頁的清單與畫面上的數字由瀏覽器內的模擬資料產生。</p>}
          </section>
        </>
      )}
    </div>
  )
}

/** 授權條款文字裡的網址變成連結 */
function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/\S+)/)
  return (
    <>
      {parts.map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer" className="underline underline-offset-3">
            {p}
          </a>
        ) : (
          p
        ),
      )}
    </>
  )
}
