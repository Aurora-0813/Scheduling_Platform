# 数据库连通后的执行清单（模块 8）

> **面向**：刘婷婷自己执行（逐条勾选）；结果需同步给团队，故本文档进仓库
> **依据**：《开发流程.md》6.9（种子数据）、9.4（数据链路）、10（测试）；
> 本模块 [开发计划.md](../开发计划.md) 的阶段 0 / 1 / 3 / 5
> **编写日期**：2026-09-27（**2026-09-28 更新**：`/report` 的 `exportUrl` 已落地并加 7 天清理，
> 步骤 5 对应两条已按实现校正；LLM baseline 已定案；
> **场地使用率分母定型为逐行读实际时段**（P2 第 1 项完成，U 组 3 条 `skip` 解除，
> 步骤 2.2 / 3B / 4.2 已按此重写））
> **前置**：申云飞的数据库连接已打通（SSH 隧道或云库 IP 白名单）
> **配套文档**：[test.md](test.md)（用例与可断言性）、[api-dashboard.md](api-dashboard.md)（接口契约）

---

## 0. 三条铁律（每次动手前扫一眼）

- [ ] **1. 解释器一律用全路径**，不要敲裸 `python`

  ```
  D:\conda_envlist\envs_dirs\smart_dev\python.exe
  ```

  仓库根 `.venv` 是个**只有 pip 的空环境**，却排在 `PATH` 最前
  （实测 `PATH` 里 `.venv/Scripts` 确实在 `/c/Windows` 之前）。
  敲裸 `python` 会命中它并报 `No module named 'pydantic'`，**看起来像依赖没装**。

  开工前先自检一句，输出必须是 `smart_dev` 的路径：

  ```bash
  "D:/conda_envlist/envs_dirs/smart_dev/python.exe" -c "import sys; print(sys.executable)"
  ```

  > 若你更愿意用 `conda activate smart_dev`，也行 —— 但仅当 conda 已对该 shell
  > 做过 `conda init`。激活成功后同样用上面那行自检确认，别凭感觉。

- [ ] **2. 本清单内全部是只读 SELECT**，不写库。
  表结构变更（DDL）/ 补数据（UPDATE / `seed.sql`）**属集成组范畴**，
  遇到需要改数据的情况 → 记录 + 转申云飞，不要在 dashboard 模块里自己动手。

- [ ] **3. 停 uvicorn 用 Ctrl+C；要强杀就按端口定位 PID**：

  ```bash
  netstat -ano | grep :8010        # 拿到 PID
  taskkill /F /PID <pid>
  ```

  **绝不要用 `taskkill /F /IM python.exe`** —— 那会杀掉机器上所有 Python 进程，
  包括你自己开着的 PyCharm 调试。

---

## 步骤 1：跑 `check_data.py`（只读）

### 命令

```bash
cd /e/projects/Scheduling_Platform/backend
"D:/conda_envlist/envs_dirs/smart_dev/python.exe" scripts/check_data.py
```

（cmd / PowerShell 下路径用反斜杠：`"D:\conda_envlist\envs_dirs\smart_dev\python.exe" scripts\check_data.py`）

**退出码**：`0` = 连上了；`1` = 连接失败（脚本会打印排查方向，不打堆栈）。

### 脚本会打印 4 节，逐节核对

- [ ] **第 1 节 `---------- 1. 各表行数 ----------`**
  9 张表逐行列出：`sys_user` / `sys_role` / `sys_permission` / `space_resource` /
  `device_resource` / `reserve_order` / `inspect_record` / `repair_ticket` / `notify_message`。
  单表查询失败会打印 `查询失败: ...` 而不中断 —— **有失败项要单独记下来**。

- [ ] **第 2 节 `---------- 2. reserve_order.device_ids 原始格式 ----------`**
  打印前 5 条订单的 `id / status / type / value`，并给出小结行。
  本轮**期望**：`type=list`，`value` 形如 `[1, 2]`。

- [ ] **第 3 节 `---------- 3. device_resource 种子结构 ----------`**
  前 5 条的 `id / 设备名 / 类型 / 状态 / total_count / available_count`，
  然后是 `设备行数 COUNT = N`、`台数合计 SUM(total_count) = M`，
  最后是判据行 `>>> 量纲判定（决定已定型口径是否自洽）<<<`。

