// Token 本地存储（《开发流程》7.2：localStorage 持久化）
// request.js 与 Pinia store 共用，避免循环依赖。

const ACCESS_TOKEN_KEY = 'sp_access_token'
const REFRESH_TOKEN_KEY = 'sp_refresh_token'

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
  clear() {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    // 顺带清掉历史遗留的演示标记：老用户浏览器里可能还留着 sp_is_demo，
    // 虽然现在已经没人读它了，但留着会让「本地存储里为什么有这个键」变成谜。
    localStorage.removeItem('sp_is_demo')
  },
}
