<template>
  <view class="app-page">
    <mp-nav-bar title="确认预约" back />

    <view class="app-body">
      <!-- 来源：让用户知道「AI 替我认出了什么」，才好判断还缺什么 -->
      <view class="src">
        <text class="src-ic">{{ sourceIcon }}</text>
        <view class="src-body">
          <text class="src-t">来自{{ prefill.sourceLabel || '手动填写' }}</text>
          <text v-if="prefill.text" class="src-x">{{ prefill.text }}</text>
          <text v-else class="src-x">{{ prefilledHint }}</text>
        </view>
      </view>

      <!-- ① 时间：15 分钟一档 -->
      <view class="card">
        <view class="card-head">
          <text class="card-title">① 使用时间</text>
          <text class="card-sub">15 分钟一档</text>
        </view>
        <view class="kv">
          <text class="k">日期</text>
          <picker mode="date" :value="date" @change="onDateChange">
            <text class="v pick">{{ date }} ›</text>
          </picker>
        </view>
        <!--
          开始 / 结束用**可禁用的时间格**，不用 picker（2026-10-14 改）。

          微信原生 picker 无法「按项置灰」，而这里必须让已占用的档位不可点 ——
          否则用户会选到已被别人约走的时段，一路填完才被后端 409 拒掉。
          换成自绘网格后，占用档位置灰且不可点，选之前就看得见。

          为什么保留置灰项而不是直接不渲染：直接抹掉会让时间轴出现空洞，
          用户以为界面少给了选项；置灰才讲得清「这一档存在，只是被占了」。
        -->
        <view class="kv kv-block">
          <text class="k">开始</text>
          <view class="tgrid">
            <view
              v-for="o in startOptions"
              :key="'s' + o.time"
              class="tcell"
              :class="{ on: startTime === o.time, off: o.disabled }"
              :hover-class="o.disabled ? 'none' : 'btn-on'"
              :hover-stay-time="60"
              @tap="pickStart(o.time)"
            >{{ o.time }}</view>
          </view>
        </view>
        <view class="kv kv-block">
          <text class="k">结束</text>
          <view class="tgrid">
            <view
              v-for="o in endOptions"
              :key="'e' + o.time"
              class="tcell"
              :class="{ on: endTime === o.time }"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap="pickEnd(o.time)"
            >{{ o.time }}</view>
          </view>
          <text v-if="!endOptions.length" class="tgrid-empty">
            先选开始时间；或所选时段之后已被占满
          </text>
        </view>

        <text v-if="conflictHint" class="tgrid-warn">{{ conflictHint }}</text>
        <text v-else class="tgrid-note">置灰的时间已被他人预约，不可选。</text>
      </view>

      <!-- ② 可用场地（冲突预检） -->
      <view class="card">
        <view class="card-head">
          <text class="card-title">② 该时段可用场地</text>
          <text class="link" @click="refreshSpaces">刷新</text>
        </view>
        <view class="kv2">
          <text class="k">人数</text>
          <input class="num" type="number" v-model="capacity" placeholder="不限" @blur="refreshSpaces" />
        </view>
        <view class="kv2">
          <text class="k">类型</text>
          <picker :range="SPACE_TYPES" range-key="label" :value="spaceTypeIndex" @change="onSpaceTypeChange">
            <text class="v pick">{{ SPACE_TYPES[spaceTypeIndex].label }} ›</text>
          </picker>
        </view>
        <view v-if="spacesLoading" class="hint">查询中…</view>
        <view v-else-if="!spaceOptions.length" class="hint is-warn">
          该时段没有合适的场地，请调整时间、人数或类型
        </view>
        <view v-else class="opts">
          <view
            v-for="s in spaceOptions"
            :key="s.spaceId"
            class="opt"
            :class="{ 'is-on': selectedSpaceId === s.spaceId }"
            @click="selectSpace(s.spaceId)"
          >
            <view class="opt-line">
              <text class="opt-name">{{ s.spaceName }}</text>
              <text v-if="s.spaceId === prefill.spaceId" class="badge">识别到</text>
            </view>
            <text class="opt-meta">
              {{ SPACE_TYPE_TEXT[s.spaceType] || '场地' }} · {{ s.capacity }} 人 · {{ s.location || '—' }}
            </text>
          </view>
        </view>
      </view>

      <!-- ③ 设备（拍照/语音/草图都可能没提到，这一步就是给用户补的） -->
      <view class="card">
        <view class="card-head">
          <text class="card-title">③ 设备（可多选）</text>
          <text class="card-sub">数字=该时段还能借几台</text>
        </view>
        <view v-if="devicesLoading" class="hint">查询中…</view>
        <text v-else-if="!deviceTypeOptions.length" class="hint">暂无可用设备</text>
        <!--
          按**类型**勾选，不再一台一个复选框（2026-10-14 改）。

          台账里 15 台设备只分 5 个类型（投影仪 ×4 / 音响 ×4 / 显示屏 ×3 /
          无人机 ×2 / 直播设备 ×2）。原先列出「投影仪01、投影仪02…」要求用户
          在几台同型设备之间做选择，而它们在业务上没有任何区别 ——
          用户要的是「一台投影仪」。

          勾选一个类型 = 选中该类型下**所有可用台次**；提交时仍旧落到 deviceIds
          （下单契约收的就是台号数组）。
        -->
        <checkbox-group v-else class="devs" @change="onDeviceTypeChange">
          <label
            v-for="t in deviceTypeOptions"
            :key="t.type"
            class="dev"
            :class="{ 'is-off': t.remaining <= 0 }"
          >
            <checkbox
              :value="t.type"
              :checked="selectedTypes.includes(t.type)"
              :disabled="t.remaining <= 0"
            />
            <text class="dev-n">{{ t.type }}</text>
            <text class="dev-r" :class="{ 'is-zero': t.remaining <= 0 }">
              {{ t.remaining > 0 ? '可借 ' + t.remaining + ' 台' : '已借满' }}
            </text>
          </label>
        </checkbox-group>
      </view>

      <!-- 两个出口（方案 A）：自己定，或交给 AI 排 -->
      <view class="acts">
        <view
          class="btn ai block"
          :class="{ disabled: submitting }"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="submit"
        >{{ submitting ? '提交中…' : '直接生成预约单' }}</view>
        <view class="btn ghost block" hover-class="btn-on" :hover-stay-time="60" @tap="goAgent">
          让 AI 帮我排方案 →
        </view>
      </view>
      <text class="foot">
        直接生成会用你**已经选好**的场地/时间/设备，2 秒完成；
        交给 AI 则由调度 Agent 再核对一遍冲突并给出备选方案（约 10~30 秒）。
      </text>
    </view>
  </view>
