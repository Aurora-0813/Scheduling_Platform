<template>
  <view class="page">
    <view class="input-area">
      <textarea
        v-model="requirement"
        placeholder="描述你的需求，如：帮我预约明天上午的会议室"
        class="textarea"
      />
      <view class="btn-row">
        <button size="mini" @click="startRecord">{{ recording ? '停止录音' : '语音' }}</button>
        <button size="mini" @click="chooseImage">图像</button>
        <button size="mini" type="primary" @click="submit">提交需求</button>
      </view>
    </view>

    <view v-if="trace.length" class="section">
      <view class="section-title">AI 思考过程</view>
      <!-- trace 为 TraceStep 对象数组（§5.3 冻结契约），按 result 渲染、按 timestamp 标注 -->
      <view v-for="(t, i) in trace" :key="i" class="trace-item">
        {{ t.step || i + 1 }}. {{ t.result }}
        <text class="trace-ts">{{ t.timestamp }}</text>
      </view>
    </view>

    <view v-if="plan" class="section">
      <view class="section-title">推荐方案</view>
      <view class="card">
        <view class="title">{{ plan.spaceName || '场地#' + plan.spaceId }}</view>
        <view class="meta">{{ plan.startTime }} ~ {{ plan.endTime }}</view>
        <view class="meta">{{ plan.reason }}</view>
        <button size="mini" type="primary" class="confirm" @click="confirmPlan(plan)">确认此方案</button>
      </view>
      <view v-if="backupPlan" class="card">
        <view class="title">{{ backupPlan.spaceName || '场地#' + backupPlan.spaceId }}</view>
        <view class="meta">{{ backupPlan.startTime }} ~ {{ backupPlan.endTime }}</view>
        <view class="meta">{{ backupPlan.reason }}</view>
        <button size="mini" type="primary" class="confirm" @click="confirmPlan(backupPlan)">确认此方案</button>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { agentSchedule, agentTranscribe, agentRecognize } from '@/api/agent'
import { createOrder } from '@/api/reserve'

const requirement = ref('')
const trace = ref([])
const plan = ref(null)
const backupPlan = ref(null)
const recording = ref(false)
let recorder = null

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

async function submit() {
  if (!requirement.value.trim()) return uni.showToast({ title: '请输入需求', icon: 'none' })
  trace.value = []
  plan.value = null
  backupPlan.value = null
  const data = await agentSchedule(requirement.value.trim())
  // 逐步渲染思考过程
  const steps = data.trace || []
  for (let i = 0; i < steps.length; i++) {
    trace.value.push(steps[i])
    await sleep(400)
  }
  plan.value = data.plan
  backupPlan.value = data.backupPlan
}

function startRecord() {
  if (recording.value) {
    recorder.stop()
    return
  }
  recorder = uni.getRecorderManager()
  recorder.onStop(async (res) => {
    recording.value = false
    uni.showLoading({ title: '识别中' })
    const data = await agentTranscribe(res.tempFilePath)
    uni.hideLoading()
    requirement.value = data.text
    uni.showToast({ title: '已识别，请确认后提交', icon: 'none' })
  })
  recorder.start({ format: 'mp3' })
  recording.value = true
}

async function chooseImage() {
  const res = await new Promise((resolve) =>
    uni.chooseImage({ count: 1, success: resolve, fail: () => resolve(null) })
  )
  if (!res || !res.tempFilePaths || !res.tempFilePaths.length) return
  uni.showLoading({ title: '识别中' })
  const data = await agentRecognize(res.tempFilePaths[0])
  uni.hideLoading()
  requirement.value = data.text
}

// 确认方案 = 直接调 orders/create，落库 agentRequest + agentTrace（§5.3）
async function confirmPlan(p) {
  await createOrder({
    spaceId: p.spaceId,
    deviceIds: p.deviceIds || [],
    startTime: p.startTime,
    endTime: p.endTime,
    agentRequest: requirement.value.trim(),
    agentTrace: trace.value,
  })
  uni.showToast({ title: '已创建预约', icon: 'success' })
  setTimeout(() => uni.switchTab({ url: '/pages/reserve/list' }), 800)
}
</script>

<style scoped>
.page { padding: 24rpx; }
.input-area { background: #fff; border-radius: 16rpx; padding: 24rpx; margin-bottom: 24rpx; }
.textarea { width: 100%; height: 160rpx; font-size: 28rpx; }
.btn-row { display: flex; gap: 16rpx; justify-content: flex-end; margin-top: 16rpx; }
.section { margin-bottom: 24rpx; }
.section-title { font-size: 28rpx; color: #666; margin-bottom: 16rpx; }
.trace-item { background: #fff; border-radius: 12rpx; padding: 16rpx 20rpx; margin-bottom: 12rpx; font-size: 26rpx; color: #555; }
.trace-ts { margin-left: 12rpx; font-size: 22rpx; color: #999; }
.card { background: #fff; border-radius: 16rpx; padding: 24rpx; margin-bottom: 20rpx; }
.title { font-size: 30rpx; font-weight: 600; margin-bottom: 12rpx; }
.meta { color: #666; font-size: 26rpx; margin-top: 8rpx; }
.confirm { margin-top: 20rpx; }
</style>
