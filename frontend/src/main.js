import { createPinia } from 'pinia'
import { createApp } from 'vue'

import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/index.css'

const app = createApp(App)

// 全量注册 Element Plus 图标（按图标名使用，如 <el-icon><Menu /></el-icon>）
for (const [iconName, iconComponent] of Object.entries(ElementPlusIconsVue)) {
  app.component(iconName, iconComponent)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
