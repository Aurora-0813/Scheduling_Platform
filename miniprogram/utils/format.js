/**
 * 时间与金额格式化
 *
 * 契约（开发流程.md §5.1）：时间一律 `YYYY-MM-DD HH:mm:ss` 本地时间。
 * 后端不做时区换算，因此**严禁**用 new Date().toISOString()——
 * 它带 `Z`（UTC），东八区会凭空差 8 小时。
 */

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function pad(n) {
  return n < 10 ? '0' + n : String(n)
}

/**
 * 解析后端时间字符串为 Date
 *
 * 坑：iOS / WKWebView 解析 `2026-10-18 14:00:00`（空格分隔）会得到 Invalid Date。
 * 统一把 `-` 换成 `/` 才能被所有端正确解析。
 */
export function parseDateTime(value) {
  if (!value) return null
  if (value instanceof Date) return value
  if (typeof value === 'number') return new Date(value)
  const d = new Date(String(value).replace(/-/g, '/'))
  return isNaN(d.getTime()) ? null : d
}

/** Date → 'YYYY-MM-DD HH:mm:ss'（本地时间，用于提交给后端） */
export function formatDateTime(value = new Date()) {
  const d = value instanceof Date ? value : parseDateTime(value)
  if (!d) return ''
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  )
}

/** Date → 'HH:mm' */
export function formatTime(value) {
  const d = value instanceof Date ? value : parseDateTime(value)
  if (!d) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Date → 'MM-DD' */
export function formatMonthDay(value) {
  const d = value instanceof Date ? value : parseDateTime(value)
  if (!d) return ''
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Date → '周三' */
export function formatWeekday(value) {
  const d = value instanceof Date ? value : parseDateTime(value)
  if (!d) return ''
  return WEEKDAYS[d.getDay()]
}

/** 当天 00:00，用于「是否同一天」的比较 */
function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/**
 * 列表里的相对时间：刚刚 / x 分钟前 / 今天 HH:mm / 昨天 HH:mm / MM-DD
 */
export function relativeTime(value) {
  const d = value instanceof Date ? value : parseDateTime(value)
  if (!d) return ''
  const diff = Date.now() - d.getTime()
  if (diff < 60 * 1000) return '刚刚'
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`

  const dayGap = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000)
  if (dayGap === 0) return formatTime(d)
  if (dayGap === 1) return `昨天 ${formatTime(d)}`
  if (dayGap < 7) return `${dayGap} 天前`
  return formatMonthDay(d)
}

/**
 * 预约时段的展示文案，如「周五 14:00 - 16:00」
 * 跨天时补上日期，避免看不出是两天
 */
export function formatTimeRange(startTime, endTime) {
  const s = parseDateTime(startTime)
  const e = parseDateTime(endTime)
  if (!s) return ''
  if (!e) return formatDateTime(s)
  const sameDay = startOfDay(s) === startOfDay(e)
  const head = `${formatWeekday(s)} ${formatTime(s)} - ${formatTime(e)}`
  return sameDay ? head : `${formatMonthDay(s)} ${formatTime(s)} - ${formatMonthDay(e)} ${formatTime(e)}`
}

/**
 * 金额展示。后端 MoneyStr 输出的是**字符串**（如 "980.10"），
 * 这里只做展示包装，不要拿去参与数值运算。
 */
export function formatMoney(value) {
  if (value === null || value === undefined || value === '') return ''
  const s = String(value)
  return `¥ ${s}`
}

/** 时长（分钟）→「2 小时」「1.5 小时」 */
export function formatDuration(startTime, endTime) {
  const s = parseDateTime(startTime)
  const e = parseDateTime(endTime)
  if (!s || !e) return ''
  const minutes = Math.round((e.getTime() - s.getTime()) / 60000)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = minutes / 60
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} 小时`
}
