# PR：模块 3（移动端预约与通知）对齐团队基线

> 建议分支：`feat/module3-team-align` → `main`
> 作者：模块 3 ｜ 日期：2026-09-26
> 关联：《docs/本次合并对齐方案.md》（对齐口径与风险）、
> 《docs/团队仓库合并冲突比对.md》（合并前冲突比对与第 11 节实测更正）

---

## 一、本轮边界

**本 PR 只做代码与测试合入。** 以下两项**明确延后到下一轮迭代**，本 PR 不含：

- ❌ `config.py` 与 `.env` 的**成对对齐**（`extra` 校验规则等）—— 需先与集成组确认 `.env` 权威键集合
- ❌ 文档的**章节级迁移**（并入团队权威 `api` / `database` / `deploy` / `test`）

> ⚠️ **`backend/app/core/config.py` 在本 PR 的 diff 里。**「延后」指的是**不按团队口径重写它**，
> 不是「diff 里没有这个文件」。它**必须**随本 PR 一起走：
> `services/agent_client.py` 要 `from ..core.config import AGENT_URL`，顶层 `tests/conftest.py`
> 依赖 `DATABASE_URL` 覆盖做 SQLite 隔离，而本模块 `.env` 里有 `AGENT_URL`
> —— 套团队版 `config.py`（`extra='forbid'` + 相对 `.env` 路径）会**启动即抛**。
> 真正要做的「成对对齐」（`extra` 校验规则 ↔ `.env` 权威键集合）见《本次合并对齐方案》第三节。
>
> `docs/` 下不做团队权威文档的合并。

---

## 二、变更面

### 后端代码

| 路径 | 变更 |
|---|---|
| `backend/app/core/database.py` | 取团队基线为主体（`async_engine`/`sync_engine`/绝对导入/池参数），保留两处临时补丁（下节） |
| `backend/app/models/` | 完整采用团队模型与 `__init__.py`（含 `system.py`/`inspection.py`）；主键列用 `PK_TYPE`；遵循云库真外键；不声明数据库索引 |
| `backend/app/schemas/agent.py` | 采用团队冻结版（`ScheduleRequest`/`TraceStep`/`Plan`/`ScheduleData`）—— 与团队**逐字相同**，故本 PR 对该文件**无 diff**；契约驱动的输出改动在 `agent_client.py` |
| `backend/app/api/agent.py` | 查真库取场地名传给 mock，避免编造场地名 |
| `backend/app/services/agent_client.py` | mock 输出对齐 `TraceStep` 对象数组；`title` → `spaceName`；各步 `timestamp` 互不相同且递增 |
| `backend/app/main.py` | 跟随引擎改名（`async_engine`） |
| `backend/seed.py` | 跟随引擎改名 |
| `backend/requirements.txt` | 补 `greenlet`、`aiosqlite`；`uvicorn` → `uvicorn[standard]`（WebSocket 需要）。**会改变队友的 venv**，见下 |

### 测试

| 路径 | 变更 |
|---|---|
| `backend/tests/conftest.py` | 仅保留公共引导（临时 SQLite 隔离 + `sys.path` 兜底） |
| `backend/tests/module3/` | **新增**：本模块 86 条用例迁入（含 `conftest.py`/`helpers.py`/9 个 `test_*.py`）；夹具新增 `_seed_users()` 预置 `sys_user` |
| `backend/tests/module4/` | 保留团队原有骨架 |

### 小程序

| 路径 | 变更 |
|---|---|
| `miniprogram/pages/agent/schedule.vue` | 思考链按 `t.result` + `timestamp` 渲染；方案标题改用 `spaceName` |
| `miniprogram/pages/reserve/detail.vue` | `agentTrace` 新旧兼容（`TraceStep` 对象 / 旧字符串） |

---

## 三、临时技术债（两处补丁，集成组修复后移除）

`backend/app/core/database.py` 中两处，均带 `[临时补丁 N/2]` 代码标记：

| # | 补丁 | 用途 | 移除条件 |
|---|---|---|---|
| 1 | `PK_TYPE` | SQLite 主键自增（单测 + §13.1 应急镜像库） | 集成组给出公共方案后 |
| 2 | `patch_asyncmy_ping()` | 修公用后端 `pool_pre_ping` × asyncmy 的 `ping` 崩溃 | 集成组在公用基线修好后 |

两处都**不改变本模块对团队的对外接口**。详见《本次合并对齐方案》第一节。

---

## 四、验证结果

