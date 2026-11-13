import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query"
import { deleteLater } from "@/lib/delete-later"
import { api } from "./index"
import { qk } from "./queries"
import {
  REACTION_EMOJIS,
  type DiscussionTarget,
  type ModerationAction,
  type Paged,
  type Reaction,
  type ReactionEmoji,
  type Reply,
  type ReportInput,
  type SuspensionDays,
  type Topic,
  type TopicInput,
  type TopicListScope,
  type TopicSort,
} from "./types"

/**
 * 討論串的查詢與動作（docs/api-contract.md「討論串（2026-11-13）」）。全部放在 `["discussions", …]` 底下：
 * 發言、刪除、隱藏、改公開暱稱之後整組重新抓，作者名稱、回覆數與 `can_*` 都以伺服器為準。
 * 表情是例外：按下立刻反映（樂觀更新），失敗時還原。刪除也是：畫面先拿掉、可以復原，通知結束才送出。
 */
export interface TopicListFilter {
  scope: TopicListScope
  /** 只有 scope=group 時有效（而且必填） */
  groupId?: string
  symbol?: string
  sort?: TopicSort
}

export const TOPIC_PAGE_SIZE = 30
export const REPLY_PAGE_SIZE = 50

export const dk = {
  all: ["discussions"] as const,
  lists: ["discussions", "topics"] as const,
  topics: (f: TopicListFilter) => ["discussions", "topics", f.scope, f.groupId ?? "", f.symbol ?? "", f.sort ?? "active"] as const,
  topic: (id: string) => ["discussions", "topic", id] as const,
  replies: (id: string) => ["discussions", "topic", id, "replies"] as const,
  adminReports: (status: "open" | "resolved") => ["discussions", "admin", "reports", status] as const,
  suspensions: ["discussions", "admin", "suspensions"] as const,
}

const no4xxRetry = (n: number, e: unknown) => !(e as { status?: number }).status?.toString().startsWith("4") && n < 1

// ── 清單、主題、回覆 ───────────────────────────────────────
/** 主題清單（看更多＝下一頁）。公開範圍不用登入；`all`／`group` 要登入，沒登入時用 `enabled` 關掉 */
export function useTopics(filter: TopicListFilter, enabled = true) {
  return useInfiniteQuery({
    enabled,
    queryKey: dk.topics(filter),
    queryFn: ({ pageParam }) =>
      api.listTopics({ scope: filter.scope, group_id: filter.groupId, symbol: filter.symbol, sort: filter.sort ?? "active", limit: TOPIC_PAGE_SIZE, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    // 換篩選或排序：新的清單回來之前先留著原本的列，不閃成骨架
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: no4xxRetry,
  })
}
export function useTopic(id: string) {
  return useQuery({ queryKey: dk.topic(id), queryFn: () => api.getTopic(id), staleTime: 15_000, retry: no4xxRetry })
}
/** 回覆（舊到新；看更多＝比較新的下一頁） */
export function useReplies(topicId: string, enabled = true) {
  return useInfiniteQuery({
    enabled,
    queryKey: dk.replies(topicId),
    queryFn: ({ pageParam }) => api.listReplies(topicId, { limit: REPLY_PAGE_SIZE, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 15_000,
    retry: no4xxRetry,
  })
}

// ── 發言與刪除 ─────────────────────────────────────────────
export function useCreateTopic() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TopicInput) => api.createTopic(body),
    onSuccess: (topic) => {
      qc.setQueryData(dk.topic(topic.id), topic)
      void qc.invalidateQueries({ queryKey: dk.lists })
    },
  })
}
export function useCreateReply(topicId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => api.createReply(topicId, { body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: dk.topic(topicId) })
      void qc.invalidateQueries({ queryKey: dk.lists })
    },
  })
}

/**
 * 刪除回覆、刪除主題：可以復原（`lib/delete-later.ts`）——畫面上立刻拿掉、通知附「復原」，通知結束才送出 `DELETE`；
 * 頁面先被關掉或藏起來就當下送出（keepalive）。失敗時放回原位並通知。
 * 刪掉之後：回覆 → 重新讀這個主題（回覆數、最後回覆時間）與清單；主題 → 丟掉它的快取、重新讀清單。
 */
export function useDeleteWithUndo() {
  const qc = useQueryClient()
  return {
    reply: (topicId: string, replyId: string) =>
      deleteLater({
        key: `reply:${replyId}`,
        title: "已刪除回覆",
        failed: "回覆沒有刪除，已經放回原位",
        send: (opts) => api.deleteReply(replyId, opts),
        onDeleted: () => Promise.all([qc.invalidateQueries({ queryKey: dk.topic(topicId) }), qc.invalidateQueries({ queryKey: dk.lists })]),
      }),
    topic: (topic: Pick<Topic, "id" | "reply_count">) =>
      deleteLater({
        key: `topic:${topic.id}`,
        title: "已刪除主題",
        description: topic.reply_count > 0 ? `底下的 ${topic.reply_count} 則回覆也一起刪除了。` : undefined,
        failed: "主題沒有刪除，已經放回原位",
        send: (opts) => api.deleteTopic(topic.id, opts),
        onDeleted: () => {
          qc.removeQueries({ queryKey: dk.topic(topic.id) })
          return qc.invalidateQueries({ queryKey: dk.lists })
        },
      }),
  }
}