- [ ] **第 4 节 `---------- 4. space_resource 开放时段 ----------`**
  前 5 条的时段值 + **全表**的类型集合与 NULL 计数（比只看前 5 条可靠），
  然后是判据行 `>>> 对 get_space_usage_rate 的影响 <<<`。

### ⚠️ 第 5 项脚本没覆盖，要手工跑

你列的 5 项记录里，**前 4 项脚本已经覆盖**，不用再单独跑 SQL：

| 你要的 | 脚本是否覆盖 | 覆盖处 |
| --- | --- | --- |
| 1. 9 张表行数 | ✅ | 第 1 节 |
| 2. `device_resource.total_count` 分布 | ✅ | 第 3 节（前 5 条明细 + COUNT/SUM 合计） |
| 3. `open_start_time` / `open_end_time` 类型 | ✅ | 第 4 节（全表类型集合 + NULL 数） |
| 4. `reserve_order.device_ids` 样本 | ✅ | 第 2 节 |
| 5. `order_status` 分布 | ❌ **未覆盖** | 见下方 |

> 第 5 项为什么要查：演示前必查项。状态 1（待确认）若有大量数据、且最终都被取消，
> 场地使用率会被**虚高**（口径已放宽到 `[1,2,4]`，见 [开发计划.md](../开发计划.md) P1-4），
> 答辩话术要预先备好。

> **本模块查库一律走 Python 脚本连库，不要指望 `mysql` 命令行** ——
> 本机**没有装 MySQL 客户端**（`mysql` / `mysqlsh` 都不存在，也没有 `C:\Program Files\MySQL`），
> 所以「敲一条 SQL 看看」这条路走不通。好消息是 `smart_dev` 里 `pymysql` + `asyncmy` 齐全，
> 而项目自己的 `settings.sync_database_url` 就是 pymysql 驱动 —— 直接用它连，不用另配凭据。
>
> 这类写法值得记住：**以后凡是临时查库，都用下面这个套路**（只读 SELECT）。

在 `backend/` 下执行这一条：

```bash
cd /e/projects/Scheduling_Platform/backend
"D:/conda_envlist/envs_dirs/smart_dev/python.exe" -c "import sys;sys.path.insert(0,'.');from sqlalchemy import create_engine,text;from app.core.config import settings;e=create_engine(settings.sync_database_url);c=e.connect();print([tuple(r) for r in c.execute(text('SELECT order_status, COUNT(*) FROM reserve_order GROUP BY order_status'))])"
```

输出形如 `[(1, 12), (2, 30), (3, 8), (4, 25)]` → 抄进下面的记录表。

> 顺带说明：这条用的是 `settings.sync_database_url`（项目自己的 `.env` 配置，pymysql 驱动，
> 是 `@property` 所以**不加括号**），与 `check_data.py` 读的是同一份配置，不存在另找凭据的问题。
>
> ⚠️ **必须 `cd` 到 `backend/` 再跑**：`config.py` 里 `env_file=".env"` 是**相对路径**，
> 在别的目录下执行会读不到 `.env`，于是端口退回默认值（不是 3308）→ 报连接失败，
> 症状看着像「隧道断了」，其实是跑错目录。

- [ ] **本步记录**（填完同步到 `docs/data-audit.md`，见步骤 4）

  | 项 | 实测值 |
  | --- | --- |
  | 9 张表行数 | sys_user= / sys_role= / sys_permission= / space_resource= / device_resource= / reserve_order= / inspect_record= / repair_ticket= / notify_message= |
  | `device_resource` 行数 COUNT | |
  | `device_resource` SUM(total_count) | |
  | 量纲判定结果（相等 / 不等） | |
  | `open_start_time` 类型集合 / NULL 数 | |
  | `open_end_time` 类型集合 / NULL 数 | |
  | `device_ids` Python 类型 | |
  | `order_status` 分布 | |

---

## 步骤 2：按实测结果定型（三张分支表）

