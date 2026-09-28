<template>
  <view class="app-page">
    <mp-nav-bar title="拍照识场" back />

    <view class="app-body has-cta">
      <view class="imgbox" @tap="pick">
        <image v-if="photo" class="photo" :src="photo" mode="aspectFill" />
        <view v-else class="cam">
          <text class="big">📷</text>
          <text>拍下门牌或场地，AI 识别空间与可用设备</text>
        </view>
        <view v-if="photo" class="bbox on-photo">
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
        </view>
        <view v-if="analyzing" class="scanline"></view>
      </view>

      <view v-if="result">
        <!-- 置信度不足：按 §4.4 模块 2 向用户追问，不直接当成已确认结果 -->
        <view v-if="result.needConfirm" class="witem blue">
          <text class="wt">需要你确认一下</text>
          <text class="wp">{{ result.question || '这张照片不太确定，请选择或补充信息。' }}</text>
          <view v-if="candidates.length" class="cands">
            <view
              v-for="(c, i) in candidates"
              :key="i"
              class="cand"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap="pickCandidate(c)"
            >
              <text class="cn-name">{{ candidateName(c) }}</text>
              <text v-if="candidateConf(c)" class="cn-conf">{{ candidateConf(c) }}</text>
            </view>
          </view>
        </view>

        <view class="mcard">
          <view class="mtitle">
            <text>🤖 AI 识别结果</text>
            <text v-if="confidenceText" class="more">{{ confidenceText }}</text>
          </view>

          <view class="mbrow">
            <text class="k">场地</text>
            <text class="v">{{ displayName }}</text>
          </view>
          <view v-if="result.type" class="mbrow">
            <text class="k">类型</text>
            <text class="v">{{ typeText }}</text>
          </view>
          <view v-if="result.capacity" class="mbrow">
            <text class="k">容量</text>
            <text class="v">{{ result.capacity }} 人</text>
          </view>
          <view v-if="result.layout" class="mbrow">
            <text class="k">布局</text>
            <text class="v">{{ result.layout }}</text>
          </view>
        </view>

        <!-- 可用时段 -->
        <view v-if="slots.length" class="mcard">
          <view class="mtitle">可用时段</view>
          <view v-for="(s, i) in slots" :key="i" class="mbrow">
            <text class="k">{{ s.date || '今天' }}</text>
            <text class="v">{{ s.startTime }} - {{ s.endTime }}</text>
          </view>
        </view>

        <!-- 识别到的设备 -->
        <view v-if="devices.length" class="mcard">
          <view class="mtitle">识别到的设备</view>
          <view v-for="(d, i) in devices" :key="i" class="mbrow">
            <text class="k">{{ d.deviceType || '设备' }}</text>
            <text class="v">{{ d.count || 1 }} 台{{ confSuffix(d.confidence) }}</text>
          </view>
        </view>

        <!-- 草图识别的需求项 -->
        <view v-if="requirements.length" class="mcard">
          <view class="mtitle">识别到的需求</view>
          <view class="chips">
            <text v-for="(r, i) in requirements" :key="i" class="chip">{{ r }}</text>
          </view>
        </view>
      </view>

      <text v-if="!photo" class="note">
        支持 jpg / png / webp / bmp，单张不超过 {{ IMAGE_LIMIT.MAX_MB }}MB。
      </text>
    </view>

    <view class="app-cta">
      <view
        v-if="!result"
        class="btn ai block"
        :class="{ disabled: analyzing }"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="pick"
      >{{ analyzing ? 'AI 识别中…' : '拍一张试试' }}</view>

      <view v-else class="app-cta-row">
        <view class="btn ghost" hover-class="btn-on" @tap="pick">重拍</view>
        <view class="btn ai grow" hover-class="btn-on" @tap="goVoice">带着它去预约 →</view>
      </view>
    </view>
  </view>
</template>

<script setup>
/**
 * 拍照识场
 *
 * 契约：POST /image/analyze  multipart，字段名固定 file
 *   → { type, spaceId, spaceName, confidence, availableTime[], devices[],
 *       needConfirm, question, candidates[], imageUrl }
 * 另有 POST /image/sketch 用于手绘草图（本页暂只接 analyze）。
 *
 * ⚠️ confidence 低于阈值时后端给 needConfirm=true + question，
 *   此时**不能**直接把结果当成已确认场地用，必须先追问（§4.4 模块 2）。
 * ⚠️ imageUrl 是 /uploads/... 相对路径，展示前要拼 BASE_URL。
 */
import { ref, computed } from 'vue'
import { analyze } from '@/api/image.js'
import { absoluteUrl } from '@/api/request.js'
import { spaceTypeLabel } from '@/utils/dict.js'
import { IMAGE_LIMIT } from '@/config/index.js'
import { first } from '@/utils/normalize.js'
import { toast, showLoading, hideLoading } from '@/utils/toast.js'
import { agentStore } from '@/store/agent.js'

const photo = ref('')
const result = ref(null)
const analyzing = ref(false)

