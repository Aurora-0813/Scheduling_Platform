import { bizHttp } from '@/utils/request'

// 模块 5：资源与设备管理
// GET /resources/spaces 场地分页
export function getSpaces(params = {}) {
  return bizHttp.get('/resources/spaces', { params })
}

// POST /resources/spaces 新增场地
export function createSpace(data) {
  return bizHttp.post('/resources/spaces', data)
}

// GET /resources/devices 设备分页
export function getDevices(params = {}) {
  return bizHttp.get('/resources/devices', { params })
}

// PUT /resources/devices/{deviceId} 修改设备
export function updateDevice(deviceId, data) {
  return bizHttp.put(`/resources/devices/${deviceId}`, data)
}

/**
 * GET /resources/spaces/{spaceId}/booked 某场地未来 N 天内已被占用的时段。
 *
 * 契约：→ `{ spaceId, spaceName, spaceType, location, capacity,
 *           openStartTime, openEndTime, days, count, bookings[] }`
 * `bookings[]` 每项：`{ orderId, userId, startTime, endTime, orderStatus, deviceIds }`
 *
 * 占用口径与下单判重**同源**（状态 1 待确认 / 2 已确认），所以这里列出的时段
 * 与「真正下单时会不会被判冲突」不会互相矛盾。
 *
 * ⚠️ 需要登录：占用数据会暴露他人的预约时段。
 * ⚠️ 默认 30 天而不是 7 天：场地的「已被预约」标记只算**本周内**，
 *    但用户点开详情是想看「接下来还有哪些时段被占了」，只看 7 天会显得内容太少。
 */
// GET /resources/spaces/available 某时段**真正订得上**的场地（2026-10-13 新增）
//
// 参数：capacity / spaceType / startTime / endTime（spaceType 不传 = 不限类型）
//   → { count, spaces: [{spaceId, spaceName, spaceType, capacity, location, budget, ...}] }
//
// 口径与建单判重**严格同源**（后端直接复用 Agent 的 query_spaces），
// 所以这里列出来的场地，点建单不会因为「时段冲突」被拒 —— 这就是「冲突预检」。
export function getAvailableSpaces(params = {}) {
  return bizHttp.get('/resources/spaces/available', { params })
}

// GET /resources/devices/available 某时段**每台设备还剩几台**（2026-10-13 新增）
//
// 参数：startTime / endTime（必填）、deviceType（可选）
//   → { count, devices: [{deviceId, deviceName, deviceType, availableCount, usedCount, remainingCount}] }
//
// 只返回 device_status == 1（完好）的设备；remainingCount <= 0 表示该时段已借满。
export function getAvailableDevices(params = {}) {
  return bizHttp.get('/resources/devices/available', { params })
}

export function getSpaceBookings(spaceId, days = 30) {
  return bizHttp.get(`/resources/spaces/${spaceId}/booked`, { params: { days } })
}
