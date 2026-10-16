<template>
  <div v-loading="recognizing">
    <div class="sp-pagebar">
      <h3>草图预约</h3>
      <div class="sp-acts">
        <span class="sp-tag is-blue">时间 15 分钟一档</span>
        <span class="sp-tag is-purple">建单前先查可用场地</span>
        <el-button size="small" @click="refreshAll">刷新可用性</el-button>
      </div>
    </div>

    <div class="sp-ai-bar">
      <div class="sp-ic">◈</div>
      <span>
        上传一张手绘布局草图，AI 识别人数与布局；<b>设备需要你手动勾选</b>
        （草图里画不出设备台账）；时间按 15 分钟选择。
        点「生成预约单」时后端会再做一次原子校验，冲突则整单回滚、不会写半张单。
      </span>
    </div>

    <!-- 冲突横幅：不再弹第二个 toast —— 请求层已经把后端的原因弹出来了，
         这里只负责告诉用户「接下来该干什么」。 -->
    <el-alert
      v-if="conflictMsg"
      class="mb"
      type="error"
      :closable="true"
      show-icon
      title="上一次提交因冲突未成功"
      :description="conflictMsg"
      @close="conflictMsg = ''"
    />

    <div class="grid2">
      <!-- ① 草图 -->
      <div class="sp-card">
        <div class="sp-card-head">
          <b>① 手绘草图</b>
          <span class="sp-grow"></span>
          <el-button v-if="sketch" link size="small" @click="resetSketch">重新上传</el-button>
        </div>
        <div class="pad">
          <el-upload
            v-if="!sketch"
            drag
            :auto-upload="false"
            :show-file-list="false"
            accept="image/*"
            :on-change="onSketchChange"
          >
            <div class="up">
              <div class="up-ic">＋</div>
              <div class="up-t">点击或拖拽上传手绘草图</div>
              <div class="up-s">JPG / PNG，≤5MB</div>
            </div>
          </el-upload>

          <div v-else>
            <el-image v-if="sketchPreview" :src="sketchPreview" fit="contain" class="sk-img" />
            <div class="kv"><span class="k">布局</span><span class="v">{{ sketch.layout || '未识别出布局' }}</span></div>
            <div class="kv">
              <span class="k">预估人数</span>
              <el-input-number v-model="capacity" :min="1" :max="10000" size="small" @change="refreshSpaces" />
            </div>
            <div class="kv">
              <span class="k">场地类型</span>
              <el-select v-model="spaceType" size="small" style="width: 140px" @change="refreshSpaces">
                <el-option v-for="t in SPACE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
              </el-select>
            </div>
            <div v-if="sketch.requirements && sketch.requirements.length" class="tags">
              <span v-for="(r, i) in sketch.requirements" :key="i" class="sp-tag is-blue">{{ r }}</span>
            </div>
            <el-alert
              v-if="sketch.needConfirm && sketch.question"
              class="mt"
              type="warning"
              :closable="false"
              show-icon
              :title="sketch.question"
            />
          </div>
        </div>
      </div>

      <!-- ② 时间 -->
      <div class="sp-card">
        <div class="sp-card-head"><b>② 使用时间</b><span class="sp-grow"></span><span class="sp-muted">15 分钟一档</span></div>
        <div class="pad">
          <div class="kv">
            <span class="k">日期</span>
            <el-date-picker
              v-model="date"
              type="date"
              value-format="YYYY-MM-DD"
              size="small"
              style="width: 160px"
              @change="refreshAll"
            />
          </div>
          <div class="kv">
            <span class="k">开始</span>
            <el-time-select
              v-model="startTime"
              start="07:00"
              step="00:15"
              end="23:45"
              size="small"
              style="width: 160px"
              placeholder="开始时间"
              @change="onStartChange"
            />
          </div>
          <div class="kv">
            <span class="k">结束</span>
            <el-time-select
              v-model="endTime"
              start="07:00"
              step="00:15"
              end="23:45"
              size="small"
              style="width: 160px"
              placeholder="结束时间"
              @change="refreshAll"
            />
          </div>
          <div class="tip">找不到想要的时间？时间档是 15 分钟粒度，与后端整点/半点口径一致。</div>
        </div>
      </div>
    </div>

    <div class="grid2">
      <!-- ③ 可用场地 -->
      <div class="sp-card">
        <div class="sp-card-head">
          <b>③ 该时段可用场地</b>
          <span class="sp-grow"></span>
          <span class="sp-tag" :class="spaceOptions.length ? 'is-green' : 'is-red'">{{ spaceOptions.length }} 个</span>
        </div>
        <div class="pad">
          <div v-if="spacesLoading" class="sp-muted">查询中…</div>
          <el-empty
            v-else-if="!spaceOptions.length"
            :description="'该时段没有合适的场地' + (capacity ? '（已按 ' + capacity + ' 人筛选）' : '') + '，请调整时间或人数'"
            :image-size="56"
          />
          <div v-else class="opts">
            <div
              v-for="s in spaceOptions"
              :key="s.spaceId"
              class="opt"
              :class="{ 'is-on': selectedSpaceId === s.spaceId }"
              @click="selectedSpaceId = s.spaceId"
            >
              <b>{{ s.spaceName }}</b>
              <span class="sp-muted">
                {{ SPACE_TYPE_TEXT[s.spaceType] || '场地' }} · {{ s.capacity }} 人 · {{ s.location || '—' }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- ④ 设备 -->
      <div class="sp-card">
        <div class="sp-card-head">
          <b>④ 设备（可多选）</b>
          <span class="sp-grow"></span>
          <span class="sp-muted">数字 = 该时段还能借几台</span>
        </div>
        <div class="pad">
          <div v-if="devicesLoading" class="sp-muted">查询中…</div>
          <el-empty v-else-if="!deviceOptions.length" description="暂无可用设备" :image-size="56" />
          <el-checkbox-group v-else v-model="selectedDeviceIds" class="devs">
            <el-checkbox
              v-for="d in deviceOptions"
              :key="d.deviceId"
              :value="String(d.deviceId)"
              :disabled="d.remainingCount <= 0"
              class="dev"
            >
              <span class="dev-n">{{ d.deviceName }}</span>
              <span class="dev-r" :class="{ 'is-zero': d.remainingCount <= 0 }">
                {{ d.remainingCount > 0 ? '剩 ' + d.remainingCount : '该时段已借满' }}
              </span>
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </div>
    </div>

    <div class="actions">
      <span class="sp-muted picked">
        已选：{{ selectedSpaceName || '未选场地' }} · {{ selectedDeviceIds.length }} 台设备
      </span>
      <el-button type="primary" size="large" :loading="submitting" @click="submit">生成预约单</el-button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { analyzeSketch } from '@/api/image'
import { createOrder } from '@/api/orders'
import { getAvailableDevices, getAvailableSpaces } from '@/api/resources'

/**
 * 草图预约（2026-10-13 新增）
 *
 * 流程：上传草图 → AI 识别人数/布局/场地类型 → 用户手动补设备 + 15 分钟档选时间
 *       → 查该时段可用场地（= 冲突预检）→ 建单（后端再原子校验一次）
 *
 * 为什么设备必须手选：手绘草图通常只画布局和座位，**画不出设备台账**。
 * 所以识别结果里刻意不带 deviceHints，改为按草图上的文字标注（「投影」「音响」）
 * 做**预勾选**，用户随时可以取消或补选。
 */

/** 场地类型：0 = 不限（草图判不出类型时不强加过滤） */
const SPACE_TYPES = [
  { value: 0, label: '不限类型' },
  { value: 1, label: '会议室' },
  { value: 2, label: '展厅' },
  { value: 3, label: '多功能厅' },
  { value: 4, label: '户外场地' },
]
const SPACE_TYPE_TEXT = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

/** 草图的需求关键词 → 台账里的设备类型。只用于预勾选，猜错了取消即可。 */
const REQ_TO_DEVICE = [
  { keys: ['投影'], type: '投影仪' },
  { keys: ['音响', '扩音', '话筒'], type: '音响' },
  { keys: ['显示屏', '大屏', '屏幕', 'LED'], type: 'LED显示屏' },
  { keys: ['直播'], type: '直播设备' },
  { keys: ['无人机', '航拍'], type: '无人机' },
]

const recognizing = ref(false)
const submitting = ref(false)

const sketch = ref(null)
const sketchPreview = ref('')
const capacity = ref(null)
const spaceType = ref(0)

const date = ref('')
const startTime = ref('')
const endTime = ref('')

const spaceOptions = ref([])
const deviceOptions = ref([])
const selectedSpaceId = ref(null)
const selectedDeviceIds = ref([])
const spacesLoading = ref(false)
const devicesLoading = ref(false)
const conflictMsg = ref('')

const selectedSpaceName = computed(() => {
  const s = spaceOptions.value.find((x) => x.spaceId === selectedSpaceId.value)
  return s ? s.spaceName : ''
})

function pad(n) {
  return n < 10 ? '0' + n : '' + n
}
function todayStr(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
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
/** 当前选择拼成后端要的 YYYY-MM-DD HH:mm:ss */
function range() {
  return {
    startTime: date.value + ' ' + startTime.value + ':00',
    endTime: date.value + ' ' + endTime.value + ':00',
  }
}

// ---------- ① 草图 ----------
function resetSketch() {
  sketch.value = null
  sketchPreview.value = ''
  capacity.value = null
  spaceType.value = 0
  conflictMsg.value = ''
  refreshAll()
}

function onSketchChange(uploadFileItem) {
  const raw = uploadFileItem && uploadFileItem.raw
  if (!raw) return
  // 本地预览：后端 imageUrl 在落盘失败时是 null，用本地 blob 永远有图可看
  sketchPreview.value = URL.createObjectURL(raw)
  recognize(raw)
}

async function recognize(raw) {
  recognizing.value = true
  conflictMsg.value = ''
  try {
    const data = (await analyzeSketch(raw)) || {}
    sketch.value = data
    capacity.value = data.capacity || null
    spaceType.value = data.spaceType || 0
    await refreshDevices()
    preselectDevices(data.requirements || [])
    await refreshSpaces()
  } catch (e) {
    sketch.value = null
    // 请求层已经弹过后端给的原因了，这里不重复弹
  } finally {
    recognizing.value = false
  }
}

/** 按草图上的文字标注预勾选设备（只是预选，用户可改） */
function preselectDevices(requirements) {
  const wanted = {}
  requirements.forEach((r) => {
    REQ_TO_DEVICE.forEach((m) => {
      if (m.keys.some((k) => String(r).indexOf(k) >= 0)) wanted[m.type] = true
    })
  })
  selectedDeviceIds.value = deviceOptions.value
    .filter((d) => wanted[d.deviceType])
    .map((d) => String(d.deviceId))
}

// ---------- ③ 可用场地（= 冲突预检） ----------
async function refreshSpaces() {
  if (!date.value || !startTime.value || !endTime.value) return
  spacesLoading.value = true
  try {
    const params = Object.assign({}, range())
    if (capacity.value) params.capacity = capacity.value
    if (spaceType.value) params.spaceType = spaceType.value
    const data = await getAvailableSpaces(params)
    spaceOptions.value = (data && data.spaces) || []
    // 之前选的场地若这个时段已经订不上了，清掉选择 —— 留着会让用户以为还选着
    if (selectedSpaceId.value && !spaceOptions.value.some((s) => s.spaceId === selectedSpaceId.value)) {
      selectedSpaceId.value = null
    }
  } catch (e) {
    spaceOptions.value = []
  } finally {
    spacesLoading.value = false
  }
}

// ---------- ④ 设备时段可用数 ----------
async function refreshDevices() {
  if (!date.value || !startTime.value || !endTime.value) return
  devicesLoading.value = true
  try {
    const data = await getAvailableDevices(range())
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

function onStartChange() {
  // 开始时间被拖到结束之后时，自动把结束顺延一小时（4 档 × 15 分钟）
  if (endTime.value && startTime.value && endTime.value <= startTime.value) {
    const parts = startTime.value.split(':')
    let h = Number(parts[0]) + 1
    if (h > 23) h = 23
    endTime.value = (h < 10 ? '0' + h : '' + h) + ':' + parts[1]
  }
  refreshAll()
}

/** 把「草图 + 选择」写成一句人话存进订单，事后回看能知道这单是怎么来的 */
function buildAgentRequest() {
  const parts = []
  if (sketch.value) {
    parts.push('手绘草图预约')
    if (sketch.value.layout) parts.push(sketch.value.layout)
    if (capacity.value) parts.push(capacity.value + ' 人')
    if (sketch.value.requirements && sketch.value.requirements.length) {
      parts.push(sketch.value.requirements.join('/'))
    }
  } else {
    parts.push('手动预约')
  }
  const names = selectedDeviceIds.value
    .map((id) => {
      const d = deviceOptions.value.find((x) => String(x.deviceId) === id)
      return d ? d.deviceName : '#' + id
    })
    .join('、')
  if (names) parts.push('设备：' + names)
  return parts.join('；').slice(0, 1000)
}

async function submit() {
  if (!selectedSpaceId.value) {
    ElMessage.warning('请先选择场地')
    return
  }
  if (endTime.value <= startTime.value) {
    ElMessage.warning('开始时间须早于结束时间')
    return
  }
  submitting.value = true
  conflictMsg.value = ''
  try {
    const payload = Object.assign(
      {
        spaceId: selectedSpaceId.value,
        deviceIds: selectedDeviceIds.value.map(Number),
        agentRequest: buildAgentRequest(),
      },
      range(),
    )
    const created = await createOrder(payload)
    ElMessage.success(
      '预约创建成功' + (created && created.orderId ? '（单号 #' + created.orderId + '）' : ''),
    )
    // 成功后刷新可用性：刚被占掉的场地/设备会从列表里消失，用户能直观看到「这一单生效了」
    refreshAll()
  } catch (e) {
    // 建单是**原子**的：后端发现冲突会整单回滚、什么都不写（不会留半张单）。
    // 所以这里只需刷新可用性 + 给一句「接下来怎么办」——
    // 具体原因（「该时段已被占用」）请求层已经弹过了，不再重复弹。
    conflictMsg.value =
      ((e && e.message) || '所选时段或设备已被占用') + ' 已为你刷新该时段的可用场地与设备，请重新选择后再提交。'
    refreshAll()
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  const now = new Date()
  const start = ceilToQuarter(now)
  const end = new Date(start.getTime() + 60 * 60 * 1000)
  date.value = todayStr(now)
  startTime.value = hhmm(start)
  endTime.value = hhmm(end)
  refreshAll()
})
</script>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.mt {
  margin-top: 12px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-s4);
  margin-bottom: 16px;
}
.pad {
  padding: 12px 16px 16px;
}
.up {
  padding: 18px 0;
}
.up-ic {
  font-size: 34px;
  color: var(--sp-t3);
  line-height: 1.1;
}
.up-t {
  font-size: 14px;
  color: var(--sp-t2);
  margin-top: 6px;
}
.up-s {
  font-size: 12px;
  color: var(--sp-t3);
  margin-top: 4px;
}
.sk-img {
  width: 100%;
  max-height: 190px;
  border-radius: var(--sp-r-md);
  margin-bottom: 10px;
  background: #f7fafd;
}
.kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-s3);
  padding: 8px 0;
  border-top: 1px solid #f0f3f7;
}
.k {
  color: var(--sp-t3);
  font-size: 13px;
  flex-shrink: 0;
}
.v {
  color: var(--sp-text);
  font-size: 13px;
  text-align: right;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-s1);
  margin-top: 10px;
}
.tip {
  margin-top: 8px;
  font-size: 12px;
  color: var(--sp-t3);
  line-height: 1.6;
}
.opts {
  display: flex;
  flex-direction: column;
  gap: var(--sp-s2);
  max-height: 260px;
  overflow-y: auto;
}
.opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-s2);
  border: 1px solid #e6ecf5;
  border-radius: var(--sp-r-md);
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.opt:hover {
  border-color: #a9c8e8;
}
.opt.is-on {
  border-color: #2e75b6;
  background: #f2f8ff;
}
.opt b {
  font-size: 14px;
  color: var(--sp-text);
}
.devs {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 260px;
  overflow-y: auto;
}
.dev {
  display: flex;
  align-items: center;
  width: 100%;
  height: 34px;
}
.dev-n {
  font-size: 13px;
  color: var(--sp-text);
}
.dev-r {
  margin-left: 8px;
  font-size: 12px;
  color: #4fd88f;
}
.dev-r.is-zero {
  color: #ff8a8a;
}
.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-s4);
  padding: 8px 0 24px;
}
.picked {
  font-size: 13px;
}
</style>
