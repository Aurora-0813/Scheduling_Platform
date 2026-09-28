# 归档：模块 6（AI 智能巡检与维修工单）早期独立实现

**这不是项目的一部分，不参与运行、不参与测试、不参与构建。** 仅作留档。

## 这是什么

杨睿坤同学的分支 `feature/ruikun-device-inspection`（提交 `7c0eb02`）交付的实现。
该分支开发时，后端仍按「backend 就是仓库根」的旧布局组织，因此这 4 个文件
被提交到了 **仓库根目录**：

| 文件 | 说明 |
| --- | --- |
| `main.py` | 一个独立的 FastAPI 应用（381 行），自带 CORS、StaticFiles、建表调用 |
| `models.py` | 同步 SQLAlchemy 模型：`device` / `inspection_record` / `repair_order` |
| `schemas.py` | Pydantic 出入参模型 |
| `database.py` | 同步 engine 与 `get_db`，使用 `Base.metadata.create_all()` 建表 |

合并时这 4 个文件被移到这里，原因是它们与本仓库现行的 `backend/` 规范**不是同一套东西**，
直接留在根目录会让仓库里出现第二套「看起来能跑」的后端。

## 与现行规范的差异（为什么不能直接用）

| 维度 | 本归档实现 | 仓库现行规范 |
| --- | --- | --- |
| 应用入口 | 根目录 `main.py`，独立 app | `backend/app/main.py`，唯一 app |
| 目录位置 | 仓库根 | `backend/` |
| ORM 会话 | 同步 `Session` | 异步 `AsyncSession` + `asyncmy` |
| 建表方式 | `Base.metadata.create_all()` | Alembic 迁移（schema 唯一来源） |
| 模型 | `device` / `inspection_record` / `repair_order` | `backend/app/models/inspection.py` 的 `inspect_record` / `repair_ticket`，外键指向 `space_resource` / `device_resource` / `sys_user` |
| 响应体 | 直接返回模型 | 统一 `{"code":200,"message":"操作成功","data":{}}` |
| 字段命名 | `snake_case` 直出 | DB `snake_case` ↔ API `camelCase` |
| 接口路径 | `/device`、`/inspection/upload`、`/repair_order` | `/api/v1/inspect/submit`、`/api/v1/tickets/list`、`/api/v1/tickets/{id}/status` |
| 身份来源 | 无鉴权 | JWT（`inspectorId` / `handlerId` 一律从 token 解析） |

**结论：前端连不上这份实现。** `frontend/src/api/inspect.js` 调的是团队契约的
`/inspect/submit`、`/tickets/list`、`/tickets/{id}/status`，本目录的 `main.py` 提供的是
另一组路径。它的价值在于**业务逻辑与字段设计可供参考**（设备 CRUD、图片上传、
AI 分析、工单状态流转），而不是可以直接挂上去运行。

## 后续怎么处理

模块 6 要真正进主干，需要按 `backend/` 规范重写一遍：

1. 模型落到 `backend/app/models/inspection.py`（已存在 `InspectRecord` / `RepairTicket` 骨架，
   需按本目录 `models.py` 的业务字段补齐：`img_path`、`ai_result`、`report_content`、
   `is_abnormal`、`order_content` 等）
2. 新增 `backend/app/schemas/inspect.py`、`backend/app/services/inspect_service.py`
3. 新增 `backend/app/api/v1/inspect.py`（相对前缀 `/inspect`），并在
   `backend/app/api/v1/__init__.py` 的 `_ROUTERS` 处注册
4. 若模型有变更，补 Alembic 迁移
5. 补 `backend/tests/` 下的用例

另注：本目录代码原本在仓库根生成 `static/` 上传目录，对应 `.gitignore` 里的 `static/`
规则已随归档一并撤回（现行上传目录是 `backend/uploads/`）。