> **术语更正**：`COUNT_MODE` 开关与 `by_row` / `by_total` 两个取值
> **已于 2026-09-27 随 `device_ids` 格式定型一并删除**，现在只有一套口径：
> 分母 = `SUM(device_resource.total_count)`，分子 = `COUNT(DISTINCT jt.did)`。
> 所以下面不再是「二选一切开关」，而是「现有口径是否自洽 / 要不要改代码」。

### 2.1 量纲分支（看第 3 节判定行）

| 实测 | 含义 | 动作 |
| --- | --- | --- |
| `两者相等 → 每行 total_count 均为 1。` | 分子（去重 ID 数）与分母（台数）**同量纲**，口径自洽 | ✅ **无需改代码**，`get_device_idle_rate` 保持现状 |
| `两者不等 → 存在「一行多台」的设备` | 借走一行只计 1 台占用，**占用被低估、闲置率偏高** | ⚠️ **需改代码**：分子要按 `total_count` 加权（`SUM(dr.total_count)` 而非 ID 计数）。**先别急着改**，把实测数据发我，一起定完再动 |

- [ ] 已判定，结论：____________

### 2.2 开放时段分支（看第 4 节两行判据）

⚠️ NULL 是**按行**的，不是全局二选一：非空行用实际时段，NULL 行走 14h 兜底。

| 实测判据行 | 含义 | 动作 |
| --- | --- | --- |
| `非空值类型均为 datetime.time →` | 类型干净 | 直接做时间减法取时长 |
| `非空值类型不全是 datetime.time（实际 ['str'])` | 存的是字符串 | 计算前先统一解析；**脚本此时会早退不实算**（避免 `AttributeError`） |
| `该字段全部为 NULL →` | 全表没填 | 分母只能全部走兜底 |
| `存在 NULL 行（start N 条 / end M 条）` | 部分缺失 | **已实现**：NULL 行按兜底 `OPEN_HOURS_FALLBACK = 14` 计，**不作为「不可用」排除** |
| `无 NULL 行 →` | 全表都有值 | 分母完全按各场地实际时段累加 |
| `⚠️ N 条走的是兜底` | 逐行点名 | **这才是要看的东西** —— 该场地时段缺失或 `end <= start`，属脏数据 |

> **2026-09-28 更新**：第 4 节已从「问要不要改分母」改成**调服务的 `_open_hours`
> 实算分母**，并逐行标出兜底行及原因。分母口径已定型（P2 第 1 项完成），
> 常量改名 `OPEN_HOURS_FALLBACK`（语义是兜底值，不是「每场地每天 14h」）。
> 真库实测：8 个可用场地、**无一行 NULL**，三种时段共 111 h/天。

- [x] 已判定（2026-09-28）：**分母逐行读实际时段**，NULL / `end <= start` 走兜底
- [ ] **另需转申云飞**：DDL 里那条 `UPDATE ... WHERE open_time IS NOT NULL` 疑似漏填，
      导致原本 `open_time` 为空的行至今没有开放时段。**表结构变更不属本模块范畴**，
      只提出、不擅自补 UPDATE（见 [开发计划.md](../开发计划.md) P2 前置条件二）。
      真库实测无 NULL 行，所以这条**当前不会造成数字偏差**，但新增场地若忘填时段就会。

### 2.3 `order_status` 分支（看步骤 1 第 5 项）

- [ ] 状态 1（待确认）有数据 → 评估占比。若占比高，备好答辩话术：
      「我们修正了统计口径，把待确认和已完成也纳入真实占用，之前的 `[2, 4]` 漏了这两个状态。」
- [ ] 状态 1 为 0 或极少 → 无需额外话术

---

## 步骤 3：U 系列用例（⚠️ 这步要拆成两半看）

> **为什么不能直接「跑 U1–U8」**：U 系列是**夹具用例** —— 期望值（20.0% / 100.0% …）
> 是按「2 个场地均 14h × 7 天 = 196h」这类**人造夹具**算出来的，
> 真库里的场地数与开放时长是另一回事，**套不上真库数据**。
> 且 `backend/tests/` 与 `pytest.ini` 属阶段 5，**尚未创建**，现在没有可执行的用例文件。
>
> 所以真库通了之后，这一步要做的是两件不同的事 ↓

### 3A. 真库交叉核对（只有通了库才能做，价值最高）

