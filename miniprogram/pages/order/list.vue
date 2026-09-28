<template>
  <view class="app-page">
    <mp-nav-bar title="我的预约" />

    <view class="app-body">
      <!-- 状态筛选 -->
      <view class="segs">
        <view
          v-for="s in SEGMENTS"
          :key="s.key"
          class="seg"
          :class="{ on: seg === s.key }"
          @tap="seg = s.key"
        >
          <text>{{ s.label }}</text>
          <text v-if="s.key !== 'all' && countOf(s.key) > 0" class="n">{{ countOf(s.key) }}</text>
        </view>
      </view>

      <view v-if="loading" class="mcard">
        <text class="mtext">加载中…</text>
      </view>

      <mp-empty
        v-else-if="error"
        icon="⚠️"
        :text="error"
        action-text="重试"
        @action="load"
      />

      <mp-empty
        v-else-if="!shown.length"
        icon="🗓"
        text="这里还没有预约"
        action-text="去语音预约"
        @action="goVoice"
      />

      <view v-else>
        <view
          v-for="o in shown"
          :key="orderId(o)"
          class="mcard"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="openDetail(o)"
        >
          <view class="ohead">
            <text class="oname">{{ spaceName(o) }}</text>
            <text class="tag" :class="statusTag('order', orderStatus(o), orderStatusText(o))">
              {{ statusLabel('order', orderStatus(o), orderStatusText(o)) }}
            </text>
          </view>

          <view class="mbrow">
            <text class="k">时段</text>
            <text class="v">{{ rangeOf(o) }}</text>
          </view>
          <view class="mbrow">
            <text class="k">设备</text>
            <text class="v">{{ devicesOf(o) }}</text>
          </view>
          <view class="mbrow">
            <text class="k">预算</text>
            <text class="v">{{ formatMoney(o.budget) || '—' }}</text>
          </view>
          <view class="mbrow">
            <text class="k">单号</text>
            <text class="v mono">{{ o.orderNo || '—' }}</text>
          </view>

          <!-- 只有待确认 / 已确认可取消，与后端校验保持一致 -->
          <view v-if="canCancelOrder(orderStatus(o), orderStatusText(o))" class="oa">
            <view
              class="btn ghost"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap.stop="askCancel(o)"
            >取消预约</view>
          </view>
        </view>
      </view>
    </view>

    <mp-tab-bar :current="1" />
  </view>
</template>

<script setup>
/**
 * 我的预约列表（tab 2）
 *
 * 原型 M1-M6 没有这一屏，视觉沿用同一套设计语言：
 * mcard + mbrow + tag，与其他页面保持一致。
 *
 * 数据：GET /orders/my。分页先只拉第一页（pageSize 50），
 * 触底加载等后端分页稳定后再补。
 */
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { myOrders, cancelOrder } from '@/api/orders.js'
import { statusLabel, statusTag, canCancelOrder } from '@/utils/dict.js'
import { spaceName, orderStatus, orderStatusText, orderId } from '@/utils/normalize.js'
import { formatTimeRange, formatMoney } from '@/utils/format.js'
import { confirm, toastOk, toast } from '@/utils/toast.js'

const SEGMENTS = [
  { key: 'all', label: '全部' },
  { key: '待确认', label: '待确认' },
  { key: '已确认', label: '已确认' },
  { key: '已完成', label: '已完成' },
]

const list = ref([])
const loading = ref(true)
const error = ref('')
const seg = ref('all')

/** 统一取状态文案，筛选与展示共用，避免两处判断不一致 */
function labelOf(o) {
  return statusLabel('order', orderStatus(o), orderStatusText(o))
}

const shown = computed(() => {
  if (seg.value === 'all') return list.value
  return list.value.filter((o) => labelOf(o) === seg.value)
})

function countOf(key) {
  return list.value.filter((o) => labelOf(o) === key).length
}

function rangeOf(o) {
  return formatTimeRange(o.startTime, o.endTime) || '—'
}

function devicesOf(o) {
  const names = o.deviceNames || []
  if (!names.length) return '无'
  return names.length > 2 ? `${names.length} 台设备` : names.join(' + ')
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await myOrders({ page: 1, pageSize: 50 })
    list.value = res.list
  } catch (e) {
    error.value = e.message || '预约加载失败'
    list.value = []
  } finally {
    loading.value = false
  }
}

onShow(load)

async function askCancel(o) {
  const ok = await confirm({
    title: '取消预约',
    content: `确定取消「${spaceName(o)}」的预约吗？取消后时段将释放给其他人。`,
    confirmText: '确定取消',
    confirmColor: '#F56C6C',
  })
  if (!ok) return

  const id = orderId(o)
  if (id === undefined) {
    toast('这条预约缺少单号，无法取消')
    return
  }
  try {
    await cancelOrder(id)
    toastOk('已取消')
    load()
  } catch (e) {
    // 后端可能因状态已变更而拒绝，如实提示并刷新
    toast(e.message || '取消失败')
    load()
  }
}

function openDetail(o) {
  const id = orderId(o)
  if (id === undefined) return
  uni.navigateTo({ url: `/pages/order/detail?orderId=${id}` })
}

function goVoice() {
  uni.navigateTo({ url: '/pages/voice/record' })
}
</script>

<style scoped>
.segs {
  display: flex;
  gap: 14rpx;
  margin-bottom: 24rpx;
}

.seg {
  flex: 1;
  text-align: center;
  padding: 16rpx 0;
  border-radius: 14rpx;
  font-size: 24rpx;
  color: var(--t2);
  background: #fff;
  border: 1px solid #eef1f6;
}

.seg.on {
  color: #fff;
  background: linear-gradient(135deg, var(--ai-a), var(--ai-b));
  border-color: transparent;
  font-weight: 600;
}

.seg .n {
  font-size: 21rpx;
  opacity: 0.75;
  margin-left: 6rpx;
}

.ohead {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-bottom: 8rpx;
}

.oname {
  flex: 1;
  min-width: 0;
  font-size: 28rpx;
  font-weight: 600;
  color: var(--t1);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 23rpx;
  color: var(--t3);
  word-break: break-all;
}

.oa {
  display: flex;
  justify-content: flex-end;
  margin-top: 20rpx;
  padding-top: 20rpx;
  border-top: 1px solid #f5f7fa;
}

.oa .btn {
  padding: 12rpx 32rpx;
  font-size: 24rpx;
}
</style>
