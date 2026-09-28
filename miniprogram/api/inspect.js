/**
 * 模块 6：AI 智能巡检
 *
 * 契约：
 *   POST /inspect/submit        FormData (file, spaceId) → { deviceStatus, report, repairSuggestion, ticketId }
 *   GET  /tickets/list
 *   PUT  /tickets/{id}/status
 *
 * ⚠️ inspectorId / handlerId 一律由后端从 JWT 解析，**禁止**从请求体或
 *    FormData 传入（§5.1 防身份伪造）。
 *
 * 注意：本模块在真实后端**尚未实现**，目前只能命中 /api/v1/mock/inspect/*
 * 与 /api/v1/mock/tickets/*。
 */
import { request, upload } from '@/api/request.js'
import { listOf, totalOf } from '@/utils/normalize.js'

/**
 * 提交巡检照片，AI 识别设备状态并自动生成维修工单
 * @param {string} filePath 图片临时路径
 * @param {number} [spaceId] 关联空间 ID
 * @returns {Promise<{deviceStatus, report, repairSuggestion, ticketId}>}
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

export default { submit, tickets, updateTicketStatus }
