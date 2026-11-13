import { useNavigate } from "@tanstack/react-router"
import type { Topic } from "@/api/types"
import type { DiscussionsSearch, NewTopicSearch, TopicSearch } from "@/router"

/**
 * 從哪裡來的，就回到哪裡（主題頁與開新主題的麵包屑、「取消」、刪除主題之後）：
 * - 清單：回到討論清單，篩選與排序還在
 * - 群組的「討論」分頁：「← 群組名」
 * - 個股的「討論」分頁：「← 股票名」
 * 來源記在網址上（`router.tsx` 的 `TopicSearch`／`NewTopicSearch`），重新整理、另開分頁都還在。
 * 連結的樣子在 `OriginLink.tsx`。
 */
export type Origin =
  | { kind: "list"; search: DiscussionsSearch }
  | { kind: "group"; id: string; name: string }
  | { kind: "stock"; symbol: string; name: string }

const listOf = (search: DiscussionsSearch): Origin => ({ kind: "list", search: { scope: search.scope, group_id: search.group_id, sort: search.sort } })

/**
 * 主題頁的來源。`from=group`／`from=stock` 要等主題載入才知道名稱（群組名、股票名）：還在載入時回 null（麵包屑先留空位，不先寫「討論」再跳成別的）。
 * 對不起來的來源（主題不是群組的、沒有標記那檔股票、沒登入——個股頁要登入）一律回到清單。
 */
export function topicOrigin(search: TopicSearch, topic: Topic | undefined, opts: { signedIn: boolean; settled: boolean }): Origin | null {
  if (search.from === "group") {
    if (topic) return topic.scope === "group" && topic.group ? { kind: "group", id: topic.group.id, name: topic.group.name } : listOf({})
    return opts.settled ? listOf({}) : null
  }
  if (search.from === "stock" && search.symbol && opts.signedIn) {
    const tag = topic?.symbols.find((s) => s.symbol === search.symbol)
    if (topic) return tag ? { kind: "stock", symbol: tag.symbol, name: tag.name } : listOf({})
    return opts.settled ? listOf({}) : null
  }
  return listOf(search.from ? {} : search)
}

/**
 * 開新主題那一頁的來源。`from=group` 要等群組清單、`from=stock` 要等那檔股票查到才知道名稱：還沒回來時是 null。
 * 對不起來的（不在那個群組裡、查不到那檔股票）回到清單。
 */
export function newTopicOrigin(
  search: NewTopicSearch,
  groups: readonly { id: string; name: string }[] | undefined,
  stock: { data?: { symbol: string; name: string }; settled: boolean },
): Origin | null {
  if (search.from === "group") {
    if (!groups) return null
    const g = groups.find((x) => x.id === search.group_id)
    return g ? { kind: "group", id: g.id, name: g.name } : listOf({})
  }
  if (search.from === "stock" && search.symbol) {
    if (stock.data) return { kind: "stock", symbol: stock.data.symbol, name: stock.data.name }
    return stock.settled ? listOf({}) : null
  }
  return listOf(search)
}

/** 主題連結要帶的網址參數：從這個來源打開主題 */
export function topicSearchFrom(origin: Origin): TopicSearch {
  if (origin.kind === "group") return { from: "group" }
  if (origin.kind === "stock") return { from: "stock", symbol: origin.symbol }
  return origin.search
}

/** 回到來源（刪除主題之後）。`replace`：不留下已經不存在的那一頁 */
export function useGoToOrigin() {
  const navigate = useNavigate()
  return (origin: Origin, opts: { replace?: boolean } = {}) => {
    if (origin.kind === "group") return navigate({ to: "/groups/$groupId", params: { groupId: origin.id }, search: { tab: "discussions" }, ...opts })
    if (origin.kind === "stock") return navigate({ to: "/stock/$symbol", params: { symbol: origin.symbol }, search: { tab: "discussions" }, ...opts })
    return navigate({ to: "/discussions", search: origin.search, ...opts })
  }
}
