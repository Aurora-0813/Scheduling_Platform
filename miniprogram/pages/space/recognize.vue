<template>
  <view class="app-page">
    <mp-nav-bar title="拍照识场" back />

    <view class="app-body has-cta">
      <!--
        两种输入方式并列：拍照识场 / 手绘草图（2026-10-13 加）。
        手绘草图走的是**独立的预约流程页**（它要额外选设备/时间/场地并直接建单，
        与「识别出一个已知场地再去预约」是两条链路），所以这里用 redirectTo 而不是
        navigateTo —— 两者是同一层级的「模式」，叠页面栈会让返回行为变得莫名其妙。
      -->
      <view class="modebar">
        <view class="mode on">📷 拍照识场</view>
        <view class="mode" hover-class="btn-on" :hover-stay-time="60" @tap="goSketch">✍️ 手绘草图</view>
      </view>

      <view class="imgbox" @tap="pick">
        <image v-if="photo" class="photo" :src="photo" mode="aspectFill" />
        <view v-else class="cam">
          <text class="big">📷</text>
          <text>拍下门牌或场地，AI 识别空间与可用设备</text>
        </view>
        <view v-if="photo" class="bbox on-photo">
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
        </view>
        <view v-if="analyzing" class="scanline"></view>
      </view>

      <view v-if="result">
        <!-- 置信度不足：按 §4.4 模块 2 向用户追问，不直接当成已确认结果 -->
        <view v-if="result.needConfirm" class="witem blue">
          <text class="wt">需要你确认一下</text>
          <text class="wp">{{ result.question || '这张照片不太确定，请选择或补充信息。' }}</text>
          <view v-if="candidates.length" class="cands">
            <view
              v-for="(c, i) in candidates"
              :key="i"
              class="cand"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap="pickCandidate(c)"
            >
              <text class="cn-name">{{ candidateName(c) }}</text>
              <text v-if="candidateConf(c)" class="cn-conf">{{ candidateConf(c) }}</text>
            </view>
          </view>
        </view>

        <view class="mcard">
          <view class="mtitle">
            <text>识别结果</text>
            <text v-if="confidenceText" class="more">{{ confidenceText }}</text>
          </view>

          <view class="mbrow">
            <text class="k">场地</text>
            <text class="v">{{ displayName }}</text>
          </view>
          <view v-if="result.type" class="mbrow">
            <text class="k">类型</text>
            <text class="v">{{ typeText }}</text>
          </view>
          <view v-if="result.capacity" class="mbrow">
            <text class="k">容量</text>
            <text class="v">{{ result.capacity }} 人</text>
          </view>
          <view v-if="result.layout" class="mbrow">
            <text class="k">布局</text>
            <text class="v">{{ result.layout }}</text>
          </view>
        </view>

        <!--
          选时段：**先选日期（未来两周），再选当天的空闲时段**。
          只列真空闲的段（占用口径与下单判重同源），选了必然锁得上，
          不会出现「Agent 假设一个时间 → 该段已被占 → 转备选或报无方案」。
          时段的样式刻意用中性灰做「未选中」态 —— 之前用主色描边，
          一排全都是蓝的，看起来像全都选中了。
        -->
        <view v-if="result.spaceId || slotsLoading || slotsNote" class="mcard">
          <view class="mtitle">
            <text>选择使用时段</text>
            <text v-if="slotsLoading" class="more">查询中…</text>
          </view>

          <text v-if="slotsLoading" class="mtext">
            正在查这个场地未来 {{ SLOT_DAYS }} 天的占用…
          </text>
          <text v-else-if="slotsNote" class="mtext">{{ slotsNote }}</text>

          <template v-else>
            <!--
              时间选择（2026-10-14 改版）。

              原先这里是「1 选日期（未来两周横滚）→ 2 从当天算好的空闲段里点一个」。
              改成与「确认预约」页同一种交互：**日期 + 开始 / 结束时间**。

              两个改进：
                1. 可选时间**严格来自该场地的开放时段**（spaceMeta.openStartTime/EndTime），
                   不再拿一个写死的 7:00~23:45 去套所有场地 —— 展厅 9:00 才开、
                   中心广场 6:00 就开，场地之间不一样；
                2. 用户自己定起止，而不是从系统算好的段里挑。

              仍然比「确认预约」多一层保护：这里能拿到该场地的占用数据，
              所以选到与已有预约重叠的时间时会**提示**（不拦，真正的判重在后端事务里）。
            -->
            <view class="kv">
              <text class="k">日期</text>
              <picker mode="date" :value="selectedDay || todayKey" :start="todayKey" :end="maxDateKey" @change="onDateChange">
                <text class="v pick">{{ dateLabel }} ›</text>
              </picker>
            </view>
            <view class="kv">
              <text class="k">开始</text>
              <picker mode="selector" :range="timeOptions" :value="startIndex" @change="onStartChange">
                <text class="v pick">{{ startTime || '请选择' }} ›</text>
              </picker>
            </view>
            <view class="kv">
              <text class="k">结束</text>
              <picker mode="selector" :range="endTimeOptions" :value="endIndex" @change="onEndChange">
                <text class="v pick">{{ endTime || '请选择' }} ›</text>
              </picker>
            </view>
            <text class="card-sub">
              可预约时间：{{ openRangeText }}（本场地的开放时段，{{ TIME_STEP_MIN }} 分钟一档）
            </text>
            <text v-if="conflictHint" class="slotnote warn">{{ conflictHint }}</text>
          </template>
        </view>

        <!-- 识别到的设备 -->
        <view v-if="devices.length" class="mcard">
          <view class="mtitle">识别到的设备</view>
          <view v-for="(d, i) in devices" :key="i" class="mbrow">
            <text class="k">{{ d.deviceType || '设备' }}</text>
            <text class="v">{{ d.count || 1 }} 台{{ confSuffix(d.confidence) }}</text>
          </view>
        </view>

        <!-- 草图识别的需求项 -->
        <view v-if="requirements.length" class="mcard">
          <view class="mtitle">识别到的需求</view>
          <view class="chips">
            <text v-for="(r, i) in requirements" :key="i" class="chip">{{ r }}</text>
          </view>
        </view>
      </view>

      <text v-if="!photo" class="note">
        支持 {{ IMAGE_LIMIT.EXT.join(' / ') }}，单张不超过 {{ IMAGE_LIMIT.MAX_MB }}MB。
      </text>
    </view>

    <view class="app-cta">
      <view
        v-if="!result"
        class="btn ai block"
        :class="{ disabled: analyzing }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="pick"
      >{{ analyzing ? 'AI 识别中…' : '拍一张试试' }}</view>

      <view v-else class="app-cta-row">
        <view class="btn ghost" hover-class="btn-on" @tap="pick">重拍</view>
        <view
          class="btn ai grow"
          :class="{ disabled: needsSlot }"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="goConfirm"
        >{{ needsSlot ? '请先选时间段' : '下一步：确认预约 →' }}</view>
      </view>
    </view>
  </view>
