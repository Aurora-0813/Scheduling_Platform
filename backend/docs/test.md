# 测试用例文档

> 适用范围：后端全部自动化测试。
> 主管模块：**模块 10 系统集成与联调**。
>
> 权威来源：仓库根目录 `开发流程.md` 第 10 章（测试规范）。
> 本文档按 `开发流程.md` 10.2「所有测试用例必须记录在 `docs/test.md`」编写，
> 逐文件列出全部用例及其断言。**新增用例请同步本文档。**

---

## 一、总体情况

| 指标 | 数值 |
| --- | --- |
| 测试文件 | 14 个（`test_*.py`） |
| 测试函数 | **210** |
| 收集到的测试项（含参数化展开） | **349** |
| 最近一次全量运行结果 | **349 passed**（耗时约 236 秒） |
| 需要外部依赖（云库 / Redis / 大模型） | **0 个** |
| `xfail` / `pytest.mark.skip` | 无 |

### 1.1 分层分布

| 目录 | 文件 | 测试函数 | items |
| --- | --- | --- | --- |
| `tests/unit/` | 4 | 96 | 178 |
| `tests/api/` | 6 | 93 | 144 |
| `tests/integration/` | 3 | 21 | 27 |
| **合计** | **14**（含 `conftest.py` 与 `fakes/`） | **210** | **349** |

### 1.2 marker 分布

| marker | 函数数 | 说明 |
| --- | --- | --- |
| `unit` | 63 | 纯逻辑，不涉及数据库与网络 |
| `api` | 101 | 通过 ASGI 客户端调用，用 SQLite 临时文件库 + 假 Redis |
| `db` | 5 | 直接驱动 `get_db` 的契约测试，不经过 HTTP |
| `migrations` | 8 | 通过 subprocess 驱动 alembic |
| `integration` | **0（已注册，当前无用例）** | 需要真实外部依赖；见 5.2 |

> `pytest.ini` 里注册了 `integration` marker，但当前**没有任何用例使用它**。
> `tests/integration/` 目录下的文件分别使用 `api` / `db` / `migrations` —— 这样它们在云库不可达时**照样能跑**，
> 而 `开发流程.md` 10.1 意义上的「需要真库的集成测试」尚未编写（见 5.2）。

---

## 二、测试策略

### 2.1 离线为主（核心决策）

云库、Redis、大模型在当前网络环境**都不可达**，因此测试**全部离线运行**：

| 依赖 | 测试替身 | 实现位置 |
| --- | --- | --- |
| MySQL 云库 | **SQLite 临时文件库**（`sqlite+aiosqlite:///<tmp>`，每个用例一个文件） | `tests/conftest.py` |
| Redis | **`FakeRedis`**（最小异步实现，含 pipeline/GETDEL/TTL） | `tests/fakes/fake_redis.py` |
| 大模型 | 无需（模块 9/10 不调用大模型） | — |

**为什么用临时文件库而不是 `:memory:`**：`:memory:` 每个连接是一个独立数据库，
而本项目要验证「未提交的写入在**另一个连接**里查不到」（事务边界，见 `test_db_session_contract.py`），
内存库下两条连接看到的是两个库，这个断言会失去意义。

**不给业务代码建 SQLite 路径**：SQLite 只出现在 `tests/` 与 `alembic` 的测试开关里。
`开发流程.md` 13.1 那条「切换本地 SQLite 镜像库」是**演示应急预案**，不落进生产代码。

### 2.2 环境变量守卫（收集期自检）

`tests/conftest.py` 在**任何 `app.*` import 之前**设置 4 个环境变量，并紧跟两条模块级断言：

```python
os.environ["REDIS_ENABLED"] = "false"      # 用 InMemoryTokenStore，不连 Redis
os.environ["BCRYPT_ROUNDS"] = "4"          # 把 bcrypt 从 ~250ms 降到 ~2ms
os.environ["AI_RISK_ENABLED"] = "false"    # 关闭可选的 AI 风控
os.environ["SQL_ECHO"] = "false"           # 不把 bcrypt 哈希打进日志

assert settings.REDIS_ENABLED is False, "tests/conftest.py 的环境变量必须在 import app.* 之前生效"
assert settings.BCRYPT_ROUNDS == 4, "BCRYPT_ROUNDS 未生效"
```

> ⚠️ **顺序被破坏时在收集期直接报错**，而不是让测试跑出一堆莫名其妙的失败。
> 若有人把 `from app.core.config import settings` 挪到这些语句之前，
> `settings` 会在 import 时就完成实例化（读 `.env`，`BCRYPT_ROUNDS=12`），断言随即触发。
>
> `BCRYPT_ROUNDS=4` 是测试能跑完的关键：全量 349 个用例里有大量登录/校验路径，
> cost=12 时每个约 250ms，会从 4 分钟变成 20 分钟以上。

**SQLite 类型垫片**：`conftest.py` 在测试进程内把 `SQLiteTypeCompiler.visit_BIGINT` 换成输出 `INTEGER`。
原因是 SQLite 的 `BIGINT` 主键不会自动成为 `rowid` 别名（`INTEGER PRIMARY KEY` 才会），
导致自增主键拿不到值。这只影响测试进程，不影响生产代码。

### 2.3 HTTP 客户端

用 `httpx.ASGITransport` 直接驱动 ASGI 应用，**不起真实端口**：

```python
AsyncClient(transport=ASGITransport(app=application), base_url="http://test")
```

`httpx 0.27.2` 下 `AsyncClient(app=...)` 已不推荐，故用 transport 形式。

**依赖覆盖**：`app.dependency_overrides` 替换 `get_db` 与 `get_token_store`，
因此接口测试**不需要**云库与 Redis。注意这会绕过生产的 `get_db` 本体 ——
该本体的行为由 `tests/integration/test_db_session_contract.py` 单独覆盖（它改为 monkeypatch `AsyncSessionLocal`）。

### 2.4 假件清单

| 假件 | 位置 | 模拟什么 |
| --- | --- | --- |
| `FakeRedis` | `tests/fakes/fake_redis.py` | 异步 Redis：`get/set(ex=)/delete/exists/incr/incrbyfloat/sadd/srem/smembers/expire/ping/getdel/pipeline`。辅助方法 `fail_next(times)` 让接下来 N 次命令抛错、`recover()`、`keys()`、`ttl(key)` |
| `FakeRedisUnavailable` | 同上 | 连接失败（**必须继承 `RedisError`** 才能被 `app.core.redis.REDIS_ERRORS` 捕获） |
| `_FakePipeline` | 同上 | `transaction=True` 时持 `asyncio.Lock`，模拟 MULTI/EXEC 不交错 —— **轮换的原子性**靠它才测得到 |
| 工厂函数 | `tests/fakes/factories.py` | `create_role` / `create_user` / `create_user_with_raw_password` / `create_admin` / `create_multiple_users` |
| `_RollbackRecordingSession` | `test_db_session_contract.py` | 记录 `rollback()` 调用次数的 `AsyncSession` |
| `_ExplodingMetricStore` | `test_monitor_api.py` | 每个方法都抛异常的指标存储（验证埋点故障隔离） |
| `_BrokenSession` | `test_health_api.py` | 永远执行失败的会话（验证 `/ready` 的诊断能力） |

