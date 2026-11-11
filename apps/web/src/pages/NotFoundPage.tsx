import { Link } from "@tanstack/react-router"
import { buttonVariants } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <div className="flex max-w-md flex-col items-start gap-3 py-16">
      <h1 className="text-2xl font-semibold">找不到這個頁面</h1>
      <p className="text-muted-foreground">網址可能打錯了，或這個頁面已經移動。可以回到總覽，或用 ⌘K 搜尋股票。</p>
      <Link to="/" className={buttonVariants({ variant: "outline" })}>
        回到總覽
      </Link>
    </div>
  )
}