</template>

<script setup>
/**
 * 预约确认页（2026-10-13 新增）
 *
 * 三个入口（拍照识场 / 语音预约 / 手绘草图）共用这一页：
 *   它们各自把「自己识别到的那部分」写进 store/reservePrefill.js，
 *   缺的部分（通常是**设备**和**时间**）由用户在这里补齐。
 *
 * 两个出口：
 *   直接生成预约单 —— 用用户选好的，一次原子建单（冲突则整单回滚 + 提示重选）
 *   让 AI 帮我排方案 —— 把选好的作为需求交给核心调度 Agent
 */
import { computed, onMounted, ref } from 'vue'
import { agentStore } from '@/store/agent.js'
import { reservePrefill as prefill } from '@/store/reservePrefill.js'
import { availableDevices, availableSpaces, spaceBookings } from '@/api/resources.js'
import { createOrder } from '@/api/reserve.js'
import { parseDateTime } from '@/utils/format.js'
import { toast } from '@/utils/toast.js'

/** 场地开放时段取不到时的**兜底**范围（小时）：覆盖绝大多数场地 */
const FALLBACK_OPEN = { start: 7, end: 23 }

/** 当前所选场地的开放时段（'HH:MM:SS'），未选/未取到时为 null */
const spaceOpenRange = ref(null)

/**
 * 当前所选场地**已被占用**的时段（分钟区间），按天分组。
 *
 * ⚠️ 2026-10-14 加。用途是**在选择阶段就禁掉已占用的时间档**，
 * 而不是等提交时被后端 409 拒掉（用户原话：选时就禁用已占用时段）。
 *
 * 数据来自同一个 GET /resources/spaces/{id}/booked —— 它同时给
 * openStartTime/openEndTime 与 bookings[]，一次请求两用，不必再打一个接口。
 *
 * ⚠️ 占用口径不在这里重判：后端已经按「1 待确认 / 2 已确认」过滤过
 *    （与下单判重同源，见 models/reservation.py 的 OCCUPYING_STATUS）。
 *    这里只做区间求交，两处口径不会漂移。
 *
 * 但它仍是**快照**：别人在你选完之后下单，本地不会知道。所以后端事务里的
 * 判重与 409 依然是最终防线，这里的禁用只是「让用户别白填一遍」。
 */
const busyByDay = ref({})

/**
 * 时间选项：由**所选场地的开放时段**生成（2026-10-14 改）。
 *
 * ⚠️ 原先是写死的 07:00~23:45，与场地实际开放时间无关。后果：
 *    A栋201 开放 8:00-22:00、展厅 9:00-21:00、中心广场 6:00-23:00，
 *    写死的话用户可以选 7:00，提交时才被后端拒 ——
 *    因为 backend/app/services/space_service.py 是按
 *    `open_start_time <= start AND open_end_time >= end` 过滤的。
 *
 * 没选场地（或还没取到开放时段）时回落到 FALLBACK_OPEN，
 * 保证界面不会出现空的下拉框；选了场地后立刻按真实时段重算。
 */
