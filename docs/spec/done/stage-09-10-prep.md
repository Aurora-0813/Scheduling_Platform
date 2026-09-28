# 阶段 9 / 10 准备核对（2026-09-28，只读调研）

> **用途**：把阶段 9（提交与合并）与阶段 10（交付与交接）的**前置条件现状**一次查清，
> 让「能不能开阶段 9」有据可依，而不是到时候才发现卡在哪一条。
>
> **方法**：全部是**实测**——本分支、远端 ref、以及一个**试合并树**
> （`git merge-tree --write-tree HEAD origin/main`，git 2.55 的只算不合，**不落任何提交**）。
> 除试合并外未执行任何写操作。
>
> **依据**：`docs/spec/stage-09-merge.md`、`docs/spec/stage-10-handover.md`、
> 主文档 8.2/8.3/8.4/8.7/8.11。ruff 一律用 CI 固定的 **0.16.9** + 仓库自带 `backend/ruff.toml`。

---

## 1. 阶段 9 入口条件（3 条）

| # | 条件（stage-09 §2） | 现状 | 证据 |
| --- | --- | --- | --- |
| 1 | `AGENT-STAGE-08` 通过 | ☐ **未满足** | `done/stage-08-completion.md`：验收结论**不通过**（2026-09-28 经项目群复核**维持**），是全流程唯一仍判不通过的阶段 |
| 2 | 已在 `feature/agent-xuchuan`（禁止中文分支名） | ✅ 满足 | 当前分支即 `feature/agent-xuchuan` |
| 3 | `.github/workflows/ci.yml` 由集成组就位且能跑通 | ⚠️ **就位了，但在仓库根** | 真 CI 在 `origin/main` 的 `.github/workflows/backend-ci.yml`（`2f533ba`，job `defaults.run.working-directory: backend`）；**本分支里的 `backend/.github/workflows/ci.yml` 是陈旧副本，GitHub 永远不会执行它**（`.github` 必须在仓库根） |

**结论：入口 1 不满足，阶段 9 现在不能开。** 入口 3 的移位归集成组，本模块不用动手。

---

## 2. CI 跑起来会红几条（实测）

| 口径 | `ruff check` | `ruff format --check` | **本模块**（`app/agent/` + `tests/test_agent_*.py`） |
| --- | --- | --- | --- |
| 本分支（尚未合 main） | **49 条 / 10 文件** | **20 文件** | **0 条 / 0 文件** ✅ |
| 试合并树（解完 3 处冲突后） | **12 条 / 3 文件** | **8 文件** | **0 条 / 0 文件** ✅ |

**本分支 49 条的分布**（没有一条落在模块 4）：

| 文件 | 条 |
| --- | --- |
| `scripts/seed.py` | 15 |
| `tests/conftest.py` | 8 |
| `tests/smoke_fake_llm.py` | 5 |
| `app/services/format_service.py` | 5 |
| `tests/test_image_service.py` | 4 |
| `tests/smoke_real_llm.py` | 4 |
| `tests/test_image_smoke.py` | 3 |
| `app/core/llm.py` | 2 |
| `app/core/config.py` | 2 |
| `app/services/image_service.py` | 1 |

**试合并树的 12 条**：`tests/conftest.py` 6、`tests/smoke_real_llm.py` 4、`app/core/config.py` 2。
数字降下来的原因是 main 自己做过一轮清理（`3c51a9b style: 清理 39 条 ruff 告警 + 16 个文件按 ruff format 统一格式`）。

> ⚠️ `app/core/config.py:180-181` 这两条 E501 的 per-line blame 是 **xuchuan**（`8e945bda`，2026-09-27），
> 但它是**核心配置**（LLM 超时/重试），不属于模块 4 的文件；顺手清可以，不清也不记本模块的账。
> 另一处别混：`app/core/exceptions.py` 那 409 映射也常被当成「本模块的」——它是集成侧的裁定、
> 落在公共文件上，见 `merge-checklist.md` 第 1 条。

**另两个 CI 步骤本模块无风险**：

- `pre-commit run no-secrets-file --all-files`：`.env` 未被跟踪、全库无真实 Key（见 §4.4）。
- `pytest --cov=app`：本分支本地 `exit=0`，覆盖率 **88.16%**（阈值 80%）。

**处置口径**：CI 的 lint 两步仍会红，但**红的每一条都在别人的文件里**。
按 stage-09 §3.3 的明文——「若 CI 红的原因不在本模块，**不要绕过 CI**，按流程找责任人修」。

---

## 3. 合并目标：本分支能不能直接合 `main`

**先摆事实**：主文档 8.2 写的目标是 **`develop`**，而远端**没有这个分支**——
远端只有 `main`、`integrate/module3` 与各 `feature/*`。这条要在项目群定。

