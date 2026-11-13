import { Fragment } from "react"
import { kaiRuns } from "./answer-text"

/**
 * 模型寫的字（放在 `.ai-voice` 裡）：漢字的片段收字距（`.kai-han`），數字和單位連成一段、不在行尾拆開（`.kai-num`）。
 * 其他頁面的模型文字（個股的「為什麼」、公司簡介、群組週報）也可以用它。
 */
export function KaiText({ text }: { text: string }) {
  return (
    <>
      {kaiRuns(text).map((r, i) =>
        r.kind === "plain" ? (
          <Fragment key={i}>{r.text}</Fragment>
        ) : (
          <span key={i} className={r.kind === "num" ? "kai-num" : "kai-han"}>
            {r.text}
          </span>
        ),
      )}
    </>
  )
}
