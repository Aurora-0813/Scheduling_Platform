<template>
  <view class="app-page">
    <mp-nav-bar title="AI 智能巡检" />

    <view class="app-body">
      <view v-if="!canInspect()" class="mini-empty" style="padding-top: 140rpx;">
        <text class="ei">🔒</text>
        <text class="et">仅管理员与系统管理员可查看巡检内容</text>
      </view>
      <template v-else>
      <!-- 入口：取景框视觉来自原型 M5。
           2026-10-06：**去掉了下面那个「开始拍照巡检」按钮** ——
           它与这个取景框是同一个 `goCapture`，功能完全重复。
           取景框本身就是入口（`.entry` 加了 hover 反馈），少一个按钮更干净。 -->
      <view class="imgbox entry" hover-class="btn-on" :hover-stay-time="60" @tap="goCapture">
        <view class="cam">
          <text class="big">📷</text>
          <text>拍下设备，AI 自动识别状态并生成工单</text>
        </view>
        <!-- 四个角标必须排在最前：theme.css 用 :nth-child(1..4) 定位四角，
             标签条插在中间会把序号错位 -->
        <view class="bbox">
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <view class="cn"></view>
          <text class="lbl">对准设备</text>
        </view>
        <view class="scanline"></view>
      </view>

      <!--
        工单列表。**结构对齐「我的预约」（pages/order/list.vue）**（2026-10-14 改）：
        之前是所有工单挤在一个 .mcard 里、靠 .ticket.sep 的分隔线与 padding 区分，
        现在改成**一条工单一张卡**（.mcard），与预约卡片同一种观感。

        「维修工单 / 刷新」这一行仍留在外面：它是这一段的标题，
        不属于任何单条工单；同时保留 loading / 未登录 / 空态三支的原有位置。
      -->
      <view class="mcard sec">
        <view class="mtitle">
          <text>维修工单</text>
          <text class="more" @tap="load">{{ loading ? '刷新中…' : '刷新' }}</text>
        </view>
      </view>

      <view v-if="loading" class="mcard">
        <text class="mtext">加载中…</text>
      </view>

      <!-- 未登录不是「没有工单」，单独一支（放在空态之前） -->
      <view v-else-if="!userStore.loggedIn" class="mcard">
        <view class="mini-empty">
          <text class="ei">🔑</text>
          <text class="et">登录后查看维修工单</text>
        </view>
      </view>

      <view v-else-if="!tickets.length" class="mcard">
        <view class="mini-empty">
          <text class="ei">🧰</text>
          <text class="et">暂无维修工单，设备一切正常</text>
        </view>
      </view>

      <!--
        ⚠️ 这里必须是 <view v-else> 而不是 <template v-else>：
        v-else / v-else-if 链要求各分支**直接相邻**，中间不能隔已闭合的兄弟节点。
        上面那个空态分支是 <view v-else-if>（自成一张卡），它闭合之后，
        这里就得是同一个链上的下一个兄弟 —— 用 <view> 正好也是「一张卡」。
      -->
      <view v-else>
        <!--
          一条工单一张卡（.mcard），字段全部走 .mbrow 键值行 ——
          与「我的预约」的卡片逐项对齐：标题行 + 若干键值行 + 右对齐动作行。
        -->
        <view
          v-for="t in tickets"
          :key="t.id"
          class="mcard"
        >
          <!-- 标题行：设备名 + 状态标签（对应预约卡的场地名 + 状态） -->
          <view class="thead">
            <text class="tname">{{ t.deviceName || '未知设备' }}</text>
            <text class="tag" :class="statusTag('ticket', t.status, t.statusText)">
              {{ statusLabel('ticket', t.status, t.statusText) }}
            </text>
          </view>

          <!--
            原先这里是两行自由文本（.tno 的「工单 #id · 空间 · 位置」+ .tdesc 的说明），
            没有标签、左对齐，和预约卡的键值行不是一个观感。现在按语义拆成键值行：

            ⚠️ 2026-09-30 旧注：空间名不能读 t.spaceName —— /tickets/list 的 TicketItem
               **只有 spaceId**（没有 spaceName），必须经 utils/nameMap.js 查表补名。
          -->
          <view class="mbrow">
            <text class="k">位置</text>
            <text class="v">
              {{ spaceLabel(t.spaceId) }}{{ t.locationHint ? ' · ' + t.locationHint : '' }}
            </text>
          </view>

          <view v-if="t.deviceStatus" class="mbrow">
            <text class="k">设备状态</text>
            <text class="v">{{ t.deviceStatus }}</text>
          </view>

          <view v-if="t.report" class="mbrow">
            <text class="k">巡检结论</text>
            <!--
              user-select：这段是 AI 对画面的整段描述（实测 113~133 字），
              属于「用户可能想复制去报修群/工单系统」的长文本。
              不加的话微信开发者工具会给一条「text 组件包含了长文本，
              可以考虑增加 user-select 属性」的建议（不是错误，但会刷控制台）。
            -->
            <text class="v" user-select>{{ t.report }}</text>
          </view>

          <view v-if="t.createTime" class="mbrow">
            <text class="k">报修时间</text>
            <text class="v">{{ relativeTime(t.createTime) }}</text>
          </view>
            <!--
              ⚠️ 2026-09-30 删掉了「维修建议」一行：原代码读 t.repairSuggestion，
              但该字段只存在于 /inspect/submit 的返回（InspectSubmitData），
              **不在 TicketItem 里**，所以 v-if 恒为 false、永远不渲染。
              工单里能反映 AI 结论的字段是 report（来自关联的巡检记录），上面那行已经覆盖。
            -->

          <view v-if="canFinish(t)" class="oa">
            <!--
              ⚠️ 这里原先还有一处「处理人」文字（.who），本轮删掉：TicketItem 里
                 **没有** handlerName（handlerId 只出现在 PUT /tickets/{id}/status 的响应里），
                 要显示处理人得后端在列表里补字段 —— 本轮不自行发明。留着它只会占位。
            -->
            <!--
              两个动作（2026-10-06 对齐 Web 端）：
                · 拍照核验 —— **机器判定**：传维修后的照片，AI 核验通过才置完成，
                  并且会把设备恢复为「完好」、可借数 +1
                · 标记完成 —— **人工决定**：到场发现是误报等场景直接关单
                  （后端在这条路径上同样会恢复设备）
              核验是带凭据的正式路径，所以排在前面。
            -->
            <view
              class="btn ai"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap.stop="verifyWithPhoto(t)"
            >拍照核验</view>
            <view
              class="btn ghost"
              hover-class="btn-on"
              :hover-stay-time="60"
              @tap.stop="finish(t)"
            >标记完成</view>
          </view>
        </view>
      </view>
      </template>
    </view>

    <mp-tab-bar :current="2" />
  </view>
