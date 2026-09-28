<template>
  <view class="app-page">
    <mp-nav-bar title="预约详情" back />

    <view class="app-body" :class="{ 'has-cta': canCancel }">
      <view v-if="loading" class="mcard">
        <text class="mtext">加载中…</text>
      </view>

      <mp-empty
        v-else-if="!order"
        icon="🔍"
        :text="error || '没有找到这条预约，可能已被取消'"
        action-text="返回列表"
        @action="goList"
      />

      <template v-else>
        <!-- 状态头 -->
        <view class="plan head">
          <text class="tt">{{ spaceName(order) }}</text>
          <text class="dd">{{ rangeText }}</text>
          <view class="tags">
            <text class="tag" :class="statusTag('order', orderStatus(order), orderStatusText(order))">
              {{ statusLabel('order', orderStatus(order), orderStatusText(order)) }}
            </text>
            <text v-if="durationText" class="tag gray">{{ durationText }}</text>
          </view>
        </view>

        <view class="mcard">
          <view class="mtitle">预约信息</view>
          <view class="mbrow">
            <text class="k">单号</text>
            <text class="v mono">{{ order.orderNo || '—' }}</text>
          </view>
          <view class="mbrow">
            <text class="k">场地</text>
            <text class="v">{{ spaceName(order) }}</text>
          </view>
          <view class="mbrow">
            <text class="k">时段</text>
            <text class="v">{{ rangeText }}</text>
          </view>
          <view class="mbrow">
            <text class="k">设备</text>
            <text class="v">{{ deviceText }}</text>
          </view>
          <view class="mbrow">
            <text class="k">预算</text>
            <text class="v">{{ formatMoney(order.budget) || '—' }}</text>
          </view>
          <view class="mbrow">
            <text class="k">创建于</text>
            <text class="v">{{ order.createTime || '—' }}</text>
          </view>
        </view>

        <!-- 用户原始需求：Agent 落库的 agent_request -->
        <view v-if="order.agentRequest" class="mcard">
          <view class="mtitle">🗣 原始需求</view>
          <text class="mtext">{{ order.agentRequest }}</text>
        </view>

        <!-- Agent 思考链：落库的 agent_trace，默认折叠 -->
        <view v-if="trace.length" class="mcard">
          <view class="mtitle">
            <text>🧠 Agent 决策链</text>
            <text class="more" @tap="showTrace = !showTrace">
              {{ showTrace ? '收起' : `展开 ${trace.length} 步` }}
            </text>
          </view>

          <template v-if="showTrace">
            <view v-for="t in trace" :key="t.step" class="mbstep">
              <view class="tnum">{{ t.step }}</view>
              <view class="txt">
                <text class="ss">{{ t.title }}</text>
                <text v-if="t.body">{{ t.body }}</text>
                <view v-if="t.call" class="code wrap">{{ t.call }}</view>
              </view>
            </view>
          </template>
        </view>
      </template>
    </view>

    <view v-if="canCancel" class="app-cta">
      <view class="btn ghost block danger" hover-class="btn-on" @tap="askCancel">取消预约</view>
    </view>
  </view>
</template>

<script setup>
/**
 * 预约详情
 *
 * ⚠️ 契约里**没有** GET /orders/{orderId}，只有 GET /orders/my。
 *   因此这里用列表接口拉取后按 id 匹配（pageSize 给得较大）。
 *   后端补上详情接口后，把 load() 换成单条查询即可，模板不用动。
 */
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { myOrders, cancelOrder } from '@/api/orders.js'
import { statusLabel, statusTag, canCancelOrder } from '@/utils/dict.js'
import { spaceName, orderStatus, orderStatusText, orderId as idOf } from '@/utils/normalize.js'
import { formatTimeRange, formatDuration, formatMoney } from '@/utils/format.js'
import { formatActionInput } from '@/api/agent.js'
import { confirm, toast, toastOk } from '@/utils/toast.js'
import { TABS } from '@/utils/tabs.js'

const order = ref(null)
const loading = ref(true)
const error = ref('')
const showTrace = ref(false)
const wantId = ref('')

const rangeText = computed(() => {
  if (!order.value) return ''
  return formatTimeRange(order.value.startTime, order.value.endTime) || '—'
})

const durationText = computed(() => {
  if (!order.value) return ''
  return formatDuration(order.value.startTime, order.value.endTime)
})

const deviceText = computed(() => {
  const names = order.value && order.value.deviceNames
  if (names && names.length) return names.join(' + ')
  const ids = order.value && order.value.deviceIds
  if (ids && ids.length) return `${ids.length} 台（编号 ${ids.join('、')}）`
  return '无'
})

const canCancel = computed(() => {
  if (!order.value) return false
  return canCancelOrder(orderStatus(order.value), orderStatusText(order.value))
})

/** 落库的 agent_trace 与 M3 的 trace 同构，复用同一套整理逻辑 */
const trace = computed(() => {
  const raw = order.value && order.value.agentTrace
  if (!Array.isArray(raw)) return []
  return raw.map((t, i) => ({
    step: t.step === undefined || t.step === null ? i + 1 : t.step,
    title: t.result || `步骤 ${i + 1}`,
    body: t.thought || '',
    call: t.action ? `${t.action}(${formatActionInput(t.actionInput)})` : '',
  }))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await myOrders({ page: 1, pageSize: 100 })
    const found = res.list.filter((o) => String(idOf(o)) === String(wantId.value))
    order.value = found.length ? found[0] : null
  } catch (e) {
    error.value = e.message || '加载失败'
    order.value = null
  } finally {
    loading.value = false
  }
}

onLoad((options) => {
  wantId.value = (options && options.orderId) || ''
  if (!wantId.value) {
    loading.value = false
    error.value = '缺少预约编号'
    return
  }
  load()
})

async function askCancel() {
  const ok = await confirm({
    content: `确定取消「${spaceName(order.value)}」的预约吗？取消后时段将释放给其他人。`,
    title: '取消预约',
    confirmText: '确定取消',
    confirmColor: '#F56C6C',
  })
  if (!ok) return

  try {
    await cancelOrder(wantId.value)
    toastOk('已取消')
    load()
  } catch (e) {
    toast(e.message || '取消失败')
    load()
  }
}

function goList() {
  uni.reLaunch({ url: TABS[1].path })
}
</script>

<style scoped>
.head .dd {
  margin-bottom: 6rpx;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-top: 18rpx;
}

.mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 23rpx;
  color: var(--t3);
  word-break: break-all;
}

.code.wrap {
  white-space: normal;
  word-break: break-all;
  line-height: 1.7;
}

.btn.danger {
  color: var(--danger);
  border-color: #fbc4c4;
}
</style>
