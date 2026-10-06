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
          <!-- /orders/{id} 只给 spaceId，名称靠 nameMap 补 -->
        <text class="tt">{{ spaceLabel(order.spaceId) }}</text>
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
          <!--
            ⚠️ 2026-09-30（查真库后更正）：reserve_order 表**没有 order_no 列**，
            主键 id 就是订单号，后端与 Agent 自己的文案也都写「订单#66」。
            原先读的 order.orderNo 恒为 undefined，这一行永远显示「—」。
          -->
          <view class="mbrow">
            <text class="k">单号</text>
            <text class="v mono">{{ orderNoText }}</text>
          </view>
          <view class="mbrow">
            <text class="k">场地</text>
            <text class="v">{{ spaceLabel(order.spaceId) }}</text>
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
            <!--
              ⚠️ reserve_order **没有预算列**，预约接口也不返回 budget，
              所以 order.budget 恒为 undefined、这一行永远是「—」。
              改成显示场地的自身预算（space_resource.budget，接口 /resources/spaces 已带），
              并在标签里写明是「场地预算」，不冒充「本次预约的花费」。
            -->
            <text class="k">场地预算</text>
            <text class="v">{{ budgetText }}</text>
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
                <!-- 只显示每步最终结果 + 时间（与 Web 端调度台同口径）；
                     thought / actionInput / observation 一律不渲染 -->
                <view class="sline">
                  <text class="ss">{{ t.title }}</text>
                  <text v-if="!t.action" class="tag gray">推理</text>
                </view>
                <text v-if="t.time" class="stime">{{ t.time }}</text>
              </view>
            </view>
          </template>
        </view>
      </template>
    </view>

    <!--
      底部动作与订单状态一一对应：
        · 确认预约（1→2）：**2026-10-06 补**。此前这里只有「取消」，
          而 Agent 建的单是 status=1 —— 用户没有任何办法把它落实。
        · 标记完成（2→4）：用完了的单要有地方结束，否则一直算占用。
        · 取消预约：待确认 / 已确认都可取消。
      用主题里已有的 .app-cta-row（flex + gap）排，不自己加 margin 拼间距。
      只有一个动作时仍走原来的整块按钮。
    -->
    <view v-if="canConfirm" class="app-cta">
      <view class="app-cta-row">
        <view class="btn grow" hover-class="btn-on" @tap="askConfirm">确认预约</view>
        <view
          v-if="canCancel"
          class="btn ghost danger"
          hover-class="btn-on"
          @tap="askCancel"
        >取消预约</view>
      </view>
    </view>
    <view v-else-if="canComplete" class="app-cta">
      <view class="app-cta-row">
        <view class="btn grow" hover-class="btn-on" @tap="askComplete">标记完成</view>
        <view
          v-if="canCancel"
          class="btn ghost danger"
          hover-class="btn-on"
          @tap="askCancel"
        >取消预约</view>
      </view>
    </view>
    <view v-else-if="canCancel" class="app-cta">
      <view class="btn ghost block danger" hover-class="btn-on" @tap="askCancel">取消预约</view>
    </view>
  </view>
</template>

<script setup>
/**
 * 预约详情
 *
 * ⚠️ **2026-09-30 更正：后端一直有 GET /orders/{orderId}。**
 *   原注释写「契约里没有该接口」是错的（backend/app/api/orders.py 的
 *   @router.get("/{orderId}") 从合并起就在），于是这里绕道列表接口拉全量再按 id
 *   过滤 —— 而后端**根本不支持分页**，那个 pageSize 是被静默忽略的，
 *   订单一多就是一次全表响应。现已改为直接调详情接口，见下方 load()。
 *
 *   越权与不存在**都返回 404**（后端刻意不区分，防止拿 orderId 枚举他人订单），
 *   所以失败提示语统一写成「预约不存在或无权查看」。
 */
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getOrder, cancelOrder, completeOrder, confirmOrder } from '@/api/orders.js'

import {
  statusLabel,
  statusTag,
  canCancelOrder,
  canCompleteOrder,
  canConfirmOrder,
} from '@/utils/dict.js'
import { ensureNameMaps, deviceLabel, spaceLabel, spaceBudget } from '@/utils/nameMap.js'
import { orderStatus, orderStatusText, orderId } from '@/utils/normalize.js'
import { formatTimeRange, formatDuration, formatMoney } from '@/utils/format.js'
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

/** 单号：表里没有 order_no，主键 id 就是订单号 */
const orderNoText = computed(() => {
  const id = orderId(order.value)
  return id === undefined ? '—' : '#' + id
})