</template>

<script setup>
/**
 * 拍照识场
 *
 * 契约：POST /image/analyze  multipart，字段名固定 file
 *   → { type, spaceId, spaceName, confidence, availableTime[], devices[],
 *       needConfirm, question, candidates[], imageUrl }
 * 另有 POST /image/sketch 用于手绘草图（本页暂只接 analyze）。
 *
 * ⚠️ confidence 低于阈值时后端给 needConfirm=true + question，
 *   此时**不能**直接把结果当成已确认场地用，必须先追问（§4.4 模块 2）。
 * ⚠️ imageUrl 是 /uploads/... 相对路径，展示前要走 `absoluteUrl()` 拼后端地址 ——
 *   它**每次现取**地址（登录页可在运行时改，内网穿透换地址后不必重打包）。
 */
import { ref, computed } from 'vue'
import { onUnload } from '@dcloudio/uni-app'
import { analyze } from '@/api/image.js'
import { absoluteUrl } from '@/api/request.js'
import { spaceBookings } from '@/api/resources.js'
import { spaceTypeLabel } from '@/utils/dict.js'
import { IMAGE_LIMIT } from '@/config/index.js'
import { first } from '@/utils/normalize.js'
import { toast, showLoading, hideLoading, resetLoading } from '@/utils/toast.js'
import { agentStore } from '@/store/agent.js'
import { setPrefill } from '@/store/reservePrefill.js'
import { userStore } from '@/store/user.js'
import { parseDateTime } from '@/utils/format.js'

