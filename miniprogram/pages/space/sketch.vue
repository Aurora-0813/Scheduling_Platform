<!--
  骨架与「拍照识场」（pages/space/recognize.vue）完全对齐（2026-10-14 改）。

  ⚠️ 原先本页用的是**另一套自造结构**：

      <view class="page">          ← 只有 padding，没有 min-height/flex
        <view class="card"> …      ← 自造的 card / card-head / upload / kv / tags
        <view class="acts"> …      ← 普通块级按钮，跟着内容走
        <text class="foot"> …

  两个后果：
    1. **底部按钮不固定**，内容长了就被顶出屏幕；而且没有
       env(safe-area-inset-bottom)，全面屏的 Home 指示条会压住按钮；
    2. 卡片圆角/内边距/字号与「拍照识场」不是同一套值，两个页面来回切
       看得出来不一样 —— 它们本来就是同一个流程的两个模式。

  现在统一用 theme.css 的布局骨架：
      .app-page（flex column + min-height:100vh）
        mp-nav-bar（占位块自己撑出导航栏高度）
        .app-body.has-cta（flex:1 + padding-bottom:200rpx 给固定按钮留位）
        .app-cta（position:fixed + 安全区内边距）
  卡片改用全局 .mcard / .mtitle / .mbrow，上传框复用 .imgbox —— 与识别页同一个外观。
-->
<template>
  <view class="app-page">
    <!-- 标题与 pages.json 的 navigationBarTitleText 保持一致（同「拍照识场」页的做法） -->
    <mp-nav-bar title="草图预约" back />

    <view class="app-body has-cta">
      <!-- 输入方式模式条：与「拍照识场」共用的样式（结构也一致） -->
      <view class="modebar">
        <view class="mode" hover-class="btn-on" :hover-stay-time="60" @tap="goRecognize">📷 拍照识场</view>
        <view class="mode on">✍️ 手绘草图</view>
      </view>

      <!--
        上传框复用 .imgbox：它已经定义了 360rpx 高度、圆角、虚线边框与
        居中的 .cam 提示块，正是识别页拍照区那一块 —— 两个模式的入口观感因此一致。
      -->
      <view v-if="!sketch" class="imgbox" @tap="chooseSketch">
        <view class="cam">
          <text class="big">✍️</text>
          <text>上传或拍摄一张手绘布局草图</text>
          <text class="cam-sub">AI 自动识别人数、布局与所需设备</text>
        </view>
      </view>

      <view v-else class="mcard">
        <view class="mtitle">
          <text>识别结果</text>
          <text class="more" @tap="chooseSketch">重新上传</text>
        </view>

        <image v-if="sketchLocalPath" :src="sketchLocalPath" mode="aspectFit" class="sk-img" />

        <view class="mbrow">
          <text class="k">布局</text>
          <text class="v">{{ sketch.layout || '未识别出布局' }}</text>
        </view>
        <view class="mbrow">
          <text class="k">预估人数</text>
          <text class="v">{{ sketch.capacity ? sketch.capacity + ' 人' : '未识别出' }}</text>
        </view>
        <view class="mbrow">
          <text class="k">场地类型</text>
          <text class="v">{{ SPACE_TYPE_TEXT[sketch.spaceType] || '未识别出' }}</text>
        </view>

        <view v-if="requirements.length" class="tags">
          <text v-for="(r, i) in requirements" :key="i" class="tag">{{ r }}</text>
        </view>
      </view>

      <!--
        置信度不足时的追问。沿用识别页的 .witem.blue —— 那里也是「需要你确认一下」，
        两页对同一件事用同一种提示样式。
        ⚠️ 原先这里是自造的 .warn-line（橙色 warning 底），但文案其实是**追问**而不是警告，
        用 warning 色会让人以为出错了。
      -->
      <view v-if="sketch && sketch.needConfirm && sketch.question" class="witem blue">
        <text class="wt">需要你确认一下</text>
        <text class="wp">{{ sketch.question }}</text>
      </view>

      <text class="note">
        草图只能看出人数和布局 —— 具体哪间场地、哪些设备、什么时间，
        在下一步补齐（人数和类型会带过去，可改）。
      </text>
    </view>

    <!-- 底部固定操作区：与识别页一样贴在屏幕底部，全面屏自动避开 Home 指示条 -->
    <view class="app-cta">
      <view class="app-cta-row">
        <view
          v-if="sketch"
          class="btn ai block grow"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="goConfirm"
        >下一步：选时间 / 场地 / 设备 →</view>
        <view
          v-else
          class="btn ai block grow"
          hover-class="btn-on"
          :hover-stay-time="60"
          @tap="chooseSketch"
        >上传草图</view>
      </view>
    </view>
  </view>
