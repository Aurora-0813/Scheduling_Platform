/**
 * 契约漂移适配层（Web 端）
 *
 * **为什么需要这一层**
 * ------------------
 * 后端各模块由不同的人分批实现，同一含义的字段在「文档 / Mock / 真实接口」三处并不统一。
 * 本层把差异收在一处，页面只读规范名。
 *
 * 这次是**照着线上真实响应**补齐的（2026-09-29 实测 `smart_scheduler_dev`）：
 *
 * | 接口 | Mock 形状 | **真实形状** |
 * | --- | --- | --- |
 * | `GET /resources/spaces`  | `{page,pageSize,total,list:[{id,name,type,…,statusText}]}` | **裸数组 `[{spaceId,spaceName,spaceType(整数),…}]`** |
 * | `GET /resources/devices` | `{…list:[{id,name,type,…}]}` | **裸数组 `[{deviceId,deviceName,deviceType,deviceStatus(整数),…}]`** |
 * | `GET /orders/my`         | `{…list:[ORDER_CREATED]}` | **裸数组 `[{orderId,…}]`** |
 *
 * 两处都不一样：**外层形状**（`{list:[…]}` vs 裸数组）与**字段名**（`id`/`name` vs `spaceId`/`spaceName`），
 * 而且**枚举值一个给字符串、一个给整数**（Mock 给 `type:"会议室"`，真实给 `spaceType:1`）。
 *
 * 页面若直接写 `data.list || []`，拿到 `undefined` 后**不报错、只是空白** ——
 * 这正是「AI 巡检的场地下拉框没有东西」的原因。
 *
 * **照抄小程序那一层**：`miniprogram/utils/normalize.js` + `utils/dict.js` 早就把这套差异收口了，
 * 所以小程序在真实接口下不空、Web 端空。两端联动时必须读**同一套规范名**，
 * 因此这里刻意与小程序保持同名同义。
 *
 * **规范名以真实接口为准**（也是 `docs/api.md` 的口径）：`spaceName` / `spaceId` / `deviceName` …
 * —— Mock 才是偏离规范的那一方，所以修的是前端，不是后端。
 */

/** 返回第一个「有值」的入参，跳过 undefined / null / 空串 */
export function first(...values) {
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return undefined
}

/**
 * 取分页列表。
 * 兼容裸数组（真实接口）、`{list:[…]}`（Mock 与 `docs/api.md`）、
 * `{items:[…]}`（`app/utils/pagination.py` 的 PageResult）、`{records:[…]}`。
 */
export function listOf(data) {
  if (!data) return []
  if (Array.isArray(data)) return data
  if (Array.isArray(data.list)) return data.list
  if (Array.isArray(data.items)) return data.items
  if (Array.isArray(data.records)) return data.records
  return []
}

/** 取总数。裸数组用长度，分页对象优先读 total/totalCount/count */
export function totalOf(data) {
  if (!data) return 0
  if (Array.isArray(data)) return data.length
  const total = first(data.total, data.totalCount, data.count)
  return typeof total === 'number' ? total : listOf(data).length
}

// ===========================================================================
// 枚举字典（与 miniprogram/utils/dict.js 同一份口径）
// ===========================================================================
// 依据 docs/api.md 与 docs/database.md：
//   space_type    1 会议室 / 2 展厅 / 3 多功能厅 / 4 户外场地
//   device_status 1 完好   / 2 损坏 / 3 缺失配件
//   order_status  1 待确认 / 2 已确认 / 3 已取消 / 4 已完成
// 真实接口给的是**整数**；Mock 给的是现成字符串（`type:"会议室"`）。
// 取值优先级一律是「后端给了文案就用文案，否则整数查表」—— 两边都能显示。
const SPACE_TYPE_LABEL = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }
const DEVICE_STATUS_LABEL = { 1: '完好', 2: '损坏', 3: '缺失配件' }
const ORDER_STATUS_LABEL = { 1: '待确认', 2: '已确认', 3: '已取消', 4: '已完成' }
const SPACE_STATUS_LABEL = { 1: '可用', 0: '停用' }

export function spaceTypeLabel(value, text) {
  return first(text, SPACE_TYPE_LABEL[Number(value)], '未知类型')
}

export function deviceStatusLabel(value, text) {
  return first(text, DEVICE_STATUS_LABEL[Number(value)], '未知状态')
}

export function orderStatusLabel(value, text) {
  return first(text, ORDER_STATUS_LABEL[Number(value)], '未知状态')
}

export function spaceStatusLabel(value, text) {
  return first(text, SPACE_STATUS_LABEL[Number(value)], '未知')
}

// ===========================================================================
// 实体归一：把「Mock 形状」与「真实形状」都收敛成同一套规范名
// ===========================================================================

/** 场地 → { spaceId, spaceName, spaceType, spaceTypeText, capacity, location, status, statusText } */
export function spaceOf(raw) {
  if (!raw) return null
  const spaceType = first(raw.spaceType, raw.type)
  return {
    ...raw,
    spaceId: first(raw.spaceId, raw.id),
    spaceName: first(raw.spaceName, raw.name, ''),
    spaceType,
    spaceTypeText: spaceTypeLabel(spaceType, typeof raw.type === 'string' ? raw.type : undefined),
    capacity: first(raw.capacity, 0),
    location: first(raw.location, ''),
    status: first(raw.status, 1),
    statusText: spaceStatusLabel(raw.status, raw.statusText),
  }
}

/** 设备 → { deviceId, deviceName, deviceType, deviceStatus, deviceStatusText, totalCount, availableCount } */
export function deviceOf(raw) {
  if (!raw) return null
  return {
    ...raw,
    deviceId: first(raw.deviceId, raw.id),
    deviceName: first(raw.deviceName, raw.name, ''),
    deviceType: first(raw.deviceType, raw.type, ''),
    deviceStatus: first(raw.deviceStatus, raw.status, 1),
    deviceStatusText: deviceStatusLabel(raw.deviceStatus ?? raw.status, raw.statusText),
    totalCount: first(raw.totalCount, 0),
    availableCount: first(raw.availableCount, 0),
  }
}

/** 订单 → { orderId, orderStatus, orderStatusText, … }（其余字段原样保留） */
export function orderOf(raw) {
  if (!raw) return null
  const orderStatus = first(raw.orderStatus, raw.status)
  return {
    ...raw,
    orderId: first(raw.orderId, raw.id),
    orderStatus,
    orderStatusText: orderStatusLabel(orderStatus, raw.statusText),
  }
}

/** 列表版：批量归一 */
export const spacesOf = (data) => listOf(data).map(spaceOf).filter(Boolean)
export const devicesOf = (data) => listOf(data).map(deviceOf).filter(Boolean)
export const ordersOf = (data) => listOf(data).map(orderOf).filter(Boolean)

