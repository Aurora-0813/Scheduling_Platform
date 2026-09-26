"""全局配置（开发流程 §3.5 / §6.1 / §9.4）。

配置项与团队公用 `backend/.env` 对齐（DB_*、APP_*、JWT_*），两边连同一个云库；
本模块在此之上扩展 `AGENT_URL`（调度 Agent，本模块独有）。

敏感配置一律从 `backend/.env` 注入，禁止硬编码提交。连接串由 DB 五项拼接，
统一使用异步驱动 asyncmy（§3.4），固定 `mysql+asyncmy://`，禁止 `mysql+pymysql://`。
"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ 目录（.env 所在位置）
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """配置项从 backend/.env 与系统环境变量读取（后者优先）。"""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 数据库配置（与公用 backend 对齐） ----------
    # 本地经 SSH 隧道连云服务器 MySQL：
    #   ssh -L 3308:127.0.0.1:3307 root@<服务器IP> -N
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3308
    DB_NAME: str = "smart_scheduler_dev"
    DB_USER: str = "smart_dev"
    DB_PASSWORD: str = ""

    # ---------- 应用配置 ----------
    APP_NAME: str = "SmartScheduler"
    APP_ENV: str = "dev"
    DEBUG: bool = True

    # ---------- JWT 配置 ----------
    # 真实校验由「用户认证与权限」模块接入，此处供 deps.py 对接点读取
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ---------- 本模块扩展 ----------
    # 显式连接串（可选，用于 §13.1 应急/自测的本地 SQLite 镜像）；留空则按上方五项拼接
    DATABASE_URL: str = ""
    # 调度 Agent 服务地址；为空时 agent_client 走内置 mock 调度器
    AGENT_URL: str = ""

    @property
    def database_url(self) -> str:
        """异步连接串：优先显式 DATABASE_URL，否则拼接为 mysql+asyncmy://（§3.4）。"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"mysql+asyncmy://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def sync_database_url(self) -> str:
        """同步连接串（pymysql），与公用 backend 对齐，供 Alembic / 同步脚本使用。"""
        if self.DATABASE_URL:
            # 自测用 SQLite 时无需同步驱动前缀
            if self.DATABASE_URL.startswith("sqlite"):
                return self.DATABASE_URL.replace("+aiosqlite", "")
            return self.DATABASE_URL.replace("+asyncmy", "+pymysql")
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


settings = Settings()
DATABASE_URL = settings.database_url
AGENT_URL = settings.AGENT_URL
