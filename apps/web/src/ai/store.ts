import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"
import type { Draft, Message, Thread } from "./types"

/**
 * AI 面板的狀態：對話、草稿、面板開合。
 * - 桌面面板的開合要記住（使用者偏好，存在這台瀏覽器）：帳本與個股頁是 `panelOpen`（預設開）；
 *   AI 沒什麼可說的頁面（群組、設定、紀錄、資料來源，見 app/nav.ts）預設收成窄欄，使用者在那裡自己打開的話
 *   另外記在 `quietPanelOpen`（只記到關掉這個分頁為止，不存檔：下次打開還是預設的窄欄）
 * - 對話紀錄與待簽名草稿也存在這台瀏覽器；M4 之後改由後端同步
 */
interface AiState {
  panelOpen: boolean
  quietPanelOpen: boolean
  mobileOpen: boolean
  threadId: string | null
  threads: Thread[]
  drafts: Record<string, Draft>
  /** 送出後要捲到的草稿（例如點了「待簽名」） */
  focusDraftId: string | null
  /** 輸入框要預填的文字（例如點了「記一筆交易」） */
  composerSeed: { text: string; nonce: number } | null

  /** `quiet`：現在是不是安靜的頁面（開合分開記） */
  setPanelOpen: (open: boolean, quiet?: boolean) => void
  setMobileOpen: (open: boolean) => void
  newThread: () => void
  openThread: (id: string) => void
  deleteThread: (id: string) => void
  /** 刪除後按「復原」：放回原來的位置（依更新時間） */
  restoreThread: (thread: Thread) => void
  /**
   * 紀錄裡暫時藏起來的對話（不存檔）：示範紀錄刪除後、後端的對話在「復原」的時間內還沒真的刪掉
   */
  hiddenThreadIds: string[]
  setThreadHidden: (id: string, hidden: boolean) => void
  push: (message: Omit<Message, "id" | "at">, opts?: { title?: string }) => string
  patchMessage: (id: string, patch: Partial<Message>) => void
  /** 串流中的 AI 訊息：用函式更新，避免競態 */
  updateMessage: (id: string, fn: (m: Message) => Message) => void
  setRemoteId: (threadId: string, remoteId: string) => void
  /** 從後端載入的對話放進來（已存在同一個 remoteId 就取代）並打開 */
  loadThread: (thread: Thread, drafts: Draft[]) => void
  removeRemote: (remoteId: string) => void
  upsertDraft: (draft: Draft) => void
  patchDraft: (id: string, patch: Partial<Draft>) => void
  focusDraft: (id: string | null) => void
  seedComposer: (text: string) => void
}

/** 對話紀錄保留 30 天 */
export const RETENTION_MS = 30 * 86_400_000

const uid = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
const now = () => new Date().toISOString()

