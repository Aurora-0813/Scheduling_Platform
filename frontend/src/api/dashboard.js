import { bizHttp } from '@/utils/request'

// 模块 8：AI 数据洞察面板
// GET /dashboard/stats 面板统计
export function getDashboardStats() {
  return bizHttp.get('/dashboard/stats')
}

// GET /dashboard/report 洞察报告
//
// ⚠️ **显式放宽到 120 秒（2026-09-29）。**
//
// 这是全站最慢的接口：它把统计数字喂给真模型、由模型写 4 条三要素建议。
// 实测 **26.7 秒**（其中第 1 层 function_calling 白等 17 秒，之后落回普通调用），
// 裸调用一次实测 **51.6 秒**。
//
// 实测波动很大：**26.7 / 37.9 / 45.2 秒**（三次测量），所以不能按最好的一次取值。
// 后端上限是 `.env` 的 `LLM_TIMEOUT`（已提到 120），取 **180 秒**留出余量：
// **前端超时必须大于后端上限**，否则前端会在后端返回前先断开，
// 用户看到「请求超时」而后端其实还在正常处理。
export function getDashboardReport() {
  return bizHttp.get('/dashboard/report', { timeout: 180000 })
}
