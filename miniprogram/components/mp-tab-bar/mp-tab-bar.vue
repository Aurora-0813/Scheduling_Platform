<template>
  <view class="tb">
    <view class="tb-fixed">
      <view class="tb-inner">
        <view
          v-for="tab in tabs"
          :key="tab.path"
          class="tb-item"
          :class="{ on: tab.index === current }"
          hover-class="tb-on"
          :hover-stay-time="60"
          @tap="go(tab.index)"
        >
          <text class="tb-ic">{{ tab.icon }}</text>
          <text class="tb-lb">{{ tab.label }}</text>
        </view>
      </view>
    </view>

    <!-- 占位块：内容滚到底时不被固定条压住 -->
    <view class="tb-holder"></view>
  </view>
</template>

<script setup>
/**
 * 自定义底部导航
 *
 * 为什么不用微信原生 tabBar：原生 iconPath 只接受 PNG，无法使用 emoji，
 * 且选中态只能用两张图，无法做原型里的渐变+放大效果。改用组件 + reLaunch，
 * 顺带避免引入任何二进制图片资源。
 *
 * 代价：切换用 reLaunch 会重建页面栈（原生 tabBar 会保留各 tab 状态）。
 * 对本项目可接受——各 tab 页在 onShow 里重新拉数据，反而保证数据新鲜。
 */
import { computed } from 'vue'
import { TABS } from '@/utils/tabs.js'
import { canInspect } from '@/store/user.js'

const props = defineProps({
  /** 当前选中的 tab 下标，页面里传常量即可 */
  current: { type: Number, default: 0 }
})

/** 无巡检权限（普通用户）不显示「巡检」tab —— 口径见 store/user.js::canInspect */
const tabs = computed(() => TABS.filter((t) => t.label !== '巡检' || canInspect()))

function go(index) {
  if (index === props.current) return
  const tab = TABS[index]
  if (!tab) return
  uni.reLaunch({ url: tab.path })
}
</script>

<style scoped>
.tb-fixed {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 100;
  background: #fff;
  border-top: 1px solid var(--bd-l, var(--bd-l));
  /* 全面屏 Home 指示条留白：mini-program 的 WXSS 支持 env() */
  padding-bottom: constant(safe-area-inset-bottom);
  padding-bottom: env(safe-area-inset-bottom);
}

.tb-inner {
  display: flex;
  height: 116rpx;
}

.tb-holder {
  height: 116rpx;
  height: calc(116rpx + constant(safe-area-inset-bottom));
  height: calc(116rpx + env(safe-area-inset-bottom));
}

.tb-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s1);
}

.tb-ic {
  font-size: 38rpx;
  line-height: 1;
  opacity: 0.42;
  transition: all 0.2s;
}

.tb-lb {
  font-size: 21rpx;
  color: var(--t3, var(--t3));
  transition: all 0.2s;
}

.tb-item.on .tb-ic {
  opacity: 1;
  transform: scale(1.14) translateY(-2rpx);
}

.tb-item.on .tb-lb {
  color: var(--primary, var(--primary));
  font-weight: 600;
}

.tb-on {
  opacity: 0.7;
}
</style>
