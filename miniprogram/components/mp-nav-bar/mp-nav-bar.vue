<template>
  <view class="nb">
    <!-- 固定条：高度用 px 而不用 rpx。
         导航栏要和微信胶囊按钮对齐，胶囊尺寸是物理 px 不随屏宽缩放，
         若用 rpx 会在宽屏机型上把标题挤出胶囊区域 -->
    <view class="nb-fixed" :style="fixedStyle">
      <view class="nb-inner" :style="innerStyle">
        <text v-if="back" class="nb-back" @tap="goBack">‹</text>

        <!-- big 模式：M1 首页的大标题，左对齐不居中 -->
        <text v-if="big" class="nb-big">{{ title }}</text>
        <text v-else class="nb-title">{{ title }}</text>

        <text v-if="right" class="nb-right" @tap="onRight">{{ right }}</text>
      </view>
    </view>

    <!-- 占位块：把后续内容顶到导航栏下方。高度必须与固定条完全一致 -->
    <view class="nb-holder" :style="holderStyle"></view>
  </view>
</template>

<script setup>
/**
 * 自定义导航栏
 *
 * pages.json 全局 navigationStyle: "custom"，导航栏全部由本组件渲染。
 *
 * 用 px 而非 rpx 的原因：导航栏需要与微信右上角胶囊按钮垂直居中对齐，
 * 胶囊高度是物理像素、不随屏宽缩放；rpx 会在大屏机上把标题挤进胶囊区域。
 * 文字仍用 rpx，轻微缩放无碍。
 */
import { ref, computed } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  /** 右侧文字，如「普通用户」。不能放图标按钮——会被胶囊遮住 */
  right: { type: String, default: '' },
  /** 是否显示返回箭头，二级页传 true */
  back: { type: Boolean, default: false },
  /** M1 首页样式：大号左对齐标题，无返回 */
  big: { type: Boolean, default: false },
  bg: { type: String, default: '#ffffff' },
  border: { type: Boolean, default: true }
})

const emit = defineEmits(['right'])

const statusBarHeight = ref(20)
const navBarHeight = ref(44)
/** 右侧内边距：让 right 文字落在胶囊左侧，避免被遮 */
const rightGap = ref(12)

function measure() {
  let statusBar = 20
  let windowWidth = 375
  try {
    const sys = uni.getSystemInfoSync()
    if (sys) {
      if (sys.statusBarHeight) statusBar = sys.statusBarHeight
      if (sys.windowWidth) windowWidth = sys.windowWidth
    }
  } catch (e) {
    // 取不到系统信息就用默认值，不影响渲染
  }

  let navBar = 44
  let gap = 12
  if (typeof uni.getMenuButtonBoundingClientRect === 'function') {
    try {
      const rect = uni.getMenuButtonBoundingClientRect()
      if (rect && rect.height && rect.top >= statusBar) {
        // 胶囊上下留白 = rect.top - statusBar，两侧对称，故 ×2
        navBar = (rect.top - statusBar) * 2 + rect.height
      }
      if (rect && rect.left) {
        gap = windowWidth - rect.left
      }
    } catch (e) {
      // 非微信端（H5 / App）没有胶囊，用默认值
    }
  }

  statusBarHeight.value = statusBar
  navBarHeight.value = navBar
  rightGap.value = gap
}

measure()

const totalHeight = computed(() => statusBarHeight.value + navBarHeight.value)

const fixedStyle = computed(() => ({
  paddingTop: statusBarHeight.value + 'px',
  background: props.bg
}))

const innerStyle = computed(() => ({
  height: navBarHeight.value + 'px',
  paddingRight: rightGap.value + 'px',
  borderBottomWidth: props.border ? '1px' : '0px'
}))

const holderStyle = computed(() => ({
  height: totalHeight.value + 'px'
}))

function goBack() {
  const pages = getCurrentPages()
  if (pages && pages.length > 1) {
    uni.navigateBack()
  } else {
    // 从分享/扫码直接进二级页时没有上一页，回首页兜底
    uni.reLaunch({ url: '/pages/index/index' })
  }
}

function onRight() {
  emit('right')
}
</script>

<style scoped>
.nb-fixed {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
}

.nb-inner {
  display: flex;
  align-items: center;
  padding-left: 26rpx;
  border-bottom: 1px solid var(--bd-l, #ebeef5);
  position: relative;
}

.nb-back {
  font-size: 44rpx;
  line-height: 1;
  color: #7a8ba0;
  padding-right: 12rpx;
  margin-top: -6rpx;
}

/* 二级页标题：绝对居中，不受左右元素宽度影响 */
.nb-title {
  position: absolute;
  left: 50%;
  top: 0;
  height: 100%;
  display: flex;
  align-items: center;
  transform: translateX(-50%);
  font-size: 32rpx;
  font-weight: 600;
  color: var(--t1, #303133);
  max-width: 50%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 首页大标题 */
.nb-big {
  font-size: 34rpx;
  font-weight: 600;
  color: var(--t1, #303133);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  margin-right: 16rpx;
}

.nb-right {
  margin-left: auto;
  font-size: 24rpx;
  color: var(--t3, #909399);
  flex: none;
}
</style>
