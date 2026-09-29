<template>
  <div v-loading="loading">
    <div class="sp-pagebar">
      <h3>预约单管理</h3>
      <div class="sp-acts">
        <span class="sp-tag is-orange" v-if="counts[1]">待确认 {{ counts[1] }}</span>
        <span class="sp-tag is-green" v-if="counts[2]">已确认 {{ counts[2] }}</span>
        <button class="sp-btn is-ghost is-sm" @click="load">刷新</button>
      </div>
    </div>

    <!--
      这个页面是**本轮新增**的。
      在此之前 Web 端只有「预约日历」一个只读视图：订单被画成日历上的色块，
      看不到单号/场地/设备/状态，也没有任何地方能点「确认」。
      后果是状态机的主干路径 1(待确认) → 2(已确认) 在 Web 上根本走不通 ——
      Agent 建的单只能一直挂着，或者被取消掉。
    -->
    <div class="sp-ai-bar">
      <div class="sp-ic">📋</div>
      <span>
        数据来源 <b>GET /orders/my</b>（只返回<b>当前登录用户本人</b>的单，身份取自 JWT）。
        后端这个接口返回的是<b>裸数组</b>且<b>不支持分页</b>，所以下面的分页在前端切片完成。
      </span>
    </div>

    <div class="sp-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.value === null ? 'all' : tab.value"
        class="sp-tab"
        :class="{ 'is-on': activeTab === tab.value }"
        @click="activeTab = tab.value"
      >
        {{ tab.label }}
        <span class="tab-count">{{ tabCount(tab.value) }}</span>
      </button>
    </div>

    <div class="sp-card">
      <table class="sp-table">
        <thead>
          <tr>
            <th style="width: 76px">预约单</th>
            <th>场地</th>
            <th>时段</th>
            <th>设备</th>
            <th style="width: 84px">状态</th>
            <th style="width: 150px">创建时间</th>
            <th style="width: 190px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!pagedOrders.length">
            <td colspan="7" class="empty-cell">
              {{ loading ? '加载中…' : '这个状态下还没有预约单' }}
            </td>
          </tr>
          <tr
            v-for="order in pagedOrders"
            :key="order.orderId"
            :class="{ 'is-cancelled': order.orderStatus === 3 }"
          >
            <td><b>#{{ order.orderId }}</b></td>
            <td>{{ spaceName(order.spaceId) }}</td>
            <td class="time-cell">{{ order.startTime }}<br />{{ order.endTime }}</td>
            <td class="device-cell">{{ deviceNames(order.deviceIds) }}</td>
            <td>
              <span class="sp-tag" :class="statusTagClass(order.orderStatus)">
                {{ order.orderStatusText }}
              </span>
            </td>
            <td class="time-cell">{{ order.createTime }}</td>
            <td>
              <button class="link-btn" @click="openDetail(order)">详情</button>
              <button
                v-if="order.orderStatus === 1"
                class="link-btn is-primary"
                :disabled="actingId === order.orderId"
                @click="onConfirm(order)"
              >
                确认
              </button>
              <button
                v-if="order.orderStatus === 1 || order.orderStatus === 2"
                class="link-btn is-danger"
                :disabled="actingId === order.orderId"
                @click="onCancel(order)"
              >
                取消
              </button>
              <span v-if="order.orderStatus === 3 || order.orderStatus === 4" class="sp-muted">
                终态
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <div class="sp-pager" v-if="filteredOrders.length > pageSize">
        <span class="sp-muted">
          共 {{ filteredOrders.length }} 条 ｜ 第 {{ page }} / {{ totalPages }} 页
        </span>
        <button class="sp-btn is-ghost is-sm" :disabled="page <= 1" @click="page -= 1">
          上一页
        </button>
        <button
          class="sp-btn is-ghost is-sm"
          :disabled="page >= totalPages"
          @click="page += 1"
        >
          下一页
        </button>
      </div>
    </div>

    <!-- ==================== 详情抽屉 ==================== -->
    <el-drawer v-model="detailVisible" :title="detailTitle" size="520px">
      <template v-if="detail">
        <div class="sp-planbox" style="margin-bottom: 14px">
          <h4>预约 #{{ detail.orderId }}</h4>
          <div class="sp-line">
            {{ spaceName(detail.spaceId) }}<br />
            {{ detail.startTime }} ~ {{ detail.endTime }}<br />
            设备：{{ deviceNames(detail.deviceIds) }}
          </div>
        </div>

        <div class="sp-card" style="margin-bottom: 14px">
          <div class="sp-card-head"><b>基本信息</b></div>
          <div class="sp-mbrow">
            <span class="sp-k">状态</span>
            <span class="sp-v">
              <span class="sp-tag" :class="statusTagClass(detail.orderStatus)">
                {{ detail.orderStatusText }}
              </span>
            </span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">创建时间</span>
            <span class="sp-v">{{ detail.createTime }}</span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">更新时间</span>
            <span class="sp-v">{{ detail.updateTime }}</span>
          </div>
        </div>

        <!-- Agent 建的单一律带 agentRequest；手建的单这里是空的 -->
        <div v-if="detail.agentRequest" class="sp-card" style="margin-bottom: 14px">
          <div class="sp-card-head"><b>🤖 Agent 原始需求</b></div>
          <div class="sp-ask">
            <div class="sp-who"><span class="sp-live is-blue"></span> 用户口述 · 已规整</div>
            {{ detail.agentRequest }}
          </div>
        </div>

        <div v-if="detailTrace.length" class="sp-card" style="margin-bottom: 14px">
          <div class="sp-card-head">
            <b>🧠 当时的思考链</b>
            <span class="sp-grow"></span>
            <span class="sp-tag is-purple">{{ detailTrace.length }} 步</span>
          </div>
          <div class="sp-trace">
            <div v-for="step in detailTrace" :key="step.step" class="sp-tstep">
              <div class="sp-tnum" :class="step.action ? '' : 'is-g'">{{ step.step }}</div>
              <div class="sp-tb">
                <h5>
                  {{ step.result }}
                  <span v-if="step.action" class="sp-tag is-purple">{{ step.action }}</span>
                </h5>
                <p v-if="step.thought">{{ step.thought }}</p>
              </div>
            </div>
          </div>
        </div>

        <div class="drawer-acts">
          <button
            v-if="detail.orderStatus === 1"
            class="sp-btn is-ai is-block"
            :disabled="actingId === detail.orderId"
            @click="onConfirm(detail)"
          >
            确认该预约
          </button>
          <button
            v-if="detail.orderStatus === 1 || detail.orderStatus === 2"
            class="sp-btn is-ghost is-block"
            style="margin-top: 8px"
            :disabled="actingId === detail.orderId"
            @click="onCancel(detail)"
          >
            取消该预约
          </button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { ElMessage } from 'element-plus'

