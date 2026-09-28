<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">Agent 监控与思考链</h1>
      <p class="sp-page-sub">大模型调用统计 + 智能调度 Agent 的完整思考链可视化（数据来源：/monitor、/agent/schedule）</p>
    </div>

    <!-- KPI -->
    <el-row :gutter="16" class="kpi-row">
      <el-col :span="6">
        <div class="sp-card kpi">
          <div class="kpi-label">总调用次数</div>
          <div class="kpi-value">{{ metrics.totalCalls ?? 0 }}</div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="sp-card kpi">
          <div class="kpi-label">成功率</div>
          <div class="kpi-value">{{ metrics.successRate ?? 100 }}<span class="unit">%</span></div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="sp-card kpi">
          <div class="kpi-label">平均耗时</div>
          <div class="kpi-value">{{ metrics.avgLatency ?? 0 }}<span class="unit">s</span></div>
        </div>
      </el-col>
      <el-col :span="6">
        <div class="sp-card kpi">
          <div class="kpi-label">降级率</div>
          <div class="kpi-value">{{ degradedRate }}<span class="unit">%</span></div>
        </div>
      </el-col>
    </el-row>

    <!-- 操作按钮 -->
    <div class="sp-card action-bar">
      <el-button type="primary" :loading="simulating" @click="onSimulate">
        <el-icon><DataLine /></el-icon>灌入模拟调用（128 次）
      </el-button>
      <el-button :loading="traceLoading" @click="onLoadTrace">
        <el-icon><View /></el-icon>查看智能调度思考链
      </el-button>
      <span class="sp-muted">监控数据由中间件自动收集；思考链来自 Agent 调度接口。</span>
    </div>

    <el-row :gutter="16">
      <!-- 思考链 -->
      <el-col :span="15">
        <div class="sp-card">
          <div class="sp-section-title">思考链时间线（Thought → Action → Observation）</div>
          <el-empty v-if="!schedule.trace?.length" description="点击上方按钮加载思考链" />
          <div v-for="step in schedule.trace" :key="step.step" class="sp-trace-step" :class="{ 'is-result': step.action }">
            <span class="sp-trace-dot"></span>
            <div class="step-head">
              <span class="step-no">第 {{ step.step }} 步</span>
              <span class="step-result">{{ step.result }}</span>
              <span class="step-time">{{ step.timestamp.slice(11) }}</span>
            </div>
            <div class="step-thought">Thought：{{ step.thought }}</div>
            <template v-if="step.action">
              <div class="step-action">Action：{{ step.action }}</div>
              <div class="sp-trace-code">Input: {{ formatJson(step.actionInput) }}</div>
              <div class="sp-trace-code">Observation: {{ formatJson(step.observation) }}</div>
            </template>
          </div>
        </div>
      </el-col>

      <!-- 调度方案 -->
      <el-col :span="9">
        <div class="sp-card plan-card">
          <div class="sp-section-title">调度方案</div>
          <el-empty v-if="!schedule.plan" description="暂无方案" :image-size="70" />
          <template v-if="schedule.plan">
            <el-alert
              v-if="schedule.needConfirm"
              title="该方案需要用户确认"
              type="warning"
              :closable="false"
              show-icon
              class="confirm-alert"
            />
            <div class="plan-box main-plan">
              <div class="plan-name">
                <el-tag type="success" effect="dark">主方案</el-tag>
                {{ schedule.plan.spaceName }}
              </div>
              <PlanDetail :plan="schedule.plan" />
            </div>
            <div class="plan-box backup-plan">
              <div class="plan-name">
                <el-tag type="info" effect="plain">备选方案</el-tag>
                {{ schedule.backupPlan.spaceName }}
              </div>
              <PlanDetail :plan="schedule.backupPlan" />
            </div>
          </template>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'

import { agentSchedule, getAgentMetrics, simulateMonitor } from '@/api/monitor'

const loading = ref(false)
const simulating = ref(false)
const traceLoading = ref(false)

const metrics = reactive({})
const schedule = reactive({})

const degradedRate = computed(() =>
  metrics.degradedRate !== undefined ? metrics.degradedRate : 0,
)

// 内联小组件：方案明细
const PlanDetail = defineComponent({
  props: { plan: { type: Object, required: true } },
  setup(props) {
    return () =>
      h('div', { class: 'plan-detail' }, [
        h('div', null, `设备：ID ${props.plan.deviceIds.join('、')}`),
        h('div', null, `时间：${props.plan.startTime} ~ ${props.plan.endTime}`),
        h('div', { class: 'plan-reason' }, `理由：${props.plan.reason}`),
      ])
  },
})

function formatJson(value) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

async function loadMetrics() {
  loading.value = true
  try {
    const data = await getAgentMetrics(true)
    Object.assign(metrics, data)
  } finally {
    loading.value = false
  }
}

async function onSimulate() {
  simulating.value = true
  try {
    await simulateMonitor({
      count: 128,
      errorRatio: 0.04,
      degradedRatio: 0.1,
      latencyMs: 3200,
    })
    await loadMetrics()
  } finally {
    simulating.value = false
  }
}

async function onLoadTrace() {
  traceLoading.value = true
  try {
    const data = await agentSchedule({})
    Object.keys(schedule).forEach((key) => delete schedule[key])
    Object.assign(schedule, data)
  } finally {
    traceLoading.value = false
  }
}

onMounted(loadMetrics)
</script>

<style scoped>
.page-head {
  margin-bottom: 16px;
}

.kpi-row {
  margin-bottom: 16px;
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kpi-label {
  font-size: 13px;
  color: #909399;
}

.kpi-value {
  font-size: 30px;
  font-weight: 800;
  color: #303133;
}

.unit {
  font-size: 13px;
  font-weight: 500;
  color: #909399;
  margin-left: 3px;
}

.action-bar {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.step-no {
  font-weight: 700;
  font-size: 13px;
  color: #303133;
}

.step-result {
  font-size: 12.5px;
  color: #409eff;
  font-weight: 600;
}

.step-time {
  margin-left: auto;
  font-size: 11px;
  color: #909399;
  font-family: Consolas, monospace;
}

.step-thought {
  font-size: 12.5px;
  line-height: 1.7;
  color: #606266;
}

.step-action {
  font-size: 12.5px;
  color: #c47b16;
  font-weight: 600;
  margin-top: 4px;
}

.plan-card {
  min-height: 400px;
}

.confirm-alert {
  margin-bottom: 12px;
}

.plan-box {
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
}

.main-plan {
  background: linear-gradient(140deg, #eef5ff, #f5f0ff);
  border: 1px solid var(--sp-ai-line);
}

.backup-plan {
  background: #f7f9fc;
  border: 1px dashed var(--sp-border);
}

.plan-name {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

:deep(.plan-detail) {
  font-size: 12.5px;
  line-height: 1.9;
  color: #606266;
}

:deep(.plan-reason) {
  color: #909399;
  margin-top: 4px;
}
</style>
