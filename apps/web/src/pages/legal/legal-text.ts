/** 文件開頭給審閱的人看的那一段引言（「本文件是草稿，供產品負責人與律師審閱…」）不放到頁面上：頁面有自己的草稿標示 */
export function stripReviewNote(source: string): string {
  return source.replace(/^(?:>[^\n]*\n)+\s*/, "")
}
/** 文件裡還有沒填的地方（【待填…】）：還是草稿，尚未生效 */
export const isDraft = (source: string) => source.includes("【待填")