> `tests/fakes/__init__.py` 的 docstring 提到「假 LLM」，但**当前没有 `fake_llm.py`** ——
> 模块 9/10 不调用大模型，假 LLM 属模块 4/6/7/8 的测试基建。见 5.3。

### 2.5 关键夹具

| 夹具 | 作用 |
| --- | --- |
| `db_path` | 每个用例一个独立的 SQLite 文件路径（POSIX 形式） |
| `engine` | 应用侧异步引擎（`NullPool`），用 `Base.metadata.create_all` 建表 |
| `db_session` | 测试侧会话（`isolation_level="AUTOCOMMIT"`），**只用于造数据与查证据** |
| `token_store` | 每个用例一份新的 `InMemoryTokenStore` |
| `fake_redis` | 一份 `FakeRedis`（要验证 `RedisTokenStore` 本体的用例自行取用） |
| `metric_store` | `InMemoryMetricStore`，并装为全局单例 |
| `_reset_global_singletons` | **autouse**：用例前后清 token store / 指标单例，并 `redis_module.reset_client()` |
| `application` | 依赖已覆盖的 FastAPI 实例 |
| `client` | 指向应用的 `httpx.AsyncClient`（`ASGITransport`，不自动跟随重定向） |
| `login` / `auth_headers` | 登录助手，及把 `accessToken` 变成 `Authorization: Bearer` 头 |

> **`_reset_global_singletons` 是 autouse 的**：token store 与指标存储都是模块级单例，
> 不重置会让上一个用例的登录态泄漏到下一个用例，产生「单跑通过、全量失败」这类最难查的问题。

---

## 三、运行方式

```bash
# 激活环境（本项目环境名为 smart_dev）
conda activate smart_dev

# 全量测试 + 覆盖率（与 CI 一致）
pytest --cov=app --cov-report=term-missing

# 全量测试
pytest

# 按 marker 选择
pytest -m unit           # 178 items：纯逻辑
pytest -m api            # 144 items：接口
pytest -m db             #   5 items：事务边界契约
pytest -m migrations     #   8 items：Alembic 迁移

# 单个文件 / 单个用例
pytest tests/api/test_auth_api.py
pytest tests/api/test_auth_api.py::test_login_success_returns_token_pair
```

**不需要** `.env`、云库、Redis。缺 `.env` 时 `app.core.config` 走默认值（这也是 CI 不需要配置任何密钥的原因）。

> ⚠️ Windows 控制台注意：日志里有中文，`PYTHONIOENCODING=utf-8` 可避免 `UnicodeEncodeError: 'gbk' codec ...`。
>
> ⚠️ 重定向输出时看不到最终汇总行（`addopts = -q` 相关），用 `-o addopts="--strict-markers"` 覆盖。

---

## 四、用例清单

> 说明：每行为一个测试函数。括号内的数字是**参数化展开后的 items 数**（未标注即为 1）。
> 「断言」列是该用例验证的核心事实。

### 4.1 `tests/unit/` — 纯逻辑（96 函数 / 178 items）

#### `tests/unit/test_camel_and_datetime.py` — 18 函数 / 40 items（`unit`）

被测：`app/core/camel.py`（`CamelModel` / `DateTimeStr` / `MoneyStr`）与 `app/core/response.py` 的 `_format_validation_error`。
为什么是「跨模块的地基」：文档 6.2 要求接口 camelCase、5.1 要求时间 `YYYY-MM-DD HH:mm:ss`，
这两条不是某个接口的实现细节，而是全组共用约定（每个出参模型都继承 `CamelModel`）。

| 用例 | 断言 |
| --- | --- |
| `test_json_dump_uses_camel_case_at_every_level` | JSON 出参各层都是 camelCase，时间/金额格式正确 |
| `test_python_dump_keeps_snake_case_unless_by_alias` | `model_dump()` 默认给 snake_case —— 这正是必须传 `by_alias=True` 的原因 |
| `test_python_dump_keeps_datetime_and_decimal_types` | `when_used="json"` 的效果：Python 模式不把 datetime/Decimal 转字符串（否则写库会把字符串塞进 DATETIME 列） |
| `test_input_accepts_both_camel_case_and_snake_case` | `populate_by_name=True`：驼峰与下划线入参都能构造 |
| `test_unknown_fields_are_ignored_not_rejected` | `extra="ignore"`：前端多传字段不该让接口 400 |
| `test_model_can_be_built_from_orm_object` | `from_attributes=True`：可直接把 ORM 对象交给响应模型 |
| `test_to_camel_alias_for_real_field_names`（7） | 项目里真实字段名逐个转换（含 `accessToken`/`refreshToken`/`openStartTime`） |
| `test_datetime_accepts_common_input_formats`（5） | 契约格式 / ISO 8601 / 省略秒 / 只有日期 / 带首尾空格都能入参 |
| `test_datetime_serialization_drops_microseconds_and_uses_space_separator` | 出参固定 `YYYY-MM-DD HH:mm:ss`，无 `T`、无毫秒、无时区后缀 |
| `test_datetime_accepts_but_does_not_convert_timezone_aware_input` | ⚠️ **已知边界**：带时区输入被照抄不换算（东八区差 8 小时） |
| `test_datetime_rejects_unparsable_input` | 完全无法解析 → `ValidationError`（接口层转 400/40001） |
| `test_datetime_none_stays_none` | 可空时间输出 `null` 而不是空字符串 |
| `test_money_is_serialized_as_two_decimal_string`（6） | 金额出参固定 2 位小数的**字符串**（不用 JSON number，避免 `980.0999999999999`） |
| `test_money_keeps_decimal_type_in_python_mode` | Python 模式金额仍是 `Decimal` |
| `test_validation_error_field_name_is_always_camel_case`（8） | 报错的 `field` 一律 camelCase（含嵌套 `items.0.spaceId`、退化情形 `body`） |
| `test_validation_error_messages_are_localized_and_carry_constraints` | 常见错误类型给中文提示并带约束值（如「长度不足（要求 6）」） |
| `test_validation_error_falls_back_to_default_message` | 未收录的错误类型回退到 Pydantic 原文，不能丢信息、不能空 |
| `test_timezone_math_sanity_for_the_known_limitation` | 量级断言：本机时区比 UTC 快 8 小时（**依赖运行机器为东八区**） |

#### `tests/unit/test_permissions.py` — 16 函数 / 47 items（`unit`）

被测：`app/core/permissions.py` 的角色-权限映射、`normalize_permissions()` 容错、`effective_permissions()` 回落规则。

