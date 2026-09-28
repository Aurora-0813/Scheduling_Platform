"""真实 API 冒烟（阶段 5 任务 5-5）：手工执行一次场景 A，打印完整思考链。

**这不是自动化用例，也不该被自动化。** 文件名是 `smoke_*.py`，不在 `pytest.ini` 的
`python_files = test_*.py` 里，`pytest` 不会收集它。原因是主文档 10.2：
真实 API 调用**费用不可控、结果受外部影响**，不能进常规用例；阶段 5 §6 也写明
「真实 API 只做这一次冒烟，不进自动化用例」，后续验证一律靠假 LLM
（`tests/conftest.py::ScriptedChatModel`）。

用法（**必须用 conda 环境 `smart_dev`**，裸 `python` 缺 asyncmy 与 langchain 栈）：

```bash
cd backend && PYTHONIOENCODING=utf-8 \
  "F:/conda_envs/envs_dirs/smart_dev/python.exe" tests/smoke_real_llm.py
```

前置：`backend/.env` 里 `LLM_MODEL_NAME` / `LLM_API_KEY` / `LLM_BASE_URL` 三项齐备。
缺任一项 `build_model()` 会抛 `AgentUnavailableError`，本脚本会明确报出来。

## 要验什么（`AGENT-STAGE-05` 的四条通过标准）

1. 跑通一次（`degraded=false`）
2. `plan` 保住场地（`spaceId` 命中），且 **`reason` 明确说明为什么不需要降级**
3. 各步 `timestamp` **互不相同且递增** —— 只有真实调用才验得了
4. 设备清单非空（`deviceIds` 不为 `[]`）

> ⚠️ **第 2 条 2026-09-27 已由项目群裁定改写（原标准 A + 新增 C）。**
> 原措辞是「设备降级为单投影」，前提是「800 元预算与双投影冲突」——
> 但这个前提**在数据模型里不成立**：`device_resource` 没有价格字段、设备不计费，
> 而 `space_resource.budget` 恰好等于 800，`capacity>=40 AND space_type=2` 只命中场地 4。
> 任何模型都算不出「双投影超支」，Prompt 又明文禁止编造价格。
> 改后的 A = 保住场地 + 说明为何不需降级；C = 另补一条**前提真成立**的降级用例，
> 落在 `tests/test_agent_schedule.py::AGENT-S-06`（要两台直播设备、库里只有 1 台可借）
> 及其前提护栏 `test_seed_supports_the_degradation_case`。
> 沿革见 `docs/spec/done/stage-05-completion.md` §3.2 与 §6 #1。

第 4 条是本阶段的存在理由：假模型不产生真实耗时，所有步骤会挤在同一秒；
只有真实调用才能暴露「用提取时刻统一打点」这个坑（阶段 5 §3.4）。

## 输出会做一次脱敏

任何打印内容都会过一遍 `_redact()`，把 Key / 密码 / JWT 密钥替换成 `***`。
**这是给「贴原始输出到群里或文档里」用的**——原始输出里出现凭据是最常见的泄漏方式，
而人肉检查 100 行输出并不可靠。
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from app.agent.chains.builder import AgentUnavailableError, run_schedule
from app.core.config import settings

#: 场景 A：主文档 4.4 表格第一个场景。**需求原文不要改**——
#: 「800 元 / 40 人 / 双投影」三个约束是这个场景的全部内容。
#: ⚠️ 但「双投影超预算 → 降级为一台」这个**旧预期不成立**：设备不计费
#: （`device_resource` 无价格字段），800 元是**场地**的预算上限，恰好等于场地 4 的价格，
#: 两台投影仪不产生任何额外预算压力。所以这个场景考的是「约束全匹配时不乱降级」，
#: 真降级那半边由 `AGENT-S-06` 承担。
SCENARIO_A = "下周三下午，我们要办一个 40 人的展厅活动，预算 800 元，需要两台投影仪。"

#: 原始日志落盘位置（归档证据）。`.gitignore` 里 `docs/` 未被忽略，
#: 但日志可能含未脱敏内容，所以落在 `backend/` 下并用 `*.log` 规则兜住。
LOG_PATH = Path(__file__).resolve().parent / "smoke_real_llm.log"


def _redact(text: str) -> str:
    """把凭据从输出里抹掉。**在打印与落盘的唯一出口上做**，避免漏掉某条分支。"""
    secrets = [
        settings.LLM_API_KEY,
        settings.DB_PASSWORD,
        settings.JWT_SECRET_KEY,
    ]
    for value in secrets:
        if value and len(value) >= 6:
            text = text.replace(value, "***")
    # 兜底：形态上像 Key 的串（sk- / Bearer 后面的长串）也抹掉，
    # 防的是「配错的那次调用把别的 Key 打进异常信息」这种情形。
    text = re.sub(r"(sk-[A-Za-z0-9_\-]{8,})", "***", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]{12,}", r"\1***", text)
    return text


def _dump(label: str, payload: object) -> None:
    """统一出口：打印 + 累积到日志缓冲。"""
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    text = _redact(f"{label}\n{payload}")
    _BUFFER.append(text)
    print(text, flush=True)


_BUFFER: list[str] = []


def _check_timestamps(steps: list) -> bool:
    """阶段 5 的第 4 条通过标准：各步时间戳**互不相同且递增**。"""
    stamps = [s.timestamp for s in steps]
    _dump("[4] 各步 timestamp", stamps)

    # 0 步必须直接判不通过。空集合既无重复也无逆序，下面的判定会**空真**通过，
    # 打印出一个「✅ 互不相同且严格递增」——2026-09-27 首次真实冒烟失败时就是这样：
    # trace 为 0 步，输出却显示时间戳判定通过。这类假绿比不打印更危险。
    if not stamps:
        _dump("  ⛔ 判定", "trace 为 0 步，没有时间戳可验 —— 判不通过（不是空真通过）")
        return False

    if len(stamps) != len(set(stamps)):
        dup = [s for s in set(stamps) if stamps.count(s) > 1]
        _dump("  ⛔ 判定", f"存在重复时间戳：{dup} —— 说明用的是「提取时刻统一打点」")
        return False

    parsed = [datetime.strptime(s, "%Y-%m-%d %H:%M:%S") for s in stamps]
    deltas = [int((parsed[i + 1] - parsed[i]).total_seconds()) for i in range(len(parsed) - 1)]
    _dump("  相邻步间隔（秒）", deltas)

    if parsed != sorted(parsed) or len(set(parsed)) != len(parsed):
        _dump("  ⛔ 判定", "不是严格递增")
        return False

    if all(d == 0 for d in deltas) and deltas:
        _dump("  ⚠️ 判定", "递增但全部相邻同秒——单调性成立，但时间轴没有拉开")
        return True

    _dump("  ✅ 判定", "互不相同且严格递增")
    return True


def _dump_prompt_facts() -> None:
    """Prompt 四要素的现场核对（阶段 5 §4 第一条）。

    对照表用**表格行**（`| 展厅 | 2 |`）而不是「文中出现过『展厅』」来判——
    后者在表被删掉、只剩正文提及时照样会过，等于没验。
    """
    from app.agent.prompts.scheduler import build_scheduler_prompt

    prompt = build_scheduler_prompt()
    table_rows = {
        label: re.search(rf"\|\s*{re.escape(label)}[^|]*\|\s*{no}\s*\|", prompt) is not None
        for no, label in ((1, "会议室"), (2, "展厅"), (3, "多功能厅"), (4, "户外场地"))
    }
    # 决策优先级的三条必须**按预算→场地→设备的顺序**出现：场景 A/C 的判断全由这个顺序决定
    order = [prompt.find(f"{n}. **{k}**") for n, k in
             ((1, "预算"), (2, "场地"), (3, "设备"))]
    _dump("[0] Prompt 现场核对", {
        "长度": len(prompt),
        "对照表逐行命中": table_rows,
        "对照表齐全": all(table_rows.values()),
        "含当前日期": datetime.now().strftime("%Y-%m-%d") in prompt,
        "优先级三条按序出现（预算→场地→设备）": all(i >= 0 for i in order) and order == sorted(order),
        "含「必须调用 submit_plan」": "submit_plan" in prompt and "唯一正规出口" in prompt,
        "含「至少 3 条修改建议」": "至少 3 条" in prompt,
    })


async def main() -> int:
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _dump("=" * 72, f"真实 API 冒烟 · 场景 A\n启动时刻：{run_at}")

    _dump("[1] LLM 配置（只报状态，不打印值）", {
        "LLM_MODEL_NAME": "已配置" if settings.LLM_MODEL_NAME else "未配置",
        "LLM_API_KEY": f"已配置（{len(settings.LLM_API_KEY)} 字符）" if settings.LLM_API_KEY else "未配置",
        "LLM_BASE_URL": ("已配置（主机 " + settings.LLM_BASE_URL.split("/")[2] + "）")
                        if settings.LLM_BASE_URL else "未配置",
        "llm_configured": settings.llm_configured,
        "AGENT_TIMEOUT": settings.AGENT_TIMEOUT,
        "AGENT_RECURSION_LIMIT": settings.AGENT_RECURSION_LIMIT,
    })
    if not settings.llm_configured:
        _dump("⛔ 中止", "LLM 三项未配齐，无法冒烟。请在 backend/.env 补齐后重跑。")
        return 2

    _dump_prompt_facts()
    _dump("[2] 需求原文", SCENARIO_A)

    try:
        outcome = await run_schedule(text=SCENARIO_A, user_id=1)
    except AgentUnavailableError as exc:
        _dump("⛔ AgentUnavailableError", str(exc))
        return 2

    data = outcome.data
    _dump("[3] 运行结果概览", {
        "success": outcome.success,
        "degraded": outcome.degraded,
        "degraded_reason": outcome.degraded_reason,
        "latency_ms": outcome.latency_ms,
        "steps": outcome.steps,
        "locked_order_id": outcome.locked_order_id,
        "message": outcome.message,
    })
    # 实测这次 29.8s / 上限 30.0s（2026-09-28），只差 155ms。真实调用慢在网络，
    # 演示当天网络一抖就会落进超时降级路径，而这条路径返回的是 200 + 友好提示，
    # 现场看代码发现不了。所以把余量摆出来，不藏在一个数字里。
    _margin_ms = int(settings.AGENT_TIMEOUT * 1000 - outcome.latency_ms)
    if _margin_ms < 3000:
        _dump("⚠️ 超时余量", f"仅剩 {_margin_ms} ms（预算 {int(settings.AGENT_TIMEOUT * 1000)} ms）。"
              "演示前请确认是否放宽 AGENT_TIMEOUT。")

    # ---- 完整 trace：逐字段打印 ----
    _dump(f"[3.1] 完整 trace（{len(data.trace)} 步）", "")
    for step in data.trace:
        _dump(
            f"--- step {step.step} ---",
            {
                "timestamp": step.timestamp,
                "thought": step.thought,
                "action": step.action,
                "actionInput": step.actionInput,
                "observation": step.observation,
                "result": step.result,
            },
        )

    # ---- 方案 ----
    _dump("[3.2] plan", data.plan.model_dump() if data.plan else None)
    _dump("[3.3] backupPlan", data.backupPlan.model_dump() if data.backupPlan else None)
    _dump("[3.4] plan.reason", data.plan.reason if data.plan else None)
    _dump("[3.5] needConfirm", data.needConfirm)

    # ---- 四条通过标准 ----
    _dump("=" * 72, "[通过标准逐条核对]")
    _dump("① 跑通一次", "✅ 是" if not outcome.degraded else f"⛔ 否（降级：{outcome.degraded_reason}）")

    space_kept = bool(data.plan and data.plan.spaceId)
    _dump("② plan 保住场地", f"✅ 是（spaceId={data.plan.spaceId if data.plan else None}）"
                            if space_kept else "⛔ 否：plan 为空或无 spaceId")

    devices = data.plan.deviceIds if data.plan else []
    _dump("② plan 给出设备清单（非空）",
          f"✅ 是（deviceIds={devices}）" if devices
          else "⛔ 否：deviceIds 为空，方案没有配套设备")

    reason = (data.plan.reason if data.plan else None) or ""
    _dump("② reason 说明为何不需降级 —— 本条人工判读，脚本不代判",
          f"reason 原文：{reason}" if reason.strip()
          else "⛔ 否：reason 为空，无从判断")
    # 为什么不自动判：判「说明的是不是『无需降级』」只能靠关键字匹配（「无需」「完全匹配」…），
    # 而模型换个说法就能同时骗过关键字和读这段输出的人——那就造出了假绿。
    # 脚本把 reason 原样打在上面，由人读；能机判的只有「非空」（进 verdict）。
    _dump("  ↳ 判读口径",
          "须写明「约束已全部满足 / 为什么不需要降级」；只写「已找到方案」不算。"
          "顺带声明：真降级用例是 tests/test_agent_schedule.py::AGENT-S-06，不在本脚本内。")

    ts_ok = _check_timestamps(data.trace)

    verdict = all([not outcome.degraded, space_kept, bool(devices),
                   bool(reason.strip()), ts_ok])
    _dump("=" * 72, f"总判定：{'✅ 通过' if verdict else '⛔ 未通过'}")
    return 0 if verdict else 1


if __name__ == "__main__":
    code = asyncio.run(main())
    LOG_PATH.write_text("\n".join(_BUFFER) + "\n", encoding="utf-8")
    print(f"\n[日志已落盘] {LOG_PATH}", flush=True)
    sys.exit(code)
