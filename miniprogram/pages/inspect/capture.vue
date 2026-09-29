<template>
  <view class="app-page">
    <mp-nav-bar title="拍照巡检" back :right="spaceLabel" />

    <view class="app-body has-cta">
      <!-- 取景框：未拍照时是引导，拍完换成照片 -->
      <view class="imgbox" @tap="pick">
        <image v-if="photo" class="photo" :src="photo" mode="aspectFill" />
        <view v-else class="cam">
          <text class="big">📷</text>
          <text>点击拍照，或从相册选择</text>
        </view>
        <view v-if="photo" class="bbox on-photo">
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
        </view>
        <view v-if="analyzing" class="scanline"></view>
      </view>

      <!-- 相机 / 相册分开给按钮：合并的 action sheet 在开发者工具里常常只弹相册，
           分开后「拍照」是明确的 camera-only 调用，失败也会把原因说出来 -->
      <view class="pickrow">
        <view class="pbtn" hover-class="pbtn-on" :hover-stay-time="60" @tap="takePhoto">
          📷 拍照
        </view>
        <view class="pbtn" hover-class="pbtn-on" :hover-stay-time="60" @tap="pickAlbum">
          🖼 从相册选
        </view>
      </view>

      <!-- 空间选择：巡检要关联到具体场地，后端才能派单 -->
      <view class="mcard">
        <view class="mbrow pick" @tap="chooseSpace">
          <text class="k">巡检区域</text>
          <text class="v">{{ spaceLabel }}</text>
          <text class="ma">›</text>
        </view>
      </view>

      <!-- 识别结果 -->
      <view v-if="result" class="mcard">
        <view class="mtitle">
          <text>🤖 AI 识别结果</text>
          <text v-if="confidenceText" class="more">{{ confidenceText }}</text>
        </view>

        <view class="mbrow">
          <text class="k">设备状态</text>
          <text class="v">
            <text class="tag" :class="statusTag('device', result.deviceStatus, result.deviceStatusText)">
              {{ statusLabel('device', result.deviceStatus, result.deviceStatusText) }}
            </text>
          </text>
        </view>
        <view v-if="deviceName" class="mbrow">
          <text class="k">设备编号</text>
          <text class="v">{{ deviceName }}</text>
        </view>
        <view class="mbrow">
          <text class="k">关联空间</text>
          <text class="v">{{ spaceLabel }}</text>
        </view>
        <view v-if="result.repairSuggestion" class="mbrow">
          <text class="k">维修建议</text>
          <text class="v">{{ result.repairSuggestion }}</text>
        </view>
      </view>

      <!-- 巡检摘要 -->
      <view v-if="result && result.report" class="mcard">
        <view class="mtitle">📋 AI 巡检摘要</view>
        <text class="mtext">{{ result.report }}</text>
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
      >{{ analyzing ? 'AI 识别中…' : '拍一张开始巡检' }}</view>

      <view
        v-else
        class="btn warn block"
        hover-class="btn-on"
        :hover-stay-time="60"
        @tap="goTickets"
      >查看维修工单 #{{ result.ticketId }}</view>
    </view>
  </view>
</template>

<script setup>
/**
 * M5 拍照巡检
 *
 * 对应原型「小程序-5 拍照巡检 · 识别框」。
 *
 * 契约：POST /inspect/submit  multipart，字段名固定 file（+ 可选 spaceId）
 *       → { deviceStatus, report, repairSuggestion, ticketId }
 *
 * ⚠️ 工单是**后端在提交时自动创建**的（返回里带 ticketId），
 *   所以原型的「生成维修工单」按钮在这里不重复调用创建接口，
 *   只做「查看工单」的跳转。
 * ⚠️ inspectorId 由后端从 JWT 解析，前端不传（§5.1）。
 */
