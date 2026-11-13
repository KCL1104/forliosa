import {
  ApiError,
  PERMANENT_UNTIL,
  PUBLIC_NAME_MAX,
  PUBLIC_NAME_MIN,
  REACTION_EMOJIS,
  REPLY_BODY_MAX,
  REPORT_NOTE_MAX,
  REPORT_REASONS,
  TOPIC_BODY_MAX,
  TOPIC_SYMBOLS_MAX,
  TOPIC_TITLE_MAX,
  type AdminReport,
  type DiscussionAuthor,
  type DiscussionScope,
  type DiscussionStatus,
  type GroupRole,
  type ModerationAction,
  type Paged,
  type Reaction,
  type ReactionEmoji,
  type Reply,
  type ReportInput,
  type ReportReason,
  type Suspension,
  type SuspensionDays,
  type Topic,
  type TopicInput,
  type TopicQuery,
  type TopicSummary,
  type TopicSymbol,
  type UserRef,
} from "../types"
import { bodyProblem, nameKey, normalizeText, oneLine, publicNameProblem, titleProblem } from "@/lib/discussion-text"
import { findInstrument } from "./instruments"
import { MOCK_AS_OF } from "./market"
import { PEOPLE } from "./members"

/**
 * 討論串的 mock（docs/api-contract.md「討論串（2026-11-13）」），規則和後端 `services/discussions.py` 相同：
 * - 範圍：公開（不用登入就能讀）／群組（不是成員、沒登入一律 404，不透露存在）。
 * - 作者：公開範圍只有公開暱稱與 `is_you` 兩個鍵；群組範圍是顯示名稱＋user_id＋avatar_url，已離開的人是「已離開的成員」。
 * - 發公開內容的檢查順序：停權（403 posting_suspended，帶 until）→ 沒有公開暱稱（409 public_name_required）
 *   → 頻率（429 rate_limited，帶 retry_after_seconds）。
 * - 頻率用滾動的 24 小時／60 分鐘；任兩則公開發言至少間隔 10 秒；刪掉發言不還額度。
 * - 隱藏：主題不出現在任何清單，直接打開是 body null＋佔位標題（作者與站方管理員拿得到原文）；回覆留在原位、body null。
 * - 時間是 UTC、`Z` 結尾、到秒。
 * 線圖留言（彈幕）與指數頁暫緩，這裡沒有。
 */

export interface DiscussionDeps {
  me(): UserRef
  signedIn(): boolean
  /** 我加入的群組與角色（沒登入是空的） */
  myGroupRoles(): { id: string; name: string; role: GroupRole }[]
  /** 群組的名稱與目前的成員；群組不存在是 null */
  groupRoster(groupId: string): { id: string; name: string; members: UserRef[] } | null
  /** 現在（毫秒） */
  now(): number
}

export interface DiscussionOptions {
  /** 示範使用者一開始的公開暱稱（預設沒有） */
  publicName?: string | null
  /** 示範使用者是不是站方管理員（預設是） */
  admin?: boolean
  /** 示範使用者的公開發言被停權 7 天 */
  suspended?: boolean
}

interface MockTopic {
  id: string
  scope: DiscussionScope
  group_id: string | null
  /** 帳號刪除後是 null */
  user_id: string | null
  title: string
  body: string
  symbols: string[]
  status: DiscussionStatus
  created_at: number
  last_activity_at: number
}
interface MockReply {
  id: string
  topic_id: string
  user_id: string | null
  body: string
  status: DiscussionStatus
  created_at: number
}
interface MockReport {
  target: string
  reporter_id: string
  reason: ReportReason
  note: string | null
  status: "open" | "resolved"
  created_at: number
}
interface MockSuspension {
  id: string
  user_id: string
  until: number
  reason: string | null
  created_at: number
  lifted: boolean
}
interface Viewer {
  id: string | null
  admin: boolean
  roles: Map<string, GroupRole>
}

// 每一個數字都在這裡（和後端的常數相同）
const RATE = {
  public: { topic: { count: 5, window: 86_400_000 }, reply: { count: 30, window: 3_600_000 } },
  group: { topic: { count: 20, window: 86_400_000 }, reply: { count: 120, window: 3_600_000 } },
} as const
const PUBLIC_POST_GAP = 10_000
const PUBLIC_NAME_COOLDOWN = 7 * 86_400_000
const REPORT_LIMIT = { count: 20, window: 3_600_000 }
const HIDDEN_TITLE = "（已被站方隱藏的主題）"
const PERMANENT = Date.parse(PERMANENT_UNTIL)
const EXCERPT_CHARS = 120
const LEFT_MEMBER = "已離開的成員"
const MANAGERS: readonly GroupRole[] = ["owner", "admin"]

/** 其他人的公開暱稱（示範用的稱呼，不是真實的人；公開身分和群組身分互相對不起來） */
const PUBLIC_PEOPLE = {
  tu: "阿土伯",
  saver: "存股小資女",
  hsinchu: "竹科打工仔",
  dca: "定期定額派",
  newbie: "小白學投資",
  sailor: "航海王阿明",
  night: "夜盤觀察員",
  yield: "高股息研究生",
  teacher: "退休林老師",
  hunter: "短線獵人",
  payout: "領息達人",
  tout: "飆股情報站",
} as const
type PublicPerson = keyof typeof PUBLIC_PEOPLE
const pid = (k: PublicPerson) => `usr_pub_${k}`

const iso = (ms: number) => `${new Date(ms).toISOString().slice(0, 19)}Z`
/** 台北時間「2026-11-10 10:10」→ 毫秒 */
const at = (taipei: string) => Date.parse(`${taipei.replace(" ", "T")}:00+08:00`)

