// 身份凭据：accessToken 的存取与登录（§5.1 / docs/api.md §1.6）
//
// 为什么客户端要自己登一次
// ------------------------
// 后端身份一律从 JWT 解析，请求头里的 `X-User-Id` 已随本轮改造删除 ——
// 那个头谁都能改，等于把「我是谁」交给客户端自报。小程序侧的真实登录页
// 由模块 1/2 负责，目前还没接进来（`docs/本次合并对齐方案.md` 第 9 项：
// JWT 切换时点待与徐川确认）。
//
// 为了让演示与联调先跑通，这里给**演示账号自动登录**：账号取自
// `backend/scripts/seed.py` 的种子数据（`user01` / `Smart@123456`），
// 只在本地/演示库有意义。
//
// 真实登录页接进来之后：删掉 `ensureToken()` 里的自动登录分支，改由登录页
// 调用 `login()`，其余调用方（request.js / ws.js）一行都不用动。

import { BASE_URL } from './request'

const TOKEN_KEY = 'accessToken'
const REFRESH_KEY = 'refreshToken'

//: 演示账号（§5.3 禁止在代码里留存真实管理员密码；这是种子数据的初始密码，
//: 可用环境变量覆盖，仅用于本地/演示库）。
export const DEMO_ACCOUNT = { username: 'user01', password: 'Smart@123456' }

export function getToken() {
  try {
    return uni.getStorageSync(TOKEN_KEY) || ''
  } catch (e) {
    return ''
  }
}

export function getRefreshToken() {
  try {
    return uni.getStorageSync(REFRESH_KEY) || ''
  } catch (e) {
    return ''
  }
}

export function setToken(accessToken, refreshToken) {
  try {
    uni.setStorageSync(TOKEN_KEY, accessToken || '')
    if (refreshToken) uni.setStorageSync(REFRESH_KEY, refreshToken)
  } catch (e) {}
}

export function clearToken() {
  try {
    uni.removeStorageSync(TOKEN_KEY)
    uni.removeStorageSync(REFRESH_KEY)
  } catch (e) {}
}

/**
 * 用户名密码登录，成功后令牌落盘。
 *
 * 刻意不复用 `utils/request.js`：那里会先调 `ensureToken()`，互相引用会成环。
 */
export function login(username, password) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}/api/v1/auth/login`,
      method: 'POST',
      data: { username, password },
      header: { 'Content-Type': 'application/json' },
      success: (res) => {
        const body = res.data || {}
        if (res.statusCode >= 200 && res.statusCode < 300 && body.code === 200) {
          setToken(body.data.accessToken, body.data.refreshToken)
          resolve(body.data)
        } else {
          reject(body)
        }
      },
      fail: reject,
    })
  })
}

/**
 * 取一个可用令牌；本地没有就自动登一次演示账号。
 *
 * 令牌有效期 30 分钟。过期后由 `request.js` 在收到 401 时 `clearToken()`，
 * 下一次请求走到这里会重新登一次 —— 演示时不会因为放了一会儿就全线报错。
 */
export async function ensureToken() {
  const cached = getToken()
  if (cached) return cached
  const data = await login(DEMO_ACCOUNT.username, DEMO_ACCOUNT.password)
  return data.accessToken
}
