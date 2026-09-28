<template>
  <view class="app-page">
    <mp-nav-bar title="消息通知" right="全部已读" @right="readAll" />

    <view class="app-body">
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
        v-else-if="!list.length"
        icon="🔔"
        text="没有未读消息"
        action-text="刷新"
        @action="load"
      />

      <view v-else>
        <view
          v-for="m in list"
          :key="m.id"
          class="msg"
          :class="{ unread: !m.isRead }"
          @tap="openMsg(m)"
        >
          <view class="h">
            <text>{{ notifyIcon(iconKey(m)) }} {{ m.title || '通知' }}</text>
            <text class="t">{{ relativeTime(m.createTime) }}</text>
          </view>
          <text class="txt">{{ m.content }}</text>
        </view>

        <!-- 契约缺口提示：后端只有「未读」接口，没有全部消息接口，也没有标记已读 -->
        <text class="gap">
          当前仅展示未读消息。「全部已读」只改本机状态，暂不落库——
          后端尚未提供 GET /messages/list 与标记已读接口。
        </text>
      </view>
    </view>

    <mp-tab-bar :current="3" />
  </view>
</template>

<script setup>
/**
 * M6 消息通知（tab 4）
 *
 * 对应原型「小程序-6 智能消息通知」。
 *
 * ⚠️ 两处契约缺口（见 api/messages.js）：
 *   1. 只有 GET /messages/unread，本页只能展示未读消息；
 *   2. 没有标记已读接口，「全部已读」仅改前端状态，刷新后会复原。
 * 页面底部有一行说明，避免演示时被误认为 bug。
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { unread } from '@/api/messages.js'
import { notifyStore, markAllReadLocal } from '@/store/notify.js'
import { notifyIcon } from '@/utils/dict.js'
import { relativeTime } from '@/utils/format.js'
import { toastOk, toast } from '@/utils/toast.js'

const list = ref([])
const loading = ref(true)
const error = ref('')

/**
 * 通知类型既可能是整型（契约 notifyType 1-3），
 * 也可能是当前 Mock 直接给的中文串，notifyIcon 两种都认。
 */
function iconKey(m) {
  return m.notifyType !== undefined && m.notifyType !== null ? m.notifyType : m.title
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await unread()
    list.value = res.list
    notifyStore.list = res.list
    notifyStore.unreadCount = res.total || res.list.length
  } catch (e) {
    error.value = e.message || '消息加载失败'
    list.value = []
  } finally {
    loading.value = false
  }
}

onShow(load)

function readAll() {
  const unreadCount = list.value.filter((m) => !m.isRead).length
  if (!unreadCount) {
    toast('没有未读消息')
    return
  }
  markAllReadLocal()
  // 本页的 list 是独立副本，同步一次才能看到左侧色条消失
  list.value = list.value.map((m) => ({ ...m, isRead: true }))
  toastOk('已全部标为已读')
}

function openMsg(m) {
  // 后端没有消息详情页接口，详情即卡片正文，这里只做已读的视觉反馈
  if (!m.isRead) {
    m.isRead = true
    const left = list.value.filter((x) => !x.isRead).length
    notifyStore.unreadCount = left
  }
}
</script>

<style scoped>
.gap {
  display: block;
  margin-top: 26rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  text-align: center;
  padding: 0 20rpx;
}
</style>
