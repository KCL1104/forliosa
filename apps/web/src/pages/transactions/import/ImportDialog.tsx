import { useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { useEffect, useId, useRef, useState } from "react"
import { toast } from "sonner"
import { api } from "@/api"
import { useAccounts, useDeleteTransactionBatch } from "@/api/queries"
import type { Account, ImportPage, PositionsCommitResult, StatementImport, TransactionBatchResult } from "@/api/types"
import { useUi, type ImportKind } from "@/app/ui-store"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button, buttonVariants } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { useIsDesktop } from "@/hooks/use-media-query"
import { cn } from "@/lib/utils"
import { accountForBroker, statementCurrency, unsupportedLine } from "./flags"
import { ImportChooser } from "./ImportChooser"
import { bodyClass, footerClass } from "./layout"
import { FileRow, Preview, QuotaLine, Reading } from "./parts"
import { imageError, imageStatus, isAbort, readError, useImportsLeft, type PickedImage } from "./read-utils"
import { PositionsFlow } from "./PositionsFlow"
import type { ReplacedName } from "./PositionsReview"
import { MAX_IMAGES, MAX_PAGES, prepareImage, sniffFile } from "./prepare-image"
import { openPdf, PdfOpenError, PdfPasswordError, preparePdf } from "./prepare-pdf"
import { ReviewTable } from "./ReviewTable"
import { replacedText, runUndo, useImportUndo } from "./undo-store"

/**
 * 匯入（產品負責人 2026-11-16 匯入對帳單、11-17 匯入庫存）。桌面是對話框、手機是抽屜。
 * 第一步先選要匯入什麼（`ImportChooser`）：匯入庫存（現有持股，最快）或匯入對帳單（交易明細）；選了之後在同一個對話框裡接下去。
 *
 * 匯入對帳單：選檔案 →（PDF 有密碼就輸入）→ 開始讀（10–40 秒，可以取消）→ 確認表 → 簽名「匯入 N 筆」→ 通知「已匯入 N 筆」＋復原。
 * - PDF：在這台裝置上用 pdf.js 解密、畫成圖、塗掉找得到的個資，只送出圖和塗過的文字（密碼與原始檔不離開裝置）。
 * - 截圖、照片：JPEG／PNG／WebP，一次最多 5 張；很長的截圖切成好幾塊。截圖沒有文字層，塗不了，整張送出（畫面上說一句）。
 * - 不存檔案、不存讀出的結果；只有簽名匯入的交易進帳本（來源「匯入」），可以整批復原。
 * 匯入庫存：見 `PositionsFlow`。讀出來是另一種的（庫存畫面丟進匯入對帳單、交易明細丟進匯入庫存），一個按鈕換過去、截圖帶著走。
 */
