<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">AI 冲突预警与智能通知</h1>
      <p class="sp-page-sub">AI 扫描资源冲突并一键生成改约/致歉通知文案（数据来源：/conflicts、/notify）</p>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <div class="sp-card">
          <div class="sp-section-title">
            冲突扫描结果
            <el-button text type="primary" size="small" class="rescan" @click="loadConflicts">
              <el-icon><Refresh /></el-icon>重新扫描
            </el-button>
          </div>
          <el-empty v-if="!conflicts.length" description="未发现冲突" />
          <div
            v-for="(item, index) in conflicts"
            :key="index"
            class="conflict-card"
            :class="{ active: selectedIndex === index }"
            @click="selectedIndex = index"
          >
            <div class="conflict-head">
              <el-tag type="warning" effect="dark">{{ item.conflictType }}</el-tag>
              <span class="order-text">涉及订单 #{{ item.orderIds.join('、#') }}</span>
            </div>
            <div class="suggestion">{{ item.suggestion }}</div>
          </div>
        </div>
      </el-col>

      <el-col :span="12">
        <div class="sp-card notify-card">
          <div class="sp-section-title">智能通知文案</div>
          <el-empty
            v-if="!notify"
            description="选择一条冲突后生成通知"
            :image-size="80"
          />
          <template v-if="notify">
            <el-input v-model="notify.title" class="notify-title" size="large" />
            <el-input
              v-model="notify.content"
              type="textarea"
              :rows="8"
              class="notify-content"
            />
            <div class="notify-actions">
              <el-button type="primary" @click="generate">
                <el-icon><MagicStick /></el-icon>重新生成
              </el-button>
              <el-button @click="copyNotify">
                <el-icon><CopyDocument /></el-icon>复制文案
              </el-button>
            </div>
          </template>
          <el-button
            v-if="!notify"
            type="primary"
            :disabled="selectedConflict === null"
            @click="generate"
          >
            <el-icon><MagicStick /></el-icon>生成通知文案
          </el-button>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { generateNotify, scanConflicts } from '@/api/conflicts'

const loading = ref(false)
const conflicts = ref([])
const selectedIndex = ref(0)
const notify = ref(null)

const selectedConflict = computed(() => conflicts.value[selectedIndex.value] || null)

async function loadConflicts() {
  loading.value = true
  try {
    conflicts.value = await scanConflicts()
    selectedIndex.value = 0
    notify.value = null
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (!selectedConflict.value) return
  notify.value = await generateNotify({
    conflictType: selectedConflict.value.conflictType,
    orderIds: selectedConflict.value.orderIds,
    suggestion: selectedConflict.value.suggestion,
  })
}

async function copyNotify() {
  const text = `${notify.value.title}\n\n${notify.value.content}`
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('浏览器不支持自动复制，请手动选择复制')
  }
}

onMounted(loadConflicts)
</script>

<style scoped>
.page-head {
  margin-bottom: 16px;
}

.rescan {
  margin-left: auto;
}

.conflict-card {
  border: 1px solid var(--sp-border-l);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.15s;
}

.conflict-card.active {
  border-color: #409eff;
  background: #ecf5ff;
  box-shadow: 0 0 0 1px #409eff inset;
}

.conflict-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.order-text {
  font-size: 12px;
  color: #b88230;
}

.suggestion {
  font-size: 13px;
  line-height: 1.7;
  color: #8a6d3b;
}

.notify-card {
  min-height: 320px;
  display: flex;
  flex-direction: column;
}

.notify-title {
  margin-bottom: 12px;
  font-weight: 600;
}

.notify-content {
  margin-bottom: 14px;
}

.notify-actions {
  display: flex;
  gap: 10px;
}
</style>
