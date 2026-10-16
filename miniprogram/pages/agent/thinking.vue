<template>
  <view class="app-page">
    <mp-nav-bar title="AI 正在思考" back :right="elapsedText" />

    <view class="app-body has-cta">
      <view v-if="error" class="witem red">
        <text class="wt">调度失败</text>
        <text class="wp">{{ error }}</text>
        <view class="btn ghost" hover-class="btn-on" @tap="retry">重新尝试</view>
      </view>

      <template v-else>
        <!-- 需求回显：让用户确认 AI 理解的是不是自己说的 -->
        <view v-if="request" class="req">
          <text class="rq">你的需求</text>
          <!-- user-select：长文本可长按复制，否则开发者工具会提示，用户也没法拷走 -->
          <text class="rt" :user-select="true">{{ request }}</text>
        </view>

        <view v-for="s in visibleSteps" :key="s.step" class="mbstep">
          <view class="tnum" :class="toneOf(s)">{{ s.step }}</view>
          <view class="txt">
            <view class="sline">
              <text class="ss">{{ s.title }}</text>
              <!-- 纯推理步标「推理」：用来区分「这步有没有动系统」。
                   有 Action 的步不标，避免挂一个英文工具名当噪音。 -->
              <text v-if="!s.action" class="tag gray">推理</text>
            </view>
            <text v-if="s.time" class="stime">{{ s.time }}</text>

            <!--
              ⚠️ 2026-10-06 对准 Web 端：**每步只显示最终结果**（result + 时间）。
              以下内容按产品决定**一律不渲染**（数据仍在接口响应里，契约没变）：
                · thought      —— 模型的逐步推理正文（几百字）
                · actionInput  —— 工具入参（snake_case 的 JSON）
                · observation  —— 工具返回
              原来这三样都渲染，7 步会被撑成好几屏，与 Web 端看到的不是一回事。
              将来若要「展开看明细」，加一个折叠层即可恢复，无需改后端。
            -->
          </view>
        </view>

        <!-- 还没出结果时的等待提示 -->
        <view v-if="!steps.length" class="waiting">
          <view class="live b"></view>
          <text>正在解析需求、检索场地、校验冲突…</text>
        </view>
      </template>
    </view>

    <view class="app-cta">
      <view
        class="btn ai block"
        :class="{ disabled: !ready }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="goPlan"
      >查看方案 →</view>
    </view>
  </view>
</template>

<script setup>
/**
 * M3 Agent 思考链
 *
 * 对应原型「小程序-3 Agent 思考链」。
 *
 * 说明：/agent/schedule 是**一次性返回**完整 trace 的（后端不流式），
 * 所以这里的「逐步显现」是按真实 trace 逐条播出，不是伪造进度。
 * 每一步的文案只取后端的 step / result / timestamp 与 action（action 仅用于判断是否标「推理」）。
 */
