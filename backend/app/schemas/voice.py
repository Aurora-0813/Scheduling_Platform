"""语音输入模块 Pydantic 数据模型（模块 1）。

命名约定（§6.2）：API 传输字段一律 camelCase，字段名直接使用 camelCase，
不做 snake_case ↔ camelCase 的 alias 转换，与模块 2 保持一致。
"""

from pydantic import BaseModel, Field


class FormatRequest(BaseModel):
    """口语清洗请求。"""

    rawText: str = Field(..., description="语音识别出的原始文本")


class FormatResult(BaseModel):
    """口语清洗结果（接口文档用）。"""

    formattedText: str = Field(..., description="清洗后的书面语")
    keywords: list[str] = Field(default_factory=list, description="结构化关键词")


class AsrResult(BaseModel):
    """语音识别结果（接口文档用）。"""

    text: str = Field(..., description="识别出的文字")
