"""校验 docs/seed.sql 是否满足五个评审场景的前提条件。

**不需要连数据库。** 脚本直接解析 SQL 文本取数据，因此可以在任何环境、任何 CI 上跑。

为什么需要它：种子数据里的容量、预算、设备状态不是随手编的，它们被评审场景的断言
反向约束。有人把某间会议室的容量从 30 改成 40，场景 B「拆分成两个会议室」就再也不
会被触发，而对应用例只会显示"通过"——因为它本来就没断言拆分一定会发生。
这类失效没有任何报错，只能靠前置条件校验拦住。

用法：
    python scripts/verify_seed.py                # 默认读 docs/seed.sql
    python scripts/verify_seed.py path/to/x.sql

依赖：sqlglot（**仅本脚本使用，不是运行时依赖**，故未写入 requirements.txt）
    pip install sqlglot -i https://mirrors.sjtug.sjtu.edu.cn/pypi/web/simple

退出码 0 表示全部通过，1 表示有前提不成立。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

try:
    import sqlglot
    from sqlglot import exp
except ImportError:
    sys.exit(
        "缺少依赖 sqlglot，本脚本用它解析 SQL 而不连库。安装：\n"
        "  pip install sqlglot -i https://mirrors.sjtug.sjtu.edu.cn/pypi/web/simple"
    )

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = ROOT / "docs" / "seed.sql"

#: 演示基准日。场景 A/B/C/D/E 的用例时间窗须落在该日或其前后 1 日内。
BASELINE_DATE = "2026-10-15"
OCCUPIED_WINDOW = (f"{BASELINE_DATE} 13:00:00", f"{BASELINE_DATE} 17:00:00")


def _value(node: exp.Expression):
    """把 AST 字面量转成 Python 值。注意 Literal.this 是字符串，调用方自行转类型。"""
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Literal):
        return node.this
    if isinstance(node, exp.Array):
        return [_value(e) for e in node.expressions]
    if isinstance(node, exp.Anonymous):
        return (node.this.upper(), [_value(e) for e in node.expressions])
    return node.sql()


def load_tables(sql: str) -> dict[str, list[dict]]:
    """解析 INSERT 语句，返回 {表名: [行字典]}。"""
    tables: dict[str, list[dict]] = {}
    for stmt in sqlglot.parse(sql, read="mysql"):
        if not isinstance(stmt, exp.Insert):
            continue
        cols = [c.name for c in stmt.this.expressions]
        tables[stmt.this.this.name] = [
            dict(zip(cols, [_value(e) for e in row.expressions]))
            for row in stmt.expression.expressions
        ]
    return tables


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    if not path.exists():
        print(f"找不到种子文件：{path}")
        return 1

    try:
        tables = load_tables(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 报告解析失败原因比抛栈更有用
        print(f"SQL 解析失败：{type(exc).__name__}: {exc}")
        return 1

    try:
        spaces = tables["space_resource"]
        devices = tables["device_resource"]
        orders = tables["reserve_order"]
    except KeyError as exc:
        print(f"种子文件缺少表：{exc}")
        return 1

    def to_int(raw) -> int:
        return int(raw)

    def devices_of(order: dict) -> list[int]:
        val = order.get("device_ids")
        if isinstance(val, tuple) and val[0] == "JSON_ARRAY":
            return [to_int(x) for x in val[1]]
        return []

    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
        if not ok:
            failures.append(label)

    # --- 条数与分布（主文档 6.9）---
    want = {"sys_user": 3, "space_resource": 8, "device_resource": 15, "reserve_order": 10}
    for tbl, n in want.items():
        actual = len(tables.get(tbl, []))
        check(f"{tbl} 条数为 {n}", actual == n, f"实际 {actual}")
    check(
        "场地分布 会议室3/展厅2/多功能厅2/户外1",
        sorted(Counter(r["space_type"] for r in spaces).values()) == [1, 2, 2, 3],
    )
    check(
        "设备分布 投影仪4/音响4/显示屏3/无人机2/直播设备2",
        sorted(Counter(r["device_type"] for r in devices).values(), reverse=True) == [4, 4, 3, 2, 2],
    )

    # --- 场景 B：会议室最大容量必须 < 40，否则拆分逻辑不会被触发 ---
    meeting = [to_int(r["capacity"]) for r in spaces if r["space_type"] == "1"]
    check("场景B：会议室最大容量 < 40", bool(meeting) and max(meeting) < 40, f"容量={sorted(meeting)}")

    # --- 场景 D：「容量>=40 且预算<=500」必须无解 ---
    solvable = [
        r["space_name"]
        for r in spaces
        if to_int(r["capacity"]) >= 40 and float(r["budget"]) <= 500
    ]
    check("场景D：无「容量>=40 且预算<=500」的场地", not solvable, f"违例={solvable}")

    # --- 场景 A：800 元 / 40 人的落点必须唯一 ---
    landing = sorted(
        r["space_name"]
        for r in spaces
        if to_int(r["capacity"]) >= 40 and float(r["budget"]) <= 800
    )
    check("场景A：落点唯一 → A栋3楼展厅", landing == ["A栋3楼展厅"], f"命中={landing}")

    # --- 场景 C：四台投影仪必须本身可用，靠预约占用触发替代 ---
    projectors = [r for r in devices if r["device_type"] == "投影仪"]
    check(
        "场景C：投影仪 4 台且全部完好可借",
        len(projectors) == 4
        and all(r["device_status"] == "1" and r["available_count"] == "1" for r in projectors),
        f"数量={len(projectors)}",
    )
    start, end = OCCUPIED_WINDOW
    occupied: set[int] = set()
    for order in orders:
        if order["order_status"] in ("1", "2") and order["start_time"] < end and order["end_time"] > start:
            occupied |= set(devices_of(order))
    projector_ids = {to_int(r["id"]) for r in projectors}
    check(
        f"场景C：基准日 {start[11:16]}~{end[11:16]} 四台投影仪全被占",
        projector_ids and projector_ids <= occupied,
        f"未占={sorted(projector_ids - occupied)}",
    )

    # --- 场景 E：同用户、同日、同场地至少两场 ---
    grouped: dict[tuple, list] = {}
    for order in orders:
        key = (order["user_id"], order["space_id"], order["start_time"][:10])
        grouped.setdefault(key, []).append(order["id"])
    repeat = [k for k, v in grouped.items() if len(v) >= 2]
    check("场景E：存在同用户同日同场地多场", bool(repeat), f"{repeat}")

    # --- AGENT-U-02：两个过滤分支各需一个「只坏一个条件」的独立见证者 ---
    # 若一台设备 status=2 且 available=0，漏写任一过滤条件的查询都会碰巧排除它，用例失效。
    bad_status = [r for r in devices if r["device_status"] == "2"]
    bad_avail = [r for r in devices if r["available_count"] == "0"]
    check(
        "U-02：状态分支见证者【只】被状态筛掉",
        len(bad_status) == 1 and bad_status[0]["available_count"] == "1",
        f"{[r['device_name'] for r in bad_status]}",
    )
    check(
        "U-02：可用数分支见证者【只】被可用数筛掉",
        len(bad_avail) == 1 and bad_avail[0]["device_status"] == "1",
        f"{[r['device_name'] for r in bad_avail]}",
    )
    check(
        "U-02：两见证者不重叠",
        not ({r["id"] for r in bad_status} & {r["id"] for r in bad_avail}),
    )

    # --- 通用数据健康度 ---
    check(
        "订单覆盖 1待确认/2已确认/3已取消/4已完成",
        {r["order_status"] for r in orders} == {"1", "2", "3", "4"},
        f"{sorted({r['order_status'] for r in orders})}",
    )
    check("无时间倒置的预约", all(r["start_time"] < r["end_time"] for r in orders))
    # 「已取消不占位」这条规则需要有对象才能被验证：没有一条 status=3 的订单，
    # 过滤条件写没写都测不出区别。
    cancelled = [r for r in orders if r["order_status"] == "3"]
    check(
        "存在已取消订单（使『已取消不占位』可被验证）",
        len(cancelled) >= 1,
        f"条数={len(cancelled)}",
    )

    print()
    if failures:
        print(f"=== {len(failures)} 项未通过 ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("=== 全部通过：种子数据满足五个评审场景的前提 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