const TIME_OPTIONS = computed(() => {
  const r = spaceOpenRange.value || {}
  const s = clockToMin(r.start)
  const e = clockToMin(r.end)
  const startH = s === null ? FALLBACK_OPEN.start : Math.floor(s / 60)
  const endH = e === null ? FALLBACK_OPEN.end : Math.floor(e / 60)
  const out = []
  for (let h = startH; h <= endH; h++) {
    const hh = h < 10 ? '0' + h : '' + h
    if (h !== endH) out.push(hh + ':00', hh + ':15', hh + ':30', hh + ':45')
  }
  // 闭馆那一刻（22:00）也要能选为结束时间
  if (out[out.length - 1] !== (endH < 10 ? '0' + endH : '' + endH) + ':00') {
    out.push((endH < 10 ? '0' + endH : '' + endH) + ':00')
  }
  return out
})

/** 'HH:MM[:SS]' → 分钟数；解析不了返回 null */
function clockToMin(t) {
  const m = String(t || '').match(/^(\d{1,2}):(\d{2})/)
  if (!m) return null
  return Number(m[1]) * 60 + Number(m[2])
}

/** 某天已占用的分钟区间数组（无数据返回空数组） */
function busyOf(dayKey) {
  return busyByDay.value[dayKey] || []
}

/**
 * 某个分钟数是否落在**已占用**区间内（含起止点：边界也算被占，
 * 因为一个占用 14:15 开始的场地，14:15 这个档位本身就不能选）。
 */
function isBusyMin(dayKey, min) {
  return busyOf(dayKey).some((b) => min >= b.startMin && min <= b.endMin)
}

/**
 * 从 from 到 to（分钟）这段区间是否与任一已占用区间相交。
 * 用于结束时间的候选过滤：跨过别人的占用段同样不合法。
 */
function intervalBusy(dayKey, from, to) {
  if (from === null || to === null || to <= from) return false
  return busyOf(dayKey).some((b) => from < b.endMin && to > b.startMin)
}

/** 时间点是否可选（按当前日期判定是否已占用） */
function isFree(dayKey, hhmm) {
  const m = clockToMin(hhmm)
  if (m === null) return false
  return !isBusyMin(dayKey, m)
}

/**
 * 可作为**开始**的档位：未被占用的档位原样可点，已占用的档位保留但标记不可点。
 *
 * 为什么保留而不是过滤掉：过滤掉会让时间轴出现空洞，用户看不出
 * 「这里本来有 14:15 这一档，只是被占了」，反而以为界面少给了选项。
 * 置灰 + 说明才讲得清。
 */
const startOptions = computed(() =>
  TIME_OPTIONS.value.map((t) => ({ time: t, disabled: !isFree(date.value, t) }))
)

/**
 * 可作为**结束**的档位：晚于开始时间，且**自身不落在**已占用区间内。
 *
 * ⚠️ 判据是「点」而不是「区间相交」，这一点很关键（2026-10-14 修正）：
 *    起初写成「开始~结束整段与占用区间相交就禁用」，结果场地 9 在 14:15-14:30
 *    被占时，选开始 14:00 会把 14:45、15:00…**一直到闭馆全部禁掉** ——
 *    而 14:30 之后本来完全可以用。
 *
 *    正确的语义是「不许跨进别人的占用段」：
 *      · 开始点已保证空闲（pickStart 拦过）；
 *      · 那么结束点只要不落在占用段内，这段区间就不会跨进去；
 *      · 一旦结束点进入占用段，说明从该点起是在占别人的时间 → 禁。
 *    所以按占用区间的**起止分钟数**判结束点是充分且必要的。
 */
const endOptions = computed(() => {
  const from = clockToMin(startTime.value)
  return TIME_OPTIONS.value
    .filter((t) => {
      const to = clockToMin(t)
      if (from === null || to === null || to <= from) return false
      return !isBusyMin(date.value, to)
    })
    .map((t) => ({ time: t, disabled: false }))
})

/** 选中区间是否仍与占用冲突（供提示用；正常选不出冲突组合） */
const conflictHint = computed(() => {
  const from = clockToMin(startTime.value)
  const to = clockToMin(endTime.value)
  if (from === null || to === null || to <= from) return ''
  if (!intervalBusy(date.value, from, to)) return ''
  return '所选时段与已有预约重叠，请重新选择。'
})

const SPACE_TYPES = [
  { value: 0, label: '不限类型' },
  { value: 1, label: '会议室' },
  { value: 2, label: '展厅' },
  { value: 3, label: '多功能厅' },
  { value: 4, label: '户外场地' },
]
const SPACE_TYPE_TEXT = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

