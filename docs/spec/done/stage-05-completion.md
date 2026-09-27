# 阶段 05 完成文档：Prompt 与 Agent 组装

| 项 | 内容 |
| --- | --- |
| 阶段 | 阶段 05 · Prompt 与 Agent 组装 |
| 对应文档 | `docs/spec/stage-05-assembly.md` |
| 负责人 | 徐川 |
| 开始日期 | 2026-09-27 |
| 完成日期 | 2026-09-27 |
| 计划工时 | 2.0 人日 |
| **实际工时** | 1.5 人日 |
| 验收测试 | `AGENT-STAGE-05` |
| **验收结论** | **不通过（阻塞）** —— 代码与组装已完成，但「真实 API 冒烟」这一条无法执行：`backend/.env` 没有 LLM 凭据 |

## 1. 本阶段目标与达成情况

目标：证明「Prompt + `create_agent` + trace 提取」三件套在真实模型下能跑通。

已达成：三件套**全部实现并跑通**。Prompt（`prompts/scheduler.py`）、Agent 组装
（`chains/builder.py`）、思考链提取（`chains/trace.py`）均已完成；
用**假模型**驱动全链路时，一次完整调度产出了 6 步 trace，`plan` 正确提取，
各步 `timestamp` 互不相同且递增（见第 3 节）。

未达成：**真实 API 冒烟**。`backend/.env` 里 `LLM_MODEL_NAME` / `LLM_API_KEY` /
`LLM_BASE_URL` 三项为空，调端点直接返回 503「大模型未配置」。
这不是本模块能自行解决的：`.env.example` 写明 base_url 与 model_name 是
**全组唯一的取值**，需 Agent 组公布 baseline 后统一填。

**因此本阶段的核心验收项（真实模型下时间戳是否互不相同）尚未被证明。**
第 3 节的证据只能证明「管道通了」，不能证明「真实耗时下时间戳不塌成同一个值」——
后者恰恰是本阶段被单拎出来的原因（假模型不产生真实耗时，这个坑只在真实调用下暴露）。

## 2. 完成判定逐项核对

- [x] `prompts/scheduler.py` 四要素齐全（角色/边界、字典对照表、决策优先级、输出要求）
      —— 证据：`SPACE_TYPE_TABLE`、`DEVICE_TYPES`、`SCHEDULER_PROMPT`、`build_scheduler_prompt(now)`
- [x] Prompt 注入当前时间，用户相对时间（「本周五」）可换算 —— 证据：
      `build_scheduler_prompt()` 把 `{current_time}` 替换为渲染时刻；
      `build_agent()` **每次调用重新组装、不做模块级缓存**，理由写在
      `builder.py::build_agent` 的 docstring（缓存会把首次请求那一刻的日期钉死，
      服务跑过午夜后所有相对时间算错一天且不报错）
- [x] `create_agent(model, tools, system_prompt)` 组装，配置全部来自 `.env` —— 证据：
      `builder.py::build_agent`；`build_model()` **显式传 `api_key`**，
      堵死 `ChatOpenAI` 隐式拾取环境变量 `OPENAI_API_KEY` 的路径
- [x] trace 提取按 Thought-Action-Observation 映射 —— 证据：
      `trace.py` 模块 docstring 的映射表；实际输出见第 3 节
- [x] `timestamp` 在**收集时**打点，不是事后统一打 —— 证据：
      `collect_stamped_messages()` 用 `astream(stream_mode="updates")` 边收边打点
- [ ] **真实 API 冒烟跑通一次** —— **未完成**，见第 1 节与第 6 节 #1
- [ ] 各步 `timestamp` 互不相同且递增（**真实调用下**）—— 未完成；假模型下的等价验证见第 3 节

未通过项说明：

