import { cn } from "@/lib/utils"

/**
 * 表單欄位：標籤（可附右側提示）＋控制項＋錯誤訊息（`FieldError`）。
 * 交易表單與設定頁共用；錯誤訊息以 role="alert" 讀出。
 */
export function FormField({
  label,
  htmlFor,
  error,
  hint,
  className,
  children,
}: {
  label: string
  htmlFor?: string
  error?: string | null
  hint?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        {htmlFor ? (
          <label htmlFor={htmlFor} className="text-sm font-medium">
            {label}
          </label>
        ) : (
          <span className="text-sm font-medium">{label}</span>
        )}
        {hint && <span className="num text-sm text-ink-2">{hint}</span>}
      </div>
      {children}
      {error && <FieldError>{error}</FieldError>}
    </div>
  )
}

/**
 * 欄位的錯誤（全站同一種）：13px 墨色 500，`role="alert"`（送出後才出現的要讀出來）。
 * 不是紅色（紅色在這個產品是「漲」），也不是說明文字的淡墨 400——粗一級、墨色，看得出是要處理的事。
 */
export function FieldError({ id, className, children }: { id?: string; className?: string; children: React.ReactNode }) {
  return (
    <p id={id} role="alert" className={cn("text-sm font-medium text-ink", className)}>
      {children}
    </p>
  )
}
