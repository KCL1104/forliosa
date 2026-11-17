import { createContext, useContext } from "react"

/**
 * 一份報告畫面裡共用的東西：註腳的錨點前綴（同一頁並排兩份報告時不撞名）、管理員檢視（每句後面多 refs）、
 * 手機上收合的段落（點註腳回到原句時，原句所在的段要先打開）。
 */
export interface ReportCtx {
  /** 錨點前綴：註腳是 `${prefix}fn-3`，原句是 `${prefix}fnref-3` */
  prefix: string
  admin: boolean
  /** 打開某一段（手機上收著的段） */
  openSection(key: string): void
}

export const ReportContext = createContext<ReportCtx>({ prefix: "", admin: false, openSection: () => {} })
export const useReport = () => useContext(ReportContext)

/**
 * 捲到報告裡的某個元素（置中、不改網址）並把焦點放過去：上面有 sticky 的頂部列與分頁列，置中才看得到。
 * 本來就能用 Tab 走到的元素（原句的出處連結）不動它的 tabindex；不能的（註腳的那一條）暫時加 `tabindex=-1`，
 * 離開時拿掉，所以來回跳過以後 Tab 的順序不變。
 */
export function jumpTo(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ block: "center", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })
  if (!el.hasAttribute("tabindex") && !el.matches("a[href], button, input, select, textarea")) {
    el.setAttribute("tabindex", "-1")
    el.addEventListener("blur", () => el.removeAttribute("tabindex"), { once: true })
  }
  el.focus({ preventScroll: true })
}

/**
 * 規則寫的標題以「盤前重點 11/18（三）：」「市場週報 11/16–11/20：」開頭（推播要用）；畫面上前面已經有報告名稱與日期，
 * 拿掉這一段不重複。只認「報告名稱＋空格＋日期＋全形冒號」，AI 寫的標題不會這樣開頭。
 */
export function titleBody(kindLabel: string, title: string): string {
  if (!title.startsWith(`${kindLabel} `)) return title
  const m = /^[\d/（）()一二三四五六日–-]+：/.exec(title.slice(kindLabel.length + 1))
  const rest = m ? title.slice(kindLabel.length + 1 + m[0].length) : title
  return rest.trim() ? rest : title
}

/** 驗證器的問題代碼 → 白話（管理員檢視；認不得的照原文） */
const PROBLEM_TEXT: Record<string, string> = {
  bad_ref: "引用的編號不在資料包",
  no_refs: "句子沒有出處",
  number_unsourced: "數字對不到出處",
  number_subject_mismatch: "數字和主體對不上",
  forbidden_word: "用了禁用字",
  direction_mismatch: "漲跌方向和資料相反",
  date_not_sourced: "日期沒有出處",
  weekday_mismatch: "星期和日期不合",
  stock_not_allowed: "寫了名單外的股票",
  sector_not_allowed: "寫了不能談的類股",
  flow_and_move: "法人買賣和漲跌寫在同一句",
  cause_without_source: "寫了原因但沒有報導出處",
  outlook_pattern: "講之後的事但不是允許的句型",
  options_as_reason: "把選擇權或期貨部位當理由",
  repeats_close_report: "盤前重講前一天的盤後數字",
  chart_invalid: "今日圖不在選單裡",
  index_points: "寫了指數點數",
  stock_item_mismatch: "個股段落開頭不是那一檔",
  item_not_event: "項目不是行事曆或報導裡的事件",
  internal_gap: "正文寫了這份缺什麼資料",
  us_local_time: "美國時間沒有附台北時間",
}
export function problemText(code: string): string {
  if (code.startsWith("compliance:")) return `合規判讀：${code.slice("compliance:".length)}`
  return PROBLEM_TEXT[code] ?? code
}