/** 需求关键词 → 台账设备类型（预勾选用） */
const REQ_TO_DEVICE = [
  { keys: ['投影'], type: '投影仪' },
  { keys: ['音响', '扩音', '话筒'], type: '音响' },
  { keys: ['显示屏', '大屏', '屏幕', 'LED'], type: 'LED显示屏' },
  { keys: ['直播'], type: '直播设备' },
  { keys: ['无人机', '航拍'], type: '无人机' },
]

const capacity = ref('')
const spaceTypeIndex = ref(0)
const date = ref('')
const startTime = ref('')
const endTime = ref('')

const spaceOptions = ref([])
const deviceOptions = ref([])
const selectedSpaceId = ref(null)
const selectedDeviceIds = ref([])
const spacesLoading = ref(false)
const devicesLoading = ref(false)
const submitting = ref(false)

// startIndex / endIndex 已随「换成时间格」移除（2026-10-14）：
// 它们只为原生 picker 的 :value 回显而存在，网格是直接比对的，不需要下标。

const sourceIcon = computed(() => {
  if (prefill.source === 'image') return '📷'
  if (prefill.source === 'voice') return '🎙'
  if (prefill.source === 'sketch') return '✍️'
  return '📝'
})

/** 没带文本时，用一句说明告诉用户「系统已经替你填了什么」 */
const prefilledHint = computed(() => {
  const bits = []
  if (prefill.capacity) bits.push(prefill.capacity + ' 人')
  if (prefill.spaceType) bits.push(SPACE_TYPE_TEXT[prefill.spaceType] || '场地')
  if (prefill.deviceTypes && prefill.deviceTypes.length) bits.push(prefill.deviceTypes.join('、'))
  if (!bits.length) return '请选择时间、场地与设备'
  return '已识别：' + bits.join(' · ') + '，请补充时间与设备后提交'
})

function pad(n) {
  return n < 10 ? '0' + n : '' + n
}
function ceilToQuarter(d) {
  const t = new Date(d.getTime())
  t.setSeconds(0, 0)
  const m = t.getMinutes()
  t.setMinutes(m + ((15 - (m % 15)) % 15))
  return t
}
function hhmm(d) {
  return pad(d.getHours()) + ':' + pad(d.getMinutes())
}
function todayStr(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
}
function range() {
  return {
    startTime: date.value + ' ' + startTime.value + ':00',
    endTime: date.value + ' ' + endTime.value + ':00',
  }
}

async function refreshSpaces() {
  if (!date.value || !startTime.value || !endTime.value) return
  spacesLoading.value = true
  try {
    const params = Object.assign({}, range())
    const cap = Number(capacity.value)
    if (cap > 0) params.capacity = cap
    const st = SPACE_TYPES[spaceTypeIndex.value].value
    if (st > 0) params.spaceType = st
    const data = await availableSpaces(params)
    spaceOptions.value = (data && data.spaces) || []
    // 识别到的场地排到最前面 —— 它多半就是对的，用户不用翻
    if (prefill.spaceId) {
      spaceOptions.value.sort((a, b) => (b.spaceId === prefill.spaceId) - (a.spaceId === prefill.spaceId))
    }
    if (selectedSpaceId.value && !spaceOptions.value.some((s) => s.spaceId === selectedSpaceId.value)) {
      selectedSpaceId.value = null
    }
  } catch (e) {
    spaceOptions.value = []
  } finally {
    spacesLoading.value = false
  }
}

async function refreshDevices() {
  if (!date.value || !startTime.value || !endTime.value) return
  devicesLoading.value = true
  try {
    const data = await availableDevices(range())
    deviceOptions.value = (data && data.devices) || []
    const usable = {}
    deviceOptions.value.forEach((d) => {
      if (d.remainingCount > 0) usable[String(d.deviceId)] = true
    })
    selectedDeviceIds.value = selectedDeviceIds.value.filter((id) => usable[id])
  } catch (e) {
    deviceOptions.value = []
  } finally {
    devicesLoading.value = false
  }
}

function refreshAll() {
  refreshSpaces()
  refreshDevices()
}

/** 按设备**类型**预勾选（拍照/语音/草图给的都是类型，不是具体某一台） */
function preselectByTypes(types) {
  if (!types || !types.length) return
  selectedDeviceIds.value = deviceOptions.value
    .filter((d) => types.indexOf(d.deviceType) >= 0)
    .map((d) => String(d.deviceId))
}

/**
 * 选场地：记下 id，并取该场地的开放时段来重算时间选项。
 *
 * 为什么走 /booked 取开放时段而不是查场地列表：只有这个接口同时给
 * openStartTime / openEndTime（见 api/resources.js 的 spaceBookings 契约），
 * 而我们本来就要在别处用它的占用数据。
 */
