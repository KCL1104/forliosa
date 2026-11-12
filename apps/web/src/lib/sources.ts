/**
 * 頁尾「資料來源與授權」的資料層（純函式）：各區塊登記的來源 → 去重 → 頁尾一次列出。
 * 元件在 `@/components/sources`，登記用的 hook 在 `@/hooks/use-source-note`。
 */

/** 一個資料來源：名稱（提供機關〈資料集〉（年份），或媒體、網站）＋授權＋可選連結 */
export type SourceNote = { name: string; licence?: string; href?: string }
/** 後端 `sources` 的原文字串也可以直接給：例如「臺灣證券交易所〈上市個股日成交資訊〉（2026），依政府資料開放授權條款第 1 版」 */
export type SourceInput = SourceNote | string

/**
 * 把後端的顯名聲明字串拆成名稱與授權（不改寫文字）：
 * - 「X〈Y〉（2026），依 Z」→ 名稱「X〈Y〉（2026）」、授權「Z」
 * - 「X〈Y〉（2026），Z」（例如 SEC 的「美國政府公開資料」）→ 同上，授權「Z」
 * - 「X（…授權…）」（例如「臺灣證券交易所 OpenAPI（政府資料開放授權條款第 1 版）」）→ 名稱「X」、授權是括號內的文字
 * - 其他 → 整句是名稱
 */
export function toSourceNote(input: SourceInput): SourceNote {
  if (typeof input !== "string") return input
  const s = input.trim()
  const dated = /^(.+?〉（\d{4}）)，\s*(?:依\s*)?(.+)$/.exec(s)
  if (dated) return { name: dated[1]!, licence: dated[2]! }
  const paren = /^(.+?)\s*（([^（）]*(?:授權|License|license|CC BY|CC0)[^（）]*)）$/.exec(s)
  if (paren) return { name: paren[1]!, licence: paren[2]! }
  return { name: s }
}

export const sourceKey = (n: SourceNote) => `${n.name}\u0000${n.licence ?? ""}`

/** 依登記順序合併、以「名稱＋授權」去重（後來的有連結時補上連結） */
export function dedupeSources(lists: readonly (readonly SourceNote[])[]): SourceNote[] {
  const seen = new Map<string, SourceNote>()
  for (const list of lists) {
    for (const n of list) {
      const k = sourceKey(n)
      const prev = seen.get(k)
      if (!prev) seen.set(k, n)
      else if (!prev.href && n.href) seen.set(k, { ...prev, href: n.href })
    }
  }
  return [...seen.values()]
}

/** 依授權分組（保留出現順序）；沒有授權的在 `""` 那一組 */
export function groupByLicence(notes: readonly SourceNote[]): [licence: string, notes: SourceNote[]][] {
  const groups = new Map<string, SourceNote[]>()
  for (const n of notes) {
    const k = n.licence ?? ""
    groups.set(k, [...(groups.get(k) ?? []), n])
  }
  return [...groups.entries()]
}

export type SourcesStore = {
  set: (id: string, notes: SourceNote[]) => void
  remove: (id: string) => void
  subscribe: (cb: () => void) => () => void
  snapshot: () => SourceNote[]
}

/** 一頁的登記表：每個區塊（id）一組來源；快照是去重後的清單（沒變就是同一個陣列） */
export function createSourcesStore(): SourcesStore {
  const entries = new Map<string, SourceNote[]>()
  const listeners = new Set<() => void>()
  let snap: SourceNote[] = []
  const emit = () => {
    snap = dedupeSources([...entries.values()])
    for (const l of listeners) l()
  }
  return {
    set: (id, notes) => {
      entries.set(id, notes)
      emit()
    },
    remove: (id) => {
      if (entries.delete(id)) emit()
    },
    subscribe: (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    snapshot: () => snap,
  }
}
