<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">用户权限</h1>
      <p class="sp-page-sub">当前登录账号、角色与权限清单（数据来源：GET /auth/info）</p>
    </div>

    <el-row :gutter="16">
      <el-col :span="9">
        <div class="sp-card user-card">
          <el-avatar :size="72" class="big-avatar">
            {{ avatarText }}
          </el-avatar>
          <div class="user-name">{{ userInfo?.username }}</div>
          <el-tag effect="dark" class="role-tag">{{ userInfo?.role }}</el-tag>
          <el-button class="refresh-btn" @click="loadInfo">
            <el-icon><Refresh /></el-icon>刷新信息
          </el-button>
        </div>
      </el-col>
      <el-col :span="15">
        <div class="sp-card">
          <div class="sp-section-title">账号信息</div>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="用户 ID">{{ userInfo?.id }}</el-descriptions-item>
            <el-descriptions-item label="用户名">{{ userInfo?.username }}</el-descriptions-item>
            <el-descriptions-item label="角色">{{ userInfo?.role }}</el-descriptions-item>
            <el-descriptions-item label="头像">{{ userInfo?.avatar || '默认头像' }}</el-descriptions-item>
          </el-descriptions>

          <div class="sp-section-title perm-title">权限码</div>
          <div class="perm-box">
            <el-tag
              v-for="perm in userInfo?.permissions || []"
              :key="perm"
              class="perm-tag"
              :type="perm === '*' ? 'success' : 'info'"
            >
              {{ perm === '*' ? '*（全部权限）' : perm }}
            </el-tag>
          </div>
          <p class="sp-muted perm-note">
            说明：角色与权限由后端 RBAC 体系（sys_role.permissions）统一下发，前端只负责按权限码渲染菜单，不在前端保存或修改权限。
          </p>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { useAuthStore } from '@/store/auth'

const loading = ref(false)
const authStore = useAuthStore()

const userInfo = computed(() => authStore.userInfo)
const avatarText = computed(() => (userInfo.value?.username || '管').slice(0, 1).toUpperCase())

async function loadInfo() {
  loading.value = true
  try {
    await authStore.fetchUserInfo()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!authStore.userInfo) {
    await loadInfo()
  }
})
</script>

<style scoped>
.page-head {
  margin-bottom: 16px;
}

.user-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 32px 20px;
}

.big-avatar {
  background: linear-gradient(135deg, #409eff, #7c5cff);
  color: #fff;
  font-size: 28px;
}

.user-name {
  font-size: 18px;
  font-weight: 700;
}

.role-tag {
  margin-bottom: 10px;
}

.refresh-btn {
  margin-top: 6px;
}

.perm-title {
  margin-top: 22px;
}

.perm-box {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.perm-tag {
  font-family: Consolas, monospace;
}

.perm-note {
  margin-top: 14px;
  line-height: 1.7;
}
</style>
