<template>
  <div v-loading="loading">
    <div class="sp-pagebar">
      <h3>预约日历 · AI 冲突预警</h3>
      <div class="sp-acts">
        <span class="sp-tag is-purple">待确认</span>
        <span class="sp-tag is-blue">已确认</span>
        <span class="sp-tag is-gray">历史单</span>
        <span class="sp-tag is-orange">非开放时段</span>
        <button class="sp-btn is-ghost is-sm" @click="loadData">扫描</button>
        <router-link to="/agent" class="sp-btn is-ai is-sm">＋ 新建预约</router-link>
      </div>
    </div>

    <div class="calwrap">
      <div class="sp-card calcard">
        <div class="toolbar">
          <div class="tb-left">
            <button class="tb-nav" @click="shift(-1)">‹</button>
            <button class="tb-nav" @click="goToday">今天</button>
            <button class="tb-nav" @click="shift(1)">›</button>
            <span class="tb-date">{{ anchorLabel }}</span>
          </div>
          <div class="tb-right">
            <div class="seg">
              <button :class="{ on: view === 'day' }" @click="view = 'day'">日</button>
              <button :class="{ on: view === 'week' }" @click="view = 'week'">周</button>
            </div>
            <div class="seg">
              <button :class="{ on: rowMode === 'space' }" @click="rowMode = 'space'">按场地</button>
              <button :class="{ on: rowMode === 'device' }" @click="rowMode = 'device'">按设备</button>
            </div>
            <el-checkbox v-model="showHistory" size="small">显示历史单</el-checkbox>
          </div>
        </div>

        <!-- ============ 日视图：资源时间线 ============ -->
        <div v-if="view === 'day'" class="tl">
          <div class="tl-row tl-head">
            <div class="tl-name tl-name-head">{{ rowMode === 'space' ? '场地' : '设备' }}</div>
            <div class="tl-track">
              <div
                v-for="m in hourMarks"
                :key="'h' + m"
                class="tl-mark"
                :style="{ left: pct(m) + '%' }"
              >{{ hhmm(m) }}</div>
            </div>
          </div>

          <div v-if="!rowList.length" class="tl-empty">暂无{{ rowMode === 'space' ? '场地' : '设备' }}数据</div>

          <div
            v-for="r in rowList"
            :key="r.key"
            class="tl-row"
            :style="{ height: rowHeight + 'px' }"
          >
            <div class="tl-name" :title="r.sub">
              <span class="tl-name-t">{{ r.name }}</span>
              <span v-if="r.badge" class="tl-name-b">{{ r.badge }}</span>
            </div>
            <div class="tl-track" @click="onTrackClick($event, r)">
              <div v-if="r.closedLeft" class="tl-closed" :style="{ left: 0, width: pct(r.closedLeft) + '%' }"></div>
              <div
                v-if="r.closedRight !== null"
                class="tl-closed"
                :style="{ left: pct(r.closedRight) + '%', right: 0 }"
              ></div>

              <div
                v-for="m in hourMarks"
                :key="'v' + m"
                class="tl-vline"
                :style="{ left: pct(m) + '%' }"
              ></div>

              <div v-if="nowLeft !== null" class="tl-now" :style="{ left: nowLeft + '%' }"></div>

              <div
                v-for="b in r.bars"
                :key="b.key"
                class="tl-bar"
                :class="b.cls"
                :style="barStyle(b)"
                :title="b.tip"
                @click.stop="openDetail(b.order)"
              >
                <span class="tl-bar-t">{{ b.label }}</span>
              </div>
            </div>
          </div>

          <div class="cal-tip">
            <span class="sp-muted">
              每行是一个{{ rowMode === 'space' ? '场地' : '设备' }}，同一时段不同行天然不重叠；
              <b>点空白处直接建预约</b>，点已存在的单看详情 / 确认 / 取消。
              <span class="tip-dim">灰色斜纹 = 该行不开放的时段。</span>
            </span>
          </div>
        </div>

        <!-- ============ 周视图：容量热力 ============ -->
        <div v-else class="wk">
          <div class="wk-row wk-head">
            <div class="wk-name">周视图 · 每日活跃单</div>
            <div v-for="d in weekDays" :key="d.key" class="wk-cell" :class="{ 'is-today': d.isToday }">
              <b>{{ d.label }}</b>
              <span>{{ d.sub }}</span>
            </div>
            <div class="wk-sum">合计</div>
          </div>
          <div v-for="r in rowList" :key="r.key" class="wk-row">
            <div class="wk-name" :title="r.sub">{{ r.name }}</div>
            <div
              v-for="d in weekDays"
              :key="r.key + d.key"
              class="wk-cell wk-click"
              :class="heatClass(r, d.key)"
              :title="heatTip(r, d.key)"
              @click="jumpTo(d.key)"
            >{{ heatCount(r, d.key) || '' }}</div>
            <div class="wk-sum">{{ weekRowTotal(r) || '' }}</div>
          </div>
          <div class="cal-tip">
            <span class="sp-muted">
              格子里的数字 = 该行当天的活跃单数量，颜色越深越满。
              <b>点任意格子</b>跳到那一天的日视图。
            </span>
          </div>
        </div>
      </div>

      <div class="sp-card radar-panel">
        <div class="sp-card-head">
          <b>软冲突雷达</b>
          <span class="sp-grow"></span>
          <!--
            扫描中不显示「0 条」：条目数在结果回来之前是未知的，
            先摆一个 0 会让人以为「扫完了，没冲突」，然后数字突然跳到 3。
          -->
          <span v-if="conflictsLoading" class="sp-tag is-gray">扫描中…</span>
          <span v-else class="sp-tag" :class="conflicts.length ? 'is-red' : 'is-gray'">
            {{ conflicts.length }} 条
          </span>
        </div>

        <div class="sp-radar">
          <i></i><i></i><i></i>
          <div class="sp-sweep"></div>
          <div class="sp-ping"></div>
        </div>

        <!--
          扫描中只提示、不显示「未发现资源冲突」——
          后者是**结论**，只能用来说明「扫过了且没有」，不能用来说明「还没扫」。
        -->
        <div v-if="conflictsLoading" class="sp-muted radar-empty">正在扫描资源冲突…</div>
        <div v-else-if="!conflicts.length" class="sp-muted radar-empty">未发现资源冲突。</div>

        <div
          v-for="(item, index) in conflicts"
          :key="index"
          class="sp-witem"
          :class="conflictClass(item)"
        >
          <b>{{ conflictTitle(item) }}</b>
          <p v-if="conflictSubject(item)" class="cf-subject">{{ conflictSubject(item) }}</p>
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
          <div class="sp-mbrow" v-if="detail.username">
            <span class="sp-k">预约人</span>
            <span class="sp-v">{{ detail.username }}</span>
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

    <!-- ==================== 点空白处：直接建预约 ==================== -->
    <el-dialog v-model="createDialog.visible" title="新建预约" width="520px">
      <el-form label-width="82px">
        <el-form-item label="场地">
          <el-select v-model="createDialog.spaceId" placeholder="请选择场地" filterable style="width: 100%">
            <el-option
              v-for="s in spaces"
              :key="s.spaceId"
              :label="s.spaceName + '（' + s.capacity + ' 人 · ' + (s.location || '—') + '）'"
              :value="s.spaceId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker
            v-model="createDialog.date"
            type="date"
            value-format="YYYY-MM-DD"
            style="width: 100%"
            @change="reloadDialogDevices"
          />
        </el-form-item>
        <el-form-item label="时间">
          <div class="cd-time">
            <el-time-select
              v-model="createDialog.start"
              start="00:00"
              step="00:15"
              end="23:45"
              placeholder="开始"
              @change="reloadDialogDevices"
            />
            <span class="cd-sep">~</span>
            <el-time-select
              v-model="createDialog.end"
              start="00:15"
              step="00:15"
              end="23:59"
              placeholder="结束"
            />
          </div>
        </el-form-item>
        <el-form-item label="设备">
          <div v-if="createDialog.devicesLoading" class="sp-muted">查询中…</div>
          <div v-else-if="!createDialog.devices.length" class="sp-muted">暂无可用设备</div>
          <el-checkbox-group v-else v-model="createDialog.deviceIds" class="cd-devs">
            <el-checkbox
              v-for="d in createDialog.devices"
              :key="d.deviceId"
              :value="String(d.deviceId)"
              :disabled="d.remainingCount <= 0"
            >
              {{ d.deviceName }}
              <span class="cd-rest" :class="{ 'is-zero': d.remainingCount <= 0 }">
                {{ d.remainingCount > 0 ? '剩 ' + d.remainingCount : '已借满' }}
              </span>
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="createDialog.submitting" @click="submitCreate">
          生成预约单
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
/**
 * 预约日历（2026-10-13 重构）
 *
 * 为什么不再用 FullCalendar 画事件：
 *   原先是一周视图里把所有订单画成并列色块。两个问题叠加导致「同一时段的预约叠在一起」：
 *     ① 把 22 条订单**全**画出来，其中 12 条（55%）是已取消/已完成/已过期 —— 废单在和新单抢位置；
 *     ② 一周 7 天挤一行，同一天里 10 个场地还得再并排切列，一条只剩 1/3 宽度，字都放不下。
 *   实测最挤的那天同一时刻 3 条重叠，**4 条里全是废单**，那天活跃单是 0。
 *
 * 现在改成**资源时间线**：每行一个场地（或设备），横向是时间。
 *   · 同一时段不同场地天然在不同行 → 永远不会叠
 *   · 同一时段同一场地：建单时已做冲突判重，活跃单不可能重叠
 *   · 历史单统一走「车道装箱」，排到活跃单下面，默认不显示
 *
 * 顺带补齐：非开放时段遮灰、点空白直接建预约、周视图看容量。
 * 右侧的 AI 软冲突雷达与详情抽屉保持原样。
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { scanConflicts } from '@/api/conflicts'
import { cancelOrder, confirmOrder, createOrder, getAllOrders, getMyOrders } from '@/api/orders'
import { getAvailableDevices, getDevices, getSpaces } from '@/api/resources'
import { useAuthStore } from '@/store/auth'
import { devicesOf, listOf, ordersOf, spacesOf } from '@/utils/normalize'

const authStore = useAuthStore()

/** 管理视角：有 order:approve 才看得到全库（与后端 /orders/all 同源） */
const canManage = computed(() => authStore.hasPermission('order:approve'))

