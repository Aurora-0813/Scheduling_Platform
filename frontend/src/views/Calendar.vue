<template>
  <div v-loading="loading">
    <div class="sp-pagebar">
      <h3>预约日历 · AI 冲突预警</h3>
      <div class="sp-acts">
        <span class="sp-tag is-blue">已确认</span>
        <span class="sp-tag is-purple">待确认</span>
        <span class="sp-tag is-green">已完成</span>
        <span class="sp-tag is-gray">已取消</span>
        <span class="sp-tag is-red">硬冲突</span>
        <button class="sp-btn is-ghost is-sm" @click="loadData">扫描</button>
        <router-link to="/agent" class="sp-btn is-ai is-sm">＋ 新建预约</router-link>
      </div>
    </div>

    <div class="calwrap">
      <div class="sp-card calcard">
        <!--
          保留 FullCalendar 引擎而不是照原型手搓一套周网格：
          它已经接的是真实数据、支持周/日/月三种视图与真实时区处理，
          手搓一套只会把这些能力退化成「只有周视图、只有本机时区」。
          这里做的是**换皮**：把事件颜色、表头、今天的底色换成设计令牌。
        -->
        <FullCalendar :options="calendarOptions" />

        <div class="cal-tip">
          <span class="sp-muted">
            事件颜色即状态；<b>点任意一条预约</b>可以直接看详情并确认/取消。
            日历只显示<b>你本人</b>的预约（GET /orders/my 的口径）。
          </span>
        </div>
      </div>

      <div class="sp-card radar-panel">
        <div class="sp-card-head">
          <b>🚨 AI 软冲突雷达</b>
          <span class="sp-grow"></span>
          <span class="sp-tag" :class="conflicts.length ? 'is-red' : 'is-gray'">
            {{ conflicts.length }} 条
          </span>
        </div>

        <div class="sp-radar">
          <i></i><i></i><i></i>
          <div class="sp-sweep"></div>
          <div class="sp-ping"></div>
        </div>

        <div v-if="!conflicts.length" class="sp-muted radar-empty">未发现资源冲突。</div>

        <div
          v-for="(item, index) in conflicts"
          :key="index"
          class="sp-witem"
          :class="conflictClass(item)"
        >
          <b>{{ item.conflictType || '冲突' }} · 预约 {{ orderRefs(item) }}</b>
          <p>{{ item.suggestion }}</p>
          <span v-if="item.ruleCode" class="sp-tag is-gray">{{ item.ruleCode }}</span>
        </div>

        <div class="panel-tip">
          硬冲突（时段完全重叠）由事务层直接拦截；软冲突（设备共享 / 容量接近 / 高价值设备低效占用）
          由规则引擎识别并给出改约建议。
        </div>
      </div>
    </div>

    <!-- ==================== 预约详情抽屉 ==================== -->
    <el-drawer v-model="detailVisible" :title="drawerTitle" size="460px">
      <template v-if="detail">
        <div class="sp-planbox" style="margin-bottom: 14px">
          <h4>预约 #{{ detail.orderId }}</h4>
          <div class="sp-line">
            {{ spaceLabel(detail.spaceId) }}<br />
            {{ detail.startTime }} ~ {{ detail.endTime }}
          </div>
        </div>

        <div class="sp-card">
          <div class="sp-mbrow">
            <span class="sp-k">状态</span>
            <span class="sp-v">
              <span class="sp-tag" :class="statusTagClass(detail.orderStatus)">
                {{ detail.orderStatusText }}
              </span>
            </span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">设备</span>
            <span class="sp-v">{{ deviceLabel(detail.deviceIds) }}</span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">创建时间</span>
            <span class="sp-v">{{ detail.createTime }}</span>
          </div>
          <div class="sp-mbrow" v-if="detail.agentRequest">
            <span class="sp-k">Agent 需求</span>
            <span class="sp-v">{{ detail.agentRequest }}</span>
          </div>
        </div>

        <div class="drawer-acts">
          <button
            v-if="detail.orderStatus === 1"
            class="sp-btn is-ai is-block"
            :disabled="acting"
            @click="onConfirm"
          >
            确认该预约
          </button>
          <button
            v-if="detail.orderStatus === 1 || detail.orderStatus === 2"
            class="sp-btn is-ghost is-block"
            style="margin-top: 8px"
            :disabled="acting"
            @click="onCancel"
          >
            取消该预约
          </button>
          <router-link to="/orders" class="sp-btn is-ghost is-block" style="margin-top: 8px">
            去预约单管理
          </router-link>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import timeGridPlugin from '@fullcalendar/timegrid'