async function selectSpace(spaceId) {
  selectedSpaceId.value = spaceId
  spaceOpenRange.value = null
  busyByDay.value = {}
  if (spaceId === undefined || spaceId === null) return
  try {
    // days=3 而不是 1：用户可以把日期改到未来几天，占用数据要一起带上，
    // 否则换日期后禁用态会全部失效（表现为「明明被占了却还能选」）。
    const res = await spaceBookings(spaceId, 3)
    spaceOpenRange.value = res
      ? { start: res.openStartTime, end: res.openEndTime }
      : null
    busyByDay.value = extractBusyByDay(res)

    // 已选时间落到「新范围之外」或「已被占用」时清掉 ——
    // 否则会留下一个当前选不中的值，用户以为选好了、点提交才被拒。
    const opts = TIME_OPTIONS.value
    if (startTime.value && (!opts.includes(startTime.value) || !isFree(date.value, startTime.value))) {
      startTime.value = ''
    }
    if (endTime.value) {
      const from = clockToMin(startTime.value)
      const to = clockToMin(endTime.value)
      if (from === null || to === null || to <= from || intervalBusy(date.value, from, to)) {
        endTime.value = ''
      }
    }
  } catch (e) {
    // 取不到就回落兜底范围，不打断用户（此时不禁用任何档位，由后端 409 兜底）
    spaceOpenRange.value = null
    busyByDay.value = {}
  }
}

/**
 * 把 /booked 的 bookings[] 拆成「日期 → [{startMin, endMin}]」。
 *
 * 只做区间换算，不重判占用口径（后端已按 1/2 过滤）。
 * 跨天占用本系统不会出现（场地按日开放），真出现时按下限截断处理。
 */
function extractBusyByDay(res) {
  const out = {}
  const list = Array.isArray((res || {}).bookings) ? res.bookings : []
  list.forEach((b) => {
    const s = parseDateTime(b.startTime)
    const e = parseDateTime(b.endTime)
    if (!s || !e || e <= s) return
    const key = todayStr(s)
    if (!out[key]) out[key] = []
    out[key].push({
      startMin: s.getHours() * 60 + s.getMinutes(),
      endMin:
        todayStr(e) === key ? e.getHours() * 60 + e.getMinutes() : 24 * 60,
    })
  })
  return out
}

/**
 * 只刷新「占用时段」，不动已选的场地/时间。
 *
 * 与 selectSpace 分开是因为触发条件不同：selectSpace 是「换了场地」，
 * 需要连开放时段一起重取并可能清掉已选时间；而这里只是「换了日期」，
 * 场地与开放时段都没变，清掉用户已选时间反而会让他在改日期后重选一遍。
 */
async function refreshBusy() {
  const sid = selectedSpaceId.value
  if (sid === undefined || sid === null) {
    busyByDay.value = {}
    return
  }
  try {
    const res = await spaceBookings(sid, 3)
    busyByDay.value = extractBusyByDay(res)
    if (res) {
      spaceOpenRange.value = { start: res.openStartTime, end: res.openEndTime }
    }
  } catch (e) {
    // 取不到就不禁用任何档位，交给后端 409 兜底
    busyByDay.value = {}
  }
}

/** 取消选择时间（供网格里的「已占用」档位提示用，不做静默清除） */
function pickStart(t) {
  if (!isFree(date.value, t)) return
  startTime.value = t
  const from = clockToMin(t)
  const to = clockToMin(endTime.value)
  // 原来的结束时间若已不合法（早于开始 / 跨过占用段），自动顺延到下一档
  if (from === null || to === null || to <= from || intervalBusy(date.value, from, to)) {
    const next = TIME_OPTIONS.value.find((x) => {
      const m = clockToMin(x)
      return m !== null && m > from && !intervalBusy(date.value, from, m)
    })
    endTime.value = next || ''
  }
  refreshAll()
}

function pickEnd(t) {
  const from = clockToMin(startTime.value)
  const to = clockToMin(t)
  if (from === null || to === null || to <= from || intervalBusy(date.value, from, to)) return
  endTime.value = t
  refreshAll()
}

function onDateChange(e) {
  date.value = e.detail.value
  // 换日期后占用数据对应的那一天变了，必须重取（否则禁用态会全部失效）
  refreshBusy()
  refreshAll()
}
function onSpaceTypeChange(e) {
  spaceTypeIndex.value = Number(e.detail.value)
  refreshSpaces()
}
/**
 * 设备按**类型**聚合（2026-10-14 改）。
 *
 * 台账是 15 台 / 5 个类型（投影仪01…音响04），一台一个复选框等于让用户在
 * 「投影仪01 和 投影仪02 有什么区别」上做无用功 —— 实际业务里他要的是
 * 「一台投影仪」，不是「02 号那台」。
 *
 * 所以界面只呈现类型，勾选类型 = 选中该类型下**所有可用台次**；
 * 内部仍旧落到 deviceId 数组（下单契约收的就是 deviceIds: list[int]）。 */
