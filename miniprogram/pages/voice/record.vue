<template>
  <view class="app-page">
    <mp-nav-bar title="语音预约" back :right="timerText" />

    <view class="app-body has-cta">
      <!--
        AI 上次的追问（例如「请您补充使用时间」）。
        方案页在没有方案时会把它带过来 —— 否则用户回到这页只看到一段预填文本，
        不知道该补什么，来回打转。
      -->
      <view v-if="agentStore.lastQuestion" class="askcard">
        <text class="askt">🤖 AI 还需要你补充</text>
        <text class="askc">{{ agentStore.lastQuestion }}</text>
      </view>

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

      <!-- 识别中让波形继续律动：这是取消 loading 转圈后的进度反馈 -->
      <view class="wave" :class="{ off: !recording && !recognizing }">
        <view v-for="n in 12" :key="n" class="bar"></view>
      </view>

      <text class="hint">{{ hintText }}</text>

      <!-- 识别文本 + 语义高亮；ASR 难免听错，所以必须能改 -->
      <view v-if="segments.length" class="asr">
        <template v-if="!editing">
          <text v-for="(s, i) in segments" :key="i" :class="s.cls">{{ s.text }}</text>
          <text v-if="recognizing || typing || formatting" class="caret"></text>
        </template>
        <textarea
          v-else
          v-model="draft"
          class="earea"
          :maxlength="200"
          auto-height
          :focus="autoFocus"
          :cursor="cursorPos"
          :cursor-spacing="24"
          @blur="onDraftBlur"
        />
      </view>

      <view v-if="segments.length" class="asrbar">
        <template v-if="!editing">
          <text class="alink" @tap="startEdit">✏️ 继续修改</text>
        </template>
        <template v-else>
          <text class="alink gray" @tap="cancelEdit">取消</text>
          <text class="alink" @tap="applyEdit">保存并重新规整</text>
        </template>
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
      >{{ formatting ? 'AI 规整中… 可直接提交' : '交给 AI 生成方案 →' }}</view>
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
 * 录音参数取自 config/index.js 的 RECORD_OPTIONS（wav / 16k / 单声道 / 60s）。
 * 注：ASR 已于 2026-09-30 从百度换成阿里云 Qwen3-ASR-Flash（见 docs/spec/后端改动1.md §5.27），
 * 但 wav / 16k / 单声道这一组参数对两家都成立，故保持不变。
 *
 * 与原 record.vue 的差异：页面按原型重做（波形 + 语义高亮 + 约束 chip），
 * 脚本风格改为 <script setup>，接口收敛到 api/voice.js 统一管理。
 */
import { ref, computed, onUnmounted } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { asr, format } from '@/api/voice.js'
import { agentStore } from '@/store/agent.js'
import { RECORD_OPTIONS } from '@/config/index.js'
import { toast } from '@/utils/toast.js'

const recording = ref(false)
const recognizing = ref(false)
const seconds = ref(0)
const rawText = ref('')
const formattedText = ref('')
const keywords = ref([])
const showInput = ref(false)
const manualText = ref('')
/** 识别结果编辑态：true 时 .asr 显示 textarea（草稿在 draft 里） */
const editing = ref(false)
const draft = ref('')
/** 规整态：与 recognizing 分开——/voice/format 实测要 20~25 秒，不能和识别共用一个标签 */
const formatting = ref(false)
/** 规整请求序号：并发时只认最后一次的结果，防止旧响应盖掉新文本 */
let fmtSeq = 0
/** 打字机：识别结果一个字一个字吐出来（typing 为 true 时展示 typed，而不是整段 rawText） */
const typing = ref(false)
const typed = ref('')
/** 一次性聚焦：识别完自动进编辑态并弹出键盘，blur 后置回 false，避免反复抢焦点 */
const autoFocus = ref(false)
/** focus 时的光标位置；只在程序化进编辑态时改，用户自己点选时不动它 */
const cursorPos = ref(0)
let typeTimer = null

let recorder = null
let timer = null

