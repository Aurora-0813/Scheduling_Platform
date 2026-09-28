/**
 * 模块 3：移动端预约与通知
 *
 * 契约：
 *   POST /orders/create            { spaceId, deviceIds[], startTime, endTime, agentRequest, agentTrace }
 *   GET  /orders/my
 *   PUT  /orders/{orderId}/cancel
 *
 * ⚠️ userId 一律由后端从 JWT 解析，**禁止**在请求体里传（§5.1 防身份伪造）。
 * ⚠️ startTime / endTime 必须是 `YYYY-MM-DD HH:mm:ss` 本地时间，
 *    用 utils/format.js 的 formatDateTime()，不要用 toISOString()。
 *
 * 注意：本模块在真实后端**尚未实现**，目前只能命中 /api/v1/mock/orders/*。
 */
import { request } from '@/api/request.js'
import { formatDateTime } from '@/utils/format.js'
import { listOf, totalOf } from '@/utils/normalize.js'

/**
 * 我的预约列表
 * @param {object} [params] { page, pageSize, status }
 * @returns {Promise<{list: object[], total: number}>}
 */
export async function myOrders(params) {
  const data = await request({ path: '/orders/my', method: 'GET', data: params })
  return { list: listOf(data), total: totalOf(data) }
}

/**
 * 创建预约（方案确认后落库）
 * @param {object} payload
 * @param {number} payload.spaceId
 * @param {number[]} [payload.deviceIds]
 * @param {string} payload.startTime 'YYYY-MM-DD HH:mm:ss'
 * @param {string} payload.endTime
 * @param {string} [payload.agentRequest] 用户原始需求
 * @param {Array}  [payload.agentTrace] Agent 思考链，落库 reserve_order.agent_trace
 */
export function createOrder(payload) {
  return request({
    path: '/orders/create',
    method: 'POST',
    data: {
      spaceId: payload.spaceId,
      deviceIds: payload.deviceIds || [],
      startTime: payload.startTime,
      endTime: payload.endTime,
      agentRequest: payload.agentRequest || '',
      agentTrace: payload.agentTrace || null,
    },
  })
}

/** 取消预约（只有待确认 / 已确认可取消，判断见 utils/dict.js 的 canCancelOrder） */
export function cancelOrder(orderId) {
  return request({ path: `/orders/${orderId}/cancel`, method: 'PUT' })
}

/** 把 Date 或后端时间串统一成提交用的格式，供页面直接调用 */
export const toApiTime = formatDateTime

export default { myOrders, createOrder, cancelOrder, toApiTime }
