<template>
  <view class="app-page">
    <mp-nav-bar title="方案确认" back :right="sideLabel" />

    <view class="app-body has-cta">
      <!--
        没有方案时把 Agent 的原话显示出来（原来只给一句通用空态）。
        追问文案在 trace 的最后一步，见下面 agentReply 的说明。
      -->
      <template v-if="!active">
        <view class="mcard">
          <view class="mtitle">🤖 AI 还需要你补充一点信息</view>
          <text class="mtext">
            {{ agentReply || '暂时没能生成方案。补充一下时间、人数或设备，我再算一次。' }}
          </text>
        </view>

        <view class="mcard">
          <view class="mtitle">接下来怎么做</view>
          <text class="mtext">
            回到语音页接着说就行——场地已经记住了，你只需要补上时间
            （例如「明天下午两点到四点」），不用把场地再描述一遍。
          </text>
        </view>
      </template>

      <template v-else>
        <!-- 主方案 / 备选方案 -->
        <view class="plan">
          <text class="tt">{{ activeTitle }}</text>

          <text class="dd">{{ spaceLine }}</text>
          <text class="dd">{{ timeLine }}</text>
          <text v-if="deviceLine" class="dd">{{ deviceLine }}</text>

          <!-- 后端冻结的 Plan schema 里没有价格字段，只有 reason 散文。
               有价格才渲染大号金额，没有就不编造数字 -->
          <text v-if="priceText" class="price">{{ priceText }}</text>
        </view>

        <!-- 决策依据：直接展示 plan.reason，这是后端给出的唯一解释来源 -->
        <view v-if="active.reason" class="mcard">
          <view class="mtitle">🤖 AI 决策依据</view>
          <text class="mtext">{{ active.reason }}</text>
        </view>

        <!-- 另一套方案：点一下即可切换，不用来回跳页 -->
        <view v-if="other" class="mcard">
          <view class="mtitle">
            <text>{{ isMain ? '备选方案' : '主方案' }}</text>
            <text class="more" @tap="toggle">点击切换</text>
          </view>
          <view class="mbrow">
            <text class="k">场地</text>
            <text class="v">{{ nameOf(other) }}</text>
          </view>
          <view class="mbrow">
            <text class="k">时段</text>
            <text class="v">{{ rangeOf(other) || '—' }}</text>
          </view>
          <view class="mbrow">
            <text class="k">差异</text>
            <text class="v warn">{{ diffOf(other) }}</text>
          </view>
        </view>

        <!-- 摘要 + 自动生成的标签 -->
        <view class="mcard">
          <view class="mtitle">🤖 AI 预约摘要</view>
          <text class="mtext">{{ summary }}</text>
          <view class="tags">
            <text v-for="(t, i) in tags" :key="i" class="tag" :class="t.tone">{{ t.text }}</text>
          </view>
        </view>

        <text class="note">
          确认后将在同一事务内锁定场地与设备并生成预约单，冲突校验由后端再次执行。
        </text>
      </template>
    </view>

    <view v-if="!active" class="app-cta">
      <view class="btn ai block" hover-class="btn-on" :hover-stay-time="60" @tap="goVoice">
        补充时间 / 改需求 →
      </view>
    </view>

    <view v-if="active" class="app-cta">
      <view class="app-cta-row">
        <view
          v-if="other"
          class="btn ghost"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="toggle"
        >换备选</view>
        <view
          class="btn ai grow"
          :class="{ disabled: submitting }"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="submit"
        >{{ submitting ? '创建中…' : '确认并创建预约' }}</view>
      </view>
    </view>
  </view>
</template>

<script setup>
/**
 * M4 方案确认
 *
 * 对应原型「小程序-4 方案确认 · AI 摘要」。
 * 数据来自 store/agent.js 里缓存的 /agent/schedule 返回，不重复请求。
 *
 * ⚠️ 冻结的 Plan schema（app/schemas/agent.py）只有
 *   { spaceId, spaceName, deviceIds, startTime, endTime, reason }，
 *   **没有价格字段**，金额只出现在 reason 散文里。
 *   因此原型的「¥ 860」在这里是条件渲染：后端给了价格才显示，
 *   否则不编造数字（详见 miniprogram/README.md「已知契约缺口」）。
 */
