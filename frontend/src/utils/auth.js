// Token 本地存储（《开发流程》7.2：localStorage 持久化）
// request.js 与 Pinia store 共用，避免循环依赖。

const ACCESS_TOKEN_KEY = 'sp_access_token'
const REFRESH_TOKEN_KEY = 'sp_refresh_token'
const IS_DEMO_KEY = 'sp_is_demo'

export const tokenStorage = {
  getAccessToken() {
    return localStorage.getItem(ACCESS_TOKEN_KEY) || ''
  },
  getRefreshToken() {
    return localStorage.getItem(REFRESH_TOKEN_KEY) || ''
  },
  setTokens(accessToken, refreshToken) {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken)
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken)
  },
  isDemo() {
    return localStorage.getItem(IS_DEMO_KEY) === '1'
  },
  setDemo(flag) {
    if (flag) {
      localStorage.setItem(IS_DEMO_KEY, '1')
    } else {
      localStorage.removeItem(IS_DEMO_KEY)
    }
  },
  clear() {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(IS_DEMO_KEY)
  },
}
