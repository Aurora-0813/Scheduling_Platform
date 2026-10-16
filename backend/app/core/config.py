"""
应用配置模块

从 `.env` 文件读取配置，统一管理。`.env` 严禁提交至仓库（项目文档 8.6 / 9.4），
仓库中只提供不含真实值的 `.env.example`。

连接串默认由 DB_* 各项拼接而成。**模块 3 额外提供一个 `DATABASE_URL` 显式覆盖口**，
仅供 §13.1 的本地 SQLite 自测 / 应急镜像使用（见该字段注释），生产必须留空。

`env_file` 用**绝对路径**指向 `backend/.env`：相对路径会跟着进程工作目录跑，
从仓库根启动就读不到它，与 `.env` 里的配置静默失联。
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（.env 所在位置）
BASE_DIR = Path(__file__).resolve().parent.parent.parent

#: 配置文件的**读取顺序**（后者覆盖前者）。分工理由见 `Settings.model_config` 的注释：
#:   `.env` 提交进仓库（共享的非敏感配置）、`.env.local` 不提交（各人自己的密钥）。
_ENV_FILES: tuple[str, ...] = (str(BASE_DIR / ".env"), str(BASE_DIR / ".env.local"))

logger = logging.getLogger(__name__)

# 非 dev 环境下 JWT 密钥的最小长度
MIN_JWT_SECRET_LENGTH = 32

# accessToken 有效期超过此值（分钟）时在启动日志中告警
ACCESS_TOKEN_WARN_MINUTES = 120


class Settings(BaseSettings):
    """
    应用配置类

    字段名对应 `.env` 里的变量名，大小写不敏感。
    """

    # ==================== 数据库配置 ====================
    # 云服务器统一 MySQL（项目文档 6.1）。开发机通过 SSH 隧道连接，
    # 因此 DB_HOST / DB_PORT 是隧道本端地址与映射端口，非云服务器真实地址。
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3308
    DB_NAME: str = "smart_scheduler_dev"
    DB_USER: str = "smart_dev"
    DB_PASSWORD: str = ""

    # 建立 MySQL 连接的超时（秒）。
    # 不设它时，隧道没起 / 云库不可达会让每个连接尝试都等到操作系统 TCP
    # 超时（Windows 上可长达 20 秒以上），表现为：进程启动卡住、
    # `GET /ready` 长时间无响应、Alembic 迁移前先干等半分多钟。
    # 取 5 秒：局域网与隧道场景足够，故障时能快速失败。
    DB_CONNECT_TIMEOUT: int = 5

    # ==================== 应用配置 ====================
    APP_NAME: str = "SmartScheduler"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    # SQL 回显。与 DEBUG 刻意解耦：开启后 SQLAlchemy 会把 SQL 参数打进日志，
    # 其中含 sys_user.password 的 bcrypt 哈希，因此默认关闭。
    SQL_ECHO: bool = False

    # ==================== JWT 配置 ====================
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    # accessToken 有效期（分钟）
    JWT_EXPIRE_MINUTES: int = 30
    # refreshToken 有效期（天）
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    # refreshToken 轮换宽限期（秒）。前端并发刷新时旧 token 在此窗口内
    # 仍可换取一次新 token（消费即失效，不可重放）。
    JWT_REFRESH_GRACE_SECONDS: int = 60

    # ==================== Redis 配置 ====================
    # refreshToken 白名单、登录失败计数、Agent 埋点指标的存储。
    # 置为 False 时退化为进程内内存实现（功能完整，但服务重启后需重新登录）。
    REDIS_ENABLED: bool = True
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6380
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    # 短超时：埋点与白名单读写都不能拖慢业务接口
    REDIS_SOCKET_TIMEOUT: float = 0.5

    # ==================== CORS 配置 ====================
    # 项目文档 5.4：需允许 Web 前端 localhost 及小程序域名。多个来源用英文逗号分隔。
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ==================== 文件上传配置 ====================
    MAX_UPLOAD_SIZE_MB: int = 10
    UPLOAD_DIR: str = "uploads"

    # ==================== 设备剩余量推导（模块 5/3 交界）====================
    # 「资源与设备」页要显示**实时剩余**，而 `device_resource.available_count`
    # 是**静态上限**、按口径**只读不写**（见 docs/available_count口径判据.md）。
    # 所以剩余量必须**用时推导**：
    #     remaining = available_count − 该窗口内「同时占用该设备」的最大活跃单数
    #
    # 本项就是这个"窗口"的长度（天）。为什么需要它：
    # 「还剩几台」是 (设备, 时段) 的函数，没有窗口就算不出一个**单值**给列表显示。
    # 取窗口内**最大占用**（最坏情况）而不是"现在这一刻"，是为了让这个数在
    # 用户选时段之前也偏保守、不会给出"看着有、下单却没有"的假象。
    #
    # 取 30 天：预约平台的实际提前期通常以周计，7 天会漏掉下下周的占用，
    # 用户会看到「明明订了却没减」。窗口越长越保守，代价只是一次范围查询。
    DEVICE_REMAINING_HORIZON_DAYS: int = 30

    # ==================== 密码哈希配置 ====================
    # bcrypt cost。12 约需 200-300ms/次；测试环境可降到 4 加速。
    BCRYPT_ROUNDS: int = 12

    # ==================== AI 增强（可选） ====================
    # 项目文档 4.4 模块 9：登录异常检测为可选增强，不影响主流程。
    # 默认关闭时，登录流程完全不读写风控键，行为与没有该模块时一致。
    AI_RISK_ENABLED: bool = False

    # 连续登录失败多少次后临时锁定（仅在 AI_RISK_ENABLED=true 时生效）。
    # 取 5 是常见取值：正常用户打错几次不会被锁，在线爆破则很快被拦住。
    LOGIN_MAX_FAILURES: int = 5
    # 失败计数的滑动窗口（秒）。停止尝试 15 分钟后计数自动清零。
    LOGIN_FAIL_WINDOW_SECONDS: int = 900

    # ==================== 模块 1 / 模块 2 引入的配置 ====================
    # 来源：模块 1（语音输入，百度 ASR + DeepSeek 口语格式化）与
    #       模块 2（摄像头空间感知，视觉多模态模型）。
    # 这些字段原先定义在两位负责人自建的临时 app/core/config.py 中，
    # 合并时整体迁入本文件，默认值保持与模块开发期一致。

    # ---------- 认证开关（仅联调用）----------
    # true 时 get_current_user 直接放行，不校验 Token。
    # ⚠️ 仅限模块自测与联调，**演示与部署前必须保持 false**。
    AUTH_BYPASS: bool = False

    # ---------- 视觉多模态模型（模块 2）----------
    VISION_MODEL_NAME: str = ""  # 模型名，如 qwen-vl-max
    VISION_API_KEY: str = ""  # 密钥，真实值放 .env
    VISION_API_BASE: str = ""  # OpenAI 兼容端点地址
    VISION_STRUCTURED_OUTPUT: bool = True  # 是否启用 with_structured_output（见 app/core/llm.py）
    #: 是否关闭视觉模型的「思考模式」（2026-10-14 加）。
    #:
    #: 背景：qwen3.8 / qwen3.7 / qwen3.6 / qwen3.5 系列属**混合思考模型，
    #: **默认开启思考**（见官方《深度思考》文档的「支持的模型」清单）。
    #: 思考模式会先生成大量推理 token 再给答案，实测同一张图 + 同一段提示词：
    #:   开启思考 ≈ 40 秒；而思考 token 量可达正常回答的 **10 倍以上**
    #:   （实测一个 233 字符的回复耗掉 1624 output tokens）。
    #:
    #: ⚠️ 三态语义，默认值刻意保证**行为不变**：
    #:   - None（默认）→ **不发送** enable_thinking，模型用自己的默认值
    #:                    → 与本次改动前的行为完全一致，零风险
    #:   - True        → 显式发送 enable_thinking=true（先思考再回复）
    #:   - False       → 显式发送 enable_thinking=false（直接回复，显著更快）
    #:
    #: 之所以不用 bool 默认 False，是因为那会**改变所有既有部署的行为**；
    #: 用 None 表示「不干预」，只有明确配置才生效。
    #:
    #: ⚠️ 若该模型不支持此参数会返回 400。视觉链路的兜底是
    #:    「降级为自然语言引导」（见 image_service），但功能会退化，
    #:    所以开这个开关前先用 scripts 里的探针确认一次。
    VISION_ENABLE_THINKING: bool | None = None
    # 单次模型调用超时（秒）。视觉任务比纯文本慢，给足。
    # 单次模型调用超时（秒）。视觉任务比纯文本慢，给足。
    # ⚠️ 类型 int → float 是模块 7 合并时的统一：模块 7 的超时降级用例要传
    #    0.05 这类亚秒值，收成 int 会被截断为 0，ChatOpenAI(timeout=0) 行为未定义。
    # 默认值取主干原值 60，不取模块 7 的 20.0 —— 本键被三条链路共用
    #    （视觉 app/core/llm.py、口语清洗 services/format_service.py、模块 7 文本链），
    #    下调会把前两条一起砍短。模块 7 原名 LLM_TIMEOUT_SECONDS，已废弃。
    LLM_TIMEOUT: float = 60.0
    # SDK 层自动重试次数；仍失败则抛异常，由 service 层降级为友好提示。
    LLM_MAX_RETRIES: int = 1

    # ---------- 空间感知策略参数（模块 2）----------
    # 置信度阈值，低于则触发向用户追问而不是直接出方案。
    IMAGE_CONFIDENCE_THRESHOLD: float = 0.75
    # 注入 Prompt 的候选场地上限，防止 Prompt 超长。
    IMAGE_SPACE_CANDIDATE_LIMIT: int = 100
    # 上传图片大小上限（MB）。
    # 与上面的 MAX_UPLOAD_SIZE_MB 分工见 `image_max_size_bytes` 属性：
    # 本项覆盖**所有**图片链路（image_storage 落盘校验 + utils.upload 的
    # validate_image_upload），MAX_UPLOAD_SIZE_MB 覆盖音频与模块 9/10 通用链路。
    # 两者默认不同（5 vs 10）是**按媒体类型**的差异，不是并行冲突：
    # 图片要送视觉模型，限制更紧以控制成本与延迟；录音时长天然更长。
    # 已确认图片链路内部两处校验取值一致（原先 validate_image_upload 误用
    # 通用上限，会让同一张图得到两种判定，已修正）。
    IMAGE_MAX_SIZE_MB: int = 5
    # 图片落盘根目录（相对 backend/）。与 UPLOAD_DIR 默认值恰好相同，
    # 但语义上属于图片链路专有，故保留独立配置项。
    IMAGE_UPLOAD_DIR: str = "uploads"
    # 对外可访问的 URL 前缀（main.py 以它挂载 StaticFiles）。
    IMAGE_STORAGE_BASE_URL: str = "/uploads"
    # 是否计算场地未来空档时段（依赖预约数据，关闭可省一次查询）。
    IMAGE_ENABLE_AVAILABLE_SLOTS: bool = True

    # ---------- 语音识别 ASR（模块 1，阿里云百炼 Qwen3-ASR-Flash）----------
    #
    # ⚠️ **2026-09-30 从「百度短语音识别标准版」切换到 Qwen3-ASR-Flash。**
    #
    # 切换理由：
    #   1. **不用新增任何凭据** —— 复用已有的百炼账号（`LLM_API_KEY`），
    #      而百度那套需要另行注册 AppID / API Key / Secret Key 三件套。
    #   2. **少一个供应商**：切换前要同时维护 DashScope + 百度 + DeepSeek 三家，
    #      切换后只剩 DashScope。
    #   3. **没有 OAuth 环节**：百度要先换 access_token（含 30 天缓存与过期处理），
    #      Qwen 直接用 API Key。
    #   4. 实测往返质量好：TTS 合成「明天下午三点在A栋3楼展厅开个二十人的评审会」
    #      再识别回来得到「明天下午三点在A栋三楼展厅开个二十人的评审会。」。
    #
    # 端点说明：走的是百炼**原生**端点，**不是** OpenAI 兼容模式 ——
    # 实测 `/audio/transcriptions` 挂在兼容模式 base 上是 404（该路径不存在）。
    # 所以这里必须单独配一个完整 URL，不能拿 `LLM_BASE_URL` 拼。
    #
    # 后期要换模型（比如出更快的 ASR），**只改 `ASR_MODEL_NAME` 即可**；
    # 换供应商才需要动 `ASR_API_BASE` 与 asr_service 的请求体构造。
    ASR_MODEL_NAME: str = "qwen3-asr-flash"
    # 留空则回退到 `LLM_API_KEY`（同一个百炼账号，通常不必单独填）。
    ASR_API_KEY: str = ""
    ASR_API_BASE: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    # 采样率，需与小程序录音参数对齐（Qwen 侧音频头自带，这里保留供校验与说明）。
    ASR_RATE: int = 16000
    # 识别音频最长秒数。
    ASR_MAX_DURATION_S: int = 60

    # ---------- 已废弃：百度短语音（保留字段，避免旧 .env / 历史代码直接报错）----------
    # 2026-09-30 起 ASR 走 Qwen3-ASR-Flash，以下四项**不再被任何代码读取**。
    # 留着是为了「有旧 .env 的人不会因为字段消失而启动失败」，时机成熟后再删。
    BAIDU_APP_ID: str = ""
    BAIDU_API_KEY: str = ""
    BAIDU_SECRET_KEY: str = ""
    # 百度 dev_pid（1537 普通话 / 1737 纯中文）—— 仅百度链路使用，已无消费者。
    ASR_MODEL_PID: int = 1537

    # ---------- 已废弃：口语格式化曾用的 DeepSeek ----------
    # 2026-09-30 起 `services/format_service.py` 复用 `LLM_*`（百炼），
    # 以下三项不再被读取。保留理由同上。
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-flash"

    # ---------- 大模型配置（Agent 组与模块 8 共用同一套，2026-09-27 定案） ----------
    # 命名：`LLM_` 前缀 + 全大写，与本文件既有 DB_ / JWT_ / APP_ 风格一致。
    #
    # ⚠️ **不要改用 `OPENAI_API_KEY` 这个名字。** `ChatOpenAI` 会**隐式**从环境变量
    #    拾取 `OPENAI_API_KEY`；沿用该名的话，本机任何同名环境变量都会把请求静默
    #    路由到别人的额度上，且排查时很难看出。调用处应**显式传参**堵死这条路径：
    #        ChatOpenAI(model=settings.LLM_MODEL_NAME,
    #                   api_key=settings.LLM_API_KEY,
    #                   base_url=settings.LLM_BASE_URL)
    #
    # 三个字段**故意给空串默认值，不设必填**。原因很具体：若设为必填，`Settings()`
    # 会在 import 期就抛异常，**没配 key 的机器上所有测试连 import 都过不去**，
    # 包括根本不用 LLM 的模块。校验点放在**真实调用入口**——用下面的
    # `llm_configured` 判断，缺了立刻报「LLM_API_KEY 未配置」，而不是走到 HTTP 401。
    LLM_MODEL_NAME: str = ""  # 模型名，如 qwen-plus
    LLM_API_KEY: str = ""  # 各人各把，真实值只放 .env，不进仓库
    LLM_BASE_URL: str = ""  # OpenAI 兼容端点，不写死服务商
    # 调度决策要可复现，取 0；调高会让同一需求两次给出不同方案
    LLM_TEMPERATURE: float = 0.0
    # SDK 内部重试次数。外层已有 AGENT_TIMEOUT 兜底，重试不宜多
    LLM_MAX_RETRIES: int = 1

    # ---------- Agent 运行参数（模块 4 专用，阶段 5/6） ----------
    # `AGENT_TIMEOUT` 同时用于两处：传给 ChatOpenAI 的单次请求超时，以及
    # `run_schedule` 里 `asyncio.wait_for` 的整体超时。**整体超时必须不小于单次请求超时**，
    # 否则模型还在正常生成，外层先把协程掐了，表现为「无端超时」。
    # 默认 60 秒（2026-09-28 由 30 上调，项目群裁定）：主线一屏 3 要展示约 40 秒的思考过程，
    # 那 40 秒是**前端按 trace 回放**出来的（阶段 5 §3.5 推荐方案），不是服务端真跑 40 秒——
    # 但**真冒烟实测**场景 A 耗时 29.845 秒，30 秒下的余量只剩 155 ms；超时走的是降级路径
    # （返回 200 + 友好提示并保留已收集的 trace），**接口层看不出异常**，现场只会发现
    # 「方案没出来」。取 60 后与 `LLM_TIMEOUT`（模块 1/2 的单次调用超时）同值。
    # ⚠️ 本值同时喂单次与整体两处，且 `LLM_MAX_RETRIES=1`：一次慢请求就能吃满整个预算。
    # 若要更稳，需把这一个键拆成「整体 90 / 单次 60」两个键（详见 done/README.md 硬卡点 #11）。
    AGENT_TIMEOUT: float = 60.0
    #: 「深度模式」（多轮 Agent，思考链完整但 40~80 秒）的**默认**开关。
    #: 只是初值 —— 运行时会被 core/flags.py 的持久化开关覆盖，
    #: 答辩时不必改这里、更不必重启后端，见 PUT /api/v1/agent/mode。
    AGENT_DEEP_MODE_ENABLED: bool = False
    #: 「AI 推荐」（/agent/parse 的推荐 + 理由 + 备选由谁给）的**默认**开关。
    #: True  → 大模型给（展示效果好，但整次解析约 32 秒）
    #: False → 规则算（约 10~15 秒，理由由真实场地数据拼出）
    #: 与 AGENT_DEEP_MODE_ENABLED 同理：只是初值，运行时被 flags.py 的持久化
    #: 开关覆盖（PUT /api/v1/agent/mode），演示前切换不必重启后端。
    #:
    #: ⚠️ 2026-10-13 补：这个字段原先**只在 flags.py 里用 getattr 兜底读**，
    #: Settings 中根本没有它 —— 于是 .env 里写 AGENT_AI_RECOMMEND 不生效、
    #: 也不报错（Settings 是 extra="forbid"，照理该拒绝未知键，但 getattr 的
    #: 兜底让它静默取默认值 True）。现在它是个真字段，.env 保底开关才立得住。
    AGENT_AI_RECOMMEND: bool = True
    #: 是否关闭**Agent / 文本链路**的「思考模式」（2026-10-14 加）。
    #:
    #: 与 VISION_ENABLE_THINKING 同源同语义，只是管另一条链路。
    #: 这里收益更大：Agent 一次调度要跑 6~7 轮「模型↔工具」往返
    #: （见 .env 里 AGENT_TIMEOUT 的注释实测 60~90 秒），**每一轮都带思考开销**。
    #:
    #: ⚠️ 三态，默认 None = 不发送该参数 = 行为不变（理由同 VISION_ENABLE_THINKING）。
    #:
    #: ⚠️ 关掉思考会削弱多步推理能力，而 Agent 正是靠推理做工具选择与
    #:    「预算不足就降级设备」这类权衡（见 prompts/scheduler.py）。
    #:    若开启后方案质量下降，表现形式是 **200 + degraded**（不会报错），
    #:    所以评估时必须看 degraded 标志，不能只看 HTTP 状态码。
    LLM_ENABLE_THINKING: bool | None = None
    # LangGraph 递归上限。一次正常调度约 4~8 个节点（模型↔工具往返），
    # 25 足够覆盖「多轮查询 + 重试 + 生成通知」的长链路；再高只会让跑飞的 Agent 拖满超时。
    AGENT_RECURSION_LIMIT: int = 25

    # ==================== 模块 3 引入的配置 ====================
    # 来源：模块 3（移动端预约与通知）。（同批的 `sync_engine` /
    # `sync_database_url` **没有**保留 —— 本仓库已把 Alembic 改为全异步迁移、
    # requirements 也不再包含 PyMySQL，同步引擎已无任何消费者，留着只是死代码。）

    # 显式连接串覆盖口，**留空则按上方 DB_* 五项拼接**（正常情况一律留空）。
    # 唯一用途：§13.1 的本地 SQLite 应急/自测镜像，以及测试期把引擎指向
    # 临时 SQLite —— `tests/conftest.py` 在导入任何 `app.*` 之前设置同名环境变量。
    # ⚠️ 生产 / 演示环境必须为空字符串，否则会绕开 DB_* 直连。
    DATABASE_URL: str = ""

    # 调度 Agent 服务地址；为空时 `services/agent_client.py` 走内置 mock 调度器。
    AGENT_URL: str = ""

    # ==================== 模块 7 引入的配置（AI 冲突预警与智能通知）====================
    # AI 总开关：False 时所有 AI 能力降级为模板/纯统计，业务链路不中断
    AI_ENABLED: bool = True
    # True 时切换为假 LLM 夹具：答辩现场 API 欠费时的应急预案，同时供离线测试使用
    AI_USE_FAKE_LLM: bool = False

    # ---------- 订单自动结单（2026-10-10）----------
    # 「时段已过 → 自动结单」，规则与理由见 `services/order_lifecycle.py`：
    #   已确认(2) + end_time 已过 → 已完成(4)
    #   待确认(1) + end_time 已过 → 已过期(5)
    #
    # 为什么与冲突扫描**分成两个开关**：两者的**演示诉求相反**。
    #   冲突扫描常因"不想现场刷消息"被关掉（见 CONFLICT_SCAN_ENABLED）；
    #   而订单状态随时间推进是**基本正确性**，关掉会让列表显示与实际不符。
    #   合成一个开关会逼着用户在两者间二选一。
    ORDER_AUTO_CLOSE_ENABLED: bool = True
    # 扫描间隔。取 300 秒与冲突扫描同一个节拍 —— 不为这一个任务另立第二套节拍。
    # 代价是「时段刚过」到「状态变已完成」之间最多有 5 分钟延迟；
    # 对「释放名额」这个目的足够了（名额释放本身是**用时推导**的，
    # 见 `docs/available_count口径判据.md`，不依赖这次落库）。
    ORDER_AUTO_CLOSE_INTERVAL_SECONDS: int = 300

    # ---------- 软冲突扫描 ----------
    CONFLICT_SCAN_ENABLED: bool = True
    CONFLICT_SCAN_INTERVAL_SECONDS: int = 300
    CONFLICT_SCAN_INITIAL_DELAY_SECONDS: int = 20
    CONFLICT_PAST_WINDOW_DAYS: int = 7
    CONFLICT_FUTURE_WINDOW_DAYS: int = 7
    CONFLICT_MAX_ORDERS_IN_SNAPSHOT: int = 2000  # 保护 2 核 2G 服务器内存

    # ---------- 软冲突阈值 ----------
    # ① 同用户连续活动无休息：相邻两场间隔小于该分钟数即命中
    CONFLICT_CONTINUOUS_GAP_MINUTES: int = 15
    # ② 容量远超需求：capacity >= 人数 * 倍数 且 差值 >= 绝对下限（双条件防误报）
    CONFLICT_CAPACITY_RATIO: float = 3.0
    CONFLICT_CAPACITY_MIN_ABS_GAP: int = 10
    CONFLICT_CAPACITY_MIN_CAPACITY: int = 10
    # ③ 高价值设备白名单，被普通使用者预约时提醒（逗号分隔）
    CONFLICT_HIGH_VALUE_DEVICE_TYPES: str = "无人机,直播设备,显示屏"
    CONFLICT_NORMAL_ROLE_NAMES: str = "普通使用者,普通用户"
    # ④ 资源过度占用：同一场地单日累计占用超该小时数
    CONFLICT_DAILY_OCCUPY_HOURS: float = 8.0
    CONFLICT_DAILY_OCCUPY_MIN_ORDERS: int = 2
    # ⑤ 长期闲置：该天数内无任何有效预约
    CONFLICT_IDLE_DAYS: int = 14

    # ---------- 通知去重 ----------
    # auto=优先 Redis，不可用时自动降级为数据库查询
    CONFLICT_DEDUP_BACKEND: str = "auto"

    # 同一冲突多久之内只提醒一次（秒）。
    #
    # ⚠️ 2026-10-10 由 24 小时（86400）上调为 **7 天**。
    #    起因是真实反馈「软冲突有那么多一样的」。
    #
    #    先说清这个值**不是**那个问题的根因：一场地一条 × 两角色
    #    （资源管理员 `待关注` + 系统管理员 `汇总`）是**设计如此**，
    #    由本项改成 7 天并不会减少那 16 条。本项真正影响的是**重复频率**：
    #    `space_idle` 这类「长期闲置」是**持续状态**（不该用着才消失），
    #    24 小时的窗口意味着同样的闲置场地**每天都重新推一遍**，
    #    日积月累就是「一屏长得一样的通知」。7 天把频率降到每周一次。
    #
    # 取值权衡：
    #   · 太短（原 24h）→ 持续状态被反复推送，通知列表失去信息量；
    #   · 太长（如 30 天）→ 冲突**先消失、后又复发**时，第二次不再提醒，
    #     把「刷屏」换成「漏报」——`dedup.py` 的 docstring 专门警告过这个反向风险。
    #   7 天与 `CONFLICT_IDLE_DAYS=14`（闲置判定窗口）同量级，是该状态
    #   自然变化的尺度：一周内没变化就不值得再打扰一次。
    #
    # 注意：本项同时被 `MemoryDedup` / `RedisDedup` / `DbDedup` **三个后端**
    # 读取（`dedup.py` 的三处 `else` 分支），改一处即三处同时生效。
    CONFLICT_DEDUP_TTL_SECONDS: int = 604800

    # 指定 .env 文件位置和编码
    #
    # ⚠️ 2026-10-10：由**单文件**改为「模板 + 本地覆盖」两级
    # ------------------------------------------------------
    # `.env` 从「本机私有、被 gitignore」改为**提交进仓库**（team 口径统一），
    # 于是它里面的密钥一律写成占位符。但占位符不能直接跑（见
    # `_reject_unfilled_placeholders`），而每个人的真实密钥又**不能进仓库**。
    #
    # 所以分成两级，后者覆盖前者：
    #     ① `.env`        —— **提交**。仓库内共享的非敏感配置（库地址、模型名、
    #                        阈值、开关）。密钥位留 `<...>` 占位符。
    #     ② `.env.local`  —— **不提交**（被 `.gitignore` 的 `.env.*` 规则忽略）。
    #                        只放自己那几项真实密钥，通常是 4 行。
    #
    # 为什么用「文件列表」而不是让各人改 `.env`：后者会让 `.env` 一直处于
    # 「已修改」状态，git 每次都要你处理它；而且一旦手滑提交，密钥就进仓库了。
    # 分开之后，`.env` 可以安心被跟踪、`.env.local` 安心被忽略。
    #
    # `.env.local` **不存在时 pydantic-settings 会跳过**（不报错），
    # 所以「拉下来还没配」的场景不会因为缺文件而崩 —— 只会在校验阶段明确
    # 告诉你哪几项还是占位符。
    model_config = SettingsConfigDict(
        # 绝对路径：相对路径会跟着进程工作目录跑（详见模块 docstring）
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        # .env 中存在未定义的键时忽略，避免队友本地多写的变量导致启动失败
        extra="ignore",
    )

    # ==================== 派生属性 ====================

    @property
    def database_url(self) -> str:
        """
        异步数据库连接串。

        项目文档 3.4：连接串固定为 `mysql+asyncmy://`，
        禁止使用同步驱动 PyMySQL / mysqlclient。

        例外：`DATABASE_URL` 非空时**直接返回它**（§13.1 的 SQLite 应急镜像与
        测试期覆盖）。这是唯一会绕开 `mysql+asyncmy://` 的路径，故只允许
        在 `APP_ENV=dev` 下使用 —— 见 `_check_security_settings`。
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"mysql+asyncmy://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    @property
    def masked_database_url(self) -> str:
        """隐藏密码的连接串，供日志与探针接口安全展示。"""
        return f"mysql+asyncmy://{self.DB_USER}:***@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def redis_url(self) -> str:
        """Redis 连接串。无密码时不拼接认证段。"""
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS_ORIGINS 解析为列表。"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        """通用上传大小上限（字节），服务于音频与模块 9/10 的通用校验。"""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def image_max_size_bytes(self) -> int:
        """
        图片上传大小上限（字节）。

        图片链路上有**两处**校验必须用同一个值，否则同一张图会得到两种判定：
            1. `app/services/image_storage.py` 落盘前的校验；
            2. `app/utils/upload.py` 的 `validate_image_upload()`（模块 6 巡检照片复用）。
        第 2 处原先误用了 `MAX_UPLOAD_SIZE_MB`（10MB），与第 1 处的 5MB 不一致，
        已随合并遗留项一并修正 —— 统一走本属性。
        """
        return self.IMAGE_MAX_SIZE_MB * 1024 * 1024

    @property
    def llm_configured(self) -> bool:
        """
        上面「大模型配置」那三个字段是否齐备。

        真实调用大模型**之前**先判断它：不齐则走降级路径或明确报错，
        不要把缺 key 的问题拖到 HTTP 401 才暴露。

        （位置说明：它与类开头的 `LLM_*` 字段同属一组，但合并 `origin/main` 时
        正式版在这附近新增了几个 `@property`，冲突里把它挪到了本段末尾。
        先按本文件既有顺序就近安置，避免为了"分组好看"再造一次冲突。）
        """
        return bool(self.LLM_MODEL_NAME and self.LLM_API_KEY and self.LLM_BASE_URL)

    # ---------- 路径属性（模块 2 引入）----------

    @property
    def backend_dir(self) -> Path:
        """
        后端项目根目录（`backend/` 的绝对路径）。

        推导：本文件位于 `backend/app/core/config.py`，
        向上三层即 `backend/`。

        为什么需要它：
            `IMAGE_UPLOAD_DIR` 是相对路径 "uploads"，若用 `Path("uploads").resolve()`
            解析，结果会跟着**进程的工作目录**走 —— 从 backend/ 启动是对的，
            从仓库根或别处启动就会写到错误位置。统一以 backend/ 为基准，
            保证无论从哪里启动，图片都落在同一处。
        """
        return Path(__file__).resolve().parent.parent.parent

    @property
    def image_upload_path(self) -> Path:
        """
        图片落盘目录的绝对路径（顺带创建目录）。

        用法：
            settings.image_upload_path / "20260924" / "xxx.jpg"

        这里顺带 mkdir，让调用方（image_storage）不必关心目录是否存在，
        也避免 main.py 挂载静态目录时因目录缺失而启动失败。
        """
        path = self.backend_dir / self.IMAGE_UPLOAD_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def is_dev(self) -> bool:
        """是否开发环境。"""
        return self.APP_ENV.lower() == "dev"

    # ==================== 启动校验 ====================

    @model_validator(mode="after")
    def _check_security_settings(self) -> Settings:
        """
        启动期安全检查。

        设计取舍：
        - 非 dev 环境密钥强度不足 → 直接拒绝启动（fail fast）。
        - dev 环境密钥强度不足 → 仅告警。因为本地开发的 `.env` 往往沿用旧值，
          硬失败会阻塞所有人联调，代价大于收益。
        """
        secret = self.JWT_SECRET_KEY or ""
        if len(secret) < MIN_JWT_SECRET_LENGTH:
            message = (
                f"JWT_SECRET_KEY 强度不足（当前 {len(secret)} 字符，"
                f"要求至少 {MIN_JWT_SECRET_LENGTH} 字符）。"
                '生成方式：python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
            if self.is_dev:
                logger.warning("%s（当前为 dev 环境，暂不阻止启动）", message)
            else:
                raise ValueError(f"{message}（当前 APP_ENV={self.APP_ENV}，已拒绝启动）")

        if self.JWT_EXPIRE_MINUTES > ACCESS_TOKEN_WARN_MINUTES:
            logger.warning(
                "JWT_EXPIRE_MINUTES=%s 分钟（超过建议上限 %s 分钟）。"
                "accessToken 有效期过长会削弱登出与强制作废的效果，"
                "请确认 .env 中的该配置是否预期为此值。",
                self.JWT_EXPIRE_MINUTES,
                ACCESS_TOKEN_WARN_MINUTES,
            )

        if self.BCRYPT_ROUNDS < 4:
            raise ValueError("BCRYPT_ROUNDS 不得小于 4。")

        self._reject_unfilled_placeholders()

        # AUTH_BYPASS 是模块 1/2 联调用的「跳过 Token 校验」开关。
        # 它会让所有请求以管理员身份放行，因此**只允许在 dev 环境使用** ——
        # 非 dev 环境直接拒绝启动，避免演示/部署时误带着它上线。
        if self.AUTH_BYPASS and not self.is_dev:
            raise ValueError(
                f"AUTH_BYPASS=true 但 APP_ENV={self.APP_ENV}：该开关会跳过全部鉴权，"
                "仅允许在 dev 环境使用。请把 AUTH_BYPASS 改回 false。"
            )

        # DATABASE_URL 覆盖口会绕开 §3.4「连接串固定 mysql+asyncmy://」的硬约束
        # （见 database_url 属性），因此与 AUTH_BYPASS 同样只允许在 dev 环境使用。
        if self.DATABASE_URL and not self.is_dev:
            raise ValueError(
                f"DATABASE_URL 有显式取值但 APP_ENV={self.APP_ENV}：该口仅用于 §13.1 的"
                "本地 SQLite 应急镜像与测试期覆盖，会绕开 §3.4 的 mysql+asyncmy:// 约束。"
                "请清空 DATABASE_URL，改用 .env 中的 DB_* 五项。"
            )

        return self

    # ---------- 配置解析辅助 ----------

    def _reject_unfilled_placeholders(self) -> None:
        """
        拒绝「模板里还没填的占位符」原样上线。

        背景（2026-10-10）
        ------------------
        `.env` 从「本机私有、被 gitignore」改为**提交进仓库**后，里面的密钥一律
        写成占位符。但占位符留着不填会以**两种很难懂**的方式炸掉：

          ① `DB_PASSWORD=<数据库密码>` —— 尖括号里的**中文**会让 asyncmy 在建连接时
             抛 `UnicodeEncodeError: 'latin-1' codec can't encode ...`。
             报错完全看不出「是密码没填」，会让人往编码/驱动方向排查很久。
          ② `JWT_SECRET_KEY=<至少32字符的随机密钥>` 长度不足 32，非 dev 环境下
             `JWT_SECRET_KEY` 的强度校验会拒绝启动，提示语也没说「这只是占位符」。
          ③ `DB_HOST=<your-db-host>` —— 会表现为 DNS 解析失败
             （`getaddrinfo failed` / `Unknown host`），同样看不出是「没填」。
             这个尤其容易误判成「云库挂了 / 网络不通」。

        所以在这里统一拦一道：**只要值与占位符同名，就直说是没填**，并给出该填什么。
        比让用户去猜一个 latin-1 编码错误友好得多。

        判据：值形如 `<...>`（首尾尖括号），与 `.env` / `.env.example` 的占位符风格一致。
        真实密码不会长成这样 —— 若真有人的密码是 `<abc>`，这里会误报，
        但那属于该改密码的情况，提示语说明了怎么绕开。
        """
        placeholders = {
            "DB_HOST": self.DB_HOST,
            "DB_PASSWORD": self.DB_PASSWORD,
            "JWT_SECRET_KEY": self.JWT_SECRET_KEY,
            "REDIS_PASSWORD": self.REDIS_PASSWORD,
            "VISION_API_KEY": self.VISION_API_KEY,
            "LLM_API_KEY": self.LLM_API_KEY,
            "ASR_API_KEY": self.ASR_API_KEY,
        }
        unfilled = [
            key
            for key, value in placeholders.items()
            # REDIS_PASSWORD / ASR_API_KEY 允许留空（本来就可能没有），
            # 只有「写了但写的是占位符」才算没填。
            if value and value.startswith("<") and value.endswith(">")
        ]
        if not unfilled:
            return

        raise ValueError(
            "以下配置还是 .env 模板里的占位符，没有填真实值："
            + "、".join(unfilled)
            + "。\n"
            "  · 这些字段在仓库里**故意留白**（.env 已提交，不能放真实密钥/唯一数据源的地址）。\n"
            "  · 正确做法：把这几行抄进 `backend/.env.local`（该文件不提交）再填真实值，\n"
            "    它会覆盖 `.env` 的同名项（两级加载见 Settings.model_config）。\n"
            "  · 数据库各项口径见 backend/开发流程.md 的「6.1 数据库统一连接规范」。\n"
            "  · JWT_SECRET_KEY 生成方式："
            'python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
            "  · 模型 API Key 填你自己的百炼 Key（VISION / LLM 可复用同一个账号）。"
        )

    @staticmethod
    def _split_csv(raw: str) -> tuple[str, ...]:
        """把 '无人机,直播设备' 解析为元组，顺带去掉空白项"""
        return tuple(item.strip() for item in raw.split(",") if item.strip())

    @property
    def high_value_device_types(self) -> frozenset[str]:
        """高价值设备类型白名单"""
        return frozenset(self._split_csv(self.CONFLICT_HIGH_VALUE_DEVICE_TYPES))

    @property
    def normal_role_names(self) -> frozenset[str]:
        """视为「普通使用者」的角色名集合"""
        return frozenset(self._split_csv(self.CONFLICT_NORMAL_ROLE_NAMES))


# 全局配置实例。其他地方直接：
#   from app.core.config import settings
settings = Settings()

# 模块 3：`services/agent_client.py` 以模块级名字导入 `AGENT_URL`
# （`from ..core.config import AGENT_URL`）。保留这行别名，避免为了一处导入
# 去改模块 3 的既有代码；新代码请直接用 `settings.AGENT_URL`。
AGENT_URL = settings.AGENT_URL
