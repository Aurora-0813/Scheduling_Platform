<template>
  <div class="login-page">
    <div class="login-hero">
      <div class="hero-content">
        <div class="hero-badge">AI · IoT · Agent</div>
        <h1 class="hero-title">AI 全感知<br />智能空间与设备<br />综合调度平台</h1>
        <p class="hero-desc">语音预约 · 空间感知 · 智能巡检<br />冲突预警 · 数据洞察 · Agent 调度</p>
        <ul class="hero-points">
          <li>自然语言一句话完成场地与设备预约</li>
          <li>AI 自动识别资源软冲突并给出改约建议</li>
          <li>Agent 思考链全程可视化，调度可追溯</li>
        </ul>
      </div>
      <div class="hero-footer">PC Web 管理端</div>
    </div>

    <div class="login-panel">
      <div class="login-card">
        <h2 class="login-title">欢迎登录</h2>
        <p class="login-sub">请输入管理员账号与密码</p>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          size="large"
          @keyup.enter="onSubmit"
        >
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" clearable />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="onSubmit"
          >
            登 录
          </el-button>
        </el-form>

        <p class="login-tip">
          演示提示：后端未连通时，点击登录将自动进入演示模式浏览全部页面
        </p>
      </div>
      <div class="login-copy">© 2026 AI全感知调度平台 · 小组项目</div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'

import { useAuthStore } from '@/store/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: 'admin', password: '123456' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function onSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    const redirect = route.query.redirect || '/dashboard'
    await router.push(redirect)
  } catch {
    // 错误提示已由拦截器/组件处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
}

.login-hero {
  flex: 1.1;
  background: linear-gradient(150deg, #0d2825 0%, #14403a 55%, #1e6b5c 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 60px 64px;
  position: relative;
  overflow: hidden;
}

.login-hero::after {
  content: '';
  position: absolute;
  right: -120px;
  top: -120px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  background: rgba(95, 184, 159, 0.12);
}

.hero-badge {
  display: inline-block;
  border: 1px solid rgba(95, 184, 159, 0.5);
  color: #8fd6c1;
  font-size: 12px;
  letter-spacing: 2px;
  padding: 5px 12px;
  border-radius: 20px;
  margin-bottom: 28px;
  width: fit-content;
}

.hero-title {
  font-size: 38px;
  line-height: 1.3;
  margin: 0 0 20px;
  font-weight: 800;
}

.hero-desc {
  color: #a9c8c0;
  font-size: 14px;
  line-height: 1.8;
  margin: 0 0 28px;
}

.hero-points {
  padding: 0;
  margin: 0;
  list-style: none;
}

.hero-points li {
  font-size: 13px;
  color: #c4d8d3;
  padding: 7px 0 7px 22px;
  position: relative;
}

.hero-points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #5fb89f;
}

.hero-footer {
  position: absolute;
  bottom: 28px;
  left: 64px;
  font-size: 12px;
  color: #6f8a82;
  letter-spacing: 2px;
}

.login-panel {
  width: 480px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #fff;
  position: relative;
}

.login-card {
  width: 340px;
}

.login-title {
  font-size: 26px;
  margin: 0 0 8px;
  color: #1f2d2b;
}

.login-sub {
  color: #8a9794;
  font-size: 13px;
  margin: 0 0 28px;
}

.login-btn {
  width: 100%;
  margin-top: 4px;
  letter-spacing: 4px;
}

.login-tip {
  margin-top: 18px;
  font-size: 12px;
  color: #a0acaa;
  text-align: center;
  line-height: 1.6;
}

.login-copy {
  position: absolute;
  bottom: 24px;
  font-size: 12px;
  color: #b3bdbb;
}
</style>
