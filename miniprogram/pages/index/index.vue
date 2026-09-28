<template>
  <view class="app-page">
    <mp-nav-bar big :title="greeting" :right="roleLabel" />

    <view class="app-body">
      <!-- AI 主视觉 -->
      <view class="ai-hero">
        <view class="tt">
          <view class="live"></view>
          <text>AI 小助手已就绪</text>
        </view>
        <text class="dd">直接说出需求，我会自动解析约束、检索场地、排冲突、出方案。</text>
      </view>

      <!-- 快捷入口 -->
      <view class="mcard">
        <view class="mtitle">快捷入口</view>
        <view class="grid4">
          <view
            v-for="item in entries"
            :key="item.key"
            class="cell"
            hover-class="btn-on"
            :hover-stay-time="60"
            @tap="go(item)"
          >
            <view class="ic" :class="item.tone">
              <text>{{ item.icon }}</text>
              <view v-if="item.badge > 0" class="badge">{{ badgeText(item.badge) }}</view>
            </view>
            <text>{{ item.label }}</text>
          </view>
        </view>
      </view>

      <!-- 即将开始 -->
      <view class="mcard">
        <view class="mtitle">
          <text>即将开始</text>
          <text class="more" @tap="goOrders">全部 ›</text>
        </view>

        <view v-if="loading" class="mtext">加载中…</view>

        <view v-else-if="upcoming" class="upnext" @tap="openOrder(upcoming)">
          <view class="bar"></view>
          <view class="bd">
            <text class="tt">{{ spaceName(upcoming) }}</text>
            <text v-for="(line, i) in upcomingLines" :key="i" class="dd">{{ line }}</text>
            <view class="tags">
              <text class="tag" :class="statusTag('order', orderStatus(upcoming), orderStatusText(upcoming))">
                {{ statusLabel('order', orderStatus(upcoming), orderStatusText(upcoming)) }}
              </text>
            </view>
          </view>
        </view>

        <view v-else class="mini-empty">
          <text class="ei">🗓</text>
          <text class="et">暂无即将开始的预约</text>
          <view class="btn ai" hover-class="btn-on" @tap="goVoice">语音预约一场</view>
        </view>
      </view>
    </view>

    <mp-tab-bar :current="0" />
  </view>
</template>

<script setup>
/**
 * M1 首页
 *
 * 对应原型「小程序-1 首页」。
 * 数据：GET /orders/my 取最近一场未结束的预约 + GET /messages/unread 取消息角标。
 * 未登录也能看（Mock 路由不鉴权），但两处接口都会失败，页面走空态。
 */
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { myOrders } from '@/api/orders.js'
import { refreshUnread, notifyStore } from '@/store/notify.js'
import { userStore, displayName, roleText } from '@/store/user.js'
import { statusLabel, statusTag } from '@/utils/dict.js'
import { spaceName, orderStatus, orderStatusText, orderId } from '@/utils/normalize.js'
import { formatTimeRange, formatMoney, parseDateTime } from '@/utils/format.js'
import { TABS } from '@/utils/tabs.js'

const loading = ref(true)
/** @type {import('vue').Ref<object|null>} */
const upcoming = ref(null)

const greeting = computed(() => {
  return userStore.loggedIn ? `你好，${displayName()} 👋` : '你好，访客 👋'
})

const roleLabel = computed(() => (userStore.loggedIn ? roleText() : '未登录'))

const entries = computed(() => [
  { key: 'voice', icon: '🎙', tone: '', label: '语音预约', url: '/pages/voice/record' },
  { key: 'space', icon: '📷', tone: 'g2', label: '拍照识场', url: '/pages/space/recognize' },
  { key: 'order', icon: '🗓', tone: 'g3', label: '我的预约', tab: 1 },
  { key: 'msg', icon: '🔔', tone: 'g4', label: '消息通知', tab: 3, badge: notifyStore.unreadCount },
])

