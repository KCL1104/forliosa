import { Link } from "@tanstack/react-router"
import { SourcesFooter } from "@/components/sources"
import { buttonVariants } from "@/components/ui/button"
import { usePageTitle } from "@/app/page-title"

export function NotFoundPage() {
  usePageTitle("找不到這個頁面")
  return (
    <div className="page-frame px-5 py-16 md:px-8 xl:px-14">
      <div className="flex flex-col items-start gap-3">
        <h1 className="text-2xl font-bold">找不到這個頁面</h1>
        <p className="max-w-prose text-base text-ink">網址可能打錯了。</p>
        <Link to="/" className={buttonVariants({ variant: "outline" })}>
          回到帳本
        </Link>
      </div>
      <SourcesFooter />
    </div>
  )
}
