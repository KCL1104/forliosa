import { useMutation, useQueryClient } from "@tanstack/react-query"
import { qk, useMe } from "@/api/queries"
import { api } from "@/api"
import { useReadOnly } from "@/api/view-as"
import { textAction } from "@/components/text-action"
import { Button } from "@/components/ui/button"
import { LegalLinks } from "@/pages/legal/LegalLinks"

/**
 * 條款有新版本、這個帳號還沒確認時，內容最上面的一行：「服務條款與隱私權政策已更新」＋兩份文件的連結＋「知道了」。
 * 不是對話框、不擋操作：一行字、上下格線（和頁面裡其他說明同一種），按「知道了」記下這個版本之後就不再出現。
 * 沒有啟用版本（`terms_version_current` 是 null）或已經確認過就什麼都不畫。查看別人的資產時不出現。
 */
export function TermsNotice() {
  const me = useMe()
  const qc = useQueryClient()
  const readOnly = useReadOnly()
  const current = me.data?.terms_version_current
  const accept = useMutation({
    mutationFn: (version: string) => api.acceptTerms(version),
    onSuccess: (user) => qc.setQueryData(qk.me, user),
    // 版本剛好又換了（409）：重新讀個人資料，這一行會換成新的版本
    onError: () => void qc.invalidateQueries({ queryKey: qk.me }),
  })
  if (readOnly || !current || me.data?.terms_version_accepted === current) return null
  return (
    <div className="page-frame px-5 pt-3 md:px-8 xl:px-14">
      <div role="status" className="flex max-w-measure flex-wrap items-center gap-x-5 gap-y-1 border-y border-rule py-2 text-md">
        <p className="mr-auto font-medium">服務條款與隱私權政策已更新。</p>
        <p className="flex flex-wrap gap-x-4">
          <LegalLinks className={textAction} />
        </p>
        <Button variant="outline" size="sm" className="pointer-coarse:h-11" disabled={accept.isPending} onClick={() => accept.mutate(current)}>
          知道了
        </Button>
      </div>
    </div>
  )
}
