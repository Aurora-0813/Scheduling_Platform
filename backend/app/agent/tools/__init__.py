"""Agent 可调用的 Tool 集合。

四条硬约束（主文档 5.3、9.3）：
1. 全部 async def
2. 不直接使用 AsyncSession，只调用 services/ 层
3. 不注册为 FastAPI 路由
4. docstring 写清参数与取值来源——Agent 靠描述决定调不调、怎么调
"""
