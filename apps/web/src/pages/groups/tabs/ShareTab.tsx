import { toast } from "sonner"
import { usePutShare } from "@/api/sharing-queries"
import { ApiError, type Group, type ShareSettings } from "@/api/types"
import { ShareToggles } from "../ShareToggles"

/**
 * 我在這個群組的分享：六個開關，改了立即生效（關掉的內容其他人馬上看不到，包括過去的週報與動態）。
 * 每個群組各自設定，不影響其他群組。
 */
export function ShareTab({ group }: { group: Group }) {
  const put = usePutShare(group.id)
  const save = (next: ShareSettings) =>
    put.mutate(next, {
      onError: (err) => toast.error("分享設定沒有存到，已還原", { description: err instanceof ApiError ? err.message : "請檢查網路後再試一次。" }),
    })
  return (
    <section aria-labelledby="share-title" className="max-w-2xl">
      <h2 id="share-title" className="text-xl font-bold">
        我在「{group.name}」分享的內容
      </h2>
      <p className="mt-1 mb-4 text-base text-ink">關掉的內容，其他成員馬上看不到，過去的週報與動態也是。只影響這個群組。</p>
      <ShareToggles value={group.my_share} onChange={save} pushTargets={group.push_targets} pushAutoOff={group.my_role !== "owner"} />
    </section>
  )
}