// 页面销毁时把 loading 计数归零：万一有哪条路径没配平，残留的计数会让之后
// 每一次 show/hide 都错位 —— 微信侧会一直报「showLoading 与 hideLoading 必须配对使用」
onUnload(() => resetLoading())

/** 可选日期范围：从今天起往后两周 */
const SLOT_DAYS = 14
/** 时间选择器的粒度（分钟）。15 分钟与「确认预约」页保持一致 */
const TIME_STEP_MIN = 15

const WEEKDAY_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const photo = ref('')
const result = ref(null)
const analyzing = ref(false)
/** /booked 返回的场地权威信息（容量 / 位置 / 开放时段）—— 识别结果里没有这些 */
const spaceMeta = ref(null)
/**
 * 该场地**已被占用**的时段（原始区间，已排序）。
 *
 * ⚠️ 2026-10-14 改版：这里不再预先把「空闲段」算成一个可点列表，
 *    而是留作**冲突提示**用 —— 用户要的是「自己选开始/结束」，不是「从系统给的段里挑」。
 *    占用口径仍由后端 /booked 过滤（1 待确认 / 2 已确认），前端只做区间求交。
 */
const busyRanges = ref([])
/** 当前选中的日期 key（YYYY-MM-DD）；空串表示还没选 */
const selectedDay = ref('')
/** 开始 / 结束时间（HH:mm），**必选项**，没选全不让往下走 */
const startTime = ref('')
const endTime = ref('')
const slotsLoading = ref(false)
const slotsNote = ref('')

/** 未来两周的日期选项（含「这天有没有空档」，没空档的置灰不可点） */
const dayOptions = computed(() => {
  const now = new Date()
  const out = []
  for (let i = 0; i < SLOT_DAYS; i++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i)
    const key = ymd(day)
    out.push({
      key,
      label: dayLabel(i, day),
      sub: pad2(day.getMonth() + 1) + '-' + pad2(day.getDate()),
    })
  }
  return out
})

/** 场地开放时段（分钟数），未取到时为 null */
const openStartMin = computed(() => clockToMinutes((spaceMeta.value || {}).openStartTime))
const openEndMin = computed(() => clockToMinutes((spaceMeta.value || {}).openEndTime))

/** 日期 + 场地名，给 picker 和提示文案用 */
const dateLabel = computed(() => {
  if (!selectedDay.value) return '请选择日期'
  const d = dayOptions.value.find((x) => x.key === selectedDay.value)
  return selectedDay.value + (d ? ' ' + d.label : '')
})

/**
 * 时间选择器的选项：**严格取自场地的开放时段**，按 TIME_STEP_MIN 切档。
 *
 * ⚠️ 关键口径：不做「8:00~22:00 写死」—— 每个场地开放时间不同
 *    （A栋201 是 8:00-22:00、展厅是 9:00-21:00、中心广场 6:00-23:00），
 *    写死会让用户选到场地没开门的时间，提交时才被后端拒。
 *    后端 space_service.py 是按 open_start_time / open_end_time 过滤的，这里同源。
 *
 * 选今天时，**已过去的时间不出现**：给一个已经开始的时间点没有意义。
 */
