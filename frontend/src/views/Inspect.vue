<template>
  <div v-loading="loading">
    <div class="sp-pagebar">
      <div class="page-titles">
        <h3>AI 智能巡检 · 维修工单</h3>
        <p class="sp-page-sub">
          上传巡检照片，AI 自动判定故障并生成维修建议与工单（数据来源：/inspect、/tickets）
        </p>
      </div>
      <div class="sp-acts">
        <button class="sp-btn is-ai is-sm" @click="inspectDialog.visible = true">
          <el-icon><Camera /></el-icon>提交巡检
        </button>
      </div>
    </div>

    <div class="inspect-grid">
      <!-- ===== 左栏：现场照片 + 多模态识别结论 ===== -->
      <div class="col-left">
        <div class="sp-imgbox photo-box">
          <!-- 提交巡检的响应只有 deviceStatus / report / repairSuggestion / ticketId，不含图片地址；
               这里预览的是用户本地上传的原始文件（真实图片），没有文件才退回相机空态。 -->
          <img v-if="previewUrl" :src="previewUrl" alt="巡检照片" />
          <div v-else class="sp-cam">
            <span>📷</span>
            现场照片 · 提交巡检后显示
          </div>
          <!-- 识别框位置由本页样式居中，**只是示意**：接口不返回真实检测坐标，
               真正的信息是 data-label 里的 AI 结论。 -->
          <div
            v-if="aiResult.deviceStatus"
            class="sp-bbox"
            :data-label="`AI 识别：${aiResult.deviceStatus}`"
          ></div>
          <div class="sp-scanline"></div>
        </div>

        <div class="sp-card">
          <div class="sp-card-head"><b>🤖 多模态识别结论</b></div>
          <template v-if="resultRows.length">
            <div v-for="row in resultRows" :key="row.k" class="sp-mbrow">
              <span class="sp-k">{{ row.k }}</span>
              <span class="sp-v">
                <span v-if="row.cls" class="sp-tag" :class="row.cls">{{ row.v }}</span>
                <template v-else>{{ row.v }}</template>
              </span>
            </div>
          </template>
          <p v-else class="sp-muted empty-tip">尚未提交巡检照片，暂无识别结论。</p>
        </div>
      </div>

      <!-- ===== 右栏：AI 摘要 + 工单列表 ===== -->
      <div class="col-right">
        <div class="sp-card">
          <div class="sp-card-head">
            <b>📋 AI 巡检摘要</b>
            <span class="sp-grow"></span>
            <!-- 巡检编号 / 巡检人接口不返回，只展示能对上的那张工单的编号与创建时间 -->
            <span v-if="resultTicket" class="sp-muted">
              工单 #{{ resultTicket.id }} · {{ resultTicket.createTime || '时间未知' }}
            </span>
          </div>
          <p v-if="aiResult.report" class="summary-text">{{ aiResult.report }}</p>
          <p v-else class="sp-muted empty-tip">尚未提交巡检，暂无 AI 摘要。</p>
          <p v-if="aiResult.ticketId" class="summary-text">
            已自动生成维修工单
            <b class="summary-num">#{{ aiResult.ticketId }}</b>
            ，可在下方列表中处理。
          </p>
        </div>

        <div class="sp-card">
          <div class="sp-card-head">
            <b>🧰 维修工单列表</b>
            <!-- 计数按真实工单状态统计；为 0 的整块不显示，原型里「2 条处理中」是设计稿占位 -->
            <span v-if="waitingCount" class="sp-tag is-blue">{{ waitingCount }} 条待处理</span>
            <span v-if="processingCount" class="sp-tag is-orange">{{ processingCount }} 条处理中</span>
            <span class="sp-grow"></span>
            <el-input
              v-model="keyword"
              placeholder="搜索工单 / 故障描述"
              clearable
              size="small"
              class="kw"
              :prefix-icon="Search"
            />
          </div>

          <table class="sp-table">
            <thead>
              <tr>
                <th>工单</th>
                <th>场地 / 设备</th>
                <th>AI 结论</th>
                <th>状态</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in filteredTickets" :key="row.id">
                <td>#{{ row.id }}</td>
                <td>
                  <div>
                    {{ spaceMap[row.spaceId] || (row.spaceId ? `场地ID ${row.spaceId}` : '场地未知') }}
                    ·
                    {{ row.deviceName || (row.deviceId ? `设备ID ${row.deviceId}` : '未关联设备') }}
                  </div>
                  <!-- 巡检报告是长文本，列表里只给一行摘要 + 悬停看全文，避免撑高表格 -->
                  <div v-if="row.report" class="cell-sub" :title="row.report">{{ row.report }}</div>
                </td>
                <td>
                  <span
                    v-if="row.deviceStatus"
                    class="sp-tag"
                    :class="judgeTagClass(row.deviceStatus)"
                  >
                    {{ row.deviceStatus }}
                  </span>
                  <span v-else class="sp-muted">—</span>
                </td>
                <td>
                  <span class="sp-tag" :class="ticketTagClass(row)">{{ row.statusText || '—' }}</span>
                </td>
                <td>{{ row.createTime || '—' }}</td>
                <td>
                  <button
                    class="sp-btn is-ghost is-sm"
                    :disabled="row.status === 3"
                    @click="handleTicket(row)"
                  >
                    处理
                  </button>
                </td>
              </tr>
              <tr v-if="!filteredTickets.length">
                <td colspan="6" class="empty-cell">
                  {{
                    tickets.length
                      ? '没有匹配该关键字的工单，换个关键词试试'
                      : '暂无维修工单，提交巡检后自动生成'
                  }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 提交巡检弹窗 -->
    <el-dialog v-model="inspectDialog.visible" title="提交 AI 巡检" width="480px">
      <el-form label-width="90px">
        <el-form-item label="所属场地">
          <el-select v-model="inspectDialog.spaceId" placeholder="请选择场地" style="width: 100%">
            <el-option
              v-for="space in spaces"
              :key="space.spaceId"
              :label="space.spaceName"
              :value="space.spaceId"
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
      <div v-for="row in resultRows" :key="row.k" class="sp-mbrow">
        <span class="sp-k">{{ row.k }}</span>
        <span class="sp-v">
          <span v-if="row.cls" class="sp-tag" :class="row.cls">{{ row.v }}</span>
          <template v-else>{{ row.v }}</template>
        </span>
      </div>
      <div v-if="aiResult.report" class="dialog-report">
        <div class="sp-section-title">分析报告</div>
        <p class="summary-text">{{ aiResult.report }}</p>
      </div>
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
import { spacesOf } from '@/utils/normalize'

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
    map[item.spaceId] = item.spaceName
  })
  return map
})

