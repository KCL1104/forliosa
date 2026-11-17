import { useId, useState } from "react"
import type { ReportTable as Spec } from "@/api/types"
import { InternalLink } from "@/components/internal-link"
import { textAction } from "@/components/text-action"
import { cn } from "@/lib/utils"

/**
 * 報告的表（排行、多期間報酬、法人、上櫃類股…）：印好的表頭（`.form-head`）、一列一條格線、等寬數字、漲跌色只在漲跌幅。
 * 表名下面一行 13px 淡墨寫這張表依什麼規則挑的（「範圍：市值前 200 名或 300 億元以上…」）。
 * 有 `fold_after` 的表先列那幾列，下面文字鈕「全部 N 列」。有連結的列整列可以按（名稱那一格的連結蓋滿整列）。
 * 放不下時表格自己橫向捲動，第一欄固定在左邊（紙色底），每一列都讀得出是什麼。
 */
export function ReportTable({ table }: { table: Spec }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const fold = table.fold_after !== null && table.rows.length > table.fold_after + 1 ? table.fold_after : null
  const rows = fold !== null && !open ? table.rows.slice(0, fold) : table.rows
  const first = table.columns[0]?.key
  // 第一欄固定在左邊只給沒有連結的表（多期間報酬這種寬的表）：固定的格子會擋住整列連結的範圍
  const sticky = !table.rows.some((r) => r.href)
  return (
    <figure aria-labelledby={`${id}-t`} className="flex flex-col" data-table={table.id}>
      <figcaption className="mb-1">
        <span id={`${id}-t`} className="block text-md font-semibold text-ink">
          {table.title}
        </span>
        {table.rule && <span className="block text-sm text-ink-2">{table.rule}</span>}
      </figcaption>
      {table.rows.length === 0 ? (
        <p className="border-y border-rule py-2.5 text-base text-ink">{table.empty_text ?? "沒有資料。"}</p>
      ) : (
        <div className="-mx-1 overflow-x-auto px-1">
          <table id={`${id}-b`} className="w-full border-collapse text-md">
            <thead className="form-head">
              <tr>
                {table.columns.map((c, i) => (
                  <th
                    key={c.key}
                    scope="col"
                    className={cn("h-9 py-1 font-normal", c.align === "right" ? "pl-3 text-right" : "pr-3 text-left", i === 0 && sticky && "sticky left-0 z-[1] bg-paper")}
                  >
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, n) => (
                <tr key={n} className={cn("relative border-b border-rule", r.href && "ruled-row")}>
                  {table.columns.map((c, i) => {
                    const cell = r.cells[c.key]
                    const tone = cell?.tone === "rise" ? "text-rise" : cell?.tone === "fall" ? "text-fall" : undefined
                    const body = (
                      <>
                        <span className={cn("block", c.num && "num whitespace-nowrap", tone)}>{cell?.text ?? "—"}</span>
                        {cell?.sub && <span className="num block text-xs leading-4 text-ink-2">{cell.sub}</span>}
                      </>
                    )
                    return (
                      <td
                        key={c.key}
                        className={cn(
                          "h-11 py-1.5 align-middle",
                          c.align === "right" ? "pl-3 text-right" : "pr-3 text-left",
                          i === 0 && sticky && "sticky left-0 z-[1] bg-paper",
                        )}
                      >
                        {/* 整列可以按：第一格的連結用 ::after 蓋滿整列（列是 relative） */}
                        {r.href && c.key === first ? (
                          <InternalLink href={r.href} className="rounded-xs text-ink after:absolute after:inset-0 after:content-[''] hover:underline hover:decoration-ctl hover:underline-offset-4">
                            {body}
                          </InternalLink>
                        ) : (
                          body
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {fold !== null && (
        <button type="button" aria-expanded={open} aria-controls={`${id}-b`} onClick={() => setOpen((v) => !v)} className={cn(textAction, "mt-1 self-start")}>
          {open ? "收起" : `全部 ${table.rows.length} 列`}
        </button>
      )}
      {table.note && <p className="mt-1.5 text-sm text-ink-2">{table.note}</p>}
    </figure>
  )
}
