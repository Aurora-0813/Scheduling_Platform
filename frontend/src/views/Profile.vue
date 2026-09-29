<template>
  <div v-loading="loading">
    <div class="sp-pagebar">
      <h3>用户权限</h3>
      <div class="sp-acts">
        <button class="sp-btn is-ghost is-sm" :disabled="loading" @click="loadInfo">
          <el-icon><Refresh /></el-icon>刷新信息
        </button>
      </div>
    </div>
    <p class="sp-page-sub">当前登录账号、角色与权限清单（数据来源：GET /auth/info）</p>

    <el-row :gutter="16">
      <el-col :xs="24" :md="9">
        <div class="sp-card user-card">
          <div class="big-avatar">{{ avatarText }}</div>
          <div class="user-name">{{ userInfo?.username || '未获取到账号' }}</div>
          <span class="sp-tag is-purple">{{ userInfo?.role || '未知角色' }}</span>

          <div class="user-stats">
            <div class="stat">
              <b>{{ userInfo?.permissions?.length ?? 0 }}</b>
              <span>权限码</span>
            </div>
            <div class="stat">
              <b>{{ userInfo?.id ?? '--' }}</b>
              <span>用户 ID</span>
            </div>
          </div>

          <p v-if="!userInfo" class="sp-muted user-empty">
            暂无账号信息，请点击右上角「刷新信息」重试
          </p>
        </div>
      </el-col>

      <el-col :xs="24" :md="15">
        <div class="sp-card">
          <div class="sp-section-title">账号信息</div>
          <div class="sp-mbrow">
            <span class="sp-k">用户 ID</span>
            <span class="sp-v">{{ userInfo?.id ?? '--' }}</span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">用户名</span>
            <span class="sp-v">{{ userInfo?.username || '--' }}</span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">角色</span>
            <span class="sp-v">{{ userInfo?.role || '--' }}</span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">头像</span>
            <span class="sp-v">{{ userInfo?.avatar || '默认头像' }}</span>
          </div>

          <div class="sp-section-title perm-title">权限码</div>
          <div v-if="userInfo?.permissions?.length" class="perm-box">
            <span
              v-for="perm in userInfo.permissions"
              :key="perm"
              class="sp-tag"
              :class="perm === '*' ? 'is-green' : 'is-blue'"
            >
              {{ perm === '*' ? '*（全部权限）' : perm }}
            </span>
          </div>
          <p v-else class="sp-muted">接口未返回权限码，当前账号无显式权限项</p>
        </div>

        <div class="sp-ai-bar rbac-bar">
          <span class="sp-ic">🛡</span>
          <span>
            角色与权限由后端 <b>RBAC</b> 体系（sys_role.permissions）统一下发，前端只按权限码渲染菜单，
            不在前端保存或修改权限。
          </span>
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
/* 说明行紧跟工具条，与下方卡片之间留出与页面栅格一致的间距 */
.sp-page-sub {
  margin-bottom: 16px;
}

/* 身份卡：竖排居中，头像用平台 AI 渐变，与侧栏/顶栏保持同一套视觉 */
.user-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 28px 20px;
  text-align: center;
}

.big-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  font-weight: 600;
  color: #fff;
  background: var(--sp-ai-gradient);
  box-shadow: 0 6px 18px rgba(64, 158, 255, 0.28);
}

.user-name {
  font-size: 18px;
  font-weight: 700;
  color: var(--sp-text);
  word-break: break-all;
}

.user-stats {
  display: flex;
  width: 100%;
  margin-top: 8px;
  padding-top: 14px;
  border-top: 1px solid #f5f7fa;
}

.user-stats .stat {
  flex: 1;
  min-width: 0;
}

.user-stats .stat + .stat {
  border-left: 1px solid #f5f7fa;
}

.user-stats b {
  display: block;
  font-size: 15px;
  color: var(--sp-text);
  word-break: break-all;
}

.user-stats span {
  font-size: 12px;
  color: var(--sp-t3);
}

.user-empty {
  margin: 4px 0 0;
}

.perm-title {
  margin-top: 22px;
}

.perm-box {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 权限码是需要逐字比对的标识，用等宽字体减少误读 */
.perm-box .sp-tag {
  font-family: Consolas, ui-monospace, monospace;
}

.rbac-bar {
  margin: 14px 0 0;
  align-items: flex-start;
  line-height: 1.7;
}

@media (max-width: 992px) {
  .user-card {
    margin-bottom: 16px;
  }
}
</style>
