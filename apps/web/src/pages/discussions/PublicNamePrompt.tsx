import { useId } from "react"
import { PUBLIC_NAME_MAX, type User } from "@/api/types"
import { FieldError } from "@/components/form-field"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { PUBLIC_NAME_HELP } from "./labels"
import { usePublicNameForm } from "./use-public-name-form"

/**
 * 還沒有公開暱稱時，取代回覆框（或出現在開新主題的「發到哪裡」下面）的一欄表單：選好就能發公開內容。
 * 獨立的元件：不依賴它出現在哪一頁。規則照合約——2 到 20 個字、不能和別人重複、不能含保留字；
 * 之後每改一次要等 7 天（第一次選的不算）。群組裡仍用原本的顯示名稱。
 */
export function PublicNamePrompt({ onDone, className }: { onDone?: (user: User) => void; className?: string }) {
  const form = usePublicNameForm("", onDone)
  const id = useId()
  return (
    <form
      aria-label="選公開暱稱"
      className={cn("flex flex-col gap-1.5", className)}
      onSubmit={(e) => {
        e.preventDefault()
        form.submit()
      }}
    >
      <label htmlFor={id} className="text-base font-semibold text-ink">
        先選一個公開暱稱
      </label>
      <p id={`${id}-help`} className="max-w-prose text-base text-ink">
        {PUBLIC_NAME_HELP}
      </p>
      <div className="mt-1.5 flex flex-wrap items-start gap-3">
        <Input
          id={id}
          value={form.name}
          maxLength={PUBLIC_NAME_MAX}
          autoComplete="off"
          aria-invalid={!!form.error}
          aria-describedby={form.error ? `${id}-error ${id}-help` : `${id}-help`}
          onChange={(e) => form.change(e.target.value)}
          className="w-full min-w-0 sm:w-64"
        />
        <Button type="submit" variant="sign" disabled={form.pending || !form.trimmed}>
          {form.pending ? "儲存中…" : "用這個暱稱"}
        </Button>
      </div>
      {form.error && <FieldError id={`${id}-error`}>{form.error}</FieldError>}
    </form>
  )
}
