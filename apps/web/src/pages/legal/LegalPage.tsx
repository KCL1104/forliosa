import { PlainLink } from "@/app/links"
import { PageFrame } from "@/app/PageFrame"
import { Markdown } from "@/components/markdown"
import { textAction } from "@/components/text-action"
import { cn } from "@/lib/utils"
import { isDraft, stripReviewNote } from "./legal-text"
// 文件的原文在 repo 的 docs/legal（律師審閱的也是這兩個檔）；建置時整份帶進來，畫面和文件永遠是同一份
import privacySource from "../../../../../docs/legal/privacy-policy.md?raw"
import termsSource from "../../../../../docs/legal/terms-of-service.md?raw"

export type LegalDoc = "terms" | "privacy"

const DOCS: Record<LegalDoc, { title: string; source: string; other: LegalDoc }> = {
  terms: { title: "服務條款", source: termsSource, other: "privacy" },
  privacy: { title: "隱私權政策", source: privacySource, other: "terms" },
}
const PATH: Record<LegalDoc, "/terms" | "/privacy"> = { terms: "/terms", privacy: "/privacy" }

/**
 * 服務條款、隱私權政策（`/terms`、`/privacy`）：不用登入就能讀。內容就是 `docs/legal/` 的兩份 Markdown。
 * 文件裡還有【待填】時，最上面一行標示「草稿」（上下格線，墨色）——這時條款還沒生效，不能讓人以為已經定案。
 * 一欄好讀的寬度；最下面連到另一份文件。
 */
export function LegalPage({ doc }: { doc: LegalDoc }) {
  const { source, other } = DOCS[doc]
  return (
    <PageFrame>
      <article className="max-w-measure text-[1rem] leading-[1.8] text-ink">
        {isDraft(source) && (
          <p role="note" className="mb-6 border-y border-rule py-2.5 text-md font-medium text-ink">
            草稿：這份文件還在審閱，有些項目還沒填，尚未生效。
          </p>
        )}
        <Markdown source={stripReviewNote(source)} />
        <p className="mt-12 border-t border-rule pt-4 text-md text-ink-2">
          另見
          <PlainLink to={PATH[other]} className={cn(textAction, "ml-2")}>
            {DOCS[other].title}
          </PlainLink>
        </p>
      </article>
    </PageFrame>
  )
}
