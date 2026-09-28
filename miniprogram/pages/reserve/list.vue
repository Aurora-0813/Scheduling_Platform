<template>
  <view class="page">
    <view class="filters">
      <view
        v-for="s in statusOptions"
        :key="s.value"
        class="filter-item"
        :class="{ active: currentStatus === s.value }"
        @click="setStatus(s.value)"
      >
        {{ s.label }}
      </view>
    </view>

    <view v-if="list.length === 0" class="empty">暂无预约，点击右下角新建</view>

    <view v-for="o in list" :key="o.orderId" class="card" @click="goDetail(o.orderId)">
      <view class="row">
        <text class="title">预约 #{{ o.orderId }}</text>
        <StatusTag :status="o.orderStatus" />
      </view>
      <view class="meta">场地：{{ spaceName(o.spaceId) }}</view>
      <view class="meta">时段：{{ fmt(o.startTime) }} ~ {{ fmt(o.endTime) }}</view>
      <view v-if="o.agentRequest" class="meta ai">AI：{{ o.agentRequest }}</view>
      <view class="actions">
        <button v-if="o.orderStatus === 1" size="mini" type="primary" @click.stop="confirm(o)">确认</button>
        <button v-if="o.orderStatus === 1 || o.orderStatus === 2" size="mini" @click.stop="cancel(o)">取消</button>
      </view>
    </view>

    <view class="fab" @click="goCreate">＋</view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { getOrders, getResources, confirmOrder, cancelOrder } from '@/api/reserve'
import StatusTag from '@/components/StatusTag.vue'
import { formatDateTime } from '@/utils/format'

const list = ref([])
const spaceMap = ref({})
const currentStatus = ref('')
const statusOptions = [
  { value: '', label: '全部' },
  { value: 1, label: '待确认' },
  { value: 2, label: '已确认' },
  { value: 4, label: '已完成' },
  { value: 3, label: '已取消' },
]

const fmt = formatDateTime

function spaceName(id) {
  return spaceMap.value[id] || `#${id}`
}

async function load() {
  list.value = await getOrders(currentStatus.value)
  try {
    const res = await getResources()
    const m = {}
    ;(res.spaces || []).forEach((s) => (m[s.spaceId] = s.spaceName))
    spaceMap.value = m
  } catch (e) {}
}

function setStatus(v) {
  currentStatus.value = v
  load()
}

function goDetail(id) {
  uni.navigateTo({ url: `/pages/reserve/detail?id=${id}` })
}

function goCreate() {
  uni.navigateTo({ url: '/pages/reserve/create' })
}

async function confirm(o) {
  await confirmOrder(o.orderId)
  uni.showToast({ title: '已确认', icon: 'success' })
  load()
}

async function cancel(o) {
  const r = await new Promise((resolve) =>
    uni.showModal({ title: '取消预约', content: '确定取消该预约吗？', success: (res) => resolve(res.confirm) })
  )
  if (!r) return
  await cancelOrder(o.orderId)
  load()
}

onShow(load)
</script>

<style scoped>
.page { padding: 24rpx; padding-bottom: 160rpx; }
.filters { display: flex; gap: 16rpx; margin-bottom: 24rpx; flex-wrap: wrap; }
.filter-item { padding: 8rpx 24rpx; background: #fff; border-radius: 32rpx; font-size: 24rpx; color: #666; }
.filter-item.active { background: #2b85e4; color: #fff; }
.empty { text-align: center; color: #999; margin-top: 160rpx; }
.card { background: #fff; border-radius: 16rpx; padding: 24rpx; margin-bottom: 20rpx; }
.row { display: flex; justify-content: space-between; align-items: center; }
.title { font-size: 30rpx; font-weight: 600; }
.meta { color: #666; font-size: 26rpx; margin-top: 12rpx; }
.meta.ai { color: #2b85e4; }
.actions { display: flex; gap: 16rpx; margin-top: 20rpx; justify-content: flex-end; }
.fab {
  position: fixed; right: 40rpx; bottom: 140rpx; width: 100rpx; height: 100rpx;
  border-radius: 50%; background: #2b85e4; color: #fff; font-size: 56rpx;
  display: flex; align-items: center; justify-content: center; box-shadow: 0 6rpx 16rpx rgba(43,133,228,0.4);
}
</style>
