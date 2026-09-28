import { createSSRApp } from 'vue'
import App from './App.vue'

// uni-app Vue3 入口：必须导出 createApp 工厂函数
export function createApp() {
  const app = createSSRApp(App)
  return { app }
}
