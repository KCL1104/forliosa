import { inText } from "@/lib/cjk"
import { Link } from "@tanstack/react-router"
import type { InstrumentDetail } from "@/api/types"
import { buttonVariants } from "@/components/ui/button"
import { TopicRows } from "@/pages/discussions/TopicRows"

/**
 * 個股的「討論」分頁：標記了這檔股票的主題——公開的，加上我的群組裡的（`scope=all`）。
 * 「開新主題」預先標記這一檔。清單是和討論頁同一套格線列。
 */
export function DiscussionsTab({ inst }: { inst: InstrumentDetail }) {
  return (
    // 個股頁的每個分頁都撐滿這一頁的欄寬：這裡不另外限寬，右緣和上面的報價、分頁列、下面的資料來源是同一條
    <section aria-labelledby="stock-discussions-title" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="stock-discussions-title" className="text-xl font-bold">
          標記「{inst.name}」的主題
        </h2>
        <Link to="/discussions/new" search={{ symbol: inst.symbol, from: "stock" }} className={buttonVariants({ variant: "outline" })}>
          開新主題
        </Link>
      </div>
      <TopicRows
        filter={{ scope: "all", symbol: inst.symbol }}
        origin={{ kind: "stock", symbol: inst.symbol, name: inst.name }}
        signedIn
        empty={{ title: `還沒有人討論${inText(inst.name, "end")}` }}
      />
    </section>
  )
}