export const useAi = create<AiState>()(
  persist(
    (set, get) => ({
      panelOpen: true,
      quietPanelOpen: false,
      mobileOpen: false,
      threadId: null,
      threads: [],
      drafts: {},
      focusDraftId: null,
      composerSeed: null,

      setPanelOpen: (open, quiet) => set(quiet ? { quietPanelOpen: open } : { panelOpen: open }),
      setMobileOpen: (mobileOpen) => set({ mobileOpen }),
      newThread: () => set({ threadId: null }),
      openThread: (id) => set({ threadId: id }),
      deleteThread: (id) =>
        set((s) => ({ threads: s.threads.filter((t) => t.id !== id), threadId: s.threadId === id ? null : s.threadId })),
      restoreThread: (thread) =>
        set((s) =>
          s.threads.some((t) => t.id === thread.id)
            ? s
            : { threads: [...s.threads, thread].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 40) },
        ),
      hiddenThreadIds: [],
      setThreadHidden: (id, hidden) =>
        set((s) => ({ hiddenThreadIds: hidden ? [...new Set([...s.hiddenThreadIds, id])] : s.hiddenThreadIds.filter((x) => x !== id) })),
      push: (message, opts) => {
        const id = uid("msg")
        const m: Message = { ...message, id, at: now() }
        const { threadId, threads } = get()
        const existing = threadId ? threads.find((t) => t.id === threadId) : undefined
        if (existing) {
          set({
            threads: threads.map((t) => (t.id === existing.id ? { ...t, updatedAt: m.at, messages: [...t.messages, m] } : t)),
          })
        } else {
          const thread: Thread = { id: uid("thr"), title: opts?.title ?? message.text ?? "新對話", updatedAt: m.at, messages: [m] }
          set({ threads: [thread, ...threads].slice(0, 40), threadId: thread.id })
        }
        return id
      },
      patchMessage: (id, patch) =>
        set((s) => ({
          threads: s.threads.map((t) => (t.messages.some((m) => m.id === id) ? { ...t, messages: t.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)) } : t)),
        })),
      updateMessage: (id, fn) =>
        set((s) => ({
          threads: s.threads.map((t) => (t.messages.some((m) => m.id === id) ? { ...t, messages: t.messages.map((m) => (m.id === id ? fn(m) : m)) } : t)),
        })),
      setRemoteId: (threadId, remoteId) =>
        set((s) => ({ threads: s.threads.map((t) => (t.id === threadId ? { ...t, remoteId } : t)) })),
      loadThread: (thread, drafts) =>
        set((s) => {
          const kept = s.threads.filter((t) => t.remoteId !== thread.remoteId)
          const merged = { ...s.drafts }
          for (const d of drafts) {
            const local = merged[d.id]
            // 本機剛簽名、還沒同步回來的狀態優先
            merged[d.id] = local && local.status !== "loading" ? { ...d, ...local } : d
          }
          return { threads: [thread, ...kept].slice(0, 40), drafts: merged, threadId: thread.id }
        }),
      removeRemote: (remoteId) =>
        set((s) => {
          const gone = s.threads.find((t) => t.remoteId === remoteId)
          return { threads: s.threads.filter((t) => t.remoteId !== remoteId), threadId: gone && s.threadId === gone.id ? null : s.threadId }
        }),
      upsertDraft: (draft) => set((s) => ({ drafts: { ...s.drafts, [draft.id]: draft } })),
      patchDraft: (id, patch) =>
        set((s) => (s.drafts[id] ? { drafts: { ...s.drafts, [id]: { ...s.drafts[id]!, ...patch } } } : s)),
      focusDraft: (focusDraftId) => set({ focusDraftId }),
      seedComposer: (text) => set({ composerSeed: { text, nonce: Date.now() } }),
    }),
    {
      name: "forliosa:ai",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ panelOpen, threads, drafts, threadId }) => ({
        panelOpen,
        threadId,
        threads,
        // 只保留還沒處理的草稿與最近 20 筆
        drafts: Object.fromEntries(
          Object.entries(drafts)
            .filter(([, d]) => d.status !== "loading")
            .sort(([, a], [, b]) => b.createdAt.localeCompare(a.createdAt))
            .slice(0, 20),
        ),
      }),
      // 每次打開 app 從建議開始（舊對話留在「紀錄」）；有待簽名草稿的對話例外，直接回到它
      onRehydrateStorage: () => (state) => {
        // 對話紀錄保留 30 天（與後端相同）
        if (state) state.threads = state.threads.filter((t) => Date.now() - Date.parse(t.updatedAt) <= RETENTION_MS)
        // 關掉頁面時還在串流的回答：不會再有後續，標成已結束
        if (state) state.threads = state.threads.map((t) => (t.messages.some((m) => m.streaming) ? { ...t, messages: t.messages.map((m) => ({ ...m, streaming: false })) } : t))
        if (!state?.threadId) return
        const thread = state.threads.find((t) => t.id === state.threadId)
        const pending = thread?.messages.some((m) =>
          [m.draftId, ...(m.draftIds ?? [])].some((id) => id && state.drafts[id]?.status === "pending"),
        )
        if (!pending) state.threadId = null
      },
    },
  ),
)

export const newId = uid

/** 目前對話 */
export function useCurrentThread(): Thread | null {
  return useAi((s) => (s.threadId ? (s.threads.find((t) => t.id === s.threadId) ?? null) : null))
}

/** 待簽名的草稿數 */
export function usePendingCount(): number {
  return useAi((s) => Object.values(s.drafts).filter((d) => d.status === "pending").length)
}

/** 面板裡有事：開著一段對話，或有草稿在等簽名（換頁時面板不因此收起來） */
export function usePanelBusy(): boolean {
  return useAi((s) => s.threadId !== null || Object.values(s.drafts).some((d) => d.status === "pending"))
}

/** 最新一份待簽名的草稿（優先找還在紀錄裡的對話中的那份） */
export function latestPendingDraftId(): string | null {
  const s = useAi.getState()
  const pending = Object.values(s.drafts)
    .filter((d) => d.status === "pending")
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  const inThread = pending.find((d) => s.threads.some((t) => t.messages.some((m) => m.draftId === d.id || m.draftIds?.includes(d.id))))
  return (inThread ?? pending[0])?.id ?? null
}

/** 打開草稿所在的對話，並把草稿標成焦點約 2.4 秒（草稿卡會捲進畫面、加上外框） */
export function openDraft(id: string | null) {
  const s = useAi.getState()
  if (id && s.drafts[id]) {
    const thread = s.threads.find((t) => t.messages.some((m) => m.draftId === id || m.draftIds?.includes(id)))
    if (thread) s.openThread(thread.id)
  }
  s.focusDraft(id)
  window.setTimeout(() => useAi.getState().focusDraft(null), 2400)
}
