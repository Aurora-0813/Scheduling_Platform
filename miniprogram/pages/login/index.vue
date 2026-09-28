<template>
  <view class="app-page">
    <mp-nav-bar title="登录" back border />

    <view class="app-body">
      <!-- AI 品牌头，视觉与首页 ai-hero 同源 -->
      <view class="brand">
        <view class="orb">
          <text class="big">🧠</text>
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

      <view
        class="btn ai block"
        :class="{ disabled: loading || !canSubmit }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="doSubmit"
      >{{ loading ? '登录中…' : '登 录' }}</view>

      <view class="btn ghost block later" hover-class="btn-on" @tap="skip">先逛逛</view>

      <text class="tip">
        账号由管理员在后台创建。未启动后端时仍可浏览演示数据，但无法保存预约。
      </text>
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
import { doLogin } from '@/store/user.js'
import { toast, toastOk, showLoading, hideLoading } from '@/utils/toast.js'

const username = ref('')
const password = ref('')
const loading = ref(false)

const canSubmit = computed(() => !!username.value.trim() && !!password.value)

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
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(150deg, var(--ai-a), var(--ai-b));
  box-shadow: 0 16rpx 48rpx rgba(64, 158, 255, 0.35);
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
  border-bottom: 1px solid #f5f7fa;
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
  color: #c0c4cc;
}

.later {
  margin-top: 22rpx;
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