| 用例 | 断言 |
| --- | --- |
| `test_known_roles_are_exactly_the_mapped_roles` | `KNOWN_ROLES` 与 `ROLE_PERMISSIONS` 的键完全一致 |
| `test_role_hierarchy_is_cumulative` | `admin ⊇ resource_admin ⊇ user`，且**层层真有增量**（不是简单复制） |
| `test_permissions_for_role_deduplicates_and_keeps_order` | 权限清单去重且顺序稳定 |
| `test_permissions_for_unknown_or_empty_role_is_empty` | 未知角色 / `None` / 空串返回空元组，不抛异常 |
| `test_every_permission_code_matches_the_naming_convention` | 每个权限码符合「模块:动作」，且是 `Permission` 常量 |
| `test_normalize_permissions_handles_every_stored_shape`（21） | **21 种存储形态**都归一到正确权限集（数组/嵌套/JSON 文本/权限位映射/裸字符串/逗号/全角逗号/分号/空格…） |
| `test_normalize_permissions_ignores_booleans` | 裸 `True`/`False`/`None` 被忽略（没有权限语义） |
| `test_normalize_permissions_keeps_broken_json_text_as_is` | JSON 解析失败的文本按普通字符串处理，不丢数据 |
| `test_normalize_permissions_never_raises_on_odd_input` | 畸形输入只要求不抛异常 |
| `test_has_permission_matrix`（12） | 12 组 owned/required 组合判定正确（含通配符 `*`、空要求） |
| `test_has_permission_does_not_match_on_substring_or_case` | 不做前缀匹配、不忽略大小写（`order:view_all` 不等于 `order:view`） |
| `test_effective_permissions_prefers_database_value` | 数据库值优先，**不与静态清单合并**（改成少而真的权限会立即生效） |
| `test_effective_permissions_falls_back_when_database_is_empty` | 仅当库值为空（`NULL`/`[]`/`"[]"`）才回落静态映射 |
| `test_effective_permissions_unknown_role_and_empty_db_is_empty` | 未知角色 + 空库 → 空集（不是「全部权限」） |
| `test_effective_permissions_wildcard_stays_wildcard` | `["*"]` 原样返回，不展开成清单 |
| `test_effective_permissions_keeps_unrecognizable_values_out_of_the_way` | 误存角色 ID 数组（`[1,2]`）时非空 → 不回落，等价无权限但不抛错 |

#### `tests/unit/test_security.py` — 29 函数 / 43 items（`unit`）

被测：`app/core/security.py` 的 bcrypt 哈希/校验与 JWT 签发/解析。
passlib 被完全封闭在本文件对应的两个函数里（判据：换库时改动面 = 1 文件 2 函数）。

**口令哈希（9 个）**

| 用例 | 断言 |
| --- | --- |
| `test_hash_password_produces_bcrypt_hash_with_configured_cost` | 哈希是 bcrypt 且 cost 取自配置 |
| `test_hash_password_is_salted` | 同一口令两次哈希不同，但都能校验通过 |
| `test_verify_password_accepts_only_the_right_password` | 只接受正确口令，且**大小写敏感** |
| `test_verify_password_returns_false_for_broken_stored_hash`（5） | 坏哈希（明文/空串/异种算法/截断/非字符串）一律 `False`，不抛异常 |
| `test_hash_password_rejects_nul_byte` | 含 `\x00` 的口令抛 `ValueError`（bcrypt 的限制） |
| `test_password_longer_than_72_bytes_is_truncated_by_bcrypt` | ⚠️ **已知现状**：bcrypt 只取前 72 **字节** |
| `test_fake_verify_password_costs_the_same_as_a_real_check` | 防时序侧信道的占位哈希是合规 bcrypt，且与占位明文匹配 |
| `test_dummy_hash_is_created_lazily` | 占位哈希惰性生成（不在 import 时付 250ms 代价） |
| `test_password_max_length_constant_is_bcrypt_limit` | `PASSWORD_MAX_LENGTH == 72` |

**JWT 签发（7 个）**

| 用例 | 断言 |
| --- | --- |
| `test_token_type_enum_values_are_stable` | `TokenType` 成员值稳定且是 `StrEnum` |
| `test_create_token_payload_shape` | 载荷形状正确（`sub` 为字符串、`jti` 是 uuid4 hex、含 `ver`） |
| `test_create_token_defaults_version_to_zero` | 未强制下线的用户版本号默认 0 |
| `test_exp_is_utc_based_not_local_time` | `exp` 基于 **UTC** 而非本地时间 |
| `test_iat_and_exp_are_consistent` | `exp - iat` 等于声明的有效期 |
| `test_role_may_be_none` | `role` 可为 `None` 也能签发（未分配角色账号） |
| `test_decode_token_round_trip` | 解析结果与签发载荷一致 |

**JWT 解析与拒绝（13 个）**

| 用例 | 断言 |
| --- | --- |
| `test_decode_without_expected_type_accepts_both_kinds` | 不指定类型时两种令牌都接受（登出场景） |
| `test_type_mismatch_is_rejected`（2） | 类型不匹配抛 `TokenTypeInvalidError`（防止用 refreshToken 调业务接口） |
| `test_expired_token_raises_expired_error` | 过期抛 `TokenExpiredError` |
| `test_tampered_signature_is_rejected` | 改签名第一位即被拒 |
| `test_modified_payload_with_original_signature_is_rejected` | 改载荷沿用旧签名被拒 |
| `test_token_signed_with_other_secret_is_rejected` | 别的密钥签的令牌被拒 |
| `test_unsigned_token_is_rejected` | `alg:none` 令牌被拒（经典的算法混淆攻击） |
| `test_missing_required_claim_is_rejected`（5） | `exp`/`iat`/`sub`/`jti`/`type` 缺一不可 |
| `test_unknown_type_value_is_rejected` | 枚举外的 `type` 值抛 `TokenTypeInvalidError` |
| `test_non_numeric_subject_is_rejected` | `sub` 非数字的令牌无效 |
| `test_bad_version_falls_back_to_zero`（3） | `ver` 非法（字符串/负数/小数）一律按 0 处理，不报错 |
| `test_missing_version_falls_back_to_zero` | `ver` 缺失按 0 处理（兼容旧令牌） |
| `test_garbage_token_is_rejected`（4） | 4 种垃圾串（空串/无点/两点缺点/超长）抛 `TokenInvalidError` |

#### `tests/unit/test_token_store.py` — 22 函数 / 37 items（`unit`）

被测：`app/core/token_store.py` 的白名单、轮换、宽限期、强制下线与降级。
**同一组用例同时跑两套实现**（`InMemoryTokenStore` 与跑在 `FakeRedis` 上的 `RedisTokenStore`，
由 `store` 夹具的 `params=["memory","redis"]` 驱动，15 个用例各跑 2 遍）——保证二者语义不分叉。

