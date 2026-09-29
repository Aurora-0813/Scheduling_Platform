/**
 * 资源名称映射（spaceId → 场地名，deviceId → 设备名）
 *
 * 为什么需要这一层
 * ----------------
 * 后端**不会**把名称冗余进业务对象：
 *   · `GET /orders/my`    只返回 `spaceId` / `deviceIds`（**没有** spaceName / deviceNames）
 *   · `GET /tickets/list` 只返回 `spaceId` / `deviceId`
 * 而 `GET /resources/spaces` / `/resources/devices` 才带名称。
 *
 * 所以页面要显示「A栋3楼展厅」「投影仪01」就必须自己查一次资源表建映射。
 * 原先多个页面直接写 `{{ o.spaceName }}` —— 那个字段**根本不存在**，
 * 结果是列表标题一片空白、设备恒显示「无」，而且**不报错**，静默错到联调最后。
 *
 * 设计
 * ----
 * · 进程内缓存 + 在途 Promise 去重：多个页面同时 onShow 也只打一次接口
 * · 用 `reactive` 包一层：模板里 `spaceLabel(id)` 依赖它，加载完会自动重渲染
 * · **失败不抛**：名称只是展示层附加值，取不到就退化成 `场地 #3`，
 *   绝不能因为它失败而让整个列表打不开
 */
import { reactive } from 'vue'

import { devices as fetchDevices, spaces as fetchSpaces } from '@/api/resources.js'

/** 映射结果。页面模板直接依赖它，加载完成后自动刷新。 */
export const nameMaps = reactive({
  /** spaceId → 场地名 */
  spaces: {},
  /** deviceId → 设备名 */
  devices: {},
  /**
   * spaceId → 场地完整信息 { name, budget, capacity, location }
   *
   * 为什么要多存一份：场地**预算**只存在于 `space_resource.budget`，
   * `reserve_order` 表里**没有预算列**（已查真库确认）。所以预约页想显示预算，
   * 只能借道这里。注意语义——这是「场地自身的预算」，不是「本次预约的花费」。
   */
  spaceInfo: {},
  loaded: false,
  /** 上一次加载失败的原因，供页面按需提示（为空表示没失败过） */
  error: '',
})

/** 在途 Promise：并发调用只发一次请求 */
let inflight = null

/**
 * 确保映射已加载。可重复调用，第二次起直接返回。
 * 首次失败后会**允许重试**（不把失败状态永久钉死）。
 */
export function ensureNameMaps() {
  if (nameMaps.loaded) return Promise.resolve(nameMaps)
  if (inflight) return inflight

  inflight = Promise.all([fetchSpaces(), fetchDevices()])
    .then(([spaceRes, deviceRes]) => {
      const spaces = {}
      const spaceInfo = {}
      for (const s of (spaceRes && spaceRes.list) || []) {
        // 真实接口是 spaceId；兼容兜底数据的 id
        const id = s.spaceId !== undefined ? s.spaceId : s.id
        if (id === undefined || id === null) continue
        const name = s.spaceName || s.name || ''
        spaces[id] = name
        spaceInfo[id] = {
          name,
          // /resources/spaces 已返回 budget（后端 float(s.budget)，未填则为 0）
          budget: s.budget,
          capacity: s.capacity,
          location: s.location,
        }
      }
      const devices = {}
      for (const d of (deviceRes && deviceRes.list) || []) {
        const id = d.deviceId !== undefined ? d.deviceId : d.id
        if (id !== undefined && id !== null) devices[id] = d.deviceName || d.name || ''
      }
      nameMaps.spaces = spaces
      nameMaps.spaceInfo = spaceInfo
      nameMaps.devices = devices
      nameMaps.loaded = true
      nameMaps.error = ''
      return nameMaps
    })
    .catch((e) => {
      // 取不到名称不该让页面开天窗：记下原因，退化成 ID 展示
      nameMaps.error = (e && e.message) || '资源名称加载失败'
      return nameMaps
    })
    .finally(() => {
      inflight = null
    })

  return inflight
}

/** 场地名；取不到时退化成「场地 #id」而不是空串（空串会让列表标题整行消失） */
export function spaceLabel(spaceId) {
  if (spaceId === undefined || spaceId === null || spaceId === '') return '未关联场地'
  return nameMaps.spaces[spaceId] || ('场地 #' + spaceId)
}

/** 设备名列表；无设备返回「无」 */
export function deviceLabel(deviceIds) {
  const ids = deviceIds || []
  if (!ids.length) return '无'
  const names = ids.map((id) => nameMaps.devices[id] || ('#' + id))
  return names.length > 2 ? names.length + ' 台设备' : names.join(' + ')
}

/**
 * 场地的**自身预算**（`space_resource.budget`）。
 *
 * ⚠️ 不是「本次预约的预算」——`reserve_order` 表里根本没有预算列，
 * 预约接口也不返回该字段（已查真库确认）。取不到或未填写（后端给 0）时返回 null，
 * 让调用方显示「—」而不是编一个 0。
 */
export function spaceBudget(spaceId) {
  const info = nameMaps.spaceInfo[spaceId]
  if (!info) return null
  const n = Number(info.budget)
  return isNaN(n) || n <= 0 ? null : n
}

/** 需要重新拉取的场合（例如刚新增了场地）手动清缓存 */
export function resetNameMaps() {
  nameMaps.loaded = false
  nameMaps.spaces = {}
  nameMaps.spaceInfo = {}
  nameMaps.devices = {}
}

export default {
  nameMaps,
  ensureNameMaps,
  spaceLabel,
  deviceLabel,
  spaceBudget,
  resetNameMaps,
}