import { ref, computed } from 'vue'
import { onLoad, onUnload } from '@dcloudio/uni-app'
import { submit } from '@/api/inspect.js'
import { spaces as fetchSpaces } from '@/api/resources.js'
import { statusLabel, statusTag } from '@/utils/dict.js'
import { first, spaceName } from '@/utils/normalize.js'
import { IMAGE_LIMIT } from '@/config/index.js'
import { toast, showLoading, hideLoading, resetLoading } from '@/utils/toast.js'
import { TABS } from '@/utils/tabs.js'

const photo = ref('')
const result = ref(null)
const analyzing = ref(false)
const spaceList = ref([])
const spaceIndex = ref(-1)

const spaceLabel = computed(() => {
  if (spaceIndex.value < 0 || !spaceList.value.length) return '未选择'
  return spaceName(spaceList.value[spaceIndex.value]) || '未选择'
})

/** 后端契约里没有置信度字段，Mock 额外给了；有才显示 */
const confidenceText = computed(() => {
  const c = result.value ? result.value.confidence : null
  if (c === undefined || c === null || c === '') return ''
  const n = Number(c)
  if (isNaN(n)) return ''
  // 0.92 与 92 两种量纲都兼容
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `置信度 ${pct}%`
})

const deviceName = computed(() => {
  const r = result.value
  if (!r) return ''
  return r.deviceName || r.deviceCode || ''
})

onLoad(() => {
  loadSpaces()
})

// 页面销毁时把 loading 计数归零：万一有哪条路径没配平，残留的计数会让之后
// 每一次 show/hide 都错位 —— 微信侧会一直报「showLoading 与 hideLoading 必须配对使用」
onUnload(() => resetLoading())

async function loadSpaces() {
  try {
    const res = await fetchSpaces({ page: 1, pageSize: 50 })
    spaceList.value = res.list
    // 默认选中第一个；Mock 与本地兜底都按 id 升序给了 A 栋 3 楼展厅之外的场地，
    // 这里不假设顺序，仅作为默认值，用户可随时改
    if (spaceList.value.length) spaceIndex.value = 0
  } catch (e) {
    spaceList.value = []
  }
}

function chooseSpace() {
  if (!spaceList.value.length) {
    toast('场地列表加载失败，稍后再试')
    return
  }
  const names = spaceList.value.map((s) => spaceName(s) || '未命名场地')
  uni.showActionSheet({
    itemList: names,
    success: (res) => {
      spaceIndex.value = res.tapIndex
    },
    fail: () => {},
  })
}

function onPicked(path, size) {
  if (!validate(path, size)) return
  photo.value = path
  result.value = null
  analyze(path)
}

/**
 * 选图统一入口。
 * @param {string|string[]} source 'camera' | 'album' | ['camera','album']
 *
 * 两个坑：
 *  1. 原来 fail 回调是空的——用户点「拍照」没反应时页面毫无提示，
 *     看起来就像「摄像头点不开」。现在把失败原因说出来（主动取消不提示）。
 *  2. chooseMedia 在部分基础库 / 开发者工具版本上相机通道不可用，
 *     失败后退回 chooseImage 再试一次；还不行才提示。
 */
function chooseImage(source, onPickedCb) {
  const sourceType = Array.isArray(source) ? source : [source]
  let retried = false

  const onFail = (err) => {
    const msg = String((err && err.errMsg) || '')
    if (/cancel/i.test(msg)) return
    if (!retried) {
      retried = true
      chooseImageLegacy(sourceType, onPickedCb, onFail)
      return
    }
    toast(msg ? `打开失败：${msg}` : '打开失败，请重试')
  }

  if (typeof uni.chooseMedia === 'function') {
    uni.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType,
      sizeType: ['compressed'],
      camera: 'back',
      success: (res) => {
        const f = res.tempFiles && res.tempFiles[0]
        if (f) onPickedCb(f.tempFilePath, f.size)
      },
      fail: onFail,
    })
    return
  }

  chooseImageLegacy(sourceType, onPickedCb, onFail)
}

