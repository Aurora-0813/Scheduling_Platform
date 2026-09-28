<template>
  <view class="empty">
    <text class="icon">{{ icon }}</text>
    <text class="txt">{{ text }}</text>
    <view
      v-if="actionText"
      class="act"
      hover-class="act-on"
      :hover-stay-time="60"
      @tap="$emit('action')"
    >{{ actionText }}</view>
  </view>
</template>

<script setup>
/**
 * 空状态 / 错误状态占位
 *
 * 三种用途共用一套视觉：列表为空、加载失败、未登录。
 * 图标一律用 emoji，避免引入图片资源。
 *
 * ⚠️ 样式必须写全（不能依赖 theme.css 的全局类）：
 * 微信自定义组件默认 styleIsolation: 'isolated'，app.wxss 里的 **class 选择器
 * 不会作用到组件内部**（只有标签选择器会穿透）。CSS 自定义属性是继承属性，
 * 所以 var(--primary) 这类变量仍可用——本文件用的是带兜底值的写法。
 */
defineProps({
  icon: { type: String, default: '📭' },
  text: { type: String, default: '暂无数据' },
  /** 传了才渲染操作按钮 */
  actionText: { type: String, default: '' }
})

defineEmits(['action'])
</script>

<style scoped>
.empty {
  padding: 120rpx 40rpx;
  text-align: center;
}

.icon {
  font-size: 90rpx;
  opacity: 0.35;
  display: block;
  margin-bottom: 24rpx;
}

.txt {
  font-size: 26rpx;
  color: var(--t3, #909399);
  line-height: 1.7;
  display: block;
  margin-bottom: 28rpx;
}

.act {
  display: inline-block;
  padding: 16rpx 44rpx;
  border-radius: 12rpx;
  font-size: 25rpx;
  color: var(--t2, #606266);
  background: #fff;
  border: 1px solid var(--bd, #dcdfe6);
}

.act-on {
  opacity: 0.82;
}
</style>