- [ ] **3A-1 场地使用率**：手工 SQL 算出的值应当与服务输出一致

  ```sql
  SELECT COUNT(*) FROM space_resource WHERE status = 1;

  SELECT SUM(TIMESTAMPDIFF(MINUTE, start_time, end_time)) / 60 AS hours
  FROM reserve_order
  WHERE order_status IN (1, 2, 4)
    AND start_time >= NOW() - INTERVAL 7 DAY;
  ```

  期望使用率 = `hours / (可用场地数 × 14 × 7) × 100`

- [ ] **3A-2 设备闲置率 —— 顺便把 `JSON_TABLE` 在真库上跑通**（本次改动里
      **唯一从未在真库执行过**的 SQL，最重要的一条）：

  ```sql
  SELECT SUM(total_count) FROM device_resource;

  SELECT COUNT(DISTINCT jt.did)
  FROM reserve_order AS ro
  JOIN JSON_TABLE(
           COALESCE(ro.device_ids, JSON_ARRAY()),
           '$[*]' COLUMNS (did BIGINT PATH '$')
       ) AS jt
  JOIN device_resource AS dr ON dr.id = jt.did
  WHERE ro.order_status IN (1, 2)
    AND ro.start_time >= NOW() - INTERVAL 7 DAY;
  ```

  期望闲置率 = `(1 - 占用数 / 台数合计) × 100`

  > 若 `JSON_TABLE` 报语法错 → 记录 **MySQL 版本**（需 8.0.4+），转申云飞。
  > 若结果与接口输出对不上，先排除时间基准差异：服务的 `since` 取的是
  > **应用进程本地时间**，上面的 SQL 取的是**数据库服务器时间**（云库可能不同）
  > —— 差 1 台 / 0.1% 量级通常源于此，不是口径错。

- [ ] 3A-3 两条都核对完，记录：服务输出 = ____ / 手工 SQL = ____ / 是否一致 ____

### 3B. U 系列断言（阶段 5，需先建测试骨架）

- [x] 建 `backend/tests/` + `pytest.ini`（**`asyncio_mode = auto`**，
      否则 `async def` 用例不会被真实执行 —— 《规范》3.6 特别强调）
      已于 2026-09-27 完成
- [x] **U3 / U5–U8：可直接断言**。它们用的是**假 session 夹具**、
      **不需要真库**，所以这一步与「库通没通」无关
- [x] **U1 / U2 / U4 的 `skip` 已于 2026-09-28 解除**（分母口径定型，P2 第 1 项完成）。
      断言体一字未动，解禁结果：
  - U1 / U2 **直接通过** —— 它们只依赖分母
  - **U4 失败 20.7 ≠ 20.0** —— 翻出**第二个、独立的缺口**：
    分子没按场地状态过滤，把挂在停用场地上那 2 小时也算进了占用。
    这是 P2 第 3 项，**列了但一直没做**。已用 `xfail(strict=True)` 锁住，
    修好后会 XPASS 报错。真库当前无停用场地，影响为 0
- [x] 另补 U9（按真库实测分布锁分母）/ U10（异常时段不猜跨天）
- [x] 用例细节见 [test.md](test.md) 第三节；D / H / C 三组同样按 test.md 落地

---

## 步骤 4：更新文档

### 4.1 新建 `docs/data-audit.md`

**该文件目前不存在**（`docs/` 下现在只有 `api-dashboard.md` 和 `test.md`），
需新建。把步骤 1 的记录表 + 下面两张表填进去即可：

**表 A：数据现状**（抄步骤 1 的实测值）

| 核查项 | 实测值 | 判定 |
| --- | --- | --- |
| 连接方式 / 目标 | | |
| 9 张表行数 | | 有无种子数据 |
| `device_resource` COUNT vs SUM(total_count) | | 量纲是否自洽 |
| `open_start_time` / `open_end_time` 类型与 NULL 数 | | 分母可否改革 |
| `device_ids` Python 类型 | | 是否 = `list` |
| `order_status` 分布 | | 状态 1 占比 |

**表 B：四个指标现状**（步骤 3A 的核对结果）