import { ref, computed } from 'vue'
import { onUnload } from '@dcloudio/uni-app'
import { agentStore, resetAgent } from '@/store/agent.js'
import { confirmOrder, createOrder } from '@/api/orders.js'
import { formatTimeRange, formatMoney } from '@/utils/format.js'
import { first } from '@/utils/normalize.js'
import { toast, toastOk, showLoading, hideLoading, resetLoading } from '@/utils/toast.js'
import { TABS } from '@/utils/tabs.js'

// 页面销毁时把 loading 计数归零：万一有哪条路径没配平，残留的计数会让之后
// 每一次 show/hide 都错位 —— 微信侧会一直报「showLoading 与 hideLoading 必须配对使用」
onUnload(() => resetLoading())

const submitting = ref(false)
/** true 表示当前展示主方案 */
const isMain = ref(true)

const payload = computed(() => agentStore.payload)
const mainPlan = computed(() => (payload.value ? payload.value.plan : null))
const backupPlan = computed(() => (payload.value ? payload.value.backupPlan : null))

const active = computed(() => (isMain.value ? mainPlan.value : backupPlan.value) || null)
const other = computed(() => (isMain.value ? backupPlan.value : mainPlan.value) || null)

const sideLabel = computed(() => (isMain.value ? '主方案' : '备选方案'))

const activeTitle = computed(() => (isMain.value ? '🤖 推荐方案' : '🤖 备选方案'))

function nameOf(p) {
  if (!p) return ''
  return first(p.spaceName, p.name, '未知场地')
}

function rangeOf(p) {
  if (!p) return ''
  return formatTimeRange(p.startTime, p.endTime)
}

const spaceLine = computed(() => `场地：${nameOf(active.value)}`)
const timeLine = computed(() => rangeOf(active.value) || '时段待定')

const deviceLine = computed(() => {
  const ids = active.value ? active.value.deviceIds : null
  if (!ids || !ids.length) return ''
  return `设备：${ids.length} 台（编号 ${ids.join('、')}）`
})

/**
 * 价格只在后端真的给了字段时才显示。
 * 兼容几种可能命名，避免后端换字段名就整个不显示。
 */
const priceText = computed(() => {
  const p = active.value
  if (!p) return ''
  const raw = first(p.price, p.totalPrice, p.budget, p.amount)
  if (raw === undefined || raw === null || raw === '') return ''
  // 后端 MoneyStr 输出的是字符串，这里只做展示包装
  return formatMoney(raw)
})

/** 备选方案相对主方案的差异，取自备选自己的 reason 首句 */
function diffOf(p) {
  if (!p || !p.reason) return '见决策依据'
  const s = String(p.reason)
  return s.length > 40 ? `${s.slice(0, 40)}…` : s
}

/** 摘要由方案字段拼装，不是另写的文案，避免与真实方案不符 */
const summary = computed(() => {
  const p = active.value
  if (!p) return ''
  const parts = [`${nameOf(p)}`]
  const range = rangeOf(p)
  if (range) parts.push(range)
  if (p.deviceIds && p.deviceIds.length) parts.push(`含 ${p.deviceIds.length} 台设备`)
  else parts.push('不含设备')
  return `${parts.join('，')}。`
})

/** 标签同样从真实字段推导，不用原型里写死的那两个 */
const tags = computed(() => {
  const out = []
  const combined = `${active.value && active.value.reason ? active.value.reason : ''}`
  if (/降级/.test(combined)) out.push({ tone: 'orange', text: '设备已降级' })
  if (/拆分|两个|两间/.test(combined)) out.push({ tone: 'purple', text: '场地已拆分' })
  if (payload.value && payload.value.needConfirm) out.push({ tone: 'blue', text: '待你确认' })
  if (backupPlan.value) out.push({ tone: 'gray', text: '含备选方案' })
  return out
})

