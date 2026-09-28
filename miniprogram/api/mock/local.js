/**
 * 本地兜底数据
 *
 * 用途：后端没启动 / 断网 / 服务端 5xx 时，让页面仍能渲染出完整业务链路，
 * 对应开发流程.md §13.1「演示应急预案」——答辩现场不空屏。
 *
 * 设计约束：
 *  1. **与后端 Mock 同构**。字段名、分页信封、枚举取值都对齐
 *     `app/api/v1/mock_data.py`，这样「后端在线」与「本地兜底」两种状态下
 *     页面渲染完全一致，切换时不会突然露出另一种布局。
 *  2. 内容取自 示例样式.html 的叙事（A 栋 3 楼展厅、双投影、投影仪 P-02
 *     灯泡老化、工单 #202），保证演示话术连贯。
 *  3. 时间**动态计算**，永远落在「本周五」，不会随时间流逝变成过期数据。
 *
 * 注意：这里的数据仅用于兜底，真实数据一律以后端为准，不要在产品逻辑里读它。
 */
import { formatDateTime } from '@/utils/format.js'

// ------------------------------------------------------------------
// 动态时间
// ------------------------------------------------------------------
function at(dayOffset, hour, minute) {
  const d = new Date()
  d.setDate(d.getDate() + dayOffset)
  d.setHours(hour, minute || 0, 0, 0)
  return d
}

/** 下一个周五（今天就是周五则取今天）——演示输入固定是「本周五下午」 */
function nextFriday(hour, minute) {
  const now = new Date()
  const diff = (5 - now.getDay() + 7) % 7
  return at(diff, hour, minute)
}

const MAIN_START = formatDateTime(nextFriday(14, 0))
const MAIN_END = formatDateTime(nextFriday(16, 0))

// ------------------------------------------------------------------
// 模块 3：移动端预约与通知
// ------------------------------------------------------------------
const ORDER_CONFIRMED = {
  orderId: 1001,
  orderNo: 'RS20260928001',
  spaceId: 4,
  spaceName: 'A 栋 3 楼展厅',
  spaceType: 2,
  deviceIds: [1, 2, 5],
  deviceNames: ['投影仪 P-01', '投影仪 P-02', '音响 S-01'],
  startTime: MAIN_START,
  endTime: MAIN_END,
  status: 2,
  statusText: '已确认',
  budget: '980.00',
  agentRequest: '本周五下午要个能坐 40 人的展厅，带双投影和音响，预算 1000 以内',
  createTime: formatDateTime(at(0, 9, 41)),
}

const ORDER_PENDING = {
  orderId: 1002,
  orderNo: 'RS20260928002',
  spaceId: 2,
  spaceName: 'B 栋 201 会议室',
  spaceType: 1,
  deviceIds: [3],
  deviceNames: ['投影仪 P-03'],
  startTime: formatDateTime(nextFriday(9, 0)),
  endTime: formatDateTime(nextFriday(11, 0)),
  status: 1,
  statusText: '待确认',
  budget: '300.00',
  agentRequest: '周五上午两个小时的部门例会',
  createTime: formatDateTime(at(0, 10, 12)),
}

const ORDER_DONE = {
  orderId: 998,
  orderNo: 'RS20260920007',
  spaceId: 7,
  spaceName: '户外活动场地',
  spaceType: 4,
  deviceIds: [],
  deviceNames: [],
  startTime: formatDateTime(at(-5, 15, 0)),
  endTime: formatDateTime(at(-5, 17, 30)),
  status: 4,
  statusText: '已完成',
  budget: '0.00',
  agentRequest: '上周五下午团建用户外场地',
  createTime: formatDateTime(at(-7, 9, 30)),
}

const ORDERS_MY = {
  page: 1,
  pageSize: 10,
  total: 3,
  list: [ORDER_CONFIRMED, ORDER_PENDING, ORDER_DONE],
}

