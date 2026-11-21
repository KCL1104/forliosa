import { useId } from "react"
import { cn } from "@/lib/utils"

/**
 * 托盤（產品負責人 2026-11-21：帳本、個股、市場採方向 C「圓桌」的結構）：一組內容放在一塊有底色、8px 圓角的面上，
 * 沒有框線、沒有陰影；托盤不疊托盤。每一盤同一種底色（產品負責人 2026-11-21：托盤只留一種底色），盤與盤之間靠間距分開。
 * 樣式與托盤裡換掉的 token 在 globals.css 的 `.tray`。
 *
 * 標題一行：名詞標題（明體 600、20px，和 `Section` 同一級）＋選用的 meta（14px 淡墨：日期、範圍，例如「11/20 收盤」
 * 「持有 12 檔」）＋選用的動作（文字鈕、分段、連結）。標題不寫問句或句子，meta 不寫說明。
 *
 * 標題一行的每一塊都可以縮（`min-w-0`）、放不下就換行，動作最多和托盤一樣寬：分頁列、分段放在 `action` 裡，
 * 窄的時候自己橫向捲動（`ScrollRow`），不會把托盤撐出畫面（方向 C 手機個股頁的分頁列包在標題裡、撐到 540px）。
 * 分頁列不要放進 `title`：標題是 `<h2>`，裡面只放字。
 */
export function Tray({
  title,
  meta,
  action,
  titleHidden = false,
  id,
  className,
  bodyClassName,
  children,
}: {
  /** 名詞（「持股」「今日損益」「類股」），不是問句或句子 */
  title: React.ReactNode
  /** 日期或範圍，14px 淡墨（「11/20 收盤」「持有 12 檔」）；不是說明句 */
  meta?: React.ReactNode
  /** 標題列右邊的動作；窄的時候換到下一行 */
  action?: React.ReactNode
  /** 標題只給螢幕閱讀器：托盤第一行已經是印好的欄位名稱時（例如「總資產」） */
  titleHidden?: boolean
  /** 網址錨點 */
  id?: string
  className?: string
  bodyClassName?: string
  children: React.ReactNode
}) {
  const titleId = useId()
  const header = !titleHidden || !!meta || !!action
  return (
    <section id={id} aria-labelledby={titleId} className={cn("tray flex flex-col", className)}>
      {header ? (
        <header className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 id={titleId} className={cn("min-w-0 font-print text-xl font-semibold text-ink", titleHidden && "sr-only")}>
            {title}
          </h2>
          {meta && <p className="num min-w-0 text-sm text-ink-2">{meta}</p>}
          {action && <div className="ml-auto flex max-w-full min-w-0 items-center gap-1 self-center">{action}</div>}
        </header>
      ) : (
        <h2 id={titleId} className="sr-only">
          {title}
        </h2>
      )}
      <div className={cn("min-w-0", header && "mt-3", bodyClassName)}>{children}</div>
    </section>
  )
}