const loading = ref(false)
const acting = ref(false)
const conflicts = reactive([])
/**
 * AI 软冲突扫描是否在飞。
 *
 * 单独一个 ref 而不是复用 loading：日历的数据与雷达的数据是**两次独立等待**，
 * 共用一个开关会让日历出来之后雷达还显示「加载中」，或者反过来 —— 都不对。
 */
const conflictsLoading = ref(false)

const view = ref('day')
const rowMode = ref('space')
/** 历史单默认不画 —— 这是「乱」的主因（55% 是废单） */
const showHistory = ref(false)

const orders = ref([])
const spaces = ref([])
const devices = ref([])

const detailVisible = ref(false)
const detail = ref(null)

/** 当前锚定日期 YYYY-MM-DD */
const anchor = ref('')

/** 活跃单：建单判重只针对这两个状态 */
const ACTIVE_STATUS = [1, 2]

const STATUS_COLOR = {
  1: 'var(--sp-cat-purple)',
  2: 'var(--sp-accent)',
  3: '#b6bec9',
  4: '#67c23a',
  5: 'var(--sp-t3)',
}

const WEEKDAY_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

// ---------------------------------------------------------------- 时间工具
function pad2(n) {
  return n < 10 ? '0' + n : String(n)
}
function dayOf(v) {
  return String(v || '').slice(0, 10)
}
/** 取 YYYY-MM-DD HH:mm:ss 的「当天第几分钟」 */
function minOf(v) {
  const s = String(v || '')
  if (s.length < 16) return 0
  return Number(s.slice(11, 13)) * 60 + Number(s.slice(14, 16))
}
function hhmm(min) {
  return pad2(Math.floor(min / 60)) + ':' + pad2(min % 60)
}
function todayStr() {
  const d = new Date()
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}
function shiftDate(key, days) {
  const d = new Date(String(key).replace(/-/g, '/'))
  d.setDate(d.getDate() + days)
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}
/** 周一为一周之首 */
function mondayOf(key) {
  const d = new Date(String(key).replace(/-/g, '/'))
  const w = d.getDay() === 0 ? 7 : d.getDay()
  d.setDate(d.getDate() - (w - 1))
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}
/** HH:mm:ss → 当天第几分钟；空值返回 null（表示不限） */
function toOpenMin(v) {
  const s = String(v || '')
  if (s.length < 5) return null
  return Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5))
}

