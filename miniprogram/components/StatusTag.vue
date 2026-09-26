<template>
  <view class="status-tag" :style="{ color: map.color, background: map.bg }">
    {{ map.label }}
  </view>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: [Number, String], required: true }, // order_status INT 编码
})

// 1待确认 / 2已确认 / 3已取消 / 4已完成（§6.3）
const STATUS_MAP = {
  1: { label: '待确认', color: '#b8860b', bg: '#fff7e0' },
  2: { label: '已确认', color: '#2b85e4', bg: '#e8f3ff' },
  3: { label: '已取消', color: '#999999', bg: '#f0f0f0' },
  4: { label: '已完成', color: '#19be6b', bg: '#e8f8f0' },
}

const map = computed(
  () => STATUS_MAP[Number(props.status)] || { label: String(props.status), color: '#666666', bg: '#eeeeee' }
)
</script>

<style scoped>
.status-tag {
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
  font-size: 24rpx;
  line-height: 1.6;
}
</style>
