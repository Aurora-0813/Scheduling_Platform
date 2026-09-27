<template>
  <view class="page">
    <view class="title">语音预约</view>
    <view class="tip">{{ statusText }}</view>

    <view
      class="mic-btn"
      :class="{ recording: status === 'recording', loading: status === 'uploading' }"
      @tap="toggleRecord"
    >
      <text class="mic-text">{{ btnText }}</text>
    </view>

    <view class="time" v-if="status === 'recording'">{{ seconds }} 秒</view>

    <view class="result-box" v-if="rawText">
      <view class="result-label">识别结果</view>
      <view class="result-text">{{ rawText }}</view>
      <button class="retry-btn" size="mini" @tap="reset">重说一遍</button>
    </view>

    <view class="error" v-if="errorMsg">{{ errorMsg }}</view>
  </view>
</template>

<script>
import { uploadVoice } from '@/utils/voiceApi.js'

export default {
  data() {
    return {
      status: 'idle', // idle 空闲 / recording 录音中 / uploading 识别中
      rawText: '',
      errorMsg: '',
      seconds: 0,
      timer: null,
      recorder: null,
    }
  },
  computed: {
    statusText() {
      if (this.status === 'recording') return '正在录音，再点一下按钮结束'
      if (this.status === 'uploading') return '正在识别，请稍候…'
      return '点一下下面的按钮，说出你的预约需求'
    },
    btnText() {
      if (this.status === 'recording') return '停止'
      if (this.status === 'uploading') return '识别中'
      return '录音'
    },
  },
  onLoad() {
    this.recorder = uni.getRecorderManager()

    // 录音结束（手动停止或到 60 秒自动结束）
    this.recorder.onStop((res) => {
      this.stopTimer()
      this.status = 'uploading'
      this.uploadAudio(res.tempFilePath)
    })

    // 录音出错（没给麦克风权限等）
    this.recorder.onError((err) => {
      this.stopTimer()
      this.status = 'idle'
      this.errorMsg = '录音失败：' + (err.errMsg || '请在设置里打开麦克风权限')
    })
  },
  methods: {
    toggleRecord() {
      this.errorMsg = ''
      if (this.status === 'recording') {
        this.recorder.stop()
        return
      }
      this.rawText = ''
      this.status = 'recording'
      this.seconds = 0
      this.startTimer()
      this.recorder.start({
        duration: 60000, // 最长 60 秒，到时间自动结束
        sampleRate: 16000, // 采样率 16k，和后端百度 ASR 保持一致
        numberOfChannels: 1, // 单声道
        encodeBitRate: 48000,
        format: 'wav', // wav 格式，百度识别直接支持
      })
    },
    async uploadAudio(filePath) {
      try {
        const data = await uploadVoice(filePath)
        this.rawText = data.text
        this.status = 'idle'
      } catch (e) {
        this.errorMsg = e.message || '识别失败，请重试'
        this.status = 'idle'
      }
    },
    startTimer() {
      this.timer = setInterval(() => {
        this.seconds += 1
      }, 1000)
    },
    stopTimer() {
      if (this.timer) {
        clearInterval(this.timer)
        this.timer = null
      }
    },
    reset() {
      this.rawText = ''
      this.errorMsg = ''
      this.status = 'idle'
    },
  },
}
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 60rpx 40rpx;
}
.title {
  font-size: 44rpx;
  font-weight: bold;
  margin-bottom: 20rpx;
}
.tip {
  font-size: 28rpx;
  color: #666;
  margin-bottom: 80rpx;
}
.mic-btn {
  width: 280rpx;
  height: 280rpx;
  border-radius: 50%;
  background-color: #2979ff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.mic-btn.recording {
  background-color: #fa3534;
}
.mic-btn.loading {
  background-color: #909399;
}
.mic-text {
  color: #fff;
  font-size: 48rpx;
}
.time {
  margin-top: 30rpx;
  font-size: 32rpx;
  color: #fa3534;
}
.result-box {
  margin-top: 70rpx;
  width: 100%;
  background-color: #f5f7fa;
  border-radius: 16rpx;
  padding: 30rpx;
  box-sizing: border-box;
}
.result-label {
  font-size: 26rpx;
  color: #999;
  margin-bottom: 12rpx;
}
.result-text {
  font-size: 32rpx;
  line-height: 1.6;
  color: #303133;
  margin-bottom: 20rpx;
}
.retry-btn {
  margin: 0;
}
.error {
  margin-top: 40rpx;
  font-size: 28rpx;
  color: #fa3534;
}
</style>
