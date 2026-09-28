import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 从 .env 读取数据库配置，不要把账号密码硬编码在代码里
load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "smart_scheduler_dev")

if not DB_PASSWORD:
    raise RuntimeError("未读取到 DB_PASSWORD，请检查项目根目录下的 .env 文件")

# 密码里的特殊字符必须先做 URL 编码，再拼进连接串。
# 连接串的结构是 用户名:密码@主机:端口，密码里如果本身带 @，不编码就会被
# 当成「密码结束、主机开始」的分隔符，导致主机名解析错误、连不上库。
# 例：密码 p@ssw0rd  ->  p%40ssw0rd
# 除了 @，: / ? # & 等同样有风险，quote_plus 一并处理掉。
ENCODED_PASSWORD = quote_plus(DB_PASSWORD)

SQLALCHEMY_DATABASE_URL = (
    f"mysql+mysqldb://{DB_USER}:{ENCODED_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,   # 取连接前先探活，避免MySQL 8小时空闲断连报错
    pool_recycle=3600,    # 连接超过1小时回收重建
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
