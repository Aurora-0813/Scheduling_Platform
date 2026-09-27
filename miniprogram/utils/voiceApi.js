// ============================================================
// 语音模块 接口封装（供小程序录音页面调用）
// ============================================================

// 后端地址，按调试场景三选一：
// 1) 微信开发者工具里调试：http://127.0.0.1:8000
//    并在「详情 -> 本地设置」勾选「不校验合法域名、web-view…」
// 2) 真机预览调试：电脑的局域网 IP，例如 http://192.168.1.10:8000
//    手机和电脑连同一个 WiFi（IP 用 ipconfig 查 IPv4 地址）
// 3) 正式上线：必须是 https 域名，并在小程序后台配置 request/uploadFile 合法域名
export const BASE_URL = 'http://127.0.0.1:8000'

/**
 * 上传录音文件 -> 后端语音识别
 * @param {string} filePath recorder.onStop 拿到的临时文件路径
 * @returns {Promise<{text: string}>}
 */
export function uploadVoice(filePath) {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + '/api/v1/voice/asr',
      filePath,
      name: 'file', // 后端用 file 字段接收，不能改
      success: (res) => {
        try {
          const data = JSON.parse(res.data)
          if (data.code === 200) {
            resolve(data.data)
          } else {
            reject(new Error(data.message || '识别失败'))
          }
        } catch (e) {
          reject(new Error('返回数据解析失败'))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络请求失败'))
      },
    })
  })
}

/**
 * 口语文本格式化 + 关键词提取
 * @param {string} rawText ASR 识别出的原始文字
 * @returns {Promise<{formattedText: string, keywords: string[]}>}
 */
export function formatVoiceText(rawText) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + '/api/v1/voice/format',
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { rawText },
      success: (res) => {
        const data = res.data
        if (data.code === 200) {
          resolve(data.data)
        } else {
          reject(new Error(data.message || '格式化失败'))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络请求失败'))
      },
    })
  })
}
