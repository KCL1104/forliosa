import { create } from "zustand"
import { createJSONStorage, persist } from "zustand/middleware"
import type { Draft, Message, Thread } from "./types"

/**
 * AI 面板的狀態：對話、草稿、面板開合。
 * - 桌面面板的開合要記住（使用者偏好，存在這台瀏覽器）
 * - 對話紀錄與待簽名草稿也存在這台瀏覽器；M4 之後改由後端同步
 */
interface AiState {
  panelOpen: boolean
  mobileOpen: boolean
  threadId: string | null
  threads: Thread[]
  drafts: Record<string, Draft>
  /** 送出後要捲到的草稿（例如點了「待簽名」） */
  focusDraftId: string | null
  /** 輸入框要預填的文字（例如點了「記一筆交易」） */
  composerSeed: { text: string; nonce: number } | null

  setPanelOpen: (open: boolean) => void
  setMobileOpen: (open: boolean) => void
  newThread: () => void
  openThread: (id: string) => void
  deleteThread: (id: string) => void
  push: (message: Omit<Message, "id" | "at">, opts?: { title?: string }) => string
  patchMessage: (id: string, patch: Partial<Message>) => void
  upsertDraft: (draft: Draft) => void
  patchDraft: (id: string, patch: Partial<Draft>) => void
  focusDraft: (id: string | null) => void
  seedComposer: (text: string) => void
}

const uid = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`
const now = () => new Date().toISOString()

export const useAi = create<AiState>()(
  persist(
    (set, get) => ({
      panelOpen: true,
      mobileOpen: false,
      threadId: null,
      threads: [],
      drafts: {},
      focusDraftId: null,
      composerSeed: null,

      setPanelOpen: (panelOpen) => set({ panelOpen }),
      setMobileOpen: (mobileOpen) => set({ mobileOpen }),
      newThread: () => set({ threadId: null }),
      openThread: (id) => set({ threadId: id }),
      deleteThread: (id) =>
        set((s) => ({ threads: s.threads.filter((t) => t.id !== id), threadId: s.threadId === id ? null : s.threadId })),
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
