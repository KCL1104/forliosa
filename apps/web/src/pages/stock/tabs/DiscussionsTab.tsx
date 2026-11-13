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
    <section aria-labelledby="stock-discussions-title" className="flex max-w-[816px] flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="stock-discussions-title" className="text-xl font-bold">
          標記「{inst.name}」的主題
        </h2>
        <Link to="/discussions/new" search={{ symbol: inst.symbol }} className={buttonVariants({ variant: "outline" })}>
          開新主題
        </Link>
      </div>
      <TopicRows
        filter={{ scope: "all", symbol: inst.symbol }}
        signedIn
        empty={{ title: `還沒有人討論${inst.name}`, description: "開一個主題並標記這檔股票，就會出現在這裡。" }}
      />
    </section>
  )
}