const timeOptions = computed(() => {
  const s = openStartMin.value
  const e = openEndMin.value
  if (s === null || e === null || e <= s) return []
  const isToday = selectedDay.value === ymd(new Date())
  const now = new Date()
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const out = []
  for (let m = s; m <= e; m += TIME_STEP_MIN) {
    if (isToday && m <= nowMin) continue
    out.push(pad2(Math.floor(m / 60)) + ':' + pad2(m % 60))
  }
  return out
})

/** 结束时间只能在**开始时间之后**，所以从下一档开始给 */
const endTimeOptions = computed(() => {
  const i = timeOptions.value.indexOf(startTime.value)
  if (i < 0) return timeOptions.value
  return timeOptions.value.slice(i + 1)
})

/** 日期 picker 不能选过去：start 取今天 */
const todayKey = computed(() => ymd(new Date()))

/** 日期 picker 的上限：今天 + (SLOT_DAYS - 1) 天 */
const maxDateKey = computed(() => {
  const d = new Date()
  d.setDate(d.getDate() + SLOT_DAYS - 1)
  return ymd(d)
})

/** picker 的下标回显（没选过时给 0，picker 自己会显示第一项） */
const startIndex = computed(() => Math.max(0, timeOptions.value.indexOf(startTime.value)))
const endIndex = computed(() => Math.max(0, endTimeOptions.value.indexOf(endTime.value)))

/** 「可预约时间：8:00 – 22:00」这行提示，直接来自场地开放时段 */
const openRangeText = computed(() => {
  const meta = spaceMeta.value || {}
  const s = meta.openStartTime
  const e = meta.openEndTime
  if (!s || !e) return '以场地实际开放时间为准'
  return String(s).slice(0, 5) + ' – ' + String(e).slice(0, 5)
})

/**
 * 用户选的时间段是否与已有预约重叠。
 *
 * 前端**不拦**，只提示：占用数据可能因他人下单而过期，真正的判重在后端事务里
 * （space_service 用 SELECT ... FOR UPDATE 锁资源）。这里拦反而会拦错。
 */
const conflictHint = computed(() => {
  const s = hmToMin(startTime.value)
  const e = hmToMin(endTime.value)
  if (s === null || e === null || e <= s || !selectedDay.value) return ''
  const dayKey = selectedDay.value
  const hit = busyRanges.value.find(
    (b) => b.dayKey === dayKey && s < b.endMin && e > b.startMin
  )
  if (!hit) return ''
  return (
    '这段时间与已有预约（' +
    pad2(Math.floor(hit.startMin / 60)) + ':' + pad2(hit.startMin % 60) +
    '-' +
    pad2(Math.floor(hit.endMin / 60)) + ':' + pad2(hit.endMin % 60) +
    '）重叠，提交时可能被拒。'
  )
})

/**
 * 时间段是**必选项**：日期、开始、结束三项都要有。
 * 选今天且当天已无可选时间时（开放时段都过去了），不做强制，否则用户被卡死。
 */
const needsSlot = computed(() => {
  if (!selectedDay.value) return true
  if (!startTime.value || !endTime.value) return true
  return false
})

const candidates = computed(() => {
  const c = result.value ? result.value.candidates : null
  return Array.isArray(c) ? c : []
})

const devices = computed(() => {
  const d = result.value ? result.value.devices : null
  return Array.isArray(d) ? d : []
})

const requirements = computed(() => {
  const r = result.value ? result.value.requirements : null
  return Array.isArray(r) ? r : []
})

const displayName = computed(() => {
  const r = result.value
  if (!r) return ''
  return first(r.spaceName, r.name, '未识别出场地名')
})

/** type 可能是 'space'/'sketch' 这类英文枚举，也可能直接是中文场地类型 */
const typeText = computed(() => {
  const t = result.value ? result.value.type : ''
  if (t === 'space') return '实体场地'
  if (t === 'sketch') return '手绘草图'
  return spaceTypeLabel(t)
})

