/**
 * 模块 1：语音输入
 *
 * 契约（与后端 app/api/v1/voice.py 已对齐，勿改）：
 *   POST /voice/asr    FormData 字段名固定 `file` → { text }
 *   POST /voice/format JSON { rawText } → { formattedText, keywords[] }
 *
 * 录音参数见 config/index.js 的 RECORD_OPTIONS：
 * wav / 16000 采样率 / 单声道 / 最长 60 秒，与百度 ASR 一致。
 */
import { request, upload } from '@/api/request.js'

/**
 * 上传录音做语音识别
 * @param {string} filePath 录音临时文件路径
 * @returns {Promise<{text: string}>}
 */
export function asr(filePath) {
  return upload({ path: '/voice/asr', filePath, name: 'file' })
}

/**
 * 口语文本规整为结构化约束 + 关键词提取
 * @param {string} rawText ASR 识别出的原始文字
 * @returns {Promise<{formattedText: string, keywords: string[]}>}
 */
export function format(rawText) {
  return request({ path: '/voice/format', method: 'POST', data: { rawText } })
}

export default { asr, format }
