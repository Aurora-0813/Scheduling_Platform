<template>
  <div v-loading="loading">
    <div class="sp-pagebar">
      <div class="page-titles">
        <h3>AI 智能巡检 · 维修工单</h3>
        <p class="sp-page-sub">
          上传巡检照片，AI 自动判定故障并生成维修建议与工单
        </p>
      </div>
      <div class="sp-acts">
        <button class="sp-btn is-ai is-sm" @click="openInspectDialog">
          <el-icon><Camera /></el-icon>提交巡检
        </button>
      </div>
    </div>

    <div class="inspect-grid">
      <!-- ===== 左栏：现场照片 + 多模态识别结论 ===== -->
      <div class="col-left">
        <!--
          整个照片框就是「提交巡检」的入口：点它打开提交弹窗，与右上角那个
          「提交 AI 巡检」按钮同一个动作（都是把 inspectDialog.visible 置 true）。

          用真实的 <button> 而不是给 div 挂 @click：键盘 Tab 可达、回车/空格可触发、
          读屏能念出用途，这些都是原生按钮白送的。类型必须显式写 type="button"，
          否则在表单里会被当提交按钮。

          注意按钮内的交互内容都必须在 `.sp-imgbox` 这个子元素里：`overflow: hidden`
          与 `position: relative` 都在它身上，识别框（`.sp-bbox`）与扫描线要靠它定位。
        -->
        <button
          type="button"
          class="photo-box photo-trigger"
          aria-label="提交 AI 巡检"
          title="点击提交巡检照片"
          @click="openInspectDialog"
        >
          <div class="sp-imgbox">
            <!-- 提交巡检的响应只有 deviceStatus / report / repairSuggestion / ticketId，不含图片地址；
                 这里预览的是用户本地上传的原始文件（真实图片），没有文件才退回相机空态。 -->
            <img v-if="previewUrl" :src="previewUrl" alt="巡检照片" />
            <div v-else class="sp-cam">
              <span>◈</span>
              点击此处 · 提交巡检照片
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
        </button>

        <div class="sp-card">
          <div class="sp-card-head"><b>识别结论</b></div>
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
            <b>巡检摘要</b>
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
            <b>维修工单列表</b>
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
                  <button class="sp-btn is-ghost is-sm" type="button" @click="openTicketDetail(row)">
                    详情
                  </button>
                  <button
                    class="sp-btn is-ghost is-sm"
                    type="button"
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

    <!--
      工单详情（2026-10-10 加）：让用户看清「到底哪台设备、坏成什么样」。
      列表里的「AI 结论」是一列标签 + 一行截断的 report，撑不下完整故障信息；
      详情弹窗把整条巡检结论、关联设备/场地、以及**处理与核验记录**一并摊开。
    -->
    <el-dialog v-model="ticketDetail.visible" title="维修工单详情" width="640px">
      <template v-if="ticketDetail.row">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="工单号">#{{ ticketDetail.row.id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <span class="sp-tag" :class="ticketTagClass(ticketDetail.row)">
              {{ ticketDetail.row.statusText || '—' }}
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="场地">
            {{
              spaceMap[ticketDetail.row.spaceId] ||
              (ticketDetail.row.spaceId ? `场地ID ${ticketDetail.row.spaceId}` : '—')
            }}
          </el-descriptions-item>
          <el-descriptions-item label="设备">
            {{
              ticketDetail.row.deviceName ||
              (ticketDetail.row.deviceId ? `设备ID ${ticketDetail.row.deviceId}` : '未关联设备')
            }}
          </el-descriptions-item>
          <el-descriptions-item label="具体位置">
            <!-- 电路/插座/门把手这类不在设备台账里的固定设施，靠它定位到「哪一个」 -->
            {{ ticketDetail.row.locationHint || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="AI 判定">
            <span
              v-if="ticketDetail.row.deviceStatus"
              class="sp-tag"
              :class="judgeTagClass(ticketDetail.row.deviceStatus)"
            >
              {{ ticketDetail.row.deviceStatus }}
            </span>
            <span v-else class="sp-muted">—</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ ticketDetail.row.createTime || '—' }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="td-sec">
          <h4>AI 巡检结论</h4>
          <p v-if="ticketDetail.row.report" class="td-text">{{ ticketDetail.row.report }}</p>
          <p v-else class="sp-muted">该工单没有关联的巡检结论。</p>
          <!--
            原始巡检照片（2026-10-13 新增）：来自关联巡检记录的 image_url。
            工单表不存这一列，是后端靠 inspect_id JOIN 回巡检记录透出来的。
            照片在巡检提交时就已落盘，这里只是把它显示出来，方便管理员核对。
          -->
          <img
            v-if="ticketDetail.row.inspectImageUrl"
            class="td-photo"
            :src="ticketDetail.row.inspectImageUrl"
            alt="巡检照片"
          />
        </div>

        <!--
          AI 核验记录：仅在走过「上传维修照片 + 核验」这条路径后才有。
          ⚠️ 这里**没有**「维修建议」一节 —— `TicketItem` schema 里没有
             repairSuggestion 字段（那是 `submit_inspection` 的**响应**字段，
             工单列表不返回）。前端不去拼一个不存在的东西。
        -->
        <div v-if="ticketDetail.row.verifyReport || ticketDetail.row.handleImageUrl" class="td-sec">
          <h4>维修核验</h4>
          <p class="sp-muted">
            核验状态：{{ ticketDetail.row.verifyStatus || '—' }}
          </p>
          <p v-if="ticketDetail.row.verifyReport" class="td-text">
            {{ ticketDetail.row.verifyReport }}
          </p>
          <img
            v-if="ticketDetail.row.handleImageUrl"
            class="td-photo"
            :src="ticketDetail.row.handleImageUrl"
            alt="处理后照片"
          />
        </div>
      </template>
      <template #footer>
        <el-button @click="ticketDetail.visible = false">关闭</el-button>
      </template>
    </el-dialog>

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
        <el-form-item label="巡检设备">
          <el-select
            v-model="inspectDialog.deviceId"
            placeholder="可不选（不选则按 AI 识别结果匹配）"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="d in devices"
              :key="d.deviceId"
              :label="d.deviceName"
              :value="d.deviceId"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="具体位置">
          <el-input
            v-model="inspectDialog.locationHint"
            placeholder="可选，如 3楼走廊东侧"
            maxlength="40"
          />
        </el-form-item>
        <el-form-item label="巡检照片">
          <el-upload
            ref="inspectUploadRef"
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

    <!-- ==================== 提交处理结果（维修后照片） ==================== -->
    <el-dialog v-model="handleDialog.visible" title="提交处理结果" width="480px">
      <div v-if="handleDialog.ticket" class="handle-target">
        <div class="sp-mbrow">
          <span class="sp-k">工单</span>
          <span class="sp-v">#{{ handleDialog.ticket.id }}</span>
        </div>
        <div class="sp-mbrow">
          <span class="sp-k">场地 / 设备</span>
          <span class="sp-v">
            {{ spaceMap[handleDialog.ticket.spaceId] || '场地未知' }}
            ·
            {{ handleDialog.ticket.deviceName || '未关联设备' }}
          </span>
        </div>
        <!-- 把原巡检结论摆出来，处理人对着修，AI 也拿它当对照基准 -->
        <div v-if="handleDialog.ticket.report" class="dialog-report">
          <div class="sp-section-title">维修前的巡检结论</div>
          <p class="summary-text">{{ handleDialog.ticket.report }}</p>
        </div>
      </div>

      <el-form label-width="90px">
        <el-form-item label="处理后照片">
          <el-upload
            ref="handleUploadRef"
            :auto-upload="false"
            :limit="1"
            accept="image/*"
            list-type="picture-card"
            :on-change="onHandleFileChange"
            :on-remove="onHandleFileRemove"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
        </el-form-item>
      </el-form>

      <p class="sp-muted handle-hint">
        AI 会核验设备是否已修好。<b>核验通过</b>才会把工单置为已完成；
        未通过则保持当前状态，你可以重拍再传。
      </p>

      <template #footer>
        <el-button @click="handleDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="handling" @click="submitHandle">
          提交并核验
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== AI 核验结果 ==================== -->
    <el-dialog v-model="verifyDialog.visible" title="AI 核验结果" width="520px">
      <template v-if="verifyResult">
        <!--
          成功 / 失败用同一套配色语义：通过=绿、未通过=红，
          与列表里的判定标签（judgeTagClass）保持一致，不另立一套颜色。
        -->
        <div class="sp-witem verify-banner" :class="verifyResult.passed ? 'is-green' : 'is-red'">
          <span class="verify-ic">{{ verifyResult.passed ? '通过' : '待确认' }}</span>
          <div>
            <b>{{ verifyResult.passed ? '核验通过，工单已完成' : '核验未通过，工单状态未变更' }}</b>
            <p>{{ verifyResult.message }}</p>
          </div>
        </div>

        <div class="sp-mbrow">
          <span class="sp-k">工单</span>
          <span class="sp-v">#{{ verifyResult.id }}</span>
        </div>
        <div class="sp-mbrow">
          <span class="sp-k">AI 判定</span>
          <span class="sp-v">
            <span v-if="verifyResult.verifyStatus" class="sp-tag" :class="judgeTagClass(verifyResult.verifyStatus)">
              {{ verifyResult.verifyStatus }}
            </span>
            <!-- 模型不可用时没有判定值，此时**不能**假装设备损坏：
                 只说明「这次没验成」，原因在下面的核验说明里 -->
            <span v-else class="sp-tag is-gray">未完成核验</span>
          </span>
        </div>
        <div class="sp-mbrow">
          <span class="sp-k">工单状态</span>
          <span class="sp-v">
            <span class="sp-tag" :class="verifyResult.status === 3 ? 'is-green' : 'is-orange'">
              {{ verifyResult.statusText }}
            </span>
          </span>
        </div>

        <div v-if="verifyResult.verifyReport" class="dialog-report">
          <div class="sp-section-title">核验说明</div>
          <p class="summary-text">{{ verifyResult.verifyReport }}</p>
        </div>
      </template>

      <template #footer>
        <el-button v-if="verifyResult && !verifyResult.passed" @click="reopenHandleFromVerify">
          重拍再传
        </el-button>
        <el-button type="primary" @click="verifyDialog.visible = false">知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { Camera, Plus, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

// ⚠️ API 函数 `handleTicket` 必须**重命名导入**：本文件另有一个同名的
//    点击处理器 `function handleTicket(row)`（打开弹窗用）。
//    直接同名导入会被局部声明遮蔽，`submitHandle` 里那一行就变成**调用它自己** ——
//    JS 不报错，只是弹窗反复打开、请求永远发不出去。
//
// 不再导入 `updateTicketStatus`：本页的「处理」已改为「传照片 + AI 核验」，
// 不走那条「直接标完成」的路径了。**后端接口仍然保留**
// （`PUT /tickets/{id}/status`），供「到场发现是误报、直接标记完成」这类
// 人工判断使用，只是本页不再调它 —— 所以这里去掉 import 而不是删掉那个函数。
import { getTickets, handleTicket as submitTicketHandle, submitInspect } from '@/api/inspect'
import { getDevices, getSpaces } from '@/api/resources'
import { spacesOf } from '@/utils/normalize'

const loading = ref(false)
const submitting = ref(false)
const keyword = ref()

const tickets = ref([])
const spaces = ref([])
// 巡检设备下拉的候选：只列「完好且还有可借台数」的（损坏/维修中的不该再被选中）
const devices = ref([])
const uploadFile = ref(null)

// deviceId / locationHint 是 2026-10-13 新增的。
// deviceId：照片里两台投影仪长得一样，模型只报得出「投影仪」这个品类，
//   后端拿它匹配会命中 4 台、只能自动分配（挑 id 最小的）→ 坏的是 03 却把 01 标损坏。
//   由人来选/扫码才准。不选也能提交（退回原来的 AI 模糊匹配）。
// locationHint：插座/门把手这类不在台账里的固定设施，位置是唯一的精度来源。
const inspectDialog = reactive({ visible: false, spaceId: null, deviceId: null, locationHint: '' })
const resultDialog = reactive({ visible: false })
const aiResult = reactive({})

// ---------- 处理工单：提交维修后照片 + AI 核验 ----------
const handling = ref(false)
//: 当前正在处理的工单（整行），弹窗里要显示它的场地 / 设备 / 原巡检结论
const handleDialog = reactive({ visible: false, ticket: null })
const handleFile = ref(null)
const verifyDialog = reactive({ visible: false })
const verifyResult = ref(null)

/**
 * 工单详情弹窗（2026-10-10 加）。
 *
 * `row` 直接放列表里的那一行对象 —— `/tickets/list` 的 `TicketItem` 已经带全
 * 详情所需的字段（report / handleImageUrl / verifyStatus / verifyReport），
 * **不需要再打一次接口**。列表里那行只是被 CSS 截断显示，数据本身是完整的。
 */
const ticketDetail = reactive({ visible: false, row: null })

// 两个 <el-upload> 的组件实例。
// ⚠️ **必须用 ref 才能清空它们的文件列表**：`uploadFile` / `handleFile`
//    只保存了我自己需要的 File 对象，上传框里那张缩略图是 el-upload 的**内部状态**
//    （`uploadFiles` 列表），不受这两个变量控制。不清它，下次打开弹窗
//    上一张图还挂在那里 —— 看起来像「历史记录没清掉」。
const inspectUploadRef = ref(null)
const handleUploadRef = ref(null)

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

// 离开本页时释放最后一张 objectURL。
// `previewUrl` 只在「文件变了」或「文件被清空」时释放旧的，而清空那一步依赖
// computed 被重新求值 —— 组件卸载后不会再求值，最后一张 URL 就会一直挂着，
// 把 File 背后的内存钉住不放。
onUnmounted(() => {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl)
    previewObjectUrl = ''
    previewFile = null
  }
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
  rows.push({ k: '生成工单', ...ticketRow() })
  // 设备台账**部分成功**时的提示。目前两种来源：
  //   ① 可借数已是 0、已有人报修 —— 本次只记录故障、未再减可借数；
  //   ② 命中的设备全部已在维修处理中 —— 本次未重复建单。
  // 不回显的话，用户看到「工单没建 / 可借数没变」会以为是 bug。
  if (aiResult.deviceWarning) {
    rows.push({ k: '设备台账', v: aiResult.deviceWarning, cls: 'is-orange' })
  }
  return rows
})

