/**
 * 枚举字典与状态展示
 *
 * 契约（docs/api.md 第 88 行 + docs/database.md）：
 *   space_type    1 会议室 / 2 展厅 / 3 多功能厅 / 4 户外场地
 *   device_status 1 完好 / 2 损坏 / 3 缺失配件
 *   order_status  1 待确认 / 2 已确认 / 3 已取消 / 4 已完成
 *   ticket_status 1 待处理 / 2 处理中 / 3 已完成
 *   notify_type   1 预约提醒 / 2 变更致歉 / 3 故障告警
 *
 * ⚠️ 已知的契约漂移（代码里必须容忍，不能只按一边写）：
 *   后端当前的 Mock（app/api/v1/mock_data.py）用的是 `status` 而非
 *   `orderStatus`，且**枚举值与数据库字典对不上**——
 *   例如 ORDER_CREATED 给的是 `status: 1` 配 `statusText: "已确认"`，
 *   而库里 order_status=1 是「待确认」。
 *
 *   因此本模块的取值优先级是：**statusText 优先，整型字典兜底**。
 *   这样当前 Mock 与将来按契约落地的真实接口都能显示正确文案。
 *   真实接口落地后应复核此处，届时可只留整型映射。
 */

const ORDER_LABEL = { 1: '待确认', 2: '已确认', 3: '已取消', 4: '已完成' }
const DEVICE_LABEL = { 1: '设备完好', 2: '设备损坏', 3: '缺失配件' }
const TICKET_LABEL = { 1: '待处理', 2: '处理中', 3: '已完成' }
const SPACE_TYPE_LABEL = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

const LABELS = {
  order: ORDER_LABEL,
  device: DEVICE_LABEL,
  ticket: TICKET_LABEL,
  spaceType: SPACE_TYPE_LABEL,
}

/** 整型枚举 → tag 配色（对应 styles/theme.css 的 .tag 变体） */
const ENUM_TAG = {
  order: { 1: 'purple', 2: 'green', 3: 'gray', 4: 'blue' },
  device: { 1: 'green', 2: 'red', 3: 'orange' },
  ticket: { 1: 'blue', 2: 'orange', 3: 'green' },
}

/** 文案 → tag 配色。用于 statusText 可读、但整型值不可信的场合 */
const TEXT_TAG = {
  待确认: 'purple',
  已确认: 'green',
  已取消: 'gray',
  已完成: 'blue',
  待处理: 'blue',
  处理中: 'orange',
  可用: 'green',
  停用: 'gray',
  正常: 'green',
  维修中: 'orange',
  设备完好: 'green',
  完好: 'green',
  设备损坏: 'red',
  损坏: 'red',
  缺失配件: 'orange',
  灯泡老化: 'red',
}

function pick(map, key) {
  if (key === undefined || key === null || key === '') return undefined
  return map[key]
}

/**
 * 状态文案
 * @param {'order'|'device'|'ticket'} kind
 * @param {number|string} value 整型枚举，或后端直接给的字符串
 * @param {string} [text] 后端 statusText（Mock 的便利字段，真实接口不保证有）
 */
export function statusLabel(kind, value, text) {
  if (text) return String(text)
  // 后端已经是可读字符串时直接用
  if (typeof value === 'string' && !/^\d+$/.test(value)) return value
  return pick(LABELS[kind], Number(value)) || '未知'
}

/** 状态对应的 tag 配色 */
export function statusTag(kind, value, text) {
  const label = statusLabel(kind, value, text)
  return (
    TEXT_TAG[label] ||
    pick(ENUM_TAG[kind], Number(value)) ||
    'gray'
  )
}

/** 场地类型文案：兼容整型（契约）与字符串（当前 Mock 给的是 "会议室"） */
export function spaceTypeLabel(value) {
  if (value === undefined || value === null || value === '') return '未知类型'
  if (typeof value === 'string' && !/^\d+$/.test(value)) return value
  return SPACE_TYPE_LABEL[Number(value)] || '未知类型'
}

/** 通知类型 → emoji 前缀（消息列表用） */
const NOTIFY_ICON = {
  1: '✅',
  2: '🤖',
  3: '⚠️',
  预约提醒: '✅',
  预约成功: '✅',
  变更致歉: '🤖',
  故障告警: '⚠️',
}

export function notifyIcon(type) {
  return NOTIFY_ICON[type] || '🔔'
}

/** 只有「待确认 / 已确认」允许取消（§5.3 模块 3 取消流程） */
export function canCancelOrder(statusValue, statusText) {
  const label = statusLabel('order', statusValue, statusText)
  return label === '待确认' || label === '已确认'
}

export default {
  statusLabel,
  statusTag,
  spaceTypeLabel,
  notifyIcon,
  canCancelOrder,
}