const deviceTypeOptions = computed(() => {
  const map = new Map()
  deviceOptions.value.forEach((d) => {
    const t = d.deviceType || '其他'
    if (!map.has(t)) map.set(t, { type: t, total: 0, remaining: 0 })
    const e = map.get(t)
    e.total += 1
    e.remaining += Math.max(0, d.remainingCount || 0)
  })
  return [...map.values()]
})

/** 当前勾选的类型（由已选台次反推，避免再维护一份状态导致不同步） */
const selectedTypes = computed(() => {
  const out = []
  selectedDeviceIds.value.forEach((id) => {
    const d = deviceOptions.value.find((x) => String(x.deviceId) === id)
    if (d && d.deviceType && out.indexOf(d.deviceType) < 0) out.push(d.deviceType)
  })
  return out
})

/** 勾选/取消一个类型 = 把该类型下所有可用台次一起加减 */
function onDeviceTypeChange(e) {
  const wanted = e.detail.value || []
  const out = []
  deviceTypeOptions.value.forEach((t) => {
    if (wanted.indexOf(t.type) < 0) return
    deviceOptions.value
      .filter((d) => (d.deviceType || '其他') === t.type && d.remainingCount > 0)
      .forEach((d) => out.push(String(d.deviceId)))
  })
  selectedDeviceIds.value = out
}
function onCapacityBlur() {
  refreshSpaces()
}

function selectedDeviceNames() {
  return selectedDeviceIds.value
    .map((id) => {
      const d = deviceOptions.value.find((x) => String(x.deviceId) === id)
      return d ? d.deviceName : '#' + id
    })
    .join('、')
}

/** 已选设备的**类型**（去重）。Agent 的工具收的是类型不是台号，见 buildAgentRequest。 */
function selectedDeviceTypes() {
  const types = []
  selectedDeviceIds.value.forEach((id) => {
    const d = deviceOptions.value.find((x) => String(x.deviceId) === id)
    if (d && d.deviceType && types.indexOf(d.deviceType) < 0) types.push(d.deviceType)
  })
  return types
}

/**
 * 交给 Agent 的需求文本。
 *
 * ⚠️ 设备这里写的是**类型**（投影仪）而不是台号（投影仪01）：
 *    Agent 的 `query_devices` 收的参数就是「设备类型」，给具体台号它也只能退回去按类型查，
 *    反而多一层没用的信息。用户要**精确指定某一台**时，走「直接生成预约单」那条路
 *    （它直接把 deviceIds 写进订单，不经过 Agent）。
 */
function buildAgentRequest() {
  const parts = []
  const sp = spaceOptions.value.find((s) => s.spaceId === selectedSpaceId.value)
  parts.push('我要预约' + (sp ? sp.spaceName : '场地'))
  if (capacity.value) parts.push(capacity.value + '人')
  parts.push(date.value + ' ' + startTime.value + '~' + endTime.value)
  const types = selectedDeviceTypes()
  if (types.length) parts.push('需要' + types.join('、'))
  if (prefill.text) parts.push('（原始需求：' + prefill.text + '）')
  return parts.join('，').slice(0, 1000)
}

/** 直接建单时写进订单备注的话：带具体台号，事后回看更清楚 */
function buildOrderNote() {
  const sp = spaceOptions.value.find((s) => s.spaceId === selectedSpaceId.value)
  const bits = []
  if (prefill.sourceLabel) bits.push('来自' + prefill.sourceLabel)
  if (sp) bits.push(sp.spaceName)
  if (capacity.value) bits.push(capacity.value + '人')
  const names = selectedDeviceNames()
  if (names) bits.push('设备：' + names)
  if (prefill.text) bits.push('原始需求：' + prefill.text)
  return bits.join('；').slice(0, 1000)
}

function checkReady() {
  if (!selectedSpaceId.value) {
    toast('请先选择场地')
    return false
  }
  if (endTime.value <= startTime.value) {
    toast('开始时间须早于结束时间')
    return false
  }
  return true
}