/**
 * 「生成工单」那一行的内容。
 *
 * ⚠️ 原实现在没有 ticketId 时**一律**写「未生成 —— 判定为「X」，无需维修」。
 *    这在 2026-10-10 之后会**说谎**：新增了「命中的设备全部已在维修处理中 →
 *    不重复建单」这条路径，那种情况是**有损坏、也已有人管**，不是「无需维修」。
 *    文案必须分开，否则用户会以为设备没事。
 *
 * 三种情况：
 *   ① 建了单        → 显示工单号
 *   ② 未建单 + 已在维修中 → 说明已在工单列表中（不改台账，也不重复建单）
 *   ③ 未建单 + 其它   → 名字没匹配上台账里的设备（既有行为，保持原文案）
 */
function ticketRow() {
  if (aiResult.ticketId) {
    return { v: `#${aiResult.ticketId}`, cls: 'is-blue' }
  }
  // 与后端 `_sync_device_status` 的 warning 同源；这里只做**展示**分支，
  // 不参与任何业务判断（业务判断在后端用原因码做，见 REASON_ALL_IN_REPAIR）。
  const warn = String(aiResult.deviceWarning || '')
  if (warn.includes('已在维修工单列表')) {
    return { v: '未重复建单 —— 该设备已在维修工单列表中处理', cls: 'is-orange' }
  }
  return { v: `未生成 —— 判定为「${aiResult.deviceStatus}」，无需维修` }
}

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

