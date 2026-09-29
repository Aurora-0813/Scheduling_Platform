<template>
  <div v-loading="loading">
    <!-- 页头工具条：原型 PC-6 的 pagebar -->
    <div class="sp-pagebar">
      <h3>Agent 调用监控</h3>
      <div class="sp-acts">
        <!-- 指标来源是接口的 source 字段，redis=跨重启累计 / memory=仅本进程，
             两者可信范围不同，摆在页头比藏在卡片里更容易被看到 -->
        <span v-if="metrics.source" class="sp-tag" :class="sourceTag.cls">{{ sourceTag.text }}</span>
        <button class="sp-btn is-ghost is-sm" @click="loadMetrics">刷新指标</button>
        <!--
          本页**不再**提供「输入需求 → 运行一次调度」的入口。
          调度（需求解析 / 思考链 / 主备方案 / 确认建单）已经独立成
          「Agent 调度台」（/agent）一个完整页面，本页只负责**事后统计**。
          两处都放入口会让「调度」有两个互不相干的家，且本页原先那份
          没有确认/落库的完整交互。这里只留一条指路。
        -->
        <router-link to="/agent" class="sp-btn is-ai is-sm">去 Agent 调度台</router-link>
      </div>
    </div>

    <!-- AI 提示条：句子里的每个数字都取自 /monitor/agent 的真实聚合值，没有就改说法 -->
    <div class="sp-ai-bar">
      <div class="sp-ic">🧠</div>
      <span v-if="hasMetrics">
        <b>AI 正在真实运行</b> — 累计 {{ metrics.totalCalls }} 次 Agent 调用，成功率
        {{ metrics.successRate }}%。
        <template v-if="metrics.degradedCalls">
          其中 {{ metrics.degradedCalls }} 次走了降级路径（占 {{ metrics.degradedRate }}%），均按容错口径返回，未中断业务。
        </template>
        <template v-else>当前没有降级记录，容错路径未被触发。</template>
      </span>
      <span v-else>
        <b>还没有采集到 Agent 调用</b> —— 去「Agent 调度台」运行一次真实调度，这里会立刻出现真实统计。
      </span>
    </div>

    <!-- KPI：口径见 backend/docs/api.md 3.1（成功率是百分数、平均耗时单位是秒） -->
    <div class="sp-kpis">
      <div class="sp-kpi">
        <div class="sp-k">总调用次数</div>
        <div class="sp-v">{{ hasMetrics ? metrics.totalCalls : '—' }}</div>
        <div v-if="hasMetrics && metrics.successCalls !== undefined" class="sp-d">
          成功 {{ metrics.successCalls }} · 失败 {{ metrics.errorCalls }}
        </div>
      </div>
      <div class="sp-kpi">
        <div class="sp-k">成功率</div>
        <div class="sp-v">{{ hasMetrics ? metrics.successRate : '—' }}<small>%</small></div>
        <div v-if="hasMetrics && metrics.errorCalls" class="sp-d is-down">失败 {{ metrics.errorCalls }} 次</div>
        <div v-else-if="hasMetrics" class="sp-d">全部请求成功</div>
      </div>
      <div class="sp-kpi">
        <div class="sp-k">平均耗时</div>
        <div class="sp-v">{{ hasMetrics ? metrics.avgLatency : '—' }}<small>s</small></div>
        <!-- 原型这里的副行是 P95，接口只给均值、没有分位数，所以这一行留空不编 -->
      </div>
      <div class="sp-kpi">
        <div class="sp-k">降级次数</div>
        <div class="sp-v">{{ hasMetrics ? metrics.degradedCalls : '—' }}</div>
        <div v-if="hasMetrics" class="sp-d" :class="{ 'is-down': metrics.degradedCalls > 0 }">
          占全部调用 {{ degradedRate }}%
        </div>
      </div>
    </div>

    <div class="am-cols">
      <!-- 左：调用构成。接口没有逐日数据，所以画的是真实计数构成，不是原型的「近 7 日趋势」 -->
      <div class="sp-card am-main">
        <div class="sp-card-head">
          <b>📊 调用构成</b>
          <span class="sp-grow"></span>
          <span class="sp-tag is-blue">接口实时聚合</span>
        </div>
        <template v-if="callComposition.length">
          <div class="sp-chart">
            <div v-for="item in callComposition" :key="item.label" class="sp-bar" :class="item.tone">
              <i :style="{ height: item.height }"></i>
              <em>{{ item.label }}</em>
            </div>
          </div>
          <div class="am-legend">
            <span v-for="item in callComposition" :key="item.label" class="sp-tag" :class="item.tag">
              {{ item.label }} {{ item.value }}（{{ item.pct }}%）
            </span>
          </div>
          <p class="sp-muted am-note">
            柱子按 successCalls / errorCalls / degradedCalls 的真实计数换算。降级仍返回 HTTP 200、已计入成功，
            所以三根柱子不构成相加关系。接口没有逐日明细，因此不画「近 7 日趋势」。
          </p>
        </template>
        <el-empty v-else description="暂无调用数据，去 Agent 调度台跑一次后这里会出现真实构成" :image-size="70" />
      </div>

      <!-- 右：降级与容错。接口只有聚合计数，没有逐条记录，所以呈现计数而不是编造的记录列表 -->
      <div class="sp-card am-side">
        <div class="sp-card-head">
          <b>⚠️ 降级与容错</b>
        </div>
        <template v-if="toleranceItems.length">
          <div v-for="item in toleranceItems" :key="item.title" class="sp-witem" :class="item.tone">
            <b>{{ item.title }}</b>
            <p>{{ item.desc }}</p>
          </div>
        </template>
        <el-empty v-else description="暂无调用数据" :image-size="60" />
        <p class="sp-muted am-note">
          后端只提供 degradedCalls / degradedRate / errorCalls 这类聚合计数，
          没有「时间 + 原因」的逐条降级明细，所以这里不虚构记录清单。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

