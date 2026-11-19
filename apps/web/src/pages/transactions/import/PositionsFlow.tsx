import { useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useId, useRef, useState } from "react"
import { api } from "@/api"
import { useAccounts } from "@/api/queries"
import type { Account, PositionsCommitResult, PositionsImport } from "@/api/types"
import { Segmented } from "@/components/segmented"
import { textAction } from "@/components/text-action"
import { Button, buttonVariants } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { accountForBroker } from "./flags"
import { bodyClass, footerClass } from "./layout"
import { maskPlainText } from "./mask"
import { FileRow, Preview, QuotaLine, Reading } from "./parts"
import { imageError, imageStatus, isAbort, readError, useImportsLeft, type PickedImage } from "./read-utils"
import { MAX_IMAGES, MAX_PAGES, prepareImage, sniffFile } from "./prepare-image"
import { PositionsReview, type ReplacedName } from "./PositionsReview"

/**
 * 匯入庫存（產品負責人 2026-11-17，四項照建議）：券商 app「庫存」頁的截圖（一次最多 5 張），或貼上庫存的文字 →
 * 讀取中（可以取消）→ 確認表 → 簽名「匯入 N 檔」。每一檔記一筆買進（均價、手續費 0），整批可以復原。
 * - 截圖沒有文字層，塗不了，整張送出（畫面上說一句，和匯入對帳單一樣）；貼上的文字在這台裝置上先塗掉個資再送出。
 * - 不存截圖、不存文字、不存讀出的結果；只有簽名匯入的買進進帳本（來源「匯入」）。
 * - 讀出來是交易明細（不是庫存）：一句話＋「改用匯入對帳單」（截圖帶過去，不用再選一次）。
 */

export type PositionsPhase = "pick" | "reading" | "review"
/** 一次貼上最多幾個字（和後端相同） */
export const MAX_TEXT = 20_000

/** 讀的時候用哪個帳戶檢查「已在帳本」：先用第一個新台幣帳戶（讀完再照畫面上的券商換） */
const firstAccount = (accounts: Account[]) => (accounts.find((a) => a.currency === "TWD") ?? accounts[0])?.id ?? ""

/** 這批庫存的幣別：多數是哪一種（台股、複委託的美股） */
function positionsCurrency(doc: PositionsImport): "TWD" | "USD" | null {
  const usd = doc.rows.filter((r) => r.currency === "USD").length
  const twd = doc.rows.length - usd
  return doc.rows.length === 0 ? null : usd > twd ? "USD" : "TWD"
}