export function ImportDialog() {
  const open = useUi((s) => s.importOpen)
  const requested = useUi((s) => s.importKind)
  const close = useUi((s) => s.closeImport)
  const isDesktop = useIsDesktop()
  const undo = useDeleteTransactionBatch()
  const askUndo = useImportUndo((s) => s.ask)
  const [phase, setPhase] = useState<Phase>("pick")
  const [kind, setKind] = useState<ImportKind>(requested)
  /** 換到另一種匯入時帶過去的截圖 */
  const [carry, setCarry] = useState<PickedImage[] | undefined>(undefined)
  // 每次打開都是新的一份（關掉時丟掉選的檔案、密碼與讀出來的表）
  const [session, setSession] = useState(0)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setSession((n) => n + 1)
      setPhase("pick")
      setKind(requested)
      setCarry(undefined)
    }
  }
  /** 對話框裡現在這一步（換成另一種匯入時，焦點移到新的第一個控制項：按過的那一列已經不在了） */
  const flowRef = useRef<HTMLDivElement>(null)
  const choose = (k: "positions" | "statement", images?: PickedImage[]) => {
    // 按過的那一列馬上會被拿掉。焦點還在它上面時被拿掉，對話框的焦點管理會在下一個畫面把焦點拉回對話框本身，
    // 蓋掉下面移到第一個控制項的那一下：先把焦點放在這一步的外框（還在對話框裡），它就不會去拉
    flowRef.current?.focus({ preventScroll: true })
    setCarry(images)
    setKind(k)
    setPhase("pick")
    setSession((n) => n + 1)
    requestAnimationFrame(() =>
      flowRef.current?.querySelector<HTMLElement>('button:not([disabled]):not([tabindex="-1"]), textarea, input:not([type=file]):not([tabindex="-1"])')?.focus(),
    )
  }

  const wide = phase === "review"
  const title = kind === "choose" ? "匯入" : kind === "positions" ? "匯入庫存" : "匯入對帳單"
  const description =
    kind === "choose"
      ? "選要匯入現有持股（庫存），還是交易明細（對帳單）。"
      : kind === "positions"
        ? // 對話框的說明（報讀器念）只留可以匯入什麼（2026-11-21 評論：「AI 讀成一張表…簽名之後」是在敘述流程，簽名格在畫面上）
          "券商 app 庫存頁的截圖，或庫存的文字"
        : "PDF 對帳單，或成交明細的截圖"
  const width = kind === "choose" ? "sm:max-w-[520px]" : !wide ? "sm:max-w-[560px]" : kind === "positions" ? "sm:max-w-[min(880px,calc(100%-4rem))]" : "sm:max-w-[min(1000px,calc(100%-4rem))]"

  const doneStatement = (res: TransactionBatchResult, count: number) => {
    toast.success(`已匯入 ${count} 筆`, {
      description: res.auto_dividends_added > 0 ? `另外自動記了 ${res.auto_dividends_added} 筆股利。` : undefined,
      duration: 10_000,
      action: { label: "復原", onClick: () => runUndo(undo.mutateAsync, res.batch_id) },
    })
    close()
  }
  // 換成券商刪掉了舊紀錄：通知照實寫，「復原」先問一次（舊紀錄回不來）
  const donePositions = (res: PositionsCommitResult, count: number, replaced: ReplacedName[]) => {
    const lines = [
      replaced.length ? `換成券商刪掉了${replacedText(replaced)}舊紀錄。` : "",
      res.auto_dividends_added > 0 ? `另外自動記了 ${res.auto_dividends_added} 筆股利。` : "",
    ].filter(Boolean)
    toast.success(`已匯入 ${count} 檔`, {
      description: lines.length ? lines.join("") : undefined,
      duration: 10_000,
      action: {
        label: "復原",
        onClick: () => (replaced.length ? askUndo({ batchId: res.batch_id, count: res.created.length, replaced }) : runUndo(undo.mutateAsync, res.batch_id)),
      },
    })
    close()
  }

  const flow = (sheet: boolean) =>
    open &&
    (kind === "choose" ? (
      <ImportChooser key={session} sheet={sheet} onPick={(k) => choose(k)} onCancel={close} />
    ) : kind === "positions" ? (
      <PositionsFlow key={session} sheet={sheet} initialImages={carry} onClose={close} onPhase={setPhase} onDone={donePositions} onSwitch={(imgs) => choose("statement", imgs)} />
    ) : (
      <ImportFlow key={session} sheet={sheet} initialImages={carry} onClose={close} onPhase={setPhase} onDone={doneStatement} onSwitch={(imgs) => choose("positions", imgs)} />
    ))

  if (isDesktop) {
    return (
      // 讀取中、核對中不因為點到外面就關掉（表格改到一半會不見）；Esc 與「取消」照常
      <Dialog open={open} onOpenChange={(o) => !o && close()} disablePointerDismissal={phase !== "pick"}>
        <DialogContent className={cn("flex max-h-[calc(100dvh-4rem)] flex-col gap-0 overflow-hidden p-0", width)}>
          <DialogHeader className="px-6 pt-5 pb-4">
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="sr-only">{description}</DialogDescription>
          </DialogHeader>
          <div ref={flowRef} tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
            {flow(false)}
          </div>
        </DialogContent>
      </Dialog>
    )
  }
  return (
    <Drawer open={open} onOpenChange={(o) => !o && close()} repositionInputs={false} dismissible={phase === "pick"}>
      <DrawerContent className="data-[vaul-drawer-direction=bottom]:max-h-[92dvh]">
        <DrawerHeader className="pb-2">
          <DrawerTitle>{title}</DrawerTitle>
          <DrawerDescription className="sr-only">{description}</DrawerDescription>
        </DrawerHeader>
        <div ref={flowRef} tabIndex={-1} className="flex min-h-0 flex-1 flex-col outline-none">
          {flow(true)}
        </div>
      </DrawerContent>
    </Drawer>
  )
}

