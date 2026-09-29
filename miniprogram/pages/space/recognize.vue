<template>
  <view class="app-page">
    <mp-nav-bar title="拍照识场" back />

    <view class="app-body has-cta">
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
            <text>🤖 AI 识别结果</text>
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
            <text class="stepk">1 · 选日期（未来两周）</text>
            <scroll-view scroll-x class="dayscroll" :show-scrollbar="false">
              <view class="dayrow">
                <view
                  v-for="d in dayOptions"
                  :key="d.key"
                  class="day"
                  :class="{ on: selectedDay === d.key, off: !d.hasSlot }"
                  hover-class="btn-on"
                  :hover-stay-time="60"
                  @tap="selectDay(d)"
                >
                  <text class="dl">{{ d.label }}</text>
                  <text class="ds">{{ d.sub }}</text>
                </view>
              </view>
            </scroll-view>

            <text class="stepk">2 · 选时间段{{ selectedSlot ? '' : '（必选）' }}</text>
            <text v-if="!selectedDay" class="mtext">先选一个日期</text>
            <text v-else-if="!currentSlots.length" class="mtext">
              这天没有可用的时段，换一天试试
            </text>
            <view v-else class="slotgrid">
              <view
                v-for="s in currentSlots"
                :key="s.key"
                class="slotbtn"
                :class="{ on: selectedSlot && selectedSlot.key === s.key }"
                hover-class="btn-on"
                :hover-stay-time="60"
                @tap="selectSlot(s)"
              >{{ s.range }}</view>
            </view>

            <text v-if="selectedSlot" class="slotnote on">
              已选 {{ selectedSlot.absolute }} —— 点下面的按钮带着它去预约，跳过去还能改。
            </text>
            <text v-else class="slotnote">
              先选日期，再点一个时间段；选好之后才能带着它去预约。
            </text>
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
          @tap="goVoice"
        >{{ needsSlot ? '请先选时间段' : '带着它去预约 →' }}</view>
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
 * ⚠️ imageUrl 是 /uploads/... 相对路径，展示前要拼 BASE_URL。
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
import { userStore } from '@/store/user.js'
import { parseDateTime } from '@/utils/format.js'

// 页面销毁时把 loading 计数归零：万一有哪条路径没配平，残留的计数会让之后
// 每一次 show/hide 都错位 —— 微信侧会一直报「showLoading 与 hideLoading 必须配对使用」
onUnload(() => resetLoading())

/** 空闲时段：往后看两周、每段至少 60 分钟 */
const SLOT_DAYS = 14
const SLOT_MIN_MINUTES = 60
/** 单日最多列几段，避免被切得太碎的场地撑爆页面 */
const SLOT_PER_DAY_MAX = 6

const WEEKDAY_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const photo = ref('')
const result = ref(null)
const analyzing = ref(false)
/** /booked 返回的场地权威信息（容量 / 位置 / 开放时段）—— 识别结果里没有这些 */
const spaceMeta = ref(null)
/** 日期 key（YYYY-MM-DD）→ 当天的空闲时段数组 */
const slotsByDay = ref({})
/** 当前选中的日期 key；空串表示还没选 */
const selectedDay = ref('')
/** 当前选中的时段；**必选项**，没选不让往下走 */
const selectedSlot = ref(null)
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
      hasSlot: (slotsByDay.value[key] || []).length > 0,
    })
  }
  return out
})

/** 选中日期下的可点时段 */
const currentSlots = computed(() => slotsByDay.value[selectedDay.value] || [])

/** 这个场地这两周里到底有没有可选的时段 */
const hasSelectableSlots = computed(() =>
  Object.keys(slotsByDay.value).some((k) => (slotsByDay.value[k] || []).length > 0)
)

/**
 * 时间段是**必选项**：只要还有可选时段，就必须先选一个才能去预约。
 * 一段都没有时（比如整两周都被占满）不做强制，否则用户会被卡死在这一页。
 */
const needsSlot = computed(() => hasSelectableSlots.value && !selectedSlot.value)

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
  slotsByDay.value = {}
  selectedDay.value = ''
  selectedSlot.value = null
  spaceMeta.value = null
  slotsNote.value = ''
  if (spaceId === undefined || spaceId === null || spaceId === '') return
  if (!userStore.loggedIn) {
    slotsNote.value = '登录后可查看这个场地的空闲时段'
    return
  }

  slotsLoading.value = true
  try {
    const res = await spaceBookings(spaceId, SLOT_DAYS)
    spaceMeta.value = res || null
    slotsByDay.value = computeSlotsByDay(res)
    // 默认落在**第一个有空档的日期**上：用户进来只需要再点一下时间段
    const firstKey = Object.keys(slotsByDay.value).find(
      (k) => (slotsByDay.value[k] || []).length > 0
    )
    if (firstKey) {
      selectedDay.value = firstKey
    } else {
      slotsNote.value = `未来 ${SLOT_DAYS} 天没有 ${SLOT_MIN_MINUTES} 分钟以上的连续空档`
    }
  } catch (e) {
    slotsNote.value = (e && e.message) || '空闲时段查询失败'
  } finally {
    slotsLoading.value = false
  }
}

/**
 * 开放时段 − 已占用 = 空闲，**按天分组**，每天列出全部够长的空档。
 *
 * ⚠️ 占用口径不在这里重判：后端 `/booked` 已经按「1 待确认 / 2 已确认」
 * 过滤过了（与下单判重同源），这里只做区间减法，避免两处口径漂移。
 *
 * 为什么从「每天只给第一段」改成「列出全天所有空档」：
 * 现在的交互是**先选日期、再选时间段**，一天只给一段等于替用户把时间定了，
 * 那不叫让他选。今天从「下一个整/半点」起算，已经过去的不展示。
 */
