"""WebSocket 连接管理器：按 user_id 维护连接并定向推送。"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self._connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        conns = self._connections.get(user_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                self._connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, message: dict) -> None:
        """定向推送；单个连接失败则清理该连接，不影响其它连接。"""
        for ws in list(self._connections.get(user_id, set())):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - 见下
                # 断线的连接会在这里抛，但**抛什么取决于传输层**（WebSocketDisconnect /
                # RuntimeError「socket 已关闭」/ 底层网络异常）。这里的语义是「这一个
                # 连接发不出去就丢掉它」，枚举类型只会让某个没料到的异常中断整轮广播
                # —— 那正是本函数要避免的事（见 docstring）。
                self.disconnect(user_id, ws)


manager = ConnectionManager()