import { cancelOrder, confirmOrder, getMyOrders } from '@/api/orders'
import { getDevices, getSpaces } from '@/api/resources'
import { devicesOf, ordersOf, spacesOf } from '@/utils/normalize'

const loading = ref(false)
const actingId = ref(null)

const orders = ref([])

/** spaceId -> spaceName / deviceId -> deviceName。订单里只有 ID，名字得自己查真库补。 */
const spaceMap = ref(new Map())
const deviceMap = ref(new Map())

const activeTab = ref(null)

const page = ref(1)
const pageSize = 10

const detailVisible = ref(false)
const detail = ref(null)

/**
 * 状态取值以 app/state_machine.py::OrderStatus 为准：
 * 1 待确认 · 2 已确认 · **3 已取消** · **4 已完成**（3/4 很容易记反）。
 */
const tabs = [
  { label: '全部', value: null },
  { label: '待确认', value: 1 },
  { label: '已确认', value: 2 },
  { label: '已取消', value: 3 },
  { label: '已完成', value: 4 },
]

const counts = computed(() => {
  const map = {}
  for (const order of orders.value) {
    map[order.orderStatus] = (map[order.orderStatus] || 0) + 1
  }
  return map
})

const filteredOrders = computed(() =>
  activeTab.value === null
    ? orders.value
    : orders.value.filter((o) => o.orderStatus === activeTab.value),
)

const totalPages = computed(() => Math.max(1, Math.ceil(filteredOrders.value.length / pageSize)))

const pagedOrders = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredOrders.value.slice(start, start + pageSize)
})