const filteredTickets = computed(() => {
  const kw = keyword.value?.trim()
  if (!kw) return tickets.value
  return tickets.value.filter(
    // ⚠️ `report` 可能是 **null**：后端 list_tickets 用 LEFT JOIN 取巡检记录，
    //    手工建的工单没有关联巡检记录，`ai.get("report")` 就是 None
    //    （schemas/inspect.py 里类型是 `str | None`）。
    //    直接 `.includes()` 会在用户**一敲搜索框**时抛 TypeError，把整页打白。
    //    实测说明：当前种子库那 3 条工单**恰好都有** report，所以这个洞现在不会响；
    //    但 list_tickets 的 LEFT JOIN 注释本身就写明「关联巡检记录被清理掉时工单仍要出现」，
    //    且 `TicketItem.report` 的类型就是 `str | None` —— 这是**契约允许**的空值，
    //    属于等着被触发的定时炸弹，顺手补掉。
    (item) => String(item.id).includes(kw) || String(item.report || '').includes(kw),
  )
})

// —— 以下为视觉改造新增的辅助函数，未改动任何已有逻辑 ——

// 接口不返回巡检照片的 URL，只能拿用户本地选中的原始文件做预览。
// 按 File 对象身份缓存 objectURL：换图时释放上一张，避免每次重算都新建 URL 造成内存泄漏。
let previewFile = null
let previewObjectUrl = ''
const previewUrl = computed(() => {
  const file = uploadFile.value
  if (!file) {
    if (previewObjectUrl) {
      URL.revokeObjectURL(previewObjectUrl)
      previewObjectUrl = ''
      previewFile = null
    }
    return ''
  }
  if (file !== previewFile) {
    if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl)
    previewObjectUrl = URL.createObjectURL(file)
    previewFile = file
  }
  return previewObjectUrl
})

// 本次巡检建出的那张工单。工单列表已在提交后重新拉取，能从里面取回真实的场地 / 设备，
// 不必拿下拉框的当前选中值充当结论。
const resultTicket = computed(
  () => tickets.value.find((item) => item.id === aiResult.ticketId) || null,
)

const resultSpaceName = computed(() => {
  const spaceId = resultTicket.value?.spaceId
  if (!spaceId) return ''
  return spaceMap.value[spaceId] || `场地ID ${spaceId}`
})

