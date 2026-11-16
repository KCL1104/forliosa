import { useQueryClient } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { ChevronDownIcon } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import { toast } from "sonner"
import { api } from "@/api"
import { useAccounts, useDeleteTransactionBatch } from "@/api/queries"
import { ApiError, type Account, type ImportPage, type StatementImport, type TransactionBatchResult } from "@/api/types"
import { useAiUsage } from "@/ai/remote-hooks"
import type { AiUsage } from "@/ai/remote"
import { useUi } from "@/app/ui-store"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { Button, buttonVariants } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer"
import { Input } from "@/components/ui/input"
import { useIsDesktop } from "@/hooks/use-media-query"
import { cn } from "@/lib/utils"
import { accountForBroker, statementCurrency, unsupportedLine } from "./flags"
import { bodyClass, footerClass } from "./layout"
import { ImageReadError, MAX_IMAGES, MAX_PAGES, prepareImage, sniffFile } from "./prepare-image"
import { openPdf, PdfOpenError, PdfPasswordError, preparePdf } from "./prepare-pdf"
import { ReviewTable } from "./ReviewTable"

/**
 * 匯入對帳單（產品負責人 2026-11-16，方案一：AI 讀檔＋確認表）。桌面是對話框、手機是抽屜。
 * 選檔案 →（PDF 有密碼就輸入）→ 開始讀（10–40 秒，可以取消）→ 確認表 → 簽名「匯入 N 筆」→ 通知「已匯入 N 筆」＋復原。
 *
 * - PDF：在這台裝置上用 pdf.js 解密、畫成圖、塗掉找得到的個資，只送出圖和塗過的文字（密碼與原始檔不離開裝置）。
 * - 截圖、照片：JPEG／PNG／WebP，一次最多 5 張；很長的截圖切成好幾塊。截圖沒有文字層，塗不了，整張送出（畫面上說一句）。
 * - 不存檔案、不存讀出的結果；只有簽名匯入的交易進帳本（來源「匯入」），可以整批復原。
 */
export function ImportDialog() {
  const open = useUi((s) => s.importOpen)
  const close = useUi((s) => s.closeImport)
  const isDesktop = useIsDesktop()
  const [phase, setPhase] = useState<Phase>("pick")
  // 每次打開都是新的一份（關掉時丟掉選的檔案、密碼與讀出來的表）
  const [session, setSession] = useState(0)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setSession((n) => n + 1)
      setPhase("pick")
    }
  }
  const wide = phase === "review"
  const title = "匯入對帳單"
  const description = "選一份 PDF 對帳單或成交明細的截圖，AI 讀成一張表，你核對過、簽名之後才寫進帳本。"
  const flow = (sheet: boolean) => open && <ImportFlow key={session} sheet={sheet} onClose={close} onPhase={setPhase} />

  if (isDesktop) {
    return (
      // 讀取中、核對中不因為點到外面就關掉（表格改到一半會不見）；Esc 與「取消」照常
      <Dialog open={open} onOpenChange={(o) => !o && close()} disablePointerDismissal={phase !== "pick"}>
        <DialogContent className={cn("flex max-h-[calc(100dvh-4rem)] flex-col gap-0 overflow-hidden p-0", wide ? "sm:max-w-[min(1000px,calc(100%-4rem))]" : "sm:max-w-[560px]")}>
          <DialogHeader className="px-6 pt-5 pb-4">
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="sr-only">{description}</DialogDescription>
          </DialogHeader>
          {flow(false)}
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
        <div className="flex min-h-0 flex-1 flex-col">{flow(true)}</div>
      </DrawerContent>
    </Drawer>
  )
}

type Phase = "pick" | "reading" | "review"

interface PickedImage {
  id: number
  file: File
  pages?: ImportPage[]
  error?: string
}

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

const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError"

/** 讀檔失敗時的一句話（伺服器的句子照原文；沒有句子的照狀態碼說） */
function readError(e: unknown): string {
  if (e instanceof ApiError) {
    if (!e.code.startsWith("http_")) return e.message
    if (e.status === 413) return "檔案太大。PDF 分開匯入，或少選幾張截圖。"
    if (e.status === 403) return "這個帳號還不能匯入對帳單。"
    if (e.status === 503) return "AI 暫時無法使用，等一下再試。"
    if (e.status === 429) return "今天的匯入次數用完了，明天再試。"
    return `沒有讀成功（${e.status}），檔案還在，再試一次。`
  }
  return "沒有連上伺服器，檔案還在，再試一次。"
}

