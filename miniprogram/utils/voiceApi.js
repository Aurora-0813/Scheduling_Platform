// ============================================================
// 语音模块 接口封装（供小程序录音页面调用）
// ============================================================

// 后端地址。
//
// ⚠️ **2026-10-14 改：不再在这个文件里写死。**
//
// 这里原先自己定义了一份 `export const BASE_URL`（与 `config/index.js` 的那份重复），
// 于是「登录页改了后端地址」对它无效 —— 语音仍然打旧地址，
// 而现象只是「语音用不了」，看不出是地址问题。
//
// 现在统一从 `api/endpoint.js` 取（每次现取，见 `getBaseUrl()` 的说明）。
import { getBaseUrl } from '@/api/endpoint.js'

/**
 * 上传录音文件 -> 后端语音识别
 * @param {string} filePath recorder.onStop 拿到的临时文件路径
 * @returns {Promise<{text: string}>}
 */
export function uploadVoice(filePath) {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: getBaseUrl() + '/api/v1/voice/asr',
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
      url: getBaseUrl() + '/api/v1/voice/format',
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
