import { useState } from "react"
import { toast } from "sonner"
import { useMe } from "@/api/queries"
import { useUpdateMe } from "@/api/sharing-queries"
import { ApiError, PUBLIC_NAME_MAX, type User } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { Section } from "@/components/section"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { PUBLIC_NAME_HELP, suspendedText, suspendedUntil } from "@/pages/discussions/labels"
import { usePublicNameForm } from "@/pages/discussions/use-public-name-form"
import { FieldError } from "@/components/form-field"

/**
 * 個人資料：顯示名稱（群組裡大家看到的名字，1–30 字；頭像來自 Discord）與公開暱稱（公開討論用的名字，2–20 字）。
 * 兩個名字分開：公開的地方不顯示顯示名稱與頭像，群組裡不顯示公開暱稱。
 */
export function Profile() {
  const me = useMe()
  if (!me.data) return null
  return (
    <Section id="profile" title="個人資料" titleId="set-profile" className="scroll-mt-20">
      <ProfileForm key={me.data.display_name} name={me.data.display_name} email={me.data.email} avatar={me.data.avatar_url ?? null} />
      <PublicNameForm key={me.data.public_name ?? ""} user={me.data} />
    </Section>
  )
}

/** 簽名格只在真的改了的時候出現；沒改時桌面留一個看不見的同寬位置（輸入框不跳動），手機什麼都不放 */
function SaveSlot({ dirty, disabled, pending, label = "儲存" }: { dirty: boolean; disabled: boolean; pending: boolean; label?: string }) {
  return dirty ? (
    <Button type="submit" variant="sign" disabled={disabled} className="mt-2.5 justify-self-start sm:col-start-2 sm:row-start-2 sm:mt-0">
      {pending ? "儲存中…" : label}
    </Button>
  ) : (
    <span aria-hidden className={cn(buttonVariants({ variant: "sign" }), "invisible hidden sm:col-start-2 sm:row-start-2 sm:inline-flex")}>
      {label}
    </span>
  )
}

function ProfileForm({ name: initial, email, avatar }: { name: string; email: string; avatar: string | null }) {
  const update = useUpdateMe()
  const [name, setName] = useState(initial)
  const trimmed = name.trim()
  const bad = trimmed.length < 1 || trimmed.length > 30
  const dirty = trimmed !== initial
  return (
    <form
      className="flex flex-col gap-4 py-1 sm:flex-row sm:items-center"
      onSubmit={(e) => {
        e.preventDefault()
        if (bad || !dirty) return
        update.mutate(trimmed, {
          onSuccess: (u) => toast.success(`顯示名稱改為「${u.display_name}」`),
          onError: (err) => toast.error("名稱沒有更新", { description: err instanceof ApiError ? err.message : undefined }),
        })
      }}
    >
      <UserAvatar name={trimmed || initial} url={avatar} size="lg" />
      <div className="grid min-w-0 flex-1 gap-x-3 gap-y-1.5 sm:grid-cols-[minmax(0,1fr)_auto]">
        <label htmlFor="display-name" className="text-sm font-medium">
          顯示名稱
        </label>
        <Input id="display-name" value={name} maxLength={30} autoComplete="nickname" aria-invalid={bad} aria-describedby="display-name-help" onChange={(e) => setName(e.target.value)} className="pointer-coarse:h-11 sm:col-start-1 sm:row-start-2" />
        {/* 說明是要讀的句子（15px 墨色）；登入帳號是標註（淡墨小字） */}
        <p id="display-name-help" className="text-base text-ink sm:col-start-1 sm:row-start-3">
          {bad ? (
            "請填 1 到 30 個字。"
          ) : (
            <>
              群組裡大家看到的名字。<span className="text-sm text-ink-2">登入帳號：{email}</span>
            </>
          )}
        </p>
        <SaveSlot dirty={dirty} disabled={bad || update.isPending} pending={update.isPending} />
      </div>
    </form>
  )
}

/**
 * 公開暱稱：公開討論裡大家看到的名字。說明留著（這是後果重大的選擇）：公開的地方用這個名字、群組仍用顯示名稱、
 * 改了之後 7 天內不能再改。公開發言被站方暫停時，下面一行寫到什麼時候。
 * 和顯示名稱同一套版面：輸入框對齊（左邊留頭像的寬度），簽名格只在改過之後出現。
 */
function PublicNameForm({ user }: { user: User }) {
  const current = user.public_name ?? ""
  const form = usePublicNameForm(current)
  const dirty = form.trimmed !== current
  const until = suspendedUntil(user)
  return (
    <form
      className="mt-4 flex flex-col gap-1.5 border-t border-rule pt-4 sm:pl-16"
      onSubmit={(e) => {
        e.preventDefault()
        if (dirty) form.submit()
      }}
    >
      <div className="grid min-w-0 gap-x-3 gap-y-1.5 sm:grid-cols-[minmax(0,1fr)_auto]">
        <label htmlFor="public-name" className="text-sm font-medium">
          公開暱稱
        </label>
        <Input
          id="public-name"
          value={form.name}
          maxLength={PUBLIC_NAME_MAX}
          autoComplete="off"
          placeholder={current ? undefined : "還沒選"}
          aria-invalid={!!form.error}
          aria-describedby={form.error ? "public-name-error public-name-help" : "public-name-help"}
          onChange={(e) => form.change(e.target.value)}
          className="pointer-coarse:h-11 sm:col-start-1 sm:row-start-2"
        />
        <div className="flex flex-col gap-1 sm:col-start-1 sm:row-start-3">
          {form.error && (
            <FieldError id="public-name-error">{form.error}</FieldError>
          )}
          <p id="public-name-help" className="text-base text-ink">
            {PUBLIC_NAME_HELP}
          </p>
        </div>
        <SaveSlot dirty={dirty} disabled={form.pending || !form.trimmed} pending={form.pending} />
      </div>
      {until && <p className="mt-2 border-y border-rule py-2.5 text-md text-ink">{suspendedText(until)}</p>}
    </form>
  )
}
