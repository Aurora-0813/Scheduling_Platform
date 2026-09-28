<script setup>
import { onLaunch } from '@dcloudio/uni-app'
import { restoreSession } from '@/store/user.js'

onLaunch(() => {
  // 从本地存储恢复登录态；无 token 时注入演示身份，保证未登录也能浏览
  restoreSession()
})
</script>

<style>
/* 全局样式：编译进 app.wxss，对所有页面生效。
   主题变量与工具类见 styles/theme.css */
@import './styles/theme.css';
</style>
