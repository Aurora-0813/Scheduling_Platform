/**
 * 全局配置
 *
 * 后端架构现状（2026-09 核对）：
 *   - 真实接口已落地：auth / voice / image / monitor / health
 *   - 其余模块（orders / resources / agent / inspect / tickets / messages …）
 *     仅在 DEBUG=true 时以 /api/v1/mock/* 形式提供，出参与真实接口同构
 *
 * 因此 API_MODE 默认走 mock 前缀，等模块落地后改成 'real' 即可，
 * 各 api 模块与页面代码一行都不用动。
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
export const API_MODE = 'mock'

/**
 * 本地兜底：网络失败 / 服务端 5xx 时，回落到 api/mock/local.js 的内置数据。
 * 用于答辩现场防翻车（对应开发流程.md §13.1 演示应急预案）。
 * 注意：业务错误（如 40001 参数校验失败）不会触发兜底，只有连不上才兜。
 */
export const FALLBACK_TO_LOCAL = true

/** 请求超时（毫秒） */
export const REQUEST_TIMEOUT = 15000

/** 小程序本地存储键 */
export const STORAGE_KEYS = {
  ACCESS: 'sp_access_token',
  REFRESH: 'sp_refresh_token',
}

/** 图片上传限制（与后端 image.py 一致：≤5MB，仅这四种格式） */
export const IMAGE_LIMIT = {
  MAX_MB: 5,
  EXT: ['jpg', 'jpeg', 'png', 'webp', 'bmp'],
}

/** 录音参数（已与后端 ASR 对齐，勿改） */
export const RECORD_OPTIONS = {
  duration: 60000,
  sampleRate: 16000,
  numberOfChannels: 1,
  encodeBitRate: 48000,
  format: 'wav',
}