| 用例 | 断言 |
| --- | --- |
| `test_whitelisted_jti_can_rotate` | 白名单内的 jti 可轮换，结果为 ok |
| `test_unknown_jti_is_rejected` | 从未签发的 jti 被拒 |
| `test_grace_allows_exactly_one_replay` | 宽限期**只放行一次**，不可无限重放 |
| `test_grace_expires` | 宽限标记过期后不再放行 |
| `test_rotated_token_is_still_usable` | 轮换出的新令牌不受宽限期约束 |
| `test_concurrent_rotation_only_one_wins` | **并发刷新 5 次只有 1 次成功**（轮换原子性） |
| `test_revoke_makes_token_immediately_invalid` | 吊销后令牌立即失效 |
| `test_revoke_clears_grace_marker` | 登出同时清掉宽限标记 |
| `test_revoke_all_bumps_version` | 强制下线版本号 +1，所有会话失效 |
| `test_revoke_all_only_affects_target_user` | 强制下线只影响目标用户 |
| `test_version_is_monotonic` | 版本号只增不减 |
| `test_login_failure_counter` | 登录失败计数递增正确 |
| `test_login_failure_counter_is_case_insensitive` | 用户名大小写与首尾空格归一到同一计数（防绕过） |
| `test_login_failure_counter_isolated_per_user` | 计数按用户隔离 |
| `test_clear_login_failure` | 清除失败计数归零 |
| `test_redis_failure_raises_unavailable_on_read` | Redis 读失败抛 `RedisUnavailableError` |
| `test_redis_failure_raises_unavailable_on_register` | 登记失败抛 `RedisUnavailableError` |
| `test_redis_failure_raises_unavailable_on_rotate` | 轮换失败抛 `RedisUnavailableError` |
| `test_redis_failure_raises_unavailable_on_revoke` | 吊销失败抛 `RedisUnavailableError` |
| `test_revoke_all_survives_cleanup_failure` | 清理阶段失败时，只要版本号递增即算成功 |
| `test_in_memory_store_never_raises` | 内存实现任何情况下都不抛 `RedisUnavailableError`（降级路径） |
| `test_build_token_store_respects_config` | 工厂按 `get_client()` 的结果选择实现 |

#### `tests/unit/test_metrics.py` — 11 函数 / 11 items（`unit`）

被测：`app/core/metrics.py` 的指标口径与双实现。

| 用例 | 断言 |
| --- | --- |
| `test_snapshot_rates_with_no_calls` | 无调用时成功率 1.0（面板显示 100% 比 0% 合理）、降级率 0 |
| `test_snapshot_computes_rates_and_average` | 快照正确算错误数、均值、两个率 |
| `test_in_memory_records_and_snapshots` | 内存实现记录三次后统计正确且 `source=memory` |
| `test_degraded_call_counts_as_success_when_http_ok` | 降级调用仍计入成功率（降级单列，不压低主指标） |
| `test_reset_clears_counters` | `reset` 清零计数与延迟和 |
| `test_redis_store_accumulates_in_redis` | Redis 实现累计正确且 `source=redis` |
| `test_redis_store_reads_are_shared_across_instances` | 两个实例共享同一份 Redis 指标（跨进程可见） |
| `test_redis_store_degrades_without_raising` | Redis 故障时写入不抛异常、读取回落内存且**不低估** |
| `test_redis_store_recovers_after_outage` | Redis 恢复后重新写回 Redis |
| `test_redis_store_reset_clears_both_layers` | `reset` 同时清 Redis 与内存两层 |
| `test_global_store_can_be_replaced` | 全局指标存储可被替换（测试隔离的前提） |

### 4.2 `tests/api/` — 接口（93 函数 / 144 items）

#### `tests/api/test_auth_api.py` — 37 函数 / 37 items（`api`）★ 模块 9 主用例

| 用例 | 断言 |
| --- | --- |
| `test_login_success_returns_token_pair` | 登录成功返回 200 与 `accessToken`/`refreshToken`/`role` |
| `test_login_payload_has_exactly_the_contract_fields` | 登录 `data` **恰好**只有契约约定的三个字段（防有人顺手加字段） |
| `test_access_token_from_login_can_call_info` | 登录签发的 accessToken 可立即通过 `/auth/info` 鉴权 |
| `test_username_is_trimmed_but_password_is_not` | `username` 会 strip 而 `password` 不会（密码里的空格是有效字符） |
| `test_login_with_wrong_password_returns_40107` | 密码错 → 401 + 40107 |
| `test_login_with_unknown_user_returns_the_same_error` | 用户不存在与密码错返回**完全相同**的响应（防用户名枚举） |
| `test_login_with_disabled_account_returns_40108` | 禁用账号 → 401 + 40108 |
| `test_login_without_role_returns_40302` | 未分配角色 → 403 + 40302 |
| `test_disabled_and_role_errors_are_hidden_behind_a_wrong_password` | 密码错时**不泄露**「该账号被禁用/无角色」 |
| `test_login_tolerates_broken_password_column` | 密码列存脏数据（明文/空串/异种哈希/截断）时返回 401 而非 500 |
| `test_login_accepts_short_password_without_validation_error` | 登录不做密码长度校验（历史账号必须能登录），短密码仍走 40107 |
| `test_login_missing_password_is_a_validation_error` | 缺 `password` → 400/40001 且列出字段名 |
| `test_login_with_empty_body_is_a_validation_error` | 空 body 报出 `username` 与 `password` 两个字段错误 |
| `test_info_without_token_returns_40101` | 无 `Authorization` 头 → 401 + 40101（**不是**框架默认的 403） |
| `test_info_with_malformed_authorization_header` | 无 `Bearer` 前缀按缺令牌处理 |
| `test_info_with_forged_signature_returns_40102` | 篡改签名 → 401 + 40102 |
| `test_info_with_garbage_token_returns_40102` | 非 JWT 垃圾串 → 401 + 40102 |
| `test_info_with_expired_access_token_returns_40103` | 过期 accessToken → 401 + 40103（**这是前端触发续期的信号**） |
| `test_refresh_token_cannot_be_used_as_access_token` | 用 refreshToken 调业务接口 → 40104 |
| `test_token_of_deleted_user_returns_40100` | 用户已被删除的有效令牌 → 40100 |
| `test_role_change_takes_effect_without_relogin` | 改角色后**不需重登**即时生效（授权只看数据库，不看令牌里的 `role`） |
| `test_refresh_rotates_tokens` | 续期成功且返回令牌对（**不含 `role`**），旧 refreshToken 已轮换 |
| `test_new_access_token_from_refresh_works` | 续期得到的新 accessToken 可访问 `/auth/info` |
| `test_old_refresh_token_replays_within_grace_period` | 宽限期内旧 refreshToken 可再换一次 |
| `test_old_refresh_token_is_rejected_after_grace_period` | 宽限期设为 0 后旧令牌立即失效 |
| `test_access_token_cannot_be_used_to_refresh` | accessToken 拿去续期 → 40104 |
| `test_refresh_with_expired_token_returns_40103` | 过期 refreshToken 续期 → 40103 |
| `test_refresh_with_unknown_token_returns_40106` | 签名合法但未登记白名单的令牌 → 40106 |
| `test_refresh_fails_strictly_when_redis_is_unavailable` | **Redis 不可用时续期严格失败**（503/50301），不降级 |
| `test_login_still_succeeds_when_redis_is_unavailable` | **Redis 不可用时登录仍成功**，但该 refreshToken 换不到新令牌 |
| `test_logout_revokes_only_the_given_session` | 带 refreshToken 登出只吊销该会话 |
| `test_logout_without_refresh_token_revokes_all_sessions` | 不带 body 登出吊销全部会话（后续续期 40105） |
| `test_logout_with_unparsable_refresh_token_still_revokes_all` | 坏 refreshToken 时退化为吊销全部（fail-safe） |
| `test_logout_cannot_revoke_another_users_session` | 用自己令牌吊销他人会话 → 403（防跨用户踢人） |
| `test_logout_requires_authentication` | 登出未带令牌 → 40101 |
| `test_logout_twice_is_idempotent` | 重复登出两次都返回 200 |
| `test_access_token_survives_logout_until_it_expires` | ⚠️ **已知限制**：登出后 accessToken 仍可用到过期 |

