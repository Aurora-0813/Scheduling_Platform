/**
 * 预约（模块 3）—— 兼容层
 *
 * ⚠️ **2026-10-06 从老请求层迁到 `@/api/request.js`。**
 *
 * 原先本文件 import 的是 `@/utils/request`（另一套**并存**的请求封装），
 * 两套的差别不是风格问题，而是**行为不同**：
 *
 *   | | 老层 utils/request.js | 新层 api/request.js |
 *   |---|---|---|
 *   | 401 处理 | **一律 clearToken** → 被踢回登录页 | 只对 40103（过期）**单例续期并重放** |
 *   | 未登录 | 照发请求，拿 401 再清 token | 提前抛 `NO_TOKEN`，页面自己决定展示 |
 *   | 服务不可用 | 直接报错 | 按配置回落本地数据 |
 *
 * 于是小程序出现「同一 App 两套行为」：**预约列表 / 预约详情 / 预订创建**
 * 这三个页面只要 accessToken 过了 30 分钟就被登出，而其它页面静默续期。
 * 迁到新层后全 App 一致。
 *
 * 另外两处顺手收敛：
 *   · 资源查询（原 `getSpaces` / `getDevices`）与 `api/resources.js` **重复**，
 *     这里改为委托给它，只保留「一次拿两张表」的便利方法；
 *   · 补上 `completeOrder`（2→4）。后端 2026-10-06 才有这个接口，
 *     此前小程序**无法把预约标记完成** → 场地永远显示被占用。
 *
 * ⚠️ 路径写成 `/orders/my` 这种**不含 `/api/v1` 前缀**的形式 ——
 * 新层在 `buildUrl()` 里统一拼前缀，自己再拼一遍会得到 `/api/v1/api/v1/...`。
 */
import { request } from '@/api/request.js'
import { spaces as fetchSpaces, devices as fetchDevices } from '@/api/resources.js'
import { listOf } from '@/utils/normalize.js'

// 资源（§5.3 模块5）—— 委托给 resources.js，避免同一件事两处实现
export { fetchSpaces as getSpaces, fetchDevices as getDevices }

/**
 * 一次拿「场地 + 设备」。
 *
 * ⚠️ 返回的是**裸数组**（`{ spaces: [...], devices: [...] }`），不是 `{list,total}`。
 * `reserve/create.vue` 直接把它塞进 `<picker :range="spaces" range-key="spaceName">`，
 * 所以这里**刻意不走** `resources.spaces()`（那个回 `{list,total}`）——
 * 保持形状不变，页面就不用改。
 */
export const getResources = async () => {
  const [spaces, devices] = await Promise.all([
    request({ path: '/resources/spaces' }),
    request({ path: '/resources/devices' }),
  ])
  return { spaces: listOf(spaces), devices: listOf(devices) }
}

// 预约订单（§5.3 模块3）
// ⚠️ 身份由请求层统一注入 JWT，**不走** /orders/user/{id}（§5.1）。
//
// ⚠️ `getOrders` **返回裸数组**，不是 `{list,total}` —— 调用方写的是
//    `list.value = await getOrders(...)`（见 pages/reserve/list.vue）。
//    后端 `/orders/my` 本身就是裸数组，所以这里保持原样，
//    换成 `api/orders.js::myOrders()` 那种包一层的写法会把页面弄坏。
export const getOrders = (status) =>
  request({ path: '/orders/my', method: 'GET', data: status ? { status } : {} })

export const getOrder = (id) => request({ path: `/orders/${id}`, method: 'GET' })

export const createOrder = (data) =>
  request({ path: '/orders/create', method: 'POST', data })

export const confirmOrder = (id) =>
  request({ path: `/orders/${id}/confirm`, method: 'PUT' })

/**
 * 完成预约（状态机 2已确认 → 4已完成）。
 *
 * 只能对「已确认」调；待确认会返回 409（后端状态迁移表只允许 2→4）。
 * 完成后该单离开活跃集合，**场地立刻不再算被占用**。
 */
export const completeOrder = (id) =>
  request({ path: `/orders/${id}/complete`, method: 'PUT' })

export const cancelOrder = (id) =>
  request({ path: `/orders/${id}/cancel`, method: 'PUT' })
