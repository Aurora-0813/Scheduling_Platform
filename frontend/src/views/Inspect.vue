<template>
  <div v-loading="loading">
    <div class="page-head">
      <h1 class="sp-page-title">AI 智能巡检与维修工单</h1>
      <p class="sp-page-sub">上传巡检照片，AI 自动判定故障并生成维修建议与工单（数据来源：/inspect、/tickets）</p>
    </div>

    <div class="sp-card">
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="搜索工单 / 故障描述"
          clearable
          style="width: 260px"
          :prefix-icon="Search"
        />
        <el-button type="primary" @click="inspectDialog.visible = true">
          <el-icon><Camera /></el-icon>提交巡检
        </el-button>
      </div>

      <el-table :data="filteredTickets" border stripe>
        <el-table-column prop="id" label="工单号" width="100" align="center" />
        <el-table-column label="场地" min-width="130">
          <template #default="{ row }">{{ spaceMap[row.spaceId] || `场地ID ${row.spaceId}` }}</template>
        </el-table-column>
        <el-table-column label="设备" width="120">
          <template #default="{ row }">设备ID {{ row.deviceId }}</template>
        </el-table-column>
        <el-table-column prop="deviceStatus" label="故障判定" width="100" align="center">
          <template #default="{ row }">
            <el-tag type="danger" effect="plain">{{ row.deviceStatus }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="report" label="巡检报告" min-width="220" show-overflow-tooltip />
        <el-table-column prop="createTime" label="创建时间" width="170" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="ticketTagType(row.status)">{{ row.statusText }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="row.status === 3"
              @click="handleTicket(row)"
            >
              处理
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 提交巡检弹窗 -->
    <el-dialog v-model="inspectDialog.visible" title="提交 AI 巡检" width="480px">
      <el-form label-width="90px">
        <el-form-item label="所属场地">
          <el-select v-model="inspectDialog.spaceId" placeholder="请选择场地" style="width: 100%">
            <el-option
              v-for="space in spaces"
              :key="space.id"
              :label="space.name"
              :value="space.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="巡检照片">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept="image/*"
            list-type="picture-card"
            :on-change="onFileChange"
            :on-remove="onFileRemove"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inspectDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitInspection">
          提交 AI 分析
        </el-button>
      </template>
    </el-dialog>

    <!-- AI 分析结果弹窗 -->
    <el-dialog v-model="resultDialog.visible" title="AI 巡检分析结果" width="520px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="故障判定">
          <el-tag type="danger">{{ aiResult.deviceStatus }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="分析报告">{{ aiResult.report }}</el-descriptions-item>
        <el-descriptions-item label="维修建议">{{ aiResult.repairSuggestion }}</el-descriptions-item>
        <el-descriptions-item label="生成工单">#{{ aiResult.ticketId }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="resultDialog.visible = false">知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Camera, Plus, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { getTickets, submitInspect, updateTicketStatus } from '@/api/inspect'
import { getSpaces } from '@/api/resources'

const loading = ref(false)
const submitting = ref(false)
const keyword = ref()

const tickets = ref([])
const spaces = ref([])
const uploadFile = ref(null)

const inspectDialog = reactive({ visible: false, spaceId: null })
const resultDialog = reactive({ visible: false })
const aiResult = reactive({})

const spaceMap = computed(() => {
  const map = {}
  spaces.value.forEach((item) => {
    map[item.id] = item.name
  })
  return map
})

const filteredTickets = computed(() => {
  const kw = keyword.value?.trim()
  if (!kw) return tickets.value
  return tickets.value.filter(
    (item) => String(item.id).includes(kw) || item.report.includes(kw),
  )
})

function onFileChange(uploadFileItem) {
  uploadFile.value = uploadFileItem.raw
}

function onFileRemove() {
  uploadFile.value = null
}

async function submitInspection() {
  if (!inspectDialog.spaceId) {
    ElMessage.warning('请选择所属场地')
    return
  }
  if (!uploadFile.value) {
    ElMessage.warning('请上传巡检照片')
    return
  }
  submitting.value = true
  try {
    const data = await submitInspect(uploadFile.value, inspectDialog.spaceId)
    Object.assign(aiResult, data)
    inspectDialog.visible = false
    resultDialog.visible = true
    await loadTickets()
  } finally {
    submitting.value = false
  }
}

async function handleTicket(row) {
  await updateTicketStatus(row.id, { status: 3 })
  ElMessage.success(`工单 #${row.id} 已标记完成（mock 数据为常量，列表不实时变化）`)
}

function ticketTagType(status) {
  if (status === 1) return 'warning'
  if (status === 3) return 'success'
  return 'info'
}

async function loadTickets() {
  const data = await getTickets()
  tickets.value = data.list || []
}

onMounted(async () => {
  loading.value = true
  try {
    const [spacesData] = await Promise.all([getSpaces(), loadTickets()])
    spaces.value = spacesData.list || []
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
