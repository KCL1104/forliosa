/**
 * 模型寫的字的大小（全站一套，和 `.ai-voice`＋`KaiText` 一起用；名稱是楷體時代留下的，字型現在是黑體）：
 * 一段話 16px（手機 17px）、行高 1.8——對話裡的回答、群組週報、AI 寫的公司簡介都一樣；
 * 只有一行的句子（模型寫的「為什麼」、收盤重點的標題）用 20px、行高 1.5。
 */
export const kaiSize = {
  /** 桌面的 AI 面板 */
  panel: "text-[1rem] leading-[1.8]",
  /** 手機全螢幕的「問 AI」 */
  screen: "text-lg leading-[1.8]",
  /** 頁面上的一段話：手機 17px、桌面（≥ 1024px）16px */
  page: "text-lg leading-[1.8] lg:text-[1rem]",
  /** 一行的句子：20px */
  line: "text-xl leading-normal",
} as const