/** 退路：基础库 < 2.10.0 没有 chooseMedia，或相机通道不可用 */
function chooseImageLegacy(sourceType, onPickedCb, onFail) {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType,
    success: (res) => {
      const path = res.tempFilePaths && res.tempFilePaths[0]
      const file = res.tempFiles && res.tempFiles[0]
      if (path) onPickedCb(path, file ? file.size : 0)
    },
    fail: onFail,
  })
}

/** 取景框 / 主按钮：交给系统菜单让用户选拍照还是相册 */
function pick() {
  if (analyzing.value) return
  chooseImage(['camera', 'album'], onPicked)
}

/** 明确拍照 */
function takePhoto() {
  if (analyzing.value) return
  chooseImage('camera', onPicked)
}

/** 明确从相册选 */
function pickAlbum() {
  if (analyzing.value) return
  chooseImage('album', onPicked)
}

/**
 * 与后端 image.py 的限制保持一致。
 * 扩展名拿不到时不拦（小程序临时路径不一定带后缀），只拦体积。
 */
function validate(path, size) {
  if (size && size > IMAGE_LIMIT.MAX_MB * 1024 * 1024) {
    toast(`图片不能超过 ${IMAGE_LIMIT.MAX_MB}MB`)
    return false
  }
  const m = String(path).match(/\.([a-zA-Z0-9]+)(?:\?|$)/)
  if (m) {
    const ext = m[1].toLowerCase()
    if (IMAGE_LIMIT.EXT.indexOf(ext) < 0) {
      toast(`仅支持 ${IMAGE_LIMIT.EXT.join(' / ')}`)
      return false
    }
  }
  return true
}

async function analyze(path) {
  analyzing.value = true
  showLoading('AI 识别中…')
  try {
    // ⚠️ **2026-09-30 修：原先这里取的是 .id。**
    //
    // 后端 /resources/spaces 返回的主键字段是 **spaceId**，根本没有 id
    // （见 backend/app/api/resources.py 的 _space_out），所以这里恒为 undefined；
    // 而 api/inspect.js 在 spaceId 为 undefined 时**不会写进 formData**，
    // 后端 /inspect/submit 的 spaceId 又是必填 Form（required=["file","spaceId"]）
    // —— 于是**拍照巡检每一次都必然被参数校验拦下**。
    //
    // 之前一直没暴露，是因为 FALLBACK_TO_LOCAL 的兜底数据恰好同时给了 id 和 name，
    // 只有「后端离线走兜底」那一路能跑通。兜底已关（config/index.js），这条路必须修。
    // first(...) 同时容忍两种命名，兜底数据若将来复用也不会再踩。
    const spaceId =
      spaceIndex.value >= 0 && spaceList.value[spaceIndex.value]
        ? first(spaceList.value[spaceIndex.value].spaceId, spaceList.value[spaceIndex.value].id)
        : undefined
    result.value = await submit(path, spaceId)
  } catch (e) {
    toast(e.message || '识别失败，请换一张照片试试')
    result.value = null
  } finally {
    analyzing.value = false
    hideLoading()
  }
}

function goTickets() {
  uni.reLaunch({ url: TABS[2].path })
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

.pick {
  justify-content: space-between;
}

.ma {
  font-size: 34rpx;
  color: #c6ced9;
  flex: none;
  margin-left: 12rpx;
}

.note {
  display: block;
  text-align: center;
  font-size: 22rpx;
  color: var(--t3);
  padding: 0 30rpx;
  line-height: 1.7;
}

/* 拍照 / 相册 双按钮 */
.pickrow {
  display: flex;
  gap: 20rpx;
  margin-bottom: 22rpx;
}

.pbtn {
  flex: 1;
  height: 84rpx;
  line-height: 84rpx;
  text-align: center;
  font-size: 26rpx;
  color: var(--t1);
  background: #fff;
  border: 1px solid var(--bd-l);
  border-radius: 20rpx;
}

.pbtn-on {
  background: #f2f6fd;
}
</style>
