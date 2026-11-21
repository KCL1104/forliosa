import { Tray } from "@/components/tray"
import { cn } from "@/lib/utils"

/**
 * 分頁第一行：規則算出來的一句話（不是模型寫的），所以是墨色 Noto Sans、關鍵數字 600；
 * 沒有值得說的就不出現。數字用 `<Fig>` 包起來。
 */
export function TabLead({ children, className }: { children?: React.ReactNode; className?: string }) {
  if (!children) return null
  return <p className={cn("mb-4 max-w-prose text-base text-ink", className)}>{children}</p>
}

/** 規則句子裡的關鍵數字：600、等寬；數字和單位（「2.1 倍」）不分開換行 */
export function Fig({ children }: { children: React.ReactNode }) {
  return <span className="num font-semibold whitespace-nowrap">{children}</span>
}

/**
 * 手機 2 欄時，`wide` 的格子要從新的一列開始：前面的普通格是奇數個時，先放下一個普通格再放它，
 * 不在左邊留一格空洞（DOM 順序和看到的順序一樣）。
 */
function arrange(items: KeyItem[]): KeyItem[] {
  const out: KeyItem[] = []
  let waiting: KeyItem[] = []
  let odd = false
  for (const it of items) {
    if (it.wide && odd) {
      waiting.push(it)
      continue
    }
    out.push(it)
    if (!it.wide) odd = !odd
    if (!odd && waiting.length) {
      out.push(...waiting)
      waiting = []
    }
  }
  return [...out, ...waiting]
}

/**
 * 最後一列不留孤零零的一格（格線斷在半路）。回傳每一格要加的 class。
 * - 手機（< lg，2 欄）：走一遍看每一格落在第幾欄（`wide` 自己佔一列）；落單的那一格撐滿那一列。
 * - 桌面 3 欄：畫成 6 條軌、每格佔 2 條；剩 1 格時最後 4 格、剩 2 格時最後 2 格各佔 3 條——
 *   最後兩列變成兩兩一列，不會有一格撐滿整個版心、標籤和數字隔 1,000px。
 * - 桌面 2 欄：落單的最後一格撐滿。
 */
function lastRowSpans(items: KeyItem[], cols: 2 | 3): string[] {
  const n = items.length
  const spans = items.map(() => "")
  let col = 0
  items.forEach((it, i) => {
    if (it.wide) {
      if (col === 1 && i > 0) spans[i - 1] = "max-lg:col-span-2"
      col = 0
    } else {
      col = col === 0 ? 1 : 0
    }
  })
  if (col === 1 && n) spans[n - 1] = "max-lg:col-span-2"
  if (cols === 3) {
    const rest = n % 3
    const halves = rest === 1 ? Math.min(4, n) : rest === 2 ? 2 : 0
    items.forEach((_, i) => {
      spans[i] = cn(spans[i], n === 1 ? "lg:col-span-6" : i >= n - halves ? "lg:col-span-3" : "lg:col-span-2")
    })
  } else if (n % 2 === 1) {
    spans[n - 1] = cn(spans[n - 1], "lg:col-span-2")
  }
  return spans
}

/**
 * 鍵值格：格線分隔，3 欄（手機 2 欄），數字等寬靠右；`wide` 的格子在手機佔滿一列（值比較長時）；最後一列不留孤格。
 * 格子很窄的時候（這張格子 < 24rem：手機上放在分頁托盤裡，393px 的手機只有 321px）標籤在上、數字在下、靠左，
 * 不讓「3 個月均量」「52 週區間」這種標籤被數字擠成兩行；數字放不下時換行，不撐出托盤。
 */
export function KeyGrid({ items, className, cols = 3 }: { items: KeyItem[]; className?: string; cols?: 2 | 3 }) {
  const ordered = arrange(items)
  const spans = lastRowSpans(ordered, cols)
  return (
    <dl className={cn("@container grid grid-cols-2 gap-x-8 border-t border-rule @max-sm:gap-x-5", cols === 3 && "lg:grid-cols-6", className)}>
      {ordered.map((it, i) => (
        <div
          key={it.label}
          className={cn(
            "flex min-h-11 items-baseline justify-between gap-3 border-b border-rule py-2.5 @max-sm:flex-col @max-sm:justify-start @max-sm:gap-0.5",
            it.wide && "max-lg:col-span-2",
            spans[i],
          )}
          title={it.title}
        >
          <dt className="min-w-0 text-md text-ink-2">{it.label}</dt>
          <dd className="num max-w-full text-right text-base whitespace-nowrap text-ink @max-sm:text-left @max-sm:whitespace-normal @max-sm:[overflow-wrap:anywhere]">{it.value}</dd>
        </div>
      ))}
    </dl>
  )
}
export type KeyItem = { label: string; value: React.ReactNode; title?: string; wide?: boolean }

/**
 * 空狀態（全站同一種）：上下各一條實線格線（沒有外框、沒有底色）、15px 墨色標題（600）、同樣 15px 墨色寫原因、最多一個動作。
 * 虛線在這個系統是「AI 草稿」，空狀態不用。
 */
export function NotYet({ title, children, action, className }: { title: string; children?: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-start border-y border-rule py-5", className)}>
      <p className="text-base font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 max-w-prose text-base text-ink">{children}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

/**
 * 總覽第三層（新聞報導、關於〈公司〉、相關股票）的托盤：名詞標題、沒有說明段落；動作放右邊。
 * 是分頁托盤的兄弟（托盤不疊托盤）；寬的時候預設撐滿一列（`@4xl:col-span-12`），`className` 可以改。
 */
export function QuietSection({
  title,
  id,
  action,
  children,
  className,
}: {
  title: React.ReactNode
  /** section 的 id（相關股票是 `ov-related`：事件托盤靠它決定要不要並排） */
  id?: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <Tray title={title} id={id} action={action} className={cn("@4xl:col-span-12", className)}>
      {children}
    </Tray>
  )
}
