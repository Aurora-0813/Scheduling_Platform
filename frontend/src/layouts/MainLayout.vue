<template>
  <el-container class="layout">
    <el-aside :width="collapsed ? '64px' : '230px'" class="layout-aside">
      <div class="logo">
        <div class="logo-mark">AI</div>
        <div v-show="!collapsed" class="logo-text">
          <div class="logo-title">全感知调度平台</div>
          <div class="logo-sub">Admin Console</div>
        </div>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="side-menu"
        background-color="#ffffff"
        text-color="#606266"
        active-text-color="#409EFF"
      >
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <el-button text class="collapse-btn" @click="collapsed = !collapsed">
          <el-icon size="20">
            <Fold v-if="!collapsed" />
            <Expand v-else />
          </el-icon>
        </el-button>
        <div class="header-title">{{ currentTitle }}</div>
        <div class="header-right">
          <el-tag v-if="isDemo" type="warning" effect="plain" round>演示模式</el-tag>
          <el-dropdown @command="onCommand">
            <span class="user-box">
              <el-avatar :size="32" class="user-avatar">
                {{ avatarText }}
              </el-avatar>
              <span class="user-name">{{ userInfo?.username || '加载中...' }}</span>
              <el-icon><ArrowDown /></el-icon>
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
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/store/auth'
import { tokenStorage } from '@/utils/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const collapsed = ref(false)

const menuItems = router
  .getRoutes()
  .filter((item) => item.meta?.title && item.meta?.icon && item.path !== '/login')
  .map((item) => ({
    path: item.path,
    title: item.meta.title,
    icon: item.meta.icon,
  }))

const activeMenu = computed(() => route.path)
const currentTitle = computed(() => route.meta.title || '')
const userInfo = computed(() => authStore.userInfo)
const isDemo = computed(() => tokenStorage.isDemo())
const avatarText = computed(() => (authStore.userInfo?.username || '管').slice(0, 1).toUpperCase())

onMounted(async () => {
  if (!authStore.userInfo) {
    try {
      await authStore.fetchUserInfo()
    } catch {
      // 守卫之外的兜底，忽略
    }
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
.layout {
  height: 100%;
}

.layout-aside {
  background: #fff;
  border-right: 1px solid var(--sp-border-l);
  transition: width 0.2s;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  height: 64px;
  border-bottom: 1px solid var(--sp-border-l);
}

.logo-mark {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: linear-gradient(135deg, #409eff, #7c5cff);
  color: #fff;
  font-weight: 800;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(64, 158, 255, 0.35);
}

.logo-title {
  color: var(--sp-text);
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
}

.logo-sub {
  color: #a8b6c9;
  font-size: 10px;
  letter-spacing: 1px;
}

.side-menu {
  border-right: none;
  flex: 1;
}

.side-menu :deep(.el-menu-item) {
  margin: 4px 10px;
  border-radius: 8px;
  height: 46px;
}

.side-menu :deep(.el-menu-item.is-active) {
  background: var(--sp-sidebar-active);
  box-shadow: inset 3px 0 0 var(--sp-accent);
  font-weight: 600;
}

.side-menu :deep(.el-menu-item:hover) {
  background: #f5f8ff;
}

.layout-header {
  background: #fff;
  border-bottom: 1px solid var(--sp-border-l);
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
}

.collapse-btn {
  padding: 6px;
}

.header-title {
  font-size: 16px;
  font-weight: 700;
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 14px;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  outline: none;
}

.user-avatar {
  background: linear-gradient(135deg, #409eff, #7c5cff);
  color: #fff;
  font-size: 14px;
}

.user-name {
  font-size: 14px;
  color: var(--sp-t2);
}

.layout-main {
  background: var(--sp-bg);
  padding: 20px;
}
</style>
