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

        <template v-else-if="shownUpcoming.length">
          <!--
            默认最多 3 条（PAGE_SIZE）。超过这个高度就在下面的 scroll-view 里滑动，
            而不是像原来那样「只取第一条、其余全部丢掉」。
            滚动区高度按屏幕高度算（见 scrollMaxH），小屏少占位、大屏多显示。
          -->
          <scroll-view
            scroll-y
            class="upscroll"
            :style="{ maxHeight: scrollMaxH + 'px' }"
            :show-scrollbar="false"
          >
            <view
              v-for="(o, i) in shownUpcoming"
              :key="orderKey(o, i)"
              class="upnext"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap="openOrder(o)"
            >
              <view class="bar"></view>
              <view class="bd">
                <!-- /orders/my 只给 spaceId，名称靠 nameMap 补（原先读 spaceName 恒为空） -->
                <text class="tt">{{ spaceLabel(o.spaceId) }}</text>
                <text v-for="(line, li) in linesOf(o)" :key="li" class="dd">{{ line }}</text>
                <view class="tags">
                  <text class="tag" :class="statusTag('order', orderStatus(o), orderStatusText(o))">
                    {{ statusLabel('order', orderStatus(o), orderStatusText(o)) }}
                  </text>
                </view>
              </view>
            </view>
          </scroll-view>

          <view
            v-if="hasMoreUpcoming"
            class="upmore"
            hover-class="btn-on"
            :hover-stay-time="60"
            @tap="loadMoreUpcoming"
          >加载更多（还有 {{ moreCount }} 条）</view>
        </template>

        <!--
          ⚠️ 2026-09-30：原来只有一个空态分支，于是「接口挂了」和「确实没有预约」
          长得一模一样 —— 401/500/断网都会被显示成「暂无即将开始的预约」，
          把故障谎报成用户自己的状态。现在拆成两个分支，如实说明。
        -->
        <!-- 未登录不是错误，单独一支（放在 loadError 之前，否则会被当成失败） -->
        <view v-else-if="!userStore.loggedIn" class="mini-empty">
          <text class="ei">🔑</text>
          <text class="et">登录后查看你的预约</text>
          <view class="btn ai" hover-class="btn-on" @tap="goLogin">去登录</view>
        </view>

        <view v-else-if="loadError" class="mini-empty">
          <text class="ei">⚠️</text>
          <text class="et">{{ loadError }}</text>
          <view class="btn ghost" hover-class="btn-on" @tap="load">重试</view>
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
import { ensureNameMaps, deviceLabel, spaceLabel } from '@/utils/nameMap.js'
import { orderStatus, orderStatusText, orderId } from '@/utils/normalize.js'
import { formatTimeRange, parseDateTime } from '@/utils/format.js'
import { TABS } from '@/utils/tabs.js'

const loading = ref(true)
/** 所有「还没结束」的预约，按开始时间升序（**不是**只取第一条） */
const upcomingList = ref([])
/** 加载失败的原因。与「确实没有预约」必须分开 —— 否则会把故障显示成空态。 */
const loadError = ref('')

/** 默认最多显示 3 条；屏幕放不下时由 .upscroll 负责滑动 */
const PAGE_SIZE = 3
const visibleCount = ref(PAGE_SIZE)
/** 滚动区高度（px），按屏幕高度算，夹在合理区间内 */
const scrollMaxH = ref(420)

const greeting = computed(() => {
  return userStore.loggedIn ? `你好，${displayName()} 👋` : '你好，访客 👋'
})

const roleLabel = computed(() => (userStore.loggedIn ? roleText() : '未登录'))

const shownUpcoming = computed(() => upcomingList.value.slice(0, visibleCount.value))
const hasMoreUpcoming = computed(() => upcomingList.value.length > visibleCount.value)
const moreCount = computed(() => Math.max(0, upcomingList.value.length - visibleCount.value))

function loadMoreUpcoming() {
  visibleCount.value += PAGE_SIZE
}

/** v-for 的 key：优先真实订单号，退化成下标 */
function orderKey(o, i) {
  const id = orderId(o)
  return id === undefined ? 'i' + i : 'o' + id
}

const entries = computed(() => [
  { key: 'voice', icon: '🎙', tone: '', label: '语音预约', url: '/pages/voice/record' },
  { key: 'space', icon: '📷', tone: 'g2', label: '拍照识场', url: '/pages/space/recognize' },
  { key: 'venues', icon: '🏢', tone: 'g5', label: '场地一览', url: '/pages/space/list' },
  { key: 'order', icon: '🗓', tone: 'g3', label: '我的预约', tab: 1 },
  { key: 'msg', icon: '🔔', tone: 'g4', label: '消息通知', tab: 3, badge: notifyStore.unreadCount },
])

/** 「即将开始」某一条的副文案，缺字段就不显示该行，避免出现「｜ ｜」 */
function linesOf(o) {
  if (!o) return []
  const lines = []

  const range = formatTimeRange(o.startTime, o.endTime)
  if (range) lines.push(range)

  // ⚠️ 2026-09-30：原先读 o.deviceNames 与 o.budget —— 这两个字段在 /orders/my
  // 里**都不存在**（订单没有携带场地/设备的冗余名，也没有预算列），
  // 所以「含 N 台设备 ｜ 预算 ¥x」这一行**永远不会出现**。
  // 设备名现在按 deviceIds 查真名；预算后端确实没有，故不再显示（不编）。
  const devices = deviceLabel(o.deviceIds)
  if (devices && devices !== '无') lines.push('含' + devices)

  return lines
}

