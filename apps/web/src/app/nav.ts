import {
  ArrowLeftRightIcon,
  ChartLineIcon,
  FileTextIcon,
  FileUpIcon,
  HouseIcon,
  LayersIcon,
  MenuIcon,
  MessageSquareTextIcon,
  SettingsIcon,
  StarIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react"

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** 尚未推出的里程碑（側欄顯示小字） */
  milestone?: string
}

/** 桌面側欄（順序依 spec §5） */
export const NAV_MAIN: NavItem[] = [
  { to: "/", label: "總覽", icon: HouseIcon },
  { to: "/holdings", label: "持股", icon: LayersIcon },
  { to: "/transactions", label: "交易", icon: ArrowLeftRightIcon },
  { to: "/watchlist", label: "自選", icon: StarIcon, milestone: "M2" },
  { to: "/performance", label: "績效", icon: ChartLineIcon },
]
export const NAV_AI: NavItem[] = [
  { to: "/ai", label: "AI 助理", icon: MessageSquareTextIcon, milestone: "M4" },
  { to: "/reports", label: "報告", icon: FileTextIcon, milestone: "M4" },
  { to: "/groups", label: "群組", icon: UsersIcon, milestone: "M5" },
]
export const NAV_DATA: NavItem[] = [
  { to: "/import", label: "匯入", icon: FileUpIcon, milestone: "M3" },
  { to: "/settings", label: "設定", icon: SettingsIcon },
]

/** 手機底部五個分頁 */
export const MOBILE_TABS: NavItem[] = [
  { to: "/", label: "總覽", icon: HouseIcon },
  { to: "/holdings", label: "持股", icon: LayersIcon },
  { to: "/watchlist", label: "自選", icon: StarIcon },
  { to: "/ai", label: "AI", icon: MessageSquareTextIcon },
  { to: "/more", label: "更多", icon: MenuIcon },
]

/** 「更多」頁列出的項目 */
export const MORE_ITEMS: NavItem[] = [
  { to: "/transactions", label: "交易紀錄", icon: ArrowLeftRightIcon },
  { to: "/performance", label: "績效分析", icon: ChartLineIcon },
  { to: "/reports", label: "報告", icon: FileTextIcon, milestone: "M4" },
  { to: "/groups", label: "群組", icon: UsersIcon, milestone: "M5" },
  { to: "/import", label: "匯入對帳單", icon: FileUpIcon, milestone: "M3" },
  { to: "/settings", label: "設定", icon: SettingsIcon },
]

export function isActivePath(pathname: string, to: string): boolean {
  if (to === "/") return pathname === "/"
  return pathname === to || pathname.startsWith(`${to}/`)
}
