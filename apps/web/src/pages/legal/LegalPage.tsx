import { useRouterState } from "@tanstack/react-router"
import { ChevronDownIcon } from "lucide-react"
import { useEffect } from "react"
import { PlainLink } from "@/app/links"
import { PageFrame } from "@/app/PageFrame"
import { usePageTitle } from "@/app/page-title"
import { Markdown } from "@/components/markdown"
import { docSections, type DocSection } from "@/components/markdown-sections"
import { disclaimerLink } from "@/components/disclaimer"
import { SourcesFooter } from "@/components/sources"
import { DISCLAIMER_PATH, DISCLAIMER_TITLE } from "@/lib/disclaimer"
import { cn } from "@/lib/utils"
import { isDraft, stripReviewNote } from "./legal-text"
// 文件的原文在 repo 的 docs/legal（律師審閱的也是這幾個檔）；建置時整份帶進來，畫面和文件永遠是同一份
import disclaimerSource from "../../../../../docs/legal/disclaimer.md?raw"
import privacySource from "../../../../../docs/legal/privacy-policy.md?raw"
import termsSource from "../../../../../docs/legal/terms-of-service.md?raw"

export type LegalDoc = "terms" | "privacy" | "disclaimer"

const DOCS: Record<LegalDoc, { title: string; source: string }> = {
  terms: { title: "服務條款", source: termsSource },
  privacy: { title: "隱私權政策", source: privacySource },
  disclaimer: { title: DISCLAIMER_TITLE, source: disclaimerSource },
}
/** 節數多於這個才放目錄（免責聲明 5 節，一個螢幕多一點） */
const TOC_MIN_SECTIONS = 6
const PATH: Record<LegalDoc, "/terms" | "/privacy" | typeof DISCLAIMER_PATH> = { terms: "/terms", privacy: "/privacy", disclaimer: DISCLAIMER_PATH }

/**
 * 服務條款、隱私權政策、免責聲明（`/terms`、`/privacy`、`/disclaimer`）：不用登入就能讀。內容就是 `docs/legal/` 的 Markdown。
 * 文件裡還有【待填】時，最上面一行標示「草稿」（上下格線，墨色）——這時條款還沒生效，不能讓人以為已經定案。
 * 一欄好讀的寬度；最下面是全站同一個頁尾（免責的一句＋連結），連結列的前面放另外兩份文件。
 * 條款與隱私權政策都有十幾節、十幾個螢幕長：桌面（1280 以上）右邊的空白放一欄跟著捲動的目錄；
 * 手機與窄螢幕在第一節前面放一個收合的「目錄」。從別處連到某一節（`/privacy#sec-5`）時，載入後捲到那一節。
 * 免責聲明只有一個螢幕多一點：不放目錄。
 */
export function LegalPage({ doc }: { doc: LegalDoc }) {
  const { source, title } = DOCS[doc]
  const body = stripReviewNote(source)
  const sections = docSections(body)
  usePageTitle(title)
  const hash = useRouterState({ select: (s) => s.location.hash })
  // 文件是這一頁的程式載入後才畫出來的，瀏覽器自己捲不到：畫好之後捲一次
  useEffect(() => {
    if (!hash) return
    document.getElementById(hash)?.scrollIntoView({ block: "start" })
  }, [hash, doc])
  const others = (Object.keys(DOCS) as LegalDoc[]).filter((d) => d !== doc)
  const links = Object.fromEntries(others.map((d) => [DOCS[d].title, PATH[d]]))
  const toc = sections.length > TOC_MIN_SECTIONS
  return (
    <PageFrame className={cn(toc && "xl:grid xl:grid-cols-[minmax(0,51rem)_minmax(0,15rem)] xl:items-start xl:gap-x-14")}>
      <article className="max-w-measure text-[1rem] leading-[1.8] text-ink">
        {isDraft(source) && (
          <p role="note" className="mb-6 border-y border-rule py-2.5 text-md font-medium text-ink">
            草稿：這份文件還在審閱，有些項目還沒填，尚未生效。
          </p>
        )}
        <Markdown
          source={body}
          docLinks={links}
          beforeFirstSection={
            toc && (
              <details className="group mt-6 border-y border-rule xl:hidden">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between text-base font-semibold [&::-webkit-details-marker]:hidden">
                  目錄
                  <ChevronDownIcon aria-hidden className="size-4 text-ink-2 transition-transform group-open:rotate-180" />
                </summary>
                <Toc sections={sections} className="pb-3" touch />
              </details>
            )
          }
        />
        {/* 免責聲明這一頁本身就是完整的聲明：頁尾不再放免責的一句與連到自己的「免責聲明」 */}
        <SourcesFooter omit={doc === "disclaimer" ? "disclaimer" : undefined}>
          {others
            .filter((d) => d !== "disclaimer")
            .map((d) => (
              <PlainLink key={d} to={PATH[d]} className={disclaimerLink}>
                {DOCS[d].title}
              </PlainLink>
            ))}
        </SourcesFooter>
      </article>
      {toc && (
        <nav aria-label="目錄" className="sticky top-24 max-xl:hidden">
          <p className="form-head pb-2">目錄</p>
          <Toc sections={sections} className="pt-2" />
        </nav>
      )}
    </PageFrame>
  )
}

/** 節標題的清單：頁內連結。手機上每一列 44px 高（`touch`） */
function Toc({ sections, className, touch }: { sections: DocSection[]; className?: string; touch?: boolean }) {
  return (
    <ol className={cn("flex flex-col text-md", className)}>
      {sections.map((s) => (
        <li key={s.id} className={cn(touch && "border-t border-rule")}>
          <a href={`#${s.id}`} className={cn("flex items-center py-1 text-ink-2 hover:text-ink", touch && "min-h-11 py-2 text-base text-ink")}>
            {s.title}
          </a>
        </li>
      ))}
    </ol>
  )
}
