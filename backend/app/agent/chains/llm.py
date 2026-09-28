"""文本 LLM 装配入口。

⚠️ 实现已上收到 app/core/llm.py，本文件仅作转发，保证既有 import 路径继续可用。
   新代码请直接从 app.core.llm 导入。
"""
from app.core.llm import (          # noqa: F401
    FAKE_NOTIFY_JSON,
    build_fake_llm,
    build_llm,
)

__all__ = ["FAKE_NOTIFY_JSON", "build_fake_llm", "build_llm"]