export function PositionsFlow({
  sheet,
  initialImages,
  onClose,
  onPhase,
  onDone,
  onSwitch,
}: {
  sheet: boolean
  /** 從匯入對帳單換過來時帶著的截圖（不用再選一次） */
  initialImages?: PickedImage[]
  onClose: () => void
  onPhase: (p: PositionsPhase) => void
  onDone: (result: PositionsCommitResult, count: number, replaced: ReplacedName[]) => void
  /** 讀出來是交易明細：改用匯入對帳單（帶著截圖） */
  onSwitch: (images: PickedImage[]) => void
}) {
  const accounts = useAccounts()
  const qc = useQueryClient()
  const [phase, setPhaseState] = useState<PositionsPhase>("pick")
  const [mode, setMode] = useState<"images" | "text">("images")
  // 從匯入對帳單帶過來的：打不開的那幾張不帶（那邊的原因說「收 PDF」，這裡不收）
  const [images, setImages] = useState<PickedImage[]>(() => (initialImages ?? []).filter((x) => !x.error))
  const [text, setText] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [doc, setDoc] = useState<PositionsImport | null>(null)
  const [readingLabel, setReadingLabel] = useState("")
  const fileRef = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const imageSeq = useRef(Math.max(0, ...(initialImages ?? []).map((x) => x.id)))
  const textId = useId()
  const textHintId = useId()
  const { left, limit } = useImportsLeft()

  const setPhase = (p: PositionsPhase) => {
    setPhaseState(p)
    onPhase(p)
  }
  useEffect(() => () => controller.current?.abort(), [])

  const reset = () => {
    controller.current?.abort()
    setImages([])
    setText("")
    setError(null)
    setDoc(null)
    setPhase("pick")
  }

  const onFiles = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    setError(null)
    const files = [...list]
    const kinds = await Promise.all(files.map((f) => sniffFile(f)))
    if (kinds.some((k) => k === "application/pdf")) {
      setError("庫存請用截圖或貼上文字。PDF 對帳單請改用「匯入對帳單」。")
      return
    }
    const room = MAX_IMAGES - images.length
    if (files.length > room) setError(`一次最多 ${MAX_IMAGES} 張，多的沒有加進來。`)
    const picked = files.slice(0, Math.max(room, 0)).map((file) => ({ id: ++imageSeq.current, file }))
    setImages((xs) => [...xs, ...picked])
    for (const p of picked) {
      try {
        const pages = await prepareImage(p.file)
        setImages((xs) => xs.map((x) => (x.id === p.id ? { ...x, pages } : x)))
      } catch (e) {
        setImages((xs) => xs.map((x) => (x.id === p.id ? { ...x, error: imageError(e, { pdf: false }) } : x)))
      }
    }
  }

  const pending = images.some((x) => !x.pages && !x.error)
  const pages = images.flatMap((x) => x.pages ?? [])
  const masked = mode === "text" ? maskPlainText(text) : null
  const ready = left !== 0 && (mode === "images" ? images.length > 0 && !pending && pages.length > 0 : text.trim().length > 0)

  const start = async () => {
    if (mode === "images" && pages.length > MAX_PAGES) {
      setError(`一次最多 ${MAX_PAGES} 張，這次有 ${pages.length} 張。少選幾張再試。`)
      return
    }
    if (mode === "text" && masked!.text.length > MAX_TEXT) {
      setError(`文字太長，一次最多 ${MAX_TEXT.toLocaleString("en-US")} 字。分成幾次貼。`)
      return
    }
    // 帳戶清單還沒載入時先等它：讀的時候檢查「已在帳本」的帳戶要是確定的那一個
    const account = firstAccount(accounts.data ?? (await accounts.refetch()).data ?? [])
    setError(null)
    setReadingLabel(mode === "images" ? `正在讀 ${pages.length} 張…` : "正在讀貼上的文字…")
    setPhase("reading")
    const ac = new AbortController()
    controller.current = ac
    try {
      const body = mode === "images" ? { account_id: account || undefined, kind: "images" as const, pages } : { account_id: account || undefined, kind: "text" as const, text: masked!.text }
      const result = await api.parsePositions(body, { signal: ac.signal })
      if (ac.signal.aborted) return
      setDoc(result)
      setPhase("review")
    } catch (e) {
      setPhase("pick")
      if (isAbort(e) || ac.signal.aborted) return
      setError(readError(e, "庫存", mode === "images" ? "截圖" : "文字"))
    } finally {
      controller.current = null
      void qc.invalidateQueries({ queryKey: ["ai", "usage"] })
    }
  }

  if (accounts.data && accounts.data.length === 0) {
    return (
      <div className={cn(bodyClass(sheet), "flex flex-col items-start gap-3")}>
        <p className="text-base text-ink">還沒有券商帳戶，先到設定建立一個。</p>
        <Link to="/settings" onClick={onClose} className={buttonVariants({ variant: "outline" })}>
          到設定
        </Link>
      </div>
    )
  }

  if (phase === "reading") return <Reading label={readingLabel} sheet={sheet} onCancel={() => controller.current?.abort()} />

  const restartLabel = mode === "images" ? "換一批截圖" : "改貼別的文字"

  if (phase === "review" && doc) {
    if (doc.rows.length === 0) {
      const toStatement = doc.document_kind === "trade_records"
      return (
        <>
          <div className={bodyClass(sheet)}>
            <p className="border-y border-rule py-5 text-base text-ink">{doc.notice || "畫面上沒有讀到持股。"}</p>
          </div>
          <div className={footerClass(sheet)}>
            <button type="button" onClick={reset} className={cn(textAction, "text-sm text-ink-2 hover:text-ink")}>
              {restartLabel}
            </button>
            <div className="ml-auto flex gap-2.5">
              <Button variant="outline" onClick={onClose}>
                取消
              </Button>
              {toStatement && <Button onClick={() => onSwitch(mode === "images" ? images : [])}>改用匯入對帳單</Button>}
            </div>
          </div>
        </>
      )
    }
    const list = accounts.data ?? []
    const initial = accountForBroker(list, doc.broker_name, doc.account_id, positionsCurrency(doc))
    return (
      <PositionsReview
        doc={doc}
        accounts={list}
        initialAccountId={initial || doc.account_id}
        sheet={sheet}
        restartLabel={restartLabel}
        onDone={onDone}
        onCancel={onClose}
        onRestart={reset}
      />
    )
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (ready) void start()
      }}
      className="flex min-h-0 flex-1 flex-col"
      noValidate
    >
      <div className={cn(bodyClass(sheet), "flex flex-col gap-4")}>
        <Segmented
          label="用什麼匯入"
          value={mode}
          onChange={(m) => {
            setMode(m)
            setError(null)
          }}
          controls="pos-input"
          options={[
            { value: "images", label: "截圖" },
            { value: "text", label: "貼上文字" },
          ]}
          className="w-full lg:w-fit"
        />
        <div id="pos-input" role="tabpanel" aria-labelledby={`tab-${mode}`} className="flex flex-col gap-4">
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="sr-only"
            tabIndex={-1}
            aria-hidden
            onChange={(e) => {
              void onFiles(e.target.files)
              e.target.value = ""
            }}
          />
          {mode === "images" ? (
            <>
              {images.length === 0 && (
                <div className="flex flex-col items-start gap-3">
                  <p className="text-base text-ink">選券商 app「庫存」頁的截圖，一次最多 5 張。持股多、要捲動的，分幾張截。</p>
                  <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
                    選截圖
                  </Button>
                </div>
              )}
              {images.length > 0 && (
                <ul className="border-y border-rule">
                  {images.map((x) => (
                    <FileRow key={x.id} name={x.file.name} status={imageStatus(x)} error={x.error} onRemove={() => setImages((xs) => xs.filter((y) => y.id !== x.id))} />
                  ))}
                </ul>
              )}
              {images.length > 0 && images.length < MAX_IMAGES && (
                <button type="button" onClick={() => fileRef.current?.click()} className={cn(textAction, "self-start")}>
                  再選一張
                </button>
              )}
              {images.length > 0 && <p className="text-base text-ink">截圖會整張送給 AI 讀。</p>}
              {pages.length > 0 && !pending && <Preview pages={pages} unit="張" />}
            </>
          ) : (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={textId} className="print-label text-sm">
                庫存的文字
              </label>
              <Textarea
                id={textId}
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={6}
                spellCheck={false}
                autoComplete="off"
                aria-describedby={textHintId}
                placeholder={"例如：\n2330 台積電 1,000 股 均價 580.5\n0050 元大台灣50 3 張 均價 150.2"}
                className="num max-h-[40dvh] min-h-36 text-base md:text-md"
              />
              <p id={textHintId} className="text-sm text-ink-2">
                從券商網頁或 app 複製庫存表貼上：代號或名稱、股數（或張數）、均價或總成本。
              </p>
              {masked && masked.masked > 0 && <p className="text-base text-ink">送出前會先塗掉 {masked.masked} 處個資。</p>}
            </div>
          )}
        </div>
        {error && (
          <p role="alert" className="text-base font-medium text-ink">
            {error}
          </p>
        )}
        <QuotaLine left={left} limit={limit} />
      </div>
      <div className={footerClass(sheet)}>
        <div className={cn("ml-auto flex gap-2.5", sheet && "w-full")}>
          <Button type="button" variant="outline" className={cn(sheet ? "flex-1" : "min-w-24")} onClick={onClose}>
            取消
          </Button>
          <Button type="submit" className={cn(sheet ? "flex-1" : "min-w-28")} disabled={!ready}>
            開始讀
          </Button>
        </div>
      </div>
    </form>
  )
}
