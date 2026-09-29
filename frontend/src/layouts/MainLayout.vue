<template>
  <div class="sp-layout">
    <!-- ==================== 侧栏 ==================== -->
    <aside class="sp-side">
      <div class="sp-logo">
        <i>🤖</i>
        <span>AI 调度中台</span>
      </div>

      <nav class="sp-nav">
        <router-link v-for="item in menuItems" :key="item.path" :to="item.path" class="sp-si">
          <span class="sp-si-ic">{{ item.emoji }}</span>
          <span>{{ item.title }}</span>
        </router-link>
      </nav>

      <div class="sp-side-foot">
        <div class="sp-aibox">
          <b><span class="sp-live"></span> {{ statusTitle }}</b>
          {{ statusLine1 }}<br />{{ statusLine2 }}
        </div>
      </div>
    </aside>

    <!-- ==================== 右侧主体 ==================== -->
    <div class="sp-body">
      <header class="sp-head">
        <span class="sp-crumb">{{ crumb }}</span>
        <span class="sp-grow"></span>
        <span class="sp-tag is-purple">🧠 LangChain 1.x</span>
        <span class="sp-tag is-green"><span class="sp-live"></span> 服务正常</span>
        <el-dropdown @command="onCommand">
          <span class="sp-user">
            <span class="sp-avatar">{{ avatarText }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">
                <el-icon><User /></el-icon>个人中心
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </header>

      <main class="sp-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getAgentMetrics } from '@/api/monitor'
import { useAuthStore } from '@/store/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

/**
 * 侧栏导航 —— **显式列出**，不再从 router 自动推导。
 *
 * 原型 `docs/new_web.html` 定义了 6 项主导航；本平台在此基础上**多一项
 * 「预约单」**：原型的预约单入口只在 Agent 工作台的「确认并创建预约」按钮里，
 * 建完单之后没有任何地方能再看到/确认/取消它，这是本轮要补的缺口。
 *
 * 「冲突预警」「用户权限」不在主导航里（前者已并入预约日历右侧的 AI 软冲突雷达，
 * 后者在右上角头像菜单），但路由与页面都保留，没有删任何功能。
 */
const menuItems = [
  { path: '/agent', title: 'Agent 调度台', emoji: '🧠' },
  { path: '/calendar', title: '预约日历', emoji: '🗓' },
  { path: '/orders', title: '预约单', emoji: '📋' },
  { path: '/resources', title: '资源与设备', emoji: '🏢' },
  { path: '/inspect', title: 'AI 智能巡检', emoji: '🧰' },
  { path: '/dashboard', title: 'AI 数据洞察', emoji: '📊' },
  { path: '/monitor', title: 'Agent 监控', emoji: '📡' },
]

const crumb = computed(() => {
  const group = route.meta?.group
  const title = route.meta?.title
  return group && title ? `${group} / ${title}` : title || ''
})

const avatarText = computed(() => (authStore.userInfo?.username || '管').slice(0, 1).toUpperCase())

/* ---------------------------------------------------------------
   侧栏底部状态盒：数字来自真实的 GET /monitor/agent。
   刻意**不写死**任何数字 —— 拿不到就退回一句纯状态描述，不编数据。
   --------------------------------------------------------------- */
const metrics = ref(null)

const statusTitle = computed(() => (metrics.value ? 'Agent 运行中' : '服务正常'))

const statusLine1 = computed(() =>
  metrics.value ? `累计调用 ${metrics.value.totalCalls ?? 0} 次` : 'FastAPI · LangChain · MySQL',
)

const statusLine2 = computed(() => {
  if (!metrics.value) return '实时指标加载中…'
  const rate = metrics.value.successRate
  return rate === undefined || rate === null ? '成功率 —' : `成功率 ${rate}%`
})

onMounted(async () => {
  if (!authStore.userInfo) {
    try {
      await authStore.fetchUserInfo()
    } catch {
      // 守卫之外的兜底，忽略
    }
  }
  try {
    metrics.value = await getAgentMetrics()
  } catch {
    // 侧栏指标拿不到不该影响主流程
    metrics.value = null
  }
})

async function onCommand(command) {
  if (command === 'profile') {
    await router.push('/profile')
  } else if (command === 'logout') {
    await authStore.logout()
    await router.push('/login')
  }
}
</script>

<style scoped>
.sp-layout {
  display: flex;
  height: 100%;
}

/* ---------------- 侧栏 ---------------- */
.sp-side {
  width: var(--sp-side-w);
  flex: none;
  background: #fff;
  border-right: 1px solid var(--sp-border-l);
  display: flex;
  flex-direction: column;
}

.sp-logo {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--sp-border-l);
  font-size: 14.5px;
  font-weight: 700;
  color: var(--sp-text);
}

.sp-logo i {
  width: 27px;
  height: 27px;
  border-radius: 8px;
  font-style: normal;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: var(--sp-ai-gradient);
  box-shadow: 0 3px 10px rgba(64, 158, 255, 0.35);
}

.sp-nav {
  flex: 1;
  padding-top: 8px;
  overflow-y: auto;
}

.sp-si {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 18px;
  font-size: 13px;
  color: var(--sp-t2);
  text-decoration: none;
  transition: background 0.15s;
}

.sp-si:hover {
  background: #f5f8ff;
}

.sp-si.router-link-active {
  color: var(--sp-accent);
  font-weight: 600;
  background: var(--sp-sidebar-active);
  box-shadow: inset 3px 0 0 var(--sp-accent);
}

.sp-si-ic {
  font-size: 14px;
  width: 16px;
  text-align: center;
}

.sp-side-foot {
  padding: 12px 14px;
  border-top: 1px solid var(--sp-border-l);
}

.sp-aibox {
  background: linear-gradient(135deg, #f2f7ff, #f6f2ff);
  border: 1px solid var(--sp-ai-line);
  border-radius: 9px;
  padding: 10px 11px;
  font-size: 11.5px;
  color: var(--sp-t2);
  line-height: 1.6;
}

.sp-aibox b {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--sp-text);
  margin-bottom: 5px;
}

/* ---------------- 主体 ---------------- */
.sp-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--sp-bg);
}

.sp-head {
  height: var(--sp-head-h);
  flex: none;
  background: #fff;
  border-bottom: 1px solid var(--sp-border-l);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 22px;
  font-size: 13px;
  color: var(--sp-t3);
}

.sp-crumb {
  font-size: 13px;
  color: var(--sp-t3);
}

.sp-user {
  display: flex;
  align-items: center;
  cursor: pointer;
  outline: none;
}

.sp-avatar {
  width: 29px;
  height: 29px;
  border-radius: 50%;
  color: #fff;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--sp-ai-gradient);
}

.sp-main {
  flex: 1;
  padding: 16px 22px;
  min-height: 0;
  overflow-y: auto;
}
</style>
