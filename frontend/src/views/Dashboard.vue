<!--
  ⚠️ 全页遮罩已去掉（2026-10-14）。

  原来根节点挂着 v-loading="loading"，文案还是「AI 正在生成结构化建议…约 30~60 秒」，
  而 loading 等的是 Promise.all([stats, report]) —— 于是 0.8 秒就能算完的统计，
  被 74 秒的 AI 建议一起遮住，用户一进页面就是转圈。

  现在遮罩只挂在下面的 .dash-body（统计主体）上，且只等 stats；
  AI 建议由它自己的卡片显示「生成中」，两件事互不牵连。
-->
<template>
  <div>
    <!-- 页头：对齐原型 PC-4 的 pagebar（标题 + 右侧「导出报告」「重新生成建议」） -->
    <div class="sp-pagebar">
      <h3>AI 数据洞察面板</h3>
      <span class="sp-tag is-blue">近 7 天</span>
      <div class="sp-acts">
        <!-- 后端约定：导出按钮的可用性只看 exportUrl（degraded 与 exportUrl=null 不等价） -->
        <button
          class="sp-btn is-ghost is-sm"
          :disabled="!report.exportUrl"
          :title="report.exportUrl ? '下载后端生成的 CSV 报告' : '暂无可导出的报告文件'"
          @click="onExport"
        >
          导出报告
        </button>
        <!-- 该接口实测 27~74 秒，生成期间禁用，避免重复打请求。
             判据用 reportLoading 而不是 loading：整页遮罩只等 stats（0.8 秒），
             用 loading 会让按钮在建议还在生成时就恢复可点。 -->
        <button class="sp-btn is-ai is-sm" :disabled="reportLoading" @click="load">
          {{ reportLoading ? '生成中…' : '重新生成建议' }}
        </button>
      </div>
    </div>

    <!-- 统计主体：遮罩只覆盖这一块，并且只等 stats（实测 0.8 秒）。
         AI 建议在右侧卡片里自己显示进度，不参与这层等待。 -->
    <div class="dash-body" v-loading="loading" element-loading-text="正在读取近 7 天的预约与设备数据…">
    <!-- AI 状态条：把 degraded 的两种含义如实讲清楚，而不是把占位零值渲染成真实 0 -->
    <div class="sp-ai-bar">
      <span class="sp-ic">◈</span>
      <span v-if="loading">正在读取近 7 天的预约与设备数据 …</span>
      <!-- 统计已就绪、AI 还在写建议：这条必须排在 degraded 判断之前，
           否则「还在生成」会被误读成「AI 不可用已降级」。 -->
      <span v-else-if="reportLoading">
        近 7 天统计已就绪；<b>AI 正在生成结构化建议</b>（约 30~70 秒，可先看下方统计，不必等）。
      </span>
      <span v-else-if="stats.degraded">
        统计数据暂时不可用（后端读库失败，四项为<b>占位零值</b>，不代表场地真空着）—— 演示应急预案已生效。
      </span>
      <span v-else-if="report.degraded">
        AI 暂不可用，以下建议由<b>纯统计口径</b>生成，引用的仍是真实统计数字。
      </span>
      <span v-else>
        报告已生成：基于近 7 天真实预约与设备数据，共 <b>{{ report.suggestions?.length ?? 0 }}</b> 条结构化建议。
      </span>
    </div>

    <!-- KPI：原型是四张卡，但后两张（Agent 调用次数 / 成功率、平均决策耗时 / P95）的数据源
         是 GET /monitor/agent，属 Agent 监控页；本页只调 /dashboard/* 两个接口，
         所以按「算不出来就不显示」的约定，换成 /dashboard/stats 与 /dashboard/report 真实有的统计项，
         不跨模块取数、也不编造数值。 -->
    <div class="sp-kpis">
      <div class="sp-kpi">
        <div class="sp-k">场地使用率</div>
        <div class="sp-v">{{ usageRate ?? '--' }}<small v-if="usageRate !== null">%</small></div>
        <div class="sp-d is-note">{{ stats.degraded ? '数据暂时不可用' : '近 7 日全场地加权' }}</div>
      </div>
      <div class="sp-kpi">
        <div class="sp-k">设备闲置率</div>
        <div class="sp-v">{{ idleRate ?? '--' }}<small v-if="idleRate !== null">%</small></div>
        <div class="sp-d is-note">{{ stats.degraded ? '数据暂时不可用' : '可调度设备空闲占比' }}</div>
      </div>
      <div class="sp-kpi">
        <div class="sp-k">AI 洞察建议</div>
        <div class="sp-v">{{ report.suggestions?.length ?? 0 }}<small>条</small></div>
        <div class="sp-d is-note">
          {{ report.degraded ? '模型不可用，已降级为统计口径' : 'finding / evidence / suggestion 三要素' }}
        </div>
      </div>
      <div class="sp-kpi">
        <div class="sp-k">单时段预约峰值</div>
        <div class="sp-v">{{ peakTop ? peakTop.count : '--' }}<small v-if="peakTop">次</small></div>
        <div class="sp-d is-note">{{ peakTop ? `峰值时段 ${peakTop.hour}:00` : '近 7 日暂无预约' }}</div>
      </div>
    </div>

    <div class="insight-row">
      <div class="insight-col">
        <!-- 原型这里是「各场地时段使用率」柱状图，但 /dashboard/stats 只给 peakHours（[{hour,count}]）：
             既没有「场地」维度，也没有「使用率」——它是按小时聚合的预约次数。
             因此如实降级：柱子画接口真有的「按小时预约次数」，标题与单位同步改成真实口径，
             不写死任何高度。 -->
        <div class="sp-card">
          <div class="sp-card-head">
            <b>预约高峰时段分布</b>
            <span class="sp-grow"></span>
            <span>单位：次</span>
          </div>
          <div v-if="peakBars.length" class="sp-chart is-dense">
            <div
              v-for="bar in peakBars"
              :key="bar.hour"
              class="sp-bar"
              :class="{ 'is-peak': bar.isPeak }"
            >
              <i :style="{ height: bar.height + '%' }"></i>
              <em>{{ bar.hour }}:00</em>
            </div>
          </div>
          <div v-else class="sp-muted empty">
            {{ stats.degraded ? '数据暂时不可用' : '近 7 天暂无预约记录' }}
          </div>
          <!-- 峰谷说明同样来自 peakHours 全量（不受柱状图只画 8 根的影响）；
               peakHours 只含「有预约」的小时，所以低谷注明是「有预约的时段中最低」。 -->
          <div v-if="peakTop" class="chart-note">
            <span class="is-peak-text">峰值</span> {{ peakTop.hour }}:00 · {{ peakTop.count }} 次预约
            <template v-if="peakLow">
              <br />
              <span class="is-low-text">低谷</span> {{ peakLow.hour }}:00 · {{ peakLow.count }} 次预约（有预约的时段中最低）
            </template>
          </div>
        </div>

        <div class="sp-card">
          <div class="sp-card-head">
            <b>设备故障频次</b>
            <span class="sp-grow"></span>
            <span>单位：次</span>
          </div>
          <table v-if="faultRows.length" class="sp-table">
            <thead>
              <tr>
                <th>设备名称</th>
                <th class="num">维修工单</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in faultRows" :key="index">
                <td>{{ row.name }}</td>
                <td class="num">{{ row.count }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="sp-muted empty">
            {{ stats.degraded ? '数据暂时不可用' : '暂无维修工单记录' }}
          </div>
          <!-- 该统计在后端没有时间窗过滤，是全量累计，所以不写成「近 7 天」，避免口径误读 -->
          <div v-if="faultRows.length" class="chart-note">累计口径（不受近 7 天窗口限制），后端最多返回前 10 台设备。</div>
        </div>
      </div>

      <div class="insight-col is-wide">
        <div class="sp-card">
          <div class="sp-card-head">
            <b>结构化运营建议</b>
            <span class="sp-grow"></span>
            <span class="sp-tag is-purple">finding · evidence · suggestion</span>
          </div>
          <template v-if="report.suggestions?.length">
            <div v-for="(item, index) in report.suggestions" :key="index" class="sp-sug">
              <div><span class="sp-lbl">发现</span><b>{{ item.finding }}</b></div>
              <div><span class="sp-lbl">依据</span>{{ item.evidence }}</div>
              <div><span class="sp-lbl">建议</span>{{ item.suggestion }}</div>
              <div class="sp-bar-anim"></div>
            </div>
          </template>
          <!--
            「正在生成」必须排在 degraded 之前判断：
            还在生成时 report.degraded 也还是初值，先判 degraded 会把它误说成「模型不可用」。
            文案里给出预期时长并指明「可以先看左侧」，用户就知道不用干等。
          -->
          <div v-else-if="reportLoading" class="sp-muted empty">
            AI 正在生成建议（约 30~70 秒），左侧统计数字可先看。
          </div>
          <div v-else class="sp-muted empty">
            {{ stats.degraded ? '数据暂时不可用' : '暂无建议' }}
          </div>
        </div>
      </div>
    </div>
    <!-- /.dash-body -->
  </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import { getDashboardReport, getDashboardStats } from '@/api/dashboard'
import { first } from '@/utils/normalize'

const loading = ref(false)
/**
 * AI 建议是否在生成中。
 *
 * 与 loading 分开：两者是**两次独立等待**（stats 0.8s / report 74s）。
 * 复用同一个开关会出现「统计出来了但整页还遮着」或「建议没出来却已经解除遮罩」。
 */