</template>

<script setup>
/**
 * 手绘草图识别（2026-10-13 改版）
 *
 * 本页现在**只负责识别**：上传 → /image/sketch → 展示识别结果。
 * 「选时间 / 选场地 / 选设备 / 下单」统一收在 pages/reserve/confirm.vue ——
 * 拍照/语音/草图三个入口共用同一套选择界面，避免三处各写一遍。
 *
 * 为什么设备不在这里选：手绘草图通常只画布局和座位，**画不出设备台账**，
 * 所以识别结果里刻意不带 deviceHints，只把图上的文字标注（「投影」「音响」）
 * 翻译成设备**类型**带过去，由用户在确认页勾选具体设备（可改）。
 */
import { ref } from 'vue'
import { sketch as recognizeSketch } from '@/api/image.js'
import { setPrefill } from '@/store/reservePrefill.js'
import { toast } from '@/utils/toast.js'

const SPACE_TYPE_TEXT = { 1: '会议室', 2: '展厅', 3: '多功能厅', 4: '户外场地' }

/** 草图需求关键词 → 台账设备类型（只用于在确认页预勾选） */
const REQ_TO_DEVICE = [
  { keys: ['投影'], type: '投影仪' },
  { keys: ['音响', '扩音', '话筒'], type: '音响' },
  { keys: ['显示屏', '大屏', '屏幕', 'LED'], type: 'LED显示屏' },
  { keys: ['直播'], type: '直播设备' },
  { keys: ['无人机', '航拍'], type: '无人机' },
]

const sketch = ref(null)
const sketchLocalPath = ref('')
const requirements = ref([])

function goRecognize() {
  uni.redirectTo({ url: '/pages/space/recognize' })
}

function chooseSketch() {
  uni.chooseImage({
    count: 1,
    sizeType: ['compressed'],
    sourceType: ['album', 'camera'],
    success: async (res) => {
      const path = (res.tempFilePaths || [])[0]
      if (!path) return
      sketchLocalPath.value = path
      uni.showLoading({ title: 'AI 识别中…', mask: true })
      try {
        const data = (await recognizeSketch(path)) || {}
        sketch.value = data
        requirements.value = data.requirements || []
      } catch (e) {
        sketch.value = null
        requirements.value = []
        toast((e && e.message) || '识别失败，请换一张草图')
      } finally {
        uni.hideLoading()
      }
    },
  })
}

/** 图上文字标注 → 设备类型（去重） */
function deviceTypesFromRequirements(reqs) {
  const hit = []
  ;(reqs || []).forEach((r) => {
    REQ_TO_DEVICE.forEach((m) => {
      if (m.keys.some((k) => String(r).indexOf(k) >= 0) && hit.indexOf(m.type) < 0) hit.push(m.type)
    })
  })
  return hit
}

