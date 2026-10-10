<template>
  <div v-loading="loading">
    <div class="sp-page-head">
      <h1 class="sp-page-title">AI 冲突预警与智能通知</h1>
      <p class="sp-page-sub">AI 扫描资源冲突并一键生成改约/致歉通知文案</p>
    </div>

    <div class="sp-pagebar">
      <h3>软冲突雷达</h3>
      <div class="sp-acts">
        <span class="sp-tag" :class="conflicts.length ? 'is-orange' : 'is-green'">
          {{ conflicts.length }} 条
        </span>
        <button class="sp-btn is-ghost" type="button" @click="loadConflicts">
          <el-icon><Refresh /></el-icon>重新扫描
        </button>
      </div>
    </div>

    <div class="cf-cols">
      <div class="sp-card">
        <div class="sp-card-head">
          <b>🚨 AI 软冲突雷达</b>
        </div>

        <!-- 雷达动效只在扫出冲突时出现：没有数据时不做无意义的动效 -->
        <div v-if="conflicts.length" class="sp-radar">
          <i></i><i></i><i></i>
          <div class="sp-sweep"></div>
          <div class="sp-ping"></div>
        </div>

        <el-empty
          v-if="!conflicts.length"
          class="sp-empty"
          description="未发现软冲突，当前资源占用健康"
          :image-size="70"
        />

        <!-- 全部用 .sp-witem.is-blue：/conflicts/scan 的 conflictType 固定为「软冲突」，
             硬冲突（时段重叠）由下单事务与唯一索引拦截、不在本接口范围内，
             所以原型的 .sp-witem.is-red（硬冲突）在这里没有真实数据可渲染。 -->
        <div
          v-for="(item, index) in conflicts"
          :key="index"
          class="sp-witem is-blue"
          :class="{ 'is-on': selectedIndex === index }"
          @click="selectedIndex = index"
        >
          <b>{{ ruleTitle(item) }}</b>
          <!-- 冲突对象：长期闲置类没有关联订单，靠这段说明是**哪个场地**，
               否则同一规则的多条会显示成一模一样（见 conflictSubject 的说明）。 -->
          <p v-if="conflictSubject(item)" class="cf-subject">{{ conflictSubject(item) }}</p>
          <p>{{ item.suggestion }}</p>
          <span v-if="item.orderIds && item.orderIds.length" class="sp-tag is-blue">
            涉及订单 #{{ item.orderIds.join('、#') }}
          </span>
          <!-- 长期闲置类规则没有关联订单：后端给的是空数组，不是缺字段 -->
          <span v-else class="sp-tag is-gray">无关联订单</span>
        </div>
      </div>

      <div class="sp-card cf-notify">
        <div class="sp-section-title">智能通知文案</div>
        <el-empty
          v-if="!notify"
          class="sp-empty"
          description="选择左侧一条冲突后生成通知"
          :image-size="80"
        />
        <template v-if="notify">
          <div class="sp-mbrow">
            <span class="sp-k">基于冲突</span>
            <span class="sp-v">{{ ruleTitle(selectedConflict) }}</span>
          </div>
          <div v-if="selectedConflict && selectedConflict.orderIds && selectedConflict.orderIds.length" class="sp-mbrow">
            <span class="sp-k">关联订单</span>
            <span class="sp-v">#{{ selectedConflict.orderIds.join('、#') }}</span>
          </div>
          <el-input v-model="notify.title" class="notify-title" size="large" />
          <el-input
            v-model="notify.content"
            type="textarea"
            :rows="8"
            class="notify-content"
          />
          <div class="cf-actions">
            <button class="sp-btn is-ai" type="button" @click="generate">
              <el-icon><MagicStick /></el-icon>重新生成
            </button>
            <button class="sp-btn is-ghost" type="button" @click="copyNotify">
              <el-icon><CopyDocument /></el-icon>复制文案
            </button>
          </div>
        </template>
        <button
          v-if="!notify"
          class="sp-btn is-ai is-block"
          type="button"
          :disabled="selectedConflict === null"
          @click="generate"
        >
          <el-icon><MagicStick /></el-icon>生成通知文案
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { generateNotify, scanConflicts } from '@/api/conflicts'

const loading = ref(false)
const conflicts = ref([])
const selectedIndex = ref(0)
const notify = ref(null)

const selectedConflict = computed(() => conflicts.value[selectedIndex.value] || null)

/** 兜底用的规则中文名映射（照 docs/api.md §5.2 的规则编码表写）。
 *
 *  ⚠️ 2026-10-10 改为**只当兜底**：后端 `/conflicts/scan` 现在直接返回 `ruleLabel`
 *  （见 app/schemas/conflict.py 的追加字段），这个本地表往后只是「后端没给时的退路」。
 *  优先用后端值，避免两处口径漂移。 */
