import { useState } from "react"
import { toast } from "sonner"
import { useMe } from "@/api/queries"
import { useUpdateMe } from "@/api/sharing-queries"
import { ApiError } from "@/api/types"
import { UserAvatar } from "@/components/avatar"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

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
  return (
    <section aria-labelledby="set-profile" className="flex flex-col gap-2">
      <h2 id="set-profile" className="border-b border-rule pb-2 text-lg font-bold">
        個人資料
      </h2>
      <form
        className="flex flex-col gap-4 py-2 sm:flex-row sm:items-end"
        onSubmit={(e) => {
          e.preventDefault()
          if (bad || trimmed === initial) return
          update.mutate(trimmed, {
            onSuccess: (u) => toast.success(`顯示名稱改為「${u.display_name}」`),
            onError: (err) => toast.error("名稱沒有更新", { description: err instanceof ApiError ? err.message : undefined }),
          })
        }}
      >
        <UserAvatar name={trimmed || initial} url={avatar} size="lg" />
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor="display-name" className="text-sm font-medium">
            顯示名稱
          </label>
          <Input id="display-name" value={name} maxLength={30} autoComplete="nickname" aria-invalid={bad} aria-describedby="display-name-help" onChange={(e) => setName(e.target.value)} />
          <p id="display-name-help" className="text-sm text-ink-2">
            {bad ? "請填 1 到 30 個字。" : `群組裡大家看到的名字。登入帳號：${email}`}
          </p>
        </div>
        <Button type="submit" variant="sign" disabled={bad || trimmed === initial || update.isPending} className="self-start sm:mb-6 sm:self-auto">
          {update.isPending ? "儲存中…" : "儲存"}
        </Button>
      </form>
    </section>
  )
}