import { computed, onMounted, reactive, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { scanConflicts } from '@/api/conflicts'
import { cancelOrder, confirmOrder, getMyOrders } from '@/api/orders'
import { getDevices, getSpaces } from '@/api/resources'
import { devicesOf, listOf, ordersOf, spacesOf } from '@/utils/normalize'

const loading = ref(false)
const acting = ref(false)
const conflicts = reactive([])

/** 场地 id → 场地名。订单本身不带 spaceName，得靠这张表补。 */
const spaceNameById = ref({})
/** 设备 id → 设备名。同理。 */
const deviceNameById = ref({})

const detailVisible = ref(false)
const detail = ref(null)

/**
 * 事件颜色按**真实状态**上色（取值见 app/state_machine.py::OrderStatus）：
 * 1 待确认紫 · 2 已确认蓝 · 3 已取消灰 · 4 已完成绿。
 */
const STATUS_COLOR = {
  1: '#7c5cff',
  2: '#409eff',
  3: '#b6bec9',
  4: '#67c23a',
}

const drawerTitle = computed(() =>
  detail.value ? '预约单 #' + detail.value.orderId : '预约详情',
)

function spaceLabel(spaceId) {
  return spaceNameById.value[spaceId] || '场地 #' + spaceId
}

function deviceLabel(deviceIds) {
  const ids = Array.isArray(deviceIds) ? deviceIds : []
  if (!ids.length) return '无'
  return ids.map((id) => deviceNameById.value[id] || '#' + id).join('、')
}

function statusTagClass(status) {
  switch (status) {
    case 2:
      return 'is-green'
    case 3:
      return 'is-gray'
    case 4:
      return 'is-blue'
    default:
      return 'is-orange'
  }
}

function toEvent(order) {
  const color = STATUS_COLOR[order.orderStatus] || '#409eff'
  return {
    // 真实订单没有 orderNo 字段，标题用订单号 —— 拼 order.orderNo 会渲染成 undefined
    title: spaceLabel(order.spaceId) + '（#' + order.orderId + '）',
    start: String(order.startTime).replace(' ', 'T'),
    end: String(order.endTime).replace(' ', 'T'),
    backgroundColor: color,
    borderColor: color,
    // 整条订单带着走，点击时不用再问一次后端
    extendedProps: { order },
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
  /**
   * **这是本轮补上的缺口。**
   * 原先日历是纯只读的：事件画出来就完了，点不动，也进不了详情，
   * 于是「看到一条待确认的预约」和「把它确认掉」之间没有任何通路。
   */
  eventClick(info) {
    openDetail(info.event.extendedProps.order)
  },
  eventDidMount(info) {
    const order = info.event.extendedProps.order
    if (!order) return
    info.el.title = spaceLabel(order.spaceId) + '（#' + order.orderId + '）· ' + order.orderStatusText
  },
})

function openDetail(order) {
  if (!order) return
  detail.value = order
  detailVisible.value = true
}

async function loadData() {
  loading.value = true
  try {
    const [ordersData, conflictsData, spacesData, devicesData] = await Promise.all([
      getMyOrders(),
      scanConflicts(),
      getSpaces(),
      getDevices(),
    ])

    // 真实接口 /orders/my 返回**裸数组**（不是 {list:[…]}），字段是 orderId/orderStatus ——
    // 原先 ordersData.list || [] 拿到 undefined，日历一个事件都没有。见 utils/normalize.js。
    const orders = ordersOf(ordersData)
    // 订单里**没有 spaceName / deviceName**（只有 ID），要另外查表做映射，
    // 否则事件标题会渲染成「（undefined）」。
    spaceNameById.value = Object.fromEntries(
      spacesOf(spacesData).map((s) => [s.spaceId, s.spaceName]),
    )
    deviceNameById.value = Object.fromEntries(
      devicesOf(devicesData).map((d) => [d.deviceId, d.deviceName]),
    )

    calendarOptions.events = orders.map(toEvent)
    if (orders[0]) {
      calendarOptions.initialDate = String(orders[0].startTime).slice(0, 10)
    }

    // 冲突扫描返回的同样是裸数组
    conflicts.splice(0, conflicts.length, ...listOf(conflictsData))
  } finally {
    loading.value = false
  }
}

/** 硬冲突给红，其余给蓝 —— 与原型 .witem / .witem.blue 的语义一致。 */
function conflictClass(item) {
  const type = String((item && item.conflictType) || '')
  return type.includes('硬') ? 'is-red' : 'is-blue'
}

function orderRefs(item) {
  const ids = Array.isArray(item && item.orderIds) ? item.orderIds : []
  return ids.length ? '#' + ids.join(' / #') : '—'
}

async function onConfirm() {
  if (!detail.value) return
  acting.value = true
  try {
    await confirmOrder(detail.value.orderId)
    ElMessage.success('预约 #' + detail.value.orderId + ' 已确认')
    await loadData()
    detailVisible.value = false
  } catch {
    // 409（状态不允许）等由 request.js 弹出后端原文
  } finally {
    acting.value = false
  }
}

async function onCancel() {
  if (!detail.value) return
  acting.value = true
  try {
    await cancelOrder(detail.value.orderId)
    ElMessage.success('预约 #' + detail.value.orderId + ' 已取消')
    await loadData()
    detailVisible.value = false
  } catch {
    // 同上
  } finally {
    acting.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.calwrap {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.calcard {
  flex: 1;
  min-width: 0;
}

.radar-panel {
  width: 316px;
  flex: none;
}

.radar-empty {
  text-align: center;
  padding: 12px 0 18px;
}

.cal-tip {
  margin-top: 13px;
  padding-top: 12px;
  border-top: 1px dashed var(--sp-border-l);
  line-height: 1.7;
}

.panel-tip {
  margin-top: 14px;
  font-size: 11.5px;
  color: var(--sp-t3);
  line-height: 1.7;
  border-top: 1px dashed var(--sp-border-l);
  padding-top: 12px;
}

.drawer-acts {
  margin-top: 14px;
}

/* ---------------- FullCalendar 换皮 ---------------- */
:deep(.fc) {
  font-size: 12px;
}

:deep(.fc-toolbar-title) {
  font-size: 15px;
  font-weight: 600;
  color: var(--sp-text);
}

:deep(.fc-button-primary) {
  background-color: #fff;
  border-color: var(--sp-border);
  color: var(--sp-t2);
  font-size: 12px;
  box-shadow: none;
  text-transform: none;
}

:deep(.fc-button-primary:hover) {
  background-color: var(--sp-ai-soft);
  border-color: var(--sp-ai-line);
  color: var(--sp-accent);
}

:deep(.fc-button-primary:disabled),
:deep(.fc-button-primary:not(:disabled).fc-button-active),
:deep(.fc-button-primary:not(:disabled):active) {
  background-color: var(--sp-accent);
  border-color: var(--sp-accent);
  color: #fff;
}

:deep(.fc-event) {
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
  font-size: 11px;
}

:deep(.fc-col-header-cell) {
  background: #fafafa;
  font-weight: 500;
}

:deep(.fc-day-today) {
  background-color: #f5faff !important;
}

:deep(.fc-col-header-cell.fc-day-today) {
  background-color: #e8f3ff !important;
  color: var(--sp-accent);
}
</style>
