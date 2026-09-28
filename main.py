from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os
import uuid
import json
import base64
import httpx
import models
from database import engine, get_db
import schemas

# 读取 .env 里的 AI 配置（API_KEY / BASE_URL / MODEL）
load_dotenv()

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="场地设备管理后端")

# 跨域配置。前端单独跑时（Vite 5173、或直接用 file:// 打开页面）浏览器会先发
# OPTIONS 预检请求，不加这个中间件预检会返回 405，请求全部被同源策略拦掉，
# 前端看到的是"网络错误"，很容易误判成后端没起来。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # 通配来源和 allow_credentials=True 不能同时生效（浏览器会拒绝），
    # 本项目身份校验走 Authorization 头，不需要 cookie 凭据
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 图片保存目录
UPLOAD_DIR = "static"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# 挂载静态目录，上传后的图片可以直接通过 /static/文件名 访问
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")

@app.get("/")
def index():
    return {"msg": "后端服务启动成功！"}

# ========== 设备CRUD接口 ==========
@app.post("/device", response_model=schemas.Device)
def create_device(device: schemas.DeviceCreate, db: Session = Depends(get_db)):
    db_device = models.Device(**device.model_dump())
    db.add(db_device)
    db.commit()
    db.refresh(db_device)
    return db_device

@app.get("/device", response_model=list[schemas.Device])
def get_all_devices(db: Session = Depends(get_db)):
    return db.query(models.Device).all()

@app.get("/device/{device_id}", response_model=schemas.Device)
def get_device(device_id: int, db: Session = Depends(get_db)):
    db_device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="设备不存在")
    return db_device

@app.put("/device/{device_id}", response_model=schemas.Device)
def update_device(device_id: int, device: schemas.DeviceCreate, db: Session = Depends(get_db)):
    db_device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="设备不存在")
    for key, value in device.model_dump().items():
        setattr(db_device, key, value)
    db.commit()
    db.refresh(db_device)
    return db_device

@app.delete("/device/{device_id}")
def delete_device(device_id: int, db: Session = Depends(get_db)):
    db_device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="设备不存在")
    db.delete(db_device)
    db.commit()
    return {"msg": "设备删除成功"}

# ========== 维修工单接口 ==========
@app.post("/repair_order", response_model=schemas.RepairOrder)
def create_repair_order(order: schemas.RepairOrderCreate, db: Session = Depends(get_db)):
    # 传了关联ID就得真实存在，否则会建出指向空处的工单。
    # 库里没有外键约束，挡不住这种脏数据，只能在这里查
    if order.inspection_id is not None:
        exists = db.query(models.InspectionRecord).filter(
            models.InspectionRecord.id == order.inspection_id).first()
        if not exists:
            raise HTTPException(status_code=404, detail="巡检记录不存在")
    if order.device_id is not None:
        exists = db.query(models.Device).filter(
            models.Device.id == order.device_id).first()
        if not exists:
            raise HTTPException(status_code=404, detail="设备不存在")

    db_order = models.RepairOrder(**order.model_dump())
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    return db_order

@app.get("/repair_order", response_model=list[schemas.RepairOrder])
def get_all_repair_orders(db: Session = Depends(get_db)):
    return db.query(models.RepairOrder).all()

@app.get("/repair_order/{order_id}", response_model=schemas.RepairOrder)
def get_repair_order(order_id: int, db: Session = Depends(get_db)):
    db_order = db.query(models.RepairOrder).filter(models.RepairOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    return db_order

@app.put("/repair_order/{order_id}", response_model=schemas.RepairOrder)
def update_repair_order(order_id: int, order: schemas.RepairOrderUpdate, db: Session = Depends(get_db)):
    db_order = db.query(models.RepairOrder).filter(models.RepairOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="工单不存在")
    db_order.status = order.status
    db.commit()
    db.refresh(db_order)
    return db_order

# ========== 巡检图片上传接口 ==========
# 允许的图片类型：content_type -> 统一使用的保存后缀
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
}
# 允许的扩展名
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

# 上传大小上限 5MB
MAX_UPLOAD_SIZE = 5 * 1024 * 1024
# 从上传流里一次读多少字节。分块读是为了能边读边判大小，
# 不用 await file.read() 一次性把整个文件读进内存（服务器只有 2核2G，
# 传个大文件进来会直接把内存打爆）
UPLOAD_CHUNK_SIZE = 1024 * 1024

