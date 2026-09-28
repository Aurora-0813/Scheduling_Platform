/**
 * 底部导航定义
 *
 * 单独抽出来是因为有三处必须保持一致：mp-tab-bar 的渲染、首页快捷入口跳转、
 * 二级页返回首页。写死在三处迟早会漂移。
 *
 * index 即页面传给 <mp-tab-bar :current="n"> 的值。
 */
export const TABS = [
  { index: 0, icon: '🏠', label: '首页', path: '/pages/index/index' },
  { index: 1, icon: '🗓', label: '预约', path: '/pages/order/list' },
  { index: 2, icon: '📷', label: '巡检', path: '/pages/inspect/index' },
  { index: 3, icon: '🔔', label: '消息', path: '/pages/message/list' },
  { index: 4, icon: '👤', label: '我的', path: '/pages/mine/index' }
]

/** 按 index 取 tab，越界返回 undefined */
export function tabAt(index) {
  for (let i = 0; i < TABS.length; i += 1) {
    if (TABS[i].index === index) return TABS[i]
  }
  return undefined
}

export default { TABS, tabAt }