#### `tests/api/test_health_api.py` — 7 函数 / 7 items（`api`）

| 用例 | 断言 |
| --- | --- |
| `test_health_returns_envelope` | `/health` 返回统一信封且 `status=ok` |
| `test_health_does_not_touch_the_database` | `/health` **不碰数据库**（会话 `execute` 调用数为 0） |
| `test_ready_reports_healthy_state` | `/ready` 在库通、Redis 关闭时 `status=ok`、`redis=disabled` |
| `test_ready_is_degraded_when_redis_is_unreachable` | Redis 连不上时 `status=degraded` 但**仍返回 200** |
| `test_ready_reports_db_error_without_raising_500` | 库不可用时报 `db=error`/`degraded` 而非 500（诊断接口不能因故障变错误页） |
| `test_ready_rolls_back_after_a_failed_probe` | 探活失败后**回滚一次**会话（否则连接池会残留未结束的事务） |
| `test_ready_never_leaks_connection_details` | 探针响应不泄露连接串/端口/用户名/密码（文档 9.4） |

#### `tests/api/test_monitor_api.py` — 18 函数 / 26 items（`api`）★ 模块 10 主用例

| 用例 | 断言 |
| --- | --- |
| `test_monitor_agent_returns_three_contract_fields_when_idle` | 无流量时也返回三个契约字段（`0` / `100.0` / `0.0`） |
| `test_monitor_agent_detail_adds_breakdown_fields` | `?detail=true` 追加明细字段且 `source=memory` |
| `test_monitor_agent_rejects_invalid_detail_param` | `detail` 非布尔 → 400/40001 |
| `test_monitor_endpoint_does_not_count_itself` | `/monitor/agent` 自身不计入埋点 |
| `test_units_are_percent_and_seconds` | `successRate` 是**百分比**、`avgLatency` 是**秒**（文档 5.3 的口径） |
| `test_success_rate_rounds_to_one_decimal` | 成功率保留一位小数（`66.7`） |
| `test_agent_request_is_counted` | 走一次 `/agent/*` 请求统计为 1 |
| `test_unmapped_agent_path_is_still_counted` | 未注册的 `/agent/*`（404）也计入（统计的是流量，不是成功） |
| `test_paths_outside_agent_prefix_are_not_counted` | `/agentx` 等前缀边界**不**计入 |
| `test_failed_status_code_counts_as_error` | 500 记为失败（只看状态码） |
| `test_degraded_header_marks_call_but_keeps_it_successful` | 降级单列，且不压低 `successRate` |
| `test_truthy_degraded_values_are_recognised`（5） | `X-Agent-Degraded` 的 `"1"/"TRUE"/"true"/"Yes"/" y "` 都识别为降级 |
| `test_falsy_degraded_values_are_ignored`（5） | `"0"/"false"/"False"/"no"/""` 不算降级 |
| `test_broken_metric_store_does_not_break_business_endpoint` | **埋点抛异常时业务接口仍 200**（故障隔离） |
| `test_broken_metric_store_does_not_break_monitor_endpoint` | 指标读失败返回零值快照而非 500 |
| `test_metric_store_failure_is_logged` | 埋点失败留下 WARNING 日志（不静默） |
| `test_detail_false_drops_none_fields` | `detail=false` 时明细字段从 JSON 中**消失**（不是 `null`） |
| `test_ok_wrapper_keeps_camel_case` | 监控出参字段为 camelCase |

#### `tests/api/test_response_envelope.py` — 9 函数 / 9 items（`api`）

**这是全组共用的「收口」护栏**：它遍历所有已注册路由，保证没有任何接口漏掉统一响应体。

| 用例 | 断言 |
| --- | --- |
| `test_every_api_route_returns_the_envelope` | 遍历全部 `/api/` 路由，每个都返回恰好三键信封，且 HTTP 状态码与业务码同段 |
| `test_envelope_keys_are_camel_case` | 成功响应字段名为 camelCase |
| `test_no_unregistered_non_api_routes` | 非 `/api/` 路径**必须登记**进 `EXEMPT_PATHS`（登记即审查） |
| `test_validation_error_lists_the_offending_fields` | 参数校验错误列出 camelCase 字段名 |
| `test_unknown_route_returns_404_envelope` | 未注册路径返回统一信封的 404 |
| `test_method_not_allowed_is_documented_as_400xx` | ⚠️ **已知偏差**：405 复用业务码 `40000` 且透传 `Allow` 头 |
| `test_unhandled_exception_is_500_without_leaking_internals` | 未处理异常 500 不泄露 SQL / 表名 / 堆栈 |
| `test_response_model_violation_is_a_server_error` | 出参不符 `response_model`（服务端 bug）收敛为 500 |
| `test_lifespan_is_not_required_for_requests` | 不跑 `lifespan` 也能正常请求 |

#### `tests/api/test_mock_routes.py` — 11 函数 / 54 items（`api`）

| 用例 | 断言 |
| --- | --- |
| `test_mock_routes_are_registered_when_debug_is_on` | `DEBUG=true` 时注册的 Mock 路径与 `MOCK_CALLS` 表**完全一致**（防漏注册） |
| `test_mock_routes_are_absent_when_debug_is_off` | `DEBUG=false` 时 Mock 路由整体不注册 |
| `test_mock_paths_are_404_when_debug_is_off` | HTTP 层面确认 `DEBUG=false` 时 Mock 路径 404 |
| `test_mock_call_returns_envelope`（21） | **21 个 Mock 接口**逐个返回 200 + 统一信封 + 非空 `data` |
| `test_mock_response_keys_are_camel_case`（21） | 逐个递归检查响应键**没有下划线** |
| `test_mock_inspect_submit_requires_space_id` | FormData 缺 `spaceId` → 400/40001 |
| `test_agent_schedule_marks_degraded_on_demand` | `?degraded=true` 带上 `X-Agent-Degraded: 1`（供演示降级路径） |
| `test_agent_schedule_has_no_degraded_header_by_default` | 默认不带降级响应头 |
| `test_mock_traffic_is_not_counted_as_agent_traffic` | Mock 流量**不计入** Agent 埋点（否则演示时指标虚高） |
| `test_simulate_feeds_the_monitor_endpoint` | 灌 20 条后 `/monitor/agent` 的统计值**精确匹配** |
| `test_simulate_validates_its_parameters`（4） | 灌数据参数越界（`count=0`/`501`、`errorRatio=1.5`、`latencyMs=-1`）→ 400 并指出字段 |

#### `tests/api/test_cors.py` — 11 函数 / 11 items（`api`）

