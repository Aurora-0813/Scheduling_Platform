<template>
  <view class="page">
    <view class="toolbar">
      <text>未读 {{ store.unreadCount }}</text>
      <text class="read-all" @click="readAll">全部已读</text>
    </view>

    <view v-if="store.list.length === 0" class="empty">暂无通知</view>

    <view
      v-for="n in store.list"
      :key="n.messageId"
      class="card"
      :class="{ unread: !n.isRead }"
      @click="goDetail(n)"
    >
      <view class="row">
        <text class="title">{{ n.title }}</text>
        <text v-if="!n.isRead" class="dot"></text>
      </view>
      <view class="meta">{{ n.content }}</view>
      <view class="time">{{ fmt(n.createTime) }}</view>
    </view>
  </view>
</template>

<script setup>
import { onShow } from '@dcloudio/uni-app'
import { useNotifyStore } from '@/store/notify'
import { readMessage, readAllMessages } from '@/api/notify'
import { formatDateTime } from '@/utils/format'

const store = useNotifyStore()

const fmt = formatDateTime

async function readAll() {
  await readAllMessages()
  store.onReadAll()
}

async function goDetail(n) {
  if (!n.isRead) {
    await readMessage(n.messageId)
    store.onRead(n.messageId)
  }
  uni.navigateTo({ url: `/pages/notify/detail?id=${n.messageId}` })
}

onShow(() => {
  store.refreshList()
  store.refreshUnread()
})
</script>

<style scoped>
.page { padding: 24rpx; }
.toolbar { display: flex; justify-content: space-between; color: #666; font-size: 26rpx; margin-bottom: 20rpx; }
.read-all { color: #2b85e4; }
.empty { text-align: center; color: #999; margin-top: 160rpx; }
.card { background: #fff; border-radius: 16rpx; padding: 24rpx; margin-bottom: 20rpx; }
.card.unread { border-left: 6rpx solid #2b85e4; }
.row { display: flex; justify-content: space-between; align-items: center; }
.title { font-size: 30rpx; font-weight: 600; }
.dot { width: 16rpx; height: 16rpx; border-radius: 50%; background: #fa3534; }
.meta { color: #666; font-size: 26rpx; margin-top: 12rpx; }
.time { color: #bbb; font-size: 22rpx; margin-top: 12rpx; }
</style>
