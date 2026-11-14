/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// `/api` 轉給本機後端：`pnpm dev:api` 時前端用同源的 /api/v1，session cookie 不必跨站。
// 後端位址可用 FORLIOSA_API_ORIGIN 覆寫（例如 http://127.0.0.1:8001）。
const apiProxy = {
  "/api": { target: process.env.FORLIOSA_API_ORIGIN ?? "http://localhost:8000", changeOrigin: false },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: { port: 5173, host: true, proxy: apiProxy },
  preview: { port: 4173, proxy: apiProxy },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("lightweight-charts")) return "kline"
          if (id.includes("recharts") || id.includes("d3-") || id.includes("victory-vendor")) return "charts"
          if (id.includes("@fontsource")) return undefined
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "react"
          if (id.includes("@tanstack")) return "tanstack"
          if (id.includes("@base-ui") || id.includes("@floating-ui")) return "base-ui"
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    // 整批跑時 50 幾個檔案同時開 jsdom：走完整流程的畫面測試（打字、存檔、重抓）在機器忙時會超過預設的 5 秒
    testTimeout: 15_000,
  },
})
