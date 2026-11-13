import { Fragment } from "react"
import { linkParts } from "@/lib/linkify"
import { cn } from "@/lib/utils"

/**
 * 使用者寫的純文字（主題內文、回覆）：保留換行，`http(s)://` 網址變成另開新視窗的連結
 * （`rel="nofollow ugc noopener noreferrer"`）。不支援 Markdown、圖片；不用 dangerouslySetInnerHTML。
 * 字是墨色、行長由外面決定；網址放不下一行時先整個換到下一行，還是放不下才在中間斷行，不撐寬頁面。
 */
export function PlainText({ text, className }: { text: string; className?: string }) {
  return (
    <p className={cn("break-words whitespace-pre-wrap text-ink", className)}>
      {linkParts(text).map((p, i) =>
        p.kind === "link" ? (
          <a
            key={i}
            href={p.href}
            target="_blank"
            rel="nofollow ugc noopener noreferrer"
            className="underline decoration-ctl decoration-1 underline-offset-4 hover:decoration-ink pointer-coarse:py-2.5"
          >
            {p.text}
            <span className="sr-only">（另開新視窗）</span>
          </a>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </p>
  )
}
