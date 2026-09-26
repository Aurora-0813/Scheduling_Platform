import { defineStore } from 'pinia'
import { getMessages, getUnreadCount } from '@/api/notify'

// 通知状态：未读数、通知列表
export const useNotifyStore = defineStore('notify', {
  state: () => ({
    unreadCount: 0,
    list: [],
    connected: false,
  }),
  getters: {
    hasUnread: (state) => state.unreadCount > 0,
  },
  actions: {
    async refreshUnread() {
      try {
        const data = await getUnreadCount()
        this.unreadCount = data.count
      } catch (e) {}
    },
    async refreshList() {
      try {
        this.list = await getMessages()
      } catch (e) {}
    },
    // 收到 WebSocket 推送：未读 +1，列表头部插入
    receive(msg) {
      this.unreadCount += 1
      this.list.unshift(msg)
    },
    onRead(msgId) {
      const item = this.list.find((i) => i.messageId === msgId)
      if (item && !item.isRead) {
        item.isRead = true
        this.unreadCount = Math.max(0, this.unreadCount - 1)
      }
    },
    onReadAll() {
      this.list.forEach((i) => (i.isRead = true))
      this.unreadCount = 0
    },
  },
})
