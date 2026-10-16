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
        <text class="askt">还需要你补充</text>
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
        <text class="sect">已规整为结构化约束</text>
        <view class="chips">
          <text v-for="(c, i) in chips" :key="i" class="chip">{{ c }}</text>
        </view>
      </template>

      <!--
        AI 解析出的条件（2026-10-13 新增，POST /agent/parse）。
        摆在「手动输入」之前、CTA 之上：用户点完按钮眼睛就在这一带，
        条件读到哪、哪个字段读空了，必须**当场**能看见 —— 猜错才有机会纠正。
      -->
      <view v-if="parsed" class="pcard">
        <view class="phead">
          <text class="pt">读出的条件</text>
          <text class="pc">置信度 {{ Math.round((parsed.confidence || 0) * 100) }}%</text>
        </view>

        <view v-if="parsedRows.length" class="prows">
          <view v-for="(r, i) in parsedRows" :key="i" class="prow">
            <text class="pk">{{ r.k }}</text>
            <text class="pv">{{ r.v }}</text>
          </view>
        </view>
        <text v-else class="pnone">这句话里没有明确的硬条件，请在确认页自己选。</text>

        <view v-if="parsedRecommend && (parsedRecommend.spaceName || parsedRecommend.reason)" class="prec">
          <text class="prect">💡 推荐场地</text>
          <text v-if="parsedRecommend.spaceName" class="precn">{{ parsedRecommend.spaceName }}</text>
          <text v-if="parsedRecommend.reason" class="precr">{{ parsedRecommend.reason }}</text>
          <!-- 备选只是并列候选，不带理由会让人以为「也行」；代价必须一起给 -->
          <text
            v-for="(a, i) in (parsedRecommend.alternatives || [])"
            :key="'a' + i"
            class="preca"
          >备选：{{ a.spaceName }}<template v-if="a.tradeoff">（{{ a.tradeoff }}）</template></text>
        </view>

        <!--
          `missing` 是模型自报的「你没说、我按什么默认值处理的」。
          这块**必须显示**：它是唯一能让用户发现「AI 悄悄替他做了决定」的地方。
        -->
        <view v-if="parsedConditions && parsedConditions.missing && parsedConditions.missing.length" class="pmiss">
          <text class="pmisst">⚠️ 这些没提到，看你认不认</text>
          <text v-for="(m, i) in parsedConditions.missing" :key="'m' + i" class="pmissl">· {{ m }}</text>
        </view>
      </view>

      <text v-if="parseError" class="perr">{{ parseError }}</text>

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
      <!--
        主出口（2026-10-13 起）：先让 AI **读一遍**，把条件摆出来给用户核对，再建单。
        与下面「交给 AI 生成方案」的区别必须说清楚：
          这条走 /agent/parse，**不落单**；下面那条走 /agent/schedule，会真落一条待确认预约。
      -->
      <view
        class="btn ai block"
        :class="{ disabled: !agentText || parsing }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="onParse"
      >{{ parseBtnLabel }}</view>

      <!--
        方案 A 的第二个出口（2026-10-13 加）：先自己把时间 / 场地 / 设备选清楚，再直接下单。
        语音和拍照不一样 —— 用户**可能**说了时间（「周六下午」），也可能一句都没提，
        所以这条路是「补全」，不是「替换」：说到的那部分自动预填，没说的在确认页补。
      -->
      <view
        class="btn ghost block cta-2"
        :class="{ disabled: !agentText }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="goConfirm"
      >先核对时间 / 场地 / 设备 →</view>

      <!--
        原有主按钮降为第三位：它会**真的落一条待确认预约**（见 goAgent），
        而上面两条都还没有副作用。有副作用的那个不该排在第一个。
      -->
      <view
        class="btn ghost block cta-2"
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
import { parseRequest } from '@/api/agent.js'
import { agentStore } from '@/store/agent.js'
import { setPrefill } from '@/store/reservePrefill.js'
import { RECORD_OPTIONS } from '@/config/index.js'
import { parseDateTime } from '@/utils/format.js'
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