const confidenceText = computed(() => {
  const c = result.value ? result.value.confidence : null
  if (c === undefined || c === null || c === '') return ''
  const n = Number(c)
  if (isNaN(n)) return ''
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `置信度 ${pct}%`
})

function confSuffix(c) {
  const n = Number(c)
  if (!c || isNaN(n)) return ''
  return `（${n <= 1 ? Math.round(n * 100) : Math.round(n)}%）`
}

function candidateName(c) {
  if (typeof c === 'string') return c
  return first(c.spaceName, c.name, '候选场地')
}

function candidateConf(c) {
  if (typeof c === 'string') return ''
  const n = Number(c.confidence)
  if (!c.confidence || isNaN(n)) return ''
  return `${n <= 1 ? Math.round(n * 100) : Math.round(n)}%`
}

/** 切到「手绘草图」模式（独立的预约流程页）。用 redirectTo：两者是同层级的模式，不叠页面栈。 */
function goSketch() {
  uni.redirectTo({ url: '/pages/space/sketch' })
}

function pick() {
  if (analyzing.value) return

  const onPicked = (path, size) => {
    if (!validate(path, size)) return
    photo.value = path
    result.value = null
    run(path)
  }

  if (typeof uni.chooseMedia === 'function') {
    uni.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera', 'album'],
      sizeType: ['compressed'],
      success: (res) => {
        const f = res.tempFiles && res.tempFiles[0]
        if (f) onPicked(f.tempFilePath, f.size)
      },
      fail: () => {},
    })
    return
  }

  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: (res) => {
      const path = res.tempFilePaths && res.tempFilePaths[0]
      const file = res.tempFiles && res.tempFiles[0]
      if (path) onPicked(path, file ? file.size : 0)
    },
    fail: () => {},
  })
}

/** 与后端 image.py 的限制保持一致（≤5MB，仅四种格式） */
function validate(path, size) {
  if (size && size > IMAGE_LIMIT.MAX_MB * 1024 * 1024) {
    toast(`图片不能超过 ${IMAGE_LIMIT.MAX_MB}MB`)
    return false
  }
  const m = String(path).match(/\.([a-zA-Z0-9]+)(?:\?|$)/)
  if (m && IMAGE_LIMIT.EXT.indexOf(m[1].toLowerCase()) < 0) {
    toast(`仅支持 ${IMAGE_LIMIT.EXT.join(' / ')}`)
    return false
  }
  return true
}

async function run(path) {
  analyzing.value = true
  showLoading('AI 识别中…')
  try {
    result.value = await analyze(path)
    // 后端回传的图片地址是相对路径，做展示用（当前页面用的是本地临时图）
    if (result.value && result.value.imageUrl) {
      result.value.imageUrl = absoluteUrl(result.value.imageUrl)
    }
    // 识别到具体场地 → 顺手查它未来几天的占用，反算空闲时段给用户点
    if (result.value && result.value.spaceId !== undefined && result.value.spaceId !== null) {
      loadFreeSlots(result.value.spaceId)
    }
  } catch (e) {
    toast(e.message || '识别失败，请换一张照片试试')
    result.value = null
  } finally {
    analyzing.value = false
    hideLoading()
  }
}

/** 用户在追问里选定了一个候选场地，直接采信该结果 */
function pickCandidate(c) {
  const name = candidateName(c)
  // ⚠️ 候选里带着 spaceId，原来只取了名字就丢掉 —— 丢掉 id 就等于后面
  // 查不了该场地的占用，也传不了 imageContext，等于白选一次
  const sid =
    typeof c === 'object' && c ? (c.spaceId !== undefined ? c.spaceId : c.id) : undefined
  result.value = { ...result.value, needConfirm: false, spaceName: name, spaceId: sid }
  toast(`已按「${name}」继续`)
  if (sid !== undefined && sid !== null) loadFreeSlots(sid)
}

