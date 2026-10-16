<template>
  <div>
    <div class="sp-pagebar">
      <h3>Agent 调度工作台</h3>
      <div class="sp-acts">
        <span class="sp-tag is-purple">Thought → Action → Observation</span>
        <button class="sp-btn is-ghost is-sm" :disabled="running || parsing" @click="onReset">
          清空
        </button>
      </div>
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

          <!--
            两个按钮的分工是这一屏最需要说清楚的事（2026-10-13 加）：
              · 解析条件 —— POST /agent/parse，一次模型调用，**不建单**，可以反复点
              · 运行调度 —— POST /agent/schedule，多轮 Agent，**会真落一条待确认预约**
            所以有副作用的那个不用渐变色，且文案里保留「会建单」的暗示。
          -->
          <div class="runrow">
            <button
              class="sp-btn is-ghost is-block parse-btn"
              :disabled="parsing || running"
              @click="onParse"
            >
              {{ parseButtonLabel }}
            </button>
            <button
              class="sp-btn is-ai is-block run-btn"
              :disabled="running || parsing"
              @click="onRun"
            >
              {{ running ? `Agent 思考中… ${elapsed}s` : '运行调度 →' }}
            </button>
          </div>
          <!--
            提示文案由两行收成一行（2026-10-14）。
            原来第二行「『AI 解析条件』只读不建单…」与本卡片上方那条
            「这不是演示动画…」讲的是同一件事（两个按钮的分工），属于重复；
            去掉后省一行高度，信息并没有少。
          -->
          <div class="ask-tip">
            Ctrl + Enter 提交 ｜ 需求越具体，Tool 调用越准
          </div>
        </div>

        <!--
          AI 解析出的条件（POST /agent/parse）。
          刻意**不折叠**：用户点完按钮眼睛就在这一带，「AI 读错了没有」必须当场可见。
        -->
        <div v-if="parsing" class="sp-ai-bar parse-wait">
          <div class="sp-ic">◈</div>
          <span>正在用一次模型调用读出时间 / 人数 / 设备 / 预算…</span>
        </div>

        <div v-else-if="parseResult" class="sp-card parse-card">
          <div class="sp-card-head">
            <b>解析出的条件</b>
            <span class="sp-grow"></span>
            <span v-if="parsedConfidence !== null" class="sp-tag is-purple">
              置信度 {{ parsedConfidence }}%
            </span>
            <span v-if="!parseFresh" class="sp-tag is-orange">需求已改，结果待刷新</span>
          </div>

          <div v-if="parsedRows.length" class="parse-rows">
            <div v-for="r in parsedRows" :key="r.label" class="parse-row">
              <span class="parse-k">{{ r.label }}</span>
              <span class="parse-v">{{ r.value }}</span>
            </div>
          </div>
          <div v-else class="sp-muted">
            这句话里没有明确的硬条件（人数 / 时间 / 场地类型 / 设备都没读到）。
          </div>

          <!--
            `missing` 是模型自报的「你没说、我按什么默认值处理的」。
            这块**必须显示**：它是用户唯一能发现「AI 悄悄替他做了决定」的地方
            （后端 prompt 里明文要求模型把默认值写在这里，见 agent/chains/parse.py）。
          -->
          <div v-if="parsedMissing.length" class="parse-missing">
            <b>⚠️ 这些没说，是模型自己按默认值处理的</b>
            <p v-for="(m, i) in parsedMissing" :key="i">· {{ m }}</p>
          </div>

          <!--
            推荐只是**候选里的第一名**：模型看到的是全部可用场地、没带时间维度
            （时间正是它要抽的东西）。真正的可用性由「运行调度」的事务兜底，
            所以这里的措辞是「建议」而不是「已锁定」。
          -->
          <div v-if="parsedRecommend && (parsedRecommend.spaceName || parsedRecommend.reason)" class="parse-rec">
            <div>
              <span class="parse-reck">建议场地</span>
              <span class="parse-recv">
                {{ parsedRecommend.spaceName || `#${parsedRecommend.spaceId}` }}
              </span>
            </div>
            <div v-if="parsedRecommend.reason" class="parse-reason">
              {{ parsedRecommend.reason }}
            </div>
            <div
              v-for="(a, i) in parsedRecommend.alternatives || []"
              :key="i"
              class="parse-alt"
            >
              备选：{{ a.spaceName }}
              <span v-if="a.tradeoff">（{{ a.tradeoff }}）</span>
            </div>
          </div>

          <!--
            出口：把读出来的条件**写回输入框**，用户可以直接改这句话再跑调度。
            不在这里直接调 /agent/schedule —— 那个接口会真落单，
            由用户看过、改过、再亲手点「运行调度」才符合它「不是演示动画」的性质。
          -->
          <button class="sp-btn is-ghost is-sm parse-apply" @click="onApplyParsed">
            把条件写回输入框，我再改一改
          </button>
        </div>

        <div v-else-if="parseError" class="sp-witem is-red">
          <b>本次没能解析出条件</b>
          <p>{{ parseError }}</p>
        </div>

        <!-- Tool 调用：**完全由真实思考链推导**，没有真实的 action 就不显示 -->
        <div class="sp-card">
          <div class="sp-card-head">
            <b>Tool 调用</b>
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
          <div class="sp-card-head"><b>落库状态</b></div>
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
            <b>Agent 思考链</b>
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
            正在等模型逐步返回…
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
            <h4>主方案 · {{ plan.spaceName || `场地 #${plan.spaceId}` }}</h4>
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
            <div class="sp-card-head"><b>方案要素完整度</b></div>
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
                  <stop offset="100%" stop-color="var(--sp-cat-purple)" />
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
            <div class="sp-card-head" style="margin-bottom: 8px"><b>备选方案</b></div>
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
            <div class="sp-ic">◈</div>
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
import { computed, onMounted, ref, watch } from 'vue'

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
  parsing,
  parseResult,
  parseFresh,
  parseError,
  parsedRows,
  parsedMissing,
  parsedRecommend,
  parsedConfidence,
} = storeToRefs(store)

