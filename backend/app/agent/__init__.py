"""核心调度 Agent 模块（模块 4）。

- tools/   4 个 Tool + submit_plan，只被 Agent 调用，不注册为 FastAPI 路由
- prompts/ System Prompt 模板
- chains/  create_agent 组装与思考链提取（LangChain 1.x，非旧版 Chain）
"""