/**
 * 打开「提交 AI 巡检」弹窗。
 *
 * `el-dialog` **没有 destroy-on-close**，所以弹窗关闭时里面的一切都还在，
 * 包括 `<el-upload>` 内部的文件列表。不清它，上次挑的那张缩略图会留在
 * 上传框里，看起来像「历史记录没清掉」。
 *
 * 为什么把「清空」放在**打开时**而不是关闭时：
 * 关闭有三条路径（取消 / 提交成功 / 点遮罩），逐个挂钩子会漏。
 * 打开只有一条路径，挂在这里不会漏。
 */
function openInspectDialog() {
  inspectUploadRef.value?.clearFiles()
  uploadFile.value = null
  // 设备 / 位置也要清：上一次选的设备留着，下一次提交会**静默地报错那一台**
  inspectDialog.deviceId = null
  inspectDialog.locationHint = ''
  inspectDialog.visible = true
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
    const data = await submitInspect(
      uploadFile.value,
      inspectDialog.spaceId,
      inspectDialog.deviceId,
      inspectDialog.locationHint,
    )
    Object.assign(aiResult, data)
    inspectDialog.visible = false
    resultDialog.visible = true
    await loadTickets()
  } finally {
    submitting.value = false
  }
}

/**
 * 点「处理」 → 打开「提交处理结果」弹窗（**不是**直接标记完成）。
 *
 * 口径变更（业务已确认）：处理完成需要有凭据 —— 维修后拍一张照片，
 * 由 AI 核验是否真的修好了。核验通过后端才把工单置为已完成。
 *
 * ⚠️ 原实现是直接调 `updateTicketStatus(row.id, { status: 3 })` 把工单标完成，
 * 不接受任何照片。那条路径**后端仍然保留**（`PUT /tickets/{id}/status`），
 * 用于「到场发现是误报、直接标记完成」这类人工判断 ——
 * 只是本页的按钮不再走它，避免「点一下就算修好了」。
 */
