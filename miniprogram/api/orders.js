/**
 * 模块 3：移动端预约与通知
 *
 * 契约：
 *   POST /orders/create            { spaceId, deviceIds[], startTime, endTime, agentRequest, agentTrace }
 *   GET  /orders/my
 *   PUT  /orders/{orderId}/confirm   状态机 1待确认 -> 2已确认
 *   PUT  /orders/{orderId}/cancel    状态机 -> 3已取消
 *
 * ⚠️ userId 一律由后端从 JWT 解析，**禁止**在请求体里传（§5.1 防身份伪造）。
 * ⚠️ startTime / endTime 必须是 `YYYY-MM-DD HH:mm:ss` 本地时间，
 *    用 utils/format.js 的 formatDateTime()，不要用 toISOString()。
 *
 * 注：本模块对应后端 `app/api/orders.py`，**已实现**（2026-09-29 复核）。
 * 原先此处写「真实后端尚未实现」是合并期的旧说法，已删除。
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
 * 预约详情：GET /orders/{orderId}
 *
 * ⚠️ **2026-09-30 补。** 原先没有这个封装，@@pages/order/detail.vue@@ 的注释里
 * 还写着「契约里没有 GET /orders/{orderId}」—— **那句话是错的**，后端一直有
 * （backend/app/api/orders.py 的 @@@router.get("/{orderId}")@@），
 * 于是详情页只能拉全量列表再按 id 过滤（@@pageSize: 100@@，而后端**根本不支持分页**，
 * 那个参数是被静默忽略的），订单一多就是一次全表响应。
 *
 * 归属校验在后端：他人单与不存在的单**都返回 404**（刻意不区分，防枚举）。
 */
export function getOrder(orderId) {
  return request({ path: '/orders/' + orderId, method: 'GET' })
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

/**
 * 确认预约（状态机 1待确认 -> 2已确认）。
 *
 * ⚠️ **Agent 方案卡必须走这条，不能走 createOrder。**
 * `/agent/schedule` 在后端内部**已经把资源锁掉并落了单**（trace 里那句
 * 「锁定资源：成功（订单 N）」就是它），返回体的 `orderId` 就是那张单，
 * `needConfirm=true` 表示「等你确认」。
 * 所以确认动作是 1→2 的流转，**不是**再建一张 ——
 * 再建一张必然撞 409「该时段已被占用」（占的正是自己刚锁的时段）。
 * 依据：docs/api.md 的 `orderId` 说明（它是确认流程的入口）+
 *       store/agent.js 顶部「后端内部会锁资源」。
 */
export function confirmOrder(orderId) {
  return request({ path: `/orders/${orderId}/confirm`, method: 'PUT' })
}

/** 取消预约（只有待确认 / 已确认可取消，判断见 utils/dict.js 的 canCancelOrder） */
export function cancelOrder(orderId) {
  return request({ path: `/orders/${orderId}/cancel`, method: 'PUT' })
}

/** 把 Date 或后端时间串统一成提交用的格式，供页面直接调用 */
export const toApiTime = formatDateTime

export default { myOrders, getOrder, createOrder, confirmOrder, cancelOrder, toApiTime }
