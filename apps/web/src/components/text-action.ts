/**
 * 文字動作：清單列裡的次要動作（編輯、修改、修改範圍、移除、加表情、留言）與要緊的文字連結。
 * 墨色字＋常駐 ctl 色底線（滑過底線變墨色）——不是只有灰字的 ghost，看得出可以按；觸控時高 44px。
 * 用在 <button>、<a>、<Link>；預設 14px。
 */
export const textAction =
  "press inline-flex min-h-8 items-center rounded-xs text-md text-ink underline decoration-ctl decoration-1 underline-offset-4 transition-[text-decoration-color] hover:decoration-ink disabled:pointer-events-none disabled:opacity-50 pointer-coarse:min-h-11"