// ---------------------------------------------------------------- 数据加工
const dayOrders = computed(() => orders.value.filter((o) => dayOf(o.startTime) === anchor.value))

/** 时间轴范围：默认 07:00~22:00，被实际订单撑开 */
const dayRange = computed(() => {
  let lo = 7 * 60
  let hi = 22 * 60
  dayOrders.value.forEach((o) => {
    lo = Math.min(lo, minOf(o.startTime))
    hi = Math.max(hi, minOf(o.endTime))
  })
  const start = Math.max(0, Math.floor(lo / 60) * 60)
  const end = Math.min(24 * 60, Math.ceil(hi / 60) * 60)
  return { start, end, span: Math.max(60, end - start) }
})

const hourMarks = computed(() => {
  const out = []
  const step = dayRange.value.span > 12 * 60 ? 120 : 60
  for (let m = dayRange.value.start; m <= dayRange.value.end; m += step) out.push(m)
  return out
})

function pct(min) {
  return ((min - dayRange.value.start) / dayRange.value.span) * 100
}

/** 每行的数据源：按场地 or 按设备 */
const rows = computed(() => {
  if (rowMode.value === 'space') {
    return spaces.value.map((s) => {
      const openA = toOpenMin(s.openStartTime)
      const openB = toOpenMin(s.openEndTime)
      return {
        key: 's' + s.spaceId,
        id: s.spaceId,
        name: s.spaceName,
        sub: (s.location || '') + (s.capacity ? ' · ' + s.capacity + ' 人' : ''),
        badge: s.status === 0 ? '停用' : '',
        closedLeft:
          openA !== null && openA > dayRange.value.start ? Math.max(dayRange.value.start, openA) : null,
        closedRight:
          openB !== null && openB < dayRange.value.end ? Math.min(dayRange.value.end, openB) : null,
        bars: [],
      }
    })
  }
  return devices.value.map((d) => ({
    key: 'd' + d.deviceId,
    id: d.deviceId,
    name: d.deviceName,
    sub: d.deviceType || '',
    badge: d.deviceStatus !== 1 ? '不可用' : d.availableCount > 0 ? '' : '无库存',
    closedLeft: null,
    closedRight: null,
    bars: [],
  }))
})

