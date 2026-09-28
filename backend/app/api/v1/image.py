"""
摄像头空间感知模块 —— API 路由层
====================================================================

职责（§7.3：路由层、服务层、数据层分离）：
    路由层**只做三件事**：参数注入、调用服务、包装统一响应体。
    任何业务逻辑、任何 SQL、任何 Prompt 都不允许出现在这里。

接口：
    POST /api/v1/image/analyze   现场拍照识别空间（§5.3 模块 2）
    POST /api/v1/image/sketch    手绘草图识别     （§5.3 模块 2）

安全（§5.1 / §9.1）：
    两个接口都挂 get_current_user 依赖，强制 JWT 认证。
    身份信息只从 JWT 取，请求体中不接受任何 userId。
    当前实现虽未使用 current_user 的字段，但依赖本身起到「鉴权闸门」的作用，
    同时为将来埋点（谁上传的、操作留痕）预留了位置。

关于鉴权开关：
    开发期可在 backend/.env 设 AUTH_BYPASS=true 跳过 Token 校验，
    便于 scripts/seed.py 与 Swagger 直接调测。**演示与部署前必须改回 false。**
"""
from fastapi import APIRouter, Depends, File, UploadFile
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.database import get_db
from app.core.llm import get_vision_llm
from app.core.response import ApiResponse, success
from app.schemas.image import SketchAnalyzeData, SpaceAnalyzeData
from app.services.image_service import analyze_sketch_image, analyze_space_image

# 路由前缀 + 标签：标签会显示在 /docs 的接口分组标题上
# 合并说明：本行原为 prefix="/api/v1/image"。
# 项目约定是「各模块 router 只写自己的相对前缀，统一由 api/v1/__init__.py
# 汇总后挂到 /api/v1 下」（见 app/api/v1/__init__.py 与 app/main.py 的说明）。
# 原写法是在临时 main.py（app.include_router(image_router) 无前缀）下定的，
# 若保持不变，合并后会变成 /api/v1/api/v1/image/...，故对齐为 "/image"。
router = APIRouter(prefix="/image", tags=["摄像头空间感知（模块 2）"])


@router.post(
    "/analyze",
    response_model=ApiResponse[SpaceAnalyzeData],
    summary="拍照识别空间/门牌",
    response_description="返回匹配到的场地、置信度与追问文案",
)
async def analyze_space(
    file: UploadFile = File(..., description="现场照片，JPG/PNG/WEBP，≤5MB"),
    db: AsyncSession = Depends(get_db),
    # 鉴权闸门：身份只从 JWT 解析，禁止从 FormData 传入（§5.1）
    current_user: CurrentUser = Depends(get_current_user),
    # 模型以依赖形式注入 → 单元测试可用 app.dependency_overrides 整体替换为假模型
    llm: BaseChatModel = Depends(get_vision_llm),
):
    """
    用户拍摄场地照片，AI 识别这是哪个场地。

    对应 §5.3 模块 2：`POST /api/v1/image/analyze`

    请求：multipart/form-data，文件字段名固定为 `file`
    响应：统一响应体，data 结构见 SpaceAnalyzeData

    §15.1 演示主线一 屏 1 走的正是这个接口：
        拍照上传 → 展示识别结果与置信度 → 置信度不足时弹出追问让用户确认。
    """
    # 注意：§3.3 要求端点必须是 async def，且服务层全程 await，不得出现同步阻塞调用
    data = await analyze_space_image(db=db, file=file, llm=llm)

    # 低置信度时用不同的 message，前端可直接按 message 做提示分级
    message = "识别完成，请确认" if data.needConfirm else "识别完成"
    return success(data, message=message)


@router.post(
    "/sketch",
    response_model=ApiResponse[SketchAnalyzeData],
    summary="手绘草图识别与布局解读",
    response_description="返回预估人数、布局描述与隐含约束",
)
async def analyze_sketch(
    file: UploadFile = File(..., description="手绘草图，JPG/PNG/WEBP，≤5MB"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
    llm: BaseChatModel = Depends(get_vision_llm),
):
    """
    用户上传手绘布局草图，AI 解读出人数、布局形式与隐含约束。

    对应 §5.3 模块 2：`POST /api/v1/image/sketch`

    请求：multipart/form-data，文件字段名固定为 `file`
    响应：统一响应体，data 结构见 SketchAnalyzeData

    解读结果通常作为 imageContext 的一部分送往核心调度 Agent（模块 4）。
    """
    data = await analyze_sketch_image(db=db, file=file, llm=llm)

    message = "解读完成，请确认" if data.needConfirm else "解读完成"
    return success(data, message=message)
