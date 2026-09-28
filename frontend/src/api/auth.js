import { realHttp, USE_MOCK } from '@/utils/request'
import { tokenStorage } from '@/utils/auth'

// 演示用户：后端/数据库未连通且 USE_MOCK=true 时的兜底会话
const DEMO_USER = {
  id: 1,
  username: 'admin',
  role: '超级管理员',
  avatar: null,
  permissions: ['*'],
}

function makeDemoToken() {
  // 注意：btoa 只能编码 Latin1，不能放中文
  const payload = btoa(JSON.stringify({ sub: 'demo', role: 'admin', exp: 0 }))
  return `demo.${payload}.sig`
}

// 登录：真实接口 POST /auth/login；mock 模式下后端不可达则进入演示会话
export function login(username, password) {
  return realHttp
    .post('/auth/login', { username, password })
    .then((data) => {
      tokenStorage.setDemo(false)
      return data
    })
    .catch((error) => {
      if (USE_MOCK) {
        const token = makeDemoToken()
        tokenStorage.setTokens(token, token)
        tokenStorage.setDemo(true)
        return { accessToken: token, refreshToken: token, role: DEMO_USER.role }
      }
      throw error
    })
}

// 当前用户信息：GET /auth/info
export function getInfo() {
  return realHttp.get('/auth/info').catch((error) => {
    if (USE_MOCK) {
      return DEMO_USER
    }
    throw error
  })
}

// 登出：POST /auth/logout
export function logout() {
  if (tokenStorage.isDemo()) {
    return Promise.resolve()
  }
  return realHttp
    .post('/auth/logout', { refreshToken: tokenStorage.getRefreshToken() })
    .catch(() => {})
}