/** 输入框里的草稿。切页丢掉可接受，每次调度都要重新输入需求。 */
const text = ref(store.text || '')

/**
 * 输入框与 store 双向同步 —— **只有 store 里那份才参与「结果是否还有效」的判断**。
 *
 * `parseFresh` 比的是 `state.text` 与 `state.parseFrom`（见 store）。
 * 若这里只写局部 ref，用户在解析完之后改一个字，界面会继续显示
 * 「需求已改，结果待刷新」以外的旧结论 —— 判断依据就假了。
 */
watch(text, (v) => {
  store.text = v || ''
})


/* ------------------------------------------------------------------ *
 * AI 解析条件（POST /agent/parse）
 * ------------------------------------------------------------------ */

/** 按钮文案随状态变：解析在飞 / 结果已就绪 / 尚未解析 */
const parseButtonLabel = computed(() => {
  if (parsing.value) return 'AI 正在解析条件…'
  if (parseResult.value && parseFresh.value) return '✓ 已有解析结果（可重新解析）'
  return '解析条件'
})

/**
 * 解析一次需求。
 *
 * 与 `onRun` 的区别是这个按钮**没有副作用**：不锁资源、不建单，
 * 所以它不弹「已创建预约」之类的成功提示，也不需要确认框。
 */
async function onParse() {
  const value = (text.value || '').trim()
  if (!value) {
    ElMessage.warning('请先输入一条调度需求')
    return
  }
  const res = await store.parse(value)
  if (res.ok) {
    const rows = store.parsedRows
    ElMessage.success(
      rows.length ? `AI 读出了 ${rows.length} 项条件，请核对` : '解析完成，但这句里没有硬条件',
    )
  } else if (res.reason === 'empty') {
    ElMessage.warning('请先输入一条调度需求')
  }
  // 其余失败：原因已经落在 store.parseError 上、由卡片显示，
  // 同时 axios 拦截器弹过后端真实 message，不重复打扰。
}

/** 场地类型码 → 中文。与后端 `agent/chains/parse.py::SPACE_TYPE_CN` 同口径。 */
const SPACE_TYPE_CN = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

/**
 * 把解析出的条件**写回输入框**，拼成一句人话。
 *
 * 为什么是「拼成一句话」而不是「把条件存起来直接调 /agent/schedule」：
 *   1. 输入框是这一屏唯一的「需求真源」，把条件落到别处就会出现两个真源；
 *   2. `/agent/schedule` 会真落单，必须由用户**看过、改过、亲手点**才符合它的性质；
 *   3. 模型的 `missing` 项在这里正好变成用户可以顺手补的位置（缺什么一眼看得出来）。
 */
