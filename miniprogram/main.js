import { createSSRApp } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import App from './App.vue'

// 导出并激活 Pinia，便于在非组件上下文（utils/ws.js）中调用 store
export const pinia = createPinia()
setActivePinia(pinia)

export function createApp() {
  const app = createSSRApp(App)
  app.use(pinia)
  return { app }
}