type Phase = "pick" | "reading" | "review"

interface PickedPdf {
  file: File
  status: "opening" | "locked" | "preparing" | "ready"
  pages?: ImportPage[]
  masked?: number
  scanned?: number
  /** 密碼打錯 */
  wrongPassword?: boolean
  /** 正在用輸入的密碼打開（密碼欄留著，不跳動） */
  checking?: boolean
}

/** 讀檔時用哪個帳戶驗算賣超、重複：只有一個就是它；好幾個時先用第一個新台幣帳戶（讀完再照對帳單上的券商換） */
const firstAccount = (accounts: Account[]) => (accounts.find((a) => a.currency === "TWD") ?? accounts[0])?.id ?? ""

function ImportFlow({
  sheet,
  initialImages,
  onClose,
  onPhase,
  onDone,
  onSwitch,
}: {
  sheet: boolean
  /** 從匯入庫存換過來時帶著的截圖 */
  initialImages?: PickedImage[]
  onClose: () => void
  onPhase: (p: Phase) => void
  onDone: (result: TransactionBatchResult, count: number) => void
  /** 讀出來是庫存畫面：改用匯入庫存（帶著截圖） */
  onSwitch: (images: PickedImage[]) => void
}) {
  const accounts = useAccounts()
  const qc = useQueryClient()
  const [phase, setPhaseState] = useState<Phase>("pick")
  const [pdf, setPdf] = useState<PickedPdf | null>(null)
  const [images, setImages] = useState<PickedImage[]>(initialImages ?? [])
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [doc, setDoc] = useState<{ result: StatementImport; account: string } | null>(null)
  const [readingPages, setReadingPages] = useState({ count: 0, unit: "頁" })
  const fileRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const imageSeq = useRef(Math.max(0, ...(initialImages ?? []).map((x) => x.id)))
  /** 換了檔案或按了移除：還在打開、準備的那一份就不要再寫回畫面 */
  const pdfSeq = useRef(0)
  const { left, limit } = useImportsLeft()

  const setPhase = (p: Phase) => {
    setPhaseState(p)
    onPhase(p)
  }
  // 關掉對話框：還在讀的就取消
  useEffect(() => () => controller.current?.abort(), [])

  const reset = () => {
    controller.current?.abort()
    pdfSeq.current++
    setPdf(null)
    setImages([])
    setPassword("")
    setError(null)
    setDoc(null)
    setPhase("pick")
  }

  // ── 選檔案 ──
  const onFiles = async (list: FileList | null) => {
    if (!list || list.length === 0) return
    setError(null)
    const files = [...list]
    const kinds = await Promise.all(files.map((f) => sniffFile(f)))
    const pdfs = files.filter((_, i) => kinds[i] === "application/pdf")
    if (pdfs.length > 0) {
      if (files.length > 1 || images.length > 0) {
        setError("一次匯入一份 PDF，或最多 5 張截圖，不能混在一起。")
        return
      }
      setImages([])
      setPassword("")
      void openAndPrepare(pdfs[0]!)
      return
    }
    if (pdf) {
      pdfSeq.current++
      setPdf(null)
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
        setImages((xs) => xs.map((x) => (x.id === p.id ? { ...x, error: imageError(e) } : x)))
      }
    }
  }

  /** 打開 PDF（有密碼就停下來問）→ 畫成圖、塗掉個資。`then`：準備好之後直接開始讀（輸入密碼後按的「開始讀」） */
  const openAndPrepare = async (file: File, pw?: string, then?: "read") => {
    const mine = ++pdfSeq.current
    const current = () => pdfSeq.current === mine
    setPdf(pw ? { file, status: "locked", checking: true } : { file, status: "opening" })
    try {
      const d = await openPdf(file, pw)
      try {
        if (!current()) return
        if (d.numPages > MAX_PAGES) {
          setPdf(null)
          setError(`這份 PDF 有 ${d.numPages} 頁，一次最多 ${MAX_PAGES} 頁。`)
          return
        }
        setPdf({ file, status: "preparing" })
        const prepared = await preparePdf(d, { maxPages: MAX_PAGES })
        if (!current()) return
        const ready: PickedPdf = { file, status: "ready", pages: prepared.pages, masked: prepared.masked, scanned: prepared.scannedPages }
        setPdf(ready)
        setPassword("")
        // 掃描的 PDF 塗不了：先停下來讓使用者看到那一句，再按一次才送出
        if (then === "read" && prepared.scannedPages === 0) void start(ready, [])
      } finally {
        void d.loadingTask.destroy()
      }
    } catch (e) {
      if (!current()) return
      if (e instanceof PdfPasswordError) {
        setPdf({ file, status: "locked", wrongPassword: e.reason === "incorrect" })
        // 打錯時選取整串，直接重打
        requestAnimationFrame(() => {
          passwordRef.current?.focus()
          passwordRef.current?.select()
        })
        return
      }
      setPdf(null)
      setError(e instanceof PdfOpenError ? "這個 PDF 打不開，可能壞掉了。" : "這個 PDF 打不開，再試一次。")
    }
  }

  const pagesNow = (p: PickedPdf | null, imgs: PickedImage[]) => (p ? (p.pages ?? []) : imgs.flatMap((x) => x.pages ?? []))
  const pendingImages = images.some((x) => !x.pages && !x.error)
  const allPages = pagesNow(pdf, images)
  const outOfImports = left === 0
  const ready =
    !outOfImports && (pdf ? pdf.status === "ready" || (pdf.status === "locked" && !pdf.checking && password.length > 0) : images.length > 0 && !pendingImages && allPages.length > 0)

  // ── 開始讀 ──
  const start = async (p: PickedPdf | null = pdf, imgs: PickedImage[] = images) => {
    const pages = pagesNow(p, imgs)
    if (pages.length === 0) return
    if (pages.length > MAX_PAGES) {
      setError(`一次最多 ${MAX_PAGES} 頁，這次有 ${pages.length} 頁。少選幾張再試。`)
      return
    }
    // 帳戶清單還沒載入時先等它：讀檔時驗算的帳戶要是確定的那一個（確認表照它判斷要不要換帳戶重算）
    const account = firstAccount(accounts.data ?? (await accounts.refetch()).data ?? [])
    setError(null)
    setReadingPages({ count: pages.length, unit: p ? "頁" : "張" })
    setPhase("reading")
    const ac = new AbortController()
    controller.current = ac
    try {
      const result = await api.parseStatement({ account_id: account || undefined, kind: p ? "pdf" : "images", pages }, { signal: ac.signal })
      if (ac.signal.aborted) return
      setDoc({ result, account })
      setPhase("review")
    } catch (e) {
      if (isAbort(e) || ac.signal.aborted) {
        setPhase("pick")
        return
      }
      setError(readError(e))
      setPhase("pick")
    } finally {
      controller.current = null
      void qc.invalidateQueries({ queryKey: ["ai", "usage"] })
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!ready) return
    if (pdf?.status === "locked") void openAndPrepare(pdf.file, password, "read")
    else void start()
  }

  if (accounts.data && accounts.data.length === 0) {
    return (
      <div className={cn(bodyClass(sheet), "flex flex-col items-start gap-3")}>
        <p className="text-base text-ink">還沒有券商帳戶</p>
        <Link to="/settings" onClick={onClose} className={buttonVariants({ variant: "outline" })}>
          到設定
        </Link>
      </div>
    )
  }

  if (phase === "reading") {
    return <Reading label={`正在讀 ${readingPages.count} ${readingPages.unit}…`} sheet={sheet} onCancel={() => controller.current?.abort()} />
  }

  if (phase === "review" && doc) {
    const unsupported = unsupportedLine(doc.result)
    if (unsupported) {
      // 庫存畫面：改用匯入庫存（截圖帶過去，不用再選一次）
      const toPositions = doc.result.document_kind === "holdings_snapshot"
      return (
        <>
          <div className={bodyClass(sheet)}>
            <p className="border-y border-rule py-5 text-base text-ink">{unsupported}</p>
          </div>
          <div className={footerClass(sheet)}>
            {toPositions && (
              <button type="button" onClick={reset} className={cn(textAction, "text-sm text-ink-2 hover:text-ink")}>
                換一個檔案
              </button>
            )}
            <div className="ml-auto flex gap-2.5">
              <Button variant="outline" onClick={onClose}>
                取消
              </Button>
              {toPositions ? <Button onClick={() => onSwitch(pdf ? [] : images)}>改用匯入庫存</Button> : <Button onClick={reset}>換一個檔案</Button>}
            </div>
          </div>
        </>
      )
    }
    const list = accounts.data ?? []
    const initial = accountForBroker(list, doc.result.broker_name, doc.account, statementCurrency(doc.result))
    return (
      <ReviewTable
        doc={doc.result}
        accounts={list}
        initialAccountId={initial}
        checkedAccountId={doc.account}
        sheet={sheet}
        onDone={(res, count) => onDone(res, count)}
        onCancel={onClose}
        onRestart={reset}
      />
    )
  }

  // ── 選檔案（第一步） ──
  const hasFiles = !!pdf || images.length > 0
  return (
    <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col" noValidate>
      <div className={cn(bodyClass(sheet), "flex flex-col gap-4")}>
        <input
          ref={fileRef}
          type="file"
          // HEIC 不列在 accept 裡：iPhone 選照片時會先轉成 JPEG；電腦上選到的 HEIC 照樣試著解開
          accept="application/pdf,.pdf,image/jpeg,image/png,image/webp"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            void onFiles(e.target.files)
            e.target.value = ""
          }}
        />
        {!hasFiles && (
          <div className="flex flex-col items-start gap-3">
            <p className="text-base text-ink">一份 PDF 對帳單，或最多 5 張成交明細的截圖、照片</p>
            <Button type="button" variant="outline" onClick={() => fileRef.current?.click()}>
              選檔案
            </Button>
          </div>
        )}

        {pdf && (
          <ul className="border-y border-rule">
            <FileRow name={pdf.file.name} status={pdfStatus(pdf)} onRemove={reset} />
          </ul>
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

        {pdf?.status === "locked" && <PasswordField value={password} onChange={setPassword} wrong={!!pdf.wrongPassword} inputRef={passwordRef} />}

        {images.length > 0 && <p className="text-base text-ink">截圖會整張送給 AI 讀。</p>}
        {pdf?.status === "ready" && <p className="text-base text-ink">{maskLine(pdf)}</p>}
        {allPages.length > 0 && (pdf?.status === "ready" || (!pdf && !pendingImages)) && <Preview pages={allPages} unit={pdf ? "頁" : "張"} />}

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
            {pdf?.checking ? "打開中…" : pdf?.status === "preparing" || pdf?.status === "opening" ? "準備中…" : "開始讀"}
          </Button>
        </div>
      </div>
    </form>
  )
}