**「直接合 `main`」的技术答复：能合，但合了没用。**

| 项 | 实测 |
| --- | --- |
| `origin/main` 是本分支的祖先吗 | **不是**。本分支 58 个提交、main 独有 6 个，merge-base `98c54ea` → **不能快进**，只能真合或 rebase |
| 试合并结果 | **3 处冲突**：`backend/app/agent/prompts/image_prompt.py`（**本模块文件**）、`backend/app/api/v1/__init__.py`、`backend/app/core/exceptions.py`。三处都是**两边各跑过一次 `ruff format` 的格式相撞**，非语义分歧，但必须人工解 |
| main 上有模块 4 的入口吗 | **没有**。main 的 `backend/app/api/v1/` 只有 `__init__ / auth / health / image / mock / mock_data / monitor / voice` |
| main 上有模块 3 的真实现吗 | **没有**。main 的 `backend/app/services/` 没有 `order_service.py`（也没有 `space_service.py`、`device_service.py`） |

**所以「合 main」会把模块 4 的代码搬到一棵既缺模块 3、也没有模块 4 入口的树上，
演示主线仍然跑不通。** 建议：**先不要单方面合 main**，等 `develop` 出现（或集成组指定目标分支），
再与模块 3 一起合。这条由集成组/项目群定，本文件只报事实。

---

## 4. tag `v0.3-m3` 的前置条件

| # | 前置 | 现状 |
| --- | --- | --- |
| 1 | tag 名在远端未被占用 | ✅ `git ls-remote --tags origin` **为空**——远端一个 tag 都没有，`v0.3-m3` 可用 |
| 2 | `AGENT-STAGE-08` 通过 | ☐ 不通过（见 §1） |
| 3 | 分支已合入目标分支（tag 打在合并后的提交上，stage-09 §3.4：**合并后**打 tag） | ☐ 未合（目标分支待定，见 §3） |
| 4 | CI 绿灯 | ☐ lint 两步红（见 §2） |
| 5 | 有推送 tag 的权限 | 未验证（**不试推**，试推会真的建 tag） |
| 6 | `.env` 不入库 | ✅ 见 §4.4 |

**6 条里齐 2 条（1、6），前置未齐。** 关键的 2/3/4 都依赖阶段 8 与合并目标，不是本模块单方面能补齐的。

### 4.4 推送前五项检查的预检（stage-09 §3.2）

| # | 检查项 | 预检结果 |
| --- | --- | --- |
| 1 | `.env` 未提交，`git status` 看不到它 | ✅ `git status --porcelain` 里无 `.env` / `*.key` / `secret`；被跟踪的 env 文件只有 `.env.example` |
| 2 | `requirements.lock` 已同步 | ✅ **本模块未引入新依赖**（`git diff --stat 98c54ea..HEAD -- backend/requirements*` 为空） |
| 3 | `pytest -q --cov=app` 本地全绿 | ✅ `exit=0`，覆盖率 88.16% ≥ 80% |
| 4 | commit message 符合规范 | ⚠️ **部分**：58 个提交里 **6 个 scope 用了中文**（`docs(模块4)`/`test(模块4)`/`merge(模块4)`/`docs(卡点#5)`/`docs(卡点#8/#9)`/`docs(开发流程)`），**1 个 type 非标准**（`merge`）。按 stage-09 §3.1 的明文处置：**不重写历史**，在完成文档里如实说明 |
| 5 | 已 `git pull` 解决冲突 | ☐ 未做（要先定合并目标） |

> ⚠️ **`sk-` 那条检查是假阳性，别慌也别"修"**：`git log -p --all | grep -ic "sk-"` 得 **18 处**，
> 逐条看全是无害文本——`tests/smoke_real_llm.py:80-82` 是**脱敏正则的源码本身**
> （`re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "***", text)`），`test_agent_schedule.py:1010/1014` 与
> `test_voice_api.py:82/95`（模块 2 的文件）用的是**测试假值**，另有 2 处是 `mask-`。
> **真实 Key 形状（`sk-ant-` / `sk-proj-` / `sk-or-` / `sk-live-` / `sk_test_`）命中 0 处；
> `sk-` 后 ≥20 位的高熵长串 0 处。** 谁也别去删那段脱敏正则——它正是防泄漏的那道网。

---

## 5. 阶段 10 交付清单：9 项现状

（清单出处：`stage-10-handover.md` §1；逐项在本分支上查文件是否**存在且被 git 跟踪**）