</template>

<script setup>
/**
 * AI 智能巡检（tab 3）
 *
 * 入口页：拍照巡检 + 维修工单列表。
 * 数据：GET /tickets/list；状态流转 PUT /tickets/{id}/status。
 *
 * 注意：本模块真实后端尚未实现，目前命中 /api/v1/mock/tickets/*。
 * handlerId 由后端从 JWT 解析，前端不传（§5.1）。
 */
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { tickets as fetchTickets, updateTicketStatus, handleTicket } from '@/api/inspect.js'
import { userStore, canInspect } from '@/store/user.js'
import { statusLabel, statusTag } from '@/utils/dict.js'
import { ensureNameMaps, spaceLabel } from '@/utils/nameMap.js'
import { relativeTime } from '@/utils/format.js'
import { toast, toastOk, confirm, showLoading, hideLoading } from '@/utils/toast.js'

const tickets = ref([])
const loading = ref(true)

async function load() {
  // ⚠️ **2026-09-30：未登录不发鉴权请求。**
  // 原先 onShow 无条件拉工单，未登录时拿到 40101 被强制弹登录页，
  // 页面自己的「未登录」分支永远显示不出来。
  if (!userStore.loggedIn) {
    tickets.value = []
    loading.value = false
    return
  }
  loading.value = true
  try {
    const res = await fetchTickets({ page: 1, pageSize: 50 })
    tickets.value = res.list
  } catch (e) {
    tickets.value = []
    toast(e.message || '工单加载失败')
  } finally {
    loading.value = false
  }
}

// 工单列表只给 spaceId，名称要靠资源表映射补（失败不影响列表本身）
onShow(() => {
  ensureNameMaps()
  load()
})

/** 已完成 / 已取消的不再显示操作入口 */
function canFinish(t) {
  const label = statusLabel('ticket', t.status, t.statusText)
  return label === '待处理' || label === '处理中'
}

async function finish(t) {
  const ok = await confirm({
    content: `确认工单 #${t.id}（${t.deviceName || '设备'}）已处理完成？`,
    title: '标记完成',
    confirmText: '确认完成',
  })
  if (!ok) return

  try {
    await updateTicketStatus(t.id, 3)
    toastOk('工单已完成')
    load()
  } catch (e) {
    toast(e.message || '操作失败')
  }
}