// 识别结论行：左侧面板与结果弹窗共用同一份真实字段，避免同一套文案在两处各写一遍后漂移。
// 契约只有 deviceStatus / repairSuggestion / ticketId 等少数几项，查不到真实值的行整行不出。
const resultRows = computed(() => {
  if (!aiResult.deviceStatus) return []
  const rows = [
    { k: '设备状态', v: aiResult.deviceStatus, cls: judgeTagClass(aiResult.deviceStatus) },
  ]
  const ticket = resultTicket.value
  if (ticket) {
    if (resultSpaceName.value) rows.push({ k: '关联场地', v: resultSpaceName.value })
    const device = ticket.deviceName || (ticket.deviceId ? `设备ID ${ticket.deviceId}` : '')
    if (device) rows.push({ k: '设备', v: device })
  }
  rows.push({ k: '维修建议', v: aiResult.repairSuggestion || '无需维修' })
  rows.push(
    aiResult.ticketId
      ? { k: '生成工单', v: `#${aiResult.ticketId}`, cls: 'is-blue' }
      : { k: '生成工单', v: `未生成 —— 判定为「${aiResult.deviceStatus}」，无需维修` },
  )
  return rows
})

// 工单计数按真实状态统计，标题右侧的标签为 0 时不渲染
const waitingCount = computed(() => tickets.value.filter((item) => item.status === 1).length)
const processingCount = computed(() => tickets.value.filter((item) => item.status === 2).length)

// 设计系统的标签配色（is-green / is-red / …）与 Element 的 tag type 是两套取值，这里只做翻译，
// 判定口径仍复用既有的 judgeTagType / ticketTagType，避免两处规则日后各改一半。
const SP_TAG_BY_EL_TYPE = {
  success: 'is-green',
  warning: 'is-orange',
  danger: 'is-red',
  info: 'is-gray',
}

/** 巡检判定 → sp- 标签配色。「缺失配件」同属异常，设计稿里也是红系，故不落回默认灰。 */
function judgeTagClass(deviceStatus) {
  if (deviceStatus === '缺失配件') return 'is-red'
  return SP_TAG_BY_EL_TYPE[judgeTagType(deviceStatus)] || 'is-gray'
}

/** 工单状态 → sp- 标签配色。「处理中」在设计稿里是橙色，故单独提色。 */
function ticketTagClass(row) {
  if (row.status === 2) return 'is-orange'
  return SP_TAG_BY_EL_TYPE[ticketTagType(row.status)] || 'is-gray'
}

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
  ElMessage.success(`工单 #${row.id} 已标记完成`)
  // ⚠️ **必须重新拉列表。**
  // 真实接口会真的落库，但**列表是本地数组**，不重新拉就一直是旧状态 ——
  // 表现就是「点了处理，状态标签没变」。
  // 原提示语写着「mock 数据为常量，列表不实时变化」，那是 Mock 时代的说法，
  // 现在后端是真的，不刷新属于**前端漏了一步**，不是设计如此。
  await loadTickets()
}

/** 巡检判定 → 标签配色。「完好」不该显示成红色告警。 */
function judgeTagType(deviceStatus) {
  if (deviceStatus === '完好') return 'success'
  if (deviceStatus === '损坏') return 'danger'
  return 'info' // 缺失配件 / 无法识别
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
    // 真实接口 /resources/spaces 返回的是**裸数组**（不是 {list:[…]}），
    // 且字段是 spaceId/spaceName —— 详见 utils/normalize.js 顶部的对照表。
    // 原先写 `spacesData.list || []` 会拿到 undefined，**不报错、只是下拉框空**。
    spaces.value = spacesOf(spacesData)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
/* 标题块与「提交巡检」按钮同排；说明文字挂在标题下面 */
.page-titles .sp-page-sub {
  margin: 5px 0 0;
  max-width: 620px;
}

/* 原型是左右两栏：左栏定宽容纳照片与识别结论，右栏自适应放摘要和表格 */
.inspect-grid {
  display: grid;
  grid-template-columns: 392px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: 13px;
  min-width: 0;
}

/* 设计系统只给了 .sp-imgbox 的外观，高度按原型的 296px 在本页补 */
.photo-box {
  height: 296px;
}

.photo-box img {
  display: block;
}

/* 接口不返回真实检测坐标，识别框只居中示意，所以不照搬原型写死的百分比 */
.photo-box .sp-bbox {
  left: 50%;
  top: 50%;
  width: 52%;
  height: 46%;
  transform: translate(-50%, -50%);
}

.empty-tip {
  margin: 0;
}

.summary-text {
  font-size: 12.5px;
  color: var(--sp-t2);
  line-height: 1.9;
  margin: 0 0 8px;
}

.summary-text:last-child {
  margin-bottom: 0;
}

.summary-num {
  color: var(--sp-accent);
}

.cell-sub {
  margin-top: 3px;
  max-width: 300px;
  font-size: 11.5px;
  color: var(--sp-t3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.empty-cell {
  padding: 26px 12px;
  text-align: center;
  color: var(--sp-t3);
}

.kw {
  width: 210px;
  flex: none;
}

.dialog-report {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--sp-border-l);
}

/* 窄屏下改为上下堆叠，避免左栏 392px 把表格挤扁 */
@media (max-width: 1180px) {
  .inspect-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .photo-box {
    height: 240px;
  }
}
</style>