const MESSAGES_UNREAD = {
  total: 4,
  list: [
    {
      id: 501,
      notifyType: 1,
      title: '预约成功',
      content: '你的预约「周五 14:00-16:00 A 栋 3 楼展厅」已确认，参会提醒已发送给 40 位成员。',
      isRead: false,
      createTime: formatDateTime(at(0, 10, 26)),
    },
    {
      id: 502,
      notifyType: 2,
      title: '方案调整致歉',
      content: '很抱歉，原定场地时段已被占用，已为你调整为 B 栋 201 + 202，预算由 980 元降至 860 元。',
      isRead: false,
      createTime: formatDateTime(at(0, 10, 18)),
    },
    {
      id: 503,
      notifyType: 3,
      title: '设备故障告警',
      content: 'A 栋 3 楼投影仪 P-02 灯泡老化，工单 #202 已派单至资源管理员，处理中。',
      isRead: false,
      createTime: formatDateTime(at(0, 9, 52)),
    },
    {
      id: 504,
      notifyType: 2,
      title: '软冲突提醒',
      content: '检测到同团队两场活动连续排期无休息，建议合并为一个时段，可节省 1 间会议室资源。',
      isRead: false,
      createTime: formatDateTime(at(-1, 17, 20)),
    },
  ],
}

// ------------------------------------------------------------------
// 模块 5：资源与设备
// ------------------------------------------------------------------
const SPACES = {
  page: 1,
  pageSize: 10,
  total: 5,
  list: [
    { id: 4, name: 'A 栋 3 楼展厅', type: '展厅', spaceType: 2, capacity: 50, location: 'A 栋 3 层', budget: 800.0, status: 1, statusText: '可用' },
    { id: 5, name: 'C 栋 1 楼展厅', type: '展厅', spaceType: 2, capacity: 35, location: 'C 栋 1 层', budget: 600.0, status: 1, statusText: '可用' },
    { id: 2, name: 'B 栋 201 会议室', type: '会议室', spaceType: 1, capacity: 20, location: 'B 栋 2 层', budget: 300.0, status: 1, statusText: '可用' },
    { id: 3, name: 'B 栋 202 会议室', type: '会议室', spaceType: 1, capacity: 20, location: 'B 栋 2 层', budget: 300.0, status: 1, statusText: '可用' },
    { id: 9, name: 'C 栋多功能厅', type: '多功能厅', spaceType: 3, capacity: 80, location: 'C 栋 1 层', budget: 1200.0, status: 1, statusText: '可用' },
  ],
}

const DEVICES = {
  page: 1,
  pageSize: 10,
  total: 6,
  list: [
    { id: 1, name: '投影仪 P-01', deviceName: '投影仪 P-01', deviceType: '投影仪', spaceId: 4, deviceStatus: 1, totalCount: 1, availableCount: 1, status: 1, statusText: '正常' },
    { id: 2, name: '投影仪 P-02', deviceName: '投影仪 P-02', deviceType: '投影仪', spaceId: 4, deviceStatus: 2, totalCount: 1, availableCount: 0, status: 2, statusText: '灯泡老化' },
    { id: 5, name: '音响 S-01', deviceName: '音响 S-01', deviceType: '音响', spaceId: 4, deviceStatus: 1, totalCount: 1, availableCount: 1, status: 1, statusText: '正常' },
    { id: 6, name: '音响 S-03', deviceName: '音响 S-03', deviceType: '音响', spaceId: 9, deviceStatus: 3, totalCount: 1, availableCount: 0, status: 3, statusText: '缺失配件' },
    { id: 11, name: '显示屏 D-01', deviceName: '显示屏 D-01', deviceType: '显示屏', spaceId: 2, deviceStatus: 1, totalCount: 2, availableCount: 2, status: 1, statusText: '正常' },
    { id: 21, name: '无人机 U-02', deviceName: '无人机 U-02', deviceType: '无人机', spaceId: 0, deviceStatus: 1, totalCount: 2, availableCount: 2, status: 1, statusText: '正常' },
  ],
}

