/**
 * 模块 2：摄像头空间感知
 *
 * 契约：两者都是 multipart/form-data，字段名固定 `file`。
 * 限制：图片 ≤5MB，仅 jpeg / png / webp / bmp（后端还会校验文件头魔数）。
 *
 * 返回里带 confidence，低于阈值时后端会给 needConfirm=true + question，
 * 页面需据此追问用户（见 §4.4 模块 2），不要直接当成已确认结果用。
 *
 * 注意 imageUrl 是相对路径（/uploads/xxx.jpg），展示前要用
 * request.js 的 absoluteUrl() 补全域名。
 */
import { upload } from '@/api/request.js'

/**
 * 拍照识别空间/门牌
 * @param {string} filePath
 * @returns {Promise<object>} { type, spaceId, spaceName, confidence,
 *                              availableTime[], devices[], needConfirm,
 *                              question, candidates[], imageUrl }
 */
export function analyze(filePath) {
  return upload({ path: '/image/analyze', filePath, name: 'file', silent: true })
}

/**
 * 手绘草图识别
 * @param {string} filePath
 * @returns {Promise<object>} { type, capacity, layout, requirements[], confidence,
 *                              needConfirm, question, imageUrl }
 */
export function sketch(filePath) {
  return upload({ path: '/image/sketch', filePath, name: 'file', silent: true })
}

export default { analyze, sketch }