| 用例 | 断言 |
| --- | --- |
| `test_preflight_from_allowed_origin_succeeds` | 白名单来源预检 200，并回显来源/方法/请求头 |
| `test_preflight_result_is_cached` | 预检响应带 `max-age=600` |
| `test_preflight_from_unlisted_origin_is_rejected` | 非白名单来源预检 400 且无 `Allow-Origin` |
| `test_preflight_does_not_require_authentication` | 预检不要求鉴权 |
| `test_actual_request_carries_allow_origin` | 实际请求带 `Allow-Origin` |
| `test_unlisted_origin_gets_no_cors_headers` | 非白名单来源拿不到 CORS 头（来源**不能**是 `*`） |
| `test_error_response_still_carries_cors_headers` | 401 错误响应**仍带** CORS 头（CORS 在最外层的原因） |
| `test_credentials_mode_is_disabled` | 不返回 `Allow-Credentials`（本项目鉴权走 Authorization 头，不用 Cookie） |
| `test_request_id_is_exposed_to_js` | `X-Request-Id` 在 `Expose-Headers` 中（前端才拿得到） |
| `test_unhandled_exception_response_has_no_cors_headers` | ⚠️ **已知边界**：未处理异常 500 **无** CORS 头与 Request-Id |
| `test_500_generated_inside_the_app_still_has_cors_headers` | 对照组：应用内生成的 500 **仍带** CORS 头 |

### 4.3 `tests/integration/` — 跨层验证（21 函数 / 27 items）

#### `tests/integration/test_auth_flow_db.py` — 8 函数 / 14 items（`api`）★ 模块 9/10 交叉验证

> **为什么它在 `integration/` 目录却标 `api`**：`integration` marker 表示「需要真实外部依赖」，
> 而本文件用 SQLite + 假 Redis，**离线可跑**，因此标 `api`。
> 目录名表示「它验证的是跨接口的流程与跨层（HTTP + 数据库）的性质」，
> marker 表示「它需要什么依赖」—— 两者是不同维度。
> 它也不与 `test_auth_api.py` 重复：那里逐个覆盖**单个接口的分支**，这里验证**多步流程与时间窗**。

辅助：`_bearer()`、`_refresh()`、`_register_gated_probe()`（在测试应用上注册带 `require_permission` 的探针路由，
以便真实地验证「门禁」），路径 `ORDER_GATE` / `MONITOR_GATE`。

| 用例 | 断言 |
| --- | --- |
| `test_full_lifecycle_login_info_refresh_logout` | 登录 → 信息 → 续期（轮换）→ 新 accessToken 可用 → 登出 → 旧 refreshToken 被拒（40106）全链路。**刻意不断言上一代令牌失效**（见下一条） |
| `test_rotation_chain_keeps_only_the_newest_token_alive` | 连续续期三次（宽限期置 0），**只有最新**的 refreshToken 能换，全部旧令牌 40106 |
| `test_superseded_token_can_revive_the_session_within_the_grace_window` | ⚠️ **已知现状**：登录→A、续期→B、登出（B），随后**重放 A 仍返回 200**（会话被复活）；再重放 A 则 401。修法是令牌加 `sid` 声明，属跨模块契约变更 |
| `test_two_sessions_are_independent_until_a_full_logout` | 会话 A 登出不影响 B 续期；随后不带 body 登出会递增版本号 → B 收到 401/`TOKEN_REVOKED` |
| `test_permission_revoked_in_the_database_stops_at_the_gate_immediately` | 把 `sys_role.permissions` 改成 `['order:view']`（**非空**，避开静态映射回落）后，同一令牌在门禁处立即 403/`PERMISSION_DENIED`（message 里含权限码）；`/auth/info` 收敛；改回 → 200 |
| `test_role_downgrade_stops_at_the_gate_on_the_same_token` | 改 `sys_user.role_id` 降级后，同一令牌立即丢权限（403） |
| `test_hand_written_permission_shapes_reach_the_gate`（7） | **7 种手工写入的权限形态**（JSON 数组 / JSON 文本 / 权限位映射 / 全角逗号 / 英文逗号 / 分号 / 空格 / 裸字符串）都能被 `require_permission` 认到：`/auth/info` 等于预期集合，ORDER_GATE 200、MONITOR_GATE 403 |
| `test_forced_logout_rejects_refresh_but_the_access_token_lives_out_its_window` | `revoke_all` 后 refresh 立即 401/`TOKEN_REVOKED`，但 accessToken 在窗口内**仍可用**（文档化的取舍），重新登录会签发不同的令牌 |

#### `tests/integration/test_db_session_contract.py` — 5 函数 / 5 items（`db`）★ 事务边界护栏

> **为什么不能靠认证接口覆盖**：`app/services/auth_service.py` 整条链路**不写库**
> （登录只读、续期只读、登出只动 Redis），所以认证测试无论如何覆盖不到事务边界。
> **为什么不用 conftest 的 `client`**：接口测试把 `get_db` 换成了测试自己的会话工厂，
> 于是**生产的 `get_db` 本体一次都没被执行到** —— 生产代码里加了 `commit()` 也不会有任何用例失败。
> 本文件改为 monkeypatch `get_db` 依赖的 `AsyncSessionLocal`，让**本体真的跑起来**。
> **观察用的连接来自 `engine` 夹具（另一个引擎、另一条连接）**：用同一个会话去验证「提交了没有」是无效的
> —— 未提交的数据在自己会话里一定看得到，这正是「测试全绿、线上丢数据」的来源。

| 用例 | 断言 |
| --- | --- |
| `test_uncommitted_write_is_invisible_to_other_connections` | 三步递进：`flush()` 后 INSERT 已下发且主键已赋值，但**别的连接看不到**；请求结束后仍看不到；若有人给 `get_db` 加了 `commit()`，此用例会失败 |
| `test_explicit_commit_is_what_persists` | 只有显式 `await session.commit()` 之后，数据才对别的连接可见 |
| `test_exception_rolls_back_and_is_not_swallowed` | 业务异常路径**回滚恰好一次**，且异常被**原样抛出**（吞掉异常比不提交更危险：接口会返回 200） |
| `test_cancellation_discards_the_write_without_using_the_except_branch` | 取消路径（`CancelledError`）的数据**不落库**（安全），但**不走** `get_db` 的 `except` 分支（`rollback_calls == 0`）—— 兜底者是 `AsyncSession.close()`。把「安全」与「走了哪个分支」分开断言（详见 5.1） |
| `test_each_request_gets_its_own_session` | 每次调用产出**不同**会话，且各自的未提交数据互不可见（防「A 未提交的写入被 B 读到、B 顺手 commit 替 A 提交」） |

#### `tests/integration/test_migrations.py` — 8 函数 / 8 items（`migrations`）

> 用 **subprocess** 在独立进程里跑 `alembic upgrade head`，避免与 pytest 的事件循环冲突。
> 通过 `ALEMBIC_DATABASE_URL` 指向临时 SQLite 库（该开关**只接受 `sqlite` 开头**的连接串，
> 从结构上排除「误设变量把迁移打到线上库」）。