import { ref, computed, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { agentStore, runSchedule } from '@/store/agent.js'

const error = ref('')
const steps = ref([])
const visibleCount = ref(0)
const elapsed = ref(0)
/** 结果是否已就绪：全部分步播完，或用户点快了就直接放行 */
const payloadReady = ref(false)

let tickTimer = null
let revealTimer = null

const request = computed(() => agentStore.request)

const elapsedText = computed(() => {
  if (!elapsed.value) return ''
  return `${(elapsed.value / 10).toFixed(1)}s`
})

const ready = computed(() => payloadReady.value && steps.value.length > 0)

const visibleSteps = computed(() => steps.value.slice(0, visibleCount.value))

/**
 * 把后端的 trace 项整理成渲染用的形状。
 *
 * ⚠️ 2026-10-06 对准 Web 端：**只保留每步的最终结果**。
 *    `title` 取 `result`（后端给的可读中文结论，如「查询场地：命中 2 个候选场地」），
 *    `time` 取 `timestamp`（只留 `HH:mm:ss`）。
 *    原先还映射了 `body`(thought) 与 `call`(actionInput)，现已删掉 ——
 *    Web 端同样不渲染它们（见 `frontend/src/views/AgentWorkbench.vue` 的说明）。
 *    `action` 仍保留：模板只用它判断**要不要标「推理」**，不渲染成文字。
 *    两者都缺时退回占位，不硬编。
 */
function normalizeTrace(trace) {
  return (trace || []).map((t, i) => ({
    step: t.step === undefined || t.step === null ? i + 1 : t.step,
    title: t.result || `步骤 ${i + 1}`,
    time: (t.timestamp || '').slice(11),
    action: t.action || '',
  }))
}

/**
 * 编号配色：末步为成功绿；结论里出现冲突/降级/失败等词的标橙。
 * 纯展示逻辑，不影响业务判断。
 */
function toneOf(s) {
  if (!s) return ''
  const title = String(s.title)
  if (/冲突|占用|不可用|降级|失败|超预算|不满足/.test(title)) return 'o'
  if (s.step === steps.value.length) return 'g'
  return ''
}

onLoad(() => {
  tickTimer = setInterval(() => {
    elapsed.value += 1
  }, 100)
  start()
})

onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
  if (revealTimer) clearTimeout(revealTimer)
})

async function start() {
  error.value = ''
  payloadReady.value = false
  steps.value = []
  visibleCount.value = 0

  try {
    // 必须把 imageContext 一起传：拍照识场识别到的场地（含 spaceId）就走这条路
    // 进 Agent，只传 text 会让它从一句话里重新猜场地
    const data = await runSchedule(agentStore.request, agentStore.imageContext)
    steps.value = normalizeTrace(data.trace)
    reveal()
  } catch (e) {
    error.value = e.message || 'AI 调度失败'
    if (tickTimer) clearInterval(tickTimer)
  }
}

/** 每 450ms 放出一条，7 步约 3.2s，与原型的「3.2s」观感一致 */
function reveal() {
  const total = steps.value.length
  if (!total) {
    payloadReady.value = true
    return
  }
  const tick = () => {
    visibleCount.value += 1
    if (visibleCount.value >= total) {
      payloadReady.value = true
      if (tickTimer) clearInterval(tickTimer)
      return
    }
    revealTimer = setTimeout(tick, 450)
  }
  tick()
}

function retry() {
  if (tickTimer) clearInterval(tickTimer)
  elapsed.value = 0
  tickTimer = setInterval(() => {
    elapsed.value += 1
  }, 100)
  start()
}

function goPlan() {
  // 等不及动画时也允许直接进方案页
  if (!steps.value.length) return
  uni.navigateTo({ url: '/pages/agent/plan' })
}
</script>

<style scoped>
.req {
  background: #fff;
  border: 1px solid var(--bd-l);
  border-radius: var(--r-lg);
  padding: 22rpx 24rpx;
  margin-bottom: 28rpx;
}

.rq {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  margin-bottom: 10rpx;
}

.rt {
  font-size: 25rpx;
  color: var(--t1);
  line-height: 1.7;
}

/* 结论行：结论文字 + 「推理」标签并排。
   用 inline-flex（不是 flex）让这组只占自身宽度，
   标签紧跟在结论后面 —— Web 端就是这样，不是把标签推到行尾。 */
.sline {
  display: inline-flex;
  align-items: baseline;
  gap: var(--s2);
  margin-bottom: 6rpx;
}

/* 主题里 .mbstep .txt .ss 是 display:block + 下边距；这里在 inline-flex 行内
   要它按内容宽度排，所以只覆盖宽度行为，字号/字重仍用主题的 */
.mbstep .txt .ss {
  flex: none;
  margin-bottom: 0;
}

.stime {
  display: block;
  font-size: 21rpx;
  color: var(--t3);
}

.waiting {
  display: flex;
  align-items: center;
  gap: var(--s2);
  padding: 40rpx 0;
  font-size: 25rpx;
  color: var(--t3);
}

.witem .btn {
  display: inline-block;
  padding: 12rpx 32rpx;
  font-size: 24rpx;
}
</style>
