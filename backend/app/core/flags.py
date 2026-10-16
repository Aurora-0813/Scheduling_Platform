"""运行时开关（2026-10-13 新增）。

## 为什么需要它

调度有两条路，**演示时要能随时决定走哪条**：

| | 深度模式（多轮 Agent） | 快速模式（单次调用抽条件） |
|---|---|---|
| 耗时 | 40~80 秒 | 5~10 秒 |
| 能看到什么 | 完整 Thought-Action-Observation 思考链 | AI 从话里读出的条件 + 推荐理由 |

而且**不能为了切这个开关重新打包 APK** —— 所以开关放在**后端**，
前端进入页面时读一次，用来显示当前处于哪一档；**真正的选路也在后端**
（`resolve_fast()`：客户端不指定 fast 时就按 deepMode 决定，见该函数）。

⚠️ 2026-10-13 修：此前 deepMode **只是个显示用的开关** —— 两端客户端都
默认发 `fast: true`，`/agent/schedule` 只看 `fast`，于是这个开关点了也不改变
任何行为。现在它是权威口径，细节见 `resolve_fast()` 的 docstring。

## 三条切换路径（都随时可行，不需要重打包）

1. Web 管理端的一个按钮 → `PUT /api/v1/agent/mode`
2. `curl -X PUT .../agent/mode -H 'Content-Type: application/json' -d '{"deepMode":true}'`
3. 改 `.env` 的 `AGENT_DEEP_MODE_ENABLED` / `AGENT_AI_RECOMMEND` 后重启（保底）
   ⚠️ 这两项 2026-10-13 之前**都不是 Settings 字段**（前者漏进模板、后者根本没定义），
   所以「保底」这条实际上一直不生效；现在两者都已是正式字段，且列在 .env.example。

⚠️ 第 2 条**必须是 JSON body**，不能写成 query（`?deepMode=true`）。
2026-10-13 之前接口签名用的是标量参数，FastAPI 会把它当 query 参数取，
于是前端发 body 时永远取到 `None`、开关切不动却不报错 —— 已修，
详见 `app/schemas/agent.py::AgentModeRequest`。

## 持久化

写 `backend/runtime_flags.json`：改完立刻生效、**重启不丢**。
文件读不到或写不了就退回 `.env` 的默认值 —— 一个开关坏掉不该让服务起不来。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ["all_flags", "set_flag", "deep_mode_enabled", "resolve_fast"]

#: 开关落盘位置。与 .env 同目录（backend/），便于运维一眼找到。
_FLAG_FILE = Path(__file__).resolve().parents[2] / "runtime_flags.json"

#: 全部开关及其**默认值**（默认值来自 .env）。
_DEFAULTS: dict[str, Any] = {
    # 深度模式：多轮 Agent（40~80 秒，思考链完整）。默认关。
    # 直接读真字段，**不要**再用 getattr 兜底：AGENT_DEEP_MODE_ENABLED 与
    # AGENT_AI_RECOMMEND 都已是 config.py 的正式字段（后者 2026-10-13 补上）。
    # 原先 AGENT_AI_RECOMMEND 只存在于这里的 getattr 里，Settings 中并没有它 ——
    # 于是 .env 里写它既不生效也不报错，静默取默认值。字段缺失就该在导入期炸掉，
    # 而不是被兜底吞掉。
    "deepMode": bool(settings.AGENT_DEEP_MODE_ENABLED),
    # AI 推荐：/agent/parse 的「推荐 + 理由 + 备选」由谁给（2026-10-13 加）
    #   True  → 大模型给（展示效果好，但整次调用约 32 秒）
    #   False → 规则算（10~15 秒，理由由真实场地数据拼出）
    # 两个都保留，演示前用 PUT /api/v1/agent/mode 切换对比，不用改代码、不用重打包。
    "aiRecommend": bool(settings.AGENT_AI_RECOMMEND),
}


def _load() -> dict[str, Any]:
    """读盘。任何异常都退回默认值，绝不抛给调用方。"""
    merged = dict(_DEFAULTS)
    try:
        if _FLAG_FILE.exists():
            raw = json.loads(_FLAG_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in _DEFAULTS:
                    if key in raw:
                        merged[key] = bool(raw[key])
    except Exception:  # noqa: BLE001 - 开关读不出来不该影响服务
        logger.warning("runtime_flags.json 读取失败，使用默认值", exc_info=True)
    return merged


_cache: dict[str, Any] | None = None


def all_flags() -> dict[str, Any]:
    global _cache
    if _cache is None:
        _cache = _load()
    return dict(_cache)


def set_flag(key: str, value: Any) -> dict[str, Any]:
    """改一个开关并落盘。落盘失败也照样返回新值（本次进程内一定生效）。"""
    global _cache
    if key not in _DEFAULTS:
        raise KeyError(key)
    current = all_flags()
    current[key] = bool(value)
    _cache = current
    try:
        _FLAG_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        logger.warning("runtime_flags.json 写入失败，本次仅进程内生效", exc_info=True)
    return dict(current)


def deep_mode_enabled() -> bool:
    return bool(all_flags().get("deepMode"))


def resolve_fast(fast: bool | None) -> bool:
    """把「客户端想怎么跑」和「全局开关怎么说」合成一个最终决定（2026-10-13 加）。

    ## 为什么需要它（这是一个真实存在的功能缺口，不是洁癖）

    这两个开关长在 Web 管理端的同一个面板里，但**只有 aiRecommend 真的接进了业务**：
    它在 app/agent/chains/parse.py 里被读，决定「推荐 + 理由」由大模型给还是规则算。

    而 deepMode 只被 GET/PUT /agent/mode 自己读写 —— /agent/schedule
    选路用的是请求体里的 fast，与它无关。于是：

        · Web 端 api/monitor.js::agentSchedule 默认发 fast: true
        · 小程序端 api/agent.js::schedule 默认发 fast: true
        · Web 端 agentWorkbench.run() 根本不传，同样落到 true

    三条路**全都**在客户端就把 fast 定成了 true，后端那个开关**从来没被读过**。
    表现就是：点「🧠 深度思考」按钮，高亮换了、后端也真的落盘了，但调度**照旧走快速
    模式** —— 没有多轮思考链、没有 40~80 秒。这属于「接口回 200、行为没变」的
    静默失败，最难查的一种。用户看到按钮亮了，只会以为「深度思考原来这么快」。

    ## 口径（三态，而不是二态）

        fast is None  → 跟随全局开关 deepMode（**服务端说了算**，这是默认）
        fast is True  → 强制快速模式（单次调用，trace 只有 3 步）
        fast is False → 强制多轮 Agent（思考链完整，40~80 秒）

    为什么保留「显式指定」而不是让开关一票否决：/agent/schedule 的调用方里
    既有要演示完整思考链的调度台，也有只想要一条结果的程序化入口。
    把 fast 定成三态，两者都能表达；而**不传**时一律交给全局开关 ——
    这正是「演示前切一下、不必重新打包 APK」得以成立的前提。
    """
    if fast is not None:
        return bool(fast)
    return not deep_mode_enabled()