// ------------------------------------------------------------------
// 空闲时段：识别到场地后，查它未来几天的占用，反算可约的空档
// ------------------------------------------------------------------
/**
 * 数据源是 `GET /resources/spaces/{id}/booked`（2026-09-30 新增）。
 *
 * 为什么要在这里算：`/image/analyze` 也会回一个 `availableTime`，
 * 但它**只算今天**、且语义在后端文档里都标着「待确认」。用户要的是
 * 「这个场地这几天什么时候能用」，直接查占用自己减更准，也能跨天。
 */
async function loadFreeSlots(spaceId) {
  spaceMeta.value = null
  busyRanges.value = []
  selectedDay.value = ''
  startTime.value = ''
  endTime.value = ''
  slotsNote.value = ''
  if (spaceId === undefined || spaceId === null || spaceId === '') return
  if (!userStore.loggedIn) {
    slotsNote.value = '登录后可查看这个场地的占用时段'
    return
  }

  slotsLoading.value = true
  try {
    const res = await spaceBookings(spaceId, SLOT_DAYS)
    spaceMeta.value = res || null
    busyRanges.value = extractBusyRanges(res)
    // 默认落在今天；若今天开放时段已过完，时间选项会是空的，用户自己换日期
    selectedDay.value = ymd(new Date())
  } catch (e) {
    slotsNote.value = (e && e.message) || '占用时段查询失败'
  } finally {
    slotsLoading.value = false
  }
}

/**
 * 从 /booked 的响应里抽出「已占用区间」，供冲突提示使用。
 *
 * ⚠️ 占用口径不在这里重判：后端已经按「1 待确认 / 2 已确认」过滤过
 *    （与下单判重同源），前端只做区间求交，避免两处口径漂移。
 */
function extractBusyRanges(res) {
  const bookings = Array.isArray((res || {}).bookings) ? res.bookings : []
  const out = []
  bookings.forEach((b) => {
    const s = parseDateTime(b.startTime)
    const e = parseDateTime(b.endTime)
    if (!s || !e || e <= s) return
    // 跨天占用（本系统按日开放，正常不会出现）拆成不处理：只取同一天内的交集，
    // 若起止不在同一天，就按各自那天的分钟数记录，宁可多提示也不漏提示
    const dayKey = ymd(s)
    out.push({
      dayKey,
      startMin: s.getHours() * 60 + s.getMinutes(),
      endMin: e.getDate() === s.getDate() ? e.getHours() * 60 + e.getMinutes() : 24 * 60,
    })
  })
  return out
}

function clockToMinutes(t) {
  const m = String(t || '').match(/^(\d{1,2}):(\d{2})/)
  if (!m) return null
  return Number(m[1]) * 60 + Number(m[2])
}

function pad2(n) {
  return n < 10 ? '0' + n : String(n)
}

function ymd(d) {
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}

/** 'HH:mm' → 分钟数；无法解析返回 null */
function hmToMin(t) {
  const m = String(t || '').match(/^(\d{1,2}):(\d{2})$/)
  if (!m) return null
  return Number(m[1]) * 60 + Number(m[2])
}

/** 今天 / 明天 / 后天，再往后直接给星期几 */
function dayLabel(offset, day) {
  if (offset === 0) return '今天'
  if (offset === 1) return '明天'
  if (offset === 2) return '后天'
  return WEEKDAY_CN[day.getDay()]
}

/**
 * 把识别结果作为图像上下文交给核心调度 Agent（模块 2 → 模块 4 的设计通道）。
 *
 * 这一步是**必须的**：只把场地名拼进一句话，Agent 得从文本里重新猜是哪个场地，
 * 拿到 spaceId 它才能直接用（实测：补上上下文后，从「追问哪个场地」变成
 * 「已为您定位到 A栋201会议室」，耗时 32s → 10s）。
 */