# 文件头魔数。扩展名和 content_type 都是请求方说了算，可以随便伪造，
# 文件内容的前几个字节伪造不了，用它判断是不是真图片
PNG_MAGIC = b"\x89\x50\x4e\x47"   # 89 50 4E 47
JPEG_MAGIC = b"\xff\xd8\xff"      # FF D8 FF


def _detect_image_ext(head: bytes) -> str | None:
    """按文件头判断真实图片类型；认不出来（不是jpg/png）返回 None"""
    if head.startswith(PNG_MAGIC):
        return ".png"
    if head.startswith(JPEG_MAGIC):
        return ".jpg"
    return None


@app.post("/inspection/upload")
async def upload_inspection_image(
    device_id: int = Form(..., description="设备ID"),
    file: UploadFile = File(..., description="巡检图片，仅支持jpg/png"),
    db: Session = Depends(get_db)
):
    # 校验图片类型：扩展名和 content_type 都要合法
    # 只信 content_type 不够（前端可以伪造），所以两边都查
    ext = os.path.splitext(file.filename or "")[1].lower()
    if file.content_type not in ALLOWED_IMAGE_TYPES or ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="只支持jpg/png格式图片")

    # 校验设备是否存在
    db_device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not db_device:
        raise HTTPException(status_code=404, detail="设备不存在，请先新增设备")

    # 分块读取，边读边判大小，超限立刻中断返回 413，不用等整个文件传完
    content = bytearray()
    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=413, detail="图片大小不能超过5MB")

    # 魔数校验：扩展名和 content_type 都对不代表文件真是图片，
    # 把 .php/.txt 改名成 .png 再报个 image/png 就能骗过前面那道校验。
    # 这里认文件头，认不出来说明根本不是图片，直接拒掉，不让它落进 static/
    save_ext = _detect_image_ext(bytes(content[:8]))
    if not save_ext:
        raise HTTPException(status_code=400, detail="文件内容不是有效的jpg/png图片")

    # 生成唯一文件名，防止重名覆盖
    # 后缀用魔数认出来的真实类型，不直接用用户传的文件名
    filename = f"{uuid.uuid4().hex}{save_ext}"
    save_path = os.path.join(UPLOAD_DIR, filename)
    # 存库用正斜杠路径，Windows 上 os.path.join 会拼成 static\xxx.jpg，
    # 前端拿去当 URL 用会出问题
    img_url_path = f"/{UPLOAD_DIR}/{filename}"

    # 保存图片到本地
    with open(save_path, "wb") as f:
        f.write(content)

    # 创建巡检记录
    record = models.InspectionRecord(
        device_id=device_id,
        img_path=img_url_path,
        ai_result=None,
        report_content=None,
        is_abnormal=False
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "msg": "图片上传成功",
        "record_id": record.id,
        "img_path": record.img_path,
        "device_id": record.device_id
    }

# 查询巡检记录列表
@app.get("/inspection/list", response_model=list[schemas.InspectionRecord])
def get_inspection_list(db: Session = Depends(get_db)):
    return db.query(models.InspectionRecord).all()

# ========== AI 巡检识别接口 ==========
AI_BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
AI_MODEL = os.getenv("MODEL")
AI_API_KEY = os.getenv("API_KEY")

# 单次请求超时（秒）。模型要先生成推理内容再输出正文，给宽一点
AI_TIMEOUT = 180
# 这个模型是推理模型，思考过程也占 max_tokens。
# 调大到 4000：实测遇到过长描述（异常项多、报告写得细）把 2000 耗尽的情况，
# 返回的 JSON 被从中间截断，json.loads 解析失败直接 502
AI_MAX_TOKENS = 4000

INSPECTION_PROMPT = """你是资深设备巡检专家。请仔细观察这张设备巡检照片，完成三件事：
1. 客观描述画面中设备的实际状况（外观、部件、铭牌、仪表读数，以及有无锈蚀、破损、渗漏、变形、异物、指示灯异常等）
2. 判断该设备是否存在异常
3. 生成一份巡检报告

严格要求：
- 只输出一个 JSON 对象，不要输出任何其他文字，不要用 markdown 代码块包裹
- 字段格式：{"is_abnormal": true 或 false, "ai_result": "对设备状况的客观描述，200字以内", "report_content": "巡检报告，包含巡检结论、发现的问题、处理建议，400字以内"}
- 如果画面中没有可识别的设备（空白、严重模糊、完全遮挡），则 is_abnormal 设为 false，并在 report_content 中明确说明照片无效、建议重新拍摄"""


