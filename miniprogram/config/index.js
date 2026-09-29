/**
 * 全局配置
 *
 * 后端架构现状（2026-09-30 复核）：
 *   **本文件里列到的接口全部已落地为真实接口**，不再有「只有 mock 占位」的模块。
 *   `/api/v1/mock/*` 仍存在（后端 DEBUG=true 时），但那是给后端自测用的，
 *   小程序业务路径**一律走真实接口**。
 */

/** 后端地址，按调试场景三选一：
 *  1) 微信开发者工具：http://127.0.0.1:8000（需在「详情 → 本地设置」勾选
 *     「不校验合法域名、web-view…」）
 *  2) 真机预览：电脑局域网 IP，如 http://192.168.1.10:8000，手机与电脑同一 WiFi
 *  3) 正式上线：必须是 https 域名，并在小程序后台配置 request / uploadFile 合法域名
 */
export const BASE_URL = 'http://127.0.0.1:8000'

/** 请求路径前缀 */
export const API_PREFIX = '/api/v1'
export const MOCK_PREFIX = '/api/v1/mock'

/**
 * 数据通道模式
 * 'mock' → 命中团队后端的 /api/v1/mock/*（需后端 DEBUG=true）
 * 'real' → 命中真实接口 /api/v1/*
 */
export const API_MODE = 'real'

/**
 * 本地兜底：网络失败 / 服务端 5xx 时，回落到 `api/mock/local.js` 的内置数据。
 *
 * ⚠️ **2026-09-30 置为 false（原为 true）。**
 *
 * 原来的用途是「答辩现场防翻车」（开发流程.md §13.1）。但实测下来它的代价大于收益：
 *
 *   1. **它把故障藏起来**。后端挂了、隧道断了、大模型 503 —— 页面不但不报错，
 *      反而显示一份**编造的数据**，且没有任何标记。演示时看到的是「一切都好」。
 *   2. **它会让假方案变成真订单**。`/agent/schedule` 的兜底数据**没有 orderId**
 *      （真实响应有），于是 `pages/agent/plan.vue` 判定「后端没建单」→ 转而调
 *      `POST /orders/create`，把**编造出来的场地/时段**真的写进了库。
 *   3. **它掩盖了真实契约错误**。例如场地列表的主键真实字段是 `spaceId`，
 *      而兜底数据给的是 `id` —— 页面写 `.id` 在兜底态下能跑通、在真实态下必失败，
 *      于是错误被一路掩盖到联调最后一天。
 *
 * 需要临时启用（比如演示前想先录一遍界面）时，把这里改回 `true` 即可，
 * `api/mock/local.js` 仍然保留着。
 */
export const FALLBACK_TO_LOCAL = false

/**
 * 请求超时（毫秒）。
 *
 * ⚠️ **2026-09-30 由 15000 提到 240000。**
 *
 * 15 秒对真实后端**远远不够**：
 *   · `POST /agent/schedule` 实测 **39~105 秒**（真模型多轮 Tool 调用）
 *   · `GET /dashboard/report` 实测 27~52 秒
 * 15 秒必然先超时，而后端其实还在正常跑、稍后也会正常返回。
 *
 * 取 240 秒 = 后端上限 `AGENT_TIMEOUT=180` + 60 秒余量；
 * **前端超时必须大于后端上限**，否则前端会在后端返回前先断开。
 *
 * 个别接口可用 `api/request.js` 的 `options.timeout` 单独调整（上传走双倍）。
 */
export const REQUEST_TIMEOUT = 240000

/** 小程序本地存储键 */
export const STORAGE_KEYS = {
  ACCESS: 'sp_access_token',
  REFRESH: 'sp_refresh_token',
}

/**
 * 图片上传限制。
 *
 * ⚠️ **2026-09-30 去掉 bmp。** 后端 `image_storage._MIME_TO_EXT` 只认
 * jpeg / png / webp 三种，bmp **上传必被 41001 拒绝**（文案就是
 * 「请上传 JPG / PNG / WEBP 格式的图片」）。原先这里列了 bmp，等于前端放行、
 * 后端必拒 —— 用户按提示选了 bmp 只会拿到一个莫名其妙的报错。
 * 5MB 与后端 `IMAGE_MAX_SIZE_MB` 一致。
 */
export const IMAGE_LIMIT = {
  MAX_MB: 5,
  EXT: ['jpg', 'jpeg', 'png', 'webp'],
}

/** 录音参数（已与后端 ASR 对齐，勿改） */
export const RECORD_OPTIONS = {
  duration: 60000,
  sampleRate: 16000,
  numberOfChannels: 1,
  encodeBitRate: 48000,
  format: 'wav',
}