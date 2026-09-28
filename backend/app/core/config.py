"""
应用配置模块
从 .env 文件读取配置，统一管理
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用配置类
    字段名对应 .env 里的变量名，大小写敏感
    """

    # ---------- 数据库配置 ----------
    # 下面五项是本地兜底值，真实值一律放 .env；以 .env 为准
    DB_HOST: str = "127.0.0.1"            # 数据库主机
    # 本机到达 MySQL 的实际端口，即 SSH 隧道的本地入口端口，须与隧道的 -L 参数一致。
    # 注意与云服务器侧 MySQL 的监听端口不是同一个数：云侧是 3307，
    # 本机隧道入口是 3308，即 ssh -L 3308:127.0.0.1:3307。
    # 代码连的是本机入口，所以默认值必须是隧道端口。
    DB_PORT: int = 3308
    DB_NAME: str = "smart_scheduler_dev"   # 数据库名
    DB_USER: str = "smart_dev"             # 数据库用户
    DB_PASSWORD: str = ""                  # 数据库密码，真实值放 .env

    # ---------- 应用配置 ----------
    APP_NAME: str = "SmartScheduler"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    # ---------- JWT 配置 ----------
    JWT_SECRET_KEY: str = "change-me"      # 真实值放 .env
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ---------- 认证开关（临时，待集成组接管）----------
    # true 时 get_current_user 直接放行，不校验 Token。
    # 仅供模块自测与联调使用，**部署与演示前必须改为 false**
    AUTH_BYPASS: bool = False

    # ---------- 跨域（§5.4）----------
    # 允许访问后端的前端来源。开发期放 localhost 各端口；
    # 生产期替换为真实域名。小程序不走浏览器 CORS，不受此项影响。
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",   # Vite 默认端口
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    ]

    # ---------- 视觉多模态模型（模块 2 摄像头空间感知）----------
    # 规范 §3.5：模型名称与 API 版本在 .env 中集中配置
    # 规范 §3.3：不训练、不微调模型，全部走公有云 API
    VISION_MODEL_NAME: str = ""                      # 模型名，如 qwen-vl-max
    VISION_API_KEY: str = ""                         # 密钥，真实值放 .env
    VISION_API_BASE: str = ""                        # OpenAI 兼容端点地址
    VISION_STRUCTURED_OUTPUT: bool = True            # 是否启用 with_structured_output（见 app/core/llm.py）
    # 单次模型调用超时（秒），视觉任务比纯文本慢，给足。
    # ⚠️ 类型 int → float 是模块 7 合并时的统一：模块 7 的超时降级用例要传
    #    0.05 这类亚秒值，收成 int 会被截断为 0，ChatOpenAI(timeout=0) 行为未定义。
    # 默认值取主干原值 60，不取模块 7 的 20.0 —— 本键被三条链路共用
    #    （视觉 app/core/llm.py、口语清洗 services/format_service.py、模块 7 文本链），
    #    下调会把前两条一起砍短。模块 7 原名 LLM_TIMEOUT_SECONDS，已废弃。
    LLM_TIMEOUT: float = 60.0
    LLM_MAX_RETRIES: int = 1                         # SDK 层自动重试次数

    # ---------- 空间感知策略参数（模块 2）----------
    IMAGE_CONFIDENCE_THRESHOLD: float = 0.75         # 置信度阈值，低于则触发向用户追问
    IMAGE_SPACE_CANDIDATE_LIMIT: int = 100           # 注入 Prompt 的候选场地上限，防止 Prompt 超长
    IMAGE_MAX_SIZE_MB: int = 5                       # 上传图片大小上限
    IMAGE_UPLOAD_DIR: str = "uploads"                # 图片落盘根目录（相对于 backend/）
    IMAGE_STORAGE_BASE_URL: str = "/uploads"         # 对外可访问的 URL 前缀
    IMAGE_ENABLE_AVAILABLE_SLOTS: bool = True        # 是否计算场地空档时段

    # ---------- 语音识别 ASR（模块 1 语音输入，百度短语音标准版）----------
    BAIDU_APP_ID: str = ""                           # 百度智能云 AppID
    BAIDU_API_KEY: str = ""                          # API Key，真实值放 .env
    BAIDU_SECRET_KEY: str = ""                       # Secret Key，真实值放 .env
    ASR_MODEL_PID: int = 1537                        # 1537 普通话(含英文/数字，实测最稳)；1737 纯中文
    ASR_RATE: int = 16000                            # 采样率，与小程序录音参数对齐
    ASR_MAX_DURATION_S: int = 60                     # 识别音频最长秒数

    # ---------- 口语格式化（模块 1，DeepSeek 纯文本模型）----------
    DEEPSEEK_API_KEY: str = ""                       # 真实值放 .env
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-flash"           # 口语清洗所用模型
    # ---------- Redis 配置 ----------
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # ---------- 大模型配置 ----------
    LLM_API_KEY: str = ""                          # 真实值放 .env
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    # 模块 7 原 LLM_TIMEOUT_SECONDS: float = 20.0 已废弃，并名到上方 LLM_TIMEOUT
    #    （同一用途只留一个键）。注意本键默认 60.0，模块 7 链路最坏耗时随之 ×3。


    # ---------- AI 总开关 ----------
    # AI_ENABLED=False：所有 AI 能力降级为模板/纯统计，业务链路不中断
    AI_ENABLED: bool = True
    # AI_USE_FAKE_LLM=True：切换假 LLM 夹具（答辩应急预案 + 离线测试）
    AI_USE_FAKE_LLM: bool = False

    # ---------- 软冲突扫描 ----------
    CONFLICT_SCAN_ENABLED: bool = True
    CONFLICT_SCAN_INTERVAL_SECONDS: int = 300
    CONFLICT_SCAN_INITIAL_DELAY_SECONDS: int = 20
    CONFLICT_PAST_WINDOW_DAYS: int = 7
    CONFLICT_FUTURE_WINDOW_DAYS: int = 7
    CONFLICT_MAX_ORDERS_IN_SNAPSHOT: int = 2000    # 保护 2 核 2G 服务器内存

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
    CONFLICT_DEDUP_TTL_SECONDS: int = 86400

    # 指定 .env 文件位置和编码
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # 路径属性
    # ------------------------------------------------------------------

    @property
    def backend_dir(self) -> Path:
        """
        后端项目根目录（即 backend/ 的绝对路径）。

        推导过程：
            本文件位于 backend/app/core/config.py
            Path(__file__).resolve()      → .../backend/app/core/config.py
            .parent                       → .../backend/app/core
            .parent                       → .../backend/app
            .parent                       → .../backend

        为什么要这个属性：
            IMAGE_UPLOAD_DIR 配置的是相对路径 "uploads"，
            如果直接用 Path("uploads").resolve()，解析结果会跟着**进程的工作目录**跑 ——
            从 backend/ 启动是对的，但从仓库根或别处启动就会写到错误位置。
            统一以 backend/ 为基准，保证无论从哪启动，图片都落在同一个地方。
        """
        return Path(__file__).resolve().parent.parent.parent

    @property
    def image_upload_path(self) -> Path:
        """
        图片落盘目录的绝对路径（自动创建）。

        用法：
            settings.image_upload_path / "20260924" / "xxx.jpg"

        说明：
            这里顺带 mkdir，让调用方（image_storage）不必关心目录是否存在，
            也避免 main.py 在挂载静态目录时因为目录不存在而启动失败。
        """
        path = self.backend_dir / self.IMAGE_UPLOAD_DIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def database_url(self) -> str:
        """
        异步数据库连接串，供 FastAPI 运行时使用

        格式：mysql+asyncmy://用户:密码@主机:端口/库名?charset=utf8mb4

        连接串由本属性拼出，不放进 .env —— 开发流程.md 3.4 把驱动固定为
        asyncmy，多一个手写的 URL 配置项就多一处写错驱动的机会。
        """
        return (
            f"mysql+asyncmy://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """
        同步数据库连接串，**仅供 Alembic 迁移使用**

        格式：mysql+pymysql://用户:密码@主机:端口/库名?charset=utf8mb4

        这是本项目唯一允许出现同步驱动的位置，理由：
        Alembic 的迁移环境（alembic/env.py）是同步的，它需要一条可同步连接的
        连接串才能对比模型元数据与实际库结构。而开发流程.md 3.4 禁止同步驱动
        针对的是**应用运行时**——应用侧一律走 asyncmy，本属性不参与任何业务请求。

        因此这条 URL 不构成违规，但边界必须守住：
        - 只有 alembic/env.py 可以引用它
        - 任何 API / service / Agent 代码都不得使用

        约束由 tests/unit/test_config.py 的两条用例守住。
        """
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    # ---------- 配置解析辅助 ----------

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


# 全局配置实例，其他地方直接：
# from app.core.config import settings
settings = Settings()