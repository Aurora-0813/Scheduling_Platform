/**
 * 模块 9：用户认证与权限
 *
 * 认证接口**恒定走真实路径**（mock: false）——后端没有 /api/v1/mock/auth/*，
 * 登录与刷新必须打 /api/v1/auth/*。
 *
 * 安全约定（§9.1）：身份一律从 JWT 解析，前端不传也不解析 userId。
 */
import { request } from '@/api/request.js'
import { setTokens, clearTokens, getAccessToken } from '@/utils/auth.js'
import { FALLBACK_TO_LOCAL } from '@/config/index.js'
import { toast } from '@/utils/toast.js'

/** 本地演示身份：仅在后端完全连不上时使用，见 login() */
export const DEMO_TOKEN = 'local-demo-token'

const DEMO_USER = {
  id: 0,
  username: 'demo',
  role: 'user',
  avatar: '',
  permissions: [],
}

const ROLE_TEXT = {
  admin: '系统管理员',
  resource_admin: '资源管理员',
  user: '普通用户',
}

export function roleText(role) {
  return ROLE_TEXT[role] || '普通用户'
}

/**
 * 登录
 * @returns {Promise<{accessToken, refreshToken, role}>}
 */
export async function login({ username, password }) {
  try {
    const data = await request({
      path: '/auth/login',
      method: 'POST',
      data: { username, password },
      auth: false, // 登录接口不需要 Authorization
      mock: false, // 认证没有 mock 路由
    })
    setTokens(data)
    return data
  } catch (e) {
    // 只有「后端连不上」才降级；密码错误是业务错误（kind === 'BIZ'），必须如实报错
    if (FALLBACK_TO_LOCAL && e.kind === 'NETWORK') {
      setTokens({ accessToken: DEMO_TOKEN, refreshToken: DEMO_TOKEN })
      toast('后端未启动，已进入本地演示模式')
      return { accessToken: DEMO_TOKEN, refreshToken: DEMO_TOKEN, role: 'user' }
    }
    throw e
  }
}

/** 当前登录用户信息 */
export async function getInfo() {
  if (getAccessToken() === DEMO_TOKEN) return { ...DEMO_USER }
  try {
    return await request({ path: '/auth/info', method: 'GET', mock: false })
  } catch (e) {
    if (FALLBACK_TO_LOCAL && e.kind === 'NETWORK') return { ...DEMO_USER }
    throw e
  }
}

/** 退出登录：先通知后端作废 refreshToken，再清本地 */
export async function logout() {
  try {
    await request({ path: '/auth/logout', method: 'POST', data: {}, mock: false, silent: true })
  } catch (e) {
    // 后端不可用也要让用户能退出，本地清理照常执行
  }
  clearTokens()
}

export default { login, getInfo, logout, roleText, DEMO_TOKEN }
