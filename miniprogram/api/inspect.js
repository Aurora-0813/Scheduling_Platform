/**
 * 模块 6：AI 智能巡检
 *
 * 契约：
 *   POST /inspect/submit        FormData (file, spaceId) → { deviceStatus, report, repairSuggestion, ticketId, deviceWarning }
 *   GET  /tickets/list
 *   PUT  /tickets/{id}/status   人工流转状态（1 待处理 / 2 处理中 / 3 已完成）
 *   POST /tickets/{id}/handle   提交维修后照片 + AI 核验（2026-10-06 新增）
 *
 * ⚠️ inspectorId / handlerId 一律由后端从 JWT 解析，**禁止**从请求体或
 *    FormData 传入（§5.1 防身份伪造）。
 *
 * ⚠️ **2026-10-06 更正：本模块的真实后端早就实现了**，不是只能命中 mock。
 *    原先这里的注释写「尚未实现，只能命中 /api/v1/mock/inspect/*」是合并期的
 *    旧说法，与 `api/resources.js` 里已更正过的那段是同一类过期说明。
 */
import { request, upload } from '@/api/request.js'
import { listOf, totalOf } from '@/utils/normalize.js'

/**
 * 提交巡检照片，AI 识别设备状态并自动生成维修工单
 * @param {string} filePath 图片临时路径
 * @param {number} [spaceId] 关联空间 ID
 * @returns {Promise<{deviceStatus, report, repairSuggestion, ticketId, deviceWarning}>}
 */
export function submit(filePath, spaceId) {
  const formData = {}
  if (spaceId !== undefined && spaceId !== null && spaceId !== '') {
    // FormData 里的值会被转成字符串，后端用 int 接收，这里显式转一下
    formData.spaceId = String(spaceId)
  }
  return upload({ path: '/inspect/submit', filePath, name: 'file', formData, silent: true })
}

/** 维修工单列表 */
export async function tickets(params) {
  const data = await request({ path: '/tickets/list', method: 'GET', data: params })
  return { list: listOf(data), total: totalOf(data) }
}

/** 更新工单状态：1 待处理 / 2 处理中 / 3 已完成 */
export function updateTicketStatus(ticketId, status) {
  return request({ path: `/tickets/${ticketId}/status`, method: 'PUT', data: { status } })
}

/**
 * 提交维修后的照片，由 AI 核验是否真的修好（2026-10-06 新增）。
 *
 * 契约：POST /tickets/{ticketId}/handle  FormData(file)
 *   → { id, status, statusText, passed, verifyStatus, verifyReport, handleImageUrl, ... }
 *
 * 与 `updateTicketStatus` 的**分工**（Web 端同口径）：
 *   · `handle`         机器判定：核验通过才把工单置为已完成
 *   · `updateTicket…`  人工决定：到场发现是误报，直接标完成
 *
 * ⚠️ **核验通过还有一个副作用：设备会被恢复为「完好」、可借数 +1。**
 *    只走 `updateTicketStatus(3)` 虽然也能关掉工单（后端在人工路径里同样会
 *    恢复设备），但**没有核验凭据**；而 `handle` 是带着照片的那条正式路径。
 *
 * 未通过时后端**不改工单状态**（`status` 保持原值），`verifyReport` 说明原因，
 * 调用方应据此提示「重拍再传」。
 *
 * @param {number} ticketId
 * @param {string} filePath 维修后照片的临时路径
 */
export function handleTicket(ticketId, filePath) {
  return upload({ path: `/tickets/${ticketId}/handle`, filePath, name: 'file' })
}

export default { submit, tickets, updateTicketStatus, handleTicket }
