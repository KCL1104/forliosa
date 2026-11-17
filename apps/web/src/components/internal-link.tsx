import { Link } from "@tanstack/react-router"

/**
 * 伺服器給的站內連結（市場報告的 `href`：`/stock/2330.TW`、`/market/reports/mrp_…`）變成路由的 `<Link>`：
 * 換頁不重新載入整個網站。認不得的站內路徑用一般的 `<a>`（照樣是站內，不另開視窗）。
 */
export function InternalLink({ href, className, children, ...rest }: { href: string; className?: string; children: React.ReactNode } & Omit<React.ComponentProps<"a">, "href" | "className" | "children">) {
  const stock = /^\/stock\/([^/?#]+)$/.exec(href)
  if (stock) {
    return (
      <Link to="/stock/$symbol" params={{ symbol: decodeURIComponent(stock[1]!) }} className={className} {...rest}>
        {children}
      </Link>
    )
  }
  const report = /^\/market\/reports\/([^/?#]+)$/.exec(href)
  if (report) {
    return (
      <Link to="/market/reports/$reportId" params={{ reportId: decodeURIComponent(report[1]!) }} className={className} {...rest}>
        {children}
      </Link>
    )
  }
  return (
    <a href={href} className={className} {...rest}>
      {children}
    </a>
  )
}
