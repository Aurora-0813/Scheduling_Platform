<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">AI 数据洞察</h1>
      <p class="sp-page-sub">基于预约与设备数据自动生成的运营分析（数据来源：/dashboard/*）</p>
    </div>

    <!-- KPI -->
    <el-row :gutter="16" class="kpi-row">
      <el-col :span="8">
        <div class="sp-card kpi-card">
          <div class="kpi-label">空间使用率</div>
          <div class="kpi-value">{{ stats.spaceUsageRate ?? '--' }}<span class="kpi-unit">%</span></div>
          <div class="kpi-foot">近 7 日全场地加权</div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="sp-card kpi-card">
          <div class="kpi-label">设备闲置率</div>
          <div class="kpi-value">{{ stats.deviceIdleRate ?? '--' }}<span class="kpi-unit">%</span></div>
          <div class="kpi-foot">可调度设备空闲占比</div>
        </div>
      </el-col>
      <el-col :span="8">
        <div class="sp-card kpi-card">
          <div class="kpi-label">AI 洞察建议</div>
          <div class="kpi-value">{{ report.suggestions?.length ?? 0 }}<span class="kpi-unit">条</span></div>
          <div class="kpi-foot">含证据链与优化建议</div>
        </div>
      </el-col>
    </el-row>

    <!-- 图表 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="14">
        <div class="sp-card">
          <div class="sp-section-title">预约高峰时段分布</div>
          <div ref="peakChartRef" class="chart-box"></div>
        </div>
      </el-col>
      <el-col :span="10">
        <div class="sp-card">
          <div class="sp-section-title">设备故障频次</div>
          <div ref="faultChartRef" class="chart-box"></div>
        </div>
      </el-col>
    </el-row>

    <!-- AI 报告 -->
    <div class="sp-card report-card">
      <div class="sp-section-title">
        AI 洞察报告
        <el-button text type="primary" class="report-export" @click="onExport">
          <el-icon><Download /></el-icon>导出报告
        </el-button>
      </div>
      <el-empty v-if="!report.suggestions?.length" description="暂无报告" />
      <div v-for="(item, index) in report.suggestions" :key="index" class="report-item">
        <div class="report-index">{{ index + 1 }}</div>
        <div class="report-body">
          <div class="report-finding">发现：{{ item.finding }}</div>
          <div class="report-evidence">证据：{{ item.evidence }}</div>
          <div class="report-suggestion">建议：{{ item.suggestion }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { getDashboardReport, getDashboardStats } from '@/api/dashboard'

const loading = ref(false)
const peakChartRef = ref()
const faultChartRef = ref()

const stats = reactive({})
const report = reactive({})

let peakChart = null
let faultChart = null

function renderPeakChart(peakHours = []) {
  peakChart = echarts.init(peakChartRef.value)
  peakChart.setOption({
    grid: { left: 44, right: 20, top: 24, bottom: 36 },
    tooltip: { trigger: 'axis', formatter: '{b} 点：{c0} 次预约' },
    xAxis: {
      type: 'category',
      data: peakHours.map((item) => `${item.hour}:00`),
      axisLine: { lineStyle: { color: '#c4d0cd' } },
      axisLabel: { color: '#6b7c79' },
    },
    yAxis: {
      type: 'value',
      name: '预约次数',
      nameTextStyle: { color: '#8a9794' },
      splitLine: { lineStyle: { color: '#eef2f1' } },
      axisLabel: { color: '#6b7c79' },
    },
    series: [
      {
        type: 'bar',
        data: peakHours.map((item) => item.count),
        barWidth: 28,
        itemStyle: {
          borderRadius: [5, 5, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#2e8b76' },
            { offset: 1, color: '#8fc7b8' },
          ]),
        },
      },
    ],
  })
}

function renderFaultChart(faultFrequency = []) {
  faultChart = echarts.init(faultChartRef.value)
  faultChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c} 次（{d}%）' },
    legend: { bottom: 0, textStyle: { color: '#6b7c79' } },
    color: ['#1e6b5c', '#5fb89f', '#b7791f', '#8a9794'],
    series: [
      {
        type: 'pie',
        radius: ['45%', '68%'],
        center: ['50%', '44%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2 },
        label: { formatter: '{b}\n{c} 次', color: '#6b7c79' },
        data: faultFrequency.map((item) => ({ name: item.deviceType, value: item.count })),
      },
    ],
  })
}

function onResize() {
  peakChart?.resize()
  faultChart?.resize()
}

function onExport() {
  if (report.exportUrl) {
    window.open(report.exportUrl)
  }
}

onMounted(async () => {
  loading.value = true
  try {
    const [statsData, reportData] = await Promise.all([getDashboardStats(), getDashboardReport()])
    Object.assign(stats, statsData)
    Object.assign(report, reportData)
    renderPeakChart(statsData.peakHours)
    renderFaultChart(statsData.faultFrequency)
    window.addEventListener('resize', onResize)
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  peakChart?.dispose()
  faultChart?.dispose()
})
</script>

<style scoped>
.page-head {
  margin-bottom: 16px;
}

.kpi-row {
  margin-bottom: 16px;
}

.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kpi-label {
  font-size: 13px;
  color: #7a8a87;
}

.kpi-value {
  font-size: 34px;
  font-weight: 800;
  color: #143d36;
  line-height: 1.1;
}

.kpi-unit {
  font-size: 14px;
  font-weight: 500;
  color: #8a9794;
  margin-left: 4px;
}

.kpi-foot {
  font-size: 12px;
  color: #a0acaa;
}

.chart-row {
  margin-bottom: 16px;
}

.chart-box {
  height: 280px;
}

.report-card {
  margin-bottom: 8px;
}

.report-export {
  margin-left: auto;
}

.report-item {
  display: flex;
  gap: 14px;
  padding: 14px 0;
  border-top: 1px dashed #e1e9e6;
}

.report-item:first-of-type {
  border-top: none;
}

.report-index {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #e3eeeb;
  color: #1e6b5c;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.report-body {
  font-size: 13px;
  line-height: 1.9;
}

.report-finding {
  font-weight: 600;
  color: #2c3e3b;
}

.report-evidence {
  color: #7a8a87;
}

.report-suggestion {
  color: #1e6b5c;
}
</style>
