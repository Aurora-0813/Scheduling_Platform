<template>
  <view class="app-page">
    <mp-nav-bar title="登录" back border />

    <view class="app-body">
      <!-- AI 品牌头，视觉与首页 ai-hero 同源 -->
      <view class="brand">
        <view class="orb">
          <text class="big">◈</text>
        </view>
        <text class="bt">AI 全感知 · 智能空间与设备综合调度平台</text>
        <text class="bs">登录后可查看预约、提交巡检、接收通知</text>
      </view>

      <view class="mcard">
        <view class="field">
          <text class="fl">账号</text>
          <input
            v-model="username"
            class="fi"
            type="text"
            placeholder="请输入用户名"
            placeholder-class="ph"
            :maxlength="32"
            :disabled="loading"
          />
        </view>

        <view class="field">
          <text class="fl">密码</text>
          <input
            v-model="password"
            class="fi"
            type="password"
            placeholder="请输入密码"
            placeholder-class="ph"
            :maxlength="64"
            :disabled="loading"
            @confirm="doSubmit"
          />
        </view>
      </view>

      <!--
        后端地址（2026-10-14 新增）。

        放在登录按钮**之前**：地址是所有请求的前提，登录也是请求之一。
        内网穿透的公网地址会变（每次重启隧道可能换一个），原先只能改
        `config/index.js` 重打包 APK —— 现在在这里填一次即可。
      -->
      <view class="ep">
        <view class="ep-head" @tap="toggleEndpoint">
          <text class="ep-t">后端地址</text>
          <text class="ep-cur">{{ endpointShort }}</text>
          <text v-if="epCustom" class="ep-badge">已自定义</text>
          <text class="ep-arrow">{{ epOpen ? '收起' : '修改 ›' }}</text>
        </view>

        <template v-if="epOpen">
          <view class="ep-row">
            <input
              v-model="baseUrl"
              class="ep-in"
              type="text"
              placeholder="http://192.168.1.10:8000 或 https://xxx.frp.io"
              placeholder-class="ph"
              :disabled="loading"
              confirm-type="done"
              @confirm="onTestEndpoint"
            />
          </view>

          <view class="ep-btns">
            <view
              class="ep-btn"
              :class="{ disabled: testingEndpoint }"
              hover-class="btn-on"
              @tap="onTestEndpoint"
            >{{ testingEndpoint ? '测试中…' : '测试连接' }}</view>
            <view class="ep-btn ghost" hover-class="btn-on" @tap="onResetEndpoint">用默认地址</view>
          </view>

          <!-- 探测结果：成功给延迟，失败给可读原因 -->
          <text v-if="epMsg" class="ep-msg" :class="epOk ? 'ok' : 'bad'">{{ epMsg }}</text>
          <text v-else class="ep-hint">只填到端口即可，结尾的 /api/v1 会自动去掉；http 仅调试可用。</text>
        </template>
      </view>

      <view
        class="btn ai block"
        :class="{ disabled: loading || !canSubmit }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="doSubmit"
      >{{ loading ? '登录中…' : '登 录' }}</view>

      <view class="btn ghost block later" hover-class="btn-on" @tap="skip">先逛逛</view>

    </view>
  </view>
</template>

<script setup>
/**
 * 登录
 *
 * 接口：POST /auth/login → { accessToken, refreshToken, role }，随后 GET /auth/info。
 * 认证接口恒定走真实路径（后端没有 /api/v1/mock/auth/*）。
 *
 * 安全约定（§5.3 §9.1）：本文件不含任何真实账号密码，仅做输入与提交；
 * 身份由后端从 JWT 解析，前端不解析也不传 userId。
 */
import { ref, computed } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import { doLogin } from '@/store/user.js'
import { toast, toastOk, showLoading, hideLoading, resetLoading } from '@/utils/toast.js'
import {
  getBaseUrl,
  getDefaultBaseUrl,
  isCustomBaseUrl,
  setBaseUrl,
  resetBaseUrl,
  probeBaseUrl,
} from '@/api/endpoint.js'
import { notifyEndpointChanged } from '@/utils/ws.js'

// 页面销毁时把 loading 计数归零：万一有哪条路径没配平，残留的计数会让之后
// 每一次 show/hide 都错位 —— 微信侧会一直报「showLoading 与 hideLoading 必须配对使用」
onUnload(() => resetLoading())

