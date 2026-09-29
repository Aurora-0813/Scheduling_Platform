<template>
  <div class="login">
    <!-- 左：品牌区（原型 .login-l：点阵 + 光晕 + 徽标 + 能力点） -->
    <div class="login-l">
      <div class="dotgrid"></div>
      <div class="orb a"></div>
      <div class="orb b"></div>

      <div class="inner">
        <div class="ll-badge">
          <span class="sp-live"></span>
          LangChain Agent 中台 · 在线
        </div>
        <h2>让空间与设备<br />听懂你的每一句话</h2>
        <p class="sub">
          多模态感知 → Agent 智能决策 → 业务自动落库<br />
          全链路异步架构 · 思考过程全程可视化
        </p>
        <div class="ll-feat">
          <div><i>🎙</i>口述一句模糊需求，Agent 自动解析并排冲突</div>
          <div><i>📷</i>拍照识空间、拍图查故障，多模态直达业务单据</div>
          <div><i>🧠</i>Thought → Action → Observation 推理链实时可见</div>
        </div>
      </div>

      <div class="ll-foot">PC Web 管理端 · AI 全感知调度平台</div>
    </div>

    <!-- 右：登录表单（原型 .login-r：.field / .inputx / .btn.ai.block） -->
    <div class="login-r">
      <div class="login-card">
        <h3>账号登录</h3>
        <p class="hint">
          JWT 双 Token · RBAC 权限模型<br />
          身份一律从 Token 解析，禁止从请求体传入
        </p>

        <el-form
          ref="formRef"
          class="login-form"
          :model="form"
          :rules="rules"
          size="large"
          label-position="top"
          @keyup.enter="onSubmit"
        >
          <el-form-item label="账号" prop="username">
            <el-input v-model="form.username" placeholder="请输入用户名" :prefix-icon="User" clearable />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            class="sp-btn is-ai is-block login-submit"
            :loading="loading"
            @click="onSubmit"
          >
            进入 AI 调度中台
          </el-button>
        </el-form>

        <p class="login-crypt">密码使用 bcrypt 加密存储 ｜ 请勿留存真实密码</p>
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
// 表单**不预填任何凭据**：原先写死的是 { username: 'admin', password: '123456' }，
// 而 123456 根本不是本项目的账号口令（真实口令见 .env / docs/seed.sql），
// 预填一个错的密码只会让人点一次登录就撞一次「用户名或密码错误」。
// 演示账号请写进 README 或口头告知，不要硬编码进源码。
const form = reactive({ username: '', password: '' })

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
    // 兜底落到「Agent 调度台」——它是本平台的主入口，
    // 与 router 里 `redirect: '/agent'` 保持同一个口径。
    // （原先兜底到 /dashboard，于是改路由默认页也没用：这里会把它覆盖掉。）
    const redirect = route.query.redirect || '/agent'
    await router.push(redirect)
  } catch {
    // 错误提示已由拦截器/组件处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* 原型登录区是 1440×900 的缩略画布，这里改为铺满浏览器视口并随宽度自适应 */
.login {
  display: flex;
  min-height: 100vh;
  background: #fff;
}

/* ---------- 左：品牌区 ---------- */
.login-l {
  flex: 1.15;
  min-width: 0;
  position: relative;
  overflow: hidden;
  padding: clamp(36px, 6vw, 74px) clamp(28px, 5vw, 68px);
  color: #fff;
  display: flex;
  flex-direction: column;
  justify-content: center;
  background: linear-gradient(145deg, #2d6fd0, #409eff 45%, #7c5cff);
}

.dotgrid {
  position: absolute;
  inset: 0;
  opacity: 0.5;
  background-image: radial-gradient(circle, rgba(255, 255, 255, 0.5) 1px, transparent 1px);
  background-size: 34px 34px;
  -webkit-mask-image: radial-gradient(620px 460px at 45% 45%, #000 15%, transparent 72%);
  mask-image: radial-gradient(620px 460px at 45% 45%, #000 15%, transparent 72%);
}

.orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
}

.orb.a {
  width: 300px;
  height: 300px;
  background: rgba(255, 255, 255, 0.35);
  top: -70px;
  right: -50px;
  animation: sp-breathe 7s ease-in-out infinite;
}

.orb.b {
  width: 280px;
  height: 280px;
  background: rgba(124, 92, 255, 0.55);
  bottom: -90px;
  left: -60px;
  animation: sp-breathe 9s ease-in-out infinite reverse;
}

.inner {
  position: relative;
  z-index: 2;
  max-width: 540px;
}

.ll-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  padding: 6px 13px;
  border-radius: 20px;
  margin-bottom: 24px;
  width: fit-content;
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.42);
}

.login-l h2 {
  font-size: clamp(24px, 2.3vw, 32px);
  line-height: 1.45;
  font-weight: 700;
  letter-spacing: 0.4px;
  margin: 0 0 14px;
}

.login-l .sub {
  font-size: 13.5px;
  color: rgba(255, 255, 255, 0.82);
  line-height: 1.9;
  margin: 0 0 34px;
}

.ll-feat {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.ll-feat div {
  display: flex;
  align-items: center;
  gap: 11px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.94);
}

.ll-feat i {
  width: 29px;
  height: 29px;
  flex: none;
  border-radius: 9px;
  font-style: normal;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.22);
  border: 1px solid rgba(255, 255, 255, 0.36);
}