| 条目 | 状态 | 原因 | 处置计划 | 责任人 |
| --- | --- | --- | --- | --- |
| 真实 API 冒烟 | 未完成 | `.env` 无 LLM 凭据（全组 baseline 未公布） | 拿到 key 后立即执行本阶段步骤 ①~④ 并补录本文件第 3 节 | Agent 组给 baseline → 徐川执行 |
| 真实调用下的时间戳 | 未完成 | 同上 | 同上。**若届时发现各步时间戳相同**，说明打点退化成了「提取时刻统一打点」，须回查 `astream` 分支是否被 `except (TypeError, ValueError)` 吞掉退化成了 `ainvoke` | 徐川 |

## 3. 验收测试执行记录

| 项 | 内容 |
| --- | --- |
| 测试编号 | `AGENT-STAGE-05`（**仅完成等价验证部分**） |
| 执行环境 | Windows 11；conda 环境 `smart_dev`（Python 3.11.9）；SSH 隧道 3308 通；开发库 `smart_scheduler_dev`；**用自实现 `bind_tools` 的假模型，不连真实 API** |
| 执行命令 | `PYTHONIOENCODING=utf-8 PYTHONPATH=. python <自检脚本>` |
| 执行时间 | 2026-09-27 18:58 |

**原始输出**（未改写）：

```text
success: True | degraded: False | latency: 2293 ms
message: 操作成功
plan: {'spaceId': 4, 'spaceName': 'A栋3楼展厅', 'deviceIds': [1, 2], 'startTime': '2026-11-06 14:00:00', 'endTime': '2026-11-06 18:00:00', 'reason': '预算内保住场地。'}
locked_order_id: None
trace steps: 6
  1. [2026-09-27 18:58:39] query_spaces :: 查询场地：命中 1 个候选场地
  2. [2026-09-27 18:58:41] query_devices :: 查询设备：命中 4 台可借设备
  3. [2026-09-27 18:58:42] lock_resources :: 锁定资源：成功（未落库）
  4. [2026-09-27 18:58:43] generate_notification :: 生成通知文案：预约成功提醒
  5. [2026-09-27 18:58:44] submit_plan :: 提交方案：已提交
  6. [2026-09-27 18:58:45] - :: 方案已生成。
```

字段逐项对齐冻结契约：`step` 从 1 递增、`result` 全部非空、
`timestamp` 格式为 `YYYY-MM-DD HH:mm:ss` 且**互不相同、严格递增**、
`thought` / `action` / `actionInput` / `observation` 均按映射表填充。
`plan` 经 `submit_plan` 的 `tool_calls[].args` 提取成功。

**结论**：管道通了。**但这不是 `AGENT-STAGE-05` 的通过证据**——
假模型不产生真实耗时，这 6 步的时间戳实际来自 `trace.py` 的**保序顺延**
（同秒内的后续步骤依次 +1 秒），而不是真实间隔。
只用这份输出声称「时间戳递增已验证」会把机制验证偷换成契约验证。

## 4. 交付物清单

| 交付物 | 计划路径 | 实际路径 | 状态 |
| --- | --- | --- | --- |
| 调度 Prompt | `app/agent/prompts/scheduler.py` | 同左 | 已交付 |
| Agent 组装 | `app/agent/chains/builder.py` | 同左 | 已交付 |
| 思考链提取 | `app/agent/chains/trace.py` | 同左 | 已交付 |
| 运行参数配置 | `app/core/config.py` | 同左（新增 `LLM_TEMPERATURE`/`LLM_MAX_RETRIES`/`AGENT_TIMEOUT`/`AGENT_RECURSION_LIMIT`） | 已交付 |
| 冒烟记录 | 本文件第 3 节 | 部分（缺真实 API 部分） | 部分 |

## 5. 偏离计划之处

| # | 计划 | 实际 | 原因 | 影响 | 是否需要同步团队 |
| --- | --- | --- | --- | --- | --- |
| 1 | 用真实 API 冒烟一次 | 改用假模型做等价验证 | `.env` 无 LLM 凭据 | 本阶段**不能判定通过**；真实耗时下的时间戳单调性仍未被证明 | 是（需 Agent 组给 baseline） |
| 2 | 降级路径只做「模型不调工具」 | 实现为三条并行的降级路径：超时 / 未交方案 / 运行期异常 | 阶段 6 §3.3 与主文档 13.1 要求超时降级，一并做齐省一次返工 | 无负面影响 | 否 |