/**
 * 把一批时间条装进「车道」，保证同一行内不互相压盖。
 *
 * 活跃单理论上不会重叠（建单判过冲突），但历史单经常和新单撞在同一时段。
 * 排序时**活跃单优先**，于是它们永远落在 lane 0（视觉上在上方），
 * 历史单自然排到下面的车道。
 */
function packBars(items) {
  const sorted = items
    .slice()
    .sort((a, b) => (a.isActive === b.isActive ? a.startMin - b.startMin : a.isActive ? -1 : 1))
  const laneEnds = []
  sorted.forEach((it) => {
    let lane = laneEnds.findIndex((end) => end <= it.startMin)
    if (lane < 0) {
      lane = laneEnds.length
      laneEnds.push(0)
    }
    laneEnds[lane] = it.endMin
    it.lane = lane
  })
  return { items: sorted, laneCount: Math.max(1, laneEnds.length) }
}

function buildBars(row) {
  const list = dayOrders.value
    .filter((o) => {
      if (!showHistory.value && ACTIVE_STATUS.indexOf(o.orderStatus) < 0) return false
      if (rowMode.value === 'space') return o.spaceId === row.id
      return (o.deviceIds || []).map(Number).indexOf(row.id) >= 0
    })
    .map((o) => {
      const s = Math.max(minOf(o.startTime), dayRange.value.start)
      const e = Math.min(minOf(o.endTime), dayRange.value.end)
      if (e <= s) return null
      const active = ACTIVE_STATUS.indexOf(o.orderStatus) >= 0
      return {
        key: o.orderId,
        order: o,
        startMin: s,
        endMin: e,
        isActive: active,
        lane: 0,
        cls: active ? 'st-' + o.orderStatus : 'is-history',
        label:
          '#' +
          o.orderId +
          (o.username && canManage.value ? ' ' + o.username : '') +
          (active ? '' : ' · ' + (o.orderStatusText || '历史')),
        tip:
          '#' +
          o.orderId +
          ' · ' +
          (o.orderStatusText || '') +
          ' · ' +
          String(o.startTime).slice(11, 16) +
          '-' +
          String(o.endTime).slice(11, 16) +
          (o.username ? ' · ' + o.username : ''),
      }
    })
    .filter(Boolean)
  return packBars(list)
}

