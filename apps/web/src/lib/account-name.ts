/**
 * 比對輸入的帳戶名稱：不管全形半形、空白與大小寫，連字號與間隔號的各種寫法當成一樣
 * （「永豐－一般」打成「永豐-一般」、「永豐・一般」打成「永豐‧一般」都算對；手機鍵盤打不出全形的「－」）。
 */
export function sameAccountName(typed: string, name: string): boolean {
  const norm = (s: string) =>
    s
      .normalize("NFKC")
      .replace(/\s+/g, "")
      .replace(/[‐‑‒–—―−-]/g, "-")
      .replace(/[·‧・･•∙]/g, "·")
      .toLowerCase()
  return norm(typed) !== "" && norm(typed) === norm(name)
}
