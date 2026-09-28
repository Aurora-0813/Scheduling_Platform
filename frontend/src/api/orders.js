import { bizHttp } from '@/utils/request'

// 模块 3：预约（管理端查看用）
// GET /orders/my 我的预约分页
export function getMyOrders(params = {}) {
  return bizHttp.get('/orders/my', { params })
}

// POST /orders/create 创建预约
export function createOrder(data) {
  return bizHttp.post('/orders/create', data)
}

// PUT /orders/{orderId}/cancel 取消预约
export function cancelOrder(orderId) {
  return bizHttp.put(`/orders/${orderId}/cancel`)
}
