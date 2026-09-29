<template>
  <view class="app-page">
    <mp-nav-bar title="场地一览" back />

    <view class="app-body">
      <!-- 类型筛选 -->
      <view class="seg">
        <text
          v-for="s in SEGMENTS"
          :key="s.key"
          class="sg"
          :class="{ on: seg === s.key }"
          @tap="seg = s.key"
        >{{ s.label }}</text>
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
        icon="🏢"
        text="没有符合条件的场地"
      />

      <template v-else>
        <view v-for="s in shown" :key="s.spaceId" class="mcard sp">
          <!-- 点标题区展开/收起「已占用时段」 -->
          <view class="sphead" hover-class="btn-on" :hover-stay-time="60" @tap="toggle(s)">
            <view class="spmain">
              <view class="sptop">
                <text class="spname">{{ nameOf(s) }}</text>
                <text class="tag blue">{{ spaceTypeLabel(s.spaceType) }}</text>
              </view>
              <text class="spmeta">📍 {{ s.location || '位置未登记' }}</text>
              <text class="spmeta">👥 可容纳 {{ s.capacity }} 人 · 🕘 {{ openText(s) }}</text>
            </view>
            <text class="chev">{{ openId === s.spaceId ? '▾' : '›' }}</text>
          </view>

          <!-- 展开区：这个场地未来 N 天被谁占走了哪几段 -->
          <view v-if="openId === s.spaceId" class="bk">
            <view class="bkhead">
              <text class="bkh">已占用时段</text>
              <view class="bkd">
                <text
                  v-for="d in DAY_OPTS"
                  :key="d"
                  class="bd"
                  :class="{ on: days === d }"
                  @tap.stop="setDays(d)"
                >{{ d }}天</text>
              </view>
            </view>

            <text v-if="box.loading" class="bkmsg">查询中…</text>
            <text v-else-if="box.error" class="bkmsg err">{{ box.error }}</text>
            <text v-else-if="!box.list.length" class="bkmsg ok">
              ✅ 未来 {{ days }} 天没有占用，随时可约
            </text>

            <template v-else>
              <view v-for="b in box.list" :key="b.orderId" class="bkrow">
                <view class="bkleft">
                  <text class="bktime">{{ bookingText(b) }}</text>
                  <text class="bksub">订单 #{{ b.orderId }}{{ deviceText(b) }}</text>
                </view>
                <text class="tag" :class="statusTag('order', b.orderStatus, '')">
                  {{ statusLabel('order', b.orderStatus, '') }}
                </text>
              </view>
              <text class="bkfoot">共 {{ box.list.length }} 段被占用，其余时段空闲</text>
            </template>
          </view>
        </view>

        <text class="tip">
          点任意场地可展开它的「已占用时段」；占用口径与下单判重一致（待确认 / 已确认都算占用）。
        </text>
      </template>
    </view>
  </view>
</template>

<script setup>
/**
 * 场地一览（二级页）
 *
 * 对应需求：小程序原先**没有任何地方能看全部场地的位置**，
 * 也看不到「某个场地哪些时间段已经被人订走了」。
 *
 * 数据来源（两个都已实测通过）：
 *   GET /resources/spaces                    → 全部场地（名称 / 类型 / 位置 / 容量 / 开放时段 / 预算）
 *   GET /resources/spaces/{spaceId}/booked   → 该场地未来 N 天的已占用时段（2026-09-30 新增）
 *
 * 为什么占用要单独开一个接口：
 *   /orders/my 只能看到**自己**的预约，/orders/user/{id} 是按人查，
 *   /image/analyze 回的 availableTime 语义是「剩余空档」——
 *   三者都答不了「这个场地被谁占走了哪几段」。
 *
 * 展开用的是**手风琴**而不是跳新页：场地只有 8 个，
 * 在列表里直接展开比来回跳页更快，也少一层导航状态。
 */
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { spaces as fetchSpaces, spaceBookings } from '@/api/resources.js'
import { ensureNameMaps, deviceLabel } from '@/utils/nameMap.js'
import { statusLabel, statusTag, spaceTypeLabel } from '@/utils/dict.js'
import {
  parseDateTime,
  formatTime,
  formatMonthDay,
  formatWeekday,
} from '@/utils/format.js'
import { userStore } from '@/store/user.js'

const SEGMENTS = [
  { key: 'all', label: '全部' },
  { key: 1, label: '会议室' },
  { key: 2, label: '展厅' },
  { key: 3, label: '多功能厅' },
  { key: 4, label: '户外场地' },
]

/** 可切换的查询天数 */
const DAY_OPTS = [7, 30]

const list = ref([])
const loading = ref(true)
const error = ref('')
const seg = ref('all')

/** 当前展开的场地 id；null 表示全部收起 */
const openId = ref(null)
/** 查询天数。种子数据里的预约分布在 09-30 ~ 10-15，故默认给 30 天 */
const days = ref(30)
/** spaceId -> { loading, error, list } */
const cache = ref({})

const shown = computed(() => {
  if (seg.value === 'all') return list.value
  return list.value.filter((s) => Number(s.spaceType) === seg.value)
})

/** 当前展开场地的查询状态；没展开时给一个空壳，模板不用到处判空 */
const box = computed(() => {
  const id = openId.value
  if (id === null) return { loading: false, error: '', list: [] }
  return cache.value[id] || { loading: false, error: '', list: [] }
})

