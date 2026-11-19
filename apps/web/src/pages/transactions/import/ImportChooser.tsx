import { ChevronRightIcon } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { bodyClass, footerClass } from "./layout"

/**
 * 匯入的第一步：要匯入什麼（產品負責人 2026-11-17）。兩列格線列，整列可以按：
 * 匯入庫存（現有持股，最快）在上面，匯入對帳單（交易明細）在下面。一行說要給什麼，一行淡墨說會記成什麼、有沒有之前的走勢
 * （兩種最大的差別：庫存每一檔是一筆券商均價的買進，均價到那天收盤的漲跌都算在那一天，之前沒有走勢與區間報酬）。
 */
export function ImportChooser({ sheet, onPick, onCancel }: { sheet: boolean; onPick: (kind: "positions" | "statement") => void; onCancel: () => void }) {
  return (
    <>
      <div className={cn(bodyClass(sheet), "pt-1")}>
        {/* 標題下面已經有一條線：清單只畫列與列之間、最後一條 */}
        <ul className="border-b border-rule" aria-label="要匯入什麼">
          <Choice
            title="匯入庫存"
            tag="現有持股，最快"
            line="券商 app 庫存頁的截圖，或貼上庫存的文字。"
            then="每一檔記成一筆買進（券商均價），沒有之前的走勢和區間報酬。"
            onClick={() => onPick("positions")}
          />
          <Choice title="匯入對帳單" tag="交易明細" line="PDF 對帳單，或成交明細的截圖。" then="每一筆買賣照原本的日期記，績效從第一筆起算。" onClick={() => onPick("statement")} />
        </ul>
      </div>
      <div className={footerClass(sheet)}>
        <Button type="button" variant="outline" className={cn("ml-auto", sheet ? "flex-1" : "min-w-24")} onClick={onCancel}>
          取消
        </Button>
      </div>
    </>
  )
}

function Choice({ title, tag, line, then, onClick }: { title: string; tag: string; line: string; then: string; onClick: () => void }) {
  return (
    <li className="border-t border-rule first:border-t-0">
      <button
        type="button"
        onClick={onClick}
        className="press group flex w-full items-center gap-3 py-3.5 pr-1 text-left outline-none hover:bg-hov focus-visible:outline-2 focus-visible:outline-solid focus-visible:-outline-offset-2 focus-visible:outline-ink active:bg-hov sm:-mx-3 sm:w-[calc(100%+1.5rem)] sm:px-3"
      >
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            <span className="text-lg font-medium text-ink">{title}</span>
            <span className="text-sm text-ink-2">{tag}</span>
          </span>
          <span className="mt-1 block text-base text-ink">{line}</span>
          <span className="mt-0.5 block text-sm text-ink-2">{then}</span>
        </span>
        <ChevronRightIcon aria-hidden className="size-4 shrink-0 text-ink-2 transition-transform group-hover:translate-x-0.5" />
      </button>
    </li>
  )
}