| # | 交付物 | 现状 |
| --- | --- | --- |
| 1 | Agent 全部代码（tools / prompts / chains） | ✅ `backend/app/agent/`（已跟踪） |
| 2 | 请求响应 schema | ✅ `backend/app/schemas/agent.py` |
| 3 | Agent 服务层 | ✅ `backend/app/services/agent_service.py` |
| 4 | API 端点与 mock 路由 | ✅ `backend/app/api/v1/agent.py` + `mock.py`（另有 `mock_data.py`） |
| 5 | 全部测试用例 + 夹具 | ✅ `backend/tests/conftest.py` + 4 个 `test_agent_*.py` + 两个冒烟脚本 `smoke_fake_llm.py`、`smoke_real_llm.py` |
| 6 | 模块 4 接口文档 | ✅ `docs/api.md` 模块 4 小节（`## 模块 4：核心调度 Agent`、`### POST /api/v1/agent/schedule`） |
| 7 | 用例清单与环境基线 | ✅ `docs/test.md` |
| 8 | mock 响应样例 | ✅ `docs/mock/agent_schedule.json` |
| 9 | 阶段完成文档 `done/stage-00~10-completion.md` | ⚠️ **10 / 11 份**：`stage-00 ~ stage-08` 8 份 + `stage-10` 1 份（**2026-09-24 预置占位，阶段 10 未执行**）→ **缺 `stage-09-completion.md`**（预期，阶段 9 未执行） |

**9 项里齐 8 项，第 9 项缺 `stage-09-completion.md`。** 其余 8 项都在、都被跟踪、都可在仓库里查到。

---

## 6. M4 四项前置：逐条现状

（出处：`stage-10-handover.md` §4.1；四项**原本全为 ☐**，这里逐条给现状与卡点）

| # | 前置 | 现状 | 卡在哪 |
| --- | --- | --- | --- |
| 1 | 桩函数全部替换 | ☐ 未齐 | `app/agent/` 自身无遗留桩，但 `generate_notification` 仍走模块 7 的**桩**：`notify_service.py` 里 `"延期致歉": None` → 返回 `ok=false`（未决 #6）；`lock_resources` 返回体里也仍带 `stub` 标记（桩期 `orderId` 恒 None 的产物）。责任人：模块 7 落地 + 集成组 |
| 2 | 屏 3 回放联调通过 | ☐ 未做 | 需与前端约定联调时间；阶段 8 的交接项尚无回执 |
| 3 | `agent_trace` 落库并在后台可展示 | ☐ 未验证 | 代码路径在（`persist_agent_trace` → `update_agent_trace`，按冻结的 §7.6 传裸列表），但**端到端没验过落库**：桩期 `orderId` 恒 None 时直接 `return False`，且要等模块 3 的真 `create_order` 落库才有 id。「后台可展示」依赖前端/模块 10，未见实现 |
| 4 | 埋点有真实数据 | ☐ 无数据 | 正式链路在 `origin/main`（`middlewares/agent_metrics.py` → `core/metrics.py` → `monitor_service` → `GET /api/v1/monitor/agent`）；本模块自建的**进程内计数已无读端**（仅本地排障用）。**真实数据**要等真实调用（真实 API 调用只在授权下跑过冒烟） |

---

## 7. 未决事项 6 项现状

（出处：`stage-10-handover.md` §4.2）

| # | 事项 | 责任人 | 状态 |
| --- | --- | --- | --- |
| 1 | `lock_resources` 的 `user_id` 如何传入 | 蔡玉礼 | ☐ |
| 2 | `TraceStep` 字段结构 | 前端 | ☐ |
| 3 | 40 秒思考过程：回放 vs SSE | 前端 + 集成组 | ☐ |
| 4 | `space_resource` 是否补 `tags` 字段 | 杨睿坤 + 集成组 | ✅ **已闭环（2026-09-28）**：不补列，改文档降级（`docs/开发流程.md`），登记硬卡点 #14；同步更正了 `stage-03-completion.md` 里的「待确认」 |
| 5 | 应急预案 SQLite 与「禁止本地数据库」冲突 | 集成组 | ☐ |
| 6 | `notify_type`(INT) 与中文枚举不一致 | 黄嵩 + 集成组 | ☐ （本模块的桩按「不擅自映射」处理，见 §6 第 1 项） |

---

## 8. 小结

**阶段 9 现在开不了**：入口条件第 1 条（`AGENT-STAGE-08` 通过）未满足，且它是全流程唯一仍判不通过的阶段。

**能提前做完的**（不依赖别人）：推送前五项检查的预检（本文件已做 4/5）、提交粒度与 message 的如实说明、
合并冲突的预判与解法（`merge-checklist.md` 第 6 节）。

**必须由别人裁定的两件**：

1. **合并目标**：主文档写 `develop`，远端没有；合 `main` 的话缺模块 3 的真实现、演示跑不通（§3）。
2. **CI 红灯的责任人**：lint 两步红的 49 条（合 main 后 12 条）**没有一条在模块 4**，
   按 stage-09 §3.3 不绕过、找责任人修（§2）。