function toggle() {
  if (!other.value) return
  isMain.value = !isMain.value
}

/**
 * 没有方案时，Agent 到底说了什么。
 *
 * 后端返回体只有 plan / backupPlan / trace / orderId / needConfirm —— **没有**独立的消息字段，
 * Agent 那句「请您补充使用时间…」只躺在 trace 最后一步的 `result` 里。
 * 原来这里只显示一句通用空态「还没有生成方案」，用户根本不知道要补什么，
 * 点按钮又跳回同一段预填文本，等于原地打转。
 *
 * 取法：优先取**最后一步没有 action 的**（不是工具调用，而是模型对用户说的话）；
 * 找不到就退回最后一步的 result。
 */
const agentReply = computed(() => {
  const p = payload.value
  if (!p || p.plan) return ''
  const trace = Array.isArray(p.trace) ? p.trace : []
  for (let i = trace.length - 1; i >= 0; i--) {
    const t = trace[i]
    if (t && !t.action && t.result) return String(t.result)
  }
  const last = trace.length ? trace[trace.length - 1] : null
  return last && last.result ? String(last.result) : ''
})

function goVoice() {
  // 把追问一起带过去，语音页会把「AI 还缺什么」显示出来
  agentStore.lastQuestion = agentReply.value || ''
  uni.navigateTo({ url: '/pages/voice/record' })
}

async function submit() {
  if (submitting.value) return

  const p = active.value
  if (!p) return
  if (!p.startTime || !p.endTime) {
    toast('方案缺少时段信息，无法创建预约')
    return
  }

  submitting.value = true

  // ⚠️ **2026-09-29 修复：原先这里无条件调 createOrder，演示时必然报 409。**
  //
  // 原因：`/agent/schedule` 在后端内部**已经把资源锁掉并落了单** ——
  // 返回体带 `orderId`，trace 里有「锁定资源：成功（订单 N）」。
  // 前端再调一次 POST /orders/create，撞上的正是**自己刚锁的那个时段**
  // → 409 / 40901「该时段已被占用」。已在真库实测复现。
  //
  // 契约（docs/api.md 的 `orderId` 说明）：`needConfirm=true` 时前端应拿
  // `orderId` 调 `PUT /orders/{orderId}/confirm` 完成 1→2 流转；
  // `orderId` 为 `null` 才表示「后端确实没建单」，那时才需要自己 createOrder。
  //
  // 只对**主方案**取 `orderId`：它是后端最后一次成功 lock_resources 的结果，
  // 对应的是 `plan`（主方案）。切到备选方案时那次锁定并不属于它，
  // 仍走 createOrder（备选是另一个时段/场地，不会与它自己冲突）。
  const lockedId = isMain.value && payload.value ? payload.value.orderId : null
  showLoading(lockedId ? '确认方案中…' : '创建预约中…')
  try {
    const order = lockedId
      ? await confirmOrder(lockedId)
      : await createOrder({
          spaceId: p.spaceId,
          deviceIds: p.deviceIds || [],
          startTime: p.startTime,
          endTime: p.endTime,
          agentRequest: agentStore.request,
          agentTrace: payload.value ? payload.value.trace : null,
        })

    toastOk(lockedId ? '预约已确认' : '预约已创建')
    // 方案已落库，清掉缓存，避免下次进来沿用旧方案
    resetAgent()

    const id = first(order && order.orderId, order && order.id)
    if (id !== undefined) {
      uni.redirectTo({ url: `/pages/order/detail?orderId=${id}` })
    } else {
      uni.reLaunch({ url: TABS[1].path })
    }
  } catch (e) {
    toast(e.message || '创建预约失败')
  } finally {
    submitting.value = false
    hideLoading()
  }
}
</script>

<style scoped>
.plan .dd {
  margin-bottom: 6rpx;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-top: 20rpx;
}

.note {
  display: block;
  margin-top: 8rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  text-align: center;
  padding: 0 20rpx;
}

.app-cta-row .btn.ghost {
  flex: 1;
}

.app-cta-row .grow {
  flex: 1.8;
}
</style>