const username = ref('')
const password = ref('')
const loading = ref(false)

const canSubmit = computed(() => !!username.value.trim() && !!password.value)

// ------------------------------------------------------------------
// 后端地址（内网穿透用，2026-10-14 新增）
// ------------------------------------------------------------------
/**
 * 输入框默认**收起**。
 *
 * 理由：这个页面的主要任务是登录，绝大多数人一辈子不会碰这个输入框。
 * 常驻展开会让「账号 / 密码 / 地址」三个输入框并列，
 * 用户很容易把地址当成必填项而卡住；也容易手滑改坏导致「突然登录不了」。
 * 需要的人点一下「修改 ›」就能看到，不需要的人完全感知不到。
 */
const epOpen = ref(false)
/** 输入框里的地址（未提交的草稿） */
const baseUrl = ref('')
/** 当前生效的地址是否来自本地存储的覆盖值 */
const epCustom = ref(false)
/** 探测结果文案与成败，用于着色 */
const epMsg = ref('')
const epOk = ref(false)
const testingEndpoint = ref(false)

/** 头部那一行只显示主机部分，太长会把「修改」挤掉 */
const endpointShort = computed(() => {
  const v = getBaseUrl()
  return v.replace(/^https?:\/\//, '')
})

onLoad(() => {
  baseUrl.value = getBaseUrl()
  epCustom.value = isCustomBaseUrl()
})

function toggleEndpoint() {
  epOpen.value = !epOpen.value
  if (epOpen.value) {
    // 每次展开都回填**当前生效值**：用户可能刚点过「用默认地址」
    baseUrl.value = getBaseUrl()
    epMsg.value = ''
    epOk.value = false
  }
}

/**
 * 测试连接：打 `GET {base}/api/v1/health`（不需要登录，见 api/endpoint.js）。
 *
 * ⚠️ 它**只探测、不保存**。测试通了才让用户保存，是刻意的两步：
 * 一个连不上的地址一旦存进去，后续所有请求（含登录）都会失败，
 * 而那时的报错是「网络连接失败」，用户**根本不会想到**是自己刚才填错了地址。
 */
async function onTestEndpoint() {
  if (testingEndpoint.value) return
  testingEndpoint.value = true
  epMsg.value = '正在探测…'
  epOk.value = false
  try {
    const res = await probeBaseUrl(baseUrl.value)
    epOk.value = res.ok
    if (res.ok) {
      baseUrl.value = res.baseUrl
      const svc = (res.detail && res.detail.service) || ''
      const env = (res.detail && res.detail.env) || ''
      epMsg.value = `${res.message}${svc ? ' ｜ ' + svc : ''}${env ? '（' + env + '）' : ''}`
    } else {
      epMsg.value = res.message
    }
  } finally {
    testingEndpoint.value = false
  }
}

/** 填回 config 里的默认地址，并清掉存储里的覆盖值 */
function onResetEndpoint() {
  baseUrl.value = resetBaseUrl()
  epCustom.value = false
  epOk.value = true
  epMsg.value = '已恢复默认地址'
  notifyEndpointChanged()
}

/**
 * 保存输入框里的地址。返回是否成功 —— 调用方（doSubmit）据此决定要不要继续登录。
 *
 * 保存成功才通知 WS 层：地址变了，旧连接必须断掉，
 * 否则它会一直重连旧地址（页面表现是「登录正常但通知永远不来」）。
 */
function saveEndpointIfChanged() {
  const draft = (baseUrl.value || '').trim()
  // 没开过这个面板、或者与当前生效值一致 → 什么都不做
  if (!draft || draft === getBaseUrl()) {
    epCustom.value = isCustomBaseUrl()
    return true
  }
  const res = setBaseUrl(draft)
  if (!res.ok) {
    epOk.value = false
    epMsg.value = res.message
    epOpen.value = true
    toast(res.message)
    return false
  }
  baseUrl.value = res.baseUrl
  epCustom.value = true
  epOk.value = true
  epMsg.value = `已保存：${res.baseUrl}`
  notifyEndpointChanged()
  return true
}

async function doSubmit() {
  if (loading.value) return

  const name = username.value.trim()
  if (!name) {
    toast('请输入用户名')
    return
  }
  if (!password.value) {
    toast('请输入密码')
    return
  }

  // 地址是登录请求的前提：先把输入框里的改动落盘再登录。
  // 失败（格式不合法）就**不发**登录请求 —— 否则用户会看到「网络连接失败」，
  // 而他刚刚明明改过地址，却不会意识到问题出在那个输入框上。
  if (!saveEndpointIfChanged()) return

  loading.value = true
  showLoading('登录中…')
  try {
    await doLogin({ username: name, password: password.value })
    toastOk('登录成功')
    goBack()
  } catch (e) {
    // 密码错误是业务错误，如实提示；网络不通时 api/auth.js 已降级为演示模式
    toast(e.message || '登录失败，请检查账号密码')
  } finally {
    loading.value = false
    hideLoading()
  }
}

function goBack() {
  const pages = getCurrentPages()
  if (pages && pages.length > 1) {
    uni.navigateBack()
  } else {
    uni.reLaunch({ url: '/pages/index/index' })
  }
}

function skip() {
  uni.reLaunch({ url: '/pages/index/index' })
}
</script>

<style scoped>
.brand {
  text-align: center;
  padding: 40rpx 0 48rpx;
}

.orb {
  width: 148rpx;
  height: 148rpx;
  margin: 0 auto 26rpx;
  border-radius: var(--r-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  /* 原为 150deg 蓝→紫渐变 + 蓝色发光阴影；改为单一主色 + 轻阴影。 */
  background: var(--primary);
  box-shadow: var(--sh2);
}

.orb .big {
  font-size: 72rpx;
}

.bt {
  display: block;
  font-size: 29rpx;
  font-weight: 600;
  color: var(--t1);
  line-height: 1.6;
  padding: 0 20rpx;
}

.bs {
  display: block;
  margin-top: 14rpx;
  font-size: 23rpx;
  color: var(--t3);
}

.field {
  display: flex;
  align-items: center;
  padding: 24rpx 0;
  border-bottom: 1px solid var(--bg-hover);
}

.field:last-child {
  border-bottom: none;
}

.fl {
  width: 110rpx;
  flex: none;
  font-size: 26rpx;
  color: var(--t3);
}

.fi {
  flex: 1;
  min-width: 0;
  font-size: 27rpx;
  color: var(--t1);
}

.ph {
  color: var(--t3);
}

.later {
  margin-top: 22rpx;
}

/* ---- 后端地址（内网穿透） ---- */
.ep {
  margin-top: 28rpx;
  background: #fff;
  border: 1px solid var(--bd-l);
  border-radius: var(--r-lg);
  padding: 24rpx;
}

.ep-head {
  display: flex;
  align-items: center;
}

.ep-t {
  font-size: 26rpx;
  font-weight: 600;
  color: var(--t1);
  flex: none;
}

.ep-cur {
  flex: 1;
  min-width: 0;
  margin-left: 16rpx;
  font-size: 23rpx;
  color: var(--t3);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.ep-badge {
  flex: none;
  margin-left: 10rpx;
  padding: 2rpx 12rpx;
  font-size: 19rpx;
  color: #fff;
  border-radius: var(--r-xs);
  background: var(--primary);
}

.ep-arrow {
  flex: none;
  margin-left: 14rpx;
  font-size: 23rpx;
  color: var(--ai-a);
}

.ep-row {
  margin-top: 20rpx;
  border-bottom: 1px solid var(--bg-hover);
  padding-bottom: 12rpx;
}

.ep-in {
  width: 100%;
  font-size: 25rpx;
  color: var(--t1);
}

.ep-btns {
  display: flex;
  margin-top: 20rpx;
}

.ep-btn {
  flex: 1;
  text-align: center;
  font-size: 24rpx;
  padding: 16rpx 0;
  border-radius: var(--r-sm);
  color: #fff;
  background: var(--primary);
  transition: background-color var(--dur) var(--ease);
}

.ep-btn.ghost {
  margin-left: 16rpx;
  color: var(--t2);
  background: var(--bg-hover);
}

.ep-btn.disabled {
  opacity: 0.6;
}

.ep-msg,
.ep-hint {
  display: block;
  margin-top: 16rpx;
  font-size: 21rpx;
  line-height: 1.6;
}

.ep-msg.ok {
  color: var(--success);
}

.ep-msg.bad {
  color: var(--danger);
}

.ep-hint {
  color: var(--t3);
}

.tip {
  display: block;
  margin-top: 34rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  text-align: center;
  padding: 0 24rpx;
}
</style>