function pushImageContext() {
  const r = result.value
  const meta = spaceMeta.value || {}
  const sid = r && r.spaceId !== undefined && r.spaceId !== null ? r.spaceId : meta.spaceId
  if (sid === undefined || sid === null) {
    agentStore.imageContext = null
    return
  }
  agentStore.imageContext = {
    source: 'image_analyze',
    spaceId: sid,
    spaceName: (r && r.spaceName) || meta.spaceName || '',
    spaceType: meta.spaceType,
    location: meta.location || '',
    capacity: meta.capacity,
    confidence: r ? r.confidence : undefined,
  }
}

/**
 * 带着识别到的场地去预约。
 *
 * 时间段是**必选项**：只要这个场地还有可选时段，就必须先选中一段才让走
 * （按钮会置灰并改文案提示）。一段都没有时不做强制，否则用户会被卡死在这页。
 *
 * 文本里带上场地名、容量与选中的时段，**同时**把 imageContext 交给 Agent：
 * 文本是给人改的（跳过去还能接着说），imageContext 才是给 Agent 用的权威数据（含 spaceId）。
 */
/** 日期 + 开始/结束 → 绝对起止时间（确认页要的是 YYYY-MM-DD HH:mm:ss） */
function slotBounds() {
  if (!selectedDay.value || !startTime.value || !endTime.value) return { start: '', end: '' }
  return {
    start: selectedDay.value + ' ' + startTime.value + ':00',
    end: selectedDay.value + ' ' + endTime.value + ':00',
  }
}

/** 选日期：换日期必须清掉已选时间（时间选项是按天重算的，留着会是无效档位） */
function onDateChange(e) {
  selectedDay.value = e.detail.value
  startTime.value = ''
  endTime.value = ''
}

/** 选开始时间：顺手把结束时间推到下一档，省一次点击（用户可再改） */
function onStartChange(e) {
  const list = timeOptions.value
  const i = Number(e.detail.value)
  startTime.value = list[i] || ''
  const next = list[i + 1] || list[i]
  // 只在「结束时间还没选，或已被推到开始之前」时才自动带一个默认值
  if (next && (!endTime.value || hmToMin(endTime.value) <= hmToMin(startTime.value))) {
    endTime.value = next
  }
}

function onEndChange(e) {
  endTime.value = endTimeOptions.value[Number(e.detail.value)] || ''
}

/**
 * 去确认页补齐信息（2026-10-13 改）。
 *
 * 原先这里直接跳**语音页**，等于把「选设备」整个跳过了 ——
 * 拍照能认出是哪间场地和人数，但**认不出该用哪些设备**
 * （照片里有没有投影仪，和这次要不要用投影仪，是两回事），时间也通常拍不出来。
 * 所以现在把识别到的部分（场地 / 人数 / 设备类型 / 时段）预填进确认页，
 * 缺的（主要是具体设备）交给用户在那里补。
 */
function goConfirm() {
  if (!result.value) return
  if (needsSlot.value) {
    toast('请先选日期、开始与结束时间')
    return
  }
  const name = displayName.value
  const meta = spaceMeta.value || {}
  const cap = meta.capacity || result.value.capacity || null
  const types = (devices.value || []).map((d) => d.deviceType).filter(Boolean)
  const bounds = slotBounds()

  pushImageContext() // 先把 imageContext 写进 agentStore，再原样转交给确认页
  const sid = result.value.spaceId
  setPrefill({
    source: 'image',
    sourceLabel: '拍照识场',
    spaceId: sid === undefined || sid === null ? null : sid,
    capacity: cap,
    spaceType: meta.spaceType || 0,
    deviceTypes: types,
    slotStart: bounds.start,
    slotEnd: bounds.end,
    text:
      '我要预约' +
      name +
      (cap ? '，' + cap + '人' : '') +
      (bounds.start ? '，' + bounds.start + ' 至 ' + bounds.end : ''),
    imageContext: agentStore.imageContext,
  })
  uni.navigateTo({ url: '/pages/reserve/confirm' })
}
</script>

<style scoped>
/* 输入方式模式条（2026-10-13 加）：拍照识场 / 手绘草图 并列 */
.modebar {
  display: flex;
  gap: var(--s2);
  margin-bottom: 22rpx;
}