## 6. 遗留问题与阻塞

| # | 问题 | 类型 | 影响 | 责任人 | 期望闭环时间 |
| --- | --- | --- | --- | --- | --- |
| 1 | **`backend/.env` 缺 `LLM_MODEL_NAME` / `LLM_API_KEY` / `LLM_BASE_URL`** | **阻塞** | ① 真实 API 冒烟做不了，本阶段不能判定通过；② 端点正常路径当前返回 503，主线一屏 3 的演示跑不起来；③ 阶段 6 的验收步骤 ② 只能验到降级/503 | Agent 组（公布 baseline）+ 徐川（填 `.env`） | 立即 |
| 2 | 真实调用下 `astream` 分支是否真被走到 | 待确认 | `collect_stamped_messages` 在 `TypeError/ValueError` 时**退回 `ainvoke`**；假模型与真模型的执行路径不同，退回与否无法在假模型下暴露 | 徐川 | 拿到 key 后同 #1 |

## 7. 未决事项进展

| # | 事项 | 本阶段是否已闭环 | 结论 / 当前卡点 |
| --- | --- | --- | --- |
| 3 | 40 秒思考过程的回放方案 | 否，但已有落点 | 服务端真跑 30 秒已是多次工具调用的量级，40 秒由**前端按 trace 回放**得到（阶段 5 §3.5）。回放素材已备好：`docs/mock/agent_schedule.json`（7 步、跨 39 秒、间隔不均）。待前端确认 |
| 4 | `query_spaces`/`query_devices` 真实 service 签名 | 否 | Prompt 里的字典对照表已与桩的取值对齐；替换真实 service 后需再核对一次 |

## 8. 下一阶段入口条件确认

- [ ] `AGENT-STAGE-05` 通过 —— **未满足**（见第 2 节）
- [x] `.env` 中已定义 `AGENT_TIMEOUT` —— 满足（`config.py` 默认 30.0，`.env.example` 已记录）
- [x] 埋点存储方式与集成组确认 —— **未满足**（阶段 6 入口条件之一）。
      当前实现为**进程内计数**并在 `agent_service.py` 标注 `TODO(申云飞)`；
      阶段 6 仍照常开工，理由与边界见 `stage-06-completion.md` 第 5 节偏离 #1

**结论**：阶段 6 的入口条件未全部满足（缺 AGENT-STAGE-05 通过 + 埋点存储确认），
本模块**按「先完成代码生成」的排期继续推进了阶段 6**，
并在 `stage-06-completion.md` 中如实标注这两条入口条件是欠账。

## 9. 经验与可复用产出

1. **「一次运行」的 Agent 不能做模块级缓存。** Prompt 里注入了当前时间，
   缓存住 Agent 等于把首次请求那一刻的日期钉死，服务跑过午夜之后所有相对时间
   （「今天下午」「本周五」）都会算错一天，且**不报错**，只给出一个看起来合理的错误方案。
   故 `build_agent()` 每次调用重新组装。

2. **`ChatOpenAI` 的 `api_key` 必须显式传参。** 它会隐式读取环境变量
   `OPENAI_API_KEY`，本机若存在同名变量，请求会被静默路由到别人的额度上，
   排查时极难看出。同理 `.env` 里的变量名**不用** `OPENAI_API_KEY`。

3. **假模型验不了时间戳，这件事要写在证据里而不是心里。**
   阶段 5 被单拎出来的原因就是它；用假模型跑通后如果直接标「通过」，
   等于把机制验证（保序顺延在跑）偷换成契约验证（真实间隔存在）。

## 10. 确认

| 角色 | 姓名 | 确认日期 | 备注 |
| --- | --- | --- | --- |
| 负责人 | 徐川 | 2026-09-27 | 待补真实 API 冒烟后改判 |
| Agent 组（LLM baseline） | | | 见第 6 节 #1 |
