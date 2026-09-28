<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">资源与设备管理</h1>
      <p class="sp-page-sub">维护场地与可调度设备台账（数据来源：/resources/*）</p>
    </div>

    <div class="sp-card">
      <el-tabs v-model="activeTab">
        <!-- 场地 -->
        <el-tab-pane label="场地管理" name="spaces">
          <div class="toolbar">
            <el-input
              v-model="spaceKeyword"
              placeholder="搜索场地名称 / 位置"
              clearable
              style="width: 240px"
              :prefix-icon="Search"
            />
            <el-button type="primary" @click="openSpaceDialog">
              <el-icon><Plus /></el-icon>新增场地
            </el-button>
          </div>
          <el-table :data="filteredSpaces" border stripe>
            <el-table-column prop="id" label="ID" width="80" align="center" />
            <el-table-column prop="name" label="场地名称" min-width="140" />
            <el-table-column prop="type" label="类型" width="110" />
            <el-table-column prop="capacity" label="可容纳人数" width="110" align="center" />
            <el-table-column prop="location" label="位置" min-width="120" />
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag :type="row.status === 1 ? 'success' : 'info'">
                  {{ row.statusText }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 设备 -->
        <el-tab-pane label="设备管理" name="devices">
          <div class="toolbar">
            <el-input
              v-model="deviceKeyword"
              placeholder="搜索设备名称 / 类型"
              clearable
              style="width: 240px"
              :prefix-icon="Search"
            />
          </div>
          <el-table :data="filteredDevices" border stripe>
            <el-table-column prop="id" label="ID" width="80" align="center" />
            <el-table-column prop="name" label="设备名称" min-width="140" />
            <el-table-column prop="type" label="类型" width="120" />
            <el-table-column label="所属场地" min-width="140">
              <template #default="{ row }">
                {{ spaceMap[row.spaceId] || `场地ID ${row.spaceId}` }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110" align="center">
              <template #default="{ row }">
                <el-tag :type="deviceTagType(row.status)">{{ row.statusText }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" align="center">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDeviceDialog(row)">修改状态</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 新增场地弹窗 -->
    <el-dialog v-model="spaceDialog.visible" title="新增场地" width="460px">
      <el-form :model="spaceDialog.form" label-width="90px">
        <el-form-item label="场地名称">
          <el-input v-model="spaceDialog.form.name" placeholder="如：五号会议室" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="spaceDialog.form.type" style="width: 100%">
            <el-option label="会议室" value="会议室" />
            <el-option label="展厅" value="展厅" />
            <el-option label="报告厅" value="报告厅" />
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

const loading = ref(false)
const activeTab = ref('spaces')
const spaceKeyword = ref('')
const deviceKeyword = ref('')

const spaces = ref([])
const devices = ref([])

const spaceMap = computed(() => {
  const map = {}
  spaces.value.forEach((item) => {
    map[item.id] = item.name
  })
  return map
})

const filteredSpaces = computed(() => {
  const kw = spaceKeyword.value.trim()
  if (!kw) return spaces.value
  return spaces.value.filter(
    (item) => item.name.includes(kw) || item.location.includes(kw),
  )
})

const filteredDevices = computed(() => {
  const kw = deviceKeyword.value.trim()
  if (!kw) return devices.value
  return devices.value.filter(
    (item) => item.name.includes(kw) || item.type.includes(kw),
  )
})

const spaceDialog = reactive({
  visible: false,
  form: { name: '', type: '会议室', capacity: 10, location: '' },
})

const deviceDialog = reactive({
  visible: false,
  form: { id: null, name: '', status: 1 },
})

function openSpaceDialog() {
  spaceDialog.form = { name: '', type: '会议室', capacity: 10, location: '' }
  spaceDialog.visible = true
}

async function submitSpace() {
  if (!spaceDialog.form.name) {
    ElMessage.warning('请填写场地名称')
    return
  }
  await createSpace({ ...spaceDialog.form, status: 1 })
  ElMessage.success('新增场地成功（mock 数据为常量，列表不实时变化）')
  spaceDialog.visible = false
}

function openDeviceDialog(row) {
  deviceDialog.form = { id: row.id, name: row.name, status: row.status }
  deviceDialog.visible = true
}

async function submitDevice() {
  await updateDevice(deviceDialog.form.id, { status: deviceDialog.form.status })
  ElMessage.success('设备状态已更新（mock 数据为常量，列表不实时变化）')
  deviceDialog.visible = false
}

function deviceTagType(status) {
  if (status === 1) return 'success'
  if (status === 2) return 'warning'
  return 'info'
}

onMounted(async () => {
  loading.value = true
  try {
    const [spacesData, devicesData] = await Promise.all([getSpaces(), getDevices()])
    spaces.value = spacesData.list || []
    devices.value = devicesData.list || []
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page-head {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
}
</style>
