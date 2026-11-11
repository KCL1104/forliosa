import { create } from "zustand"
import { persist } from "zustand/middleware"

/** 自選清單（M2 之前先存在本機；之後改由後端 watchlists 同步） */
interface WatchlistState {
  symbols: string[]
  toggle: (symbol: string) => void
}

export const useWatchlist = create<WatchlistState>()(
  persist(
    (set) => ({
      symbols: [],
      toggle: (symbol) =>
        set((s) => ({ symbols: s.symbols.includes(symbol) ? s.symbols.filter((x) => x !== symbol) : [...s.symbols, symbol] })),
    }),
    { name: "forliosa:watchlist", version: 1 },
  ),
)
