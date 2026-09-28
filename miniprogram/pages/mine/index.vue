<template>
  <view class="app-page">
    <mp-nav-bar big title="我的" :right="userStore.loggedIn ? roleText() : ''" />

    <view class="app-body">
      <!-- 身份卡 -->
      <view class="mcard prof">
        <view class="avatar">{{ avatarEmoji }}</view>
        <view class="pinfo">
          <text class="pname">{{ userStore.loggedIn ? displayName() : '未登录' }}</text>
          <text class="prole">
            {{ userStore.loggedIn ? `账号 ID：${userId}` : '登录后可查看预约与工单' }}
          </text>
        </view>
        <view
          v-if="!userStore.loggedIn"
          class="btn"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="goLogin"
        >去登录</view>
      </view>

      <!-- 数据概览 -->
      <view class="stats">
        <view v-for="s in stats" :key="s.key" class="stat" @tap="go(s)">
          <text class="num">{{ s.value }}</text>
          <text class="lb">{{ s.label }}</text>
        </view>
      </view>

      <!-- 功能入口 -->
      <view class="mcard">
        <view class="mtitle">常用功能</view>
        <view
          v-for="(m, i) in menus"
          :key="m.key"
          class="mrow"
          :class="{ sep: i > 0 }"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="go(m)"
        >
          <text class="mi">{{ m.icon }}</text>
          <text class="ml">{{ m.label }}</text>
          <text v-if="m.badge > 0" class="mbadge">{{ m.badge }}</text>
          <text class="ma">›</text>
        </view>
      </view>

      <!-- 关于 -->
      <view class="mcard">
        <view class="mbrow">
          <text class="k">版本</text>
          <text class="v">小程序端 v1.0.0</text>
        </view>
        <view class="mbrow">
          <text class="k">后端</text>
          <text class="v mono">{{ apiModeText }}</text>
        </view>
      </view>

      <view
        v-if="userStore.loggedIn"
        class="btn ghost block out"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="askLogout"
      >退出登录</view>
    </view>

    <mp-tab-bar :current="4" />
  </view>
</template>

<script setup>
/**
 * 我的（tab 5）
 *
 * 原型 M1-M6 没有这一屏，视觉沿用同一套设计语言。
 * 聚合展示身份、数据概览与功能入口。
 */
import { ref, computed } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { userStore, displayName, roleText, doLogout } from '@/store/user.js'
import { notifyStore, refreshUnread } from '@/store/notify.js'
import { myOrders } from '@/api/orders.js'
import { tickets as fetchTickets } from '@/api/inspect.js'
import { API_MODE } from '@/config/index.js'
import { toastOk, confirm } from '@/utils/toast.js'
import { TABS } from '@/utils/tabs.js'

const orderCount = ref(0)
const ticketCount = ref(0)

const userId = computed(() => {
  if (!userStore.info) return '—'
  return userStore.info.id === undefined || userStore.info.id === null
    ? '—'
    : String(userStore.info.id)
})

/** 没有头像资源，用角色对应的 emoji 代替，避免引入图片 */
const avatarEmoji = computed(() => {
  if (!userStore.loggedIn) return '👤'
  return userStore.role === 'admin' ? '🧑💼' : userStore.role === 'resource_admin' ? '🧰' : '🙂'
})

const stats = computed(() => [
  { key: 'order', label: '我的预约', value: orderCount.value, tab: 1 },
  { key: 'ticket', label: '维修工单', value: ticketCount.value, tab: 2 },
  { key: 'msg', label: '未读消息', value: notifyStore.unreadCount, tab: 3 },
])

const menus = computed(() => [
  { key: 'voice', icon: '🎙', label: '语音预约', url: '/pages/voice/record' },
  { key: 'space', icon: '📷', label: '拍照识场', url: '/pages/space/recognize' },
  { key: 'capture', icon: '🧰', label: '拍照巡检', url: '/pages/inspect/capture' },
  { key: 'order', icon: '🗓', label: '我的预约', tab: 1 },
  { key: 'msg', icon: '🔔', label: '消息通知', tab: 3, badge: notifyStore.unreadCount },
])

const apiModeText = computed(() =>
  API_MODE === 'mock' ? 'Mock 路由（/api/v1/mock/*）' : '真实接口（/api/v1/*）'
)

async function load() {
  // 未登录时接口会失败，静默处理，保持 0
  try {
    const res = await myOrders({ page: 1, pageSize: 1 })
    orderCount.value = res.total
  } catch (e) {
    orderCount.value = 0
  }
  try {
    const res = await fetchTickets({ page: 1, pageSize: 1 })
    ticketCount.value = res.total
  } catch (e) {
    ticketCount.value = 0
  }
  refreshUnread()
}

onShow(load)

function go(item) {
  if (item.tab !== undefined) {
    const tab = TABS[item.tab]
    if (tab) uni.reLaunch({ url: tab.path })
    return
  }
  if (item.url) uni.navigateTo({ url: item.url })
}

function goLogin() {
  uni.navigateTo({ url: '/pages/login/index' })
}

async function askLogout() {
  const ok = await confirm({
    content: '退出后需要重新登录才能查看预约与工单。',
    title: '退出登录',
    confirmText: '退出',
    confirmColor: '#F56C6C',
  })
  if (!ok) return

  await doLogout()
  toastOk('已退出登录')
  orderCount.value = 0
  ticketCount.value = 0
  notifyStore.list = []
  notifyStore.unreadCount = 0
}
</script>

<style scoped>
.prof {
  display: flex;
  align-items: center;
  gap: 24rpx;
}

.avatar {
  width: 108rpx;
  height: 108rpx;
  flex: none;
  border-radius: 50%;
  font-size: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eef5ff, #f3efff);
  border: 1px solid var(--ai-line);
}

.pinfo {
  flex: 1;
  min-width: 0;
}

.pname {
  display: block;
  font-size: 31rpx;
  font-weight: 600;
  color: var(--t1);
  margin-bottom: 8rpx;
}

.prole {
  display: block;
  font-size: 23rpx;
  color: var(--t3);
}

.prof .btn {
  flex: none;
  padding: 14rpx 30rpx;
  font-size: 24rpx;
}

.stats {
  display: flex;
  gap: 20rpx;
  margin-bottom: 22rpx;
}

.stat {
  flex: 1;
  background: #fff;
  border: 1px solid #f0f3f8;
  border-radius: 24rpx;
  padding: 26rpx 0;
  text-align: center;
}

.stat .num {
  display: block;
  font-size: 40rpx;
  font-weight: 700;
  color: var(--primary);
  line-height: 1.2;
}

.stat .lb {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  margin-top: 8rpx;
}

.mrow {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 26rpx 0;
}

.mrow.sep {
  border-top: 1px solid #f5f7fa;
}

.mi {
  font-size: 34rpx;
  flex: none;
}

.ml {
  flex: 1;
  font-size: 26rpx;
  color: var(--t1);
}

.mbadge {
  min-width: 34rpx;
  height: 34rpx;
  padding: 0 10rpx;
  border-radius: 17rpx;
  background: var(--danger);
  color: #fff;
  font-size: 20rpx;
  line-height: 34rpx;
  text-align: center;
  flex: none;
}

.ma {
  font-size: 34rpx;
  color: #c6ced9;
  flex: none;
}

.mono {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 23rpx;
  color: var(--t3);
}

.out {
  margin-top: 8rpx;
  color: var(--t3);
}
</style>