/** 场地预算（space_resource.budget）。预约本身没有预算，别把两者混为一谈。 */
const budgetText = computed(() => {
  const o = order.value
  if (!o) return '—'
  return formatMoney(spaceBudget(o.spaceId)) || '—'
})

const durationText = computed(() => {
  if (!order.value) return ''
  return formatDuration(order.value.startTime, order.value.endTime)
})

// 订单只给 deviceIds。原先先读 deviceNames（该字段不存在）、再退回显示编号，
// 用户看到的是「2 台（编号 1、5）」而不是设备名。现在统一按 ID 查真名。
const deviceText = computed(() => deviceLabel(order.value && order.value.deviceIds))

const canCancel = computed(() => {
  if (!order.value) return false
  return canCancelOrder(orderStatus(order.value), orderStatusText(order.value))
})

/** 只有「已确认」能标记完成（状态机 2→4，后端也只允许 2→4） */
const canComplete = computed(() => {
  if (!order.value) return false
  return canCompleteOrder(orderStatus(order.value), orderStatusText(order.value))
})

/** 只有「待确认」能确认（状态机 1→2，后端也只允许 1→2） */
const canConfirm = computed(() => {
  if (!order.value) return false
  return canConfirmOrder(orderStatus(order.value), orderStatusText(order.value))
})

/**
 * 落库的 agent_trace 与 M3 的 trace 同构，复用同一套整理逻辑。
 *
 * ⚠️ 2026-10-06 对准 Web 端：**只保留每步的最终结果**（result + 时间）。
 *    原先还映射了 `body`(thought) 与 `call`(`${action}(${actionInput})`)，
 *    两者都在这轮删掉 —— 它们会暴露模型的推理正文与工具入参（snake_case JSON），
 *    对用户没有信息量，且与调度台「只显示每步最终结果」的口径自相矛盾。
 *    `action` 保留：模板只用它判断**要不要标「推理」**，不渲染成文字。
 */
const trace = computed(() => {
  const raw = order.value && order.value.agentTrace
  if (!Array.isArray(raw)) return []
  return raw.map((t, i) => ({
    step: t.step === undefined || t.step === null ? i + 1 : t.step,
    title: t.result || `步骤 ${i + 1}`,
    time: (t.timestamp || '').slice(11),
    action: t.action || '',
  }))
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    // ⚠️ **2026-09-30 改：原先拉全量列表再按 id 过滤（pageSize: 100，而后端
    // 根本不支持分页、那个参数被静默忽略），订单一多就是一次全表响应。**
    // 现在直接打详情接口（后端一直有这个路由）。
    order.value = await getOrder(wantId.value)
  } catch (e) {
    // 404 有两种含义（不存在 / 不是本人的单），后端刻意不区分，所以提示语不能写死成「不存在」
    error.value = e && e.code === 40404 ? '预约不存在或无权查看' : (e.message || '加载失败')
    order.value = null
  } finally {
    loading.value = false
  }
}

onLoad((options) => {
  ensureNameMaps()
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
    content: `确定取消「${spaceLabel(order.value.spaceId)}」的预约吗？取消后时段将释放给其他人。`,
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

async function askConfirm() {
  const ok = await confirm({
    content: `确认「${spaceLabel(order.value.spaceId)}」这场预约吗？确认后该时段正式占用。`,
    title: '确认预约',
    confirmText: '确认预约',
  })
  if (!ok) return

  try {
    await confirmOrder(wantId.value)
    toastOk('已确认')
    load()
  } catch (e) {
    toast(e.message || '确认失败')
    load()
  }
}

async function askComplete() {
  const ok = await confirm({
    content: `确认「${spaceLabel(order.value.spaceId)}」这场预约已经结束了吗？完成后该时段会释放给其他人。`,
    title: '标记完成',
    confirmText: '标记完成',
  })
  if (!ok) return

  try {
    await completeOrder(wantId.value)
    toastOk('已完成')
    load()
  } catch (e) {
    toast(e.message || '操作失败')
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

/* 思考链每步：结论行 + 时间（与 pages/agent/thinking.vue 同一样式口径）。
   `.ss` 在主题里是 display:block + 下边距；放进 inline-flex 行内要改成按内容宽度排 */
.sline {
  display: inline-flex;
  align-items: baseline;
  gap: 12rpx;
  margin-bottom: 6rpx;
}

.mbstep .txt .ss {
  flex: none;
  margin-bottom: 0;
}

.stime {
  display: block;
  font-size: 21rpx;
  color: var(--t3);
}

.btn.danger {
  color: var(--danger);
  border-color: #fbc4c4;
}
</style>