// ------------------------------------------------------------------
// 模块 6：AI 智能巡检
// ------------------------------------------------------------------
const INSPECT_SUBMIT = {
  deviceStatus: 2,
  deviceStatusText: '灯泡老化',
  deviceName: '投影仪 P-02',
  confidence: 0.92,
  report: '本次巡检 8 台设备，7 台完好，1 台投影仪灯泡老化需更换，识别置信度 92%。',
  repairSuggestion: '建议更换灯泡，型号 X，预计耗时 30 分钟。',
  ticketId: 202,
}

const TICKETS = {
  page: 1,
  pageSize: 10,
  total: 3,
  list: [
    {
      id: 202,
      spaceId: 4,
      spaceName: 'A 栋 3 楼展厅',
      deviceId: 2,
      deviceName: '投影仪 P-02',
      deviceStatus: 2,
      deviceStatusText: '灯泡老化',
      status: 2,
      statusText: '处理中',
      handlerName: '杨睿坤',
      report: '投影仪指示灯红灯常亮，无画面输出。',
      repairSuggestion: '更换灯泡，型号 X。',
      createTime: formatDateTime(at(0, 10, 22)),
    },
    {
      id: 201,
      spaceId: 9,
      spaceName: 'C 栋多功能厅',
      deviceId: 6,
      deviceName: '音响 S-03',
      deviceStatus: 3,
      deviceStatusText: '缺失配件',
      status: 1,
      statusText: '待处理',
      handlerName: '',
      report: '音响接线端子缺失。',
      repairSuggestion: '补齐接线端子配件。',
      createTime: formatDateTime(at(-1, 15, 40)),
    },
    {
      id: 199,
      spaceId: 2,
      spaceName: 'B 栋 201 会议室',
      deviceId: 11,
      deviceName: '显示屏 D-01',
      deviceStatus: 1,
      deviceStatusText: '设备完好',
      status: 3,
      statusText: '已完成',
      handlerName: '黄嵩',
      report: '设备外观与显示均正常。',
      repairSuggestion: '',
      createTime: formatDateTime(at(-3, 11, 5)),
    },
  ],
}

// ------------------------------------------------------------------
// 模块 1：语音
// ------------------------------------------------------------------
const VOICE_FORMAT = {
  formattedText:
    '时间：周五下午；人数：约 40 人；空间类型：展厅；设备：双投影 + 音响；预算：1000 元以内；可接受场地拆分。',
  keywords: ['周五下午', '40 人', '展厅', '双投影', '音响', '1000 元以内', '可拆分'],
}

const VOICE_ASR = {
  text: '嗯……那个周五下午吧，大概四十来号人，要个展厅，带双投影和音响，预算 1000 以内，没大场地就拆两个小的。',
}

// ------------------------------------------------------------------
// 模块 2：视觉
// ------------------------------------------------------------------
const IMAGE_ANALYZE = {
  type: 'space',
  spaceId: 4,
  spaceName: 'A 栋 3 楼展厅',
  confidence: 0.92,
  needConfirm: false,
  question: '',
  availableTime: [
    { date: formatDateTime(at(0, 0, 0)).slice(0, 10), startTime: '09:00:00', endTime: '12:00:00' },
    { date: formatDateTime(at(0, 0, 0)).slice(0, 10), startTime: '14:00:00', endTime: '18:00:00' },
  ],
  devices: [
    { deviceType: '投影仪', count: 2, confidence: 0.95 },
    { deviceType: '音响', count: 1, confidence: 0.9 },
  ],
  candidates: [],
  imageUrl: null,
}

const IMAGE_SKETCH = {
  type: 'sketch',
  capacity: 40,
  layout: '长方形会场，前排讲台 + 后排 8 排座椅，两侧留过道',
  requirements: ['需要双投影', '需要音响', '需要讲台'],
  confidence: 0.85,
  needConfirm: false,
  question: '',
  imageUrl: null,
}

