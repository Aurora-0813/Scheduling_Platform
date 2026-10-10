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
        <!--
          ⚠️ 恢复卡（2026-10-09 加）：只在「上次动作被会话过期打断」时出现。
          用 `hasPendingAction` 而不是 `orderId` 判断 —— 后者是历史快照，
          拿它驱动会让早已处理完的单子每次进来都弹一次。
          这里**不自动做任何事**：确认/查看/忽略都由用户点。
        -->
        <div v-if="hasPendingAction" class="sp-card pending-card">
          <div class="sp-card-head">
            <b>⚠️ 上次操作被打断</b>
          </div>
          <div class="sp-witem is-orange">
            <p>{{ pendingActionText }}</p>
            <p v-if="pendingAction && pendingAction.reason" class="pending-why">
              （{{ pendingAction.reason }}）
            </p>
          </div>
          <div class="pending-acts">
            <button
              v-if="orderId"
              class="sp-btn is-ai is-sm"
              :disabled="acting || orderStatus === 2"
              @click="onConfirm"
            >
              {{ orderStatus === 2 ? '✓ 已确认' : '确认这张预约' }}
            </button>
            <button class="sp-btn is-ghost is-sm" @click="onGoOrders">
              去预约单列表核对
            </button>
            <button class="sp-btn is-ghost is-sm" @click="onDismissPending">
              忽略
            </button>
          </div>
        </div>

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
                  <!--
                    这里原本还有一个紫色标签显示 `step.action`，即**内部工具名**
                    （英文函数名，如查场地/查设备那两个）。已删掉：
                    `step.result` 本身就是中文结论（「查询场地：命中 2 个候选场地」），
                    再挂一个英文函数名对使用者没有信息量，纯属噪音。
                    纯推理步的「推理」标签保留 —— 它是中文，用来区分「这步有没有动系统」。
                    注：注释里不写具体工具名，否则它们会随 HTML 注释一起到浏览器，
                    用「查看源代码」仍能搜到。
                  -->
                  <span v-if="!step.action" class="sp-tag is-gray">推理</span>
                  <span class="step-time">{{ (step.timestamp || '').slice(11) }}</span>
                </h5>

                <!--
                  只展示每步的**最终结果**（`step.result` + 时间）。
                  以下内容**按产品决定全部不渲染**：
                    · `step.thought`    —— 模型的逐步推理正文
                    · `step.actionInput` —— 工具入参
                    · `step.observation` —— 工具返回
                  一段几百字的内部思考加两坨 JSON 会把 7 步撑成好几屏。
                  这三项数据**仍在接口响应里**（`TraceStep` 契约未变），
                  将来若要「展开看明细」，用 `<details>` 包一层即可恢复，无需改后端。
                -->
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
import { onMounted, ref } from 'vue'

import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'

import { useAgentWorkbenchStore } from '@/store/agentWorkbench'

/**
 * 调度状态全部来自 store，**不是本组件的局部 ref**。
 *
 * 原因见 store 的模块文档：一次调度要 40~105 秒，若状态挂在组件上，
 * 用户切到别的页面就会把它连同「调用过程与结果」一起丢掉。
 * 放进 store 后，切页回来仍能看到完整的思考链与方案。
 */
const store = useAgentWorkbenchStore()
const router = useRouter()

const {
  running,
  acting,
  elapsed,
  trace,
  plan,
  backupPlan,
  orderId,
  needConfirm,
  orderStatus,
  fallbackMessage,
  toolCalls,
  totalToolCalls,
  orderStatusText,
  statusTagClass,
  planFields,
  planFilled,
  planScore,
  hasPendingAction,
  pendingActionText,
  pendingAction,
} = storeToRefs(store)

/** 输入框里的草稿。切页丢掉可接受，每次调度都要重新输入需求。 */
const text = ref('')

/* ------------------------------------------------------------------ *
 * 展示辅助
 * ------------------------------------------------------------------ */

/**
 * 有 Action 的步骤给紫渐变，纯推理给绿 —— 让「哪几步真的动了系统」一眼可见。
 *
 * 注意：`step.action`（内部工具名）**只用于这个判断**，不再渲染成标签。
 */
function stepNumberClass(step) {
  return step.action ? '' : 'is-g'
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
      const name = store.deviceMap.get(Number(id))
      return name ? `${name}（#${id}）` : `#${id}`
    })
    .join('、')
}

/* ------------------------------------------------------------------ *
 * 交互
 * ------------------------------------------------------------------ */

/**
 * 跑一次真实调度。
 *
 * 实际的请求与状态写入都在 store 里（见 `store/agentWorkbench.js` 的 `run`），
 * 这里只负责**提示分级** —— 弹哪个 toast 是视图层的选择，不是 store 的。
 */
async function onRun() {
  const value = (text.value || '').trim()
  if (!value) {
    ElMessage.warning('请先输入一条调度需求')
    return
  }

  const res = await store.run(value)
  if (!res.ok) return

  if (store.orderId) {
    ElMessage.success(`已生成方案并创建预约 #${store.orderId}（待确认）`)
  } else if (!store.plan) {
    ElMessage.warning('本次没有生成方案，原因见思考链上方')
  } else {
    ElMessage.info('方案已生成，但本次没有落库（没有单号可确认）')
  }
}

async function onConfirm() {
  if (await store.confirm()) {
    ElMessage.success(`预约 #${store.orderId} 已确认`)
  }
}

async function onCancel() {
  if (await store.cancel()) {
    ElMessage.success(`预约 #${store.orderId} 已取消`)
  }
}

function onReset() {
  store.onReset()
}

/**
 * 恢复卡：去预约单列表核对。
 *
 * 为什么要有这个出口：恢复卡只能告诉用户「可能成了」，**真正确认得看列表**。
 * 用户亲自看一眼比前端替他判断可靠，所以这里直接把人送到能核对的地方。
 * 一并清掉恢复卡 —— 已经去看过了，再弹就是噪音。
 */
function onGoOrders() {
  store.dismissPending()
  router.push('/orders')
}

/** 恢复卡：忽略。只清「中断事件」，保留上次的思考链与方案供继续查看 */
function onDismissPending() {
  store.dismissPending()
}

onMounted(() => {
  store.loadDeviceMap()
})

// ⚠️ 这里**不再**有 onUnmounted(stopTimer)：
// 计时器归 store 所有，组件卸载不能停它 —— 停了秒数就不走了，
// 而调度仍在后台继续，用户切回来会看到一个卡住的计时。
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

/* ---------------- 恢复卡（上次操作被会话过期打断） ---------------- */
.pending-card {
  /* 与思考链卡片拉开距离，让它在最上面独立成一块，不被当成思考链的一部分 */
  margin-bottom: 14px;
  border-left: 3px solid var(--sp-warn, #e6a23c);
}

.pending-card .sp-witem p {
  margin: 0;
  line-height: 1.7;
}

/* 「为什么会中断」——次要信息，字号收小、颜色压暗，不跟主文案抢注意力 */
.pending-why {
  margin-top: 5px !important;
  font-size: 12px;
  color: var(--sp-t3);
}

.pending-acts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
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
