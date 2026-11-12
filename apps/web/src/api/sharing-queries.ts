import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./index"
import { qk } from "./queries"
import type {
  ChannelNotify,
  CommentTarget,
  DelegationInput,
  Group,
  InviteInput,
  LeaderboardPeriod,
  ReactionEmoji,
  ShareSettings,
} from "./types"

/**
 * 分享（M5）的查詢與動作。所有群組資料放在 `["groups", id, …]` 底下：改了分享設定、留言、表情時整組重新抓，
 * 投影由伺服器每次重新套用，前端不自己推算別人看得到什麼。
 */
export const sk = {
  providers: ["auth", "providers"] as const,
  delegations: ["delegations"] as const,
  candidates: ["delegations", "candidates"] as const,
  groups: ["groups"] as const,
  group: (id: string) => ["groups", id] as const,
  share: (id: string) => ["groups", id, "share"] as const,
  leaderboard: (id: string, period: LeaderboardPeriod) => ["groups", id, "leaderboard", period] as const,
  holdings: (id: string) => ["groups", id, "holdings"] as const,
  shared: (id: string, userId: string) => ["groups", id, "shared", userId] as const,
  feed: (id: string, userId?: string) => ["groups", id, "feed", userId ?? "all"] as const,
  comments: (id: string, target: CommentTarget) => ["groups", id, "comments", target] as const,
  digests: (id: string) => ["groups", id, "digests"] as const,
  channels: (id: string) => ["groups", id, "channels"] as const,
  invites: (id: string) => ["groups", id, "invites"] as const,
  invite: (token: string) => ["invite", token] as const,
}

const no4xxRetry = (n: number, e: unknown) => !(e as { status?: number }).status?.toString().startsWith("4") && n < 1

// ── 登入與個人資料 ─────────────────────────────────────────
export function useAuthProviders() {
  return useQuery({ queryKey: sk.providers, queryFn: () => api.getAuthProviders(), staleTime: 10 * 60_000, retry: no4xxRetry })
}
export function useUpdateMe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (display_name: string) => api.updateMe({ display_name }),
    onSuccess: (user) => {
      qc.setQueryData(qk.me, user)
      // 群組裡顯示的就是這個名稱
      void qc.invalidateQueries({ queryKey: sk.groups })
      void qc.invalidateQueries({ queryKey: sk.delegations })
    },
  })
}

// ── 授權查看 ───────────────────────────────────────────────
export function useDelegations() {
  return useQuery({ queryKey: sk.delegations, queryFn: () => api.listDelegations(), staleTime: 30_000 })
}
export function useDelegationCandidates(enabled = true) {
  return useQuery({ enabled, queryKey: sk.candidates, queryFn: () => api.listDelegationCandidates(), staleTime: 30_000 })
}
function useInvalidateDelegations() {
  const qc = useQueryClient()
  return () => void qc.invalidateQueries({ queryKey: sk.delegations })
}
export function useCreateDelegation() {
  const invalidate = useInvalidateDelegations()
  return useMutation({ mutationFn: (body: DelegationInput) => api.createDelegation(body), onSuccess: invalidate })
}
export function useUpdateDelegation() {
  const invalidate = useInvalidateDelegations()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Pick<DelegationInput, "scope" | "account_ids"> }) => api.updateDelegation(id, patch),
    onSuccess: invalidate,
  })
}
export function useDeleteDelegation() {
  const invalidate = useInvalidateDelegations()
  return useMutation({ mutationFn: (id: string) => api.deleteDelegation(id), onSuccess: invalidate })
}

