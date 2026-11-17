import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"
import { appToday, marketNow } from "@/api"
import { useHoldings, useMarketStatus, useSummary } from "@/api/queries"
import type { Market, TwClose } from "@/api/types"
import { closeLine, closeNote, closesChanged, closeState, dayWord, indexNote, ledgerBoardDays, ledgerUsCloseDay, twClose, type CloseState, type TwBoard } from "@/lib/as-of"
import { formatDateShort } from "@/lib/format"
import { usCloseLabel } from "@/lib/labels"
import { useRealtime } from "@/realtime/store"

/** 台股的市場（上市／上櫃）；美股與不知道的是 null */
export const twBoard = (market: Market | null | undefined): TwBoard | null => (market === "TWSE" || market === "TPEX" ? market : null)

/**
 * 一個收盤價（報價的 `as_of`）現在該怎麼標，`market` 是它的市場（上市、上櫃各自公布的時間不同）：
 * - `state`／`note`：盤中「盤中不更新」；該進來的還沒進來時寫預計幾點更新（「今天的收盤價預計下午 2:00–2:30 更新」）；
 *   其他時候沒有（見 lib/as-of.ts）
 * - `day`：「今日」損益、「今日漲跌」的那個詞——收盤價的日期就是今天才寫「今日」，否則寫那個日期（「11/12」）
 * 市場狀態大約每分鐘更新一次；還沒載入時不加說明，「今天」先用本機的台北日期。
 */
export function useClose(asOf: string | null | undefined, market?: Market | null): { state: CloseState; note: string | null; day: string } {
  const status = useMarketStatus().data?.tw
  const now = marketNow()
  const board = twBoard(market)
  const state = closeState(status, asOf, now, board)
  return { state, note: closeNote(state, asOf, twClose(status, board), now), day: dayWord(asOf, status?.date ?? appToday()) }
}

/**
 * 帳本（全部帳戶）的收盤：主數字旁的那一行（`label`、在等時的 `note`）和「今日」損益、「今日漲跌」的那個詞（`day`）。
 * - 有台股的價格：上市、上櫃分開看（`closeLine`）——「11/12 收盤」＋「上市預計下午 2:30 前更新・上櫃預計今晚更新」，
 *   兩個市場的日期不同時「上市 11/16・上櫃 11/13 收盤」；每個市場都是今天的收盤才寫「今日」
 * - 只有美股有價格（`ledgerUsCloseDay`）：紐約的交易日「11/13 收盤（美東）」與「11/13」——那是紐約那一天的收盤，
 *   不套台股的盤中／還沒公布，也不寫「今日」
 */
export function useLedgerClose(): { label: string; note: string | null; day: string } {
  const summary = useSummary().data
  const holdings = useHoldings().data
  const status = useMarketStatus().data?.tw
  const us = ledgerUsCloseDay(summary, holdings)
  if (us) return { label: usCloseLabel(us), note: null, day: formatDateShort(us, false) }
  return closeLine(status, ledgerBoardDays(holdings, summary?.as_of), summary?.as_of, marketNow(), status?.date ?? appToday())
}

/**
 * 市場頁標題旁的說明：上市或上櫃的收盤價還沒進來時，預計幾點更新（「上市預計下午 2:30 前更新・上櫃預計今晚更新」）；
 * 寫法和帳本一樣（`closeLine`），市場的日期用後端存到的那天（`tw.closes` 的 `latest`）。舊版後端沒有 `closes`：不加說明。
 */
export function useMarketCloseNote(asOf: string | null | undefined): string | null {
  const status = useMarketStatus().data?.tw
  const boards = (status?.closes ?? []).flatMap((c) => (c.latest ? [{ board: c.market, day: c.latest }] : []))
  if (!boards.length) return null
  return closeLine(status, boards, asOf, marketNow(), status?.date ?? appToday()).note
}

/**
 * 市場頁指數那一排下面的一行：上市個股的收盤價進來了、加權指數還沒有時，指數預計什麼時候進來（`indexNote`）。
 * 舊版後端沒有 `index`：null。
 */
export function useIndexCloseNote(): string | null {
  const status = useMarketStatus().data?.tw
  return indexNote(twClose(status, "TWSE"), marketNow())
}

/** 收盤價進來時重新讀的查詢：帳本（摘要、持股、績效、部位）、報價、觀察清單、市場頁、走勢圖、估值、「為什麼」 */
const CLOSE_QUERIES = [["portfolio"], ["quote"], ["watchlist"], ["market"], ["history"], ["valuation"], ["overview"], ["why"]] as const

/**
 * 第一次重新讀之後再讀一次的間隔：後端的報價快取 30 秒（`marketdata/service.py` QUOTE_TTL_SECONDS），
 * 收盤價剛存進去的那 30 秒內讀到的可能還是快取裡前一天的價格——之後就沒有東西會再讓帳本更新（2026-11-16 審查）
 */
export const CLOSE_REFETCH_AGAIN_MS = 35_000

/**
 * 即時更新的 `market.closes` 剛處理過（這段時間內）：伺服器已經先清掉報價快取、畫面也已經重新讀過，這裡不再重複
 */
export const CLOSE_EVENT_COVERS_MS = 2 * 60_000

/**
 * 收盤價一進來就自己更新（不跳通知）：`market-status` 每分鐘問一次（分頁在背景時不問，回到分頁時馬上問），
 * 任何一個市場的收盤價進來了（`closesChanged`），就讓帳本、報價與市場頁重新讀，35 秒後再讀一次（後端報價快取過期後）。
 * 掛在外殼上，一個分頁一份。
 *
 * 即時更新連著時，收盤價一存進去伺服器就通知（`realtime/topics.ts` 的 `market.closes`，同時讓 `market-status` 重新讀）：
 * 剛收到過通知就不再重新讀一次。沒有收到通知（即時更新斷著、mock 模式，或萬一哪一條路沒有通知）時照舊，這裡是保險。
 */
export function useCloseRefresh(): void {
  const qc = useQueryClient()
  const closes = useMarketStatus().data?.tw.closes
  const prev = useRef<readonly TwClose[] | undefined>(undefined)
  const again = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  useEffect(() => {
    if (!closes) return
    const covered = Date.now() - useRealtime.getState().closesAt < CLOSE_EVENT_COVERS_MS
    if (closesChanged(prev.current, closes) && !covered) {
      const refetch = () => {
        for (const queryKey of CLOSE_QUERIES) void qc.invalidateQueries({ queryKey: [...queryKey] })
      }
      refetch()
      clearTimeout(again.current)
      again.current = setTimeout(refetch, CLOSE_REFETCH_AGAIN_MS)
    }
    prev.current = closes
  }, [closes, qc])
  useEffect(() => () => clearTimeout(again.current), [])
}