/** 出口一：直接建单（后端原子校验，冲突整单回滚） */
async function submit() {
  if (!checkReady()) return
  submitting.value = true
  try {
    const payload = {
      spaceId: selectedSpaceId.value,
      deviceIds: selectedDeviceIds.value.map(Number),
      agentRequest: buildOrderNote(),
    }
    Object.assign(payload, range())
    const res = await createOrder(payload, { silent: true })
    const orderId = res && (res.orderId || res.id)
    uni.showToast({ title: '预约创建成功', icon: 'success' })
    setTimeout(() => {
      /*
       * 建单成功后跳「预约详情」，并且用 **reLaunch 清空整个页面栈**（2026-10-14 定）。
       *
       * ## 为什么落点是详情页，不是首页、也不是预约列表
       *
       * 用户刚完成一次有副作用、不可撤销的操作，落点要回答「我到底订成功了什么」：
       *   · 首页 —— 等于丢掉反馈，还得自己再找进去；
       *   · 预约列表 —— 二十多条混在一起，刚建的那条要自己找；而且列表是
       *     「继续浏览」的语义，不是「一件事做完了」的落点；
       *   · 详情页 —— 预约单号、场地、时段、状态、能不能取消，当场都在。
       *
       * 详情页本身**不会被卡住**：它有导航栏的返回（回首页）与「返回列表」动作，
       * 取消成功后也会自己 reLaunch 到列表（见 order/detail.vue）。
       *
       * ## 为什么必须是 reLaunch
       *
       * 原先是 redirectTo。它替换的是**栈顶那一页**，而栈顶正是本页（confirm），
       * 底下压着的中间页一页不少，全留在了栈里：
       *
       *     本页从「语音/草图 → confirm」进来     → 栈变成 [record, detail]
       *     本页从「… → plan → confirm」进来      → 栈变成 [record, thinking, plan, detail]
       *
       * 于是用户在详情页按返回，会依次退回 plan / thinking / record 这些
       * **已经走完的中间页**。它们不是死页（plan 在建单时已 resetAgent 清掉缓存、
       * 点不出第二次提交），但用户会看到一个「看起来还能再确认一次」的方案页，
       * 分不清自己是退回去了还是又要下单 —— 这是纯粹的困惑，没有任何收益。
       *
       * reLaunch 清空页面栈，详情页成为唯一一页，从任何位置都回不到流程中间态。
       *
       * ## from=create 的作用
       *
       * 告诉详情页「你是因为刚建单才进来的」，它会据此**不渲染返回箭头**
       * （栈已清空，返回本身也没有意义），改由「返回列表」给出唯一出口。
       * 正常从列表点进详情时不带这个参数，返回箭头照旧。
       *
       * ## orderId 缺失时为什么仍然去详情页
       *
       * 后端建单成功**一定会返回 orderId**，拿不到属于异常。此时若改跳列表，
       * 用户会停在没被清栈的表单页上、又看不到任何成功证据，很容易再点一次提交。
       * 带着空 id 去详情页更好：详情页读不到订单会渲染 mp-empty
       * 「没有找到这条预约」并给出「返回列表」，反馈链是完整的。
       */
      uni.reLaunch({ url: '/pages/order/detail?from=create&orderId=' + encodeURIComponent(orderId || '') })
    }, 700)
  } catch (e) {
    // 请求层已经弹过后端原因（「该时段已被占用」），这里只把「接下来怎么办」说清楚
    uni.showModal({
      title: '该时段存在冲突',
      content: ((e && e.message) || '所选时段或设备已被占用') + '，已刷新可用场地与设备，请重新选择。',
      showCancel: false,
      confirmText: '重新选择',
    })
    refreshAll()
  } finally {
    submitting.value = false
  }
}

/** 出口二：交给核心调度 Agent（把已选的作为明确需求传过去） */
function goAgent() {
  if (!checkReady()) return
  agentStore.request = buildAgentRequest()
  agentStore.lastQuestion = ''
  // 拍照识场带过来的 imageContext 原样转交；草图的识别结果也在这里一并给 Agent
  agentStore.imageContext = prefill.imageContext || null
  uni.navigateTo({ url: '/pages/agent/thinking' })
}

onMounted(() => {
  capacity.value = prefill.capacity ? String(prefill.capacity) : ''
  spaceTypeIndex.value = prefill.spaceType
    ? Math.max(0, SPACE_TYPES.findIndex((t) => t.value === prefill.spaceType))
    : 0
  selectedSpaceId.value = prefill.spaceId || null

  if (prefill.slotStart && prefill.slotEnd) {
    // 拍照识场里已经选过时段：直接用，用户不用再选一遍
    const s = parseDateTime(prefill.slotStart)
    const e2 = parseDateTime(prefill.slotEnd)
    if (s && e2) {
      date.value = todayStr(s)
      startTime.value = hhmm(s)
      endTime.value = hhmm(e2)
    }
  }
  if (!date.value) {
    const now = new Date()
    const start = ceilToQuarter(now)
    const end = new Date(start.getTime() + 60 * 60 * 1000)
    date.value = todayStr(now)
    startTime.value = hhmm(start)
    endTime.value = hhmm(end)
  }

  // ⚠️ 预填了场地时也要走 selectSpace（而不是只赋值 selectedSpaceId）：
  //    它顺带取该场地的开放时段，时间选项才会按真实开放时间收敛。
  //    只赋值的话 picker 会停在兜底的 7:00~23:00，用户能选到场地没开门的时间。
  if (selectedSpaceId.value !== null && selectedSpaceId.value !== undefined) {
    selectSpace(selectedSpaceId.value)
  }

  refreshDevices().then(() => preselectByTypes(prefill.deviceTypes))
  refreshSpaces()
})
</script>

