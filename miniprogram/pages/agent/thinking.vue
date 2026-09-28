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
          <text class="rt">{{ request }}</text>
        </view>

        <view v-for="s in visibleSteps" :key="s.step" class="mbstep">
          <view class="tnum" :class="toneOf(s)">{{ s.step }}</view>
          <view class="txt">
            <text class="ss">{{ s.title }}</text>
            <text>{{ s.body }}</text>

            <!-- 工具调用回显。actionInput 的键是 snake_case（后端 Tool 签名原样回显），
                 这里不做字段解析，整串展示 -->
            <view v-if="s.call" class="code wrap">{{ s.call }}</view>
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
 * 每一步的文案都来自后端的 step / result / thought / action / actionInput。
 */
import { ref, computed, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { agentStore, runSchedule } from '@/store/agent.js'
import { formatActionInput } from '@/api/agent.js'

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
 * 标题取 result（后端给的可读结论，如「查询场地：命中 2 个候选场地」），
 * 正文取 thought（模型的推理过程）。两者都缺就退回占位，不硬编。
 */
function normalizeTrace(trace) {
  return (trace || []).map((t, i) => ({
    step: t.step === undefined || t.step === null ? i + 1 : t.step,
    title: t.result || `步骤 ${i + 1}`,
    body: t.thought || '',
    call: t.action
      ? `${t.action}(${formatActionInput(t.actionInput)})`
      : '',
    raw: t,
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
    const data = await runSchedule(agentStore.request)
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
  border: 1px solid #f0f3f8;
  border-radius: 20rpx;
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

/* 工具调用串较长，这一步不省略，允许折行 */
.code.wrap {
  white-space: normal;
  word-break: break-all;
  line-height: 1.7;
}

.mbstep .txt .ss {
  line-height: 1.6;
}

.waiting {
  display: flex;
  align-items: center;
  gap: 16rpx;
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