function computeSlotsByDay(res) {
  const out = {}
  const data = res || {}
  const bookings = Array.isArray(data.bookings) ? data.bookings : []
  const openS = clockToMinutes(data.openStartTime)
  const openE = clockToMinutes(data.openEndTime)
  if (openS === null || openE === null || openE <= openS) return out

  const busy = []
  bookings.forEach((b) => {
    const s = parseDateTime(b.startTime)
    const e = parseDateTime(b.endTime)
    if (s && e && e > s) busy.push({ s, e })
  })
  busy.sort((a, b) => a.s.getTime() - b.s.getTime())

  const now = new Date()
  for (let d = 0; d < SLOT_DAYS; d++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + d)
    const dayKey = ymd(day)
    const dayStart = atMinutes(day, openS)
    const dayClose = atMinutes(day, openE)

    let cursor = dayStart
    if (d === 0) {
      // 今天：向上取整到下一个整/半点，别给用户一个已经开始的时间
      const r = new Date(now.getTime())
      r.setSeconds(0, 0)
      const rest = r.getMinutes() % 30
      r.setMinutes(r.getMinutes() + (rest === 0 ? 30 : 30 - rest))
      if (r > cursor) cursor = r
    }

    const list = []
    if (cursor < dayClose) {
      for (const seg of busy) {
        if (seg.e <= dayStart || seg.s >= dayClose) continue
        const s = seg.s < cursor ? cursor : seg.s
        const e = seg.e > dayClose ? dayClose : seg.e
        if (e <= cursor) continue
        // 这段占用开始之前还剩得下 → 记一段空档
        if (gapMinutes(cursor, s) >= SLOT_MIN_MINUTES) {
          list.push(makeSlot(dayKey, cursor, s))
        }
        cursor = e
        if (cursor >= dayClose) break
        if (list.length >= SLOT_PER_DAY_MAX) break
      }
      // 收尾：最后一个占用段结束到闭馆之间
      if (
        list.length < SLOT_PER_DAY_MAX &&
        cursor < dayClose &&
        gapMinutes(cursor, dayClose) >= SLOT_MIN_MINUTES
      ) {
        list.push(makeSlot(dayKey, cursor, dayClose))
      }
    }
    out[dayKey] = list
  }
  return out
}

function clockToMinutes(t) {
  const m = String(t || '').match(/^(\d{1,2}):(\d{2})/)
  if (!m) return null
  return Number(m[1]) * 60 + Number(m[2])
}

function atMinutes(day, minutes) {
  const d = new Date(day.getFullYear(), day.getMonth(), day.getDate())
  d.setMinutes(minutes)
  return d
}

function gapMinutes(a, b) {
  return Math.round((b.getTime() - a.getTime()) / 60000)
}

function pad2(n) {
  return n < 10 ? '0' + n : String(n)
}

function hm(d) {
  return pad2(d.getHours()) + ':' + pad2(d.getMinutes())
}

function ymd(d) {
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
}

/** 今天 / 明天 / 后天，再往后直接给星期几 */
function dayLabel(offset, day) {
  if (offset === 0) return '今天'
  if (offset === 1) return '明天'
  if (offset === 2) return '后天'
  return WEEKDAY_CN[day.getDay()]
}

function makeSlot(dayKey, start, end) {
  return {
    key: dayKey + ' ' + hm(start),
    dayKey,
    range: hm(start) + '-' + hm(end),
    // 给 Agent 的是**绝对时间**：相对时间（"明天"）靠模型自己换算不稳定，
    // 而这里我们已经精确知道是哪一天了，没必要让它再猜一次
    absolute: dayKey + ' ' + hm(start) + '-' + hm(end),
  }
}

/** 选日期。换日期必须重选时间段 —— 「必选」是按具体时段算的，不是按天算的 */
function selectDay(d) {
  if (!d.hasSlot || selectedDay.value === d.key) return
  selectedDay.value = d.key
  selectedSlot.value = null
}

/** 选时间段；再点一次取消选择（取消后按钮会重新变灰，符合「必选」的直觉） */
function selectSlot(s) {
  selectedSlot.value = selectedSlot.value && selectedSlot.value.key === s.key ? null : s
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
function goVoice() {
  if (!result.value) return
  if (needsSlot.value) {
    toast('请先选一个日期和时间段')
    return
  }
  const name = displayName.value
  const cap = spaceMeta.value && spaceMeta.value.capacity
  const parts = [`我要预约${name}`]
  if (cap) parts.push(`${cap}人`)
  if (selectedSlot.value) parts.push(selectedSlot.value.absolute)
  agentStore.request = parts.join('，')
  pushImageContext()
  uni.navigateTo({ url: '/pages/voice/record' })
}
</script>

<style scoped>
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
  gap: 14rpx;
  margin-top: 18rpx;
}

.cand {
  display: flex;
  align-items: center;
  gap: 14rpx;
  background: #fff;
  border: 1px solid var(--ai-line);
  border-radius: 16rpx;
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
  gap: 14rpx;
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
  border-radius: 16rpx;
  background: #f5f7fa;
  border: 1px solid #e6eaf0;
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
  gap: 14rpx;
}

.slotbtn {
  min-width: 176rpx;
  text-align: center;
  font-size: 25rpx;
  padding: 16rpx 20rpx;
  border-radius: 16rpx;
  color: var(--t1);
  background: #f5f7fa;
  border: 1px solid #e6eaf0;
}

.slotbtn.on {
  color: #fff;
  background: var(--primary);
  border-color: var(--primary);
  font-weight: 600;
}

.slotnote {
  display: block;
  margin-top: 20rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
}

.slotnote.on {
  color: var(--primary);
  font-weight: 600;
}
</style>
