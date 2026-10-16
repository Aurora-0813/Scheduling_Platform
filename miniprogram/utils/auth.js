/**
 * 令牌读写
 *
 * 安全约定（开发流程.md §5.1 / §9.1）：
 *   身份标识一律从 JWT 解析，禁止从请求体或 FormData 传入 userId。
 *   前端只负责持有并携带 token，不解析也不信任其内容做权限判断。
 */
import { STORAGE_KEYS } from '@/config/index.js'

export function getAccessToken() {
  return uni.getStorageSync(STORAGE_KEYS.ACCESS) || ''
}

export function getRefreshToken() {
  return uni.getStorageSync(STORAGE_KEYS.REFRESH) || ''
}

/** 后端 /auth/login 与 /auth/refresh 都返回 {accessToken, refreshToken} */
export function setTokens({ accessToken, refreshToken } = {}) {
  if (accessToken) uni.setStorageSync(STORAGE_KEYS.ACCESS, accessToken)
  // refresh 是轮换制的：后端换发新 token 后旧的立即失效，
  // 因此新值必须覆盖旧值，缺省时保留原值
  if (refreshToken) uni.setStorageSync(STORAGE_KEYS.REFRESH, refreshToken)
}

export function clearTokens() {
  uni.removeStorageSync(STORAGE_KEYS.ACCESS)
  uni.removeStorageSync(STORAGE_KEYS.REFRESH)
}

/**
 * `clearTokens` 的别名。
 *
 * utils/ws.js 一直按 `clearToken`（单数）导入，而本文件只有 `clearTokens` ——
 * ES 模块里导入一个不存在的具名导出会直接报错，所以补上这个名字。
 * 保留单数写法而不是去改 ws.js，是因为两个名字都在用的可能性更高，
 * 留一个薄别名比让 ws.js 与其它调用方各写一套更安全。
 */
export function clearToken() {
  clearTokens()
}

export function hasToken() {
  return !!getAccessToken()
}


/**
 * 给 WebSocket 用的 token（见 utils/ws.js）。
 *
 * ⚠️ 2026-10-14 重写。原先这个函数是这样写的：
 *
 *     const token = uni.getStorageSync('token')          // ← 键名不对
 *     const { request } = await import('@/utils/request.js')  // ← 文件根本不存在
 *     uni.setStorageSync('token', res.token)             // ← 字段名不对
 *
 * 三个问题叠在一起：
 *   1. `@/utils/request.js` 不存在（网络层在 api/request.js），
 *      编译期就报 Cannot find module，**整个小程序构建失败**；
 *   2. 它读写的键是裸字符串 'token'，而全项目用的是 STORAGE_KEYS.ACCESS，
 *      于是永远读不到；
 *   3. 后端 /auth/refresh 返回的是 { accessToken, refreshToken }，
 *      没有 `token` 字段，就算前两步对了拿到的也是 undefined。
 *
 * 而且它**本来就多余**：续期是网络层 api/request.js 的职责，那里已经实现了
 * 「无 token → 抛 NO_TOKEN」「40103 过期 → refreshAccessToken() 后原样重放」
 * 「续期失败 → clearTokens() + 跳登录」。WebSocket 只需要拿到当前 access token。
 *
 * 现在只做一件事：把当前 access token 交给调用方；没有就抛，
 * 由 ws.js 捕获后安排重连（它自己已经有 scheduleReconnect）。
 * 这里**刻意不跳登录页**：连不上 WebSocket 只是收不到通知，
 * 不该因此把用户从正在看的页面上赶走 —— 真需要重新登录时，
 * 下一次 HTTP 请求会由网络层按上面的流程统一处理。
 */
export async function ensureToken() {
  const token = getAccessToken()
  if (!token) throw new Error('NO_TOKEN')
  return token
}
