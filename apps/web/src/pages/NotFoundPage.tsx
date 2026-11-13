import { Link } from "@tanstack/react-router"
import { buttonVariants } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <div className="page-frame flex flex-col items-start gap-3 px-5 py-16 md:px-8 xl:px-14">
      <h1 className="text-2xl font-bold">找不到這個頁面</h1>
      <p className="max-w-prose text-ink-2">網址可能打錯了，或這個頁面已經移動。可以回到帳本，或用 ⌘K 搜尋股票。</p>
      <Link to="/" className={buttonVariants({ variant: "outline" })}>
        回到帳本
      </Link>
    </div>
  )
}
