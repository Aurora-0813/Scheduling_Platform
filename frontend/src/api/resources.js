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
