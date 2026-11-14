import { createContext } from "react"

/**
 * 浮出來的東西（選單）要掛在哪個元素底下：抽屜裡是抽屜本身（見 drawer.tsx），其他地方是 null（照常掛在 body）。
 */
export const PortalContainer = createContext<HTMLElement | null>(null)
