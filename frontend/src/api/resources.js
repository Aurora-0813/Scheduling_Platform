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
export function getSpaceBookings(spaceId, days = 30) {
  return bizHttp.get(`/resources/spaces/${spaceId}/booked`, { params: { days } })
}
