/**
 * 免責的文字：全站只有這一份（產品負責人 2026-11-17：「清楚標示我們只是替使用者整理資訊，不是在為他們做投顧服務」）。
 *
 * - 後端有同樣的字：`apps/api/src/forliosa/disclaimer.py`（推播、`done.disclaimer`、週報與日報的 `disclaimer`、
 *   法人觀點的 `disclaimer`）。改這裡的字時兩邊一起改；後端的測試（`tests/test_disclaimer.py`）會比對兩邊是否一樣。
 * - 完整的聲明在 `docs/legal/disclaimer.md`（`/disclaimer` 這一頁就是那份檔案），條文在〈服務條款〉第 2 節。
 * - 畫面上用 `components/disclaimer.tsx` 的 `<Disclaimer>`（13px 淡墨），不要在元件裡另寫一句。
 *
 * 每一個畫面區塊最多一句，不用對話框、不用橫幅。
 */
export const DISCLAIMER = {
  /** 全站的一句：頁尾、介紹頁、登入頁、邀請頁、推播、匯出檔 */
  short: "Forliosa 只替你整理公開資訊與你自己的紀錄，不是投資顧問，不提供投資建議；投資決定請自己判斷。",
  /** AI 寫的內容下面：對話的回答、收盤重點、收盤簡報、群組週報與日報、模型寫的「為什麼漲跌」 */
  ai: "AI 只替你整理資訊，可能有錯；Forliosa 不是投資顧問，不提供投資建議。",
  /** 法人觀點（第三方機構的評等與目標價，放在清單上面；後端 `analyst-views` 的 `disclaimer` 是同一句） */
  analyst: "以下是媒體報導的第三方機構看法，可能不完整或未經授權轉載；Forliosa 只替你整理，不代表本站意見，也不是投資建議。",
  /** 個股頁的新聞報導（媒體的標題與連結） */
  news: "標題與內容由各媒體負責；Forliosa 只替你整理連結，不是投資建議。",
  /** 討論區與群組裡使用者自己寫的內容 */
  userContent: "使用者言論，不代表本站立場，也不是投資建議。",
} as const

export type DisclaimerKind = keyof typeof DISCLAIMER

/** 完整聲明的頁面（不用登入就能讀） */
export const DISCLAIMER_PATH = "/disclaimer"
/** 連到完整聲明的連結文字、那一頁的標題 */
export const DISCLAIMER_TITLE = "免責聲明"
