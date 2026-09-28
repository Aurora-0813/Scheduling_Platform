/**
 * 契约漂移适配层
 *
 * 后端各模块由不同的人分批实现，同一含义的字段在文档、当前 Mock、
 * 以及未落地的模块里并不统一。这一层把差异收在一处，页面只读规范名。
 *
 * 已知差异：
 *   1. 主键：文档/未来真实接口用 `id`，订单的当前 Mock 用 `orderId`
 *   2. 订单状态：文档用 `orderStatus`，当前 Mock 用 `status`
 *   3. 场地名：文档用 `spaceName`，当前 Mock 用 `name`
 *   4. 分页：docs/api.md 与全部 Mock 数据用 `list`，
 *      但 app/utils/pagination.py 的 PageResult 字段名是 `items` —— 两者都读
 *
 * 另外，小程序端避免使用 `??` 与 `?.`（部分构建链不降级 ES2020 语法），
 * 统一用 first() 取值。
 */

/** 返回第一个「有值」的入参，跳过 undefined / null / 空串 */
export function first(...values) {
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return undefined
}

/** 订单主键 */
export function orderId(order) {
  if (!order) return undefined
  return first(order.orderId, order.id)
}

/** 订单状态值（当前 Mock 用 status） */
export function orderStatus(order) {
  if (!order) return undefined
  return first(order.orderStatus, order.status)
}

/** 订单状态文案（优先 statusText，理由见 utils/dict.js 顶部注释） */
export function orderStatusText(order) {
  if (!order) return ''
  return first(order.statusText, order.statusLabel, '')
}

/** 场地名 */
export function spaceName(space) {
  if (!space) return ''
  return first(space.spaceName, space.name, '')
}

/** 设备名 */
export function deviceName(device) {
  if (!device) return ''
  return first(device.deviceName, device.name, '')
}

/**
 * 取分页列表。
 * 兼容 {list: [...]}（当前契约与 Mock）与 {items: [...]}（PageResult），
 * 以及后端直接返回裸数组的情况。
 */
export function listOf(data) {
  if (!data) return []
  if (Array.isArray(data)) return data
  if (Array.isArray(data.list)) return data.list
  if (Array.isArray(data.items)) return data.items
  if (Array.isArray(data.records)) return data.records
  return []
}

/** 取总数 */
export function totalOf(data) {
  if (!data) return 0
  if (Array.isArray(data)) return data.length
  const total = first(data.total, data.totalCount, data.count)
  return typeof total === 'number' ? total : listOf(data).length
}

/**
 * 时间字段统一取字符串。
 * 后端有的地方给 `startTime`，场地列表里给的是 `openStartTime`。
 */
export function timeOf(obj, ...keys) {
  if (!obj) return ''
  for (let i = 0; i < keys.length; i += 1) {
    const v = obj[keys[i]]
    if (v) return v
  }
  return ''
}
