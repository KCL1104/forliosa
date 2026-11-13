import { useState } from "react"
import { toast } from "sonner"
import { useMe } from "@/api/queries"
import { useUpdateMe } from "@/api/sharing-queries"
import { ApiError } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { Section } from "@/components/section"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

/** 個人資料：顯示名稱（群組裡大家看到的名字，1–30 字）；頭像來自 Discord */
export function Profile() {
  const me = useMe()
  if (!me.data) return null
  return <ProfileForm key={me.data.display_name} name={me.data.display_name} email={me.data.email} avatar={me.data.avatar_url ?? null} />
}

function ProfileForm({ name: initial, email, avatar }: { name: string; email: string; avatar: string | null }) {
  const update = useUpdateMe()
  const [name, setName] = useState(initial)
  const trimmed = name.trim()
  const bad = trimmed.length < 1 || trimmed.length > 30
  // 簽名格只在真的改了名字時出現；沒改時桌面留一個看不見的同寬位置（輸入框不跳動），手機什麼都不放
  const dirty = trimmed !== initial
  return (
    <Section title="個人資料" titleId="set-profile">
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
          <p id="display-name-help" className="text-sm text-ink-2 sm:col-start-1 sm:row-start-3">
            {bad ? "請填 1 到 30 個字。" : `群組裡大家看到的名字。登入帳號：${email}`}
          </p>
          {dirty ? (
            <Button type="submit" variant="sign" disabled={bad || update.isPending} className="mt-2.5 justify-self-start sm:col-start-2 sm:row-start-2 sm:mt-0">
              {update.isPending ? "儲存中…" : "儲存"}
            </Button>
          ) : (
            <span aria-hidden className={cn(buttonVariants({ variant: "sign" }), "invisible hidden sm:col-start-2 sm:row-start-2 sm:inline-flex")}>
              儲存
            </span>
          )}
        </div>
      </form>
    </Section>
  )
}