| 用例 | 断言 |
| --- | --- |
| `test_fixture_starts_without_doc66_indexes` | 夹具自检：10 条文档 6.6 索引确实都不存在（否则后续断言无意义） |
| `test_upgrade_creates_doc66_indexes` | `upgrade` 建出全部 10 个索引，且**列定义与列顺序**一致（复合索引的列顺序即定义顺序） |
| `test_upgrade_is_idempotent_when_indexes_already_exist` | 索引已存在时重复 `upgrade` **不报错**（这就是该迁移写成幂等版的理由） |
| `test_migrated_schema_matches_models` | 迁移后的库结构与 ORM 模型**逐列一致**（`autogenerate` 无噪音） |
| `test_downgrade_drops_only_own_indexes` | 回滚只删本迁移创建的索引，**不动表与唯一约束** |
| `test_offline_sql_lists_all_doc66_indexes` | 离线 `--sql` 输出 10 条 `CREATE INDEX` 与「未做存在性判断」的警示注释 |
| `test_offline_sql_is_utf8` | 离线 SQL 是合法 UTF-8（否则 Windows 下中文注释乱码，评审时看不懂） |
| `test_non_sqlite_override_is_rejected` | 非 `sqlite` 的 `ALEMBIC_DATABASE_URL` 被**硬拒绝**（安全护栏） |

---

## 五、`开发流程.md` 10.2 专项要求的覆盖情况

`开发流程.md` 10.2 提出了几条**指名要求**，逐条对照如下。

### 5.1 核心接口必须覆盖正常流程和异常流程 ✅

模块 9 的四个接口共 37 + 14 = 51 个用例，覆盖正常流程与全部异常分支：

| 接口 | 正常 | 异常分支 |
| --- | --- | --- |
| `login` | 成功、字段恰好三个 | 密码错、用户不存在、禁用、无角色、缺字段、空 body、密码列脏数据、Redis 不可用 |
| `info` | 成功、权限清单 | 无令牌、头畸形、签名伪造、垃圾串、过期、类型错用、用户被删、禁用、无角色 |
| `refresh` | 成功、轮换、宽限期 | 过期、未登记、类型错用、版本不符、Redis 不可用 |
| `logout` | 单会话、全会话、幂等 | 坏令牌退化、跨用户、未鉴权、Redis 不可用 |

### 5.2 「多模态识别必须测试失败降级」 — 归属模块 2/6

本模块**不实现**多模态识别，因此不在本仓库覆盖。上传侧的**降级/边界**已覆盖：

| 已覆盖 | 位置 |
| --- | --- |
| 上传超限 → `40002` | `app/utils/upload.py` 的 `UploadTooLargeError`（由使用方模块的测试触发） |
| 上传类型不支持 → `40003` | 同上 |
| 上传内容为空 → `40003` | `validate_upload_size()` 的 `size == 0` 分支 |
| `python-multipart 0.0.12` 无 `UploadFile.size` 的兼容 | `app/utils/upload.py` 的 `get_upload_size()`：先试 `.size`，取不到则流式计数并复位游标 |

> ⚠️ **待办**：`app/utils/upload.py` 目前**没有独立单元测试**（工具的调用方是模块 1/2/6，
> 本轮未实现其路由）。已列入 5.4 的未覆盖清单。

### 5.3 两类强制降级用例（`开发流程.md` 10.2 第 3 条）

| 类型 | 状态 | 说明 |
| --- | --- | --- |
| ① 大模型返回非 JSON → 降级为自然语言 | ⏳ **不在本仓库** | 模块 9/10 **不调用大模型**。契约已由模块 10 预置（`AiOutputInvalidError` → `50001` / HTTP 502），实现在模块 4/6/7/8，其测试由各自负责 |
| ② 外部 API 超时/失败 → 降级为友好提示 | ✅ **已覆盖（认证侧与上传侧）** | 认证侧：`test_refresh_fails_strictly_when_redis_is_unavailable`、`test_login_still_succeeds_when_redis_is_unavailable`、`test_in_memory_store_never_raises`、`test_redis_store_degrades_without_raising`、`test_broken_metric_store_does_not_break_business_endpoint`。外部 HTTP 调用的通用异常基类是 `ExternalApiUnavailableError`（`50303`） |

> **降级策略在认证链路上的取舍（决策 7）**：`login` 降级（照常发令牌）、`refresh`/`logout` 严格失败。
> 理由见本文档 4.2 与 `docs/api.md` 第 2.6 节 —— 读不到白名单时凭空签发新令牌等于让登出彻底失效。

### 5.4 「测试使用独立测试库 `smart_scheduler_test`」 — 当前不适用

`开发流程.md` 10.2 要求「测试使用独立测试库 `smart_scheduler_test`，或事务内回滚」。
本项目当前**全部测试离线运行**（SQLite 临时文件库），因此：

- 不需要 `smart_scheduler_test`，**也不会污染云库**；
- 需要真库才能验证的部分（`SELECT ... FOR UPDATE` 的并发行锁语义、真实 MySQL 方言、种子数据）**必须在云库上由人验证**，
  步骤见 `docs/deploy.md`；
- `smart_scheduler_test` 是否已建、账号有无建库权限**尚未核实**（已列入 `docs/汇报文档.md` 待确认项）。

### 5.5 「Agent 层测试使用假 LLM 夹具」 — 归属模块 4

模块 9/10 不涉及 Agent。`tests/fakes/__init__.py` 的 docstring 提到假 LLM 但**尚无 `fake_llm.py`**；
需要它的模块（4/6/7/8）应自行补齐，或由模块 10 统一收口 —— **属待确认分工项**。

### 5.6 未覆盖清单（如实记录）

| 未覆盖 | 原因 | 计划 |
| --- | --- | --- |
| `SELECT ... FOR UPDATE` 的并发行锁语义 | SQLite 无此语义；离线测试跑不到 | 云库实测（`docs/deploy.md`） |
| 真实 MySQL 方言（`JSON_ARRAY`、`ON DUPLICATE KEY UPDATE`、`CURDATE()+INTERVAL`） | 云库不可达 | 已在本地做方言翻译后验证（`docs/database.md` 8.6），真库执行留给人 |
| `app/utils/pagination.py`、`app/utils/time_utils.py` | 当前无调用方（模块 1～8 未实现） | 模块 1～8 接入时由其测试覆盖；模块 10 可补工具单测 |
| `app/utils/upload.py` | 同上 | 同上 |
| `app/services/risk_service.py`（可选 AI 风控） | `AI_RISK_ENABLED=false` 时**完全不执行**；默认关闭 | 开启该开关时补用例（需要它时） |
| `app/api/v1/mock_data.py` | 纯静态数据 | 已由 `test_mock_routes.py` 的 21×2 参数化间接覆盖 |
| `app/core/logging.py` 的 JSON 格式化细节 | 日志正确性难以断言，收益低 | 不计划 |
| 真实云库上的端到端联调 | 云库 / Redis / SSH 均不可达 | `docs/deploy.md` 的手工步骤 |

---

## 六、覆盖率

CI 以 `pytest --cov=app --cov-report=term-missing --cov-report=xml` 运行（`开发流程.md` 8.7），
覆盖率报告作为构建产物上传。

最近一次实测（本地 `pytest --cov=app --cov-report=term`，349 项全绿）：

```
TOTAL                                 2027    319    84%
349 passed in 147.94s (0:02:27)
```

**逐文件**（只列值得说明的；未列出的文件均为 100%）：