function goConfirm() {
  const s = sketch.value || {}
  const types = deviceTypesFromRequirements(requirements.value)
  const cap = s.capacity || null
  setPrefill({
    source: 'sketch',
    sourceLabel: '手绘草图',
    capacity: cap,
    spaceType: s.spaceType || 0,
    deviceTypes: types,
    text:
      '手绘草图：' +
      (s.layout || '布局未识别') +
      (cap ? ' · ' + cap + ' 人' : '') +
      (types.length ? ' · 需要 ' + types.join('、') : ''),
    // 交给 Agent 时也带上，免得它再从一句话里重新猜
    imageContext: {
      source: 'sketch',
      capacity: cap,
      spaceType: s.spaceType || null,
      layout: s.layout || '',
      requirements: requirements.value,
    },
  })
  uni.navigateTo({ url: '/pages/reserve/confirm' })
}
</script>

<style scoped>
/*
 * 本页样式只剩四小块（2026-10-14 精简）。
 *
 * ⚠️ 原先这里有 10 个自造类：.page / .card / .card-head / .card-title / .link /
 *    .upload / .up-ic / .up-t / .up-s / .kv / .warn-line / .acts / .foot。
 *    它们要么和全局类重复（.card ≈ .mcard），要么在换骨架后已无人引用。
 *    留着只会让两个「同一流程的模式页」继续长得不一样 —— 全部删掉，
 *    改用 theme.css 的 .app-page / .app-body / .app-cta / .mcard / .mbrow /
 *    .imgbox / .witem，与「拍照识场」完全同源。
 */

/* ---- 输入方式模式条 ----
 * 与 pages/space/recognize.vue 的这段**逐值相同**。
 * 两个页面各写一份是现状（都是 scoped，互相看不见），保持一致比抽公共类更稳：
 * 抽出去要动两个页面的模板，收益只是少 20 行，风险不成比例。
 * 改任一处时记得同步另一处。
 */
.modebar {
  display: flex;
  gap: var(--s2);
  margin-bottom: 22rpx;
}

.modebar .mode {
  flex: 1;
  text-align: center;
  font-size: 27rpx;
  padding: 18rpx 0;
  border-radius: var(--r-pill);
  color: var(--t2);
  background: var(--bg-hover);
  border: 1px solid var(--bd-l);
}

.modebar .mode.on {
  color: #fff;
  background: var(--primary-h);
  border-color: var(--primary-h);
  font-weight: 600;
}

/* ---- 识别结果卡里的两处补充 ----
 * 全局 .mbrow 是「标签在左、值紧随其后」，而本页三行是**键右对齐**的键值对，
 * 所以只需补 flex 排布；字号/颜色/分隔线仍沿用 .mbrow 自己的定义，不另起一套。
 */
.mbrow .k {
  flex-shrink: 0;
  width: 150rpx;
  color: var(--t3);
}

.mbrow .v {
  flex: 1;
  text-align: right;
  color: var(--t1);
}

/* ---- 上传的草图预览 ----
 * 固定 420rpx 高 + aspectFit：草图多为横长或竖长，用 widthFix 会把卡片
 * 撑得非常高（原先页面「超出」的原因之一），固定高度则不随图片比例变化。
 */
.sk-img {
  width: 100%;
  height: 420rpx;
  border-radius: var(--r-sm);
  background: var(--bg-hover);
  margin-bottom: 18rpx;
}

/* ---- 识别出的需求标签 ---- */
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: 18rpx;
}

.tag {
  font-size: 22rpx;
  color: var(--primary-h);
  background: var(--primary-bg);
  border-radius: var(--r-xs);
  padding: 6rpx 14rpx;
}

/* ---- 底部说明 ----
 * 全局没有 .note（上一个版本的 scoped 里叫 .foot），这里补上，
 * 值与识别页的 .note 一致：居中、22rpx、t3。
 */
.note {
  display: block;
  margin-top: 4rpx;
  padding: 0 20rpx;
  font-size: 22rpx;
  color: var(--t3);
  line-height: 1.7;
  text-align: center;
}

/* 上传框里那行小字（.imgbox .cam 的子元素，全局未定义） */
.imgbox .cam .cam-sub {
  font-size: 22rpx;
  color: var(--t3);
  margin-top: 8rpx;
}
</style>
