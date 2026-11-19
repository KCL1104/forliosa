import { PlainLink } from "@/app/links"
import { DISCLAIMER, DISCLAIMER_PATH, DISCLAIMER_TITLE, type DisclaimerKind } from "@/lib/disclaimer"
import { cn } from "@/lib/utils"

/** 連到完整聲明（`/disclaimer`）的文字連結：13px 淡墨、常駐底線（和頁尾「資料來源與授權」同一種） */
export const disclaimerLink =
  "inline-flex min-h-11 items-center text-sm text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink"

/**
 * 免責的一句話，全站同一個樣子：13px 淡墨（DESIGN.md「免責與法律用語」），不加框、不加底色、不加圖示。
 * 字取自 `lib/disclaimer.ts`；後端有給（`done.disclaimer`、週報與日報、法人觀點的 `disclaimer`）時傳 `text`，沒有時用 `kind` 的常數。
 * `link`：句子後面接一個「免責聲明」連結（到 `/disclaimer`）。每個畫面區塊最多放一句。
 */
export function Disclaimer({
  kind = "short",
  text,
  link = false,
  className,
}: {
  kind?: DisclaimerKind
  /** 後端給的字（空字串、null 時用常數） */
  text?: string | null
  link?: boolean
  className?: string
}) {
  return (
    // 只在標點與空白處斷行（keep-all），一句話不會在「投資決／定」中間拆開；比一行還長的片段才用 anywhere 拆
    <p data-disclaimer={kind} className={cn("max-w-prose text-sm text-pretty text-ink-2 [overflow-wrap:anywhere] [word-break:keep-all]", className)}>
      {text || DISCLAIMER[kind]}
      {link && (
        <>
          {" "}
          {/* 夾在句子裡（和登入頁「登入即表示你同意服務條款」同一種）：不撐 44px 的高度，行距才不會被撐開 */}
          <PlainLink to={DISCLAIMER_PATH} className="whitespace-nowrap text-ink-2 underline decoration-ctl underline-offset-3 hover:text-ink hover:decoration-ink">
            {DISCLAIMER_TITLE}
          </PlainLink>
        </>
      )}
    </p>
  )
}