const timerText = computed(() => {
  if (!recording.value && !seconds.value) return ''
  const m = Math.floor(seconds.value / 60)
  const s = seconds.value % 60
  return `${m < 10 ? '0' + m : m}:${s < 10 ? '0' + s : s}`
})

const hintText = computed(() => {
  if (editing.value) return '改完点「保存并重新规整」'
  if (recording.value) return '正在聆听… 松开结束'
  if (recognizing.value) return 'AI 正在识别语音…'
  if (typing.value) return '识别完成，稍后可直接修改'
  if (formatting.value) return 'AI 正在规整为结构化约束…（文字已可用，可直接提交）'
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

const segments = computed(() =>
  buildSegments(typing.value ? typed.value : rawText.value, keywords.value)
)

// ------------------------------------------------------------------
// 录音
// ------------------------------------------------------------------
onLoad(() => {
  // 拍照识场会往 agentStore.request 里放一句「我想预约 XX 场地」再跳过来，
  // 这里接着它，用户不用重新说一遍；直接提交也能走通（agentText 兜底用 rawText）
  const pre = agentStore.request
  if (pre) {
    // 从拍照识场带过来的需求（"我要预约A栋201会议室，12人，…"）：
    // 直接进编辑态，用户接着补时间/设备就行，不用先点一下「修改」
    rawText.value = pre
    manualText.value = pre
    enterEdit()
  } else {
    // 全新的语音需求：清掉上一次拍照识场留下的场地上下文，
    // 否则 Agent 会把上一张照片里的场地当成这次的需求
    agentStore.imageContext = null
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
  stopTypewriter()
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
  if (editing.value) {
    toast('先保存或取消正在修改的文字')
    return
  }

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

/**
 * 上传录音做 ASR → 打字机吐出结果 → 自动进入可编辑态 → 后台规整。
 *
 * 有意**不用 showLoading 转圈**：ASR 只有 1~2 秒，弹遮罩会把整页锁住，
 * 还会和后面的规整阶段抢同一个提示。进度感改由「律动的波形 + 打字机光标」承担。
 */
async function recognize(filePath) {
  stopTypewriter()
  editing.value = false
  draft.value = ''
  // 上一轮可能还在规整：作废它的结果，免得盖掉这一轮的新文本
  fmtSeq += 1
  formatting.value = false
  recognizing.value = true
  try {
    const asrRes = await asr(filePath)
    rawText.value = asrRes.text || ''
  } catch (e) {
    toast(e.message || '语音识别失败')
    return
  } finally {
    recognizing.value = false
  }

  if (!rawText.value) {
    toast('没听清，再说一次试试')
    return
  }

  await typeOut(rawText.value)
  // 识别完直接就是可编辑的，光标落在末尾——不再需要先点一下「修改」
  enterEdit()
  reformat(rawText.value)
}

/** 进入可编辑态：光标默认落在末尾，并自动聚焦 */
function enterEdit() {
  draft.value = rawText.value
  cursorPos.value = rawText.value.length
  editing.value = true
  autoFocus.value = true
}

/** 键盘收起后解除自动聚焦，否则页面上任何一次重渲染都会把键盘再弹回来 */
function onDraftBlur() {
  autoFocus.value = false
}

/**
 * 打字机：把 src 逐段写进 typed（展示层看的是 segments → typed）。
 * 总时长压到 1.2 秒左右（30ms 一跳），长句自动加大每跳字数，
 * 不会出现「说得越长等得越久」。
 */
function typeOut(src) {
  return new Promise((resolve) => {
    const text = String(src || '')
    typed.value = ''
    if (!text) {
      typing.value = false
      resolve()
      return
    }
    typing.value = true
    const perTick = Math.max(1, Math.ceil(text.length / 40))
    // 先吐第一段：否则 segments 会短暂为空，识别框闪一下才出现
    typed.value = text.slice(0, perTick)
    typeTimer = setInterval(() => {
      typed.value = text.slice(0, typed.value.length + perTick)
      if (typed.value.length >= text.length) {
        stopTypewriter()
        resolve()
      }
    }, 30)
  })
}

function stopTypewriter() {
  if (typeTimer) {
    clearInterval(typeTimer)
    typeTimer = null
  }
  typing.value = false
}

/** 手动输入直接走 /voice/format，与语音路径汇聚到同一处 */
async function useManual() {
  const text = manualText.value.trim()
  if (!text) {
    toast('请先输入需求')
    return
  }
  cancelEdit()
  await reformat(text)
}

// ------------------------------------------------------------------
// 识别结果编辑（ASR 难免听错「二十人」→「二是人」这类词）
// ------------------------------------------------------------------
/**
 * 把原文交给 /voice/format 重新规整。手输、改识别结果、语音识别后都走这一条路。
 *
 * 有意**不加遮罩**：/voice/format 实测要 20~25 秒（模型走思考模式），
 * 而原文在这之前就已经写在屏幕上了。再盖一层「正在转换」只会让人以为卡住了，
 * 所以改成一句行内提示，期间文字照样可读、可改、可直接提交（agentText 会退回 rawText）。
 */
async function reformat(text) {
  // 每次规整领一个序号，回调时对不上就说明已经有更新的请求，直接丢弃
  const seq = ++fmtSeq
  stopTypewriter()
  // 注意：这里**不**动 editing —— 语音识别后要一直留在可编辑态，
  // 收起编辑框由 applyEdit / useManual 自己决定
  rawText.value = text
  manualText.value = text
  formattedText.value = ''
  keywords.value = []
  formatting.value = true
  try {
    const fmtRes = await format(text)
    if (seq !== fmtSeq) return
    formattedText.value = fmtRes.formattedText || ''
    keywords.value = fmtRes.keywords || []
  } catch (e) {
    if (seq !== fmtSeq) return
    // 规整失败不丢原文：agentText 会退回 rawText，照样能提交
    toast(e.message || '规整失败，将直接用原文提交')
  } finally {
    if (seq === fmtSeq) formatting.value = false
  }
}

function startEdit() {
  // 识别 / 打字中文本还会被整段覆盖，先不让改；
  // 规整中允许改——保存时会作废在飞的那次规整结果
  if (recognizing.value || typing.value) return
  enterEdit()
}

function cancelEdit() {
  stopTypewriter()
  editing.value = false
  draft.value = ''
}

function applyEdit() {
  const text = draft.value.trim()
  if (!text) {
    toast('内容不能为空')
    return
  }
  if (text === rawText.value) {
    cancelEdit()
    return
  }
  cancelEdit()
  reformat(text)
}

function goAgent() {
  const text = agentText.value
  if (!text) {
    toast('请先说出或输入你的需求')
    return
  }
  // 把这段需求连同可能的场地上下文一起交给 thinking 页发起 /agent/schedule
  agentStore.request = text
  // 追问已经用过了，清掉，免得下一轮还挂着上一轮的话
  agentStore.lastQuestion = ''
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

/* ---- 识别结果编辑 ---- */
.earea {
  width: 100%;
  padding: 0;
  min-height: 96rpx;
  font-size: 27rpx;
  line-height: 2;
  color: var(--t1);
  background: transparent;
}

.asrbar {
  display: flex;
  justify-content: flex-end;
  gap: 36rpx;
  margin-top: 16rpx;
}

.alink {
  font-size: 24rpx;
  color: var(--primary);
}

.alink.gray {
  color: var(--t3);
}

/* ---- AI 上次的追问（从方案页带过来） ---- */
.askcard {
  background: #f3f8ff;
  border: 1px solid var(--ai-line);
  border-radius: 22rpx;
  padding: 22rpx 24rpx;
  margin-bottom: 26rpx;
}

.askt {
  display: block;
  font-size: 24rpx;
  font-weight: 600;
  color: var(--primary);
  margin-bottom: 10rpx;
}

.askc {
  display: block;
  font-size: 23rpx;
  color: var(--t2);
  line-height: 1.7;
}
</style>
