import { useQueryClient } from "@tanstack/react-query"
import { Link, useNavigate, useSearch } from "@tanstack/react-router"
import { ArrowLeftIcon, XIcon } from "lucide-react"
import { useId, useState } from "react"
import { toast } from "sonner"
import { useCreateTopic } from "@/api/discussion-queries"
import { qk, useInstrument, useMe } from "@/api/queries"
import { useGroups } from "@/api/sharing-queries"
import { ApiError, TOPIC_BODY_MAX, TOPIC_SYMBOLS_MAX, TOPIC_TITLE_MAX, type GroupSummary, type Instrument, type User } from "@/api/types"
import { useReadOnly } from "@/api/view-as"
import { PlainLink } from "@/app/links"
import { PageFrame } from "@/app/PageFrame"
import { ViewAsBlocked } from "@/app/ViewAsBanner"
import { SkeletonLines } from "@/components/states"
import { SymbolPicker } from "@/components/symbol-picker"
import { Button, buttonVariants } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { bodyProblem, charCount, titleProblem } from "@/lib/discussion-text"
import type { NewTopicSearch } from "@/router"
import { postErrorText, suspendedText, suspendedUntil } from "./labels"
import { PublicNamePrompt } from "./PublicNamePrompt"
import { PostingAs } from "./ReplyComposer"

type Destination = "public" | `group:${string}`

/**
 * 開新主題：發到哪裡（公開／我的每一個群組）→ 標題 → 內文 → 標記股票（最多 5 檔）→ 發表。
 * 網址可以預先選好：`?scope=public`、`?scope=group&group_id=…`（從清單的篩選、群組的討論分頁來）、`?symbol=…`（從個股的討論分頁來）。
 * 沒有預先選、而且有群組可以選時，不替使用者決定（公開或只給群組看是要緊的選擇）；沒有群組就只有公開。
 * 錯誤就地說明：哪一欄不對、公開發言被暫停到什麼時候、發言太頻繁要等多久。
 */
export function NewTopicPage() {
  const readOnly = useReadOnly()
  if (readOnly) return <ViewAsBlocked title="討論" />
  return <NewTopic />
}

function NewTopic() {
  const me = useMe()
  const groups = useGroups()
  return (
    <PageFrame className="lg:pt-6">
      <nav aria-label="位置" className="flex min-h-11 items-center text-sm">
        <PlainLink to="/discussions" className="-ml-1 inline-flex h-9 items-center gap-1 rounded-sm px-1 text-ink hover:bg-hov pointer-coarse:h-11">
          <ArrowLeftIcon aria-hidden className="size-4" />
          討論
        </PlainLink>
      </nav>
      <div className="max-w-[42rem]">
        <h1 className="mt-1 text-2xl font-bold tracking-[-0.01em] lg:text-3xl">開新主題</h1>
        {/* 群組清單回來之前不知道有哪些地方可以發：先放骨架，不讓選項跳動 */}
        {me.data && groups.data ? <TopicForm user={me.data} groups={groups.data} /> : <SkeletonLines rows={6} className="mt-6" />}
      </div>
    </PageFrame>
  )
}

function TopicForm({ user, groups }: { user: User; groups: GroupSummary[] }) {
  const search = useSearch({ from: "/discussions/new" }) as NewTopicSearch
  const navigate = useNavigate()
  const qc = useQueryClient()
  const create = useCreateTopic()
  const id = useId()
  const preset: Destination | null =
    search.scope === "group" && groups.some((g) => g.id === search.group_id) ? `group:${search.group_id!}` : search.scope === "public" || groups.length === 0 ? "public" : null
  const [dest, setDest] = useState<Destination | null>(preset)
  const [title, setTitle] = useState("")
  const [body, setBody] = useState("")
  const [picked, setPicked] = useState<Instrument[]>([])
  const [errors, setErrors] = useState<{ dest?: string; title?: string; body?: string; form?: string }>({})

  // 從個股頁來：預先標記那一檔（查得到才有；使用者可以移除）
  const presetSymbol = useInstrument(search.symbol ?? "", !!search.symbol)
  const [presetRemoved, setPresetRemoved] = useState(false)
  const presetTag = !presetRemoved && search.symbol ? presetSymbol.data : undefined
  const tags: Instrument[] = (presetTag ? [presetTag, ...picked.filter((t) => t.symbol !== presetTag.symbol)] : picked).slice(0, TOPIC_SYMBOLS_MAX)
  const removeTag = (symbol: string) => {
    if (presetTag?.symbol === symbol) setPresetRemoved(true)
    setPicked((list) => list.filter((x) => x.symbol !== symbol))
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
          toast.success("已發表")
          void navigate({ to: "/discussions/$topicId", params: { topicId: topic.id } })
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
    clear("dest")
  }

  return (
    <div className="mt-6 flex flex-col gap-6">
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
          <p id={`${id}-dest-error`} role="alert" className="mt-1.5 text-sm text-destructive">
            {errors.dest}
          </p>
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
              onChange={(i) => i && setPicked((list) => (list.some((x) => x.symbol === i.symbol) ? list : [...list, i]))}
              accept={(i) => !tags.some((x) => x.symbol === i.symbol)}
              rejectReason="已標記"
            />
          ) : (
            <p className="text-sm text-ink-2">最多標記 {TOPIC_SYMBOLS_MAX} 檔。要換一檔，先移除一個。</p>
          )}
          <p className="text-sm text-ink-2">標記的主題也會出現在那檔股票的「討論」分頁。</p>
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
          <Link to="/discussions" className={buttonVariants({ variant: "outline" })}>
            取消
          </Link>
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
          <span className="ml-2 text-md text-ink-2 max-sm:ml-0 max-sm:block">{detail}</span>
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
        <p id={errorId} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