const candidates = computed(() => {
  const c = result.value ? result.value.candidates : null
  return Array.isArray(c) ? c : []
})

const slots = computed(() => {
  const s = result.value ? result.value.availableTime : null
  return Array.isArray(s) ? s : []
})

const devices = computed(() => {
  const d = result.value ? result.value.devices : null
  return Array.isArray(d) ? d : []
})

const requirements = computed(() => {
  const r = result.value ? result.value.requirements : null
  return Array.isArray(r) ? r : []
})

const displayName = computed(() => {
  const r = result.value
  if (!r) return ''
  return first(r.spaceName, r.name, '未识别出场地名')
})

/** type 可能是 'space'/'sketch' 这类英文枚举，也可能直接是中文场地类型 */
const typeText = computed(() => {
  const t = result.value ? result.value.type : ''
  if (t === 'space') return '实体场地'
  if (t === 'sketch') return '手绘草图'
  return spaceTypeLabel(t)
})

const confidenceText = computed(() => {
  const c = result.value ? result.value.confidence : null
  if (c === undefined || c === null || c === '') return ''
  const n = Number(c)
  if (isNaN(n)) return ''
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `置信度 ${pct}%`
})

function confSuffix(c) {
  const n = Number(c)
  if (!c || isNaN(n)) return ''
  return `（${n <= 1 ? Math.round(n * 100) : Math.round(n)}%）`
}

function candidateName(c) {
  if (typeof c === 'string') return c
  return first(c.spaceName, c.name, '候选场地')
}

function candidateConf(c) {
  if (typeof c === 'string') return ''
  const n = Number(c.confidence)
  if (!c.confidence || isNaN(n)) return ''
  return `${n <= 1 ? Math.round(n * 100) : Math.round(n)}%`
}

function pick() {
  if (analyzing.value) return

  const onPicked = (path, size) => {
    if (!validate(path, size)) return
    photo.value = path
    result.value = null
    run(path)
  }

  if (typeof uni.chooseMedia === 'function') {
    uni.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera', 'album'],
      sizeType: ['compressed'],
      success: (res) => {
        const f = res.tempFiles && res.tempFiles[0]
        if (f) onPicked(f.tempFilePath, f.size)
      },
      fail: () => {},
    })
    return
  }

  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: (res) => {
      const path = res.tempFilePaths && res.tempFilePaths[0]
      const file = res.tempFiles && res.tempFiles[0]
      if (path) onPicked(path, file ? file.size : 0)
    },
    fail: () => {},
  })
}

/** 与后端 image.py 的限制保持一致（≤5MB，仅四种格式） */
function validate(path, size) {
  if (size && size > IMAGE_LIMIT.MAX_MB * 1024 * 1024) {
    toast(`图片不能超过 ${IMAGE_LIMIT.MAX_MB}MB`)
    return false
  }
  const m = String(path).match(/\.([a-zA-Z0-9]+)(?:\?|$)/)
  if (m && IMAGE_LIMIT.EXT.indexOf(m[1].toLowerCase()) < 0) {
    toast(`仅支持 ${IMAGE_LIMIT.EXT.join(' / ')}`)
    return false
  }
  return true
}

async function run(path) {
  analyzing.value = true
  showLoading('AI 识别中…')
  try {
    result.value = await analyze(path)
    // 后端回传的图片地址是相对路径，做展示用（当前页面用的是本地临时图）
    if (result.value && result.value.imageUrl) {
      result.value.imageUrl = absoluteUrl(result.value.imageUrl)
    }
  } catch (e) {
    toast(e.message || '识别失败，请换一张照片试试')
    result.value = null
  } finally {
    analyzing.value = false
    hideLoading()
  }
}

/** 用户在追问里选定了一个候选场地，直接采信该结果 */
function pickCandidate(c) {
  const name = candidateName(c)
  result.value = { ...result.value, needConfirm: false, spaceName: name }
  toast(`已按「${name}」继续`)
}

/**
 * 带着识别到的场地去预约。
 * 把场地名拼进需求文本，让 Agent 能直接用上；不伪造 spaceId。
 */
function goVoice() {
  if (!result.value) return
  const name = displayName.value
  agentStore.request = `我想预约${name}`
  uni.navigateTo({ url: '/pages/voice/record' })
}
</script>

<style scoped>
.photo {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 100%;
}

.note {
  display: block;
  text-align: center;
  font-size: 22rpx;
  color: var(--t3);
  padding: 0 30rpx;
  line-height: 1.7;
}

.cands {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
  margin-top: 18rpx;
}

.cand {
  display: flex;
  align-items: center;
  gap: 14rpx;
  background: #fff;
  border: 1px solid var(--ai-line);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
}

.cn-name {
  flex: 1;
  font-size: 26rpx;
  color: var(--t1);
}

.cn-conf {
  font-size: 22rpx;
  color: var(--t3);
}

.app-cta-row .btn.ghost {
  flex: 1;
}

.app-cta-row .grow {
  flex: 1.8;
}
</style>