/** 「即将开始」的两行副文案，缺字段就不显示该行，避免出现「｜ ｜」 */
const upcomingLines = computed(() => {
  const o = upcoming.value
  if (!o) return []
  const lines = []

  const range = formatTimeRange(o.startTime, o.endTime)
  if (range) lines.push(range)

  const devices = o.deviceNames || []
  const budget = formatMoney(o.budget)
  const parts = []
  if (devices.length) parts.push(`含${devices.length > 2 ? '多台设备' : devices.join(' + ')}`)
  if (budget) parts.push(`预算 ${budget}`)
  if (parts.length) lines.push(parts.join(' ｜ '))

  return lines
})

/** 角标超过 99 显示 99+ */
function badgeText(n) {
  return n > 99 ? '99+' : String(n)
}

/**
 * 取「最近一场还没结束的预约」。
 * 已完成 / 已取消的不算，其余按开始时间升序取第一条。
 */
function pickUpcoming(list) {
  const now = Date.now()
  const alive = list.filter((o) => {
    const label = statusLabel('order', orderStatus(o), orderStatusText(o))
    if (label === '已取消' || label === '已完成') return false
    const end = parseDateTime(o.endTime)
    return !end || end.getTime() >= now
  })
  alive.sort((a, b) => {
    const da = parseDateTime(a.startTime)
    const db = parseDateTime(b.startTime)
    return (da ? da.getTime() : 0) - (db ? db.getTime() : 0)
  })
  return alive.length ? alive[0] : null
}

async function load() {
  loading.value = true
  try {
    const { list } = await myOrders({ page: 1, pageSize: 10 })
    upcoming.value = pickUpcoming(list)
  } catch (e) {
    upcoming.value = null
  } finally {
    loading.value = false
  }
  // 角标失败不影响首页主体，store 内部已经吞掉错误
  refreshUnread()
}

onShow(load)

function go(item) {
  if (item.tab !== undefined) {
    const tab = TABS[item.tab]
    if (tab) uni.reLaunch({ url: tab.path })
    return
  }
  uni.navigateTo({ url: item.url })
}

function goVoice() {
  uni.navigateTo({ url: '/pages/voice/record' })
}

function goOrders() {
  uni.reLaunch({ url: TABS[1].path })
}

function openOrder(o) {
  const id = orderId(o)
  if (id === undefined) return
  uni.navigateTo({ url: `/pages/order/detail?orderId=${id}` })
}
</script>

<style scoped>
/* 即将开始的卡片：原型用 border-image 做渐变竖条，
   border-image 在小程序端兼容性不稳，改用实心渐变块 */
.upnext {
  display: flex;
  gap: 22rpx;
}

.upnext .bar {
  width: 6rpx;
  flex: none;
  border-radius: 6rpx;
  background: linear-gradient(180deg, #409eff, #7c5cff);
}

.upnext .bd {
  flex: 1;
  min-width: 0;
}

.upnext .tt {
  display: block;
  font-size: 27rpx;
  font-weight: 600;
  color: var(--t1);
  margin-bottom: 12rpx;
}

.upnext .dd {
  display: block;
  font-size: 24rpx;
  color: var(--t3);
  line-height: 1.8;
}

.upnext .tags {
  margin-top: 18rpx;
}

/* 快捷入口角标 */
.ic {
  position: relative;
}

.badge {
  position: absolute;
  top: -8rpx;
  right: 2rpx;
  min-width: 30rpx;
  height: 30rpx;
  padding: 0 8rpx;
  border-radius: 15rpx;
  background: var(--danger);
  color: #fff;
  font-size: 19rpx;
  line-height: 30rpx;
  text-align: center;
  border: 2rpx solid #fff;
}

/* 卡片内的轻量空态，比整页的 .empty 更紧凑 */
.mini-empty {
  text-align: center;
  padding: 30rpx 0 10rpx;
}

.mini-empty .ei {
  display: block;
  font-size: 66rpx;
  opacity: 0.35;
  margin-bottom: 16rpx;
}

.mini-empty .et {
  display: block;
  font-size: 25rpx;
  color: var(--t3);
  margin-bottom: 24rpx;
}

.mini-empty .btn {
  display: inline-block;
  padding: 16rpx 44rpx;
}
</style>
