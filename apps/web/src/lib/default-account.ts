import type { Account, Holding } from "@/api/types"

/**
 * 記帳時預設的帳戶（記一筆、完整表單、減少持股與 AI 草稿同一條規則；2026-11-14 第七次評分）：
 * ① 這一檔現在持有的帳戶 → ② 幣別和這一檔相同的帳戶 → ③ 第一個帳戶。
 * 只看第一個帳戶的話，在 Apple 的個股頁按「記一筆」會記進新台幣帳戶。
 */
export function defaultAccount(
  accounts: Account[] | undefined,
  item: { symbol?: string | null; currency?: string | null } | null | undefined,
  holdings: Holding[] | undefined,
): Account | undefined {
  if (!accounts?.length) return undefined
  const held = item?.symbol ? (holdings?.find((h) => h.symbol === item.symbol)?.account_ids ?? []) : []
  return accounts.find((a) => held.includes(a.id)) ?? (item?.currency ? accounts.find((a) => a.currency === item.currency) : undefined) ?? accounts[0]
}
