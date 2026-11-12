import { useEffect, useRef } from "react"
import { cn } from "@/lib/utils"

/** 被選取的子元件（分頁、區間、切換、導覽）：捲進畫面用 */
const SELECTED =
  '[aria-selected="true"],[aria-checked="true"],[aria-pressed="true"],[aria-current]:not([aria-current="false"]),[data-active]:not([data-active="false"])'
/** 淡出的寬度（和 globals.css 的 .scroll-row 相同），捲動時讓目標停在淡出區外 */
const FADE = 28

function reveal(row: HTMLElement, target: Element, smooth: boolean) {
  const r = target.getBoundingClientRect()
  const c = row.getBoundingClientRect()
  let delta = 0
  if (r.left < c.left + FADE) delta = r.left - c.left - FADE
  else if (r.right > c.right - FADE) delta = r.right - c.right + FADE
  if (!delta) return
  const left = Math.max(0, row.scrollLeft + delta)
  const reduce = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  if (typeof row.scrollTo === "function") row.scrollTo({ left, behavior: smooth && !reduce ? "smooth" : "auto" })
  else row.scrollLeft = left
}

/**
 * 橫向捲動的一列（手機上放不下的分頁列、區間與篩選）：
 * - 沒有箭頭；只有「後面還有」的那一邊淡出（mask），隨捲動與尺寸變化更新（ResizeObserver）。
 * - 選取中的子元件會捲進畫面（載入時、選取改變時），鍵盤移動焦點時焦點所在的子元件也會。
 * - 這個 div 就是捲動容器：可以直接給 `role="tablist"`／`role="radiogroup"` 與 `aria-label`，子元件放分頁或選項。
 */
export function ScrollRow({ className, children, ref, ...props }: React.ComponentProps<"div">) {
  const own = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const row = own.current
    if (!row) return
    const update = () => {
      const max = row.scrollWidth - row.clientWidth
      row.toggleAttribute("data-overflow-start", max > 1 && row.scrollLeft > 1)
      row.toggleAttribute("data-overflow-end", max > 1 && row.scrollLeft < max - 1)
    }
    const revealSelected = (smooth: boolean) => {
      const sel = row.querySelector(SELECTED)
      if (sel) reveal(row, sel, smooth)
    }
    const onFocus = (e: FocusEvent) => {
      if (e.target instanceof Element && e.target !== row) reveal(row, e.target, false)
    }

    revealSelected(false)
    update()
    row.addEventListener("scroll", update, { passive: true })
    row.addEventListener("focusin", onFocus)

    // 尺寸：容器與每個子元件（字型載入、標籤改變都會改變內容寬度）
    const resize = typeof ResizeObserver === "function" ? new ResizeObserver(update) : null
    const observeChildren = () => {
      if (!resize) return
      resize.disconnect()
      resize.observe(row)
      for (const child of Array.from(row.children)) resize.observe(child)
    }
    observeChildren()

    // 子元件增減、選取改變：重新觀察並把新的選取捲進畫面
    const mutations =
      typeof MutationObserver === "function"
        ? new MutationObserver((records) => {
            if (records.some((r) => r.type === "childList")) observeChildren()
            if (records.some((r) => r.type === "attributes")) revealSelected(true)
            update()
          })
        : null
    mutations?.observe(row, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-selected", "aria-checked", "aria-pressed", "aria-current", "data-active"] })

    return () => {
      row.removeEventListener("scroll", update)
      row.removeEventListener("focusin", onFocus)
      resize?.disconnect()
      mutations?.disconnect()
    }
  }, [])

  return (
    <div
      {...props}
      ref={(el) => {
        own.current = el
        if (typeof ref === "function") return ref(el)
        if (ref) ref.current = el
      }}
      className={cn("scroll-row flex", className)}
    >
      {children}
    </div>
  )
}