.modebar .mode {
  flex: 1;
  text-align: center;
  font-size: 27rpx;
  padding: 18rpx 0;
  border-radius: var(--r-pill);
  color: var(--t2);
  background: var(--bg-hover);
  border: 1px solid var(--bd-l);
}

.modebar .mode.on {
  color: #fff;
  background: var(--primary-h);
  border-color: var(--primary-h);
  font-weight: 600;
}

.photo {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.note {
  display: block;
  text-align: center;
  font-size: 22rpx;
  color: var(--t3);
  padding: 0 30rpx;
  line-height: 1.7;
}

.cands {
  display: flex;
  flex-direction: column;
  gap: var(--s2);
  margin-top: 18rpx;
}

.cand {
  display: flex;
  align-items: center;
  gap: var(--s2);
  background: #fff;
  border: 1px solid var(--ai-line);
  border-radius: var(--r-md);
  padding: 20rpx 24rpx;
}

.cn-name {
  flex: 1;
  font-size: 26rpx;
  color: var(--t1);
}

.cn-conf {
  font-size: 22rpx;
  color: var(--t3);
}

.app-cta-row .btn.ghost {
  flex: 1;
}

.app-cta-row .grow {
  flex: 1.8;
}

/* ---- 选时段：两步（先日期，后时间段） ---- */
.stepk {
  display: block;
  font-size: 23rpx;
  color: var(--t3);
  margin: 22rpx 0 14rpx;
}

/* 日期横向滚动条 */
.dayscroll {
  width: 100%;
  white-space: nowrap;
}

.dayrow {
  display: flex;
  gap: var(--s2);
  padding-bottom: 4rpx;
}

/*
  ⚠️ 关键：**未选中态必须是中性灰**。
  之前一排在用主色描边 + 浅蓝底，看上去全都是「已选中」——
  用户反馈的就是这个。现在未选中一律灰底灰边，只有 .on 才上主色实心。
*/
.day {
  flex: none;
  width: 108rpx;
  padding: 14rpx 0;
  text-align: center;
  border-radius: var(--r-md);
  background: var(--bg-hover);
  border: 1px solid var(--bd-l);
}

.day.off {
  opacity: 0.35;
}

.day .dl {
  display: block;
  font-size: 24rpx;
  color: var(--t1);
}

.day .ds {
  display: block;
  font-size: 20rpx;
  color: var(--t3);
  margin-top: 4rpx;
}

.day.on {
  background: var(--primary);
  border-color: var(--primary);
}

.day.on .dl,
.day.on .ds {
  color: #fff;
}

/* 时间段按钮：同样，未选中灰、选中才实心主色 */
.slotgrid {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
}

/* ---- 时间选择（2026-10-14 改版）----
 * 由「点空闲段」改为「日期 + 开始/结束时间」选择器，
 * 所以下面用 .kv 承载 picker —— 与「确认预约」页的 ① 使用时间 是同一套写法。
 */
.kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16rpx 0;
  border-top: 1rpx solid var(--bd-l);
}

.kv .k {
  color: var(--t3);
  font-size: 26rpx;
  flex-shrink: 0;
  width: 120rpx;
}

/* 可点区域要撑满右侧，否则只有文字那一小块能点，手感很差 */
.kv picker {
  flex: 1;
  min-width: 0;
}

.pick {
  display: block;
  text-align: right;
  font-size: 26rpx;
  color: var(--primary);
}

.card-sub {
  display: block;
  margin-top: 14rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.6;
}

.slotnote {
  display: block;
  margin-top: 20rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
}

/* 与已有预约重叠时的提示。用 warning 色（这是「可能失败」的提示，不是错误） */
.slotnote.warn {
  color: var(--warning);
  background: var(--warning-bg);
  border-radius: var(--r-xs);
  padding: 12rpx 16rpx;
}
</style>