const b64 = (s: string) => btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
const encodeCursor = (ts: number, id: string) => b64(`${ts}|${id}`)
function decodeCursor(cursor: string): [number, string] {
  try {
    const raw = atob(cursor.replace(/-/g, "+").replace(/_/g, "/"))
    const i = raw.indexOf("|")
    const ts = Number(raw.slice(0, i))
    if (i < 1 || !Number.isFinite(ts)) throw new Error("bad cursor")
    return [ts, raw.slice(i + 1)]
  } catch {
    throw new ApiError(422, "validation_error", "分頁游標無效")
  }
}

const invalid = (message: string, code = "validation_error") => new ApiError(422, code, message)
const notFound = (message = "找不到這個主題") => new ApiError(404, "not_found", message)
const loginRequired = () => new ApiError(401, "unauthorized", "請先登入")
const TARGET_RE = /^(topic|reply):[A-Za-z0-9_]{1,40}$/
const excerptOf = (text: string) => [...oneLine(text)].slice(0, EXCERPT_CHARS).join("")

export function createDiscussionStore(deps: DiscussionDeps, scenario: "default" | "empty" | "stress" = "default", options: DiscussionOptions = {}) {
  const admin = options.admin ?? true
  let myPublicName: string | null = options.publicName ?? null
  /** 上一次「改名」的時間（第一次設定不算，不啟動冷卻） */
  let myNameChangedAt: number | null = null
  const publicNames = new Map<string, string>(Object.entries(PUBLIC_PEOPLE).map(([k, name]) => [pid(k as PublicPerson), name]))

  let topics: MockTopic[] = []
  let replies: MockReply[] = []
  const reactions = new Map<string, Map<ReactionEmoji, Set<string>>>()
  let reports: MockReport[] = []
  const suspensions: MockSuspension[] = []
  /** 每則發言一列（不含內容）：頻率限制用，刪掉發言不會把額度還回來 */
  const postLog: { user_id: string; scope: DiscussionScope; kind: "topic" | "reply"; at: number }[] = []
  let seq = 100
  const newId = (prefix: string) => `${prefix}_${++seq}`

  const meId = () => deps.me().user_id

  // ── 示範資料 ──
  const react = (target: string, emoji: ReactionEmoji, users: string[]) => {
    const map = reactions.get(target) ?? new Map<ReactionEmoji, Set<string>>()
    map.set(emoji, new Set(users))
    reactions.set(target, map)
  }
  const seedTopic = (
    id: string,
    scope: DiscussionScope,
    groupId: string | null,
    author: string | null,
    created: string,
    title: string,
    body: string,
    symbols: string[],
    thread: [id: string, author: string | null, created: string, body: string, status?: DiscussionStatus][],
    status: DiscussionStatus = "visible",
  ) => {
    const created_at = at(created)
    topics.push({
      id, scope, group_id: groupId, user_id: author, title, body, symbols, status, created_at,
      last_activity_at: Math.max(created_at, ...thread.map((r) => at(r[2]))),
    })
    for (const [rid, user, when, text, st] of thread) replies.push({ id: rid, topic_id: id, user_id: user, body: text, status: st ?? "visible", created_at: at(when) })
  }
  const seedReport = (target: string, entries: [who: PublicPerson, reason: ReportReason, when: string, note?: string][], status: "open" | "resolved") => {
    for (const [who, reason, when, note] of entries) reports.push({ target, reporter_id: pid(who), reason, note: note ?? null, status, created_at: at(when) })
  }

  if (scenario !== "empty") {
    const me = meId()
    seedTopic("top_p_etf", "public", null, pid("tu"), "2026-11-10 10:10", "0050 要不要改買 006208？",
      "兩檔追蹤的是同一個指數，差別主要在內扣費用和每股價格。\n\n我現在每個月定期定額 0050，已經扣了三年多。想問有換過的人：賣掉重買要付的手續費和證交稅，多久才補得回來？還是舊的留著、新的錢改買 006208 就好？",
      ["0050.TW", "006208.TW"],
      [
        ["rep_p_etf_1", pid("dca"), "2026-11-10 11:02", "我是舊的不動、新的錢改買。賣掉要先付一次稅，不如讓它繼續放著。"],
        ["rep_p_etf_2", pid("saver"), "2026-11-10 12:40", "同上。兩檔分開記，也比較看得出各自的成本。"],
        ["rep_p_etf_3", pid("teacher"), "2026-11-11 09:15", "費用的差距要放很多年才看得出來，先確定自己扣得下去比較重要。"],
        ["rep_p_etf_4", pid("tu"), "2026-11-12 12:31", "謝謝各位。決定新的錢改買 006208，0050 留著領息。"],
      ])
    react("topic:top_p_etf", "👍", [pid("saver"), pid("dca"), me])
    react("topic:top_p_etf", "👀", [pid("newbie")])
    react("reply:rep_p_etf_1", "👍", [pid("tu"), pid("teacher")])

    seedTopic("top_p_tsmc", "public", null, pid("hsinchu"), "2026-11-11 21:05", "台積電法說會前，大家怎麼配置？",
      "下個月法說會，我手上台積電佔了快一半，另外是 0050。\n\n想聽聽大家的做法：法說前會先減碼一點，還是不管它、照原本的比例放著？我自己是長期持有，但單一個股的比重這麼高，心裡還是不太踏實。",
      ["2330.TW", "0050.TW"],
      [
        ["rep_p_tsmc_1", pid("tu"), "2026-11-11 21:40", "比重超過自己睡得著的程度就調，不用等法說會。"],
        ["rep_p_tsmc_2", pid("tout"), "2026-11-11 22:10", "想知道法說會後哪幾檔會噴？加我 LINE 進群組，每天盤前給名單，保證獲利。", "hidden"],
        ["rep_p_tsmc_3", pid("hunter"), "2026-11-12 09:20", "抱一半還敢說自己長期持有？看不懂財報就不要出來亂講。"],
        ["rep_p_tsmc_4", pid("teacher"), "2026-11-12 10:05", "0050 裡面本來就有很大一部分是台積電，兩個加起來的實際比重可以先算一下。"],
        ["rep_p_tsmc_5", pid("hsinchu"), "2026-11-12 13:02", "算了一下，加起來真的比想像中高。之後的定期定額會先改到別的地方。"],
      ])
    react("topic:top_p_tsmc", "👍", [pid("tu"), pid("teacher"), pid("saver")])
    react("topic:top_p_tsmc", "🔥", [pid("dca")])
    react("reply:rep_p_tsmc_4", "👍", [pid("hsinchu"), pid("tu"), me])

    seedTopic("top_p_yield", "public", null, pid("saver"), "2026-11-10 20:30", "00878 的殖利率，大家怎麼算？",
      "看到有人拿單季配息直接乘以 4 當年化殖利率，也有人用過去四季加總。\n\n兩種算出來差不少。大家平常看哪一種？我自己是看過去四季實際領到的，再除以我的平均成本。",
      ["00878.TW"],
      [
        ["rep_p_yield_1", pid("yield"), "2026-11-10 21:12", "用過去四季加總比較實在。單季乘以 4 是假設之後每一季都一樣。"],
        ["rep_p_yield_2", pid("dca"), "2026-11-11 08:03", "用自己的成本算的是「成本殖利率」，跟別人比的時候要講清楚是哪一種。"],
        // 帳號已刪除：內容保留，作者是 null
        ["rep_p_yield_3", null, "2026-11-11 12:00", "我都直接看每年實際入帳的金額。"],
      ])
    react("topic:top_p_yield", "👍", [pid("yield"), pid("dca")])

    seedTopic("top_p_day", "public", null, pid("dca"), "2026-11-09 09:00", "定期定額的扣款日，選幾號有差嗎？",
      "券商讓我選 6、16、26 號。看過一些說法是長期下來差異很小，但還是想問問有沒有人特別挑日子。\n\n我目前選發薪日隔天，錢進來就扣，比較不會花掉。",
      [],
      [
        ["rep_p_day_1", pid("newbie"), "2026-11-09 10:20", "我也是發薪日後扣，不然月底就沒錢了。"],
        ["rep_p_day_2", pid("tu"), "2026-11-09 19:45", "扣了十年的心得：哪一天不重要，不要停扣比較重要。"],
      ])
    react("topic:top_p_day", "👍", [pid("newbie"), pid("tu"), pid("saver"), pid("teacher")])

    seedTopic("top_p_odd", "public", null, pid("newbie"), "2026-11-08 22:15", "第一次買零股，手續費怎麼算？",
      "剛開戶，想先從零股開始買。\n\n聽說手續費有最低收費，買太少會不划算。請問大家一次大概買多少金額以上？盤中零股和盤後零股又差在哪裡？\n\n我有找到證交所的網站 https://www.twse.com.tw/，但規則看不太懂。",
      [],
      [
        ["rep_p_odd_1", pid("saver"), "2026-11-08 22:50", "每家券商的最低手續費不一樣，先看自己券商的規定。金額太小的話，手續費佔的比例會很高。"],
        ["rep_p_odd_2", pid("dca"), "2026-11-09 08:10", "用定期定額買零股通常比較划算，可以問問你的券商。"],
        ["rep_p_odd_3", pid("newbie"), "2026-11-09 12:00", "了解，謝謝兩位！"],
      ])
    react("topic:top_p_odd", "👍", [pid("saver")])

    seedTopic("top_p_ship", "public", null, pid("sailor"), "2026-11-07 15:20", "長榮還抱著的人，現在怎麼看？",
      "去年買的一直放到現在，中間領了一次息。\n\n最近運價的新聞很多，看多看空都有。想問還抱著的人是打算繼續放，還是有設停利的價位？",
      ["2603.TW"],
      [
        ["rep_p_ship_1", pid("teacher"), "2026-11-07 16:02", "航運跟著景氣循環走，我自己是有賺就分批出。"],
        ["rep_p_ship_2", pid("sailor"), "2026-11-08 09:30", "分批出聽起來不錯，至少不用猜最高點。"],
      ])
    react("topic:top_p_ship", "😮", [pid("newbie")])

    seedTopic("top_p_us", "public", null, pid("night"), "2026-11-06 23:40", "美股要用複委託，還是開海外券商？",
      "想開始買美股 ETF，主要是 VOO，可能再加一點個股。\n\n複委託的好處是錢留在台灣；海外券商的手續費通常比較低，但要自己匯款。想問兩種都用過的人，實際用起來差在哪？",
      ["VOO", "AAPL"],
      [["rep_p_us_1", pid("teacher"), "2026-11-07 08:20", "金額不大、買了就放著的話，複委託的定期定額很省事。"]])
    react("topic:top_p_us", "👀", [pid("tu"), pid("hsinchu")])

    seedTopic("top_p_div", "public", null, pid("yield"), "2026-11-05 19:10", "高股息 ETF 要不要全部換成市值型？",
      "存了幾年 0056 和 00878，最近看到很多人說長期下來市值型的總報酬比較好。\n\n我的想法是：領息對我來說有一種安定感，全部換掉大概做不到。有沒有人是兩種各放一半的？比例怎麼抓？",
      ["0056.TW", "00878.TW", "0050.TW"],
      [
        ["rep_p_div_1", pid("tu"), "2026-11-05 20:00", "我是一半一半。息拿來生活，市值型放著不動。"],
        ["rep_p_div_2", pid("payout"), "2026-11-06 10:10", "私訊我領取高股息名單，每個月穩定領 2 萬。"],
      ])
    react("topic:top_p_div", "👍", [pid("tu"), pid("saver"), pid("dca")])

    // 被站方隱藏的主題：不出現在任何清單
    seedTopic("top_p_ad", "public", null, pid("tout"), "2026-11-11 08:00", "免費飆股群組，今天開放加入",
      "盤前給名單、盤中帶進帶出，加 LINE 就能進群。名額有限。", [], [], "hidden")

    // 檢舉：兩則待處理、兩則已處理（隱藏）
    seedReport("reply:rep_p_tsmc_3", [["tu", "abuse", "2026-11-12 09:40", "人身攻擊，不是在討論"], ["teacher", "abuse", "2026-11-12 10:10"]], "open")
    seedReport("reply:rep_p_div_2", [["yield", "solicitation", "2026-11-06 10:30"], ["saver", "spam", "2026-11-06 12:05", "同一句話貼在好幾個主題"], ["tu", "solicitation", "2026-11-06 20:15"]], "open")
    seedReport("reply:rep_p_tsmc_2", [["hsinchu", "solicitation", "2026-11-11 22:12", "拉人進 LINE 群組"], ["tu", "solicitation", "2026-11-11 22:15"], ["teacher", "solicitation", "2026-11-11 22:20"], ["saver", "spam", "2026-11-11 22:24"]], "resolved")
    seedReport("topic:top_p_ad", [["tu", "spam", "2026-11-11 08:20", "廣告"], ["saver", "spam", "2026-11-11 08:45", "每天都來貼"], ["dca", "spam", "2026-11-11 09:02"], ["newbie", "spam", "2026-11-11 09:30"]], "resolved")
    suspensions.push({ id: "sus_tout", user_id: pid("tout"), until: at("2026-12-11 22:30"), reason: "重複張貼招攬訊息", created_at: at("2026-11-11 22:30"), lifted: false })

    // 群組範圍：家族投資（三則）與大學同學（一則）
    seedTopic("top_g_dca", "group", "grp_family", PEOPLE.dad.user_id, "2026-11-06 20:15", "這個月的定期定額，大家扣了嗎？",
      "我兩個帳戶 6 號都扣了 0050。\n\n媽媽的好像還沒設定？這個月先手動買也可以，下個月再一起設成自動。",
      ["0050.TW"],
      [
        ["rep_g_dca_1", PEOPLE.mom.user_id, "2026-11-06 20:40", "我明天去問營業員怎麼設定。"],
        // 王叔叔已經離開群組：顯示「已離開的成員」
        ["rep_g_dca_2", PEOPLE.wang.user_id, "2026-11-06 21:05", "我也是 6 號扣，跟你們同一天。"],
        ["rep_g_dca_3", PEOPLE.sis.user_id, "2026-11-07 12:10", "我改成 16 號，發薪日之後比較有錢。"],
      ])
    react("topic:top_g_dca", "👍", [PEOPLE.mom.user_id, PEOPLE.sis.user_id])

    seedTopic("top_g_red", "group", "grp_family", PEOPLE.sis.user_id, "2026-11-09 21:30", "過年的紅包，要不要一起存 0056？",
      "每年紅包都不知不覺花掉。\n\n今年想說大家各拿一部分出來買 0056，放在自己的帳戶，明年過年再來比誰存得多。",
      ["0056.TW"],
      [
        ["rep_g_red_1", PEOPLE.dad.user_id, "2026-11-09 22:00", "好啊，先說我會存最多。"],
        ["rep_g_red_2", PEOPLE.bro.user_id, "2026-11-10 08:30", "那我只好認真了。"],
      ])
    react("topic:top_g_red", "🎉", [PEOPLE.dad.user_id, PEOPLE.mom.user_id, me])

    seedTopic("top_g_fix", "group", "grp_family", me, "2026-11-11 20:10", "我把聯發科的交易補記好了",
      "之前漏記的兩筆聯發科已經補上，排行的數字應該會跟著變。\n\n如果你們也有漏記的，補完跟大家說一聲，不然報酬率會看起來怪怪的。",
      ["2454.TW"],
      [["rep_g_fix_1", PEOPLE.dad.user_id, "2026-11-11 20:45", "收到，我的都有記。"]])
    react("topic:top_g_fix", "👍", [PEOPLE.dad.user_id])

    seedTopic("top_f_meet", "group", "grp_friends", PEOPLE.kai.user_id, "2026-11-08 19:00", "下次聚餐，順便對一下今年的績效？",
      "大家各自截圖帶來就好。記得開隱私模式，只看百分比。", [],
      [["rep_f_meet_1", PEOPLE.yun.user_id, "2026-11-08 19:30", "可以，我來訂位。"]])
  }
  if (options.suspended) {
    suspensions.push({ id: "sus_me", user_id: meId(), until: Date.parse(MOCK_AS_OF) + 7 * 86_400_000, reason: null, created_at: Date.parse(MOCK_AS_OF), lifted: false })
  }

  // ── 誰在看 ──
  const viewer = (): Viewer => {
    const signedIn = deps.signedIn()
    return { id: signedIn ? meId() : null, admin: signedIn && admin, roles: new Map(deps.myGroupRoles().map((g) => [g.id, g.role])) }
  }
  const requireUser = (): Viewer & { id: string } => {
    const v = viewer()
    if (!v.id) throw loginRequired()
    return v as Viewer & { id: string }
  }
  const requireAdmin = () => {
    const v = requireUser()
    // 不是管理員 → 404（和不存在的路徑一樣）
    if (!v.admin) throw new ApiError(404, "not_found", "找不到這個頁面")
    return v
  }
  const publicNameOf = (userId: string | null) => (userId === null ? null : userId === meId() ? myPublicName : (publicNames.get(userId) ?? null))
  const activeSuspension = (userId: string, now = deps.now()) =>
    suspensions.filter((s) => s.user_id === userId && !s.lifted && s.until > now).sort((a, b) => b.until - a.until)[0] ?? null

  // ── 讀得到什麼 ──
  /** 看得到這個主題才回傳：公開 → 任何人；群組 → 成員。其他一律 404（不透露存在，沒登入也一樣） */
  const visibleTopic = (v: Viewer, id: string): MockTopic => {
    const t = topics.find((x) => x.id === id)
    if (!t || (t.scope === "group" && !v.roles.has(t.group_id ?? ""))) throw notFound()
    return t
  }
  const target = (v: Viewer, raw: string): { kind: "topic" | "reply"; topic: MockTopic; reply: MockReply | null } => {
    if (!TARGET_RE.test(raw ?? "")) throw invalid("輸入資料格式錯誤：target")
    const [kind, id] = raw.split(":") as ["topic" | "reply", string]
    if (kind === "topic") return { kind, topic: visibleTopic(v, id), reply: null }
    const reply = replies.find((r) => r.id === id)
    if (!reply) throw notFound("找不到這則內容")
    return { kind, topic: visibleTopic(v, reply.topic_id), reply }
  }
  /** 站方管理員的對象：只有公開內容，群組內容對站方不存在（404） */
  const publicTarget = (raw: string) => {
    if (!TARGET_RE.test(raw ?? "")) throw invalid("輸入資料格式錯誤：target")
    const [kind, id] = raw.split(":") as ["topic" | "reply", string]
    const reply = kind === "reply" ? (replies.find((r) => r.id === id) ?? null) : null
    const topic = topics.find((t) => t.id === (reply ? reply.topic_id : kind === "topic" ? id : ""))
    if (!topic || topic.scope !== "public" || (kind === "reply" && !reply)) throw notFound("找不到這則內容")
    return { kind, topic, reply }
  }
  const canDelete = (v: Viewer, t: MockTopic, authorId: string | null) => {
    if (!v.id) return false
    const manages = t.scope === "group" && MANAGERS.includes(v.roles.get(t.group_id ?? "") as GroupRole)
    return (authorId !== null && authorId === v.id) || manages
  }
  const canReport = (v: Viewer, t: MockTopic, authorId: string | null) => t.scope === "public" && v.id !== null && authorId !== v.id
  const bodyFor = (v: Viewer, t: MockTopic, status: DiscussionStatus, authorId: string | null, body: string) =>
    status !== "hidden" || (authorId !== null && authorId === v.id) || (v.admin && t.scope === "public") ? body : null

  // ── 輸出 ──
  const authorOut = (v: Viewer, t: MockTopic, userId: string | null): DiscussionAuthor => {
    // 公開：只有公開暱稱與 is_you 兩個鍵（沒有 user_id、顯示名稱、頭像）
    if (t.scope === "public") return { name: publicNameOf(userId), is_you: userId !== null && userId === v.id }
    if (userId === null) return { name: null, is_you: false, user_id: null, avatar_url: null }
    const member = deps.groupRoster(t.group_id ?? "")?.members.find((m) => m.user_id === userId)
    if (!member) return { name: LEFT_MEMBER, is_you: false, user_id: null, avatar_url: null }
    return { name: member.display_name, is_you: userId === v.id, user_id: member.user_id, avatar_url: member.avatar_url }
  }
  const symbolsOut = (symbols: string[]): TopicSymbol[] =>
    symbols.map((s) => {
      const spec = findInstrument(s)
      return { symbol: s, code: spec?.code ?? s, name: spec?.name ?? s }
    })
  const reactionsOf = (key: string, me: string | null): Reaction[] => {
    const map = reactions.get(key)
    if (!map) return []
    return REACTION_EMOJIS.flatMap((emoji) => {
      const users = map.get(emoji)
      return users && users.size > 0 ? [{ emoji, count: users.size, mine: me !== null && users.has(me) }] : []
    })
  }
  const base = (v: Viewer, t: MockTopic) => {
    const roster = t.scope === "group" ? deps.groupRoster(t.group_id ?? "") : null
    return {
      id: t.id, scope: t.scope, group: roster ? { id: roster.id, name: roster.name } : null, title: t.title, symbols: symbolsOut(t.symbols),
      author: authorOut(v, t, t.user_id), created_at: iso(t.created_at), last_activity_at: iso(t.last_activity_at),
      reply_count: replies.filter((r) => r.topic_id === t.id).length, status: t.status, mine: t.user_id !== null && t.user_id === v.id,
    }
  }
  const topicOut = (v: Viewer, t: MockTopic): Topic => {
    const out: Topic = {
      ...base(v, t),
      body: bodyFor(v, t, t.status, t.user_id, t.body),
      reactions: reactionsOf(`topic:${t.id}`, v.id),
      can_delete: canDelete(v, t, t.user_id),
      can_report: canReport(v, t, t.user_id),
      can_reply: v.id !== null && t.status === "visible",
    }
    // 隱藏的主題：標題本身可能就是有害的部分（廣告、帶單），其他人拿到佔位標題、沒有標記
    if (t.status === "hidden" && out.body === null) return { ...out, title: HIDDEN_TITLE, symbols: [] }
    return out
  }
  const replyOut = (v: Viewer, t: MockTopic, r: MockReply): Reply => ({
    id: r.id, topic_id: r.topic_id, body: bodyFor(v, t, r.status, r.user_id, r.body), author: authorOut(v, t, r.user_id), created_at: iso(r.created_at),
    status: r.status, reactions: reactionsOf(`reply:${r.id}`, v.id), mine: r.user_id !== null && r.user_id === v.id,
    can_delete: canDelete(v, t, r.user_id), can_report: canReport(v, t, r.user_id),
  })

  // ── 發言前的檢查：停權 → 公開暱稱 → 頻率 ──
  const checkRate = (userId: string, scope: DiscussionScope, kind: "topic" | "reply", now: number) => {
    const limit = RATE[scope][kind]
    const times = postLog.filter((p) => p.user_id === userId && p.scope === scope && p.kind === kind && p.at > now - limit.window).map((p) => p.at).sort((a, b) => a - b)
    let wait = 0
    if (times.length >= limit.count) wait = times[times.length - limit.count]! + limit.window - now
    if (scope === "public") {
      const last = Math.max(-Infinity, ...postLog.filter((p) => p.user_id === userId && p.scope === "public").map((p) => p.at))
      if (Number.isFinite(last)) wait = Math.max(wait, last + PUBLIC_POST_GAP - now)
    }
    if (wait > 0) {
      const seconds = Math.max(1, Math.ceil(wait / 1000))
      throw new ApiError(429, "rate_limited", `發言太頻繁，請 ${seconds} 秒後再試`, { retry_after_seconds: seconds })
    }
  }
  const guardPost = (userId: string, scope: DiscussionScope, kind: "topic" | "reply", now: number) => {
    if (scope === "public") {
      const s = activeSuspension(userId, now)
      if (s) throw new ApiError(403, "posting_suspended", "你的公開發言已被站方暫停", { until: iso(s.until) })
      if (!publicNameOf(userId)) throw new ApiError(409, "public_name_required", "發公開內容前要先設定公開暱稱")
    }
    checkRate(userId, scope, kind, now)
  }
  const purge = (ids: string[]) => {
    const gone = new Set(ids)
    const goneReplies = replies.filter((r) => gone.has(r.topic_id)).map((r) => `reply:${r.id}`)
    const keys = new Set([...ids.map((id) => `topic:${id}`), ...goneReplies])
    for (const k of keys) reactions.delete(k)
    reports = reports.filter((r) => !keys.has(r.target))
    replies = replies.filter((r) => !gone.has(r.topic_id))
    topics = topics.filter((t) => !gone.has(t.id))
  }
  const text = (raw: unknown, max: number, what: string) => {
    if (typeof raw !== "string") throw invalid(`輸入資料格式錯誤：${what}`)
    const problem = bodyProblem(raw, max, what)
    if (problem) throw invalid(problem)
    return normalizeText(raw)
  }

  return {
    // ── 個人資料多出來的三個欄位、公開暱稱 ──
    meFields(): { public_name: string | null; is_admin: boolean; public_posting_suspended_until: string | null } {
      const s = activeSuspension(meId())
      return { public_name: myPublicName, is_admin: admin, public_posting_suspended_until: s ? iso(s.until) : null }
    },
    setPublicName(raw: string): void {
      requireUser()
      const problem = typeof raw === "string" ? publicNameProblem(raw) : `公開暱稱需為 ${PUBLIC_NAME_MIN}–${PUBLIC_NAME_MAX} 字`
      if (problem) throw invalid(problem)
      const name = raw.trim()
      if (name === myPublicName) return
      const now = deps.now()
      if (myNameChangedAt !== null) {
        const wait = myNameChangedAt + PUBLIC_NAME_COOLDOWN - now
        if (wait > 0) {
          const days = Math.max(1, Math.ceil(wait / 86_400_000))
          throw new ApiError(409, "public_name_cooldown", `公開暱稱 7 天內只能改一次，${days} 天後可以再改`, { retry_after_days: days })
        }
      }
      const key = nameKey(name)
      if ([...publicNames.values()].some((n) => nameKey(n) === key)) throw new ApiError(409, "public_name_taken", "這個公開暱稱已經有人使用")
      // 第一次設定不啟動冷卻：打錯字可以馬上改一次
      if (myPublicName !== null) myNameChangedAt = now
      myPublicName = name
    },

    // ── 主題 ──
    listTopics(query: TopicQuery = {}): Paged<TopicSummary> {
      const v = viewer()
      const scope = query.scope ?? "public"
      if (!["public", "group", "all"].includes(scope)) throw invalid("輸入資料格式錯誤：scope")
      const sort = query.sort ?? "active"
      if (sort !== "active" && sort !== "new") throw invalid("輸入資料格式錯誤：sort")
      const limit = query.limit ?? 30
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw invalid("輸入資料格式錯誤：limit")
      if (!v.id && (scope !== "public" || query.mine)) throw loginRequired()
      let rows = topics.filter((t) => t.status === "visible")
      if (scope === "public") rows = rows.filter((t) => t.scope === "public")
      else if (scope === "group") {
        if (!query.group_id) throw invalid("請指定群組")
        if (!v.roles.has(query.group_id)) throw notFound("找不到群組")
        rows = rows.filter((t) => t.scope === "group" && t.group_id === query.group_id)
      } else rows = rows.filter((t) => t.scope === "public" || v.roles.has(t.group_id ?? ""))
      if (query.symbol?.trim()) {
        const resolved = findInstrument(query.symbol.trim())?.symbol ?? query.symbol.trim().toUpperCase()
        rows = rows.filter((t) => t.symbols.includes(resolved))
      }
      if (query.mine) rows = rows.filter((t) => t.user_id === v.id)
      const col = (t: MockTopic) => (sort === "active" ? t.last_activity_at : t.created_at)
      rows.sort((a, b) => col(b) - col(a) || (a.id < b.id ? 1 : -1))
      if (query.cursor) {
        const [before, beforeId] = decodeCursor(query.cursor)
        rows = rows.filter((t) => col(t) < before || (col(t) === before && t.id < beforeId))
      }
      const page = rows.slice(0, limit)
      const last = rows.length > limit ? page[page.length - 1]! : null
      return {
        items: page.map((t) => ({ ...base(v, t), excerpt: excerptOf(t.body) })),
        next_cursor: last ? encodeCursor(col(last), last.id) : null,
      }
    },
    createTopic(body: TopicInput): Topic {
      const v = requireUser()
      if (body?.scope !== "public" && body?.scope !== "group") throw invalid("輸入資料格式錯誤：scope")
      if (typeof body.title !== "string") throw invalid("輸入資料格式錯誤：title")
      const titleBad = titleProblem(body.title, TOPIC_TITLE_MAX)
      if (titleBad) throw invalid(titleBad)
      const content = text(body.body, TOPIC_BODY_MAX, "內文")
      const wanted = body.symbols ?? []
      if (!Array.isArray(wanted) || wanted.length > TOPIC_SYMBOLS_MAX) throw invalid(`最多標記 ${TOPIC_SYMBOLS_MAX} 檔股票`)
      if (body.scope === "group") {
        if (!body.group_id) throw invalid("群組範圍的主題要指定群組")
        if (!v.roles.has(body.group_id)) throw notFound("找不到群組")
      } else if (body.group_id) throw invalid("公開主題不能指定群組")
      const symbols: string[] = []
      for (const s of wanted) {
        const spec = typeof s === "string" ? findInstrument(s) : undefined
        if (!spec) throw invalid(`找不到商品：${String(s)}`, "unknown_symbol")
        if (!symbols.includes(spec.symbol)) symbols.push(spec.symbol)
      }
      const now = deps.now()
      guardPost(v.id, body.scope, "topic", now)
      const t: MockTopic = {
        id: newId("top"), scope: body.scope, group_id: body.scope === "group" ? body.group_id! : null, user_id: v.id, title: body.title.trim(),
        body: content, symbols, status: "visible", created_at: now, last_activity_at: now,
      }
      topics.push(t)
      postLog.push({ user_id: v.id, scope: body.scope, kind: "topic", at: now })
      return topicOut(v, t)
    },
    getTopic(id: string): Topic {
      const v = viewer()
      return topicOut(v, visibleTopic(v, id))
    },
    deleteTopic(id: string): void {
      const v = requireUser()
      const t = visibleTopic(v, id)
      if (!canDelete(v, t, t.user_id)) throw new ApiError(403, "forbidden", "只有作者或群組管理員可以刪除主題")
      purge([t.id])
    },

    // ── 回覆（舊到新） ──
    listReplies(topicId: string, query: { limit?: number; cursor?: string | null } = {}): Paged<Reply> {
      const v = viewer()
      const t = visibleTopic(v, topicId)
      const limit = query.limit ?? 50
      if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw invalid("輸入資料格式錯誤：limit")
      let rows = replies.filter((r) => r.topic_id === t.id).sort((a, b) => a.created_at - b.created_at || (a.id < b.id ? -1 : 1))
      if (query.cursor) {
        const [after, afterId] = decodeCursor(query.cursor)
        rows = rows.filter((r) => r.created_at > after || (r.created_at === after && r.id > afterId))
      }
      const page = rows.slice(0, limit)
      const last = page[page.length - 1]
      return { items: page.map((r) => replyOut(v, t, r)), next_cursor: rows.length > limit && last ? encodeCursor(last.created_at, last.id) : null }
    },
    createReply(topicId: string, body: { body: string }): Reply {
      const v = requireUser()
      const content = text(body?.body, REPLY_BODY_MAX, "回覆")
      const t = visibleTopic(v, topicId)
      if (t.status === "hidden") throw new ApiError(409, "topic_hidden", "這個主題已被站方隱藏，不能回覆")
      const now = deps.now()
      guardPost(v.id, t.scope, "reply", now)
      const r: MockReply = { id: newId("rep"), topic_id: t.id, user_id: v.id, body: content, status: "visible", created_at: now }
      replies.push(r)
      t.last_activity_at = Math.max(t.last_activity_at, now)
      postLog.push({ user_id: v.id, scope: t.scope, kind: "reply", at: now })
      return replyOut(v, t, r)
    },
    deleteReply(id: string): void {
      const v = requireUser()
      const { topic, reply } = target(v, `reply:${id}`)
      if (!reply || !canDelete(v, topic, reply.user_id)) throw new ApiError(403, "forbidden", "只有作者或群組管理員可以刪除回覆")
      reactions.delete(`reply:${reply.id}`)
      reports = reports.filter((r) => r.target !== `reply:${reply.id}`)
      replies = replies.filter((r) => r !== reply)
      // 最後活動時間退回剩下最新的那一則（沒有回覆就是主題建立時間）
      topic.last_activity_at = Math.max(topic.created_at, ...replies.filter((r) => r.topic_id === topic.id).map((r) => r.created_at))
    },

    // ── 表情（204，沒有內容） ──
    addReaction(body: { target: string; emoji: ReactionEmoji }): void {
      const v = requireUser()
      if (!REACTION_EMOJIS.includes(body?.emoji)) throw invalid("輸入資料格式錯誤：emoji")
      target(v, body.target)
      const map = reactions.get(body.target) ?? new Map<ReactionEmoji, Set<string>>()
      map.set(body.emoji, new Set([...(map.get(body.emoji) ?? []), v.id]))
      reactions.set(body.target, map)
    },
    removeReaction(key: string, emoji: ReactionEmoji): void {
      const v = requireUser()
      if (!REACTION_EMOJIS.includes(emoji)) throw invalid("輸入資料格式錯誤：emoji")
      target(v, key)
      reactions.get(key)?.get(emoji)?.delete(v.id)
    },

    // ── 檢舉（只有公開內容） ──
    report(body: ReportInput): void {
      const v = requireUser()
      if (!REPORT_REASONS.includes(body?.reason)) throw invalid("輸入資料格式錯誤：reason")
      const note = body.note?.trim() ? text(body.note.trim(), REPORT_NOTE_MAX, "補充說明") : null
      const { topic, reply } = target(v, body.target)
      if (topic.scope !== "public") throw invalid("群組裡的內容不能檢舉，請找群組管理員處理")
      if ((reply ?? topic).user_id === v.id) throw invalid("不能檢舉自己的內容")
      // 同一人對同一則只留第一次
      if (reports.some((r) => r.target === body.target && r.reporter_id === v.id)) return
      const now = deps.now()
      const recent = reports.filter((r) => r.reporter_id === v.id && r.created_at > now - REPORT_LIMIT.window).map((r) => r.created_at).sort((a, b) => a - b)
      if (recent.length >= REPORT_LIMIT.count) {
        const seconds = Math.max(1, Math.ceil((recent[recent.length - REPORT_LIMIT.count]! + REPORT_LIMIT.window - now) / 1000))
        throw new ApiError(429, "rate_limited", `檢舉太頻繁，請 ${seconds} 秒後再試`, { retry_after_seconds: seconds })
      }
      // 已處理過的對象再被檢舉，會回到待處理（這一筆是 open）
      reports.push({ target: body.target, reporter_id: v.id, reason: body.reason, note, status: "open", created_at: now })
    },

    // ── 站方管理（不回傳 email、user_id；用「某一則內容」指定作者） ──
    adminReports(query: { status?: "open" | "resolved"; limit?: number; cursor?: string | null } = {}): Paged<AdminReport> {
      requireAdmin()
      const status = query.status ?? "open"
      if (status !== "open" && status !== "resolved") throw invalid("輸入資料格式錯誤：status")
      const limit = query.limit ?? 30
      const byTarget = new Map<string, MockReport[]>()
      for (const r of [...reports].sort((a, b) => a.created_at - b.created_at)) byTarget.set(r.target, [...(byTarget.get(r.target) ?? []), r])
      let rows = [...byTarget.entries()]
        .map(([key, list]) => ({ key, id: key.split(":")[1]!, list, last: list[list.length - 1]!.created_at, open: list.filter((r) => r.status === "open").length }))
        .filter((x) => (status === "open" ? x.open > 0 : x.open === 0))
        .sort((a, b) => b.last - a.last || (a.id < b.id ? 1 : -1))
      if (query.cursor) {
        const [before, beforeId] = decodeCursor(query.cursor)
        rows = rows.filter((x) => x.last < before || (x.last === before && x.id < beforeId))
      }
      const page = rows.slice(0, limit)
      const lastRow = page[page.length - 1]
      const items = page.flatMap((x): AdminReport[] => {
        let found: ReturnType<typeof publicTarget>
        try {
          found = publicTarget(x.key)
        } catch {
          return []
        }
        const { kind, topic, reply } = found
        const content = reply ?? topic
        const reasons: Partial<Record<ReportReason, number>> = {}
        for (const r of x.list) reasons[r.reason] = (reasons[r.reason] ?? 0) + 1
        return [{
          target: x.key, kind, excerpt: excerptOf(reply ? reply.body : `${topic.title}｜${topic.body}`),
          author_name: publicNameOf(content.user_id), topic_id: topic.id, report_count: x.list.length, reasons,
          notes: x.list.flatMap((r) => (r.note ? [r.note] : [])), first_reported_at: iso(x.list[0]!.created_at),
          status: x.open > 0 ? "open" : "resolved", hidden: content.status === "hidden",
        }]
      })
      return { items, next_cursor: rows.length > limit && lastRow ? encodeCursor(lastRow.last, lastRow.id) : null }
    },
    moderate(body: { target: string; action: ModerationAction }): void {
      requireAdmin()
      if (!["hide", "unhide", "dismiss"].includes(body?.action)) throw invalid("輸入資料格式錯誤：action")
      const { topic, reply } = publicTarget(body.target)
      const content = reply ?? topic
      if (body.action === "hide") content.status = "hidden"
      else if (body.action === "unhide") content.status = "visible"
      if (body.action !== "unhide") for (const r of reports) if (r.target === body.target && r.status === "open") r.status = "resolved"
    },
    listSuspensions(): Suspension[] {
      requireAdmin()
      const now = deps.now()
      return suspensions
        .filter((s) => !s.lifted && s.until > now)
        .sort((a, b) => b.created_at - a.created_at || (a.id < b.id ? 1 : -1))
        .map((s) => ({ id: s.id, public_name: publicNameOf(s.user_id), until: iso(s.until), reason: s.reason, created_at: iso(s.created_at) }))
    },
    createSuspension(body: { target: string; days: SuspensionDays; reason?: string }): Suspension {
      requireAdmin()
      // days 一定要給：永久要明確傳 null（避免漏欄位變成永久停權）
      if (!body || !("days" in body) || ![1, 7, 30, null].includes(body.days)) throw invalid("輸入資料格式錯誤：days")
      const { topic, reply } = publicTarget(body.target)
      const authorId = (reply ?? topic).user_id
      if (authorId === null) throw invalid("這則內容的作者帳號已刪除")
      const now = deps.now()
      let s = activeSuspension(authorId, now)
      if (!s) {
        s = { id: newId("sus"), user_id: authorId, until: 0, reason: null, created_at: now, lifted: false }
        suspensions.push(s)
      }
      // 對已停權的人再停權：改掉原本那一筆
      s.until = body.days === null ? PERMANENT : now + body.days * 86_400_000
      s.reason = body.reason?.trim() || null
      return { id: s.id, public_name: publicNameOf(authorId), until: iso(s.until), reason: s.reason, created_at: iso(s.created_at) }
    },
    liftSuspension(id: string): void {
      requireAdmin()
      const s = suspensions.find((x) => x.id === id)
      if (!s) throw notFound("找不到這筆停權")
      s.lifted = true
    },

    /** 刪除群組時，連同它的主題一起刪 */
    purgeGroup(groupId: string): void {
      purge(topics.filter((t) => t.group_id === groupId).map((t) => t.id))
    },
  }
}
