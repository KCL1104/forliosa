const LATIN = /[A-Za-z0-9]/

/**
 * 把名稱放進中文句子裡：名稱的頭或尾是英數字時，和旁邊的中文之間留一個半形空白
 * （「找到 Apple 的報導」「元大台灣50 的配息」）；中文名稱不加（「台積電的配息」）。
 * 句子開頭的名稱用 `start`（前面不加空白）。
 */
export function inText(name: string, at: "middle" | "start" | "end" = "middle"): string {
  const before = at !== "start" && LATIN.test(name[0] ?? "") ? " " : ""
  const after = at !== "end" && LATIN.test(name.at(-1) ?? "") ? " " : ""
  return `${before}${name}${after}`
}
