<template>
  <view class="page" v-if="msg">
    <view class="card">
      <view class="title">{{ msg.title }}</view>
      <view class="time">{{ fmt(msg.createTime) }}</view>
      <view class="content">{{ msg.content }}</view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { useNotifyStore } from '@/store/notify'
import { formatDateTime } from '@/utils/format'

const store = useNotifyStore()
const id = ref(null)
const msg = computed(() => store.list.find((i) => i.messageId === Number(id.value)))

const fmt = formatDateTime

onLoad((opt) => {
  id.value = opt.id
})
</script>

<style scoped>
.page { padding: 24rpx; }
.card { background: #fff; border-radius: 16rpx; padding: 24rpx; }
.title { font-size: 32rpx; font-weight: 600; }
.time { color: #bbb; font-size: 24rpx; margin-top: 12rpx; }
.content { color: #333; font-size: 28rpx; margin-top: 24rpx; line-height: 1.8; }
</style>
