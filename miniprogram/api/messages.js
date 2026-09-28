/**
 * 模块 3 / 7：消息通知
 *
 * 契约只有 GET /messages/unread，返回 { total, list: [{ id, notifyType,
 * title, content, isRead, createTime }] }。
 *
 * ⚠️ 两处契约缺口（未与后端确认前不自行发明接口，代码里标 TODO）：
 *   1. 没有「标记已读」接口 → 页面上的「全部已读」只做前端态，不落库。
 *   2. 没有 GET /messages/list（全部消息）→ 消息页只能展示未读。
 *   两者落地后在这里补 read() / list()，页面模板不用改。
 */
import { request } from '@/api/request.js'
import { listOf, totalOf } from '@/utils/normalize.js'

/** 未读消息 */
export async function unread() {
  const data = await request({ path: '/messages/unread', method: 'GET' })
  return { list: listOf(data), total: totalOf(data) }
}

// TODO(契约缺口): export function list(params) → GET /messages/list
// TODO(契约缺口): export function read(id)      → PUT  /messages/{id}/read

export default { unread }
