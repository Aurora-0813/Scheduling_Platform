/**
 * 模块 9：用户认证与权限
 *
 * 认证接口**恒定走真实路径**（mock: false）——后端没有 /api/v1/mock/auth/*，
 * 登录与刷新必须打 /api/v1/auth/*。
 *
 * 安全约定（§9.1）：身份一律从 JWT 解析，前端不传也不解析 userId。
 *
 * ⚠️ **2026-09-30 删除了「本地演示身份」（DEMO_TOKEN / DEMO_USER）。**
 *
 * 原行为：`FALLBACK_TO_LOCAL=true` 且后端**完全连不上**时（密码错误不触发），
 * 直接写入一个假 token `'local-demo-token'` 当成登录成功。
 *
 * 删除理由 —— **它连兜底都做不到，只是个死路**：
 *   `'local-demo-token'` 不是 JWT，后端 `decode_token` 直接判 40102，
 *   于是用户「登录成功」之后，进任何一个页面发出第一个请求就会被
 *   `request.js` 的 AUTH_FAIL_CODES 分支 `clearTokens() + redirectToLogin()`
 *   弹回登录页。既没有兜住，又制造了一次假成功。
 *   （另外 `login/index.vue` 的「登录成功」toast 还会把它那句
 *     「后端未启动，已进入本地演示模式」覆盖掉，用户连提示都看不到。）
 *
 * 现在登录只有一个结果：拿到真实 JWT，或者如实报错。
 * 一并说明：`FALLBACK_TO_LOCAL` 也已置为 false（见 config/index.js）。
 */
import { request } from '@/api/request.js'
import { setTokens, clearTokens } from '@/utils/auth.js'

/**
 * 角色展示名。
 *
 * 后端 /auth/login 与 /auth/info 返回的 role 是 **中文角色名**
 * （docs/seed.sql 里 users.role 存的就是「系统管理员 / 管理员 / 普通用户」），
 * 不是 admin/user 这类代码。早期这里只写了代码→中文的映射，任何角色都命中
 * 不到 key，于是统一落到兜底值——admin 登录后首页也显示「普通用户」。
 *
 * 现在两种写法都认；实在认不出的原样展示，不冒充「普通用户」。
 */
const ROLE_TEXT = {
  // 代码写法（兼容旧数据 / 前端其它地方传值）
  admin: '系统管理员',
  resource_admin: '资源管理员',
  user: '普通用户',
  // 后端真实返回值：中文角色名，原样透传
  系统管理员: '系统管理员',
  管理员: '管理员',
  资源管理员: '资源管理员',
  普通用户: '普通用户',
}

export function roleText(role) {
  const key = String(role == null ? '' : role).trim()
  if (!key) return '普通用户'
  return ROLE_TEXT[key] || key
}

/**
 * 登录
 * @returns {Promise<{accessToken, refreshToken, role}>}
 */
export async function login({ username, password }) {
  const data = await request({
    path: '/auth/login',
    method: 'POST',
    data: { username, password },
    auth: false, // 登录接口不需要 Authorization
    mock: false, // 认证没有 mock 路由
  })
  setTokens(data)
  return data
}

/** 当前登录用户信息 */
export async function getInfo() {
  return request({ path: '/auth/info', method: 'GET', mock: false })
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

export default { login, getInfo, logout, roleText }