function onApplyParsed() {
  const c = store.parsedConditions
  if (!c) return
  const parts = []
  const rec = store.parsedRecommend
  // 场地用**名字**而不是 id：输入框里给后端的是自然语言，id 反而读不懂
  parts.push(`我要预约${(rec && rec.spaceName) || '场地'}`)
  if (c.capacity) parts.push(`${c.capacity}人`)
  if (c.spaceType) parts.push(SPACE_TYPE_CN[c.spaceType] || '场地')
  if (c.startTime && c.endTime) parts.push(`${c.startTime}~${c.endTime}`)
  else if (c.startTime) parts.push(c.startTime)
  if (Array.isArray(c.deviceTypes) && c.deviceTypes.length) {
    parts.push(`需要${c.deviceTypes.join('、')}`)
  }
  if (c.budget) parts.push(`预算${c.budget}元以内`)
  text.value = parts.join('，').slice(0, 1024)
  ElMessage.info('已写回输入框，改完再点「运行调度」——那一步才会真的建单')
}

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
  // 输入框也要清：它现在通过 watch 同步进 store.text，而 store.text 正是
  // `parseFresh` 的比较基准。只清结果不清输入，界面上会留着上一次的需求文本，
  // 用户会以为「清空」没生效。
  text.value = ''
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
/* ================= 需求输入区的两个按钮 ================= */
.runrow {
  display: flex;
  gap: var(--sp-s2);
  margin-top: 11px;
}

.runrow .sp-btn {
  flex: 1;
  min-width: 0;
}

/* 解析按钮不加渐变：它**不建单**，视觉上就不该和「运行调度」争主位 */
.parse-btn {
  white-space: normal;
  line-height: 1.5;
}

/* ================= AI 解析结果 ================= */
.parse-wait {
  margin-bottom: 13px;
  align-items: flex-start;
}

.parse-card {
  /* 与思考链卡片区分开：左缘一条紫线，表示「这是 AI 读出来的，还没有落库」 */
  border-left: 3px solid var(--sp-cat-purple);
}

.parse-rows {
  margin-top: 4px;
}

.parse-row {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-s2);
  padding: 7px 0;
  border-bottom: 1px solid var(--sp-bg-hover);
  font-size: 12.5px;
}

.parse-row:last-child {
  border-bottom: none;
}

/*
 * ⚠️ 这里用的不是全局的 `.sp-k` / `.sp-v`：那两个类在 styles/index.css 里
 * 只作为 **`.sp-mbrow` 的后代选择器**存在（`.sp-mbrow .sp-k`），
 * 单独用在别的容器里没有任何样式。本组件的 <style scoped> 也不该去改全局类。
 * 所以这一块自建一对类名。
 */
.parse-k {
  width: 72px;
  flex: none;
  color: var(--sp-t3, var(--sp-t3));
}

.parse-v {
  flex: 1;
  min-width: 0;
  word-break: break-all;
  color: var(--sp-text);
}

/* 「没说、模型自己按默认值处理的」—— 橙色与普通信息区分，这是**必须被看见**的一块 */
.parse-missing {
  margin-top: 12px;
  padding: 10px 12px;
  background: #fffbeb;
  border: 1px solid #fde8c8;
  border-radius: var(--sp-r-sm);
  font-size: 12px;
  color: #9a5f0f;
}

.parse-missing b {
  display: block;
  margin-bottom: 6px;
  color: #9a5f0f;
}

.parse-missing p {
  margin: 0;
  line-height: 1.7;
}

/* 推荐场地：一行「标签 + 名字」，下面的理由是正文 */
.parse-rec {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--sp-border-l);
}

.parse-reck {
  font-size: 12px;
  color: var(--sp-t3, var(--sp-t3));
  margin-right: 8px;
}

.parse-recv {
  font-size: 13px;
  font-weight: 600;
  color: var(--sp-text);
}

.parse-reason {
  font-size: 12px;
  color: var(--sp-t2, var(--sp-t2));
  line-height: 1.75;
  margin-top: 4px;
}

.parse-alt {
  font-size: 12px;
  color: var(--sp-t3, var(--sp-t3));
  line-height: 1.7;
  margin-top: 4px;
}

.parse-apply {
  margin-top: 12px;
}

.agentgrid {
  display: flex;
  gap: var(--sp-s3);
  align-items: flex-start;
  /* 行距（窄屏换行后生效）也收一档，避免换行后纵向叠出滚动 */
  row-gap: 10px;
}