<style scoped>
/* 页面骨架用项目统一的 .app-page / .app-body（固定导航栏的高度由 mp-nav-bar 的占位块负责），
   这里只加一点底部余量，避免最后一张卡片贴屏幕底 */
.app-body {
  padding-bottom: 60rpx;
}
.src {
  display: flex;
  gap: var(--s2);
  background: var(--primary-bg);
  border-radius: var(--r-md);
  padding: 22rpx;
  margin-bottom: 20rpx;
}
.src-ic {
  font-size: 40rpx;
  line-height: 1.2;
}
.src-body {
  flex: 1;
}
.src-t {
  display: block;
  font-size: 27rpx;
  font-weight: 600;
  color: var(--t1);
}
.src-x {
  display: block;
  font-size: 24rpx;
  color: var(--t2);
  margin-top: 8rpx;
  line-height: 1.6;
}
.card {
  background: #fff;
  border-radius: var(--r-md);
  padding: 24rpx;
  margin-bottom: 20rpx;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14rpx;
}
.card-title {
  font-size: 30rpx;
  font-weight: 600;
  color: var(--t1);
}
.card-sub {
  font-size: 22rpx;
  color: var(--t3);
}
.link {
  font-size: 24rpx;
  color: var(--primary-h);
}
.kv,
.kv2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16rpx 0;
  border-top: 1rpx solid var(--bd-l);
}
.k {
  color: var(--t3);
  font-size: 26rpx;
  flex-shrink: 0;
  width: 120rpx;
}
.v {
  color: var(--t1);
  font-size: 26rpx;
  flex: 1;
  text-align: right;
}
.pick {
  color: var(--primary-h);
}

/* ---- 可禁用的时间格（2026-10-14 加）----
 * 替代原生 picker：微信 picker 无法按项置灰，而「已占用的档位不可点」
 * 必须在选择阶段就体现出来，否则用户填完才吃 409。
 */
.kv.kv-block {
  /* 时间格会换行成多行，不能再按「标签 + 单行值」垂直居中 */
  align-items: flex-start;
  flex-direction: column;
  gap: 12rpx;
}

.tgrid {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  width: 100%;
}

.tcell {
  min-width: 104rpx;
  text-align: center;
  font-size: 24rpx;
  padding: 12rpx 0;
  border-radius: var(--r-sm);
  color: var(--t1);
  background: var(--bg-hover);
  border: 1px solid var(--bd-l);
}

.tcell.on {
  color: #fff;
  background: var(--primary);
  border-color: var(--primary);
  font-weight: 600;
}

/* 已占用：置灰 + 划掉，并从视觉上明确「不是没渲染，是不可选」 */
.tcell.off {
  color: var(--t3);
  background: transparent;
  border-style: dashed;
  text-decoration: line-through;
  opacity: 0.55;
}

.tgrid-note,
.tgrid-empty {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.6;
}

.tgrid-warn {
  display: block;
  font-size: 22rpx;
  color: var(--warning);
  background: var(--warning-bg);
  border-radius: var(--r-xs);
  padding: 12rpx 16rpx;
  margin-top: 12rpx;
  line-height: 1.6;
}
.num {
  flex: 1;
  text-align: right;
  font-size: 26rpx;
  color: var(--t1);
}
.hint {
  font-size: 24rpx;
  color: var(--t3);
  padding: 12rpx 0;
}
.hint.is-warn {
  color: var(--warning);
}
.opts {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: 8rpx;
}
.opt {
  border: 2rpx solid var(--bd-l);
  border-radius: var(--r-sm);
  padding: 18rpx 20rpx;
}
.opt.is-on {
  border-color: var(--primary-h);
  background: var(--primary-bg);
}
.opt-line {
  display: flex;
  align-items: center;
  gap: var(--s2);
}
.opt-name {
  font-size: 28rpx;
  color: var(--t1);
  font-weight: 500;
}
.badge {
  font-size: 20rpx;
  color: var(--primary-h);
  background: var(--primary-line);
  border-radius: var(--r-xs);
  padding: 2rpx 10rpx;
}
.opt-meta {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  margin-top: 6rpx;
}
.devs {
  display: flex;
  flex-direction: column;
  gap: var(--s1);
}
.dev {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 14rpx 0;
  border-top: 1rpx solid var(--bd-l);
}
.dev.is-off {
  opacity: 0.45;
}
.dev-n {
  font-size: 26rpx;
  color: var(--t1);
  flex: 1;
}
.dev-r {
  font-size: 22rpx;
  color: var(--chart-ok);
}
.dev-r.is-zero {
  color: var(--chart-full);
}
.acts {
  margin-top: 8rpx;
}
.acts .btn {
  margin-bottom: 18rpx;
}
.foot {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  text-align: center;
}
</style>