function handleTicket(row) {
  openHandleDialog(row)
}

/**
 * 打开「工单详情」弹窗。
 *
 * 只读：不做任何请求、不改任何状态 —— 列表行本身就是完整的 `TicketItem`。
 */
function openTicketDetail(row) {
  ticketDetail.row = row
  ticketDetail.visible = true
}

/**
 * 打开「提交处理结果」弹窗，并**清空上一次留下的照片**。
 *
 * 与 `openInspectDialog` 同样的理由：`el-dialog` 没开 destroy-on-close，
 * `<el-upload>` 的内部文件列表会跨开关存活，不清就会看到
 * 「点了处理，上次传的图还挂在那儿」。清空放在打开时，三条关闭路径都不用管。
 */
function openHandleDialog(row) {
  handleUploadRef.value?.clearFiles()
  handleFile.value = null
  handleDialog.ticket = row
  handleDialog.visible = true
}

function onHandleFileChange(fileItem) {
  handleFile.value = fileItem.raw
}

function onHandleFileRemove() {
  handleFile.value = null
}

/**
 * 提交处理结果照片 → 后端调 AI 核验 → 展示核验结果。
 *
 * 后端在**核验未通过时不改工单状态**，所以这里无论成败都要重新拉列表：
 * 通过时状态会从 1/2 变成 3，未通过时状态不变 —— 不重拉的话，
 * 通过的那种情况下列表还显示旧状态，用户会以为没生效。
 */
