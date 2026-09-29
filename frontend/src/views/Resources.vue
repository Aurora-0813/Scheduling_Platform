<template>
  <div v-loading="loading">
    <div class="sp-page-head">
      <h1 class="sp-page-title">资源与设备管理</h1>
      <p class="sp-page-sub">维护场地与可调度设备台账（数据来源：/resources/*）</p>
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
        <el-empty
          v-if="!filteredSpaces.length"
          class="sp-empty"
          :description="spaceKeyword ? '没有匹配的场地，换个关键词试试' : '暂无场地数据'"
          :image-size="70"
        />
        <table v-else class="sp-table">
          <thead>
            <tr>
              <th class="c w-id">ID</th>
              <th>场地名称</th>
              <th class="w-type">类型</th>
              <th class="c w-cap">可容纳人数</th>
              <th>位置</th>
              <th class="c w-status">状态</th>
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
                <span class="sp-tag" :class="row.status === 1 ? 'is-green' : 'is-gray'">
                  {{ row.statusText }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
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
        <table v-else class="sp-table">
          <thead>
            <tr>
              <th class="c w-id">ID</th>
              <th>设备名称</th>
              <th class="w-type">类型</th>
              <!-- 原「所属场地」列已删：真实 device_resource **没有 space_id**（设备是全局资源，
                   跨场地共用），那一列在真数据下永远是空的。换成真实存在的库存字段。 -->
              <th class="c w-inv">可用 / 总数</th>
              <th class="c w-status">状态</th>
              <th class="c w-act">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredDevices" :key="row.deviceId">
              <td class="c">{{ row.deviceId }}</td>
              <td class="strong">{{ row.deviceName }}</td>
              <td>{{ row.deviceType || '—' }}</td>
              <td class="c">{{ row.availableCount }} / {{ row.totalCount }}</td>
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  createSpace,
  getDevices,
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