const detailTitle = computed(() =>
  detail.value ? '预约单 #' + detail.value.orderId : '预约单详情',
)

/** agentTrace 的元素形状见 backend/app/schemas/agent.py::TraceStep */
const detailTrace = computed(() => {
  const t = detail.value && detail.value.agentTrace
  return Array.isArray(t) ? t : []
})

// 换筛选条件要回到第一页，否则会停在一个越界的页码上显示空白
watch(activeTab, () => {
  page.value = 1
})

function tabCount(value) {
  return value === null ? orders.value.length : counts.value[value] || 0
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

function spaceName(spaceId) {
  const name = spaceMap.value.get(Number(spaceId))
  return name || '场地 #' + spaceId
}

function deviceNames(deviceIds) {
  const ids = Array.isArray(deviceIds) ? deviceIds : []
  if (!ids.length) return '无'
  return ids
    .map((id) => deviceMap.value.get(Number(id)) || '#' + id)
    .join('、')
}

async function load() {
  loading.value = true
  try {
    orders.value = ordersOf(await getMyOrders()).sort((a, b) =>
      String(b.createTime).localeCompare(String(a.createTime)),
    )
    // 页码可能因为筛选/删除而越界
    if (page.value > totalPages.value) page.value = totalPages.value
  } finally {
    loading.value = false
  }
}

async function loadDictionaries() {
  // 补名字失败不该让整页打不开 —— 退化成显示 ID 即可
  try {
    spaceMap.value = new Map(
      spacesOf(await getSpaces()).map((s) => [Number(s.spaceId), s.spaceName]),
    )
  } catch {
    spaceMap.value = new Map()
  }
  try {
    deviceMap.value = new Map(
      devicesOf(await getDevices()).map((d) => [Number(d.deviceId), d.deviceName]),
    )
  } catch {
    deviceMap.value = new Map()
  }
}

function openDetail(order) {
  detail.value = order
  detailVisible.value = true
}

/**
 * 确认预约 —— 状态机 1 → 2。
 *
 * 后端只允许本人的单（越权一律 404），且状态不允许时返回 409「当前状态不允许确认」。
 * 两种情况 request.js 都会把后端原文弹出来，所以这里不自己编提示语。
 */
async function onConfirm(order) {
  actingId.value = order.orderId
  try {
    await confirmOrder(order.orderId)
    ElMessage.success('预约 #' + order.orderId + ' 已确认')
    await load()
    syncDetail(order.orderId)
  } catch {
    await load()
  } finally {
    actingId.value = null
  }
}

async function onCancel(order) {
  actingId.value = order.orderId
  try {
    await cancelOrder(order.orderId)
    ElMessage.success('预约 #' + order.orderId + ' 已取消')
    await load()
    syncDetail(order.orderId)
  } catch {
    await load()
  } finally {
    actingId.value = null
  }
}

/** 抽屉里点完按钮，抽屉里那份数据也得跟着更新，否则显示的还是旧状态。 */
function syncDetail(orderId) {
  if (!detail.value || detail.value.orderId !== orderId) return
  detail.value = orders.value.find((o) => o.orderId === orderId) || detail.value
}

onMounted(async () => {
  await Promise.all([load(), loadDictionaries()])
})
</script>

<style scoped>
.tab-count {
  font-size: 11px;
  color: var(--sp-t3);
  margin-left: 4px;
}

.empty-cell {
  text-align: center;
  color: var(--sp-t3);
  padding: 40px 0;
}

.time-cell {
  font-size: 11.5px;
  color: var(--sp-t3);
  line-height: 1.6;
  font-family: ui-monospace, Consolas, monospace;
}

.device-cell {
  font-size: 12px;
  max-width: 200px;
}

/* 已取消的单视觉上退到后面，避免和生效中的单抢注意力 */
.is-cancelled td {
  opacity: 0.55;
}

.link-btn {
  background: none;
  border: none;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--sp-t2);
  cursor: pointer;
  padding: 0 8px 0 0;
}

.link-btn:hover {
  color: var(--sp-accent);
}

.link-btn.is-primary {
  color: var(--sp-accent);
  font-weight: 600;
}

.link-btn.is-danger {
  color: var(--sp-danger);
}

.link-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.drawer-acts {
  padding-top: 4px;
}
</style>
