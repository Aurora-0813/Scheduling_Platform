import request, { BASE_URL } from '@/utils/request'
import { ensureToken } from '@/utils/auth'

// 核心调度 Agent（§5.3 模块4）：提交需求文本 → 主/备方案 + 思考过程
export const agentSchedule = (text) =>
  request({ url: '/api/v1/agent/schedule', method: 'POST', data: { text } })

// 上传走 uni.uploadFile（multipart），不走 utils/request.js，所以认证头得自己加 ——
// 与那里同一口径：`Authorization: Bearer <accessToken>`（§5.1）。
// 注：`/agent/transcribe` 与 `/agent/recognize` 目前在服务端**没有**要求登录，
// 带上令牌不影响；若模块 4 后续给它们加上认证，这里不用改。
async function upload(url, filePath) {
  const token = await ensureToken()
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + url,
      filePath,
      name: 'file',
      header: { Authorization: `Bearer ${token}` },
      success: (res) => {
        try {
          const body = JSON.parse(res.data)
          if (body && body.code === 200) resolve(body.data)
          else {
            uni.showToast({ title: body.message || '上传失败', icon: 'none' })
            reject(body)
          }
        } catch (e) {
          reject(e)
        }
      },
      fail: reject,
    })
  })
}

export const agentTranscribe = (filePath) => upload('/api/v1/agent/transcribe', filePath)
export const agentRecognize = (filePath) => upload('/api/v1/agent/recognize', filePath)
