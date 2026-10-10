/**
 * 「未完成动作」记录 —— 会话中断后的恢复凭据
 *
 * ⚠️ 为什么需要它（2026-10-09 实测故障）：
 *
 *   `POST /agent/schedule` 要跑 **25~105 秒**（真模型多轮 Tool 调用），
 *   而 accessToken 只有 30 分钟。令牌若在这期间过期，会出现最难排查的一类故障：
 *
 *     1. 调度**成功**返回，订单已按「待确认」落库（**后端行为正确**）
 *     2. 紧接着的前端调用 401 → 续期也失败 → 用户被踢到登录页
 *     3. 用户重新登录后**上下文全丢**：不知道自己刚才那件事到底成没成
 *
 *   最坏的后果是用户重跑一次 → 多出一张重复预约。
 *
 *   所以这里记下「哪个动作、动到哪个 id、结果如何」，让中断后的恢复**有据可依**，
 *   并且由**用户显式决定**是否继续 —— 绝不自动重放任何有副作用的请求。
 *
 * ⚠️ 用 sessionStorage 而不是 localStorage：它只在**当前标签页会话**内有意义，
 *    关掉标签页就该忘掉；localStorage 会让它跨天复活（本项目在
 *    `agentWorkbench.js` 上踩过「清空后重启又回来」的坑）。
 *
 * ⚠️ 与 `agentWorkbench.js` 的 `PERSIST_KEY` **刻意分开**：
 *    那边持久化的是「调度结果快照」，这边是「中断事件」。混在一个键里，
 *    「历史结果」与「被打断的待办」就分不清了 —— 而恢复卡**只应对后者弹**。
 */

const KEY = 'dsh.pendingAction'

/**
 * @typedef {object} PendingAction
 * @property {string} kind       动作类型，如 'agent.schedule'
 * @property {string} label      给用户看的一句话，如「AI 调度」
 * @property {number|null} orderId 若后端已建单，这里就是单号（恢复的关键）
 * @property {number} at         发生时刻（ms）
 * @property {string} reason     为什么会中断
 */

/** 记住一个未完成动作。任何异常都吞掉：记不下不该影响主流程。 */
export function rememberPendingAction(action) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...action, at: Date.now() }))
  } catch {
    /* 忽略 */
  }
}

/** 读取未完成动作；没有 / 坏了都返回 null，绝不抛。 */
export function getPendingAction() {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || !parsed.kind) return null
    return parsed
  } catch {
    return null
  }
}

/** 用户处理完（查看/确认/忽略）后清掉，避免反复弹卡。 */
export function clearPendingAction() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* 忽略 */
  }
}

/**
 * 「正在进行的持久化动作」的短时标记。
 *
 * 用途：请求层拿到 401 时，需要知道**当前是否有一个已经产生了副作用的动作在跑**，
 * 才决定要不要写「未完成动作」记录。这个标记是**进程内**的（不持久化）——
 * 它只在「请求在途」这段时间里有意义，页面一刷新就无意义了。
 *
 * 为什么不用 Pinia：请求层（`utils/request.js`）不该依赖任何 store，
 * 否则会引入 store → api → request → store 的循环依赖。
 * 用一个模块级变量 + 显式定义作用域最省事，也不产生耦合。
 */
let durableOperation = null

/**
 * 标记「接下来这段操作有副作用，若中途会话失效需要记下来」。
 * 返回一个**清理函数**，务必在 finally 里调用。
 *
 * @param {{kind: string, label: string, orderId?: number|null}} info
 * @returns {() => void} 清理函数
 */
export function beginDurableOperation(info) {
  durableOperation = { ...info }
  return () => {
    durableOperation = null
  }
}

/** 供请求层查询：当前是否有在途的持久化动作 */
export function currentDurableOperation() {
  return durableOperation
}

/** 把「在途动作」升级为「未完成动作」（请求层在会话失效时调用） */
export function stashDurableOperationAsPending(reason) {
  if (!durableOperation) return null
  const action = {
    kind: durableOperation.kind,
    label: durableOperation.label,
    orderId: durableOperation.orderId ?? null,
    reason: reason || '会话已过期',
  }
  rememberPendingAction(action)
  return action
}

/**
 * 用后端刚返回的结果补全在途动作的 `orderId`。
 *
 * 场景：`/agent/schedule` 返回成功、带 `orderId`，但**同一时刻**另有请求 401
 * 把用户踢出去 —— 这时「在途动作」已知道单号，恢复卡就能直接给出单号，
 * 而不是含糊地说「你可能成功过」。
 */
export function attachOrderIdToDurableOperation(orderId) {
  if (durableOperation && orderId != null) {
    durableOperation.orderId = orderId
  }
}
