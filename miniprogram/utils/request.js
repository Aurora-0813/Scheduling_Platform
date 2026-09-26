// HTTP 封装：baseURL、统一注入身份头、统一响应体 {code, message, data} 解包
// 本地联调指向本机后端；上线改 https 域名（开发流程 §12.2）
export const BASE_URL = 'http://127.0.0.1:8000'

// 演示阶段固定 mock 用户 id；真实登录后从登录态读取（§5.1）
export const USER_ID = 1

export function request(options) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + options.url,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        'X-User-Id': USER_ID, // 演示 mock 用户；真实登录后从登录态读取
        ...(options.header || {}),
      },
      success: (res) => {
        const body = res.data || {}
        if (res.statusCode >= 200 && res.statusCode < 300 && body.code === 200) {
          resolve(body.data)
        } else {
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
