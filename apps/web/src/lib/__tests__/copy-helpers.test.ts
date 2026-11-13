import { describe, expect, it } from "vitest"
import { pageTitle } from "@/app/page-title"
import { docSections } from "@/components/markdown-sections"
import { ABOUT_FORLIOSA } from "@/lib/about"
import { inText } from "@/lib/cjk"
import { isCoverageNote } from "@/lib/data-notes"
import { stripReviewNote } from "@/pages/legal/legal-text"

describe("名稱放進中文句子：英數字和中文之間留一個空白", () => {
  it("英文名稱前後加空白；中文名稱不加；開頭、結尾各只加一邊", () => {
    expect(`找到${inText("Apple")}的報導`).toBe("找到 Apple 的報導")
    expect(`找到${inText("台積電")}的報導`).toBe("找到台積電的報導")
    expect(`${inText("Vanguard S&P 500 ETF", "start")}沒有報價`).toBe("Vanguard S&P 500 ETF 沒有報價")
    expect(`看${inText("NVIDIA", "end")}`).toBe("看 NVIDIA")
    // 結尾是數字的中文名稱：只有接數字那一邊加
    expect(`是${inText("元大台灣50")}定期定額`).toBe("是元大台灣50 定期定額")
    expect(inText("")).toBe("")
  })
})

describe("後端 notes 裡「資料從哪天開始」的那一類", () => {
  it("新的寫法、淨值的寫法、還沒有資料；舊版後端的寫法也認得；算法說明不算", () => {
    expect(isCoverageNote("資料從 2026/06/01 開始")).toBe(true)
    expect(isCoverageNote("資料從 2026/06/01 開始；持股期間有幾天沒有收盤價，績效算不出來")).toBe(true)
    expect(isCoverageNote("淨值資料從 2026/11/03 開始")).toBe(true)
    expect(isCoverageNote("還沒有資料")).toBe(true)
    expect(isCoverageNote("資料累積中：自 2026-06-01 起存檔")).toBe(true)
    expect(isCoverageNote("EPS = 收盤價 ÷ 本益比")).toBe(false)
    expect(isCoverageNote("美股沒有報價")).toBe(false)
  })
})

describe("分頁標題", () => {
  it("頁名在前、站名在後；沒有頁名只有站名", () => {
    expect(pageTitle("台積電 2330")).toBe("台積電 2330｜Forliosa")
    expect(pageTitle(null)).toBe("Forliosa")
    expect(pageTitle("")).toBe("Forliosa")
  })
})

describe("條款文件的節", () => {
  it("有編號的是 sec-N；沒有編號的第一節是 sec-top", () => {
    const md = "# 標題\n\n前言\n\n## 重點先講\n\n- a\n\n## 1. 本服務是什麼\n\n內文\n\n### 1.1 小節\n\n## 2. **不是**投資建議\n"
    expect(docSections(md)).toEqual([
      { id: "sec-top", title: "重點先講" },
      { id: "sec-1", title: "1. 本服務是什麼" },
      { id: "sec-2", title: "2. 不是投資建議" },
    ])
  })
  it("給審閱者看的引言與「草稿日期」那一行不放到頁面上", () => {
    const md = "> 本文件是草稿。\n\n# 標題\n\n- 生效日期：【待填：生效日期】\n- 草稿日期：2026-11-13（依當天的程式與文件撰寫）\n\n內文"
    expect(stripReviewNote(md)).toBe("# 標題\n\n- 生效日期：【待填：生效日期】\n\n內文")
  })
})

describe("Forliosa 是什麼的那一句", () => {
  it("只說事實：沒有破折號、沒有冒號後面的功能清單", () => {
    expect(ABOUT_FORLIOSA).toBe("Forliosa 是股票帳本，可以記買賣、看績效、查個股、問 AI，也能和親友開群組。")
    expect(ABOUT_FORLIOSA).not.toMatch(/[—：]/)
  })
})
