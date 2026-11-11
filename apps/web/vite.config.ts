/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: { port: 5173, host: true },
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
  },
})