async function submitHandle() {
  if (!handleFile.value) {
    ElMessage.warning('请上传处理后的照片')
    return
  }
  const ticketId = handleDialog.ticket?.id
  if (!ticketId) return

  handling.value = true
  try {
    const res = await submitTicketHandle(ticketId, handleFile.value)
    // passMessage 打开后返回 { data, message }：判定结论在后端算好，
    // 前端不自己拿 verifyStatus 和字符串比（那是第二处口径）。
    verifyResult.value = { ...(res.data || {}), message: res.message || '' }
    handleDialog.visible = false
    verifyDialog.visible = true
    await loadTickets()
  } finally {
    handling.value = false
  }
}

/** 核验未通过 → 直接把弹窗切回「提交处理结果」，处理人不必自己找那一行。 */
function reopenHandleFromVerify() {
  verifyDialog.visible = false
  openHandleDialog(tickets.value.find((item) => item.id === verifyResult.value?.id) || null)
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
    const [spacesData, devicesData] = await Promise.all([
      getSpaces(),
      getDevices(),
      loadTickets(),
    ])
    // 真实接口 /resources/spaces 返回的是**裸数组**（不是 {list:[…]}），
    // 且字段是 spaceId/spaceName —— 详见 utils/normalize.js 顶部的对照表。
    // 原先写 `spacesData.list || []` 会拿到 undefined，**不报错、只是下拉框空**。
    spaces.value = spacesOf(spacesData)
    // /resources/devices 的形状与 /resources/spaces 一样是**裸数组**，这里两种都兼容。
    // 只留「完好 + 有可借台数」的：损坏的、已在维修中的不该再被巡检选中。
    const rawDevices = Array.isArray(devicesData) ? devicesData : (devicesData || {}).list || []
    devices.value = rawDevices.filter(
      (d) => d.deviceStatus === 1 && (d.availableCount || 0) > 0,
    )
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
  gap: var(--sp-s3);
  align-items: start;
}

