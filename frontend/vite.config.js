import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vite 配置（《开发流程》3.2：Vite 5.4.8）
// dev 环境把 /api 前缀代理到本机后端 8000 端口，避免浏览器跨域问题。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // ⚠️ **`/static` 也必须代理（2026-09-29 补）。**
      //
      // 后端用 `StaticFiles` 把导出目录挂在 `/static` 下，看板的「导出报告」
      // 返回的 `exportUrl` 就是 `/static/exports/dashboard_*.csv`。
      // 只代理 `/api` 时，浏览器会带着这个相对路径打到 **5173**，
      // 被 Vite 的 SPA fallback 接住 —— **HTTP 状态还是 200**，
      // 但下到的是 491 字节的 `index.html` 而不是 1KB 的 CSV。
      // 用户看到的只是「下载了个打不开的文件」，从状态码上完全看不出问题。
      '/static': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          // ⚠️ 2026-09-30 删掉了原来的 `echarts: ['echarts']`。
          //
          // 本平台已经**没有任何页面**引用 echarts：Dashboard 原来那两个图
          // （柱状 + 饼图）按新原型 `docs/new_web.html` 换成了纯 CSS 的
          // `.sp-chart/.sp-bar` 与 `.sp-table`。这个条目留着不会报错，
          // 但每次构建都会产出一个 **0.00 kB 的空 chunk** 白占一个文件。
          //
          // 注意：`echarts` 依赖本身**仍留在 package.json**（未卸载）。
          // 将来若有页面重新引入它，会并进那个页面的 chunk ——
          // 想恢复独立分包，把这一行加回来即可。
          fullcalendar: [
            '@fullcalendar/core',
            '@fullcalendar/vue3',
            '@fullcalendar/daygrid',
            '@fullcalendar/timegrid',
            '@fullcalendar/interaction',
          ],
          element: ['element-plus', '@element-plus/icons-vue'],
          vue: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
})