| 项 | 结果 |
|---|---|
| 单测（`pytest -q`，`tests/module3/`） | **86 passed** |
| 真库 E2E（读接口 / 上传占位 / Agent / 建单·确认·取消 / WebSocket 推送 / 409·404·422 边界） | **24 / 24** |
| 并发验证（300 并发打真库，超过池上限 15 必然复用连接） | **300 / 300 全部 200**，补丁 2 在连接复用路径上生效 |
| `seed.py` | 引擎改名后跑通 |

> 并发项专门覆盖「连接复用」路径 —— 该路径是补丁 2 的根因所在，也是 SQLite 单测**照不出来**的
> 唯一场景（单测全绿 ≠ 真库不炸），故单列。

---

## 五、交接清单

| # | 事项 | 负责人 | 状态 |
|---|---|---|---|
| 1 | **确认种子数据源**（云库现状 vs `docs/seed.sql`，评审场景 C/D 前提已失效） | 集成组 | **最高优先级** |
| 2 | 工单 **#1 ping 补丁**、**#2 `PK_TYPE` 公共方案** —— **分开跟踪** | 集成组 | 待确认 |
| 3 | 确认数据库 `idx_*` 索引**补建 / 废弃**（§6.7 第 7 步未执行，云库实测 9 个全缺） | 集成组 | 待确认 |
| 4 | 提供 `sys_user` / `sys_role` **权威种子**（现 `sys_user` 仅 1 行演示用户，`sys_role` 空表） | 集成组 | 待确认 |
| 5 | 确认 `AGENT_TIMEOUT` 取值、**JWT 切换时间点** | 徐川（模块 4） | 待确认 |
| 6 | 确认**通知模块业务边界** | 黄嵩（模块 7） | 待确认 |
| 7 | **轮换密钥、清理已提交的 `.env`** | 管理员 | 已通知 |
| 8 | **`weix/` 纳入 git 版本控制**（本 PR 的前置） | 本模块 | **已完成**（本地仓 + 两个提交，见第六节） |

**下一轮迭代**：`config.py` 与 `.env` 成对对齐、文档章节迁移。

---

## 六、交付方式与阻塞（2026-09-26 实测）

### 6.1 已完成

`weix/` 已建本地 git 仓库，两个提交：

| 提交 | 内容 |
|---|---|
| `e74e7e5` | **基线**：团队 `main` 的文件树（由 codeload 归档重建，非团队真实提交对象） |
| `2a2ee462` | **本轮对齐**：63 文件，+3852 / −77，**0 处删除** |

暂存与提交都只按显式文件清单（`--pathspec-from-file`）逐条加入，**从不使用 `git add -A`**，
故团队侧文件一个都没被删。提交后复跑：**86 passed**。

### 6.2 ⚠️ 阻塞：本机推不上去

两条通道都实测失败，**推送必须在另一台机器上做**：

| 通道 | 实测结果 |
|---|---|
| HTTPS（`github.com`） | `Recv failure: Connection was reset`（网络层被重置） |
| SSH over 443（`ssh.github.com:443`） | `Permission denied (publickey)`（本机密钥未被授权） |

### 6.3 操作流程：补丁路线 + fork 发 PR

交付物：`he/module3-team-align.patch`（约 180 KB，含提交信息，可直接 `git am`）。

在**有网络的机器**上执行：

```bash
# 0) 前提：ssh 通道可用（本机 HTTPS 被重置，只能走 ssh 或 ssh.github.com:443）
ssh -T git@github.com

# 1) 网页 fork 团队仓库到你自己的账号（已有则跳过）
#    https://github.com/Aurora-0813/Scheduling_Platform → Fork
#    然后 clone 你**自己的 fork**，不是团队仓库
git clone git@github.com/<你的用户名>/Scheduling_Platform.git
cd Scheduling_Platform

# 2) 身份信息（am 会用它当提交者；作者在下一步单独 amend）
git config user.name  "你的名字"
git config user.email "你的邮箱"

# 3) 把团队仓库挂成 upstream，基于**团队 main** 开分支
git remote add upstream git@github.com:Aurora-0813/Scheduling_Platform.git
git fetch upstream main
git checkout -b feat/module3-team-align upstream/main

# 4) 应用补丁（--3way：11 个「修改」类文件走三方合并，兜住换行/空白差异）
git -c core.autocrlf=false am --3way /path/to/module3-team-align.patch

# 5) 替换占位作者（补丁里是 module3-weix <module3@localhost.localdomain>）
git commit --amend --author="你的名字 <你的邮箱>" --no-edit

# 6) 校验：0 处删除 + 63 文件
git diff upstream/main --diff-filter=D --name-only | wc -l   # 必须是 0
git diff upstream/main --stat | tail -3                      # 期望 63 files, +3852 / −77

# 7) 推到你自己的 fork
git push -u origin feat/module3-team-align
```