const laidRows = computed(() => {
  const out = rows.value.map((r) => {
    const packed = buildBars(r)
    return Object.assign({}, r, { bars: packed.items, laneCount: packed.laneCount })
  })
  const maxLane = out.reduce((m, r) => Math.max(m, r.laneCount), 1)
  const laneHeight = 22
  return { rows: out, laneH: laneHeight, height: Math.max(30, maxLane * laneHeight + 6) }
})

const rowHeight = computed(() => laidRows.value.height)
const laneH = computed(() => laidRows.value.laneH)
const rowList = computed(() => laidRows.value.rows)

function barStyle(b) {
  return {
    left: pct(b.startMin) + '%',
    width: Math.max(0.8, pct(b.endMin) - pct(b.startMin)) + '%',
    top: b.lane * laneH.value + 3 + 'px',
    height: laneH.value - 6 + 'px',
    background: b.isActive ? STATUS_COLOR[b.order.orderStatus] || 'var(--sp-accent)' : 'var(--sp-t3)',
  }
}

const nowLeft = computed(() => {
  if (anchor.value !== todayStr()) return null
  const d = new Date()
  const m = d.getHours() * 60 + d.getMinutes()
  if (m < dayRange.value.start || m > dayRange.value.end) return null
  return pct(m)
})

// ---------------------------------------------------------------- 周视图
const weekDays = computed(() => {
  const mon = mondayOf(anchor.value || todayStr())
  const out = []
  const today = todayStr()
  for (let i = 0; i < 7; i++) {
    const key = shiftDate(mon, i)
    const d = new Date(key.replace(/-/g, '/'))
    out.push({ key, label: WEEKDAY_CN[d.getDay()], sub: key.slice(5), isToday: key === today })
  }
  return out
})

function rowOrdersOn(row, day) {
  return orders.value.filter((o) => {
    if (ACTIVE_STATUS.indexOf(o.orderStatus) < 0) return false
    if (dayOf(o.startTime) !== day) return false
    if (rowMode.value === 'space') return o.spaceId === row.id
    return (o.deviceIds || []).map(Number).indexOf(row.id) >= 0
  })
}
function heatCount(row, day) {
  return rowOrdersOn(row, day).length
}
function heatClass(row, day) {
  const n = heatCount(row, day)
  if (!n) return 'is-0'
  if (n >= 4) return 'is-4'
  return 'is-' + n
}
function heatTip(row, day) {
  const n = heatCount(row, day)
  return row.name + ' · ' + day + ' · ' + (n ? n + ' 条活跃预约' : '空闲')
}
function weekRowTotal(row) {
  return weekDays.value.reduce((s, d) => s + heatCount(row, d.key), 0)
}
function jumpTo(day) {
  anchor.value = day
  view.value = 'day'
}

// ---------------------------------------------------------------- 导航
const anchorLabel = computed(() => {
  if (view.value === 'week') {
    const ds = weekDays.value
    return ds[0].key.slice(5) + ' ~ ' + ds[6].key.slice(5)
  }
  const d = new Date((anchor.value || todayStr()).replace(/-/g, '/'))
  return anchor.value + ' ' + WEEKDAY_CN[d.getDay()]
})

function shift(n) {
  anchor.value = shiftDate(anchor.value, view.value === 'week' ? n * 7 : n)
}
function goToday() {
  anchor.value = todayStr()
}

// ---------------------------------------------------------------- 点空白建单
const createDialog = reactive({
  visible: false,
  spaceId: null,
  date: '',
  start: '09:00',
  end: '10:00',
  deviceIds: [],
  devices: [],
  devicesLoading: false,
  submitting: false,
})

function onTrackClick(ev, row) {
  const rect = ev.currentTarget.getBoundingClientRect()
  if (!rect.width) return
  const ratio = (ev.clientX - rect.left) / rect.width
  const raw = dayRange.value.start + ratio * dayRange.value.span
  // 吸附到 15 分钟 —— 与后端和确认页的时间粒度一致
  let startMin = Math.round(raw / 15) * 15
  startMin = Math.max(dayRange.value.start, Math.min(dayRange.value.end - 15, startMin))

  createDialog.spaceId = rowMode.value === 'space' ? row.id : null
  createDialog.date = anchor.value
  createDialog.start = hhmm(startMin)
  createDialog.end = hhmm(Math.min(dayRange.value.end, startMin + 60))
  createDialog.deviceIds = rowMode.value === 'device' ? [String(row.id)] : []
  createDialog.visible = true
  reloadDialogDevices()
}

