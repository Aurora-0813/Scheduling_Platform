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

export function hasToken() {
  return !!getAccessToken()
}
