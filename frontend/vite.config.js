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
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts'],
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