const reportLoading = ref(false)

const stats = reactive({})
const report = reactive({})

// ---------- 展示层派生：只做取值兜底与格式化，不引入任何接口以外的新数据 ----------

// degraded=true 时后端给的是「占位 0」而不是真实 0%，渲染成 0% 会把「读不到库」说成「场地全空着」，
// 所以这种情况统一退化成 --（口径见 docs/api-dashboard.md 的 degraded 说明）。
const usageRate = computed(() =>
  stats.degraded || stats.spaceUsageRate == null ? null : stats.spaceUsageRate,
)
const idleRate = computed(() =>
  stats.degraded || stats.deviceIdleRate == null ? null : stats.deviceIdleRate,
)

// peakHours 后端已按 count 降序返回，这里只做数值化与兜底排序，口径不变。
const peakRows = computed(() => {
  const rows = Array.isArray(stats.peakHours) ? stats.peakHours : []
  return rows
    .map((item) => ({ hour: Number(item.hour), count: Number(item.count) || 0 }))
    .filter((item) => Number.isFinite(item.hour))
    .sort((a, b) => b.count - a.count)
})

const peakTop = computed(() => peakRows.value[0] ?? null)

// 只有一个时段、或各时段次数完全相同，就谈不上「低谷」，此时不显示那一行。
const peakLow = computed(() => {
  const rows = peakRows.value
  if (rows.length < 2) return null
  const last = rows[rows.length - 1]
  return last.count === rows[0].count ? null : last
})

