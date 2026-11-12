import { formatNumber } from "@/lib/format"

/** 實收資本額（新台幣元）→「2,593.24 億元」；不到 1 億元時「9,621 萬元」 */
export function formatCapital(n: number): string {
  if (n >= 100_000_000) return `${formatNumber(n / 100_000_000, 2)} 億元`
  return `${formatNumber(n / 10_000, 0)} 萬元`
}

/** 網址顯示：去掉 https:// 與結尾斜線（`https://www.tsmc.com/` → `www.tsmc.com`） */
export function displayHost(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "")
}

/** 美股會計年度結束日「09-26」→「9 月 26 日」 */
export function fiscalYearEnd(mmdd: string): string {
  const [m, d] = mmdd.split("-")
  return `${Number(m)} 月 ${Number(d)} 日`
}