// ── 表情（樂觀更新） ───────────────────────────────────────
/** 按下或收回一個表情之後的清單：順序照固定的六個表情，數到 0 的拿掉 */
export function toggleReaction(reactions: Reaction[], emoji: ReactionEmoji, on: boolean): Reaction[] {
  return REACTION_EMOJIS.flatMap((e) => {
    const r = reactions.find((x) => x.emoji === e)
    if (e !== emoji) return r ? [r] : []
    // 已經是這個狀態（重複按）：計數不變
    const count = (r?.count ?? 0) + (on === !!r?.mine ? 0 : on ? 1 : -1)
    return count > 0 ? [{ emoji: e, count, mine: on }] : []
  })
}

/**
 * 表情：`PUT`／`DELETE` 回 204、沒有內容，所以畫面自己更新——按下那一刻就改快取裡的主題或那一則回覆，
 * 失敗時還原；這個主題的表情都送完之後再向伺服器讀一次，計數以伺服器為準。
 */
export function useToggleDiscussionReaction(topicId: string) {
  const qc = useQueryClient()
  const mutationKey = ["discussions", "reaction", topicId] as const
  return useMutation({
    mutationKey,
    mutationFn: ({ target, emoji, on }: { target: DiscussionTarget; emoji: ReactionEmoji; on: boolean }) =>
      on ? api.addDiscussionReaction({ target, emoji }) : api.removeDiscussionReaction(target, emoji),
    onMutate: async ({ target, emoji, on }) => {
      // 進行中的讀取回來會蓋掉樂觀更新：先取消
      await qc.cancelQueries({ queryKey: dk.topic(topicId) })
      const topic = qc.getQueryData<Topic>(dk.topic(topicId))
      const replies = qc.getQueryData<InfiniteData<Paged<Reply>, string | null>>(dk.replies(topicId))
      if (target === `topic:${topicId}`) {
        qc.setQueryData<Topic>(dk.topic(topicId), (t) => (t ? { ...t, reactions: toggleReaction(t.reactions, emoji, on) } : t))
      } else {
        qc.setQueryData<InfiniteData<Paged<Reply>, string | null>>(dk.replies(topicId), (data) =>
          data && {
            ...data,
            pages: data.pages.map((p) => ({
              ...p,
              items: p.items.map((r) => (`reply:${r.id}` === target ? { ...r, reactions: toggleReaction(r.reactions, emoji, on) } : r)),
            })),
          },
        )
      }
      return { topic, replies }
    },
    onError: (_err, _vars, ctx) => {
      if (!ctx) return
      // 還有別的表情在送就不整份還原（會把那一個也一起還原）；最後一個結束時重新讀取
      if (qc.isMutating({ mutationKey }) > 1) return
      qc.setQueryData(dk.topic(topicId), ctx.topic)
      qc.setQueryData(dk.replies(topicId), ctx.replies)
    },
    onSettled: () => {
      if (qc.isMutating({ mutationKey }) <= 1) void qc.invalidateQueries({ queryKey: dk.topic(topicId) })
    },
  })
}

// ── 檢舉、公開暱稱 ─────────────────────────────────────────
export function useReportDiscussion() {
  return useMutation({ mutationFn: (body: ReportInput) => api.reportDiscussion(body) })
}
export function useSetPublicName() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.setPublicName(name),
    onSuccess: (user) => {
      qc.setQueryData(qk.me, user)
      // 改名後舊貼文顯示新暱稱
      void qc.invalidateQueries({ queryKey: dk.all })
    },
  })
}

// ── 站方管理 ───────────────────────────────────────────────
export function useAdminReports(status: "open" | "resolved", enabled = true) {
  return useInfiniteQuery({
    enabled,
    queryKey: dk.adminReports(status),
    queryFn: ({ pageParam }) => api.listAdminReports({ status, limit: 30, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 15_000,
    retry: no4xxRetry,
  })
}
export function useSuspensions(enabled = true) {
  return useQuery({ enabled, queryKey: dk.suspensions, queryFn: () => api.listSuspensions(), staleTime: 15_000, retry: no4xxRetry })
}
/** 隱藏、取消隱藏、不處理：清單、主題頁與管理頁一起重新抓 */
export function useModerate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { target: DiscussionTarget; action: ModerationAction }) => api.moderateDiscussion(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: dk.all }),
  })
}
export function useCreateSuspension() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { target: DiscussionTarget; days: SuspensionDays; reason?: string }) => api.createSuspension(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: dk.suspensions }),
  })
}
export function useLiftSuspension() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.liftSuspension(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: dk.suspensions }),
  })
}
