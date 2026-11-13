import { useQueryClient } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { XIcon } from "lucide-react"
import { useEffect, useId, useState } from "react"
import { toast } from "sonner"
import { useCreateTopic } from "@/api/discussion-queries"
import { qk, useInstrument, useMe } from "@/api/queries"
import { useGroups } from "@/api/sharing-queries"
import { ApiError, TOPIC_BODY_MAX, TOPIC_SYMBOLS_MAX, TOPIC_TITLE_MAX, type GroupSummary, type User } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { SkeletonLines } from "@/components/states"
import { SymbolPicker } from "@/components/symbol-picker"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { FieldError } from "@/components/form-field"
import { textAction } from "@/components/text-action"
import { bodyProblem, charCount, titleProblem } from "@/lib/discussion-text"
import { clearDraft, hasTopicContent, newTopicDraftKey, parseNewTopicDraft, readDraft, writeDraft, type DraftTag, type NewTopicDraft } from "@/lib/drafts"
import { cn } from "@/lib/utils"
import type { NewTopicSearch } from "@/router"
import { postErrorText, suspendedText, suspendedUntil } from "./labels"
import { newTopicOrigin, topicSearchFrom, type Origin } from "./origin"
import { BackLink, OriginLink } from "./OriginLink"
import { PublicNamePrompt } from "./PublicNamePrompt"
import { PostingAs } from "./ReplyComposer"
import { usePageTitle } from "@/app/page-title"

type Destination = "public" | `group:${string}`

/**
 * 開新主題：發到哪裡（公開／我的每一個群組）→ 標題 → 內文 → 標記股票（最多 5 檔）→ 發表。
 * 網址可以預先選好：`?scope=public`、`?scope=group&group_id=…`（從清單的篩選、群組的討論分頁來）、`?symbol=…`（從個股的討論分頁來）。
 * 沒有預先選、而且有群組可以選時，不替使用者決定（公開或只給群組看是要緊的選擇）；沒有群組就只有公開。
 * 錯誤就地說明：哪一欄不對、公開發言被暫停到什麼時候、發言太頻繁要等多久。
 * 還沒發出去的字邊打邊存（這個分頁，`lib/drafts.ts`）：按「改」去設定、按「取消」或上一頁再回來都還在，發表成功才清掉；
 * 還原的時候表單上面有一行說明與「清除草稿」。麵包屑與「取消」回到來的地方（清單、群組或個股的「討論」分頁）。
 */
export function NewTopicPage() {
  usePageTitle("開新主題")
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="討論" />
  return <NewTopic />
}

function NewTopic() {
  const search = useSearch({ from: "/discussions/new" }) as NewTopicSearch
  const me = useMe()
  const groups = useGroups()
  // 從個股頁來的那一檔：麵包屑的名稱與預先標記都用它
  const stock = useInstrument(search.symbol ?? "", !!search.symbol)
  const origin = newTopicOrigin(search, groups.data, { data: stock.data, settled: !search.symbol || !stock.isPending })
  return (
    <PageFrame className="lg:pt-6">
      {/* 和設定同一個欄寬（816px）：表單、清單、主題頁同一個右緣 */}
      <div className="max-w-measure">
        <nav aria-label="位置" className="flex min-h-11 items-center text-sm">
          {origin && <BackLink origin={origin} />}
        </nav>
        <h1 className="mt-1 text-2xl font-bold tracking-[-0.01em] lg:text-3xl">開新主題</h1>
        {/* 群組清單回來之前不知道有哪些地方可以發：先放骨架，不讓選項跳動 */}
        {me.data && groups.data && origin ? <TopicForm user={me.data} groups={groups.data} origin={origin} /> : <SkeletonLines rows={6} className="mt-6" />}
      </div>
    </PageFrame>
  )
}

const asTag = ({ symbol, code, name }: DraftTag): DraftTag => ({ symbol, code, name })