/**
 * 「AI 解析条件」态（2026-10-13 新增）。
 *
 * 与 formatting 分开：两者都是模型调用、都可能同时在飞，共用一个标签会让
 * 用户以为「规整完了」，其实解析还在跑。序号同 fmtSeq 的理由 —— 并发只认最后一次。
 */
const parsing = ref(false)
const parseSeq = { n: 0 }
/** POST /agent/parse 的结果：`{ conditions, recommend, confidence, latencyMs }` */
const parsed = ref(null)
/**
 * 这份 parsed 是**针对哪段文本**解析出来的。
 *
 * 用来判断「还能不能直接复用」：用户改完字再点按钮，旧的条件就不能再拿去预填了，
 * 必须重新解析。用文本本身比对，比加一个 dirty 标志可靠（改了又改回来仍算同一份）。
 */
const parsedFrom = ref('')
/** 解析失败时的可读原因（后端 message / 网络原因），显示在按钮下方 */
const parseError = ref('')
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
  if (parsing.value) return 'AI 正在读这句话里的时间 / 人数 / 设备…'
  if (formatting.value) return 'AI 正在规整为结构化约束…（文字已可用，可直接提交）'
  if (rawText.value) return '长按可以重新说一次'
  return '按住下方按钮，说出你的场地需求'
})

/**
 * 交给 Agent 的文本：优先用规整后的，没有就用原始识别结果。
 *
 * ⚠️ 「AI 解析条件」解析的是**规整后**的文本（用户点按钮时屏幕上显示的就是它）。
 * 规整还在飞的时候 `formattedText` 为空，此处自动退回 `rawText` ——
 * 这正是我们要的：解析不等规整，用户点了就用现有的文字去读。
 */
const agentText = computed(() => formattedText.value || rawText.value)

const chips = computed(() => keywords.value)

// ------------------------------------------------------------------
// AI 解析条件（POST /agent/parse）
// ------------------------------------------------------------------
/**
 * 上次解析出来的条件，**是否仍然对应当前这段文字**。
 *
 * 为什么要有这个判断：解析一次要 10~32 秒，用户改一个字就得重跑一遍体验很差。
 * 反过来，如果用户改了字还用旧条件去预填，就等于拿「别的话」读出来的结果
 * 替他填表 —— 比不填更糟。用文本比对两头都占到。
 */
const parseFresh = computed(() => Boolean(parsed.value) && parsedFrom.value === agentText.value)

const parsedConditions = computed(() => (parsed.value && parsed.value.conditions) || null)
const parsedRecommend = computed(() => (parsed.value && parsed.value.recommend) || null)

const SPACE_TYPE_TEXT = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

/** 「AI 读出了什么」列出成对（`{ k, v }`），空值不占位置。 */
const parsedRows = computed(() => {
  const c = parsedConditions.value
  if (!c) return []
  const rows = []
  if (c.capacity) rows.push({ k: '人数', v: c.capacity + ' 人' })
  if (c.spaceType) rows.push({ k: '类型', v: SPACE_TYPE_TEXT[c.spaceType] || '不限' })
  const start = parseDateTime(c.startTime)
  if (start) {
    const end = parseDateTime(c.endTime)
    rows.push({
      k: '时间',
      v:
        `${start.getMonth() + 1}-${start.getDate()} ` +
        `${('0' + start.getHours()).slice(-2)}:${('0' + start.getMinutes()).slice(-2)}` +
        (end
          ? `~${('0' + end.getHours()).slice(-2)}:${('0' + end.getMinutes()).slice(-2)}`
          : ''),
    })
  }
  if (c.deviceTypes && c.deviceTypes.length) rows.push({ k: '设备', v: c.deviceTypes.join('、') })
  if (c.budget) rows.push({ k: '预算', v: '¥ ' + c.budget })
  return rows
})

/**
 * 按钮文案。**点一次解析、再点一次进确认页**，不是一点就跳走。
 *
 * 为什么不第一次点就直接跳确认页：那样用户永远看不到「AI 读出了什么」，
 * 只能到确认页里自己发现人数被读成了 20。先展示再带走，才是「猜错能当场纠正」。
 */