// ── 群組 ──────────────────────────────────────────────────
export function useGroups() {
  return useQuery({ queryKey: sk.groups, queryFn: () => api.listGroups(), staleTime: 30_000 })
}
export function useGroup(id: string) {
  return useQuery({ queryKey: sk.group(id), queryFn: () => api.getGroup(id), staleTime: 30_000, retry: no4xxRetry })
}
export function useCreateGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => api.createGroup({ name }),
    onSuccess: (g) => {
      qc.setQueryData(sk.group(g.id), g)
      void qc.invalidateQueries({ queryKey: sk.groups, exact: true })
    },
  })
}
/** 群組裡任何東西改了：這個群組底下的查詢都重新抓（投影可能跟著變） */
function useInvalidateGroup(id: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: sk.group(id) })
    void qc.invalidateQueries({ queryKey: sk.groups, exact: true })
  }
}
export function useUpdateGroup(id: string) {
  const invalidate = useInvalidateGroup(id)
  return useMutation({ mutationFn: (patch: { name?: string; ranking_enabled?: boolean }) => api.updateGroup(id, patch), onSuccess: invalidate })
}
export function useDeleteGroup(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.deleteGroup(id),
    onSuccess: () => {
      qc.removeQueries({ queryKey: sk.group(id) })
      void qc.invalidateQueries({ queryKey: sk.groups, exact: true })
      void qc.invalidateQueries({ queryKey: sk.delegations })
    },
  })
}
export function useTransferGroup(id: string) {
  const invalidate = useInvalidateGroup(id)
  return useMutation({ mutationFn: (userId: string) => api.transferGroup(id, userId), onSuccess: invalidate })
}
export function useSetMemberRole(id: string) {
  const invalidate = useInvalidateGroup(id)
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: "admin" | "member" }) => api.setMemberRole(id, userId, role),
    onSuccess: invalidate,
  })
}
/** 移除成員或離開（userId 是自己）；離開後這個群組的資料全部丟掉 */
export function useRemoveMember(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId }: { userId: string; self: boolean }) => api.removeMember(id, userId),
    onSuccess: (_, { self }) => {
      if (self) qc.removeQueries({ queryKey: sk.group(id) })
      else void qc.invalidateQueries({ queryKey: sk.group(id) })
      void qc.invalidateQueries({ queryKey: sk.groups, exact: true })
      void qc.invalidateQueries({ queryKey: sk.delegations })
    },
  })
}
export function useInvites(id: string, enabled: boolean) {
  return useQuery({ enabled, queryKey: sk.invites(id), queryFn: () => api.listInvites(id), staleTime: 30_000 })
}
export function useCreateInvite(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: InviteInput) => api.createInvite(id, body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sk.invites(id) }),
  })
}
export function useRevokeInvite(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (inviteId: string) => api.revokeInvite(id, inviteId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sk.invites(id) }),
  })
}
export function useInvitePreview(token: string) {
  return useQuery({ queryKey: sk.invite(token), queryFn: () => api.getInvite(token), staleTime: 60_000, retry: no4xxRetry })
}
export function useAcceptInvite(token: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (share: ShareSettings) => api.acceptInvite(token, share),
    onSuccess: (g) => {
      qc.setQueryData(sk.group(g.id), g)
      void qc.invalidateQueries({ queryKey: sk.groups, exact: true })
      void qc.invalidateQueries({ queryKey: sk.invite(token) })
    },
  })
}

// ── 我的分享 ──────────────────────────────────────────────
export function usePutShare(id: string) {
  const qc = useQueryClient()
  const key = sk.share(id)
  return useMutation({
    mutationKey: key,
    // 一次送一筆、照按的順序：每筆都是完整的六個開關，並行送出時可能後發先至，
    // 舊的那筆最後寫入就把剛關掉的分享（例如交易動態）又打開了。開關本身照樣立即反應（onMutate 不排隊）。
    scope: { id: `share:${id}` },
    mutationFn: (share: ShareSettings) => api.putShare(id, share),
    onMutate: async (share) => {
      // 開關立即反應；失敗時還原
      await qc.cancelQueries({ queryKey: sk.group(id), exact: true })
      const before = qc.getQueryData(sk.group(id))
      qc.setQueryData<Group>(sk.group(id), (g) => (g ? { ...g, my_share: share } : g))
      return { before }
    },
    onError: (_e, _s, ctx) => {
      if (ctx?.before) qc.setQueryData(sk.group(id), ctx.before)
    },
    // 還有排在後面的分享設定時先不重抓：伺服器還沒寫入下一筆，重抓會讓開關跳回舊的狀態；最後一筆完成才整組重抓
    onSettled: () => {
      if (qc.isMutating({ mutationKey: key }) <= 1) void qc.invalidateQueries({ queryKey: sk.group(id) })
    },
  })
}

// ── 排行、持股、成員 ───────────────────────────────────────
export function useLeaderboard(id: string, period: LeaderboardPeriod) {
  return useQuery({ queryKey: sk.leaderboard(id, period), queryFn: () => api.getLeaderboard(id, period), staleTime: 60_000 })
}
export function useGroupHoldings(id: string) {
  return useQuery({ queryKey: sk.holdings(id), queryFn: () => api.getGroupHoldings(id), staleTime: 60_000 })
}
export function useSharedPortfolio(id: string, userId: string) {
  return useQuery({ queryKey: sk.shared(id, userId), queryFn: () => api.getSharedPortfolio(id, userId), staleTime: 60_000, retry: no4xxRetry })
}