8. **网页开 PR**：base = `Aurora-0813/Scheduling_Platform` : `main`，
   head = `<你的用户名>` : `feat/module3-team-align`。PR 描述直接粘第一节～第五节。

> `--3way` 用得上：本补丁的「修改」类文件都带有 pre-image blob 哈希，而本地基线是由团队
> 真实文件树重建的，**blob 哈希与团队仓库一致**，所以三方合并有完整素材，不用手工找旧版本。

### 6.3.1 为什么选补丁路线，不直接推本地分支

两个理由，缺一都不成立：

1. **没有共同祖先**：`weix/` 原本不是 git 仓库，本地基线是由 codeload 归档**重建**的，
   与团队 `main` 的真实提交对象无共同祖先。直接推会被判为 unrelated histories，PR 无法比对。
2. **会把 9 个文件标记删除**：重建基线时，团队已提交的 `backend/.env` 与 8 个
   `__pycache__/*.pyc` 被有意排除在外（理由见 6.4）。直接推这个分支，这 9 个文件会
   相对团队 `main` 显示为删除。

补丁路线对这两条都是免疫的：它以**真实 `main` 为基线应用改动**，天然有共同祖先；
且补丁只覆盖本模块范围内的文件，团队 `main` 上的其他文件
（`frontend/`、`scripts/`、`backend/alembic/`、`LICENSE`、`backend/.env` 等）**原样不动，
一处删除都不会产生**。

### 6.4 两处刻意排除（务必知悉）

`backend/.env` 与团队提交的 8 个 `__pycache__/*.pyc` **不在补丁里**，属有意为之：

- `.env` 含真实库口令。把它写进本地仓库的 git 对象等于把凭据固化成一个持久副本，
  所以基线重建时也**没有**把它放进去（这是「凭据绝不进 PR」的落实，非疏漏）。
- `__pycache__/*.pyc` 是编译产物，本就不该进版本库，一并排除。
- 后果：**若不走 6.3 的补丁路线、而是直接推这个本地分支**，这 9 个文件会显示为删除
  （6.3.1 的第 2 条理由）。走补丁路线则无此问题。

### 6.5 冲突处理（`git am --3way` 报冲突时）

**冲突只可能出在 11 个「修改」类文件上**（其余 52 个是新文件，除非上游也新建了同名路径）。
上游 `main` 自 2026-09-25 00:52 起若没动过，则一处冲突都没有。

先看清方向，这是最容易搞反的一步：在 `git am` 的三方合并里，
**`<<<<<<< HEAD` 一侧是团队 `main`，另一侧（`>>>>>>>`）才是本模块的改动。**

```bash
git status                 # 冲突文件显示为 UU / AA
# ——逐个解决后——
git add <已解决的文件>
git am --continue
# 想放弃重来：
git am --abort             # 回到 am 之前，工作区干净
```

逐个文件的口径：

| 文件 | 解决口径 |
|---|---|
| `app/core/database.py` | 以**团队侧**为准，再把两段 `[临时补丁 N/2]` 手抄回去（`PK_TYPE` 常量、`patch_asyncmy_ping()` 与「导入时接线」的 `if`） |
| `app/models/*.py`（5 个：`system`/`resource`/`reservation`/`inspection`/`notification`） | 以**团队侧**为准；仅把主键列类型换成 `PK_TYPE`；**不要**加任何 `idx_*` 索引；跨模块字段保留真外键 |
| `app/models/__init__.py` | 取并集（团队 6 个模型 + 团队既有导出） |
| `app/core/config.py` | 以**本模块侧**为准（绝对 `.env` 路径 + `extra="ignore"` + `AGENT_URL`/`DATABASE_URL`），理由见第一节 |
| `app/schemas/__init__.py` | 保留团队导出，补上本模块的 `order` |
| `tests/conftest.py` | 以**本模块侧**为准（顶层只留公共引导：SQLite 隔离 + `sys.path` 兜底） |
| `requirements.txt` | 保留团队新增行，并保留本模块的 `greenlet` / `aiosqlite` / `uvicorn[standard]` |

**兜底**（`--3way` 都合不了，或想逐文件过目）：

```bash
git am --abort
git apply --3way --reject /path/to/module3-team-align.patch   # 合不了的产出 .rej，逐个看
git add -A && git commit        # 提交信息从补丁头部复制（git am 没走成，不会自动带）
```

**解决完务必复跑**（这一步需要 `backend/.env` 与数据库隧道，两者都不在仓库里）：

```bash
pwsh backend/start_tunnel.ps1                    # 先开隧道，否则启动即 asyncmy 2003
cd backend && python -m pytest -q                # 期望 86 passed
```