// 柱子只画次数最高的 8 个时段：24 个小时全画会挤成一团；展示时按时间正序，读起来才像「一天里的分布」。
const peakBars = computed(() => {
  const rows = peakRows.value.slice(0, 8)
  if (!rows.length) return []
  const max = rows[0].count
  return [...rows]
    .sort((a, b) => a.hour - b.hour)
    .map((item) => ({
      hour: item.hour,
      height: max > 0 ? Math.round((item.count / max) * 100) : 0,
      isPeak: max > 0 && item.count === max,
    }))
})

// 真实接口给 deviceName、Mock 给 deviceType，两处都容忍（沿用 normalize 的 first）。
const faultRows = computed(() =>
  (Array.isArray(stats.faultFrequency) ? stats.faultFrequency : []).map((item) => ({
    name: first(item.deviceName, item.deviceType, '未知设备'),
    count: Number(item.count) || 0,
  })),
)

function onExport() {
  if (report.exportUrl) {
    window.open(report.exportUrl)
  }
}

// 取数已拆成两步（见下方 loadStats / loadReport）：
// 原先两者走同一个 Promise.all，于是 0.8 秒的统计被 74 秒的 AI 建议一起遮住。
// 接口与请求参数都没变，只是不再互相等待。
/**
 * 统计面板：/dashboard/stats。**实测 0.8 秒**，是这一屏的主体。
 *
 * 拆出来单独 await，是为了让 KPI、高峰分布、设备故障三块**立刻**渲染 ——
 * 它们全部只依赖 stats，跟 AI 建议没有任何关系。
 */
