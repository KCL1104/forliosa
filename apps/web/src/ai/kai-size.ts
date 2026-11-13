/**
 * 模型寫的字的大小（全站一套，和 `.ai-voice`＋`KaiText` 一起用）：
 * 一段話 17px（手機 18px）、行高 1.8——對話裡的回答、群組週報、AI 寫的公司簡介都一樣；
 * 只有一行的楷體（模型寫的「為什麼」）可以用 20px、行高 1.5。
 */
export const kaiSize = {
  /** 桌面的 AI 面板 */
  panel: "text-lg leading-[1.8]",
  /** 手機全螢幕的「問 AI」 */
  screen: "text-[1.125rem] leading-[1.8]",
  /** 頁面上的一段話：手機 18px、桌面（≥ 1024px）17px */
  page: "text-[1.125rem] leading-[1.8] lg:text-lg",
  /** 一行的楷體：20px */
  line: "text-xl leading-normal",
} as const