// ── 動態、留言、表情 ───────────────────────────────────────
export function useFeed(id: string, userId?: string) {
  return useInfiniteQuery({
    queryKey: sk.feed(id, userId),
    queryFn: ({ pageParam }) => api.getFeed(id, { limit: 30, cursor: pageParam, user_id: userId }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 30_000,
  })
}
export function useComments(id: string, target: CommentTarget, enabled = true) {
  return useQuery({ enabled, queryKey: sk.comments(id, target), queryFn: () => api.listComments(id, target, { limit: 50 }), staleTime: 15_000, retry: no4xxRetry })
}
/** 留言與表情改了：留言串、動態與週報的計數一起更新 */
function useInvalidateDiscussion(id: string) {
  const qc = useQueryClient()
  return (target: CommentTarget) => {
    void qc.invalidateQueries({ queryKey: sk.comments(id, target) })
    void qc.invalidateQueries({ queryKey: ["groups", id, "feed"] })
    void qc.invalidateQueries({ queryKey: sk.digests(id) })
  }
}
export function useCreateComment(id: string) {
  const invalidate = useInvalidateDiscussion(id)
  return useMutation({
    mutationFn: ({ target, body }: { target: CommentTarget; body: string }) => api.createComment(id, { target, body }),
    onSuccess: (_, { target }) => invalidate(target),
  })
}
export function useDeleteComment(id: string) {
  const invalidate = useInvalidateDiscussion(id)
  return useMutation({
    mutationFn: ({ commentId }: { commentId: string; target: CommentTarget }) => api.deleteComment(id, commentId),
    onSuccess: (_, { target }) => invalidate(target),
  })
}
export function useToggleReaction(id: string) {
  const invalidate = useInvalidateDiscussion(id)
  return useMutation({
    mutationFn: ({ target, emoji, on }: { target: CommentTarget; emoji: ReactionEmoji; on: boolean }) =>
      on ? api.addReaction(id, { target, emoji }) : api.removeReaction(id, target, emoji),
    onSuccess: (_, { target }) => invalidate(target),
  })
}

// ── 週報 ──────────────────────────────────────────────────
export function useDigests(id: string) {
  return useInfiniteQuery({
    queryKey: sk.digests(id),
    queryFn: ({ pageParam }) => api.listDigests(id, { limit: 8, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    staleTime: 60_000,
  })
}

// ── 頻道 ──────────────────────────────────────────────────
/** `poll`：等 Telegram 群組傳 /link 時每 3 秒看一次，連結好了就停 */
export function useChannels(id: string, opts: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: sk.channels(id),
    queryFn: () => api.getChannels(id),
    staleTime: 30_000,
    refetchInterval: (q) => (opts.poll && q.state.data?.telegram.status !== "active" ? 3000 : false),
  })
}
function useInvalidateChannels(id: string) {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: sk.channels(id) })
    // 推播到哪些頻道（push_targets）在 Group 裡
    void qc.invalidateQueries({ queryKey: sk.group(id), exact: true })
  }
}
export function usePutDiscord(id: string) {
  const invalidate = useInvalidateChannels(id)
  return useMutation({
    mutationFn: (body: { webhook_url: string } & Required<ChannelNotify>) => api.putDiscord(id, body),
    onSuccess: invalidate,
  })
}
export function usePatchChannel(id: string, kind: "discord" | "telegram") {
  const invalidate = useInvalidateChannels(id)
  return useMutation({
    mutationFn: (patch: ChannelNotify) => (kind === "discord" ? api.patchDiscord(id, patch) : api.patchTelegram(id, patch)),
    onSuccess: invalidate,
  })
}
export function useDeleteChannel(id: string, kind: "discord" | "telegram") {
  const invalidate = useInvalidateChannels(id)
  return useMutation({ mutationFn: () => (kind === "discord" ? api.deleteDiscord(id) : api.deleteTelegram(id)), onSuccess: invalidate })
}
export function useLinkTelegram(id: string) {
  return useMutation({ mutationFn: () => api.linkTelegram(id) })
}