| 指标 | 服务输出 | 手工 SQL | 是否一致 | 备注 |
| --- | --- | --- | --- | --- |
| 场地使用率（7 天） | | | | |
| 设备闲置率（7 天） | | | | |
| 高峰时段 Top 1 | | | | |
| 故障频次 Top 1 | | | | |

- [ ] `docs/data-audit.md` 已创建并填写

### 4.2 更新 `docs/test.md`

- [x] 第三节 U 系列：U1 / U2 / U4 的状态已由「⏸ 依赖 P2 暂缓」更新为实测结论
      —— **已于 2026-09-28 完成**（P2 第 1 项落地）：U1 / U2 → ✅；
      U4 → ⚠️ `xfail(strict=True)`（期望值对，缺的是分子过滤实现）；并补 U9 / U10
- [x] 第 0.1 节可断言性分级表：已同步（原「⏸ 依赖 P2」一级撤销，
      新增「⚠️ 断言到位、实现有缺口」一级）
- [ ] 若步骤 2.1 判定量纲不一致 → **第二节 I 系列的期望值要整体重算**，
      并在该节顶部标注「分子口径已于 ____ 变更为按 total_count 加权」

---

## 步骤 5：验证两个接口

### 启动

```bash
cd /e/projects/Scheduling_Platform/backend
"D:/conda_envlist/envs_dirs/smart_dev/python.exe" -m uvicorn app.main:app --port 8010
```

- [ ] 启动日志无异常（注意：`core/database.py` 在模块级建引擎，驱动缺失会在这里就报错）

### `GET /api/v1/dashboard/stats`

```bash
curl "http://127.0.0.1:8010/api/v1/dashboard/stats"
curl "http://127.0.0.1:8010/api/v1/dashboard/stats?days=30"
```

- [ ] HTTP 200，响应体是 `{"code":200,"message":"ok","data":{...}}`
- [ ] `spaceUsageRate` / `deviceIdleRate` **非全 0**（全 0 说明库里没种子数据 → 转申云飞执行 `seed.sql`）
- [ ] `peakHours` 非空（空 = `reserve_order` 无数据，同时要问蔡玉礼预约组）
- [ ] `faultFrequency` 非空（空 = `repair_ticket` 无数据，要问杨睿坤巡检组）
- [ ] `days=30` 与 `days=7` 的数值**不同**（证明参数真的生效了；若完全相同，回来找我）
- [ ] 数值与步骤 3A 的手工 SQL 一致
- [ ] `data` 里**有 `degraded` 字段且为 `false`**（2026-09-28 新增的第 5 个字段）。
      真库通的时候它必须是 `false` —— 若这里读到 `true`，说明**取数其实失败了**，
      上面那些数值全是占位零值，**不能当成真数据记进核查结果**
- [x] ~~⚠️ 已知缺口：库抖一下 `/stats` 会返回 500~~ ✅ 2026-09-28 已补兜底（P2 完成）：
      库不可达时返回 200 + `degraded=true` + 空 4 字段，与 `/report` 行为对齐。
      所以真库核查时**看到 500 反而是新问题**（去查后端日志），不再是「预期现状」

### `GET /api/v1/dashboard/report`

```bash
curl "http://127.0.0.1:8010/api/v1/dashboard/report"
```

- [ ] HTTP 200（**任何情况下都不该 500**）
- [ ] `data.exportUrl` 是**路径**（形如 `/static/exports/dashboard_20260928_194500.csv`，不再是 `null`），
      且**能真的下载到** —— 直接把返回的路径拼到 base 后面 curl 一下，应拿到 200 且首三字节是
      `EF BB BF`（BOM，Excel 中文乱码的分界线）：
      ```bash
      # 取前 3 字节看 BOM（不要用 -I，那只取响应头，看不到文件内容）
      curl -s "http://127.0.0.1:8010/static/exports/dashboard_<时间戳>.csv" | head -c 3 | od -An -tx1
      # 期望输出： ef bb bf
      ```
      404 说明静态挂载点与 URL 前缀漂移了（两处隔着两个文件，E10 是这条的离线哨兵）
- [ ] 目录 `backend/static/exports/` 里的文件**保留 7 天**会自动清理（惰性 + 启动两处触发）。
      审计时若看到只有近期文件、没有陈年堆积，说明清理在工作；这是**预期行为**，不是文件丢了
