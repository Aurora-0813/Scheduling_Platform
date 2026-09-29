/**
 * 轻提示 / 加载 / 确认弹窗的统一封装
 * 对应开发流程.md §4.3「统一异常处理：失败均设置友好降级提示」
 *
 * ⚠️ 2026-09-30 修：开发者工具一直在打印
 *    「请注意 showLoading 与 hideLoading 必须配对使用」
 *
 * 根因是**微信里 showLoading / hideLoading / showToast 共用同一个弹窗**，
 * 而原封装没有把这层约束兜住，有四处会与微信侧失配：
 *
 *   1. `hideLoading()` 在「本来就没有 loading」时也会真调一次 `uni.hideLoading()`
 *      —— 多调一次 hide 本身就是一次不配对。原写法：
 *          if (loadingDepth > 0) loadingDepth -= 1
 *          if (loadingDepth === 0) uni.hideLoading()   // 深度本来就是 0 时照样调
 *   2. `showLoading()` 每次都真调 `uni.showLoading()`。loading 是**单例弹窗**，
 *      计数已 >0 时再 show 一次同样不配对。
 *   3. `showToast` 会**顶掉** loading，之后再 `hideLoading()` 就找不到弹窗了。
 *      典型写法 `showLoading() → toastOk() → finally { hideLoading() }` 必踩。
 *   4. 计数是模块级单例，**热重载**（开发者工具自动热重载）或页面被销毁后
 *      可能与微信侧的真实状态失配，此后每一次 show/hide 都是错位的。
 *
 * 现在用一个显式的 `loadingVisible` 记录「微信侧到底有没有弹窗」，
 * 所有出口都只在**真的有一个弹窗**时才调 `uni.hideLoading()`。
 */

/** 当前 loading 的嵌套深度（>0 表示逻辑上还有人在等） */
let loadingDepth = 0
/** 微信侧**实际**是否正显示着 loading。与 depth 分开维护，才不会各说各话。 */
let loadingVisible = false

export function toast(title, duration = 2000) {
  // showToast 与 showLoading 共用同一个弹窗：先把 loading 收掉，
  // 否则调用方 finally 里的 hideLoading() 会找不到那个弹窗
  dropLoading()
  uni.showToast({ title: String(title || '操作失败'), icon: 'none', duration })
}

export function toastOk(title = '操作成功') {
  dropLoading()
  uni.showToast({ title, icon: 'success', duration: 1500 })
}

/**
 * 显示 loading。支持嵌套：内层不会重复弹，也不会提前关掉外层的。
 *
 * 注意**不重复调用 `uni.showLoading`** —— 它是单例弹窗，
 * 重复调用既不会换标题，还会被开发者工具记为一次不配对。
 * 所以嵌套时后进来的标题会被忽略（微信本来就不支持更新标题）。
 */
export function showLoading(title = '加载中…') {
  loadingDepth += 1
  if (loadingVisible) return
  loadingVisible = true
  uni.showLoading({ title, mask: true })
}

/** 关闭一层 loading。**计数为 0 时直接返回**，绝不乱调 `uni.hideLoading()`。 */
export function hideLoading() {
  if (loadingDepth === 0) return
  loadingDepth -= 1
  if (loadingDepth > 0) return
  dropLoading()
}

/**
 * 把计数与微信侧状态一起归零。
 *
 * 用在「上下文已经变了」的场合 —— 页面 `onUnload`、热重载 —— 否则上面第 4 条
 * 那种残留计数会让之后每一次 show/hide 都错位。
 */
export function resetLoading() {
  loadingDepth = 0
  dropLoading()
}

/**
 * 内部使用：收掉当前这个弹窗。
 *
 * **只动 `loadingVisible`，不动 `loadingDepth`** —— 深度归调用方自己管。
 * 这样 `toast()` 抢走弹窗之后，调用方 `finally` 里那次 `hideLoading()`
 * 仍能正确地把深度减到 0，只是不会再重复调一次 `uni.hideLoading()`。
 */
function dropLoading() {
  if (!loadingVisible) return
  loadingVisible = false
  uni.hideLoading()
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
