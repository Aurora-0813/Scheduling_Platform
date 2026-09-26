<template>
  <view class="page">
    <view class="form-item">
      <text class="label">场地</text>
      <picker :range="spaces" range-key="spaceName" @change="onSpaceChange">
        <view class="picker">{{ selectedSpace ? selectedSpace.spaceName : '请选择场地' }}</view>
      </picker>
    </view>

    <view class="form-item column">
      <text class="label">设备（可多选）</text>
      <checkbox-group class="devices" @change="onDeviceChange">
        <label v-for="d in devices" :key="d.deviceId" class="device-item">
          <checkbox :value="String(d.deviceId)" :checked="selectedDeviceIds.includes(String(d.deviceId))" />{{ d.deviceName }}
        </label>
      </checkbox-group>
      <text v-if="devices.length === 0" class="hint">暂无设备</text>
    </view>

    <view class="form-item">
      <text class="label">日期</text>
      <picker mode="date" :value="date" @change="(e) => (date = e.detail.value)">
        <view class="picker">{{ date || '请选择日期' }}</view>
      </picker>
    </view>

    <view class="form-item">
      <text class="label">开始时间</text>
      <picker mode="time" :value="startTime" @change="(e) => (startTime = e.detail.value)">
        <view class="picker">{{ startTime }}</view>
      </picker>
    </view>

    <view class="form-item">
      <text class="label">结束时间</text>
      <picker mode="time" :value="endTime" @change="(e) => (endTime = e.detail.value)">
        <view class="picker">{{ endTime }}</view>
      </picker>
    </view>

    <button type="primary" class="submit" @click="submit">提交预约</button>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { getResources, createOrder } from '@/api/reserve'

const spaces = ref([])
const devices = ref([])
const selectedSpace = ref(null)
const selectedDeviceIds = ref([])
const date = ref('')
const startTime = ref('09:00')
const endTime = ref('10:00')

function today() {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

onLoad(async () => {
  date.value = today()
  const data = await getResources()
  spaces.value = data.spaces || []
  devices.value = data.devices || []
})

function onSpaceChange(e) {
  selectedSpace.value = spaces.value[e.detail.value]
}
function onDeviceChange(e) {
  selectedDeviceIds.value = e.detail.value
}

async function submit() {
  // 前端校验（后端仍会强校验）
  if (!selectedSpace.value) return uni.showToast({ title: '请选择场地', icon: 'none' })
  if (startTime.value >= endTime.value)
    return uni.showToast({ title: '开始时间须早于结束时间', icon: 'none' })

  // 时间格式统一 YYYY-MM-DD HH:mm:ss（§5.1）
  const payload = {
    spaceId: selectedSpace.value.spaceId,
    deviceIds: selectedDeviceIds.value.map(Number),
    startTime: `${date.value} ${startTime.value}:00`,
    endTime: `${date.value} ${endTime.value}:00`,
  }

  await createOrder(payload)
  uni.showToast({ title: '预约已提交', icon: 'success' })
  setTimeout(() => uni.navigateBack(), 800)
}
</script>

<style scoped>
.page { padding: 24rpx; }
.form-item { background: #fff; border-radius: 16rpx; padding: 24rpx; margin-bottom: 20rpx; display: flex; justify-content: space-between; align-items: center; }
.form-item.column { flex-direction: column; align-items: flex-start; }
.label { color: #333; width: 160rpx; flex-shrink: 0; }
.column .label { width: auto; margin-bottom: 16rpx; }
.picker { color: #666; flex: 1; text-align: right; }
.input { flex: 1; text-align: right; }
.devices { display: flex; flex-wrap: wrap; gap: 16rpx; }
.device-item { font-size: 26rpx; color: #333; display: flex; align-items: center; gap: 8rpx; }
.hint { color: #bbb; font-size: 24rpx; }
.submit { margin-top: 40rpx; }
</style>