/**
 * 拍照核验：传一张维修后的照片，由 AI 判断是否真的修好。
 *
 * 与 `finish`（人工标记完成）的区别：这条是**带凭据**的路径 ——
 * 核验通过后后端会把工单置为已完成，**同时恢复设备为「完好」、可借数 +1**。
 *
 * 未通过时后端**不改工单状态**，`verifyReport` 给出原因，这里如实提示并让用户重拍。
 */
async function verifyWithPhoto(t) {
  const picked = await chooseImage()
  if (!picked) return

  showLoading('AI 核验中…')
  try {
    const res = await handleTicket(t.id, picked)
    hideLoading()

    if (res && res.passed) {
      // 核验结论由后端算好（passed），前端不拿 verifyStatus 和字符串比
      toastOk('核验通过，工单已完成')
    } else {
      // 未通过 / 模型不可用：把后端给的原因显示出来，别让用户猜
      const why = (res && res.verifyReport) || 'AI 核验未通过'
      uni.showModal({
        title: '核验未通过',
        content: `${why}\n\n工单状态未变更，可以重拍一张更清晰的照片再试。`,
        showCancel: false,
        confirmText: '知道了',
      })
    }
    load()
  } catch (e) {
    hideLoading()
    toast((e && e.message) || '核验失败')
    load()
  }
}

/** 选图（相册或拍照）→ 返回临时路径；用户取消则 null */
function chooseImage() {
  return new Promise((resolve) => {
    uni.chooseImage({
      count: 1,
      sizeType: ['compressed'],
      sourceType: ['camera', 'album'],
      success: (res) => {
        const files = res.tempFilePaths || []
        resolve(files[0] || null)
      },
      fail: () => resolve(null),
    })
  })
}

function goCapture() {
  uni.navigateTo({ url: '/pages/inspect/capture' })
}
</script>

<style scoped>
.entry {
  height: 320rpx;
}

.sec {
  margin-top: 24rpx;
}

.mini-empty {
  text-align: center;
  padding: 40rpx 0;
}

.mini-empty .ei {
  display: block;
  font-size: 66rpx;
  opacity: 0.35;
  margin-bottom: 16rpx;
}

.mini-empty .et {
  font-size: 25rpx;
  color: var(--t3);
}

/* ---- 工单卡片的标题行 ----
 * 与「我的预约」的 .ohead / .oname **逐值对齐**（含 28rpx 字号），
 * 这样两个列表卡片在视觉上才是同一套。
 */
.thead {
  display: flex;
  align-items: center;
  gap: var(--s2);
  margin-bottom: 8rpx;
}

.tname {
  flex: 1;
  min-width: 0;
  font-size: 28rpx;
  font-weight: 600;
  color: var(--t1);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* ---- 工单卡片的动作行 ----
 * 与「我的预约」的 .oa **逐值相同**。两页各自持有一份是现状（scoped 互相看不见），
 * 保持一致比抽公共类更稳：抽出去要同时改两个页面的模板，收益只是少 12 行。
 * 改任一处时记得同步另一处。
 */
.oa {
  display: flex;
  justify-content: flex-end;
  /* 两个动作（拍照核验 / 标记完成）必须有间距，否则会贴在一起；
     flex-wrap 兜住窄屏 —— 两个按钮加内边距在 320px 宽的机型上会顶满 */
  flex-wrap: wrap;
  gap: var(--s2);
  margin-top: 20rpx;
  padding-top: 20rpx;
  border-top: 1px solid var(--bg-hover);
}

.oa .btn {
  padding: 12rpx 32rpx;
  font-size: 24rpx;
}

/*
 * ⚠️ 本轮删掉的选择器（2026-10-14）：
 *   .ticket.sep  —— 旧结构「所有工单挤在一个 .mcard 里」画分隔线用的；
 *                   改成一条一张卡后不再需要（卡与卡之间由 .mcard 的 margin-bottom 分开）。
 *   .tno / .tdesc / .tdesc.sug —— 旧的两行自由文本，已被 .mbrow 键值行取代。
 *   .tfoot       —— 旧的左对齐动作行，已换成与预约卡一致的 .oa。
 *   .who         —— 只定义、从未在模板里使用（死代码）。
 *   .btn.tiny    —— 只有上面那个动作行在用，随它一起删；
 *                   按钮尺寸改为与预约卡一致（由 .oa .btn 覆盖）。
 */
</style>
