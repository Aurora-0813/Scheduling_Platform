<template>
  <view class="page" v-if="order">
    <view class="card">
      <view class="row">
        <text class="title">预约 #{{ order.orderId }}</text>
        <StatusTag :status="order.orderStatus" />
      </view>
      <view class="meta">场地：{{ spaceName }}</view>
      <view class="meta">设备：{{ deviceNames }}</view>
      <view class="meta">时段：{{ fmt(order.startTime) }} ~ {{ fmt(order.endTime) }}</view>
      <view v-if="order.agentRequest" class="meta ai">AI 需求：{{ order.agentRequest }}</view>
    </view>

    <view v-if="trace.length" class="card trace-card">
      <view class="trace-title">AI 思考过程（溯源）</view>
      <!-- 新落库的是 TraceStep 对象（§5.3 冻结契约）；早期数据是纯字符串，两种都要能显示 -->
      <view v-for="(t, i) in trace" :key="i" class="trace-item">
        {{ t.step || i + 1 }}. {{ traceText(t) }}
        <text v-if="t.timestamp" class="trace-ts">{{ t.timestamp }}</text>
      </view>
    </view>

    <view class="actions">
      <button v-if="order.orderStatus === 1" type="primary" @click="confirm">确认预约</button>
      <button v-if="order.orderStatus === 1 || order.orderStatus === 2" @click="cancel">取消预约</button>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getOrder, getResources, confirmOrder, cancelOrder } from '@/api/reserve'
import StatusTag from '@/components/StatusTag.vue'
import { formatDateTime } from '@/utils/format'

const id = ref(null)
const order = ref(null)
const spaceName = ref('')
const deviceNames = ref('')

// agent_trace 为 JSON 数组（后端已反序列化），直接渲染成逐步思考过程（答辩溯源）
const trace = computed(() => (order.value && Array.isArray(order.value.agentTrace) ? order.value.agentTrace : []))

// TraceStep 对象取 result；早期落库的纯字符串原样显示
function traceText(t) {
  return t && typeof t === 'object' ? t.result || '' : String(t ?? '')
}

const fmt = formatDateTime

async function refresh() {
  order.value = await getOrder(id.value)
  try {
    const res = await getResources()
    const sp = (res.spaces || []).find((s) => s.spaceId === order.value.spaceId)
    spaceName.value = sp ? sp.spaceName : `#${order.value.spaceId}`
    const dm = res.devices || []
    deviceNames.value =
      (order.value.deviceIds || [])
        .map((did) => {
          const d = dm.find((x) => x.deviceId === did)
          return d ? d.deviceName : `#${did}`
        })
        .join('、') || '—'
  } catch (e) {
    spaceName.value = `#${order.value.spaceId}`
    deviceNames.value = (order.value.deviceIds || []).join('、') || '—'
  }
}

onLoad(async (opt) => {
  id.value = opt.id
  await refresh()
})

async function confirm() {
  await confirmOrder(id.value)
  uni.showToast({ title: '已确认', icon: 'success' })
  refresh()
}

async function cancel() {
  const r = await new Promise((resolve) =>
    uni.showModal({ title: '取消预约', content: '确定取消该预约吗？', success: (res) => resolve(res.confirm) })
  )
  if (!r) return
  await cancelOrder(id.value)
  refresh()
}
</script>

<style scoped>
.page { padding: 24rpx; }
.card { background: #fff; border-radius: 16rpx; padding: 24rpx; }
.row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20rpx; }
.title { font-size: 32rpx; font-weight: 600; }
.meta { color: #666; font-size: 28rpx; margin-top: 16rpx; }
.meta.ai { color: #2b85e4; }
.trace-card { margin-top: 20rpx; }
.trace-title { font-size: 28rpx; font-weight: 600; color: #2b85e4; margin-bottom: 16rpx; }
.trace-item { font-size: 26rpx; color: #555; padding: 12rpx 0; border-bottom: 1rpx solid #f0f0f0; }
.trace-item:last-child { border-bottom: none; }
.trace-ts { margin-left: 12rpx; font-size: 22rpx; color: #999; }
.actions { margin-top: 40rpx; display: flex; flex-direction: column; gap: 20rpx; }
</style>
