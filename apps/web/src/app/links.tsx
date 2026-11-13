import { createLink } from "@tanstack/react-router"
import { forwardRef } from "react"

/**
 * 內文裡的站內連結（字標、「近 1 個月走勢」的原因、本週事項那一列…）。
 * TanStack Router 的 `<Link>` 只要目標就是目前的網址，就自動加 `aria-current="page"`，
 * 螢幕閱讀器會在不是導覽的連結上讀「目前頁面」。`aria-current="page"` 只留給真正的導覽
 * （頂部列、手機底部列——那裡自己傳 `aria-current`）；其他地方用這個元件：
 * 預載、SPA 導覽、型別都和 `<Link>` 一樣，只是不標 `aria-current`。
 */
export const PlainLink = createLink(
  forwardRef<HTMLAnchorElement, React.ComponentProps<"a">>(function PlainAnchor({ "aria-current": _current, ...props }, ref) {
    return <a ref={ref} {...props} />
  }),
)