const parseBtnLabel = computed(() => {
  if (parsing.value) return 'AI 正在解析条件…'
  return parseFresh.value ? '确认条件并核对场地 →' : '解析条件'
})

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

function onPressStart() {
  if (recording.value || recognizing.value) return
  // 解析要跑 10~32 秒。这期间重新录一段不会让在飞的解析停下，
  // 只会得到一份「针对上一句话」的条件卡 —— 直接不让起录更干净。
  if (parsing.value) {
    toast('AI 正在解析条件，请稍等')
    return
  }
  if (editing.value) {
    toast('先保存或取消正在修改的文字')
    return
  }

  // 直接 start()：微信小程序与 App 都会自动触发麦克风权限弹窗；
  // 被拒绝时 recorder.onError 会兜住。不再用 uni.authorize ——
  // 那是微信专用 API，在 Android App 上会静默失败，导致「按了没反应」。
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
  // 文字要变了，上一次的条件解析结果随之作废。
  // `parseFresh` 本来就会因为文本对不上而失效，这里显式清掉卡片与错误提示 ——
  // 否则屏幕上会留着一张描述**上一句话**的条件卡，用户会以为它还是准的。
  parsed.value = null
  parsedFrom.value = ''
  parseError.value = ''
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

/** 需求关键词 → 台账设备类型。只用于在确认页**预勾选**，抽错了取消即可。 */
const REQ_TO_DEVICE = [
  { keys: ['投影'], type: '投影仪' },
  { keys: ['音响', '扩音', '话筒', '麦克'], type: '音响' },
  { keys: ['显示屏', '大屏', '屏幕', 'LED'], type: 'LED显示屏' },
  { keys: ['直播'], type: '直播设备' },
  { keys: ['无人机', '航拍'], type: '无人机' },
]

function deviceTypesFromText(text) {
  const hit = []
  REQ_TO_DEVICE.forEach((m) => {
    if (m.keys.some((k) => String(text).indexOf(k) >= 0) && hit.indexOf(m.type) < 0) hit.push(m.type)
  })
  return hit
}

/** 「20人」「12 位」→ 20 / 12；没说就返回 null（不猜） */
function extractCapacity(text) {
  const m = String(text).match(/(\d{1,4})\s*(人|位)/)
  return m ? Number(m[1]) : null
}

/**
 * 把模型给的时间**吸附到 15 分钟档**，返回 `'YYYY-MM-DD HH:mm:00'`；出界返回 ''。
 *
 * ⚠️ 为什么必须做（2026-10-13 补，这是个真会咬人的坑）：
 *   确认页的时间是 picker 选的，档位固定 15 分钟一格
 *   （`confirm.vue` 的 `TIME_OPTIONS`＝ 07:00~23:45 每 15 分钟）。
 *   它算选中下标用的是 `Math.max(0, TIME_OPTIONS.indexOf(startTime))` ——
 *   值不在档位里时 `indexOf` 返回 **-1**，被 `Math.max` 夹成 **0**，
 *   于是 picker **静默显示 07:00**；而 `range()` 拼提交参数用的
 *   又是那个错的 `startTime.value`。**看到的和提交的是同一个错值，没人会发现。**
 *
 *   模型完全可能给「下午两点二十」这种非整档时间（实测给过 14:20）。
 *   不吸附的话，预约单会建在早上七点。
 *
 * 出界（早于 07:00 / 晚于 23:45 / 跨天）返回 ''：那说明模型理解出了问题，
 * 让用户自己去确认页选，比替他决定一个错时间强。
 */
function toQuarterHourSlot(value) {
  const raw = parseDateTime(value)
  if (!raw) return ''
  const d = new Date(raw.getTime())
  // 向上取整到 15 分钟档
  d.setSeconds(0, 0)
  d.setMinutes(d.getMinutes() + ((15 - (d.getMinutes() % 15)) % 15))
  // 取整后跨了天（23:5x → 次日），或落在 picker 覆盖不到的范围 → 不猜
  if (d.getDate() !== raw.getDate() || d.getHours() < 7 || d.getHours() > 23) return ''
  const p = (n) => (n < 10 ? '0' + n : '' + n)
  return (
    d.getFullYear() +
    '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
    ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':00'
  )
}

/**
 * 「AI 解析条件」按钮（2026-10-13 新增）。
 *
 * 点第一次：把这句话交给 `POST /agent/parse`，把 AI 读出的时间 / 人数 / 设备 / 预算
 * 就地摆出来给用户核对；点第二次（文案变成「确认条件并核对场地 →」）才带着这些
 * 条件去确认页。**两次点击是有意的** —— 见 parseBtnLabel 的说明。
 *
 * 解析本身**没有任何副作用**（不建单、不锁资源），所以可以放心重复点；
 * 与 `goAgent()`（/agent/schedule，真落一条待确认预约）是完全不同的两条路。
 */
async function onParse() {
  const text = agentText.value
  if (!text) {
    toast('请先说出或输入你的需求')
    return
  }
  if (recording.value || recognizing.value) {
    toast('先等这次识别结束')
    return
  }
  // 已经解析过、且文字没变 → 用户这次点的是「确认」，直接带着结果去确认页
  if (parseFresh.value) {
    goConfirmWithParsed()
    return
  }

  const seq = ++parseSeq.n
  parsing.value = true
  parseError.value = ''
  try {
    const res = await parseRequest({ text, imageContext: agentStore.imageContext || {} })
    // 期间用户又发起了一次解析 / 改了文字重新提交 —— 旧结果直接丢弃
    if (seq !== parseSeq.n) return
    parsed.value = res || null
    parsedFrom.value = text
    const c = (res && res.conditions) || {}
    // 「AI 没读懂」要和「AI 读出来了但字段为空」区分开，否则用户以为解析失败了
    if (!c.capacity && !c.spaceType && !c.startTime && (!c.deviceTypes || !c.deviceTypes.length)) {
      parseError.value = '这句话里没读出人数/时间/场地的硬条件，去确认页自己选也很快。'
    }
  } catch (e) {
    if (seq !== parseSeq.n) return
    parsed.value = null
    parsedFrom.value = ''
    // request.js 这次是 silent 的，原因由这里说 —— 否则用户只看到按钮弹回去
    parseError.value = (e && e.message) || 'AI 解析失败，可直接手动选择时间与场地'
  } finally {
    if (seq === parseSeq.n) parsing.value = false
  }
}

/**
 * 带着**已核对过的解析结果**去确认页。
 *
 * 预填口径：解析出来的条件优先，解析没读到的字段退回本地正则兜底
 * （`extractCapacity` / `deviceTypesFromText`）—— 两者都不猜时留空，
 * 由用户在确认页补齐，这与「不让 AI 替他补常识」是同一条原则。
 */
function goConfirmWithParsed() {
  const text = agentText.value
  const c = (parsedConditions.value || {})
  const rec = parsedRecommend.value || {}
  setPrefill({
    source: 'voice',
    sourceLabel: '语音预约 · AI 解析',
    // ① 场地：推荐只是候选里的第一名，确认页仍会按该时段**真实可用性**重查一遍，
    //    查不到就自动清掉（见 confirm.vue::refreshSpaces），所以这里给出去是安全的
    spaceId: rec.spaceId || null,
    capacity: c.capacity || extractCapacity(text),
    spaceType: c.spaceType || 0,
    deviceTypes: c.deviceTypes && c.deviceTypes.length ? c.deviceTypes : deviceTypesFromText(text),
    // ② 时间：解析出的是绝对时间，确认页会拆成「日期 + 开始 + 结束」三段。
    //    必须**吸附到 15 分钟档**再交出去 —— 理由见 toQuarterHourSlot：
    //    非整档的值会被确认页的 picker 静默显示成 07:00，并且就这么提交上去。
    slotStart: toQuarterHourSlot(c.startTime),
    slotEnd: toQuarterHourSlot(c.endTime),
    text: text,
    imageContext: agentStore.imageContext || null,
  })
  uni.navigateTo({ url: '/pages/reserve/confirm' })
}

/**
 * 去确认页自己把时间 / 场地 / 设备选清楚（方案 A 的第二个出口，2026-10-13 加）。
 *
 * 为什么不直接把这句话丢给 Agent：
 *   Agent 得从「周六下午」反推绝对时间、从「要投影」猜设备类型、从场地名匹配 spaceId，
 *   **猜错了用户没有机会纠正** —— 只能等方案出来再改，绕一圈。
 * 这里把能抽出来的（人数、设备类型）预填好，抽不出的（具体时段、哪间场地、哪台设备）
 * 让用户在确认页点一下就行。
 *
 * ⚠️ 这是**不经过 AI 解析**的兜底出口（纯本地正则），解析按钮走 goConfirmWithParsed。
 */
function goConfirm() {
  const text = agentText.value
  if (!text) {
    toast('请先说出或输入你的需求')
    return
  }
  setPrefill({
    source: 'voice',
    sourceLabel: '语音预约',
    capacity: extractCapacity(text),
    deviceTypes: deviceTypesFromText(text),
    text: text,
    imageContext: agentStore.imageContext || null,
  })
  uni.navigateTo({ url: '/pages/reserve/confirm' })
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
/* 底部 CTA 现在有三个按钮（解析 / 自己核对 / 交给 Agent），比默认两行高，
   而 .app-body.has-cta 只留了 200rpx —— 不补的话最后一张卡片会被压住 */
.app-body.has-cta {
  padding-bottom: 340rpx;
}

.cta-2 {
  margin-top: 18rpx;
}

/* ---- AI 解析出的条件（POST /agent/parse） ---- */
.pcard {
  margin-top: 30rpx;
  background: var(--primary-bg);
  border: 1px solid var(--ai-line);
  border-radius: var(--r-lg);
  padding: 24rpx;
}

.phead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.pt {
  font-size: 26rpx;
  font-weight: 600;
  color: var(--primary);
}

.pc {
  font-size: 22rpx;
  color: var(--t3);
}

/* 读出来的条件：左标签右值，用户一眼扫完就能判断「读错没有」 */
.prows {
  margin-top: 6rpx;
}

.prow {
  display: flex;
  align-items: flex-start;
  padding: 12rpx 0;
  border-top: 1rpx solid var(--primary-bg);
}

.pk {
  width: 110rpx;
  flex-shrink: 0;
  font-size: 24rpx;
  color: var(--t3);
}

.pv {
  flex: 1;
  font-size: 26rpx;
  color: var(--t1);
  line-height: 1.5;
}

.pnone {
  display: block;
  font-size: 24rpx;
  color: var(--t3);
  line-height: 1.7;
  padding-top: 8rpx;
}

.prec {
  margin-top: 20rpx;
  padding-top: 18rpx;
  border-top: 1rpx solid var(--primary-bg);
}

.prect {
  display: block;
  font-size: 24rpx;
  color: var(--t3);
  margin-bottom: 8rpx;
}

.precn {
  display: block;
  font-size: 28rpx;
  font-weight: 600;
  color: var(--t1);
}

.precr {
  display: block;
  font-size: 23rpx;
  color: var(--t2);
  line-height: 1.7;
  margin-top: 6rpx;
}

.preca {
  display: block;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  margin-top: 6rpx;
}

/* 「没说、我替你按什么默认值处理了」—— 用橙色，与普通信息区分开 */
.pmiss {
  margin-top: 20rpx;
  padding: 18rpx 20rpx;
  background: var(--warning-bg);
  border: 1px solid var(--warning-bg);
  border-radius: var(--r-sm);
}

.pmisst {
  display: block;
  font-size: 23rpx;
  font-weight: 600;
  color: var(--warning);
  margin-bottom: 8rpx;
}

.pmissl {
  display: block;
  font-size: 22rpx;
  color: var(--warning);
  line-height: 1.7;
}

.perr {
  display: block;
  margin-top: 24rpx;
  font-size: 23rpx;
  color: var(--t3);
  line-height: 1.7;
  text-align: center;
}

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
  border: 1px solid var(--bd-l);
  border-radius: var(--r-lg);
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
  gap: var(--s4);
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
  background: var(--primary-bg);
  border: 1px solid var(--ai-line);
  border-radius: var(--r-lg);
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
