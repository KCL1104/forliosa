import { usePageTitle } from "@/app/page-title"
import { DemoTag } from "@/components/section"
import { ABOUT_SHORT } from "@/lib/about"
import { LegalLinks } from "@/pages/legal/LegalLinks"
import { DraftSpecimen, LedgerSpecimen, StockSpecimen } from "./specimens"

/**
 * 沒登入的首頁（`/`）：簡短的介紹頁。登入後同一個網址是帳本（`app/RootLayout.tsx`）。
 * 只有四樣東西：外殼的頁首（字標、討論、登入——`PublicShell`）、標題「股票帳本」、三個用示範資料畫的畫面、頁尾的條款連結。
 * 沒有副標、賣點清單、標語或第二顆登入按鈕：產品是什麼，由三個畫面自己交代。
 *
 * 三個畫面是一張印好的表：桌面三欄並排，三個標題坐在同一條印刷線上（欄與欄之間不留縫，線是連續的）；
 * 手機一欄直排，每個標題下面各一條印刷線。每一欄的標題右邊都標「示範資料」。
 */
const SPECIMENS: { title: string; label: string; body: React.ReactNode }[] = [
  { title: "帳本", label: "示範畫面：帳本。上面是總資產、今日漲跌與總損益，下面一列一檔持股，寫著股數、收盤價與當天漲跌。", body: <LedgerSpecimen /> },
  { title: "個股", label: "示範畫面：個股頁。股票名稱、收盤價與漲跌，下面是持有的股數、均價與未實現損益，再下面是收盤價的走勢圖。", body: <StockSpecimen /> },
  { title: "問 AI", label: "示範畫面：問 AI。輸入「買 0050 2 張 52.4」，出現一張算好稅費的草稿，下面是簽名格。", body: <DraftSpecimen /> },
]

export function HomePage() {
  usePageTitle()
  return (
    <div className="page-frame px-5 pt-8 pb-10 md:px-8 lg:pt-14 xl:px-14 xl:pb-14">
      <h1 className="text-3xl font-bold tracking-[-0.01em] lg:text-4xl">{ABOUT_SHORT}</h1>

      <div className="mt-8 grid gap-y-12 lg:grid-cols-3">
        {SPECIMENS.map((s) => (
          <figure key={s.title} className="group/specimen flex min-w-0 flex-col max-lg:max-w-lg">
            {/* 欄與欄之間的留白放在欄裡面（第一欄右邊、最後一欄左邊各 2rem，中間那一欄左右各 1rem）：三欄的內容一樣寬，標題下的印刷線連成一條 */}
            <figcaption className="flex min-h-11 items-end gap-3 border-b border-print pb-2 lg:px-4 lg:group-first/specimen:pr-8 lg:group-first/specimen:pl-0 lg:group-last/specimen:pr-0 lg:group-last/specimen:pl-8">
              <h2 className="text-xl font-bold">{s.title}</h2>
              <DemoTag className="mb-1 ml-auto" />
              <span className="sr-only">{s.label}</span>
            </figcaption>
            <div aria-hidden className="pointer-events-none flex flex-1 flex-col pt-5 select-none lg:px-4 lg:group-first/specimen:pr-8 lg:group-first/specimen:pl-0 lg:group-last/specimen:pr-0 lg:group-last/specimen:pl-8">
              {s.body}
            </div>
          </figure>
        ))}
      </div>

      <footer className="mt-12 flex flex-wrap gap-x-5 border-t border-rule pt-3 text-sm lg:mt-16">
        <LegalLinks className="inline-flex min-h-11 items-center text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink" />
      </footer>
    </div>
  )
}