function nameOf(s) {
  return s.spaceName || ('场地 #' + s.spaceId)
}

/** 开放时段：后端给 HH:mm:ss，展示到分钟即可；没配置则写「不限」 */
function openText(s) {
  const a = hhmm(s.openStartTime)
  const b = hhmm(s.openEndTime)
  return a + ' ~ ' + b
}

function hhmm(t) {
  const v = String(t || '')
  return v ? v.slice(0, 5) : '不限'
}

/** 占用时段文案。跨天的订单要把结束日期也带上，否则看不出占了两天 */
function bookingText(b) {
  const s = parseDateTime(b.startTime)
  const e = parseDateTime(b.endTime)
  if (!s || !e) return String(b.startTime || '—')
  if (s.toDateString() === e.toDateString()) {
    return formatMonthDay(s) + ' ' + formatWeekday(s) + ' ' + formatTime(s) + ' - ' + formatTime(e)
  }
  return formatMonthDay(s) + ' ' + formatTime(s) + ' - ' + formatMonthDay(e) + ' ' + formatTime(e)
}

function deviceText(b) {
  const d = deviceLabel(b.deviceIds)
  return d && d !== '无' ? ' · ' + d : ''
}

onLoad(() => {
  // 占用明细里只有 deviceIds，设备名要靠资源映射补
  ensureNameMaps()
  load()
})

async function load() {
  loading.value = true
  try {
    const res = await fetchSpaces()
    list.value = res.list || []
    error.value = ''
  } catch (e) {
    list.value = []
    error.value = (e && e.message) || '场地列表加载失败'
  } finally {
    loading.value = false
  }
}

function toggle(s) {
  const id = s.spaceId
  if (openId.value === id) {
    openId.value = null
    return
  }
  openId.value = id
  loadBookings(id)
}

async function loadBookings(id) {
  if (!userStore.loggedIn) {
    // 占用接口要鉴权（会暴露他人的预约时段），未登录时如实说明而不是装作「没人订」
    setBox(id, { loading: false, error: '登录后可查看占用时段', list: [] })
    return
  }

  setBox(id, { loading: true, error: '', list: [] })
  try {
    const res = await spaceBookings(id, days.value)
    setBox(id, { loading: false, error: '', list: (res && res.bookings) || [] })
  } catch (e) {
    setBox(id, {
      loading: false,
      error: (e && e.message) || '占用时段查询失败',
      list: [],
    })
  }
}

function setBox(id, val) {
  // 整体替换而不是改属性：cache 是 ref，直接改嵌套属性不会触发重渲染
  cache.value = Object.assign({}, cache.value, { [id]: val })
}

/** 切换天数：所有缓存作废，重新查当前展开的那个 */
function setDays(d) {
  if (days.value === d) return
  days.value = d
  cache.value = {}
  if (openId.value !== null) loadBookings(openId.value)
}
</script>

<style scoped>
/* 类型筛选 */
.seg {
  display: flex;
  flex-wrap: wrap;
  gap: 14rpx;
  margin-bottom: 22rpx;
}

.sg {
  font-size: 24rpx;
  padding: 12rpx 26rpx;
  border-radius: 28rpx;
  color: var(--t2);
  background: #fff;
  border: 1px solid var(--bd-l);
}

.sg.on {
  color: #fff;
  background: var(--primary);
  border-color: var(--primary);
}

/* 场地卡 */
.sphead {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.spmain {
  flex: 1;
  min-width: 0;
}

.sptop {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-bottom: 12rpx;
}

.spname {
  font-size: 29rpx;
  font-weight: 600;
  color: var(--t1);
}

.spmeta {
  display: block;
  font-size: 24rpx;
  color: var(--t3);
  line-height: 1.8;
}

.chev {
  flex: none;
  font-size: 34rpx;
  color: #c6ced9;
}

/* 展开区 */
.bk {
  margin-top: 22rpx;
  padding-top: 22rpx;
  border-top: 1px solid #f0f3f8;
}

.bkhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.bkh {
  font-size: 25rpx;
  font-weight: 600;
  color: var(--t1);
}

.bkd {
  display: flex;
  gap: 10rpx;
}

.bd {
  font-size: 22rpx;
  padding: 6rpx 18rpx;
  border-radius: 20rpx;
  color: var(--t3);
  background: #f4f6fa;
}

.bd.on {
  color: var(--primary);
  background: #eef5ff;
  border: 1px solid var(--ai-line);
}

.bkmsg {
  display: block;
  font-size: 24rpx;
  color: var(--t3);
  padding: 10rpx 0;
  line-height: 1.8;
}

.bkmsg.err {
  color: var(--danger);
}

.bkmsg.ok {
  color: var(--success);
}

.bkrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
  padding: 14rpx 0;
}

.bkrow + .bkrow {
  border-top: 1px solid #f6f8fb;
}

.bkleft {
  flex: 1;
  min-width: 0;
}

.bktime {
  display: block;
  font-size: 25rpx;
  color: var(--t1);
  font-weight: 600;
}

.bksub {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  margin-top: 6rpx;
}

.bkfoot {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  margin-top: 12rpx;
}

.tip {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  padding: 26rpx 8rpx 10rpx;
}
</style>
