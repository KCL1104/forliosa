import { createContext, useContext, useEffect, useId, useSyncExternalStore } from "react"
import { type SourceInput, type SourceNote, type SourcesStore, toSourceNote } from "@/lib/sources"

/** 由 `<SourcesProvider>`（`@/components/sources`）提供；沒有 provider 時是 null */
export const SourcesContext = createContext<SourcesStore | null>(null)

const EMPTY: SourceNote[] = []
const noSubscribe = () => () => {}
const emptySnapshot = () => EMPTY

/**
 * 區塊登記它用到的資料來源，頁尾的 `<SourcesFooter />` 一次列出（卸載時移除）。
 * 可以給一筆、一串，或後端 `sources` 的原文字串陣列；空的就不登記。
 * 在 `<SourcesProvider>` 外面使用不會出錯（不做事）。「資料累積中…」這類狀態說明不是來源，不要放進來。
 */
export function useSourceNote(note: SourceInput | readonly SourceInput[] | null | undefined) {
  const store = useContext(SourcesContext)
  const id = useId()
  const list: readonly SourceInput[] = note == null ? [] : Array.isArray(note) ? note : [note as SourceInput]
  // 以內容當依賴：每次 render 新建的陣列不會造成重複登記
  const key = JSON.stringify(list.map(toSourceNote).filter((n) => n.name))
  useEffect(() => {
    if (!store) return
    const notes = JSON.parse(key) as SourceNote[]
    if (notes.length === 0) store.remove(id)
    else store.set(id, notes)
  }, [store, id, key])
  useEffect(() => () => store?.remove(id), [store, id])
}

/** 目前這一頁登記的來源（去重、依登記順序）；在 provider 外是空陣列 */
export function useSources(): SourceNote[] {
  const store = useContext(SourcesContext)
  return useSyncExternalStore(store?.subscribe ?? noSubscribe, store?.snapshot ?? emptySnapshot, emptySnapshot)
}