.ll-foot {
  position: absolute;
  left: clamp(28px, 5vw, 68px);
  bottom: 28px;
  z-index: 2;
  font-size: 12px;
  letter-spacing: 1px;
  color: rgba(255, 255, 255, 0.65);
}

/* ---------- 右：表单区 ---------- */
.login-r {
  flex: 1;
  min-width: 0;
  position: relative;
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 56px clamp(24px, 6vw, 88px);
}

.login-card {
  width: 100%;
  max-width: 360px;
}

.login-r h3 {
  font-size: 23px;
  color: var(--sp-text);
  margin: 0 0 8px;
}

.login-r .hint {
  font-size: 12.5px;
  color: var(--sp-t3);
  line-height: 1.7;
  margin: 0 0 30px;
}

/* 输入框落到原型的 .inputx：细描边 + 聚焦 3px 光晕 */
.login-form :deep(.el-form-item) {
  margin-bottom: 19px;
}

.login-form :deep(.el-form-item__label) {
  font-size: 12.5px;
  color: var(--sp-t2);
  line-height: 1.2;
  padding-bottom: 8px;
  margin-bottom: 0;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: 7px;
  padding: 4px 14px;
  box-shadow: 0 0 0 1px var(--sp-border) inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--sp-accent) inset,
    0 0 0 3px rgba(64, 158, 255, 0.12);
}

/* Element Plus 的 primary 皮肤改不动渐变阴影，这里显式落到原型的 .btn.ai.block */
.login-form :deep(.el-button.login-submit) {
  letter-spacing: 4px;
  border: none;
  background: var(--sp-ai-gradient);
  box-shadow: 0 3px 12px rgba(64, 158, 255, 0.32);
}

.login-crypt {
  margin: 16px 0 0;
  font-size: 11.5px;
  color: #c0c4cc;
  text-align: center;
}

.login-copy {
  position: absolute;
  bottom: 24px;
  font-size: 12px;
  color: var(--sp-t3);
}

/* 窄屏：品牌区收起为顶部横条，表单铺满，避免左侧大块留白 */
@media (max-width: 900px) {
  .login {
    flex-direction: column;
  }

  .login-l {
    flex: none;
    padding: 40px 28px;
  }

  .login-l .sub {
    margin-bottom: 22px;
  }

  .ll-foot {
    display: none;
  }

  .login-r {
    flex: 1;
    padding: 40px 22px 64px;
  }
}
</style>