.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: var(--sp-s3);
  min-width: 0;
}

/* 设计系统只给了 .sp-imgbox 的外观，高度按原型的 296px 在本页补 */
.photo-box {
  height: 296px;
}

/*
 * 照片框本身是「提交巡检」的入口。这里是把它作为**按钮**所需的复位：
 * 浏览器默认按钮带 border / padding / 背景 / 居中文字，不清掉就会在
 * 设计好的照片框外面套一圈灰边。
 * 交互反馈只做「边框提色 + 相机图标变清晰」，不动布局，避免和内部的
 * 识别框、扫描线抢视觉。
 */
.photo-trigger {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  color: inherit;
  cursor: pointer;
  appearance: none;
}

.photo-trigger .sp-imgbox {
  height: 100%;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

/* 悬停 / 键盘聚焦：给一个明确「这里能点」的信号，两者用同一种表现 */
.photo-trigger:hover .sp-imgbox,
.photo-trigger:focus-visible .sp-imgbox {
  border-color: var(--sp-accent);
  box-shadow: var(--sp-focus);
}

.photo-trigger:focus-visible {
  outline: none;
  border-radius: var(--sp-r-md);
}

.photo-trigger:hover .sp-cam span,
.photo-trigger:focus-visible .sp-cam span {
  opacity: 0.85;
}

.photo-trigger:active .sp-imgbox {
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.34);
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
  font-size: 12px;
  color: var(--sp-t3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ---- 工单详情弹窗（2026-10-10 加）---- */

/* 一节一块：标题 + 正文。用块级分隔而不是 <el-descriptions> 是因为
   报告是长文本，按描述项那套「标签: 值」的窄格子排版会挤成一条竖线。 */
.td-sec {
  margin-top: 16px;
}

.td-sec h4 {
  margin: 0 0 6px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--sp-t1);
}

/* 长报告要换行并保留原样里的换行（AI 常按条列写） */
.td-text {
  margin: 0;
  line-height: 1.75;
  font-size: 13px;
  color: var(--sp-t2);
  white-space: pre-wrap;
  word-break: break-word;
}

.td-photo {
  display: block;
  margin-top: 8px;
  max-width: 100%;
  max-height: 260px;
  border-radius: var(--sp-r-sm);
  border: 1px solid var(--sp-border-l);
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

/* ---------------- 处理结果提交 / AI 核验 ---------------- */

.handle-target {
  margin-bottom: 4px;
}

.handle-hint {
  margin: 0;
  line-height: 1.8;
}

/*
 * 核验结论横幅：直接复用设计系统的告警条目 `.sp-witem`（见 styles/index.css），
 * 只补一条 `.is-green` 给「核验通过」用 —— 它原先只有 warning / is-red / is-blue。
 * 不另起一套 .verify-banner 配色：同一件事在列表和弹窗里颜色不同，
 * 是这类页面最容易积累的不一致。
 */
.verify-banner {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-s2);
}

.verify-ic {
  font-size: 17px;
  line-height: 1.3;
  flex: none;
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