// ------------------------------------------------------------------
// 模块 4：核心调度 Agent
// ------------------------------------------------------------------
/**
 * 思考链。
 *
 * 真源是后端 `docs/mock/agent_schedule.json`（7 步、时间戳跨 39 秒），
 * 前端与后端共用同一份。这里为了控制包体做了**压缩**：
 * 保留全部 7 步与 result / thought / action / actionInput，
 * 但把 observation 里冗长的候选场地与设备数组裁成计数。
 * 渲染路径与真源完全一致，接入真实接口后无需改页面。
 *
 * ⚠️ 冻结的 Plan schema（app/schemas/agent.py）里**没有价格字段**，
 * 只有 `reason` 散文，所以方案卡的大号金额在本数据下不显示。
 * 详见 miniprogram/README.md 的「已知契约缺口」。
 */
function buildSchedule() {
  const start = MAIN_START
  const end = MAIN_END
  const stepTime = (offsetSeconds) => {
    const d = nextFriday(14, 0)
    d.setSeconds(offsetSeconds)
    return formatDateTime(d)
  }

  return {
    plan: {
      spaceId: 4,
      spaceName: 'A 栋 3 楼展厅',
      deviceIds: [1, 2, 5],
      startTime: start,
      endTime: end,
      reason:
        'A 栋 3 楼展厅可容纳 50 人（需求 40 人）、租金 800 元，配投影仪 2 台与音响 1 套，合计未超 1000 元预算。',
    },
    backupPlan: {
      spaceId: 2,
      spaceName: 'B 栋 201 + B 栋 202',
      deviceIds: [3],
      startTime: start,
      endTime: end,
      reason: '备选：若展厅该时段被占用，按用户授权拆分为两间 20 人会议室，时段对齐，投影降级为单投影。',
    },
    needConfirm: true,
    trace: [
      {
        step: 1,
        result: '模型推理',
        timestamp: stepTime(0),
        thought:
          '需求拆解：人数 40、场地类型「展厅」、时间「本周五下午」→ 14:00-16:00、需要双投影 + 音响、预算上限 1000 元。先按容量与类型查场地，再按类型逐类查设备，最后核算预算。',
        action: null,
        actionInput: null,
        observation: null,
      },
      {
        step: 2,
        result: '查询场地：命中 2 个候选场地',
        timestamp: stepTime(4),
        thought: '先查展厅：容量下限 40 人，时段 14:00-16:00。',
        action: 'query_spaces',
        actionInput: { capacity: 40, space_type: 2, start_time: start, end_time: end },
        observation: { ok: true, count: 2, spaceTypeLabel: '展厅' },
      },
      {
        step: 3,
        result: '查询设备：命中 4 台可借设备',
        timestamp: stepTime(8),
        thought:
          '候选场地两个：C 栋 1 楼展厅只能坐 35 人，不满足 40 人；A 栋 3 楼展厅 50 人、800 元，可用。接着查设备，需求要双投影。',
        action: 'query_devices',
        actionInput: { device_type: '投影仪' },
        observation: { ok: true, count: 4, deviceTypeLabel: '投影仪' },
      },
      {
        step: 4,
        result: '查询设备：命中 1 套音响',
        timestamp: stepTime(15),
        thought: '投影仪 4 台全部可用，取 id 1、2 满足双投影。再查音响。',
        action: 'query_devices',
        actionInput: { device_type: '音响' },
        observation: { ok: true, count: 4, deviceTypeLabel: '音响' },
      },
      {
        step: 5,
        result: '锁定资源：成功（订单 1001）',
        timestamp: stepTime(23),
        thought:
          '方案定了：A 栋 3 楼展厅 + 投影仪 id 1、2 + 音响 id 5。核对时段不与营业时间冲突，预算 800 + 设备费仍在 1000 元内。单事务内 SELECT ... FOR UPDATE 锁定场地行后写入订单。',
        action: 'lock_resources',
        actionInput: { space_id: 4, device_ids: [1, 2, 5], start_time: start, end_time: end },
        observation: { ok: true, orderId: 1001, reason: null },
      },
      {
        step: 6,
        result: '生成通知文案：预约成功提醒',
        timestamp: stepTime(29),
        thought: '资源已锁定，接着生成参会通知文案。通知类型取字典内的「预约提醒」。',
        action: 'generate_notification',
        actionInput: {
          order_info: {
            notifyType: '预约提醒',
            orderId: 1001,
            spaceName: 'A 栋 3 楼展厅',
            startTime: start,
            endTime: end,
          },
        },
        observation: {
          ok: true,
          notifyType: 1,
          title: '预约成功提醒',
          content: `您预约的「A 栋 3 楼展厅」已提交，时间 ${start} ~ ${end}。`,
        },
      },
      {
        step: 7,
        result: '提交方案：已提交',
        timestamp: stepTime(39),
        thought: '方案与备选方案都已确定，通过 submit_plan 交出。',
        action: 'submit_plan',
        actionInput: {
          plan: { spaceId: 4, spaceName: 'A 栋 3 楼展厅', deviceIds: [1, 2, 5] },
          backup_plan: { spaceId: 2, spaceName: 'B 栋 201 + B 栋 202', deviceIds: [3] },
          reason: '主方案满足 40 人 + 双投影 + 音响且不超预算；备选为拆分会场方案。',
        },
        observation: { ok: true, accepted: true, message: '方案已提交，无需再次调用本工具。' },
      },
    ],
  }
}

