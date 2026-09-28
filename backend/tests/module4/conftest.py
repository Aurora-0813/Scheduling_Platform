"""核心调度 Agent 模块测试夹具。

夹具在阶段 7 逐步补齐，顺序不可调换：
1. fake_llm    假 LLM 夹具（必须先冒烟验证 bind_tools 可用）
2. db_session  测试库夹具（连 smart_scheduler_test，用例后回滚）

见 docs/spec/stage-07-testing.md
"""
