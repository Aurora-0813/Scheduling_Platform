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

      <!-- 未登录不是「没有消息」，单独一支（放在空态之前） -->
      <mp-empty
        v-else-if="!userStore.loggedIn"
        icon="🔑"
        text="登录后查看消息通知"
        action-text="去登录"
        @action="goLogin"
      />

      <mp-empty
        v-else-if="!list.length"
        icon="🔔"
        text="暂无消息"
        action-text="刷新"
        @action="load"
      />

      <view v-else>
        <view
          v-for="m in list"
          :key="m.messageId"
          class="msg"
          :class="{ unread: !m.isRead }"
          @tap="openMsg(m)"
        >
          <view class="h">
            <text>{{ notifyIcon(iconKey(m)) }} {{ m.title || '通知' }}</text>
            <text class="t">{{ relativeTime(m.createTime) }}</text>
          </view>
          <!-- user-select：AI 生成的通知正文通常较长，允许长按复制 -->
          <text class="txt" :user-select="true">{{ m.content }}</text>
        </view>

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
 * ⚠️ **2026-09-30 修正：这里原先声称的两处「契约缺口」都是假的。**
 *   旧注释写：「只有 GET /messages/unread，本页只能展示未读消息」
 *             「没有标记已读接口，全部已读仅改前端状态，刷新后会复原」
 *   事实：`GET /messages` / `PUT /messages/{id}/read` / `PUT /messages/read-all`
 *   **后端一直都有**（backend/app/api/messages.py）。照着一句错话，
 *   页面被实现成「只能看未读、已读不落库」，那段假说明还被渲染给用户看。
 *   现在按真实接口重写。
 *
 * 两个真实存在的字段陷阱（详见 api/messages.js）：
 *   · `/messages/unread` 只返回 `{count}`，**不能当列表用** —— 列表走 `/messages`
 *   · 列表项主键是 `messageId`，不是 `id`
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { list as fetchMessages, read, readAll as readAllApi } from '@/api/messages.js'
import { notifyStore } from '@/store/notify.js'
import { userStore } from '@/store/user.js'
import { notifyIcon } from '@/utils/dict.js'
import { relativeTime } from '@/utils/format.js'
import { toastOk, toast } from '@/utils/toast.js'

const list = ref([])
const loading = ref(true)
const error = ref('')

/**
 * 通知类型既可能是整型（契约 notifyType 1-3），也可能是字符串，
 * notifyIcon 两种都认。
 */
function iconKey(m) {
  return m.notifyType !== undefined && m.notifyType !== null ? m.notifyType : m.title
}

/** 未读数由列表现算，不再依赖 /messages/unread（那是另一个接口，只给计数） */
function syncUnreadCount() {
  notifyStore.unreadCount = list.value.filter((m) => !m.isRead).length
}

async function load() {
  // ⚠️ **2026-09-30：未登录不发鉴权请求。**
  // 原先 onShow 无条件拉消息，未登录时拿到 40101 被强制弹到登录页 ——
  // 页面自己的「未登录」分支永远显示不出来，每进一次还白打一轮 401。
  if (!userStore.loggedIn) {
    list.value = []
    error.value = ''
    loading.value = false
    return
  }
  loading.value = true
  error.value = ''
  try {
    // ⚠️ 必须用 list()：原先用的 unread() 只返回 {count}，
    // 经 listOf() 解出来**恒为空数组**，于是真实后端下这一页永远显示「没有未读消息」，
    // 而首页角标却显示真实未读数 —— 自相矛盾。
    const res = await fetchMessages({ skip: 0, limit: 50 })
    list.value = res.list
    notifyStore.list = res.list
    syncUnreadCount()
  } catch (e) {
    error.value = e.message || '消息加载失败'
    list.value = []
  } finally {
    loading.value = false
  }
}

function goLogin() {
  uni.navigateTo({ url: '/pages/login/index' })
}

onShow(load)

async function readAll() {
  const unreadCount = list.value.filter((m) => !m.isRead).length
  if (!unreadCount) {
    toast('没有未读消息')
    return
  }
  try {
    await readAllApi()
  } catch (e) {
    // 落库失败**不能谎报成功** —— 刷新一下让界面回到真实状态
    toast(e.message || '标记失败，请重试')
    await load()
    return
  }
  list.value = list.value.map((m) => ({ ...m, isRead: true }))
  syncUnreadCount()
  toastOk('已全部标为已读')
}

async function openMsg(m) {
  if (m.isRead) return
  try {
    await read(m.messageId)
  } catch (e) {
    // 后端对「不存在」与「不是本人的消息」都返回 404（刻意不区分）
    toast(e.message || '标记已读失败')
    return
  }
  m.isRead = true
  syncUnreadCount()
}
</script>

<style scoped>
/* 2026-09-30：原先这里有一条 .gap 样式，服务于页面底部那段
   「后端尚未提供…」的假说明。说明已删（那句话是错的），样式一并删掉。 */
</style>