function ImportFlow({ sheet, onClose, onPhase }: { sheet: boolean; onClose: () => void; onPhase: (p: Phase) => void }) {
  const accounts = useAccounts()
  const qc = useQueryClient()
  const undo = useDeleteTransactionBatch()
  const [phase, setPhaseState] = useState<Phase>("pick")
  const [pdf, setPdf] = useState<PickedPdf | null>(null)
  const [images, setImages] = useState<PickedImage[]>([])
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [doc, setDoc] = useState<{ result: StatementImport; account: string } | null>(null)
  const [readingPages, setReadingPages] = useState({ count: 0, unit: "頁" })
  const fileRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const imageSeq = useRef(0)
  /** 換了檔案或按了移除：還在打開、準備的那一份就不要再寫回畫面 */
  const pdfSeq = useRef(0)
  const usage = useAiUsage().data as (AiUsage & { imports_today?: number; import_daily_limit?: number }) | undefined
  const left = usage?.import_daily_limit != null && usage.imports_today != null ? Math.max(usage.import_daily_limit - usage.imports_today, 0) : null

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
        const msg =
          e instanceof ImageReadError
            ? e.reason === "heic"
              ? "這張是 HEIC 格式，這個瀏覽器讀不了。請改存成 JPEG，或改用截圖。"
              : e.reason === "unsupported"
                ? "只收 PDF、JPEG、PNG、WebP。"
                : "這張圖打不開。"
            : "這張圖打不開。"
        setImages((xs) => xs.map((x) => (x.id === p.id ? { ...x, error: msg } : x)))
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

  const done = (res: TransactionBatchResult, count: number) => {
    toast.success(`已匯入 ${count} 筆`, {
      description: res.auto_dividends_added > 0 ? `另外自動記了 ${res.auto_dividends_added} 筆股利。` : undefined,
      duration: 10_000,
      action: {
        label: "復原",
        onClick: () =>
          void undo.mutateAsync(res.batch_id).then(
            () => toast("已復原這次匯入"),
            (err) => toast.error("沒有復原成功。", { description: err instanceof Error ? err.message : undefined }),
          ),
      },
    })
    onClose()
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

  if (phase === "reading") {
    return <Reading count={readingPages.count} unit={readingPages.unit} sheet={sheet} onCancel={() => controller.current?.abort()} />
  }

  if (phase === "review" && doc) {
    const unsupported = unsupportedLine(doc.result)
    if (unsupported) {
      return (
        <>
          <div className={bodyClass(sheet)}>
            <p className="border-y border-rule py-5 text-base text-ink">{unsupported}</p>
          </div>
          <div className={footerClass(sheet)}>
            <div className="ml-auto flex gap-2.5">
              <Button variant="outline" onClick={onClose}>
                取消
              </Button>
              <Button onClick={reset}>換一個檔案</Button>
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
        onDone={done}
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
            <p className="text-base text-ink">選一份 PDF 對帳單，或最多 5 張成交明細的截圖、照片。</p>
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
              <FileRow
                key={x.id}
                name={x.file.name}
                status={x.error ? null : x.pages ? (x.pages.length > 1 ? `切成 ${x.pages.length} 張` : "1 張") : "讀取中…"}
                error={x.error}
                onRemove={() => setImages((xs) => xs.filter((y) => y.id !== x.id))}
              />
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
        {outOfImports ? (
          <p className="text-base text-ink">今天的 {usage?.import_daily_limit} 份用完了，明天再匯入。</p>
        ) : left !== null && left <= 3 ? (
          <p className="text-sm text-ink-2">今天還可以匯入 {left} 份。</p>
        ) : null}
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

function FileRow({ name, status, error, onRemove }: { name: string; status: string | null; error?: string; onRemove: () => void }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule py-2 last:border-b-0">
      <span className="min-w-0 flex-1 truncate text-base text-ink">{name}</span>
      {status && <span className="num text-sm text-ink-2">{status}</span>}
      <button type="button" onClick={onRemove} className={textAction} aria-label={`移除 ${name}`}>
        移除
      </button>
      {error && <FieldError className="w-full">{error}</FieldError>}
    </li>
  )
}

function PasswordField({ value, onChange, wrong, inputRef }: { value: string; onChange: (v: string) => void; wrong: boolean; inputRef: React.RefObject<HTMLInputElement | null> }) {
  const id = useId()
  const hintId = useId()
  return (
    <div className="flex flex-col gap-1.5 sm:max-w-xs">
      <label htmlFor={id} className="text-sm font-medium">
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

/** 「看要送出的 2 頁」：塗過之後、實際送出去的圖 */
function Preview({ pages, unit }: { pages: ImportPage[]; unit: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className="inline-flex min-h-9 items-center gap-1 text-md text-ink underline decoration-ctl underline-offset-4 hover:decoration-ink pointer-coarse:min-h-11"
      >
        看要送出的 {pages.length} {unit}
        <ChevronDownIcon aria-hidden className={cn("size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div id={id} className="mt-2 flex max-h-[50dvh] flex-col gap-2 overflow-y-auto">
          {pages.map((p, i) => (
            <img key={i} src={`data:${p.media_type};base64,${p.data}`} alt={`要送出的第 ${i + 1} ${unit}`} className="w-full border border-rule" />
          ))}
        </div>
      )}
    </div>
  )
}

/** 讀取中：「正在讀 2 頁…」、已經過了幾秒、取消 */
function Reading({ count, unit, sheet, onCancel }: { count: number; unit: string; sheet: boolean; onCancel: () => void }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => window.clearInterval(t)
  }, [])
  return (
    <>
      <div className={cn(bodyClass(sheet), "flex flex-col items-start gap-1.5 py-6")} aria-busy="true">
        <p className="text-lg font-medium text-ink" role="status">
          正在讀 {count} {unit}…
        </p>
        <p className="num text-sm text-ink-2">
          通常要 10 到 40 秒{seconds >= 3 ? `，已經 ${seconds} 秒` : ""}。
        </p>
      </div>
      <div className={footerClass(sheet)}>
        <Button type="button" variant="outline" className={cn("ml-auto", sheet ? "flex-1" : "min-w-24")} onClick={onCancel}>
          取消
        </Button>
      </div>
    </>
  )
}
