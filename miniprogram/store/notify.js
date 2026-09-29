/**
 * 消息通知 store
 *
 * 维护**未读数角标**与消息列表。首页、消息页、我的页共用同一份。
 *
 * ⚠️ **2026-09-30 两处修正：**
 *
 * 1. `refreshUnread()` 不再写 `notifyStore.list`。
 *    它调的是 `GET /messages/unread`，那个接口**只返回计数**（`{count}`），
 *    根本给不出列表。原实现把 `list` 一起赋成了空数组 —— 于是只要首页
 *    （或我的页）比消息页晚刷新一次，**消息页刚拉到的列表就被清空了**。
 *    现在分工明确：本函数只管角标，列表由消息页自己用 `list()` 拉。
 *
 * 2. **删掉了 `markAllReadLocal()`。**
 *    它的注释写着「后端没有标记已读接口，所以只改前端状态、刷新会复原」——
 *    **这句话是错的**：`PUT /messages/read-all` 一直都有。已读现在由
 *    消息页直接调真实接口落库，这个「只改内存」的替身没有存在必要。
 */
import { reactive } from 'vue'
import * as messagesApi from '@/api/messages.js'

export const notifyStore = reactive({
  /** @type {object[]} 由消息页写入；首页/我的页只读 unreadCount */
  list: [],
  unreadCount: 0,
  loaded: false,
  loading: false,
  error: '',
})

/**
 * 刷新未读数角标。失败时**保留旧值**，只记错误 ——
 * 角标显示上一次的数字，好过因为一次网络抖动直接跳到 0。
 */
export async function refreshUnread() {
  notifyStore.loading = true
  notifyStore.error = ''
  try {
    const { total } = await messagesApi.unread()
    notifyStore.unreadCount = total
    notifyStore.loaded = true
  } catch (e) {
    notifyStore.error = e.message || '消息加载失败'
  } finally {
    notifyStore.loading = false
  }
}

/** 供消息页在本地变更后同步角标（真实落库由消息页调 API 完成） */
export function setUnreadCount(n) {
  notifyStore.unreadCount = Math.max(0, Number(n) || 0)
}

export default { notifyStore, refreshUnread, setUnreadCount }
