// HTTP 封装：baseURL、统一注入认证头、统一响应体 {code, message, data} 解包
// 本地联调指向本机后端；上线改 https 域名（开发流程 §12.2）
import { clearToken, ensureToken } from './auth'

export const BASE_URL = 'http://127.0.0.1:8000'

export async function request(options) {
  let token
  try {
    token = await ensureToken()
  } catch (e) {
    uni.showToast({ title: '登录失败，请检查后端与演示账号', icon: 'none' })
    return Promise.reject(e)
  }

  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + options.url,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        // 身份一律从 JWT 解析（§5.1 / docs/api.md §1.6）。
        // 这里曾经发的是 `X-User-Id: 1` —— 那个头不在契约里，且谁都改得了。
        Authorization: `Bearer ${token}`,
        ...(options.header || {}),
      },
      success: (res) => {
        const body = res.data || {}
        if (res.statusCode >= 200 && res.statusCode < 300 && body.code === 200) {
          resolve(body.data)
        } else {
          // 401：令牌过期或无效 —— 丢掉本地令牌，下次请求会自动重新登录。
          // 不在这里直接续期：三个 401 分支（40101 缺令牌 / 40102 无效 /
          // 40103 过期）里只有 40103 值得续期，交给专门做这件事的人去分。
          if (res.statusCode === 401) clearToken()
          const msg = body.message || `请求失败(${res.statusCode})`
          uni.showToast({ title: msg, icon: 'none' })
          reject(body)
        }
      },
      fail: (err) => {
        uni.showToast({ title: '网络异常，请检查后端是否启动', icon: 'none' })
        reject(err)
      },
    })
  })
}

export default request
