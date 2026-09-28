<template>
  <view class="app-page">
    <mp-nav-bar title="语音预约" back :right="timerText" />

    <view class="app-body has-cta">
      <!-- 麦克风按钮：按住说话 -->
      <view
        class="rec"
        :class="{ on: recording }"
        @touchstart="onPressStart"
        @touchend="onPressEnd"
        @touchcancel="onPressEnd"
      >
        <text>🎙</text>
      </view>

      <view class="wave" :class="{ off: !recording }">
        <view v-for="n in 12" :key="n" class="bar"></view>
      </view>

      <text class="hint">{{ hintText }}</text>

      <!-- 识别文本 + 语义高亮 -->
      <view v-if="segments.length" class="asr">
        <text v-for="(s, i) in segments" :key="i" :class="s.cls">{{ s.text }}</text>
        <text v-if="recognizing" class="caret"></text>
      </view>

      <!-- 规整后的结构化约束 -->
      <template v-if="chips.length">
        <text class="sect">🤖 AI 已规整为结构化约束</text>
        <view class="chips">
          <text v-for="(c, i) in chips" :key="i" class="chip">{{ c }}</text>
        </view>
      </template>

      <!-- 录音不可用 / 不想说话时的兜底输入 -->
      <view class="manual">
        <text class="mlink" @tap="showInput = !showInput">
          {{ showInput ? '收起手动输入' : '不方便说话？手动输入 ›' }}
        </text>
        <template v-if="showInput">
          <textarea
            v-model="manualText"
            class="marea"
            placeholder="例：本周五下午要个能坐 40 人的展厅，带双投影和音响，预算 1000 以内，没大场地就拆两个小的"
            :maxlength="200"
            auto-height
          />
          <view class="btn ghost" hover-class="btn-on" @tap="useManual">用这段文字</view>
        </template>
      </view>
    </view>

    <view class="app-cta">
      <view
        class="btn ai block"
        :class="{ disabled: !agentText }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="goAgent"
      >交给 AI 生成方案 →</view>
    </view>
  </view>
</template>

<script setup>
/**
 * M2 语音预约
 *
 * 对应原型「小程序-2 语音输入 · 语义高亮」。
 *
 * 接口契约沿用郑宇豪已对齐的后端实现，**未做任何改动**：
 *   POST /voice/asr     FormData 字段名 file  → { text }
 *   POST /voice/format  { rawText }           → { formattedText, keywords[] }
 * 录音参数取自 config/index.js 的 RECORD_OPTIONS（wav / 16k / 单声道 / 60s），
 * 与百度 ASR 要求一致，勿改。
 *
 * 与原 record.vue 的差异：页面按原型重做（波形 + 语义高亮 + 约束 chip），
 * 脚本风格改为 <script setup>，接口收敛到 api/voice.js 统一管理。
 */
import { ref, computed, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { asr, format } from '@/api/voice.js'
import { agentStore } from '@/store/agent.js'
import { RECORD_OPTIONS } from '@/config/index.js'
import { toast, showLoading, hideLoading } from '@/utils/toast.js'

const recording = ref(false)
const recognizing = ref(false)
const seconds = ref(0)
const rawText = ref('')
const formattedText = ref('')
const keywords = ref([])
const showInput = ref(false)
const manualText = ref('')

let recorder = null
let timer = null

const timerText = computed(() => {
  if (!recording.value && !seconds.value) return ''
  const m = Math.floor(seconds.value / 60)
  const s = seconds.value % 60
  return `${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`
})

const hintText = computed(() => {
  if (recording.value) return '正在聆听… 松开结束'
  if (recognizing.value) return 'AI 正在识别…'
  if (rawText.value) return '长按可以重新说一次'
  return '按住下方按钮，说出你的场地需求'
})

/** 交给 Agent 的文本：优先用规整后的，没有就用原始识别结果 */
const agentText = computed(() => formattedText.value || rawText.value)

const chips = computed(() => keywords.value)

// ------------------------------------------------------------------
// 语义高亮
// ------------------------------------------------------------------
/**
 * 关键词归类到原型的四种高亮色：
 * t 时间 / n 人数 / d 设备 / b 预算。
 * 后端只给 keywords[]，没有类型信息，因此按词面做启发式判断。
 * 判断顺序重要——「1000 元以内」必须先于「人」等规则命中。
 */
function classify(kw) {
  const s = String(kw)
  if (/预算|价格|费用|元|块钱|以内|以下/.test(s)) return 'ent b'
  if (/人|位|号人|规模/.test(s)) return 'ent n'
  if (/投影|音响|屏幕|显示屏|话筒|麦克|灯光|设备|白板|讲台/.test(s)) return 'ent d'
  if (/周|星期|上午|下午|晚上|中午|点|时段|今天|明天|后天|号/.test(s)) return 'ent t'
  return 'ent t'
}

/**
 * 把原文切成 [普通片段, 高亮片段...]。
 * 关键词可能互相包含或重叠，这里按起点排序后只保留不重叠的命中。
 */
function buildSegments(text, kws) {
  const src = String(text || '')
  if (!src) return []

  const hits = []
  ;(kws || []).forEach((k) => {
    const kw = String(k || '')
    if (!kw) return
    let from = 0
    while (from <= src.length - kw.length) {
      const idx = src.indexOf(kw, from)
      if (idx < 0) break
      hits.push({ start: idx, end: idx + kw.length, kw })
      from = idx + kw.length
    }
  })

  if (!hits.length) return [{ text: src, cls: '' }]

  // 起点靠前的优先；起点相同则长词优先
  hits.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start))

  const picked = []
  let lastEnd = -1
  hits.forEach((h) => {
    if (h.start >= lastEnd) {
      picked.push(h)
      lastEnd = h.end
    }
  })

  const segs = []
  let cursor = 0
  picked.forEach((h) => {
    if (h.start > cursor) segs.push({ text: src.slice(cursor, h.start), cls: '' })
    segs.push({ text: src.slice(h.start, h.end), cls: classify(h.kw) })
    cursor = h.end
  })
  if (cursor < src.length) segs.push({ text: src.slice(cursor), cls: '' })
  return segs
}

