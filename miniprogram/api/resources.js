/**
 * 模块 5：资源与设备管理
 *
 * 契约：
 *   GET  /resources/spaces
 *   GET  /resources/devices
 *   POST /resources/spaces
 *   PUT  /resources/devices/{id}
 *
 * ⚠️ 2026-09-30 更正：原注释写「本模块在真实后端**尚未实现**，只能命中 mock」是**错的**。
 *   这四个接口在 backend/app/api/resources.py 里早已实现，并已用真库实测通过
 *   （/resources/spaces 返回 8 条，每条都带 spaceId/spaceName/capacity/location/budget）。
 *   场地类型是整数 spaceType，文案解析走 utils/dict.js 的 spaceTypeLabel()。
 */
import { request } from '@/api/request.js'
import { listOf, totalOf } from '@/utils/normalize.js'

/** 场地列表 */
export async function spaces(params) {
  const data = await request({ path: '/resources/spaces', method: 'GET', data: params })
  return { list: listOf(data), total: totalOf(data) }
}

/** 设备列表 */
export async function devices(params) {
  const data = await request({ path: '/resources/devices', method: 'GET', data: params })
  return { list: listOf(data), total: totalOf(data) }
}

/**
 * 某场地未来 N 天内**已被占用**的时段（2026-09-30 新增的后端只读接口）。
 *
 * 契约：GET /resources/spaces/{spaceId}/booked?days=N
 *   → { spaceId, spaceName, spaceType, location, capacity,
 *       openStartTime, openEndTime, days, count, bookings[] }
 *   bookings[] 每项：{ orderId, userId, startTime, endTime, orderStatus, deviceIds }
 *
 * 占用口径与下单判重同源（状态 1 待确认 / 2 已确认），
 * 所以这里显示的「已占用」与真正下单时的判重结果**不会互相矛盾**。
 *
 * ⚠️ 需要登录：占用数据会暴露他人的预约时段。
 */
export function spaceBookings(spaceId, days = 30) {
  return request({
    path: `/resources/spaces/${spaceId}/booked`,
    method: 'GET',
    data: { days },
  })
}

/** 新增场地 */
export function createSpace(payload) {
  return request({ path: '/resources/spaces', method: 'POST', data: payload })
}

/** 更新设备 */
export function updateDevice(deviceId, payload) {
  return request({ path: `/resources/devices/${deviceId}`, method: 'PUT', data: payload })
}

export default { spaces, devices, spaceBookings, createSpace, updateDevice }
