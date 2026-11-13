/**
 * 整頁重新載入到另一個網址（不是站內換頁）：記憶體裡的東西（查詢快取、各個 store）全部重來。
 * 刪除帳號之後用它回到登入頁。獨立一個函式，測試時可以換掉（jsdom 不能真的換頁）。
 */
export function hardNavigate(url: string): void {
  window.location.assign(url)
}
