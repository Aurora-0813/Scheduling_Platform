/**
 * 用户登录态 store
 *
 * 为什么不用 Pinia：开发流程.md §3.2 的 Pinia 属于 Web 前端（Vue3）那一栏，
 * 小程序端只规定「Uni-app 随 HBuilderX 4.24 固定」。HBuilderX 工程模式下
 * 没有 node_modules，引入 Pinia 需要先 npm install，会破坏「打开即运行」。
 * 因此用 Vue 的 reactive 手写同形态的轻量 store（state + actions），
 * 日后若统一换 Pinia，只需替换本文件实现。
 */
import { reactive } from 'vue'
import { hasToken, clearTokens } from '@/utils/auth.js'
import * as authApi from '@/api/auth.js'

export const userStore = reactive({
  /** @type {null|{id:number, username:string, role:string, avatar:string, permissions:string[]}} */
  info: null,
  role: 'user',
  loggedIn: false,
  loading: false,
})

/** 角色展示名 */
export function roleText() {
  return authApi.roleText(userStore.role)
}

/** 展示名：优先昵称，退回用户名，再退回占位 */
export function displayName() {
  if (!userStore.info) return '访客'
  return userStore.info.username || '用户'
}

/** App 启动时调用：有 token 就拉一次用户信息 */
export function restoreSession() {
  userStore.loggedIn = hasToken()
  if (userStore.loggedIn) {
    fetchInfo()
  }
}

/** 拉取当前用户信息。失败不打断启动流程 */
export async function fetchInfo() {
  userStore.loading = true
  try {
    const info = await authApi.getInfo()
    userStore.info = info
    userStore.role = info.role || 'user'
    userStore.loggedIn = true
  } catch (e) {
    // token 失效的情况 request.js 已经清过登录态了，这里只同步本地状态
    if (e.kind === 'AUTH') {
      userStore.loggedIn = false
      userStore.info = null
    }
  } finally {
    userStore.loading = false
  }
}

/** 登录并写入 store */
export async function doLogin({ username, password }) {
  const data = await authApi.login({ username, password })
  userStore.role = data.role || 'user'
  userStore.loggedIn = true
  await fetchInfo()
  return data
}

/** 退出登录 */
export async function doLogout() {
  await authApi.logout()
  clearTokens()
  userStore.loggedIn = false
  userStore.info = null
  userStore.role = 'user'
}

/**
 * 需要身份的操作前调用。
 * 未登录时引导去登录页并返回 false。
 */
export function requireLogin() {
  if (userStore.loggedIn) return true
  uni.navigateTo({ url: '/pages/login/index' })
  return false
}

export default { userStore, restoreSession, fetchInfo, doLogin, doLogout, requireLogin, roleText, displayName }
