"""
应用配置模块
从 .env 文件读取配置，统一管理
"""
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

    # 指定 .env 文件位置和编码
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

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