import { getAgentMetrics } from '@/api/monitor'

const loading = ref(false)

const metrics = reactive({})

const degradedRate = computed(() =>
  metrics.degradedRate !== undefined ? metrics.degradedRate : 0,
)

/**
 * 是否已经拿到真实指标。
 * 必须把「还没请求回来」和「后端统计确实是 0 次」分开：前者该显示空态文案，
 * 后者要老实显示 0，拿默认值 100% 之类去顶替就是在编数据。
 */
const hasMetrics = computed(() => Number(metrics.totalCalls) > 0)

/**
 * 指标来源文案。直接读接口的 source 字段：redis = 跨进程重启累计，
 * memory = Redis 不可用、只统计本进程启动至今 —— 两者可信范围不同，
 * 用户有权知道看到的数字覆盖了多久，所以不写死成一句「数据正常」。
 */
const sourceTag = computed(() => {
  if (metrics.source === 'redis') return { text: 'Redis 累计', cls: 'is-green' }
  if (metrics.source === 'memory') return { text: '仅本进程', cls: 'is-orange' }
  return { text: '来源未知', cls: 'is-gray' }
})

/**
 * 调用构成柱状图的数据。
 * 接口只给聚合计数（successCalls / errorCalls / degradedCalls），**没有逐日数据**，
 * 所以这里画的是「构成」而不是原型里的「近 7 日趋势」—— 宁可换个说法，也不编 7 天假柱子。
 * 成功/失败两个字段缺任意一个就返回空数组，让模板走空态，避免把缺字段画成 0。
 */
const callComposition = computed(() => {
  const total = Number(metrics.totalCalls) || 0
  if (!total || metrics.successCalls === undefined || metrics.errorCalls === undefined) return []
  const make = (label, value, tone, tag) => ({
    label,
    value,
    tone,
    tag,
    // 高度按真实计数占比换算；兜 3% 是为了让 4% 的失败柱不至于看不见
    height: `${Math.max((value / total) * 100, 3)}%`,
    pct: ((value / total) * 100).toFixed(1),
  })
  return [
    make('成功', Number(metrics.successCalls) || 0, '', 'is-green'),
    make('失败', Number(metrics.errorCalls) || 0, 'is-error', 'is-red'),
    make('降级', Number(metrics.degradedCalls) || 0, 'is-warn', 'is-orange'),
  ]
})

/**
 * 「降级与容错」条目。
 * 接口没有逐条降级记录（时间 + 原因），所以只按真实计数生成条目；
 * 计数为 0 时明说「没触发」，而不是留一张空白卡片让人以为是加载失败。
 */
const toleranceItems = computed(() => {
  if (!hasMetrics.value) return []
  const total = Number(metrics.totalCalls) || 0
  const degraded = Number(metrics.degradedCalls) || 0
  const errors = Number(metrics.errorCalls) || 0
  return [
    degraded
      ? {
          tone: '',
          title: `降级调用 ${degraded} 次`,
          desc: `占全部调用 ${metrics.degradedRate ?? 0}% · 降级仍返回 HTTP 200，因此单列、不并入成功率`,
        }
      : {
          tone: 'is-blue',
          title: '暂无降级调用',
          desc: 'degradedCalls / degradedRate 均为 0，容错路径未被触发',
        },
    errors
      ? {
          tone: 'is-red',
          title: `失败调用 ${errors} 次`,
          desc: `占全部调用 ${((errors / total) * 100).toFixed(1)}% · 按 HTTP 状态码判定（≥ 400）`,
        }
      : {
          tone: 'is-blue',
          title: '没有失败调用',
          desc: `成功率 ${metrics.successRate}%，全部请求状态码均 < 400`,
        },
  ]
})

async function loadMetrics() {
  loading.value = true
  try {
    const data = await getAgentMetrics(true)
    Object.assign(metrics, data)
  } finally {
    loading.value = false
  }
}

onMounted(loadMetrics)
</script>

<style scoped>
/* 两栏布局：原型用 flex 比例（1.4 : 1），这里沿用，窄屏再堆叠 */
.am-cols {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.am-main {
  flex: 1.4;
  min-width: 0;
}

.am-side {
  flex: 1;
  min-width: 0;
}

/* 失败 / 降级柱：设计系统只有蓝、橙两种柱子语义，红的只有事件类，
   但「失败」用橙色会和「降级」撞色，所以在这里补一个本页独有的红色柱 */
.sp-bar.is-error i {
  background: linear-gradient(180deg, #f9a3a3, #f56c6c);
}

.sp-bar.is-warn i {
  background: linear-gradient(180deg, #ffcd85, #e6a23c);
}

.am-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.am-note {
  margin: 10px 0 0;
  line-height: 1.7;
}

@media (max-width: 1200px) {
  .am-cols {
    flex-direction: column;
  }

  .am-main,
  .am-side {
    width: 100%;
  }
}
</style>
