<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">预约日历</h1>
      <p class="sp-page-sub">以周/日视图查看全部预约，右侧为 AI 软冲突预警（数据来源：/orders、/conflicts）</p>
    </div>

    <el-row :gutter="16">
      <el-col :span="17">
        <div class="sp-card">
          <FullCalendar :options="calendarOptions" />
        </div>
      </el-col>
      <el-col :span="7">
        <div class="sp-card conflict-panel">
          <div class="sp-section-title">
            AI 冲突预警
            <el-button text type="primary" size="small" class="rescan-btn" @click="loadData">
              <el-icon><Refresh /></el-icon>扫描
            </el-button>
          </div>
          <el-empty v-if="!conflicts.length" description="未发现资源冲突" :image-size="70" />
          <div v-for="(item, index) in conflicts" :key="index" class="conflict-item">
            <div class="conflict-head">
              <el-tag type="warning" effect="dark" size="small">{{ item.conflictType }}</el-tag>
              <span class="conflict-orders">订单 #{{ item.orderIds.join(' / #') }}</span>
            </div>
            <div class="conflict-suggestion">{{ item.suggestion }}</div>
          </div>
          <div class="panel-tip">硬冲突（时间完全重叠）自动拦截；软冲突（设备共享/容量接近）由 AI 识别并给出改约建议。</div>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import FullCalendar from '@fullcalendar/vue3'
import timeGridPlugin from '@fullcalendar/timegrid'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import { onMounted, reactive, ref } from 'vue'

import { scanConflicts } from '@/api/conflicts'
import { getMyOrders } from '@/api/orders'

const loading = ref(false)
const conflicts = reactive([])

function toEvent(order) {
  return {
    title: `${order.spaceName}（${order.orderNo}）`,
    start: order.startTime.replace(' ', 'T'),
    end: order.endTime.replace(' ', 'T'),
    backgroundColor: '#409eff',
    borderColor: '#409eff',
    extendedProps: { statusText: order.statusText },
  }
}

const calendarOptions = reactive({
  plugins: [timeGridPlugin, dayGridPlugin, interactionPlugin],
  initialView: 'timeGridWeek',
  locale: 'zh-cn',
  height: 620,
  slotMinTime: '08:00:00',
  slotMaxTime: '21:30:00',
  nowIndicator: true,
  headerToolbar: {
    left: 'prev,next today',
    center: 'title',
    right: 'timeGridWeek,timeGridDay,dayGridMonth',
  },
  buttonText: { today: '今天', week: '周', day: '日', month: '月' },
  events: [],
  eventDidMount(info) {
    if (info.event.extendedProps.statusText) {
      info.el.title = info.event.extendedProps.statusText
    }
  },
})

async function loadData() {
  loading.value = true
  try {
    const [ordersData, conflictsData] = await Promise.all([
      getMyOrders({ page: 1, pageSize: 50 }),
      scanConflicts(),
    ])

    calendarOptions.events = (ordersData.list || []).map(toEvent)
    if (ordersData.list?.[0]) {
      calendarOptions.initialDate = ordersData.list[0].startTime.slice(0, 10)
    }

    conflicts.splice(0, conflicts.length, ...conflictsData)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.page-head {
  margin-bottom: 16px;
}

:deep(.fc) {
  font-size: 12px;
}

:deep(.fc-toolbar-title) {
  font-size: 15px;
  font-weight: 600;
}

:deep(.fc-button-primary) {
  background-color: #409eff;
  border-color: #409eff;
}

:deep(.fc-button-primary:disabled),
:deep(.fc-button-primary:not(:disabled).fc-button-active),
:deep(.fc-button-primary:not(:disabled):active) {
  background-color: #337ecc;
  border-color: #337ecc;
}

:deep(.fc-event) {
  cursor: pointer;
  padding: 2px 4px;
}

:deep(.fc-day-today) {
  background-color: #ecf5ff !important;
}

:deep(.fc-col-header-cell.fc-day-today) {
  background-color: #d9ecff !important;
}

.conflict-panel {
  min-height: 660px;
}

.rescan-btn {
  margin-left: auto;
}

.conflict-item {
  border: 1px solid #f0e2c8;
  background: #fdf8ef;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.conflict-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.conflict-orders {
  font-size: 12px;
  color: #b88230;
}

.conflict-suggestion {
  font-size: 12.5px;
  line-height: 1.7;
  color: #8a6d3b;
}

.panel-tip {
  margin-top: 14px;
  font-size: 11.5px;
  color: #909399;
  line-height: 1.7;
  border-top: 1px dashed var(--sp-border);
  padding-top: 12px;
}
</style>
