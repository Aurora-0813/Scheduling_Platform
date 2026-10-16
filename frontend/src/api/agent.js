import { bizHttp } from '@/utils/request'

/**
 * 核心调度 Agent —— 与「调度模式开关」相关的接口（2026-10-13 新增）。
 *
 * ## 为什么单开一个文件，而不是继续往 `api/monitor.js` 里塞
 *
 * `monitor.js` 里的 `agentSchedule` 是**模块 4 的调度入口**，和「大模型调用统计」
 * （`GET /monitor/agent`）混在一个文件里，是因为两者都由监控页引用。
 * 而下面这三个接口服务的是**另一件事**：让用户与管理员在页面上决定
 * 「这一轮调度怎么跑」。把它们继续塞进 monitor.js，会让「统计」和「开关」
 * 两件事的调用方互相牵扯，改一个动另一个。
 *
 * ## 三条路由与三个开关的关系
 *
 *   POST /agent/parse   —— 把自然语言解析成**可编辑条件 + 推荐**，**不建单**
 *   GET  /agent/mode    —— 读当前开关（进页面读一次）
 *   PUT  /agent/mode    —— 切开关（`user:update` 权限，系统级）
 *
 * ⚠️ 开关是**后端全局**的（落盘 `backend/runtime_flags.json`），不是浏览器本地的。
 * 也就是说管理员切一次，所有用户、以及小程序端都会跟着变 —— 这正是它的设计目的
 * （演示前改一下，不必重新打包 APK，见 `backend/app/core/flags.py`）。
 * 所以按钮旁边必须把这件事写出来，不能让它看起来像个「我的偏好设置」。
 */

/**
 * 把自然语言需求解析成条件 + 推荐。
 *
 * **没有副作用**：不锁资源、不建单，可以反复调用。
 * 返回 `{ conditions, recommend, confidence, latencyMs }`，
 * 其中 `conditions.missing[]` 是模型自报的「你没说、我按什么默认值处理的」。
 *
 * 耗时随后端 `aiRecommend` 开关变化：AI 推荐约 32 秒，规则推荐约 10~15 秒。
 * 因此调用方**必须**自己给出等待反馈 —— 这里的按钮是有加载态的，见 AgentWorkbench。
 */
export function agentParse(data = {}) {
  return bizHttp.post('/agent/parse', {
    text: data.text || '',
    imageContext: data.imageContext || {},
  })
}

/**
 * 读当前调度模式开关。
 *
 * `{ deepMode, flags: { deepMode, aiRecommend } }`。
 * 刻意走**真实**路由且不挂权限（后端 `GET /agent/mode` 对所有登录用户开放）——
 * 普通用户也该看到「当前是快速模式还是深度思考」，否则他会以为慢是系统卡了。
 */
export function getAgentMode() {
  return bizHttp.get('/agent/mode')
}

/**
 * 切开关。两个都可单独切，不传的那个保持原样。
 *
 * ⚠️ 需要 `user:update` 权限（后端 `require_permission(Permission.USER_UPDATE)`）——
 * 它是**系统级**开关。前端在按钮上做了权限判断（见 AgentWorkbench 的 canSwitchMode），
 * 但那只是「不显示点不了的按钮」；真正的准入在后端，普通用户直接 curl 也会被 403。
 *
 * @param {{ deepMode?: boolean, aiRecommend?: boolean }} data
 */
export function setAgentMode(data = {}) {
  const payload = {}
  if (data.deepMode !== undefined) payload.deepMode = data.deepMode
  if (data.aiRecommend !== undefined) payload.aiRecommend = data.aiRecommend
  // 开关的**回显就是唯一证据**：请求发出去了但值没变，用户必须看得出来。
  // 后端把结果和 message（「深度模式已开启」）一起回，所以这里取回整包。
  return bizHttp.put('/agent/mode', payload, { passMessage: true })
}

export default { agentParse, getAgentMode, setAgentMode }