.agcol {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.agcol.is-side {
  width: 326px;
  flex: none;
}

.agcol.is-main {
  flex: 1;
}

/*
 * 单列断点（2026-10-14 加）。
 *
 * 这一屏是「左输入 / 中思考链 / 右方案」三列，左列固定 326px。
 * 窄屏下三列会被压到不可读（实测 390px 视口时中文被挤成「一个字一行」，
 * 且文档横向溢出）。这里按宽度分两级降为单列：
 *
 *   ≤1200px  两列：输入列 + 主列（方案列并入主列下方）
 *   ≤900px   单列：全部纵向堆叠，顺序不变
 *
 * 只改布局，不动任何内容与顺序。
 */
@media (max-width: 1200px) {
  .agentgrid {
    flex-wrap: wrap;
  }

  .agcol.is-side {
    width: 300px;
  }
}

@media (max-width: 900px) {
  .agentgrid {
    flex-direction: column;
  }

  .agcol.is-side,
  .agcol.is-main {
    width: 100%;
    flex: none;
  }
}

/* ---------------- 需求输入 ---------------- */
/*
 * 需求输入框。
 *
 * ⚠️ 高度口径（2026-10-14 调整）：本屏要**一屏放下**，输入框是纵向占用最大的一块。
 *    · 行高 1.85 → 1.6：原先接近 1.9 的行高在 textarea 里显得空，压到 1.6 仍好读；
 *    · 行数与上限交给 clamp()：视口高时给足 200px（写长需求舒服），
 *      视口矮（笔记本 768~820）时自动收到 80px，避免整页被挤出滚动条。
 *    用的是 height + min/max-height 而不是只给 rows，因为 rows 是固定行数、
 *    不会随视口变。
 */
.ask-input {
  width: 100%;
  border: 1px solid var(--sp-accent-line);
  border-radius: var(--sp-r-sm);
  padding: 8px 12px;
  font-size: 13px;
  font-family: inherit;
  line-height: 1.6;
  color: var(--sp-text);
  background: #fff;
  resize: vertical;
  outline: none;
  height: clamp(64px, 12vh, 180px);
  min-height: 64px;
  max-height: 40vh;
}

.ask-input:focus {
  border-color: var(--sp-accent);
  box-shadow: var(--sp-focus);
}

/* 键盘聚焦也要有同样明确的信号（:focus 已覆盖，这里补 outline 清空） */
.ask-input:focus-visible {
  outline: none;
}

.run-btn {
  margin-top: var(--sp-s2);
}

.ask-tip {
  font-size: 12px;
  color: var(--sp-t3);
  margin-top: var(--sp-s2);
  line-height: 1.6;
  text-align: center;
}

/* ---------------- Tool 调用 ---------------- */
.tool-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  padding: 7px 0;
  border-bottom: 1px solid var(--sp-bg-hover);
}

.tool-row:last-child {
  border-bottom: none;
}

.tool-row code {
  font-family: ui-monospace, Consolas, monospace;
  color: #3d5a80;
  background: var(--sp-bg-hover);
  border-radius: var(--sp-r-xs);
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
  border-left: 3px solid var(--sp-warning);
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
  gap: var(--sp-s2);
  margin-top: 12px;
}

/* ---------------- 思考链 ----------------
 *
 * min-height 由 520px 降为 420px。
 * 原先 520 是为了「空态也撑出一块像样的画布」，但本屏要一屏放下，
 * 而这个值直接决定中列高度 —— 加上输入列的高度，整页就会被挤出滚动条。
 * 420 仍足以容纳 5~6 步思考链（每步约 60~70px），不够时它自己会长高。
 */
.trace-card {
  min-height: 420px;
}

/*
 * 矮屏收紧（2026-10-14 加）。
 *
 * 「一屏放下」在 ≥820px 视口高时已经成立，但 1366×768 这类笔记本还差约 33px。
 * 与其继续压控件把所有人都挤到，不如只在**确实矮**的时候把列间距收一档：
 * 12px → 8px，左列 3 个间距 + 网格行距一共省下约 20px，刚好补上缺口。
 * 高度 ≥ 801px 的屏幕完全不受影响。
 */
@media (max-height: 800px) {
  .agcol {
    gap: 8px;
  }

  .agentgrid {
    gap: 8px;
    row-gap: 8px;
  }

  .trace-card {
    min-height: 380px;
  }
}

.trace-empty {
  padding: 40px 0;
  text-align: center;
}

.trace-waiting {
  display: flex;
  align-items: center;
  gap: var(--sp-s2);
  font-size: 12.5px;
  color: var(--sp-accent);
  background: var(--sp-ai-soft);
  border: 1px solid var(--sp-ai-line);
  border-radius: var(--sp-r-sm);
  padding: 9px 12px;
  margin-bottom: 13px;
}

.step-time {
  margin-left: auto;
  font-size: 12px;
  color: var(--sp-t3);
  font-family: ui-monospace, Consolas, monospace;
  font-weight: 400;
}

/* ---------------- 方案要素 ---------------- */
.field-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-s1);
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
