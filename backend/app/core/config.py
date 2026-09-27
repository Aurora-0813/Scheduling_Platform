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
    DB_HOST: str = "127.0.0.1"            # 数据库主机
    DB_PORT: int = 3308                    # 本地 SSH 隧道端口
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
    LLM_TIMEOUT: int = 60                            # 单次模型调用超时（秒），视觉任务比纯文本慢，给足
    LLM_MAX_RETRIES: int = 1                         # SDK 层自动重试次数

    # ---------- 空间感知策略参数（模块 2）----------
    IMAGE_CONFIDENCE_THRESHOLD: float = 0.75         # 置信度阈值，低于则触发向用户追问
    IMAGE_SPACE_CANDIDATE_LIMIT: int = 100           # 注入 Prompt 的候选场地上限，防止 Prompt 超长
    IMAGE_MAX_SIZE_MB: int = 5                       # 上传图片大小上限
    IMAGE_UPLOAD_DIR: str = "uploads"                # 图片落盘根目录（相对于 backend/）
    IMAGE_STORAGE_BASE_URL: str = "/uploads"         # 对外可访问的 URL 前缀
    IMAGE_ENABLE_AVAILABLE_SLOTS: bool = True        # 是否计算场地空档时段

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
        """
        return (
            f"mysql+asyncmy://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """
        同步数据库连接串，供 Alembic 迁移使用
        格式：mysql+pymysql://用户:密码@主机:端口/库名?charset=utf8mb4
        """
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?charset=utf8mb4"
        )


# 全局配置实例，其他地方直接：
# from app.core.config import settings
settings = Settings()