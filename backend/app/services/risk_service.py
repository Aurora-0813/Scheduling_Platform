"""
登录异常检测（模块 9 的可选增强，项目文档 4.4）

定位
----
文档 4.4 明说这是「可选增强、不影响主流程」。因此本模块：

- 由 `settings.AI_RISK_ENABLED`（默认 **false**）控制是否启用。默认关闭时
  登录流程**完全不碰 Redis 的风控键**，与没这个模块时行为一致；
- 只做**规则判定**：连续失败计数 + 登录 IP 变化。所有 Redis 调用都吞掉异常，
  绝不因为风控不可用而让登录失败（安全组件的可用性问题不能转化为业务不可用）；
- **不含独立的 LLM 调用**。原因：真实的大模型异常登录分析需要「IP → 地理位置」
  的解析能力（离线 IP 库或第三方接口），本项目没有该数据源；调用 LLM 也只会
  把同样的 IP 字符串扔过去，得到一段无法验证的描述文本。为了一个可选件引入
  外部依赖与不确定性，收益为负。真正的接入点已留在 `assess_login_risk()`
  的 TODO 处，接口形状（入参/出参）已定好。

为什么规则判定仍有价值
----------------------
「同一账号连续 N 次密码错误」这一条不需要任何外部数据，却能挡住最常见的
在线密码爆破；「登录 IP 与上次成功登录不同」则能在答辩演示里直观展示
异常登录识别的能力。两者都只用现有 Redis 键即可实现。

与主流程的边界
--------------
- `is_locked_out()` 在读 Redis 失败时返回 False（判定为「未锁定」）——
  宁可漏判也不能把所有人挡在门外；
- `record_failure()` 在读 Redis 失败时返回 0，调用方据此不做锁定判断；
- `clear_on_success()` 失败只记日志。

即：**风控永远只能「少拦」，不能「多拦」**。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.core.exceptions import RedisUnavailableError
from app.core.logging import get_logger
from app.core.token_store import TokenStore

__all__ = [
    "LoginRiskAssessment",
    "is_enabled",
    "is_locked_out",
    "record_failure",
    "clear_on_success",
    "assess_login_risk",
]

logger = get_logger(__name__)

# 判定为「异地登录」时，只记日志与返回标记；不改用更严格的校验。
# TODO(模块 9): 接入真实的地理位置数据源后，可在此增加「异地 + 敏感操作」
#              的二次验证；当前没有该数据源，不做猜测。
_ip_last_seen: dict[int, str] = {}


@dataclass(frozen=True)
class LoginRiskAssessment:
    """登录风险判定结果（供日志与审计使用，不参与放行/拒绝决策）。"""

    suspicious: bool = False
    """是否命中任一异常规则。"""

    failed_attempts: int = 0
    """本次登录前该账号的连续失败次数。"""

    ip_changed: bool = False
    """本次登录 IP 与该账号上次成功登录的 IP 不同。"""

    reasons: tuple[str, ...] = ()
    """命中的规则名，便于日志检索。"""


def is_enabled() -> bool:
    """风控是否启用（`AI_RISK_ENABLED`，默认 false）。"""
    return bool(settings.AI_RISK_ENABLED)


async def is_locked_out(token_store: TokenStore, username: str) -> bool:
    """
    该账号是否因连续失败已被临时锁定。

    Redis 不可用时返回 False —— 风控只能少拦，不能多拦。
    """
    if not is_enabled():
        return False
    try:
        attempts = await token_store.get_login_failure(username)
    except RedisUnavailableError as exc:
        logger.warning("风控：读取登录失败计数失败，判定为未锁定（%s）", exc)
        return False
    return attempts >= settings.LOGIN_MAX_FAILURES


async def record_failure(token_store: TokenStore, username: str) -> int:
    """
    记一次登录失败，返回累计次数（失败或未启用时返回 0）。

    计数键的 TTL 是滑动窗口：每次失败都续期，因此持续爆破会让窗口一直有效，
    而停止尝试 `LOGIN_FAIL_WINDOW_SECONDS` 后计数自动清零
    （实现见 app/core/token_store.py 的 `record_login_failure`）。
    """
    if not is_enabled():
        return 0
    try:
        return await token_store.record_login_failure(
            username, ttl_seconds=settings.LOGIN_FAIL_WINDOW_SECONDS
        )
    except RedisUnavailableError as exc:
        logger.warning("风控：记录登录失败计数失败（不影响本次响应）（%s）", exc)
        return 0


async def clear_on_success(token_store: TokenStore, username: str) -> None:
    """登录成功后清零失败计数。"""
    if not is_enabled():
        return
    try:
        await token_store.clear_login_failure(username)
    except RedisUnavailableError as exc:
        logger.warning("风控：清零登录失败计数失败（不影响本次响应）（%s）", exc)


async def assess_login_risk(
    token_store: TokenStore,
    user_id: int,
    username: str,
    client_ip: str | None,
) -> LoginRiskAssessment:
    """
    登录成功后的异常判定，结果只用于日志与审计。

    调用时机：密码校验**通过之后**。放在失败路径上会让「这个账号存在吗」
    通过响应耗时或日志形态泄露出去。

    规则（全部为本地规则，无外部调用）：
    1. 本次登录前连续失败次数 ≥ 阈值的一半 —— 可能是爆破刚刚得手；
    2. 登录 IP 与该账号上次成功登录的 IP 不同。

    规则 2 的局限必须讲清楚：IP 变化**不等于**异地 —— 手机换基站、公司出口
    IP 轮换都会触发。它只能作为「值得看一眼」的线索，不能作为拒绝依据，
    所以本函数不返回任何「是否放行」的语义。
    """
    if not is_enabled():
        return LoginRiskAssessment()

    reasons: list[str] = []

    try:
        failed = await token_store.get_login_failure(username)
    except RedisUnavailableError:
        failed = 0

    threshold = max(1, settings.LOGIN_MAX_FAILURES)
    if failed and failed * 2 >= threshold:
        reasons.append("frequent_failures")

    ip_changed = False
    if client_ip:
        previous = _ip_last_seen.get(user_id)
        # 首次登录（previous 为 None）不算异常
        ip_changed = previous is not None and previous != client_ip
        _ip_last_seen[user_id] = client_ip
        if ip_changed:
            reasons.append("ip_changed")

    assessment = LoginRiskAssessment(
        suspicious=bool(reasons),
        failed_attempts=failed,
        ip_changed=ip_changed,
        reasons=tuple(reasons),
    )

    if assessment.suspicious:
        # 用 warning 级别：这是需要人工留意的安全线索，但不阻断登录
        logger.warning(
            "风控：登录存在异常线索 userId=%s username=%s ip=%s 规则=%s",
            user_id,
            username,
            client_ip,
            ",".join(reasons),
            extra={
                "extra_fields": {
                    "userId": user_id,
                    "riskReasons": list(reasons),
                    "clientIp": client_ip,
                }
            },
        )
    return assessment
