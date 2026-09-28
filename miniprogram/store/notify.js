/**
 * 消息通知 store
 *
 * 维护未读数角标与消息列表。首页与消息页共用同一份，避免两处各拉一次。
 */
import { reactive } from 'vue'
import * as messagesApi from '@/api/messages.js'

export const notifyStore = reactive({
  /** @type {object[]} */
  list: [],
  unreadCount: 0,
  loaded: false,
  loading: false,
  error: '',
})

/** 拉取未读消息。失败时保留旧数据，只记错误 */
export async function refreshUnread() {
  notifyStore.loading = true
  notifyStore.error = ''
  try {
    const { list, total } = await messagesApi.unread()
    notifyStore.list = list
    notifyStore.unreadCount = total || list.length
    notifyStore.loaded = true
  } catch (e) {
    notifyStore.error = e.message || '消息加载失败'
  } finally {
    notifyStore.loading = false
  }
}

/**
 * 本地置为已读。
 *
 * ⚠️ 后端**没有**「标记已读」接口（见 api/messages.js 的契约缺口说明），
 * 所以这里只改前端状态，不落库；刷新页面后会重新变回未读。
 * 接口落地后在此处补一次 API 调用即可。
 */
export function markAllReadLocal() {
  notifyStore.list = notifyStore.list.map((item) => ({ ...item, isRead: true }))
  notifyStore.unreadCount = 0
}

export default { notifyStore, refreshUnread, markAllReadLocal }
