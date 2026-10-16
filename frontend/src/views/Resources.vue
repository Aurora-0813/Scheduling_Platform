<template>
  <div v-loading="loading">
    <div class="sp-page-head">
      <h1 class="sp-page-title">资源与设备管理</h1>
      <p class="sp-page-sub">维护场地与可调度设备台账</p>
    </div>

    <div class="sp-pagebar">
      <h3>资源台账</h3>
      <div class="sp-acts">
        <button
          v-if="activeTab === 'spaces'"
          class="sp-btn"
          type="button"
          @click="openSpaceDialog"
        >
          <el-icon><Plus /></el-icon>新增场地
        </button>
      </div>
    </div>

    <div class="sp-card">
      <!-- 页签改用原型 .sp-tabs：el-tabs 自带的下划线/内边距和设计系统对不上 -->
      <div class="sp-tabs">
        <button
          class="sp-tab"
          :class="{ 'is-on': activeTab === 'spaces' }"
          type="button"
          @click="activeTab = 'spaces'"
        >
          场地管理
        </button>
        <button
          class="sp-tab"
          :class="{ 'is-on': activeTab === 'devices' }"
          type="button"
          @click="activeTab = 'devices'"
        >
          设备管理
        </button>
      </div>

      <!-- 场地 -->
      <template v-if="activeTab === 'spaces'">
        <div class="sp-filters">
          <el-input
            v-model="spaceKeyword"
            placeholder="搜索场地名称 / 位置"
            clearable
            style="width: 240px"
            :prefix-icon="Search"
          />
        </div>

        <!--
          「占用」列的口径说明。放在列附近而不是塞进 tooltip：
          这两个词都有容易误解的边界（「已被预约」只算本周内；「使用中」只算已确认），
          不写清楚就会被当成 bug —— 两种情况都真实发生过，这一条就是这么来的。
          用设计系统的 .sp-ai-bar 通知条，与其它页面的提示保持同一套观感。
        -->
        <div class="sp-ai-bar occ-hint">
          <div class="sp-ic">ℹ</div>
          <span>
            <b>占用</b>共三种：<b>使用中</b>＝<b>已确认</b>的预约正在时段内；
            <b>已被预约</b>＝<b>本周内</b>已有人预约（下周及以后的预约不在此列，
            那时该场地仍显示「空闲」；预约还在「待确认」的也算这一档）；
            <b>空闲</b>＝本周内没有预约。
            它与最后一列「状态」（可用 / 停用）不是一回事 ——
            后者是管理员维护的台账开关，预约不会改动它。
          </span>
        </div>

        <el-empty
          v-if="!filteredSpaces.length"
          class="sp-empty"
          :description="spaceKeyword ? '没有匹配的场地，换个关键词试试' : '暂无场地数据'"
          :image-size="70"
        />
        <!-- sp-table-wrap：让台账在卡片内滚动，页面不出现整页滚动条（见 styles/index.css） -->
        <div v-else class="sp-table-wrap">
          <table class="sp-table">
          <thead>
            <tr>
              <th class="c w-id">ID</th>
              <th>场地名称</th>
              <th class="w-type">类型</th>
              <th class="c w-cap">可容纳人数</th>
              <th>位置</th>
              <!-- 「占用」是**推导值**（按活跃单时段与当前时间算），与「状态」不是一回事：
                   状态是「可用 / 停用」的台账开关，由管理员维护，预约绝不改写它
                   （改了会让被预约的场地从所有可用场地查询里消失）。 -->
              <th class="c w-status">占用</th>
              <th class="c w-status">状态</th>
              <!-- 「详情」列（2026-10-10 加）：点开看该场地**已被哪些时段占用**。
                   只有被预约/使用中的场地可点 —— 空闲场地没有占用明细可看，
                   按钮置灰而不是隐藏：整列对齐，也让人知道这个功能存在。 -->
              <th class="c w-act">详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredSpaces" :key="row.spaceId">
              <td class="c">{{ row.spaceId }}</td>
              <td class="strong">{{ row.spaceName }}</td>
              <td>{{ row.spaceTypeText }}</td>
              <td class="c">{{ row.capacity }}</td>
              <td>{{ row.location || '—' }}</td>
              <td class="c">
                <span class="sp-tag" :class="occupancyTagClass(row.occupancyText)">
                  {{ row.occupancyText }}
                </span>
              </td>
              <td class="c">
                <span class="sp-tag" :class="row.status === 1 ? 'is-green' : 'is-gray'">
                  {{ row.statusText }}
                </span>
              </td>
              <td class="c">
                <button
                  class="sp-link"
                  type="button"
                  :disabled="!isSpaceBooked(row)"
                  :title="isSpaceBooked(row) ? '查看预约时段' : '该场地本周内没有预约，无可查看的占用'"
                  @click="openSpaceBookings(row)"
                >
                  详情
                </button>
              </td>
            </tr>
          </tbody>
          </table>
        </div>
        <div class="sp-pager">
          <!-- /resources/spaces 真实返回**裸数组**、忽略 page/pageSize，后端没有分页能力，
               所以这里只报真实条数，不渲染页码（不造假分页器）。 -->
          <span>共 {{ filteredSpaces.length }} 个场地</span>
        </div>
      </template>

      <!-- 设备 -->
      <template v-else>
        <div class="sp-filters">
          <el-input
            v-model="deviceKeyword"
            placeholder="搜索设备名称 / 类型"
            clearable
            style="width: 240px"
            :prefix-icon="Search"
          />
        </div>
        <el-empty
          v-if="!filteredDevices.length"
          class="sp-empty"
          :description="deviceKeyword ? '没有匹配的设备，换个关键词试试' : '暂无设备数据'"
          :image-size="70"
        />
        <div v-else class="sp-table-wrap">
          <table class="sp-table">
          <thead>
            <tr>
              <th class="c w-id">ID</th>
              <th>设备名称</th>
              <th class="w-type">类型</th>
              <!-- 原「所属场地」列已删：真实 device_resource **没有 space_id**（设备是全局资源，
                   跨场地共用），那一列在真数据下永远是空的。换成真实存在的库存字段。
                   「剩余」是**推导值**（可借上限 − 窗口内峰值占用），与「可借上限」不是一回事：
                   存储的那一列按口径只读不写，所以它不会因为有人下单就减少 ——
                   会减少的是这里的「剩余」。 -->
              <th class="c w-inv">剩余 / 可借 / 总数</th>
              <!--
                「借出时间 / 归还时间」（2026-10-10 加）——取自**借了这台设备的订单**的
                起止时段，不是 device_resource 的列：设备一行代表一种设备、可能多台，
                同一台在不同时段被不同订单借用，所以没有「该设备的借出时间」，
                只有「当前这笔 / 下一笔」。取值口径见
                backend/app/services/order_service.py::device_loan_windows。
              -->
              <th class="c w-loan">借出时间</th>
              <th class="c w-loan">归还时间</th>
              <th class="c w-status">状态</th>
              <th class="c w-act">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredDevices" :key="row.deviceId">
              <td class="c">{{ row.deviceId }}</td>
              <td class="strong">{{ row.deviceName }}</td>
              <td>{{ row.deviceType || '—' }}</td>
              <td class="c">{{ row.remainingCount }} / {{ row.availableCount }} / {{ row.totalCount }}</td>
              <!-- 借用时段。没有在借/待借的单时后端给空串，这里显示「—」。
                   加 loanState 标签是因为「借用中」与「已排期」对使用者是两件事：
                   前者现在借不到，后者现在能借但要按时还。 -->
              <td class="c">
                <span v-if="!row.borrowedAt" class="sp-muted">—</span>
                <template v-else>
                  {{ row.borrowedAt }}
                  <span
                    class="sp-tag"
                    :class="row.loanState === 'in_use' ? 'is-orange' : 'is-blue'"
                  >
                    {{ row.loanState === 'in_use' ? '借用中' : '已排期' }}
                  </span>
                </template>
              </td>
              <td class="c">{{ row.dueAt || '—' }}</td>
              <td class="c">
                <span class="sp-tag" :class="deviceTagClass(row.deviceStatus)">
                  {{ row.deviceStatusText }}
                </span>
              </td>
              <td class="c">
                <button class="sp-link" type="button" @click="openDeviceDialog(row)">修改状态</button>
              </td>
            </tr>
          </tbody>
          </table>
        </div>
        <div class="sp-pager">
          <!-- 同场地：/resources/devices 也是裸数组、无分页，只报真实条数。 -->
          <span>共 {{ filteredDevices.length }} 台设备</span>
        </div>
      </template>
    </div>

    <!-- 新增场地弹窗 -->
    <el-dialog v-model="spaceDialog.visible" title="新增场地" width="460px">
      <el-form :model="spaceDialog.form" label-width="90px">
        <el-form-item label="场地名称">
          <el-input v-model="spaceDialog.form.spaceName" placeholder="如：五号会议室" />
        </el-form-item>
        <el-form-item label="类型">
          <!-- 真实字典是整数（space_type：1会议室 2展厅 3多功能厅 4户外场地），
               原先给的是中文字符串、而且「报告厅」不在规范字典里（规范是「多功能厅」）。 -->
          <el-select v-model="spaceDialog.form.spaceType" style="width: 100%">
            <el-option label="会议室" :value="1" />
            <el-option label="展厅" :value="2" />
            <el-option label="多功能厅" :value="3" />
            <el-option label="户外场地" :value="4" />
          </el-select>
        </el-form-item>
        <el-form-item label="容纳人数">
          <el-input-number v-model="spaceDialog.form.capacity" :min="1" :max="500" />
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="spaceDialog.form.location" placeholder="如：B 栋 2 层" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="spaceDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitSpace">确定</el-button>
      </template>
    </el-dialog>

    <!-- 修改设备弹窗 -->
    <el-dialog v-model="deviceDialog.visible" title="修改设备状态" width="420px">
      <el-form label-width="90px">
        <el-form-item label="设备名称">
          <el-input :model-value="deviceDialog.form.name" disabled />
        </el-form-item>
        <el-form-item label="设备状态">
          <el-select v-model="deviceDialog.form.status" style="width: 100%">
            <el-option label="正常" :value="1" />
            <el-option label="维修中" :value="2" />
            <el-option label="停用" :value="3" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deviceDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitDevice">确定</el-button>
      </template>
    </el-dialog>

    <!--
      场地「详情」：该场地未来 N 天已被占用的时段。
      数据来自 GET /resources/spaces/{spaceId}/booked —— 与下单判重**同源**
      （状态 1 待确认 / 2 已确认），所以这里列出的时段与「下单会不会被判冲突」
      不会互相矛盾。
    -->
    <el-dialog v-model="bookingDialog.visible" title="场地预约详情" width="620px">
      <div v-loading="bookingDialog.loading">
        <p class="bk-head">
          <b>{{ bookingDialog.spaceName }}</b>
          <span class="sp-muted">
            未来 {{ bookingDialog.days }} 天共 {{ bookingDialog.list.length }} 个占用时段
          </span>
        </p>

        <el-empty
          v-if="!bookingDialog.loading && !bookingDialog.list.length"
          description="未来这段时间没有占用，随时可约"
          :image-size="70"
        />

        <el-table v-else :data="bookingDialog.list" size="small" border>
          <el-table-column prop="orderId" label="订单号" width="90">
            <template #default="{ row }">#{{ row.orderId }}</template>
          </el-table-column>
          <el-table-column label="预约时段" min-width="240">
            <template #default="{ row }">
              {{ row.startTime }} ~ {{ row.endTime }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <span class="sp-tag" :class="bookingStatusClass(row.orderStatus)">
                {{ bookingStatusText(row.orderStatus) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="设备" width="90">
            <template #default="{ row }">
              {{ row.deviceIds && row.deviceIds.length ? row.deviceIds.length + ' 台' : '—' }}
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="bookingDialog.visible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  createSpace,
  getDevices,
  getSpaceBookings,
  getSpaces,
  updateDevice,
} from '@/api/resources'
import { devicesOf, spacesOf } from '@/utils/normalize'

const loading = ref(false)
const activeTab = ref('spaces')
const spaceKeyword = ref('')
const deviceKeyword = ref('')

const spaces = ref([])
const devices = ref([])

/**
 * 场地「详情」弹窗（2026-10-10 加）。
 *
 * `list` 直接放后端 `bookings[]`，字段名不二次加工 —— `_booking_out` 已经是
 * camelCase 契约（orderId / startTime / endTime / orderStatus / deviceIds）。
 */
const bookingDialog = reactive({
  visible: false,
  loading: false,
  spaceId: null,
  spaceName: '',
  days: 30,
  list: [],
})

const spaceMap = computed(() => {
  const map = {}
  spaces.value.forEach((item) => {
    map[item.spaceId] = item.spaceName
  })
  return map
})

const filteredSpaces = computed(() => {
  const kw = spaceKeyword.value.trim()
  if (!kw) return spaces.value
  return spaces.value.filter(
    (item) => item.spaceName.includes(kw) || item.location.includes(kw),
  )
})

const filteredDevices = computed(() => {
  const kw = deviceKeyword.value.trim()
  if (!kw) return devices.value
  return devices.value.filter(
    (item) => item.deviceName.includes(kw) || item.deviceType.includes(kw),
  )
})

const spaceDialog = reactive({
  visible: false,
  form: { spaceName: '', spaceType: 1, capacity: 10, location: '' },
})

const deviceDialog = reactive({
  visible: false,
  form: { id: null, name: '', status: 1 },  // id/name 仅用于弹窗展示，提交只发 deviceStatus
})

function openSpaceDialog() {
  spaceDialog.form = { spaceName: '', spaceType: 1, capacity: 10, location: '' }
  spaceDialog.visible = true
}

async function submitSpace() {
  if (!spaceDialog.form.spaceName) {
    ElMessage.warning('请填写场地名称')
    return
  }
  // 按**真实接口**的字段名发（spaceName / spaceType 整数），
  // 不再把 Mock 的 {name, type:'会议室'} 原样透传 —— 那样后端收不到必需字段。
  await createSpace({
    spaceName: spaceDialog.form.spaceName,
    spaceType: spaceDialog.form.spaceType,
    capacity: spaceDialog.form.capacity,
    location: spaceDialog.form.location || null,
    status: 1,
  })
  ElMessage.success('新增场地成功')
  spaceDialog.visible = false
  await refresh()
}

function openDeviceDialog(row) {
  deviceDialog.form = { id: row.deviceId, name: row.deviceName, status: row.deviceStatus }
  deviceDialog.visible = true
}

async function submitDevice() {
  // 真实字段是 deviceStatus（Mock 用的是 status）
  await updateDevice(deviceDialog.form.id, { deviceStatus: deviceDialog.form.status })
  ElMessage.success('设备状态已更新')
  deviceDialog.visible = false
  await refresh()
}

function deviceTagType(status) {
  if (status === 1) return 'success'
  if (status === 2) return 'warning'
  return 'info'
}

/** 展示层新增：deviceTagType 给的是 el-tag 的 type 值，而状态标签已换成原型的 .sp-tag，
 *  需要 is-green / is-orange / is-gray 这套类名；这里只做映射，不动原函数的返回值口径。 */
const TAG_CLASS = { success: 'is-green', warning: 'is-orange', info: 'is-gray' }

function deviceTagClass(status) {
  return TAG_CLASS[deviceTagType(status)] || 'is-gray'
}

/**
 * 场地占用状态 → 标签配色。
 *
 * 「使用中」用**橙色**而不是红色：它表示场地正被正常使用，不是故障或告警。
 * 红色留给真正的异常（设备损坏那种）。「空闲」用灰而不是绿 ——
 * 绿在本页已经表示「可用」这个台账状态，两种绿会让人分不清哪个是哪个。
 */
const OCCUPANCY_CLASS = { 使用中: 'is-orange', 已被预约: 'is-blue', 空闲: 'is-gray' }

function occupancyTagClass(text) {
  return OCCUPANCY_CLASS[text] || 'is-gray'
}

/* ------------------------------------------------------------------ *
 * 场地「详情」：已被占用的时段
 * ------------------------------------------------------------------ */

/**
 * 该场地是否可点「详情」。
 *
 * ⚠️ 2026-10-10 收窄：**只有「已被预约」可点**，「使用中」与「空闲」都置灰。
 *    原判据是 `occupancyText !== '空闲'`（使用中也可点），按业务方要求改为只认
 *    「已被预约」。理由：这一列回答的是「**接下来还有哪些时段被订走了**」——
 *    那是使用者要规划时最需要的信息；「使用中」的场地此刻已被人占着，
 *    看占用明细的紧迫性低，业务方选择把它归入不可点。
 *
 * 判据取后端推导好的 `occupancyText`，**不前端自己按订单算**：口径只有一处
 * （`space_service.space_occupancy`），前端再算一遍会多一个要同步的地方。
 */
function isSpaceBooked(row) {
  return !!row && row.occupancyText === '已被预约'
}

/** 打开详情：拉该场地未来 N 天的占用时段 */
async function openSpaceBookings(row) {
  if (!isSpaceBooked(row)) return
  bookingDialog.visible = true
  bookingDialog.loading = true
  bookingDialog.spaceId = row.spaceId
  bookingDialog.spaceName = row.spaceName
  bookingDialog.list = []
  try {
    const data = await getSpaceBookings(row.spaceId, bookingDialog.days)
    // 接口返回的是对象（不是裸数组），bookings 才是列表
    bookingDialog.list = (data && data.bookings) || []
  } catch {
    // request.js 已弹出后端真实 message；这里保持弹窗开着并显示空列表
    bookingDialog.list = []
  } finally {
    bookingDialog.loading = false
  }
}

/** 订单状态文案。与 utils/normalize 的字典同口径（1 待确认 / 2 已确认 / 3 已取消 / 4 已完成 / 5 已过期） */
const BOOKING_STATUS_LABEL = {
  1: '待确认',
  2: '已确认',
  3: '已取消',
  4: '已完成',
  5: '已过期',
}

function bookingStatusText(status) {
  return BOOKING_STATUS_LABEL[Number(status)] || '未知'
}

function bookingStatusClass(status) {
  switch (Number(status)) {
    case 2:
      return 'is-green'
    case 3:
      return 'is-gray'
    case 4:
      return 'is-blue'
    case 5:
      return 'is-red'
    default:
      return 'is-orange'
  }
}

/** 拉取两张表。抽成函数是因为「新增场地 / 改设备状态」提交后要重新拉一次 ——
 *  原先的提示语写着「mock 数据为常量，列表不实时变化」，那是 Mock 时代的说法；
 *  现在是真实接口，提交后会真的落库，必须刷新才看得到。 */
async function refresh() {
  loading.value = true
  try {
    const [spacesData, devicesData] = await Promise.all([getSpaces(), getDevices()])
    // 真实接口返回**裸数组**且字段名不同（spaceId/spaceName、deviceId/deviceName）——
    // 原先的 `spacesData.list || []` 拿到 undefined，不报错只是表格空。见 utils/normalize.js。
    spaces.value = spacesOf(spacesData)
    devices.value = devicesOf(devicesData)
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
/* 场地详情弹窗的头部一行：场地名 + 条数，两端对齐 */
.bk-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-s3);
  margin: 0 0 12px;
}

/*
 * 「占用」口径提示条。`.sp-ai-bar` 默认 `align-items: center`，
 * 那是为**单行**提示设计的；这条说明有两三行，图标会被垂直居中到中间，
 * 看着像浮在文字旁。改为顶对齐并微调行高，让图标与首行文字齐平。
 */
.occ-hint {
  align-items: flex-start;
}

.occ-hint .sp-ic {
  margin-top: 2px;
}

.occ-hint span {
  line-height: 1.75;
}

/* 表格列宽与对齐：原型把这些写在内联 style 里，这里收进 scoped，避免模板堆样式 */
.sp-table .w-id {
  width: 76px;
}

.sp-table .w-type {
  width: 120px;
}

.sp-table .w-cap,
.sp-table .w-inv {
  width: 120px;
}

.sp-table .w-status {
  width: 110px;
}

/* 借出/归还时间两列：要放下 "2026-10-10 09:00:00" 这样的完整时刻，
   比其它列宽（110px 会折行）。设备表因此变宽，横向滚动由 .sp-table 容器负责。 */
.sp-table .w-loan {
  width: 168px;
}

.sp-table .w-act {
  width: 100px;
}

.sp-table th.c,
.sp-table td.c {
  text-align: center;
}

.sp-table td.strong {
  color: var(--sp-text);
  font-weight: 600;
}

/* 表内操作：原型表格里是纯文字链，不用按钮块 */
.sp-link {
  border: none;
  background: none;
  padding: 0;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--sp-accent);
  cursor: pointer;
}

.sp-link:hover {
  text-decoration: underline;
}

.sp-empty {
  padding: 6px 0 2px;
}
</style>
