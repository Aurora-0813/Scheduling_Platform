<template>
  <view class="app-page">
    <mp-nav-bar title="AI 智能巡检" />

    <view class="app-body">
      <!-- 入口：取景框视觉来自原型 M5 -->
      <view class="imgbox entry" @tap="goCapture">
        <view class="cam">
          <text class="big">📷</text>
          <text>拍下设备，AI 自动识别状态并生成工单</text>
        </view>
        <!-- 四个角标必须排在最前：theme.css 用 :nth-child(1..4) 定位四角，
             标签条插在中间会把序号错位 -->
        <view class="bbox">
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <text class="lbl">对准设备</text>
        </view>
        <view class="scanline"></view>
      </view>

      <view class="btn ai block" hover-class="btn-on" :hover-stay-time="60" @tap="goCapture">
        开始拍照巡检
      </view>

      <!-- 工单列表 -->
      <view class="mcard sec">
        <view class="mtitle">
          <text>维修工单</text>
          <text class="more" @tap="load">{{ loading ? '刷新中…' : '刷新' }}</text>
        </view>

        <text v-if="loading" class="mtext">加载中…</text>

        <!-- 未登录不是「没有工单」，单独一支（放在空态之前） -->
        <view v-else-if="!userStore.loggedIn" class="mini-empty">
          <text class="ei">🔑</text>
          <text class="et">登录后查看维修工单</text>
        </view>

        <view v-else-if="!tickets.length" class="mini-empty">
          <text class="ei">🧰</text>
          <text class="et">暂无维修工单，设备一切正常</text>
        </view>

        <view v-else>
          <view
            v-for="(t, i) in tickets"
            :key="t.id"
            class="ticket"
            :class="{ sep: i > 0 }"
          >
            <view class="thead">
              <text class="tname">{{ t.deviceName || '未知设备' }}</text>
              <text class="tag" :class="statusTag('ticket', t.status, t.statusText)">
                {{ statusLabel('ticket', t.status, t.statusText) }}
              </text>
            </view>

            <!--
              ⚠️ 2026-09-30：这一行原先读的是 t.spaceName，而 /tickets/list 的
              TicketItem **只有 spaceId**（没有 spaceName），所以永远显示「未关联空间」。
              改为查一次资源表建映射后取名字（见 utils/nameMap.js）。
            -->
            <text class="tno">工单 #{{ t.id }} · {{ spaceLabel(t.spaceId) }}</text>

            <text v-if="t.report" class="tdesc">{{ t.report }}</text>
            <!--
              ⚠️ 2026-09-30 删掉了「维修建议」一行：原代码读 t.repairSuggestion，
              但该字段只存在于 /inspect/submit 的返回（InspectSubmitData），
              **不在 TicketItem 里**，所以 v-if 恒为 false、永远不渲染。
              工单里能反映 AI 结论的字段是 report（来自关联的巡检记录），上面那行已经覆盖。
            -->

            <view class="tfoot">
              <!--
                ⚠️ 2026-09-30 删掉了「处理人」一行：TicketItem 里**没有** handlerName
                （handlerId 只在 PUT /tickets/{id}/status 的响应里），
                所以原先恒显示「尚未派单」—— 连已完成的工单也这么说，是句错话。
                要显示处理人得后端在列表里补字段，本轮不自行发明。
              -->
              <view
                v-if="canFinish(t)"
                class="btn ghost tiny"
                hover-class="btn-on"
                :hover-stay-time="60"
                @tap.stop="finish(t)"
              >标记完成</view>
            </view>
          </view>
        </view>
      </view>
    </view>

    <mp-tab-bar :current="2" />
  </view>
</template>

<script setup>
/**
 * AI 智能巡检（tab 3）
 *
 * 入口页：拍照巡检 + 维修工单列表。
 * 数据：GET /tickets/list；状态流转 PUT /tickets/{id}/status。
 *
 * 注意：本模块真实后端尚未实现，目前命中 /api/v1/mock/tickets/*。
 * handlerId 由后端从 JWT 解析，前端不传（§5.1）。
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { tickets as fetchTickets, updateTicketStatus } from '@/api/inspect.js'
import { userStore } from '@/store/user.js'
import { statusLabel, statusTag } from '@/utils/dict.js'
import { ensureNameMaps, spaceLabel } from '@/utils/nameMap.js'
import { toast, toastOk, confirm } from '@/utils/toast.js'

const tickets = ref([])
const loading = ref(true)

async function load() {
  // ⚠️ **2026-09-30：未登录不发鉴权请求。**
  // 原先 onShow 无条件拉工单，未登录时拿到 40101 被强制弹登录页，
  // 页面自己的「未登录」分支永远显示不出来。
  if (!userStore.loggedIn) {
    tickets.value = []
    loading.value = false
    return
  }
  loading.value = true
  try {
    const res = await fetchTickets({ page: 1, pageSize: 50 })
    tickets.value = res.list
  } catch (e) {
    tickets.value = []
    toast(e.message || '工单加载失败')
  } finally {
    loading.value = false
  }
}

// 工单列表只给 spaceId，名称要靠资源表映射补（失败不影响列表本身）
onShow(() => {
  ensureNameMaps()
  load()
})

/** 已完成 / 已取消的不再显示操作入口 */
function canFinish(t) {
  const label = statusLabel('ticket', t.status, t.statusText)
  return label === '待处理' || label === '处理中'
}

async function finish(t) {
  const ok = await confirm({
    content: `确认工单 #${t.id}（${t.deviceName || '设备'}）已处理完成？`,
    title: '标记完成',
    confirmText: '确认完成',
  })
  if (!ok) return

  try {
    await updateTicketStatus(t.id, 3)
    toastOk('工单已完成')
    load()
  } catch (e) {
    toast(e.message || '操作失败')
  }
}

function goCapture() {
  uni.navigateTo({ url: '/pages/inspect/capture' })
}
</script>

<style scoped>
.entry {
  height: 320rpx;
}

.sec {
  margin-top: 24rpx;
}

.mini-empty {
  text-align: center;
  padding: 40rpx 0;
}

.mini-empty .ei {
  display: block;
  font-size: 66rpx;
  opacity: 0.35;
  margin-bottom: 16rpx;
}

.mini-empty .et {
  font-size: 25rpx;
  color: var(--t3);
}

.ticket.sep {
  margin-top: 26rpx;
  padding-top: 26rpx;
  border-top: 1px solid #f5f7fa;
}

.thead {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-bottom: 8rpx;
}

.tname {
  flex: 1;
  min-width: 0;
  font-size: 27rpx;
  font-weight: 600;
  color: var(--t1);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.tno {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  margin-bottom: 12rpx;
}

.tdesc {
  display: block;
  font-size: 24rpx;
  color: var(--t2);
  line-height: 1.7;
}

.tdesc.sug {
  margin-top: 8rpx;
  color: #c47b16;
}

.tfoot {
  display: flex;
  align-items: center;
  margin-top: 20rpx;
}

.who {
  flex: 1;
  font-size: 23rpx;
  color: var(--t3);
}

.btn.tiny {
  padding: 10rpx 26rpx;
  font-size: 23rpx;
}
</style>