- [ ] `data.suggestions` 非空数组，每条三要素齐全（`finding` / `evidence` / `suggestion`）
- [ ] `suggestions` 里的数字都能在 `/stats` 的返回中找到 —— **这是《规范》9.3 业务边界校验的现场验证**
- [ ] 跑之前先确认 `.env` 里 **`LLM_API_KEY` 已填**（各人自己的 key，**不入库、不贴群**）。
      另两个变量 **baseline 已定案（2026-09-27）**，仓库里的 `.env` 已配好，不用再问：
      - `LLM_MODEL_NAME=qwen-plus`
      - `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
        （**必须填全**：`LLM_BASE_URL` 留空会走 OpenAI 官方端点，然后因 key 无效而失败 ——
        `config.py` 里三个变量默认都是空字符串，靠 `.env` 覆盖）
- [ ] `data.degraded` 判断：
  - `false` → **AI 真的在工作**
  - `true` → **走了降级，是预期行为不是故障**。常见原因：没配 key / 超时 / 模型输出无法解析 /
    全部建议被判定为幻觉。属正常兜底，答辩时正是要展示这条路径
- [ ] 若 `degraded=false`，**这是第 1 层 `with_structured_output` 首次跑真实模型** ——
      此前所有验证用的都是假模型。请把这次的**原始返回**（`suggestions` 全文）截图存档，
      作为「AI 真的在工作 + 变量名已统一」的证据同步群里

      ⚠️ **顺带要看的一件事**：第 1 层已显式指定 `method="function_calling"`。
      若日志里出现「第 1 层失败」紧接着「第 2 层成功」，说明这条路仍然不通 ——
      `langchain-openai` 1.5.0 起 `with_structured_output` 默认 `json_schema`，
      而 DashScope 的 OpenAI 兼容模式对 `qwen-plus` **只支持 `json_object`、不支持 `json_schema`**，
      这正是当初必须显式覆盖 `method` 的原因。**没有测试守护这个参数**
      （假模型走不到真协议层），所以只能靠这次真实冒烟确认；
      每次升级 `langchain-openai` 都要重跑一次。

### 停止

- [ ] Ctrl+C 优雅退出（不要 `taskkill /IM python.exe`，见铁律 3）

---

## 步骤 6：`.pyc` 与 `.gitignore`

### ⚠️ 看 `git status` 之前先读这段：三条事实

**补 `.gitignore` 不会让 `git status` 变干净** —— 这是最容易误判的一条。
照直觉看 status，下面三件事都会判断错：

| 你可能会以为 | 实际是 | 正确做法 |
| --- | --- | --- |
| 「ignore 补好了，status 就该干净了」 | ❌ `.gitignore` **只管未被跟踪的文件**。已经被 git 跟踪的 `.pyc` 不会因为写了 ignore 就消失 | 已跟踪的必须 `git rm --cached <path>`，再提交一次才从 status 消失 |
| 「那两个 `.pyc` 删除在暂存区，得先清暂存」 | ❌ 是**工作区未暂存删除**（status 里显示 ` D`，改动在第 2 列，不在暂存区） | 直接 `git restore` 恢复，**不需要动暂存区** |
| 「status 里一堆 `??` 是垃圾 / ignore 漏了」 | ❌ 那是**模块 8 的待提交成果**：`backend/app/api/`、`app/services/`、`app/schemas/`、`app/core/response.py`、`backend/scripts/`、`docs/` | 属**正常且应该**，不要 ignore 掉 —— 它们正是这次要交的代码 |

> 一句话记法：`git status` = 「已跟踪文件的改动」+「未跟踪的新文件」两部分。
> `.gitignore` 只影响第二部分的**未来新增**，对第一部分和**已经存在的**新文件都无能为力。

### 动作 1：恢复误删的那 2 个 `.pyc`

```bash
cd /e/projects/Scheduling_Platform
git restore backend/alembic/__pycache__/env.cpython-313.pyc \
             backend/alembic/versions/__pycache__/8969262c9d0c_init_tables_single_role.cpython-313.pyc