async function reloadDialogDevices() {
  if (!createDialog.date || !createDialog.start || !createDialog.end) return
  createDialog.devicesLoading = true
  try {
    const data = await getAvailableDevices({
      startTime: createDialog.date + ' ' + createDialog.start + ':00',
      endTime: createDialog.date + ' ' + createDialog.end + ':00',
    })
    createDialog.devices = (data && data.devices) || []
    const usable = {}
    createDialog.devices.forEach((d) => {
      if (d.remainingCount > 0) usable[String(d.deviceId)] = true
    })
    createDialog.deviceIds = createDialog.deviceIds.filter((id) => usable[id])
  } catch (e) {
    createDialog.devices = []
  } finally {
    createDialog.devicesLoading = false
  }
}

async function submitCreate() {
  if (!createDialog.spaceId) {
    ElMessage.warning('请选择场地')
    return
  }
  if (createDialog.end <= createDialog.start) {
    ElMessage.warning('开始时间须早于结束时间')
    return
  }
  createDialog.submitting = true
  try {
    const res = await createOrder({
      spaceId: createDialog.spaceId,
      deviceIds: createDialog.deviceIds.map(Number),
      startTime: createDialog.date + ' ' + createDialog.start + ':00',
      endTime: createDialog.date + ' ' + createDialog.end + ':00',
      agentRequest: '预约日历·点击空白创建',
    })
    ElMessage.success('预约创建成功' + (res && res.orderId ? '（单号 #' + res.orderId + '）' : ''))
    createDialog.visible = false
    await loadData()
  } catch (e) {
    // 409 冲突由 request.js 弹出后端原文，这里只刷新一下可用性
    reloadDialogDevices()
  } finally {
    createDialog.submitting = false
  }
}

// ---------------------------------------------------------------- 详情 / 冲突
const drawerTitle = computed(() => (detail.value ? '预约单 #' + detail.value.orderId : '预约详情'))

