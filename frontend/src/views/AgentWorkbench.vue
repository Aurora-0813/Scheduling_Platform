<template>
  <div>
    <div class="sp-pagebar">
      <h3>Agent 调度工作台</h3>
      <div class="sp-acts">
        <span class="sp-tag is-purple">🧠 Thought → Action → Observation</span>
        <button class="sp-btn is-ghost is-sm" :disabled="running" @click="onReset">清空</button>
      </div>
    </div>

    <!-- 副作用必须说在前面：这不是演示动画，跑一次就真的落一条单 -->
    <div class="sp-ai-bar">
      <div class="sp-ic">🧠</div>
      <span>
        <b>这不是演示动画。</b>
        点一次「运行调度」会真的跑一轮大模型、真的在事务里
        <code>SELECT ... FOR UPDATE</code> 锁资源，并真的落一条 <b>待确认</b> 预约。
        生成后请<strong>确认或取消</strong>，别让它一直挂着占位。
      </span>
    </div>

    <div class="agentgrid">
      <!-- ==================== 左：需求 + 工具调用 ==================== -->
      <div class="agcol is-side">
        <div class="sp-ask">
          <div class="sp-who">
            <span class="sp-live is-blue"></span>
            用户需求 · 自然语言
          </div>
          <textarea
            v-model="text"
            class="ask-input"
            rows="4"
            maxlength="1024"
            placeholder="请输入需求：时间、地点、人数、设备、预算等"
            @keydown.ctrl.enter="onRun"
          ></textarea>
          <button class="sp-btn is-ai is-block run-btn" :disabled="running" @click="onRun">
            {{ running ? `Agent 思考中… ${elapsed}s` : '运行调度 →' }}
          </button>
          <div class="ask-tip">Ctrl + Enter 提交 ｜ 需求越具体，Tool 调用越准</div>
        </div>

        <!-- Tool 调用：**完全由真实思考链推导**，没有真实的 action 就不显示 -->
        <div class="sp-card">
          <div class="sp-card-head">
            <b>⚡ Tool 调用</b>
            <span class="sp-grow"></span>
            <span class="sp-tag" :class="toolCalls.length ? 'is-blue' : 'is-gray'">
              {{ toolCalls.length ? `${totalToolCalls} 次` : '未调用' }}
            </span>
          </div>
          <div v-if="!toolCalls.length" class="sp-muted">还没有调用记录，先运行一次调度。</div>
          <div v-for="tool in toolCalls" :key="tool.name" class="tool-row">
            <code>{{ tool.name }}</code>
            <b>{{ tool.count }}</b>
          </div>
        </div>

        <!-- 落库状态：orderId 是后端真的建出来的那一条 -->
        <div class="sp-card">
          <div class="sp-card-head"><b>📌 落库状态</b></div>
          <div class="sp-mbrow">
            <span class="sp-k">预约单号</span>
            <span class="sp-v">
              <b v-if="orderId">#{{ orderId }}</b>
              <span v-else class="sp-muted">未落库</span>
            </span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">当前状态</span>
            <span class="sp-v">
              <span v-if="orderStatusText" class="sp-tag" :class="statusTagClass">
                {{ orderStatusText }}
              </span>
              <span v-else class="sp-muted">—</span>
            </span>
          </div>
          <div class="sp-mbrow">
            <span class="sp-k">需要确认</span>
            <span class="sp-v">{{ needConfirm ? '是' : '否' }}</span>
          </div>
          <router-link v-if="orderId" to="/orders" class="to-orders">去预约单管理 →</router-link>
        </div>
      </div>

      <!-- ==================== 中：真实思考链 ==================== -->
      <div class="agcol is-main">
        <div class="sp-card trace-card">
          <div class="sp-card-head">
            <b>🧠 Agent 思考链</b>
            <span class="sp-grow"></span>
            <span class="sp-tag is-purple">{{ trace.length }} 步</span>
          </div>

          <!-- 降级路径：plan 为 null，唯一可读原因在 message 里 -->
          <div v-if="fallbackMessage" class="sp-witem is-red">
            <b>本次没拿到方案</b>
            <p>{{ fallbackMessage }}</p>
          </div>

          <div v-if="running" class="trace-waiting">
            <span class="sp-live is-blue"></span>
            正在等模型逐步返回…（实测一轮 40–105 秒，步骤边收边显示）
          </div>

          <div v-if="!trace.length && !running" class="sp-muted trace-empty">
            输入需求后点「运行调度」。这里会按真实时间戳回放模型的每一步推理。
          </div>

          <div v-else class="sp-trace">
            <div
              v-for="(step, index) in trace"
              :key="step.step"
              class="sp-tstep"
              :style="{ animationDelay: `${index * 0.06}s` }"
            >
              <div class="sp-tnum" :class="stepNumberClass(step)">{{ step.step }}</div>
              <div class="sp-tb">
                <h5>
                  {{ step.result }}
                  <span v-if="step.action" class="sp-tag is-purple">{{ step.action }}</span>
                  <span v-else class="sp-tag is-gray">推理</span>
                  <span class="step-time">{{ (step.timestamp || '').slice(11) }}</span>
                </h5>
                <p v-if="step.thought">{{ step.thought }}</p>
                <div v-if="step.actionInput" class="sp-code">
                  Input: {{ compact(step.actionInput) }}
                </div>
                <div v-if="step.observation" class="sp-code">
                  Observation: {{ compact(step.observation) }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ==================== 右：方案 ==================== -->
      <div class="agcol is-side">
        <template v-if="plan">
          <div class="sp-planbox">
            <h4>🤖 主方案 · {{ plan.spaceName || `场地 #${plan.spaceId}` }}</h4>
            <div class="sp-line">
              {{ formatRange(plan) }}<br />
              设备：{{ deviceNames(plan) }}<br />
              {{ plan.reason || '模型未给出说明' }}
            </div>
          </div>

          <!--
            原型这里是一个「方案置信度 88%」的环。**后端不返回置信度**
            （见 backend/app/schemas/agent.py::Plan，只有 5 个要素字段），
            所以这里换成**方案要素完整度** —— 由真实字段是否存在算出来，
            可比对、可解释，不是编出来的百分比。
          -->
          <div class="sp-card">
            <div class="sp-card-head"><b>📊 方案要素完整度</b></div>
            <div class="sp-ringwrap">
              <svg viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="15.9" fill="none" stroke="#eef2f8" stroke-width="3" />
                <circle
                  cx="18"
                  cy="18"
                  r="15.9"
                  fill="none"
                  stroke="url(#spGAI)"
                  stroke-width="3"
                  stroke-linecap="round"
                  :stroke-dasharray="`${planScore} 100`"
                  transform="rotate(-90 18 18)"
                />
              </svg>
              <div class="sp-rc">
                <b>{{ planScore }}%</b>
                {{ planFilled }} / {{ planFields.length }} 项要素齐全
              </div>
            </div>
            <svg width="0" height="0" style="position: absolute">
              <defs>
                <linearGradient id="spGAI" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stop-color="#409EFF" />
                  <stop offset="100%" stop-color="#7c5cff" />
                </linearGradient>
              </defs>
            </svg>
            <div class="field-list">
              <span
                v-for="f in planFields"
                :key="f.label"
                class="sp-tag"
                :class="f.ok ? 'is-green' : 'is-gray'"
              >
                {{ f.ok ? '✓' : '✗' }} {{ f.label }}
              </span>
            </div>
          </div>

          <div v-if="backupPlan" class="sp-plan-alt">
            <div class="sp-card-head" style="margin-bottom: 8px"><b>🔄 备选方案</b></div>
            <div class="sp-mbrow">
              <span class="sp-k">场地</span>
              <span class="sp-v">{{ backupPlan.spaceName || `#${backupPlan.spaceId}` }}</span>
            </div>
            <div class="sp-mbrow">
              <span class="sp-k">时段</span>
              <span class="sp-v">{{ formatRange(backupPlan) }}</span>
            </div>
            <div class="sp-mbrow">
              <span class="sp-k">差异</span>
              <span class="sp-v">{{ backupPlan.reason || '—' }}</span>
            </div>
          </div>
        </template>

        <div v-else-if="!running" class="sp-card plan-empty">
          <div class="sp-muted">主方案会显示在这里。</div>
        </div>

        <!--
          ⚠️ 这里**没有**原型里的「确认并创建预约」按钮，因为那个语义是反的：
          POST /agent/schedule **已经**把单建出来了（响应里的 orderId 就是它，
          status=1 待确认）。再「创建」一次只会得到第二条重复预约。
          正确动作是 PUT /orders/{orderId}/confirm 把它从 1 推到 2 ——
          这正是 ScheduleData.orderId 的注释里写明的用途。
        -->
        <template v-if="orderId">
          <div class="sp-ai-bar cta-hint">
            <div class="sp-ic">✅</div>
            <span>
              预约 <b>#{{ orderId }}</b> 已由本次调度创建，当前
              <b>{{ orderStatusText }}</b>。确认后才会进入「已确认」，占用才算真正落实。
            </span>
          </div>
          <button
            class="sp-btn is-ai is-block"
            :disabled="acting || orderStatus === 2"
            @click="onConfirm"
          >
            {{ orderStatus === 2 ? '✓ 已确认' : '确认预约' }}
          </button>
          <button
            class="sp-btn is-ghost is-block cta-second"
            :disabled="acting || orderStatus === 3"
            @click="onCancel"
          >
            取消该预约
          </button>
        </template>

        <div v-else-if="plan && !running" class="sp-card">
          <div class="sp-muted">
            本次 Agent <b>没有落库</b>（未调用 lock_resources，或调用时冲突被驳回），
            所以没有单号可确认。可以调整需求后重跑。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { ElMessage } from 'element-plus'

import { agentSchedule } from '@/api/monitor'
import { cancelOrder, confirmOrder, getOrder } from '@/api/orders'
import { getDevices } from '@/api/resources'
import { devicesOf, orderStatusLabel } from '@/utils/normalize'

const text = ref(
  '',
)

const running = ref(false)
const acting = ref(false)
const elapsed = ref(0)

const trace = ref([])
const plan = ref(null)
const backupPlan = ref(null)
const orderId = ref(null)
const needConfirm = ref(true)
const orderStatus = ref(null)

/** 降级路径的可读原因。它来自 agentSchedule 返回的 message，不在 data 里。 */
const fallbackMessage = ref('')

/** deviceId -> deviceName。Agent 只返回设备 ID，名字得自己查真库补上。 */
const deviceMap = ref(new Map())

let timer = null

/* ------------------------------------------------------------------ *
 * 派生数据
 * ------------------------------------------------------------------ */

const toolCalls = computed(() => {
  const byName = new Map()
  for (const step of trace.value) {
    if (!step.action) continue
    const entry = byName.get(step.action) || { name: step.action, count: 0 }
    entry.count += 1
    byName.set(step.action, entry)
  }
  return [...byName.values()]
})

const totalToolCalls = computed(() => toolCalls.value.reduce((sum, t) => sum + t.count, 0))

const orderStatusText = computed(() => {
  if (orderStatus.value === null || orderStatus.value === undefined) return ''
  return orderStatusLabel(orderStatus.value)
})

const statusTagClass = computed(() => {
  switch (orderStatus.value) {
    case 2:
      return 'is-green'
    case 3:
      return 'is-gray'
    case 4:
      return 'is-blue'
    default:
      return 'is-orange'
  }
})

/**
 * 方案要素完整度 —— 由 Plan 契约里那 5 个字段的真实有无算出来。
 *
 * 原型画的是一「AI 方案置信度 88%」，但**后端根本不返回置信度**
 * （app/schemas/agent.py::Plan 只有 spaceId/spaceName/deviceIds/startTime/endTime/reason）。
 * 与其编一个 88%，不如算一个用户能自己核对的东西。
 */
const planFields = computed(() => {
  const p = plan.value
  if (!p) return []
  return [
    { label: '场地', ok: p.spaceId !== null && p.spaceId !== undefined },
    { label: '开始时间', ok: Boolean(p.startTime) },
    { label: '结束时间', ok: Boolean(p.endTime) },
    { label: '设备', ok: Array.isArray(p.deviceIds) && p.deviceIds.length > 0 },
    { label: '理由', ok: Boolean(p.reason) },
  ]
})

const planFilled = computed(() => planFields.value.filter((f) => f.ok).length)

const planScore = computed(() =>
  planFields.value.length ? Math.round((planFilled.value / planFields.value.length) * 100) : 0,
)

/* ------------------------------------------------------------------ *
 * 展示辅助
 * ------------------------------------------------------------------ */

function compact(value) {
  if (value === null || value === undefined) return '—'
  const json = typeof value === 'string' ? value : JSON.stringify(value)
  return json.length > 160 ? `${json.slice(0, 160)}…` : json
}

function formatRange(p) {
  if (!p) return '—'
  const start = p.startTime || '未知'
  const end = p.endTime || '未知'
  return `${start} ~ ${end}`
}

function deviceNames(p) {
  const ids = Array.isArray(p && p.deviceIds) ? p.deviceIds : []
  if (!ids.length) return '未指定'
  return ids
    .map((id) => {
      const name = deviceMap.value.get(Number(id))
      return name ? `${name}（#${id}）` : `#${id}`
    })
    .join('、')
}

/** 有 Action 的步骤给紫渐变，纯推理给绿 —— 让「哪几步真的动了系统」一眼可见。 */
function stepNumberClass(step) {
  return step.action ? '' : 'is-g'
}

/* ------------------------------------------------------------------ *
 * 交互
 * ------------------------------------------------------------------ */

function startTimer() {
  elapsed.value = 0
  timer = setInterval(() => {
    elapsed.value += 1
  }, 1000)
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function onReset() {
  trace.value = []
  plan.value = null
  backupPlan.value = null
  orderId.value = null
  orderStatus.value = null
  fallbackMessage.value = ''
}

/**
 * 跑一次真实调度。
 *
 * agentSchedule 返回的是 `{ data, message }`（passMessage: true）：降级路径
 * （模型没交方案 / 输出格式错乱）是 **HTTP 200 + code=200**，但 data.plan 是 null，
 * 「为什么没有方案」这句话**只在 message 里**。只要 data 的话会渲染出一个空白方案区，
 * 用户完全不知道发生了什么。
 */
async function onRun() {
  const value = (text.value || '').trim()
  if (!value) {
    ElMessage.warning('请先输入一条调度需求')
    return
  }

  running.value = true
  startTimer()
  try {
    const res = await agentSchedule({ text: value })
    const data = (res && res.data) || {}
    const message = (res && res.message) || ''

    trace.value = Array.isArray(data.trace) ? data.trace : []
    plan.value = data.plan || null
    backupPlan.value = data.backupPlan || null
    orderId.value = data.orderId || null
    needConfirm.value = data.needConfirm !== false
    // 「操作成功」是正常路径的固定文案，拿它当降级原因显示会很怪
    fallbackMessage.value = !data.plan && message && message !== '操作成功' ? message : ''

    if (orderId.value) {
      ElMessage.success(`已生成方案并创建预约 #${orderId.value}（待确认）`)
      // 单号已经有了，顺手把真实状态读回来，别靠猜
      await refreshOrderStatus()
    } else if (!data.plan) {
      ElMessage.warning('本次没有生成方案，原因见思考链上方')
    } else {
      ElMessage.info('方案已生成，但本次没有落库（没有单号可确认）')
    }
  } catch {
    // request.js 已经弹过后端的真实 message，这里不重复打扰
  } finally {
    running.value = false
    stopTimer()
  }
}

async function refreshOrderStatus() {
  if (!orderId.value) return
  try {
    const order = await getOrder(orderId.value)
    orderStatus.value = order && order.orderStatus
  } catch {
    // 拿不到状态不影响主流程，按钮仍可用
  }
}

async function onConfirm() {
  if (!orderId.value) return
  acting.value = true
  try {
    await confirmOrder(orderId.value)
    ElMessage.success(`预约 #${orderId.value} 已确认`)
    await refreshOrderStatus()
  } catch {
    // 409（当前状态不允许确认）等由 request.js 弹出真实原因
    await refreshOrderStatus()
  } finally {
    acting.value = false
  }
}

async function onCancel() {
  if (!orderId.value) return
  acting.value = true
  try {
    await cancelOrder(orderId.value)
    ElMessage.success(`预约 #${orderId.value} 已取消`)
    await refreshOrderStatus()
  } catch {
    await refreshOrderStatus()
  } finally {
    acting.value = false
  }
}

onMounted(async () => {
  try {
    deviceMap.value = new Map(
      devicesOf(await getDevices()).map((d) => [Number(d.deviceId), d.deviceName]),
    )
  } catch {
    // 补不到设备名就退化成显示 ID，不影响调度
    deviceMap.value = new Map()
  }
})

onUnmounted(stopTimer)
</script>

<style scoped>
.agentgrid {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.agcol {
  display: flex;
  flex-direction: column;
  gap: 13px;
  min-width: 0;
}

.agcol.is-side {
  width: 326px;
  flex: none;
}

.agcol.is-main {
  flex: 1;
}

/* ---------------- 需求输入 ---------------- */
.ask-input {
  width: 100%;
  border: 1px solid var(--sp-ai-line);
  border-radius: 7px;
  padding: 10px 12px;
  font-size: 13px;
  font-family: inherit;
  line-height: 1.85;
  color: var(--sp-text);
  background: #fff;
  resize: vertical;
  outline: none;
}

.ask-input:focus {
  border-color: var(--sp-accent);
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.12);
}

.run-btn {
  margin-top: 11px;
}

.ask-tip {
  font-size: 11.5px;
  color: var(--sp-t3);
  margin-top: 9px;
  text-align: center;
}

/* ---------------- Tool 调用 ---------------- */
.tool-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  padding: 7px 0;
  border-bottom: 1px solid #f5f7fa;
}

.tool-row:last-child {
  border-bottom: none;
}

.tool-row code {
  font-family: ui-monospace, Consolas, monospace;
  color: #4a6a92;
  background: #f7f9fc;
  border-radius: 4px;
  padding: 1px 6px;
}

.tool-row b {
  color: var(--sp-accent);
}

/* ---------------- 落库状态 ---------------- */
.to-orders {
  display: inline-block;
  margin-top: 11px;
  font-size: 12px;
  color: var(--sp-accent);
  text-decoration: none;
}

/* ---------------- 思考链 ---------------- */
.trace-card {
  min-height: 520px;
}

.trace-empty {
  padding: 40px 0;
  text-align: center;
}

.trace-waiting {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--sp-accent);
  background: var(--sp-ai-soft);
  border: 1px solid var(--sp-ai-line);
  border-radius: 7px;
  padding: 9px 12px;
  margin-bottom: 13px;
}

.step-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--sp-t3);
  font-family: ui-monospace, Consolas, monospace;
  font-weight: 400;
}

/* ---------------- 方案要素 ---------------- */
.field-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 13px;
}

.plan-empty {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cta-hint {
  margin-bottom: 10px;
  align-items: flex-start;
}

.cta-second {
  margin-top: 8px;
}
</style>
