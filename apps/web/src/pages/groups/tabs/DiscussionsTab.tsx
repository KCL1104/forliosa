import { Link } from "@tanstack/react-router"
import type { Group } from "@/api/types"
import { buttonVariants } from "@/components/ui/button"
import { TopicRows } from "@/pages/discussions/TopicRows"

/**
 * 群組的「討論」分頁：這個群組的主題（只有成員看得到）。「開新主題」預先選好這個群組。
 * 清單是和討論頁同一套格線列；群組名稱不重複寫在每一列。群組範圍沒有檢舉，由群組的擁有者與管理員刪除。
 */
export function DiscussionsTab({ group }: { group: Group }) {
  return (
    <section aria-labelledby="group-discussions-title" className="flex max-w-measure flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 id="group-discussions-title" className="sr-only">
          討論
        </h2>
        <p className="text-md text-ink-2">只有「{group.name}」的成員看得到。</p>
        <Link to="/discussions/new" search={{ scope: "group", group_id: group.id, from: "group" }} className={buttonVariants({ variant: "outline" })}>
          開新主題
        </Link>
      </div>
      <TopicRows
        filter={{ scope: "group", groupId: group.id }}
        origin={{ kind: "group", id: group.id, name: group.name }}
        signedIn
        showGroup={false}
        empty={{ title: "這個群組還沒有主題", description: "開一個主題，問問大家這個月怎麼配置。" }}
      />
    </section>
  )
}