const RULE_LABEL_FALLBACK = {
  continuous_activity: '同团队连续活动无休息',
  capacity_overflow: '容量远超实际需求',
  high_value_device_low_priority: '高价值设备被低优先级占用',
  space_overuse: '场地单日累计占用过长',
  space_idle: '场地长期闲置',
}

function ruleTitle(item) {
  if (!item) return ''
  return (
    item.ruleLabel ||
    RULE_LABEL_FALLBACK[item.ruleCode] ||
    item.conflictType ||
    '软冲突'
  )
}

/**
 * 这条冲突的「对象」——让每条可区分。
 *
 * ⚠️ 这是「软冲突有那么多一样的」的直接修法。规则按**场地**产 hit
 * （长期闲置一场地一条），原先响应里没有 `spaceId`、也没有 `reason`，
 * 于是 7 条闲置冲突在列表上逐字段相同、只能显示成 7 条一模一样的东西。
 *
 * 现在优先用 `reason`：它由后端按事实生成、已含场地名与人数
 * （「场地 中心广场（可容纳 100 人）在最近 14 天内…」），比前端再拼一次可靠。
 * 取不到 reason 时退化为只有 `spaceId` 可用的情况。
 *
 * 刻意**不**去拉一次 `/resources/spaces` 做 id→名字映射：本页是只读预警页，
 * 为一条提示多打一次接口不划算，而 reason 已经把名字带上了。
 */
function conflictSubject(item) {
  if (!item) return ''
  const reason = String(item.reason || '').trim()
  if (reason) return reason
  if (item.spaceId !== null && item.spaceId !== undefined) return `场地 #${item.spaceId}`
  return ''
}

async function loadConflicts() {
  loading.value = true
  try {
    conflicts.value = await scanConflicts()
    selectedIndex.value = 0
    notify.value = null
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (!selectedConflict.value) return
  // ⚠️ 后端契约是 `{type, orderInfo}`（见 docs/api.md 与 app/schemas/notify.py），
  //    不是 `{conflictType, orderIds, suggestion}` —— 后者实测返回
  //    400 / 40001「type 该字段为必填项」。
  //    `type` 取语气字典里的别名（预约提醒 / 变更致歉 / 故障告警）。
  //    冲突扫描出来的都是软冲突（闲置类），对应「预约提醒」；
  //    订单号与原因塞进 orderInfo，后端会用**库里的订单事实**覆盖掉载荷里对不上的部分。
  const c = selectedConflict.value
  notify.value = await generateNotify({
    type: '预约提醒',
    orderInfo: {
      orderId: Array.isArray(c.orderIds) && c.orderIds.length ? c.orderIds[0] : null,
      ruleLabel: c.conflictType,
      reason: c.suggestion,
    },
  })
}

async function copyNotify() {
  const text = `${notify.value.title}\n\n${notify.value.content}`
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('浏览器不支持自动复制，请手动选择复制')
  }
}

onMounted(loadConflicts)
</script>

<style scoped>
/* 左右两栏：原型这里用内联 flex，收进 scoped；窄屏改纵向堆叠 */
.cf-cols {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.cf-cols > .sp-card:first-child {
  flex: 1.35;
  min-width: 0;
}

.cf-cols > .sp-card:last-child {
  flex: 1;
  min-width: 0;
}

@media (max-width: 1100px) {
  .cf-cols {
    flex-direction: column;
  }

  .cf-cols > .sp-card {
    width: 100%;
  }
}

/* 条目可点选：用内描边表示选中，避免动到 index.css 里的公共样式 */
.sp-witem {
  cursor: pointer;
  transition: box-shadow 0.15s;
}

.sp-witem.is-on {
  box-shadow: inset 0 0 0 1px var(--sp-accent);
}

/* 冲突对象（哪个场地 / 哪张单）。与下面的 suggestion 区分开：
   这一段是**事实**、suggestion 是**建议**，两者在后端也是分开的字段
   （ConflictItem.reason vs .suggestion），混在一起会让用户分不清哪个是结论。 */
.cf-subject {
  margin: 4px 0 6px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--sp-t2);
}

.cf-notify {
  min-height: 320px;
  display: flex;
  flex-direction: column;
}

.cf-notify .sp-mbrow {
  padding: 6px 0;
}

.cf-actions {
  display: flex;
  gap: 10px;
}

.notify-title {
  margin: 12px 0;
  font-weight: 600;
}

.notify-content {
  margin-bottom: 14px;
}

.sp-empty {
  padding: 6px 0 2px;
}
</style>
