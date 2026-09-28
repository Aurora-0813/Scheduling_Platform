/**
 * 轻提示 / 加载 / 确认弹窗的统一封装
 * 对应开发流程.md §4.3「统一异常处理：失败均设置友好降级提示」
 */

export function toast(title, duration = 2000) {
  uni.showToast({ title: String(title || '操作失败'), icon: 'none', duration })
}

export function toastOk(title = '操作成功') {
  uni.showToast({ title, icon: 'success', duration: 1500 })
}

let loadingDepth = 0

/** 支持嵌套调用，避免内层 hideLoading 提前关掉外层的 loading */
export function showLoading(title = '加载中…') {
  loadingDepth += 1
  uni.showLoading({ title, mask: true })
}

export function hideLoading() {
  if (loadingDepth > 0) loadingDepth -= 1
  if (loadingDepth === 0) uni.hideLoading()
}

/**
 * Promise 化的 uni.showModal，返回用户是否点了确定。
 *
 * 两种调用形式都支持：
 *   confirm('要取消吗？', '提示', '确定')
 *   confirm({ content: '要取消吗？', confirmText: '确定取消', confirmColor: '#F56C6C' })
 * 后者用于破坏性操作——把确定键标红，减少误触。
 */
export function confirm(content, title = '提示', confirmText = '确定') {
  const opts =
    content !== null && typeof content === 'object'
      ? content
      : { content, title, confirmText }

  return new Promise((resolve) => {
    uni.showModal({
      title: opts.title || '提示',
      content: opts.content || '',
      confirmText: opts.confirmText || '确定',
      cancelText: opts.cancelText || '取消',
      confirmColor: opts.confirmColor || '#409EFF',
      success: (res) => resolve(!!res.confirm),
      fail: () => resolve(false),
    })
  })
}
