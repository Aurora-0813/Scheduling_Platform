"""Agent 组装与思考链提取。

注意：LangChain 1.x 下本目录不是旧版 Chain，而是：
- builder.py  create_agent 的组装
- trace.py    LangGraph messages → TraceStep 的映射

主文档 3.3 已明确「以 create_agent 封装为准，不直接操作底层 State」。
"""
