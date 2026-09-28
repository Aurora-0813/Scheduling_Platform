/**
 * 模块 5：资源与设备管理
 *
 * 契约：
 *   GET  /resources/spaces
 *   GET  /resources/devices
 *   POST /resources/spaces
 *   PUT  /resources/devices/{id}
 *
 * 注意：本模块在真实后端**尚未实现**，目前只能命中 /api/v1/mock/resources/*。
 * 场地类型字段在文档里是整数 spaceType，当前 Mock 给的是字符串 type ——
 * 文案解析统一走 utils/dict.js 的 spaceTypeLabel()，两种都能处理。
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

/** 新增场地 */
export function createSpace(payload) {
  return request({ path: '/resources/spaces', method: 'POST', data: payload })
}

/** 更新设备 */
export function updateDevice(deviceId, payload) {
  return request({ path: `/resources/devices/${deviceId}`, method: 'PUT', data: payload })
}

export default { spaces, devices, createSpace, updateDevice }