// ------------------------------------------------------------------
// 路由表
// ------------------------------------------------------------------
/** 把 '/orders/1001/cancel' 归一成 '/orders/:id/cancel'，让动态段能命中 */
function normalizePath(path) {
  return String(path)
    .split('?')[0]
    .replace(/\/\d+(?=\/|$)/g, '/:id')
}

function routeKey(method, path) {
  return `${String(method).toUpperCase()} ${normalizePath(path)}`
}

const ROUTES = {
  'GET /orders/my': ORDERS_MY,
  'POST /orders/create': (payload) => ({
    orderId: 1001,
    orderNo: 'RS20260928001',
    spaceId: payload.spaceId || 4,
    spaceName: 'A 栋 3 楼展厅',
    deviceIds: payload.deviceIds || [],
    startTime: payload.startTime || MAIN_START,
    endTime: payload.endTime || MAIN_END,
    status: 2,
    statusText: '已确认',
  }),
  'PUT /orders/:id/cancel': { orderId: 1001, status: 3, statusText: '已取消' },

  'GET /messages/unread': MESSAGES_UNREAD,

  'GET /resources/spaces': SPACES,
  'GET /resources/devices': DEVICES,

  'GET /tickets/list': TICKETS,
  'PUT /tickets/:id/status': { id: 202, status: 3, statusText: '已完成', handlerId: 1 },
  'POST /inspect/submit': INSPECT_SUBMIT,

  'POST /voice/format': VOICE_FORMAT,
  // ASR 走 uni.uploadFile，在 request.js 里以 method='UPLOAD' 兜底
  'UPLOAD /voice/asr': VOICE_ASR,
  'UPLOAD /image/analyze': IMAGE_ANALYZE,
  'UPLOAD /image/sketch': IMAGE_SKETCH,

  'POST /agent/schedule': buildSchedule,
}

/**
 * 查本地兜底数据。
 * @returns 命中的数据（静态对象或函数返回值）；未命中返回 undefined
 */
export function resolve(method, path, payload) {
  const entry = ROUTES[routeKey(method, path)]
  if (entry === undefined) return undefined
  return typeof entry === 'function' ? entry(payload || {}) : entry
}

/** 深拷贝，避免调用方改到模块级常量 */
export function clone(value) {
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(value))
}

export default { resolve, clone }
