import request, { BASE_URL, USER_ID } from '@/utils/request'

// 核心调度 Agent（§5.3 模块4）：提交需求文本 → 主/备方案 + 思考过程
export const agentSchedule = (text) =>
  request({ url: '/api/v1/agent/schedule', method: 'POST', data: { text } })

function upload(url, filePath) {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + url,
      filePath,
      name: 'file',
      header: { 'X-User-Id': USER_ID },
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