async function loadStats() {
  const data = await getDashboardStats()
  Object.assign(stats, data)
}

/**
 * AI 结构化建议：/dashboard/report。**实测 74 秒**（波动 27~74 秒）。
 *
 * ⚠️ 这是本页最慢的一步，原先它和 stats 一起走 Promise.all，
 * 于是一整屏要等 74 秒才出现 —— 而 0.8 秒就能算完的统计数字被白白压着。
 * 现在它独立在后台跑，只有右侧「结构化运营建议」卡片自己显示生成中。
 *
 * 失败（模型不可用 / 超时）只清空建议并复位转圈：左下两块统计不受影响。
 */
async function loadReport() {
  reportLoading.value = true
  try {
    const data = await getDashboardReport()
    Object.assign(report, data)
  } catch (e) {
    report.suggestions = []
  } finally {
    reportLoading.value = false
  }
}

/**
 * 刷新。统计先出，建议随后 —— 刻意**不 await loadReport()**，
 * 否则点一次按钮又要等 74 秒才看到任何东西。
 */
async function load() {
  loading.value = true
  try {
    await loadStats()
  } finally {
    loading.value = false
  }
  loadReport()
}

onMounted(load)
</script>

<style scoped>
/* 两栏比例照原型：左 1.2（图表）/ 右 1.7（建议） */
.insight-row {
  display: flex;
  gap: var(--sp-s3);
  align-items: flex-start;
}

.insight-col {
  display: flex;
  flex-direction: column;
  gap: var(--sp-s3);
  flex: 1.2;
  min-width: 0;
}

.insight-col.is-wide {
  flex: 1.7;
}

@media (max-width: 1180px) {
  .insight-row {
    flex-direction: column;
  }

  .insight-col,
  .insight-col.is-wide {
    width: 100%;
    flex: none;
  }
}

/*
 * 矮屏收紧（2026-10-14 加）。
 *
 * 本页左列是「柱状图 + 故障表」两块叠起来，实测 insight-row 高 487px：
 * 视口 ≥820px 时刚好一屏放下（页面无滚动条），但 1366×768 这类笔记本还差 37px。
 *
 * 与其把所有人都挤到，不如只在**确实矮**的时候收一档：
 *   · 图表高度 150 → 124px（柱子还能看清高低）
 *   · 两栏间距 12 → 8px
 * 高度 ≥801px 的屏幕完全不受影响，图表保持原本的舒展。
 */
@media (max-height: 800px) {
  .insight-row,
  .insight-col {
    gap: 8px;
  }

  /* 148 → 118px：实测视口 768 时还差 3px，图表占这一屏纵向的大头，收它是代价最小的一刀 */
  .sp-chart.is-dense {
    height: 118px;
  }

  .sp-kpi .sp-v {
    font-size: 23px;
  }
}

/* 8 根柱子的时间标签比原型的 7 个星期标签长，在 1180~1300px 会把卡片顶出横向滚动，
   所以这一处图表收窄间距与标签字号（样式仍只作用于本页的这根图表）。

   ⚠️ 字号统一为 12px 最小档：原先写 10.5px，比全局最小字号还小，
      中文在这个尺寸下发虚、长时间看很累。宁可靠收窄 gap 与换行腾地方。 */
.sp-chart.is-dense {
  gap: var(--sp-s2);
}

.sp-chart.is-dense .sp-bar em {
  font-size: 12px;
}

/* 原型 .sp-d 是给「环比涨跌」用的绿色，这里只是统计口径说明，不是涨跌，所以压回中性色 */
.sp-kpi .sp-d.is-note {
  color: var(--sp-t3);
}

.chart-note {
  font-size: 12.5px;
  color: var(--sp-t3);
  margin-top: var(--sp-s3);
  line-height: 1.7;
}

.chart-note .is-peak-text {
  color: var(--sp-warning);
}

.chart-note .is-low-text {
  color: var(--sp-success);
}

.empty {
  padding: var(--sp-s5) 0;
  text-align: center;
}

.sp-table .num {
  text-align: right;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
</style>