| 文件 | Stmts | Miss | Cover | 说明 |
| --- | --- | --- | --- | --- |
| `app/core/exceptions.py` | 122 | 0 | **100%** | 异常体系的 `code`/`http_status` 每个都被断言到 |
| `app/core/permissions.py` | 111 | 0 | **100%** | 权限归一化 21 种形态全覆盖 |
| `app/core/security.py` | 82 | 0 | **100%** | bcrypt 封装边界 + JWT 全部拒绝分支 |
| `app/core/error_codes.py` | 41 | 0 | **100%** | — |
| `app/core/camel.py` | 21 | 0 | **100%** | camelCase / 时间 / 金额转换 |
| `app/api/v1/mock.py` | 86 | 0 | **100%** | 21 个 Mock 路由逐个被调用 |
| `app/core/database.py` | 15 | 0 | **100%** | `get_db` 三个分支（commit 由服务层负责，故本体很薄） |
| `app/models/*.py` | 122 | 0 | **100%** | 建表即全部字段被 touch 到 |
| `app/core/token_store.py` | 275 | 13 | 95% | 两套实现同组用例；未覆盖的多是 Redis 命令的异常兜底 |
| `app/core/response.py` | 79 | 3 | 96% | 三个未覆盖分支是 `_STATUS_MESSAGES` 的兜底查找 |
| `app/middlewares/agent_metrics.py` | 50 | 2 | 96% | 埋点主体；故障隔离路径已覆盖 |
| `app/core/metrics.py` | 134 | 11 | 92% | 双实现 + 降级/恢复已覆盖 |
| `app/core/config.py` | 70 | 6 | 91% | 未覆盖的是非 dev 环境的**硬失败**分支（测试跑在 dev 下） |
| `app/api/v1/auth.py` | 35 | 4 | 89% | 路由很薄，逻辑在 service |
| `app/services/monitor_service.py` | 33 | 4 | 88% | — |
| `app/utils/time_utils.py` | 22 | 4 | 82% | — |
| `app/services/auth_service.py` | 128 | 30 | 77% | 未覆盖的是 Redis 异常时的**告警与降级日志分支**（测试注入的失败点较集中） |
| `app/api/deps.py` | 66 | 21 | 68% | 未覆盖的是 `require_role` 与部分 `get_current_user` 归档分支（当前无路由用 `require_role`，见下） |
| `app/core/redis.py` | 43 | 20 | 53% | 连接池建立与探活：离线测试里不通真实 Redis |
| `app/main.py` | 73 | 34 | 53% | `lifespan` 的关闭路径、CORS 白名单解析、OpenAPI 定制 |
| `app/services/risk_service.py` | 67 | 34 | 49% | `AI_RISK_ENABLED=false` 时**整段不执行**（默认关闭的可选件） |
| `app/core/logging.py` | 47 | 28 | 40% | JSON 格式化细节；难以断言且收益低 |
| `app/utils/pagination.py` | 39 | 39 | **0%** | 无调用方（模块 1～8 未实现） |
| `app/utils/upload.py` | 53 | 53 | **0%** | 同上 |
| `app/schemas/base.py` | 3 | 3 | 0% | 分页 schema 占位，无调用方 |

**怎么读这张表**：低覆盖率的文件分三类，都**不是**「测试没写好」：

1. **无调用方**（`pagination.py` / `upload.py` / `schemas/base.py`，合计 95 行 = 全项目 30% 的未覆盖行）：
   它们的调用方是模块 1/2/6，本轮未实现其路由。这三处**必然**是 0%，写测试也只能是自测自。
2. **默认关闭的可选件**（`risk_service.py`）：`AI_RISK_ENABLED=false` 时整段跳过，符合设计。
3. **离线环境跑不到的基础设施**（`redis.py` 的连接池、`main.py` 的关闭路径、`config.py` 的非 dev 硬失败）：
   它们要么需要真实 Redis，要么只在进程启停/换环境时执行。

**口径说明**：覆盖率是**辅助指标**，不作为验收门槛。本项目的验收门槛是
「349 个用例全绿」+「协议契约（响应体/字段命名/错误码）有断言」。
一个说明这个立场的例子：`test_response_envelope.py` 用 9 个用例遍历全部路由，
它对覆盖率数字的贡献很小，但它是**唯一**能拦住「新接口忘了包统一信封」的护栏 ——
按覆盖率排序会把它排在最后，按价值排序它在最前。

---

## 七、CI 集成

`.github/workflows/ci.yml`（`开发流程.md` 8.7）在推送 `main` / `develop` 及面向它们 PR 时执行：

```
检出代码 → 安装 Python 3.11.9 → pip install -r requirements.lock
        → pip install ruff==0.16.9 pre-commit==4.6.2
        → ruff check --output-format=github .
        → ruff format --check .
        → pre-commit run no-secrets-file --all-files
        → pytest --cov=app --cov-report=term-missing --cov-report=xml
        → 上传覆盖率报告（if: always()）
```

两点值得强调：

1. **CI 不需要配置任何密钥**（不需要 `.env`、云库、Redis）—— 这正是「测试全部离线」的直接收益；
2. **`pre-commit run no-secrets-file` 是 CI 里最有价值的一项**：`.env` 一旦进过仓库历史，密钥就必须更换（历史无法撤回）。

> ⚠️ **当前限制**：`.github/workflows/ci.yml` 位于 `backend/.github/` 下，
> 而 **GitHub Actions 只认仓库根目录的 `.github/workflows/**`**，因此**它现在不会执行**。
> 处理方式（二选一，见文件头注释）：
> a) 合入 monorepo 时移到根目录的 `.github/workflows/backend-ci.yml` 并加 `working-directory`；
> b) 若本仓库直接被当作后端仓库使用（自身即仓库根），**移一次目录即可生效**。
>
> 另外本仓库当前**零提交**，因此 CI 与 pre-commit 钩子都尚未真正跑过 —— 需要先完成首次提交与远端配置。

---

## 八、维护约定

| 变更 | 要求 |
| --- | --- |
| 新增接口 | 至少覆盖：正常流程 + 参数校验失败 + 未鉴权 + 权限不足（若需鉴权）；并在本文档对应章节登记用例 |
| 修改错误码 | 同步 `tests/api/test_response_envelope.py` 的段一致性断言与本文档 |
| 新增外部依赖（DB/Redis/大模型） | **必须**在 `tests/conftest.py` 提供替身，保证 CI 仍离线可跑 |
| 新增共享工具 / 跨模块约定 | 在 `tests/unit/` 加用例（如 `test_camel_and_datetime.py` 对 `CamelModel` 的护栏作用） |
| 发现新的已知限制 | **不要静默改行为**：先写成带说明的用例（用 `⚠️ 已知现状/已知边界` 措辞）钉住，再列入 `docs/汇报文档.md` 的待确认项 |

> **为什么要「先钉住再谈修」**：本项目的三条已知限制（时区不换算、宽限期可复活已登出的会话、500 无 CORS 头）
> 都是**跨模块契约或框架结构**决定的行为。静默「顺手修掉」会让前端按旧假设写好的代码在联调当天失效；
> 而用断言钉住 + 写进待确认项，能让「当前行为是什么」有据可查、改动时有测试报警。