/** 角标超过 99 显示 99+ */
function badgeText(n) {
  return n > 99 ? '99+' : String(n)
}

/**
 * 取所有「还没结束的预约」。
 * 已完成 / 已取消的不算，其余按开始时间升序**全部返回**。
 *
 * ⚠️ 2026-09-30：原来这里只 `return alive[0]`，于是首页永远只有 1 张卡，
 * 其余预约在界面上**完全看不到**（用户反馈「查出会被隐藏」）。
 * 现在把整段返回，由 shownUpcoming 按 PAGE_SIZE 切片。
 */
function pickUpcomingList(list) {
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
  return alive
}

async function load() {
  loading.value = true
  try {
    // ⚠️ **2026-09-30：未登录不要发鉴权请求。**
    // 原先 onShow 无条件调 myOrders()，未登录时拿到 40101，
    // 再被 request.js 的 AUTH_FAIL_CODES 分支强制弹到登录页 ——
    // 于是下面模板里那个「登录后可查看」的分支永远显示不出来，
    // 而且每进一次首页就白打一轮 401（开发者工具里刷屏）。
    // 现在 request.js 会提前抛 kind='NO_TOKEN'，这里直接短路更省一次判定。
    if (!userStore.loggedIn) {
      upcomingList.value = []
      loadError.value = ''
      return
    }
    // ⚠️ 后端 /orders/my **不支持分页**（只认 status），pageSize 是被静默忽略的，
    // 这里保留参数只是历史遗留；真要做分页得后端支持。
    const { list } = await myOrders()
    upcomingList.value = pickUpcomingList(list)
    // 每次重新加载都回到默认的 3 条，避免上一轮的「加载更多」状态残留
    visibleCount.value = PAGE_SIZE
    loadError.value = ''
  } catch (e) {
    // ⚠️ 2026-09-30：原先这里只把 upcoming 置 null，与「确实没有预约」
    // **完全不可区分** —— 401/500/断网都会显示成「暂无即将开始的预约」，
    // 把「取不到数据」谎报成「你没有预约」。现在分开记，模板里分别渲染。
    upcomingList.value = []
    loadError.value = (e && e.message) || '预约加载失败'
  } finally {
    loading.value = false
  }
  // 角标失败不影响首页主体，store 内部已经吞掉错误。
  // 未登录同样不必打这个接口（它要鉴权）—— 上面的短路分支已经 return。
  if (userStore.loggedIn) refreshUnread()
}

onShow(() => {
  // 订单只给 spaceId / deviceIds，名称要靠资源表映射补
  ensureNameMaps()
  measureScroll()
  load()
})

/**
 * 「即将开始」滚动区高度：按屏幕高度取约 40%，夹在 300~620px 之间。
 * 大屏能多露一点，小屏不至于把首页整屏吃掉；条数上限仍由 PAGE_SIZE 控制。
 */
function measureScroll() {
  try {
    const info =
      typeof uni.getWindowInfo === 'function' ? uni.getWindowInfo() : uni.getSystemInfoSync()
    const h = (info && info.windowHeight) || 0
    if (h > 0) scrollMaxH.value = Math.min(620, Math.max(300, Math.round(h * 0.4)))
  } catch (e) {
    // 取不到就用默认值，不影响功能
  }
}

function go(item) {
  if (item.tab !== undefined) {
    const tab = TABS[item.tab]
    if (tab) uni.reLaunch({ url: tab.path })
    return
  }
  uni.navigateTo({ url: item.url })
}

function goLogin() {
  uni.navigateTo({ url: '/pages/login/index' })
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
/* 快捷入口从 4 个变成 5 个：把每格压到 20% 让它们排成一行，
   否则第 5 个会孤零零换到第二行、左边空一大块。
   本文件是 scoped，选择器会带上 data-v 属性，特异性高于 theme.css 的 .grid4 .cell */
.grid4 .cell {
  width: 20%;
}

/* 第 5 个入口的图标底色（theme.css 只定义了 g2/g3/g4） */
.grid4 .cell .ic.g5 {
  background: #eef8f1;
}

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

/* 「即将开始」滚动区：超过 3 条时在这里滑动，而不是把后面的整段吞掉。
   真实高度由 :style 按屏幕高度覆盖，这里只兜底。 */
.upscroll {
  max-height: 420px;
}

/* 多张卡之间加分隔线，滑动时能看清是两条不同的预约 */
.upscroll .upnext + .upnext {
  margin-top: 24rpx;
  padding-top: 24rpx;
  border-top: 1px solid #f0f3f8;
}

/* 底部「加载更多」，点击后一次追加 PAGE_SIZE 条 */
.upmore {
  margin-top: 24rpx;
  height: 76rpx;
  line-height: 76rpx;
  text-align: center;
  font-size: 25rpx;
  color: var(--primary);
  background: #f5f9ff;
  border: 1px solid var(--ai-line);
  border-radius: 18rpx;
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
