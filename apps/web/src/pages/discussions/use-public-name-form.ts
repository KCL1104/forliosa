import { useState } from "react"
import { toast } from "sonner"
import { useSetPublicName } from "@/api/discussion-queries"
import type { User } from "@/api/types"
import { publicNameProblem } from "@/lib/discussion-text"
import { publicNameErrorText } from "./labels"

/**
 * 選公開暱稱的表單狀態（第一次選、設定頁修改共用）：送出前先照合約的規則檢查（2–20 字、一行、不能含保留字），
 * 伺服器的 409（已經有人用、7 天內改過）就地寫成一句話。
 */
export function usePublicNameForm(initial: string, onDone?: (user: User) => void) {
  const save = useSetPublicName()
  const [name, setName] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const trimmed = name.trim()
  const submit = () => {
    if (save.isPending) return
    const problem = publicNameProblem(name)
    if (problem) return setError(problem)
    setError(null)
    save.mutate(trimmed, {
      onSuccess: (user) => {
        toast.success(`公開暱稱是「${user.public_name ?? trimmed}」`)
        onDone?.(user)
      },
      onError: (err) => setError(publicNameErrorText(err)),
    })
  }
  return {
    name,
    trimmed,
    error,
    pending: save.isPending,
    submit,
    change: (v: string) => {
      setName(v)
      if (error) setError(null)
    },
  }
}