```

### 动作 2：等申云飞补根目录 `.gitignore`

根目录**目前没有 `.gitignore`** —— 这 9 个 `.pyc` 当初能被 git 跟踪，就是因为缺它。
内容至少要有这两行：

```gitignore
__pycache__/
*.pyc
```

### 动作 3：已跟踪的 `.pyc` 要 `git rm --cached`

`git rm --cached` 只把文件从**索引**里移除，**工作区文件保留不动**（不会真删文件），
之后 `.gitignore` 才管得住它们。**这批由申云飞统一处理**。

### 验收判据（代替「status 干净」）

- [ ] `.gitignore` 里有 `__pycache__/` 和 `*.pyc`
- [ ] `git status` 的未跟踪列表里**不再出现新的 `__pycache__` / `*.pyc`**
- [ ] 已被跟踪的那批 `.pyc` 经 `git rm --cached` 后从 status 消失（由申云飞处理）
- [ ] 我删的那 2 个 `.pyc`：由你决定是 `git restore` 恢复、还是并进 `git rm --cached` 一起处理
- [ ] 确认 status 里的 `??` 列表**就是**模块 8 的待提交成果，没有多出别的东西

> 本模块侧我已经在 `.git/info/exclude` 里加了 `__pycache__/` 与 `*.pyc`
> 兜住本地噪音（该文件纯本地、不会 push）。但 exclude 与 `.gitignore` 同理，
> **同样不能取消已跟踪文件的跟踪状态**，所以那 9 个仍需 `git rm --cached`。

---

## 附：卡住了怎么办

| 现象 | 先怀疑 | 动作 |
| --- | --- | --- |
| 脚本退出码 1、`[连接失败]` | 隧道没起 / IP 没进白名单 / `.env` 的 `DB_PORT` | 按脚本打印的 3 条排查方向走；确认 `DB_HOST=127.0.0.1`、`DB_PORT=3308`（隧道端口） |
| `mysql: command not found` | 本机没装 MySQL 客户端（正常） | 改用 Python 连库，见步骤 1 第 5 项的单行命令 |
| `git status` 里 `.pyc` / `??` 看着不对劲 | 对 `.gitignore` 的作用范围理解偏了 | **先读步骤 6 那张对照表**，再判断，别急着动手 |
| `ModuleNotFoundError: No module named 'pydantic'` | **解释器选错了**（命中空 `.venv`） | 回到铁律 1，用全路径 + 自检 |
| `No module named 'asyncmy'` | 同上，用的是 base conda 而非 `smart_dev` | 同上 |
| 第 3 节「两者不等」 | 量纲不自洽 | **别硬套现有口径**，把数据发我，一起重定分子口径 |
| `JSON_TABLE` 语法错 | MySQL 版本 < 8.0.4 | 记录版本号，转申云飞 |
| `/stats` 返回 500 | **代码缺陷**（2026-09-28 起库不可达已降级为 200，不再是预期现状） | 查后端日志（`logger.exception` 有完整堆栈）；同时看 `data.degraded` |
| `/stats` 的 `degraded=true` | 取数失败，四项是占位零值 | **这不是「场地全空着」** —— 别把 0 记进核查结果；查后端日志的取数异常 |
| `/report` 返回 `degraded=true` | 无 key / 超时 / 幻觉全拦 | **正常**，这正是要展示的降级路径 |

---

## 执行完毕的标志

- [ ] 步骤 1 记录表填满，`docs/data-audit.md` 已建
- [ ] 步骤 2 三张分支表都判定了，需要改代码的已提出来（未擅自改）
- [ ] 步骤 3A 交叉核对一致，**`JSON_TABLE` 已在真库跑通**
- [ ] 步骤 3B 测试骨架已建，U3/U5/U6/U7/U8 断言落地，U1/U2/U4 已标 skip
- [ ] 步骤 4 两份文档已更新
- [ ] 步骤 5 两个接口实测通过，结果已记录
- [ ] 步骤 6 `.pyc` / `.gitignore` 已转申云飞，本模块侧无遗留

> 阶段 0 的验收标准（《开发计划》）：`GET /api/v1/dashboard/stats` 返回**非全 0 的真实数值**、
> 不报 500，且 `JSON_TABLE` 的 SQL 能在真库真实执行。以上全部勾完即达标。