def _read_image_as_data_url(disk_path: str, filename: str) -> str:
    """把本地图片转成 data:image/xxx;base64,... 形式，供模型接口使用"""
    ext = os.path.splitext(filename)[1].lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"
    with open(disk_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _strip_code_fence(text: str) -> str:
    """模型偶尔仍会套一层 ```json ... ```，这里剥掉"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    t = t.strip("`").strip()
    if t.lower().startswith("json"):
        t = t[4:]
    return t.strip()


@app.post("/inspection/ai_analysis", response_model=schemas.InspectionAnalysisResult)
async def ai_analysis(req: schemas.InspectionAnalysisRequest, db: Session = Depends(get_db)):
    if not AI_API_KEY or not AI_BASE_URL or not AI_MODEL:
        raise HTTPException(status_code=500, detail="AI配置缺失，请检查 .env 里的 API_KEY/BASE_URL/MODEL")

    # 1. 找巡检记录
    record = db.query(models.InspectionRecord).filter(
        models.InspectionRecord.id == req.record_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="巡检记录不存在")

    # 2. 定位图片文件。img_path 存的是 /static/xxx.png，取 basename 拼成本地路径，
    #    顺便避免路径穿越
    filename = os.path.basename(record.img_path or "")
    disk_path = os.path.join(UPLOAD_DIR, filename)
    if not filename or not os.path.exists(disk_path):
        raise HTTPException(status_code=404, detail=f"图片文件不存在：{record.img_path}")

    # 3. 调用多模态模型
    payload = {
        "model": AI_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": INSPECTION_PROMPT},
                {"type": "image_url", "image_url": {"url": _read_image_as_data_url(disk_path, filename)}},
            ],
        }],
        "max_tokens": AI_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT) as client:
            resp = await client.post(
                f"{AI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"调用AI接口失败：{type(e).__name__}: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"AI接口返回错误 {resp.status_code}：{resp.text[:200]}")

    # 4. 解析返回
    try:
        content = resp.json()["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"AI接口返回结构异常：{type(e).__name__}: {resp.text[:200]}")

    content = _strip_code_fence(content)
    if not content:
        raise HTTPException(status_code=502, detail="AI未返回正文（可能 max_tokens 被推理过程耗尽，可调大 AI_MAX_TOKENS）")

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"AI返回的不是合法JSON：{content[:200]}")

    # 5. 回写数据库
    record.ai_result = str(result.get("ai_result") or "")
    record.report_content = str(result.get("report_content") or "")
    record.is_abnormal = bool(result.get("is_abnormal", False))
    db.commit()
    db.refresh(record)

    # 6. 判定为异常就自动开一张维修工单，让巡检结果闭环到维修环节
    repair_order_id = None
    if record.is_abnormal:
        # 同一条巡检记录可能被反复分析（前端重复点按钮、重试等），
        # 建单前先查这张记录是不是已经有工单了，有就直接复用，不重复建单
        existing = db.query(models.RepairOrder).filter(
            models.RepairOrder.inspection_id == record.id
        ).first()
        if existing:
            repair_order_id = existing.id
        else:
            # 工单内容给维修人员看，ai_result 正常不会为空，
            # 但模型偶尔会漏字段，兜个默认值避免生成一张没有内容的工单
            order_content = (record.ai_result or record.report_content
                             or "AI识别到设备异常，请现场核实")
            db_order = models.RepairOrder(
                inspection_id=record.id,
                device_id=record.device_id,
                order_content=order_content,
                status="待维修",
            )
            db.add(db_order)
            db.commit()
            db.refresh(db_order)
            repair_order_id = db_order.id

    return {
        "record_id": record.id,
        "device_id": record.device_id,
        "is_abnormal": record.is_abnormal,
        "ai_result": record.ai_result,
        "report_content": record.report_content,
        "repair_order_id": repair_order_id,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)