function spaceLabel(spaceId) {
  const s = spaces.value.find((x) => x.spaceId === spaceId)
  return s ? s.spaceName : '场地 #' + spaceId
}
function deviceLabel(deviceIds) {
  const ids = Array.isArray(deviceIds) ? deviceIds : []
  if (!ids.length) return '无'
  return ids
    .map((id) => {
      const d = devices.value.find((x) => x.deviceId === Number(id))
      return d ? d.deviceName : '#' + id
    })
    .join('、')
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

function openDetail(order) {
  if (!order) return
  detail.value = order
  detailVisible.value = true
}

/**
 * 页面主数据：订单 + 场地 + 设备。
 *
 * ⚠️ **不含 AI 冲突扫描**（2026-10-14 拆开）。
 *
 * 原先这三项与 scanConflicts() 一起走 Promise.all，而 v-loading 挂在根节点上，
 * 于是**必须等最慢的 AI 扫描回来才显示日历** —— 用户进页面先对着空白等，
 * 体验上就像「点了之后没反应」。现在这里只等这三项（都是普通查询，很快），
 * 日历立刻出来；冲突雷达由 loadConflicts() 后台补上，它自己转圈。
 */
async function loadBoard() {
  const ordersRequest = canManage.value ? getAllOrders() : getMyOrders()
  const [ordersData, spacesData, devicesData] = await Promise.all([
    ordersRequest,
    getSpaces(),
    getDevices(),
  ])
  orders.value = ordersOf(ordersData)
  spaces.value = spacesOf(spacesData)
  devices.value = devicesOf(devicesData)
  if (!anchor.value) anchor.value = todayStr()
}

/**
 * AI 软冲突扫描。**独立于日历**，失败也不影响日历渲染。
 *
 * 为什么允许它「晚到」：软冲突是**决策辅助**，不是这一屏的主体；
 * 而硬冲突（时段完全重叠）由建单事务层直接拦截，不依赖这个结果。
 * 所以「先看到日历、几秒后雷达出数」在语义上是安全的。
 *
 * 失败只清空列表并复位转圈状态：radar 拿不到数不该让整个日历页看起来坏了。
 * 权限口径同侧栏 —— 普通用户看不到日历页，这里再兜一次，避免无谓的 403 请求。
 */
async function loadConflicts() {
  if (!canManage.value) return
  conflictsLoading.value = true
  try {
    const data = await scanConflicts()
    conflicts.splice(0, conflicts.length, ...listOf(data))
  } catch (e) {
    conflicts.splice(0, conflicts.length)
  } finally {
    conflictsLoading.value = false
  }
}

/**
 * 一次完整刷新：日历先出，雷达随后。
 *
 * 刻意**不 await loadConflicts()** —— 等它就等于回到「整页等 AI」的老问题。
 * 调用方（onMounted / 建单后刷新）因此不会阻塞。
 */
async function loadData() {
  loading.value = true
  try {
    await loadBoard()
  } finally {
    loading.value = false
  }
  loadConflicts()
}

function conflictClass(item) {
  const type = String((item && item.conflictType) || '')
  return type.includes('硬') ? 'is-red' : 'is-blue'
}

function conflictTitle(item) {
  if (!item) return '冲突'
  const rule = String(item.ruleLabel || item.ruleCode || item.conflictType || '冲突')
  const ids = Array.isArray(item.orderIds) ? item.orderIds : []
  if (ids.length) return rule + ' · 预约 #' + ids.join(' / #')
  if (item.spaceId !== null && item.spaceId !== undefined) return rule + ' · 场地 #' + item.spaceId
  return rule
}

function conflictSubject(item) {
  return String((item && item.reason) || '').trim()
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
    // 409 等由 request.js 弹出后端原文
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
  gap: var(--sp-s3);
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

/*
 * 窄屏断点（2026-10-14 加）。
 *
 * 本页是「周历（flex:1）+ 右侧软冲突雷达（固定 316px）」的双列结构。
 * 窄屏下雷达列会把周历挤到不可读，这里改为上下堆叠。
 *
 * 周历本身按时间轴横向铺开，给 .calcard 加 overflow-x 让它在**自己的容器内**
 * 滚动 —— 那是时间轴控件的正常交互，与「整个页面横向溢出」是两件事
 * （前者用户能接受，后者会让顶栏、侧栏一起被推出屏幕）。
 */
@media (max-width: 1100px) {
  .calwrap {
    flex-direction: column;
  }

  .radar-panel {
    width: 100%;
  }

  .calcard {
    width: 100%;
    overflow-x: auto;
  }
}

.radar-empty {
  text-align: center;
  padding: 12px 0 18px;
}

.cf-subject {
  margin: 4px 0 6px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--sp-t2);
}

.cal-tip {
  margin-top: 13px;
  padding-top: 12px;
  border-top: 1px dashed var(--sp-border-l);
  line-height: 1.7;
}

.tip-dim {
  color: var(--sp-t3);
}

.panel-tip {
  margin-top: 14px;
  font-size: 12px;
  color: var(--sp-t3);
  line-height: 1.7;
  border-top: 1px dashed var(--sp-border-l);
  padding-top: 12px;
}

.drawer-acts {
  margin-top: 14px;
}

/* ---------------- 工具条 ---------------- */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-s3);
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.tb-left {
  display: flex;
  align-items: center;
  gap: var(--sp-s2);
}

.tb-nav {
  border: 1px solid var(--sp-border);
  background: #fff;
  color: var(--sp-t2);
  border-radius: var(--sp-r-sm);
  padding: 4px 12px;
  font-size: 13px;
  cursor: pointer;
}

.tb-nav:hover {
  border-color: var(--sp-ai-line);
  color: var(--sp-accent);
}

.tb-date {
  font-weight: 600;
  font-size: 14px;
  margin-left: 6px;
}

.tb-right {
  display: flex;
  align-items: center;
  gap: var(--sp-s3);
}

.seg {
  display: inline-flex;
  border: 1px solid var(--sp-border);
  border-radius: var(--sp-r-sm);
  overflow: hidden;
}

.seg button {
  border: 0;
  background: #fff;
  color: var(--sp-t2);
  padding: 5px 14px;
  font-size: 13px;
  cursor: pointer;
}

.seg button + button {
  border-left: 1px solid var(--sp-border);
}

.seg button.on {
  background: var(--sp-ai-soft);
  color: var(--sp-accent);
  font-weight: 600;
}

/* ---------------- 日视图：资源时间线 ---------------- */
.tl {
  border: 1px solid var(--sp-border-l);
  border-radius: var(--sp-r-md);
  overflow: hidden;
}

.tl-row {
  display: flex;
  align-items: stretch;
  border-top: 1px solid var(--sp-border-l);
}

