/**
 * 模块 3 / 7：消息通知
 *
 * 四个接口后端**全都有**（backend/app/api/messages.py）：
 *   GET  /messages                        全部消息（**裸数组**，支持 skip/limit，上限 100）
 *   GET  /messages/unread                 **只有未读数** → {count}（不是列表！）
 *   PUT  /messages/{messageId}/read       单条标记已读（越权与不存在都 404）
 *   PUT  /messages/read-all               全部标记已读（真批量 UPDATE）
 *
 * ⚠️ **2026-09-30 更正了一段错话。**
 * 本文件原先写着「两处契约缺口：没有标记已读接口、没有 GET /messages/list」，
 * 并据此只实现了 `unread()` —— **那两句都是错的**，上面四个接口从合并起就在。
 * 后果是页面被写成了「只能看未读、已读只改内存」，而且那段假说明
 * （`pages/message/list.vue` 的「后端尚未提供…」）还被渲染给用户看。
 *
 * ⚠️ 两个字段陷阱：
 *   1. `GET /messages/unread` 返回的是 `{count: N}`，**不是** `{total, list}`。
 *      所以它**只能拿来当角标**，不能当列表用 —— 用 `listOf()` 解它恒得空数组。
 *   2. 列表项主键是 **`messageId`**，不是 `id`（见 _message_out）。
 *      模板里若写 `:key="m.id"` 会全是 undefined。
 */
import { request } from '@/api/request.js'
import { listOf, totalOf } from '@/utils/normalize.js'

/** 全部消息（含已读）。后端按 createTime 倒序返回裸数组。 */
export async function list(params) {
  const data = await request({ path: '/messages', method: 'GET', data: params })
  return { list: listOf(data), total: totalOf(data) }
}

/**
 * 未读数。
 *
 * ⚠️ 这个接口**只返回计数**（`{count: N}`），没有列表。
 * 返回形状保持 `{list, total}` 只是为了调用方统一，`list` **恒为空数组**。
 * 要列表请用 `list()`。
 */
export async function unread() {
  const data = await request({ path: '/messages/unread', method: 'GET' })
  return { list: listOf(data), total: totalOf(data) }
}

/** 单条标记已读 */
export function read(messageId) {
  return request({ path: '/messages/' + messageId + '/read', method: 'PUT' })
}

/** 全部标记已读 */
export function readAll() {
  return request({ path: '/messages/read-all', method: 'PUT' })
}

export default { list, unread, read, readAll }