const segments = computed(() => buildSegments(rawText.value, keywords.value))

// ------------------------------------------------------------------
// 录音
// ------------------------------------------------------------------
onLoad(() => {
  // 拍照识场会往 agentStore.request 里放一句「我想预约 XX 场地」再跳过来，
  // 这里接着它，用户不用重新说一遍；直接提交也能走通（agentText 兜底用 rawText）
  const pre = agentStore.request
  if (pre) {
    manualText.value = pre
    rawText.value = pre
    showInput.value = true
  }

  // 录音器要在页面内取，不能在模块顶层（小程序启动时可能还没准备好）
  recorder = uni.getRecorderManager()

  recorder.onStop((res) => {
    stopTimer()
    const path = res && res.tempFilePath
    if (!path) {
      toast('没有录到声音，请重试')
      return
    }
    if (seconds.value < 1) {
      toast('说话时间太短了')
      return
    }
    recognize(path)
  })

  recorder.onError((err) => {
    recording.value = false
    stopTimer()
    toast((err && err.errMsg) || '录音失败')
  })
})

onUnmounted(() => {
  stopTimer()
})

function startTimer() {
  seconds.value = 0
  timer = setInterval(() => {
    seconds.value += 1
    // 后端与 RECORD_OPTIONS 都限制 60s，到点自动收
    if (seconds.value >= RECORD_OPTIONS.duration / 1000) {
      stopRecord()
    }
  }, 1000)
}

function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

/** 先要录音权限，被拒过就引导去设置页 */
function ensureAuth() {
  return new Promise((resolve) => {
    uni.authorize({
      scope: 'scope.record',
      success: () => resolve(true),
      fail: () => {
        uni.showModal({
          title: '需要麦克风权限',
          content: '语音预约需要录音权限，请在设置中开启后重试。',
          confirmText: '去设置',
          success: (res) => {
            if (res.confirm) uni.openSetting({})
            resolve(false)
          },
          fail: () => resolve(false),
        })
      },
    })
  })
}

async function onPressStart() {
  if (recording.value || recognizing.value) return

  const ok = await ensureAuth()
  if (!ok) return

  recording.value = true
  startTimer()
  try {
    recorder.start({
      duration: RECORD_OPTIONS.duration,
      sampleRate: RECORD_OPTIONS.sampleRate,
      numberOfChannels: RECORD_OPTIONS.numberOfChannels,
      encodeBitRate: RECORD_OPTIONS.encodeBitRate,
      format: RECORD_OPTIONS.format,
    })
  } catch (e) {
    recording.value = false
    stopTimer()
    toast('录音启动失败，请检查麦克风权限')
  }
}

function stopRecord() {
  if (!recording.value) return
  recording.value = false
  try {
    recorder.stop()
  } catch (e) {
    stopTimer()
  }
}

function onPressEnd() {
  stopRecord()
}

/** 上传录音做 ASR，再调 /voice/format 拿结构化约束 */
async function recognize(filePath) {
  recognizing.value = true
  showLoading('AI 识别中…')
  try {
    const asrRes = await asr(filePath)
    rawText.value = asrRes.text || ''
    if (!rawText.value) {
      toast('没听清，再说一次试试')
      return
    }
    const fmtRes = await format(rawText.value)
    formattedText.value = fmtRes.formattedText || ''
    keywords.value = fmtRes.keywords || []
  } catch (e) {
    toast(e.message || '语音识别失败')
  } finally {
    recognizing.value = false
    hideLoading()
  }
}

/** 手动输入直接走 /voice/format，与语音路径汇聚到同一处 */
async function useManual() {
  const text = manualText.value.trim()
  if (!text) {
    toast('请先输入需求')
    return
  }
  rawText.value = text
  formattedText.value = ''
  keywords.value = []
  recognizing.value = true
  showLoading('AI 规整中…')
  try {
    const fmtRes = await format(text)
    formattedText.value = fmtRes.formattedText || ''
    keywords.value = fmtRes.keywords || []
  } catch (e) {
    toast(e.message || '规整失败，将直接用原文提交')
  } finally {
    recognizing.value = false
    hideLoading()
  }
}

function goAgent() {
  const text = agentText.value
  if (!text) {
    toast('请先说出或输入你的需求')
    return
  }
  // 交给 thinking 页发起 /agent/schedule，避免两个页面重复请求
  agentStore.request = text
  uni.navigateTo({ url: '/pages/agent/thinking' })
}
</script>

<style scoped>
.hint {
  display: block;
  text-align: center;
  font-size: 24rpx;
  color: var(--t3);
  margin: 16rpx 0 26rpx;
}

.sect {
  display: block;
  margin: 26rpx 0 18rpx;
  font-size: 24rpx;
  color: var(--t3);
}

.manual {
  margin-top: 34rpx;
}

.mlink {
  font-size: 24rpx;
  color: var(--primary);
}

.marea {
  width: 100%;
  margin-top: 18rpx;
  padding: 22rpx;
  min-height: 160rpx;
  font-size: 26rpx;
  line-height: 1.7;
  color: var(--t1);
  background: #fff;
  border: 1px solid #f0f3f8;
  border-radius: 20rpx;
}

.manual .btn {
  margin-top: 18rpx;
  display: block;
}
</style>