function TopicForm({ user, groups, origin }: { user: User; groups: GroupSummary[]; origin: Origin }) {
  const search = useSearch({ from: "/discussions/new" }) as NewTopicSearch
  const navigate = useNavigate()
  const qc = useQueryClient()
  const create = useCreateTopic()
  const id = useId()
  const draftKey = newTopicDraftKey(user.id)
  // 上次沒發出去的內容（這個分頁）：只在進來的那一刻讀一次
  const [saved] = useState(() => readDraft(draftKey, parseNewTopicDraft))
  const preset: Destination | null =
    search.scope === "group" && groups.some((g) => g.id === search.group_id) ? `group:${search.group_id!}` : search.scope === "public" || groups.length === 0 ? "public" : null
  // 網址預先選好的優先（那是這次進來的入口）；沒有的話用草稿裡選的（群組還在才算）
  const savedDest: Destination | null =
    saved?.dest === "public" ? "public" : saved?.dest && groups.some((g) => `group:${g.id}` === saved.dest) ? (saved.dest as Destination) : null
  const [dest, setDest] = useState<Destination | null>(preset ?? savedDest)
  const [title, setTitle] = useState(saved?.title ?? "")
  const [body, setBody] = useState(saved?.body ?? "")
  const [picked, setPicked] = useState<DraftTag[]>(saved?.tags ?? [])
  const [errors, setErrors] = useState<{ dest?: string; title?: string; body?: string; form?: string }>({})
  // 表單裡是還原的草稿（不是這次打的）：上面顯示一行說明與「清除草稿」，一動表單就收起來
  const [restored, setRestored] = useState(saved !== null)

  // 從個股頁來：預先標記那一檔（查得到才有；使用者可以移除）
  const presetSymbol = useInstrument(search.symbol ?? "", !!search.symbol)
  const [presetRemoved, setPresetRemoved] = useState(!!search.symbol && saved?.removedPreset === search.symbol)
  const presetTag = !presetRemoved && search.symbol && presetSymbol.data ? asTag(presetSymbol.data) : undefined
  const tags: DraftTag[] = (presetTag ? [presetTag, ...picked.filter((t) => t.symbol !== presetTag.symbol)] : picked).slice(0, TOPIC_SYMBOLS_MAX)
  const removeTag = (symbol: string) => {
    if (presetTag?.symbol === symbol) setPresetRemoved(true)
    setPicked((list) => list.filter((x) => x.symbol !== symbol))
    setRestored(false)
  }

  // 邊打邊存：只有自己加的標記算內容（從個股頁預先標記的那一檔不算——什麼都沒寫就離開，不留草稿）
  const draft: NewTopicDraft = { dest, title, body, tags: picked, removedPreset: presetRemoved ? (search.symbol ?? null) : null }
  const draftJson = JSON.stringify(hasTopicContent(draft) ? draft : null)
  useEffect(() => {
    writeDraft(draftKey, JSON.parse(draftJson))
  }, [draftKey, draftJson])
  const clearAll = () => {
    setDest(preset)
    setTitle("")
    setBody("")
    setPicked([])
    setPresetRemoved(false)
    setErrors({})
    setRestored(false)
  }

  const group = dest?.startsWith("group:") ? groups.find((g) => `group:${g.id}` === dest) : undefined
  const isPublic = dest === "public"
  const until = isPublic ? suspendedUntil(user) : null
  const needsName = isPublic && !until && !user.public_name
  const titleCount = charCount(title.trim())
  const bodyCount = charCount(body)

  const submit = () => {
    if (create.isPending) return
    const next: typeof errors = {}
    if (!dest) next.dest = "請選擇要發到哪裡。"
    else if (until) next.form = groups.length > 0 ? "公開發言被暫停的期間不能發公開主題；可以改發到群組。" : "公開發言被暫停的期間不能發公開主題。"
    else if (needsName) next.form = "發公開主題前，先在上面選一個公開暱稱。"
    const titleBad = titleProblem(title, TOPIC_TITLE_MAX)
    if (titleBad) next.title = titleBad
    const bodyBad = bodyProblem(body, TOPIC_BODY_MAX, "內文")
    if (bodyBad) next.body = bodyBad
    setErrors(next)
    if (Object.keys(next).length > 0 || !dest) return
    create.mutate(
      { scope: isPublic ? "public" : "group", ...(group ? { group_id: group.id } : {}), title: title.trim(), body, symbols: tags.map((t) => t.symbol) },
      {
        onSuccess: (topic) => {
          clearDraft(draftKey)
          toast.success("已發表")
          // 新主題的「← 回去」也是回到來的地方
          void navigate({ to: "/discussions/$topicId", params: { topicId: topic.id }, search: topicSearchFrom(origin) })
        },
        onError: (err) => {
          setErrors({ form: postErrorText(err, "主題") })
          // 伺服器說還沒有公開暱稱、或已被停權：重新讀個人資料，表單換成對應的狀態
          if (err instanceof ApiError && (err.code === "public_name_required" || err.code === "posting_suspended")) void qc.invalidateQueries({ queryKey: qk.me })
        },
      },
    )
  }
  const clear = (key: keyof typeof errors) => setErrors((e) => (e[key] || e.form ? { ...e, [key]: undefined, form: undefined } : e))
  const pick = (d: Destination) => {
    setDest(d)
    setRestored(false)
    clear("dest")
  }

  return (
    <div className="mt-6 flex flex-col gap-6">
      {restored && (
        <p className="-mb-2 flex flex-wrap items-center gap-x-3 text-md text-ink">
          這是上次還沒發表的內容。
          <button type="button" onClick={clearAll} className={cn(textAction, "text-ink-2 hover:text-ink")}>
            清除草稿
          </button>
        </p>
      )}
      {/* 發到哪裡：在表單外面（下面選公開暱稱的那一欄是另一個表單，表單不能包表單） */}
      <fieldset aria-describedby={errors.dest ? `${id}-dest-error` : undefined}>
        <legend className="mb-1.5 text-sm font-medium">發到哪裡</legend>
        <ul className="border-y border-rule">
          <DestinationRow name={`${id}-dest`} checked={isPublic} onChange={() => pick("public")} label="公開" detail="所有人都看得到，不用登入也能讀。" />
          {groups.map((g) => (
            <DestinationRow
              key={g.id}
              name={`${id}-dest`}
              checked={dest === `group:${g.id}`}
              onChange={() => pick(`group:${g.id}`)}
              label={g.name}
              detail="只有這個群組的成員看得到。"
            />
          ))}
        </ul>
        {errors.dest && (
          <FieldError id={`${id}-dest-error`} className="mt-1.5">
            {errors.dest}
          </FieldError>
        )}
      </fieldset>

      {until && <p className="max-w-prose border-y border-rule py-2.5 text-md text-ink">{suspendedText(until)}</p>}
      {needsName && <PublicNamePrompt />}

      <form
        id={`${id}-form`}
        aria-label="新主題"
        className="flex flex-col gap-6"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <Field label="標題" htmlFor={`${id}-title`} error={errors.title} errorId={`${id}-title-error`} hint={titleCount > TOPIC_TITLE_MAX - 20 ? `${titleCount}/${TOPIC_TITLE_MAX}` : undefined}>
          <Input
            id={`${id}-title`}
            value={title}
            autoComplete="off"
            aria-invalid={!!errors.title}
            aria-describedby={errors.title ? `${id}-title-error` : undefined}
            onChange={(e) => {
              setTitle(e.target.value)
              setRestored(false)
              clear("title")
            }}
          />
        </Field>
        <Field label="內文" htmlFor={`${id}-body`} error={errors.body} errorId={`${id}-body-error`} hint={bodyCount > TOPIC_BODY_MAX - 500 ? `${bodyCount}/${TOPIC_BODY_MAX}` : undefined}>
          <Textarea
            id={`${id}-body`}
            value={body}
            rows={8}
            aria-invalid={!!errors.body}
            aria-describedby={errors.body ? `${id}-body-error` : `${id}-body-help`}
            onChange={(e) => {
              setBody(e.target.value)
              setRestored(false)
              clear("body")
            }}
            // 跟著內容自己長高（field-sizing-content），不需要右下角的原生拖曳把手
            className="min-h-48 resize-none border-ctl bg-raised px-3 py-2.5 text-base leading-[1.7] md:text-base"
          />
          {!errors.body && (
            <p id={`${id}-body-help`} className="text-sm text-ink-2">
              純文字，可以換行；貼上的網址會變成連結。
            </p>
          )}
        </Field>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium">標記股票（選填）</span>
            <span className="num text-sm text-ink-2">{`${tags.length}/${TOPIC_SYMBOLS_MAX}`}</span>
          </div>
          {tags.length > 0 && (
            <ul aria-label="已標記的股票" className="flex flex-wrap gap-2">
              {tags.map((t) => (
                <li key={t.symbol} className="flex h-9 items-center rounded-sm border border-ctl pl-2.5 text-md pointer-coarse:h-[2.875rem]">
                  <span className="max-w-[14rem] truncate">{t.name}</span>
                  <span className="num ml-1.5 text-ink-2">{t.code}</span>
                  <button
                    type="button"
                    aria-label={`移除 ${t.name}`}
                    title="移除"
                    onClick={() => removeTag(t.symbol)}
                    className="press ml-0.5 grid h-full w-9 place-items-center rounded-sm text-ink-2 hover:bg-hov hover:text-ink pointer-coarse:w-11"
                  >
                    <XIcon aria-hidden className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {tags.length < TOPIC_SYMBOLS_MAX ? (
            <SymbolPicker
              label="標記股票"
              value={null}
              onChange={(i) => {
                if (!i) return
                setPicked((list) => (list.some((x) => x.symbol === i.symbol) ? list : [...list, asTag(i)]))
                setRestored(false)
              }}
              accept={(i) => !tags.some((x) => x.symbol === i.symbol)}
              rejectReason="已標記"
            />
          ) : (
            <p className="text-sm text-ink-2">最多標記 {TOPIC_SYMBOLS_MAX} 檔。要換一檔，先移除一個。</p>
          )}
          <p className="text-base text-ink">標記的主題也會出現在那檔股票的「討論」分頁。</p>
        </div>

        {errors.form && (
          <p role="alert" className="max-w-prose border-y border-rule py-2.5 text-md text-ink">
            {errors.form}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <Button type="submit" variant="sign" disabled={create.isPending}>
            {create.isPending ? "發表中…" : "發表"}
          </Button>
          {/* 取消：回到來的地方；打到一半的字留著（回來時還在） */}
          <OriginLink origin={origin} className={buttonVariants({ variant: "outline" })}>
            取消
          </OriginLink>
          {dest && !needsName && !until && <PostingAs user={user} scope={isPublic ? "public" : "group"} groupName={group?.name} />}
        </div>
      </form>
    </div>
  )
}

/** 「發到哪裡」的一列：整列都是 radio 的標籤（44px 以上），名稱墨色、後面一句淡墨的說明（誰看得到） */
function DestinationRow({ name, checked, onChange, label, detail }: { name: string; checked: boolean; onChange: () => void; label: string; detail: string }) {
  return (
    <li className="border-b border-rule last:border-b-0">
      <label className="flex min-h-12 cursor-pointer items-center gap-3 px-1 py-2 hover:bg-hov">
        <input type="radio" name={name} checked={checked} onChange={onChange} className="size-4 shrink-0 accent-ink" />
        <span className="min-w-0">
          <span className="font-medium break-words">{label}</span>
          <span className="ml-2 text-base text-ink max-sm:ml-0 max-sm:block">{detail}</span>
        </span>
      </label>
    </li>
  )
}

/** 表單的一欄：標籤（右邊是接近上限時才出現的字數）＋控制項＋就地的錯誤 */
function Field({ label, htmlFor, hint, error, errorId, children }: { label: string; htmlFor: string; hint?: string; error?: string; errorId: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={htmlFor} className="text-sm font-medium">
          {label}
        </label>
        {hint && <span className="num text-sm text-ink-2">{hint}</span>}
      </div>
      {children}
      {error && (
        <FieldError id={errorId}>{error}</FieldError>
      )}
    </div>
  )
}
