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
            <!--
              ⚠️ 2026-09-30 修：原先这里是 spaceName(o)，而 /orders/my 的订单对象
              **根本没有 spaceName**（只有 spaceId），于是每张卡的标题都是空白。
              名称统一由 utils/nameMap.js 查资源表补出来。
            -->
            <text class="oname">{{ spaceLabel(o.spaceId) }}</text>
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
            <text class="v">{{ deviceLabel(o.deviceIds) }}</text>
          </view>
          <!--
            ⚠️ 2026-09-30（查真库后更正）：
            · reserve_order **没有 budget 列**，o.budget 恒为 undefined；
              这里改显示场地的自身预算（space_resource.budget），标签写明是「场地预算」。
            · reserve_order **没有 order_no 列**，主键 id 就是订单号（后端自己也叫「订单#66」）。
          -->
          <view class="mbrow">
            <text class="k">场地预算</text>
            <text class="v">{{ budgetOf(o) }}</text>
          </view>
          <view class="mbrow">
            <text class="k">单号</text>
            <text class="v mono">{{ orderNoOf(o) }}</text>
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
import { ensureNameMaps, deviceLabel, spaceLabel, spaceBudget } from '@/utils/nameMap.js'
import { orderStatus, orderStatusText, orderId } from '@/utils/normalize.js'
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

/** 单号：表里没有 order_no，主键 id 就是订单号 */
function orderNoOf(o) {
  const id = orderId(o)
  return id === undefined ? '—' : '#' + id
}

/** 场地自身预算；预约表没有预算列，别把它当成「本次预约的花费」 */
function budgetOf(o) {
  return formatMoney(spaceBudget(o && o.spaceId)) || '—'
}

function rangeOf(o) {
  return formatTimeRange(o.startTime, o.endTime) || '—'
}

// 原先这里有个 devicesOf(o)，读的是 o.deviceNames —— 该字段在 /orders/my 里
// **不存在**，所以它恒返回「无」。即使 deviceIds 明明有值也在撒谎。
// 现改用 utils/nameMap.js 的 deviceLabel(o.deviceIds)，按真实 ID 查名字。

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

// 订单只给 spaceId / deviceIds，名称要靠资源表映射补（失败不影响列表本身）
onShow(() => {
  ensureNameMaps()
  load()
})

async function askCancel(o) {
  const ok = await confirm({
    title: '取消预约',
    content: `确定取消「${spaceLabel(o.spaceId)}」的预约吗？取消后时段将释放给其他人。`,
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