.tl-row:first-child {
  border-top: 0;
}

.tl-head {
  background: var(--sp-bg-hover);
}

.tl-name {
  width: 132px;
  flex: none;
  padding: 6px 10px;
  font-size: 12.5px;
  color: var(--sp-text);
  border-right: 1px solid var(--sp-border-l);
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
}

.tl-name-head {
  color: var(--sp-t3);
  font-size: 12px;
}

.tl-name-t {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tl-name-b {
  font-size: 12px;
  color: var(--sp-warning);
}

.tl-track {
  position: relative;
  flex: 1;
  min-width: 0;
  background: #fff;
  cursor: crosshair;
}

.tl-head .tl-track {
  height: 26px;
  background: var(--sp-bg-hover);
}

.tl-mark {
  position: absolute;
  top: 3px;
  font-size: 12px;
  color: var(--sp-t3);
  transform: translateX(-50%);
  white-space: nowrap;
}

.tl-vline {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--sp-border-l);
  opacity: 0.7;
  pointer-events: none;
}

.tl-now {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--sp-danger);
  pointer-events: none;
}

.tl-closed {
  position: absolute;
  top: 0;
  bottom: 0;
  background: repeating-linear-gradient(
    45deg,
    #f2f4f7 0,
    #f2f4f7 5px,
    #e9edf3 5px,
    #e9edf3 10px
  );
  pointer-events: none;
}

.tl-bar {
  position: absolute;
  border-radius: var(--sp-r-xs);
  color: #fff;
  font-size: 12px;
  line-height: 1;
  display: flex;
  align-items: center;
  padding: 0 6px;
  cursor: pointer;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 35, 60, 0.14);
}

.tl-bar-t {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tl-bar.st-1 {
  background: var(--sp-cat-purple);
}

.tl-bar.st-2 {
  background: var(--sp-accent);
}

.tl-bar.is-history {
  background: var(--sp-t3);
  opacity: 0.85;
  font-size: 12px;
}

.tl-empty {
  padding: 24px;
  text-align: center;
  color: var(--sp-t3);
  font-size: 13px;
}

/* ---------------- 周视图：容量热力 ---------------- */
.wk {
  border: 1px solid var(--sp-border-l);
  border-radius: var(--sp-r-md);
  overflow: hidden;
}

.wk-row {
  display: flex;
  align-items: stretch;
  border-top: 1px solid var(--sp-border-l);
}

.wk-row:first-child {
  border-top: 0;
}

.wk-head {
  background: var(--sp-bg-hover);
}

.wk-name {
  width: 132px;
  flex: none;
  padding: 8px 10px;
  font-size: 12.5px;
  border-right: 1px solid var(--sp-border-l);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.wk-head .wk-name {
  color: var(--sp-t3);
  font-size: 12px;
}

.wk-cell {
  flex: 1;
  min-width: 0;
  text-align: center;
  font-size: 12.5px;
  padding: 8px 2px;
  border-left: 1px solid var(--sp-border-l);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.wk-head .wk-cell {
  color: var(--sp-t2);
  font-size: 12px;
}

.wk-head .wk-cell span {
  font-size: 12px;
  color: var(--sp-t3);
}

.wk-cell.is-today {
  background: var(--sp-accent-bg);
}

.wk-click {
  cursor: pointer;
}

.wk-click:hover {
  outline: 2px solid var(--sp-ai-line);
  outline-offset: -2px;
}

.wk-cell.is-1 {
  background: var(--sp-accent-bg);
}

.wk-cell.is-2 {
  background: var(--sp-accent-line);
}

.wk-cell.is-3 {
  background: #79bbff;
}

.wk-cell.is-4 {
  background: #409eff;
  color: #fff;
}

.wk-sum {
  width: 66px;
  flex: none;
  text-align: center;
  font-size: 12.5px;
  padding: 8px 2px;
  border-left: 1px solid var(--sp-border-l);
  color: var(--sp-t2);
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ---------------- 新建预约弹窗 ---------------- */
.cd-time {
  display: flex;
  align-items: center;
  gap: var(--sp-s2);
}

.cd-sep {
  color: var(--sp-t3);
}

.cd-devs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 200px;
  overflow-y: auto;
  width: 100%;
}

.cd-rest {
  margin-left: 6px;
  font-size: 12px;
  color: #4fd88f;
}

.cd-rest.is-zero {
  color: #ff8a8a;
}
</style>
