import { bizHttp } from '@/utils/request'

// 模块 3：预约（管理端查看与状态流转）
//
// 出参形状（app/api/orders.py::_order_out）：
//   orderId / userId / spaceId / deviceIds[] / startTime / endTime /
//   orderStatus / agentRequest / agentTrace[] / createTime / updateTime
// 注意 orderStatus 是**数字**，取值以 app/state_machine.py::OrderStatus 为准：
//   1 待确认 PENDING · 2 已确认 CONFIRMED · 3 已取消 CANCELLED · 4 已完成 COMPLETED
// （3/4 容易记反 —— 已取消是 3，已完成是 4。utils/normalize.js 的字典与此一致。）

// GET /orders/my 我的预约列表（**裸数组**，不是 {list:[…]}）
//
// 后端只接受 status 一个查询参数（app/api/orders.py:181），**没有分页**：
// 传 page/pageSize 会被静默忽略。列表页要在前端做切片。
export function getMyOrders(status) {
  const params = status === undefined || status === null ? {} : { status }
  return bizHttp.get('/orders/my', { params })
}

// GET /orders/{orderId} 预约详情
//
// 仅限本人的单：他人单与不存在的单**都返回 404**（后端刻意不区分，
// 防止拿 orderId 枚举别人的单）。所以 404 的提示语不能写成「不存在」，
// 要写成「预约不存在或无权查看」。
export function getOrder(orderId) {
  return bizHttp.get(`/orders/${orderId}`)
}

// POST /orders/create 创建预约
export function createOrder(data) {
  return bizHttp.post('/orders/create', data)
}

// PUT /orders/{orderId}/confirm 确认预约（状态机 1→2）
//
// 这是**唯一**能把预约从「待确认」推到「已确认」的入口 —— Agent 建的单
// 也是 status=1，必须由用户显式点确认才会真正落地（§5.3 模块 3）。
// 状态不允许时后端返回 409 / 40902「当前状态不允许确认」。
export function confirmOrder(orderId) {
  return bizHttp.put(`/orders/${orderId}/confirm`)
}

// PUT /orders/{orderId}/cancel 取消预约
export function cancelOrder(orderId) {
  return bizHttp.put(`/orders/${orderId}/cancel`)
}