function pdfStatus(p: PickedPdf): string {
  if (p.status === "opening") return "打開中…"
  if (p.status === "locked") return "有密碼"
  if (p.status === "preparing") return "準備中…"
  return `${p.pages?.length ?? 0} 頁`
}

/** PDF 準備好之後的一句：塗掉了幾處；掃描的、或沒找到可以塗的，照實說整頁送出 */
function maskLine(p: PickedPdf): string {
  if ((p.scanned ?? 0) > 0) return "這份 PDF 是掃描的，沒辦法塗掉個資，會整頁送給 AI 讀。"
  if ((p.masked ?? 0) > 0) return `已經先塗掉 ${p.masked} 處個資。`
  return "沒有找到可以塗掉的個資，會整頁送給 AI 讀。"
}

function PasswordField({ value, onChange, wrong, inputRef }: { value: string; onChange: (v: string) => void; wrong: boolean; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const id = useId()
  const hintId = useId()
  return (
    <div className="flex flex-col gap-1.5 sm:max-w-xs">
      <label htmlFor={id} className="print-label text-sm">
        PDF 密碼
      </label>
      <Input
        ref={inputRef}
        id={id}
        type="password"
        // 不讓瀏覽器記住或自動填入（通常是身分證字號）
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck={false}
        enterKeyHint="go"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={wrong || undefined}
        aria-describedby={hintId}
      />
      {wrong && <FieldError>密碼不對</FieldError>}
      <p id={hintId} className="text-sm text-ink-2">
        通常是身分證字號，英文大寫。密碼只在這台裝置上用，不會送出。
      </p>
    </div>
  )
}
