import request from '@/utils/request'

// 资源（§5.3 模块5）
export const getSpaces = () => request({ url: '/api/v1/resources/spaces' })
export const getDevices = () => request({ url: '/api/v1/resources/devices' })
export const getResources = async () => {
  const [spaces, devices] = await Promise.all([getSpaces(), getDevices()])
  return { spaces, devices }
}

// 预约订单（§5.3 模块3：GET /orders/my，身份由 utils/request.js 统一注入 JWT，不走 /user/{id}）
export const getOrders = (status) =>
  request({ url: '/api/v1/orders/my', data: status ? { status } : {} })
export const getOrder = (id) => request({ url: `/api/v1/orders/${id}` })
export const createOrder = (data) =>
  request({ url: '/api/v1/orders/create', method: 'POST', data })
export const confirmOrder = (id) =>
  request({ url: `/api/v1/orders/${id}/confirm`, method: 'PUT' })
export const cancelOrder = (id) =>
  request({ url: `/api/v1/orders/${id}/cancel`, method: 'PUT' })
