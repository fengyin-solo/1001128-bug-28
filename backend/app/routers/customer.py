"""货主档案接口：维护货主，覆盖审核客户、暂停合作、终止合作等动作。

变更类接口通过 X-Operator 请求头识别当前账号，并校验其是否为该客户编码对应的责任人；
责任人之外的账号只读。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.customer import PermissionError, CustomerService

router = APIRouter(prefix="/api/customer", tags=["货主档案"])

service = CustomerService()

LIST_FIELDS = [
    "客户编码", "客户名称", "客户类型", "联系人", "联系电话",
    "结算方式", "信用等级", "客户状态", "责任人", "所属部门",
]
STATUSES = ["待审核", "合作中", "已暂停", "已终止"]


def _current_operator(x_operator: str | None) -> str:
    """从请求头解析当前登录账号；前端按 UTF-8 百分号编码，演示环境默认「值班管理员」。"""
    if not x_operator:
        return "值班管理员"
    return unquote(x_operator).strip()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按客户编码检索"),
    status: str | None = Query(default=None, description="待审核、合作中、已暂停、已终止"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按客户编码与状态过滤货主档案列表；同编码只返回一条，没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status is not None and status and status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"客户状态「{status}」不在可选范围内")
    items, total = service.list_entries(keyword=keyword, status=status or None, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """货主看板统计：合作中只统计「合作中」状态，已暂停、已终止不计入。"""
    rows, _ = service.list_entries(page=1, size=10000)
    return {
        "合作货主": service.active_count(),
        "待审核货主": sum(1 for row in rows if str(row.get("客户状态", "")) == "待审核"),
        "停用货主": sum(1 for row in rows if str(row.get("客户状态", "")) in ("已暂停", "已终止")),
    }


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出货主档案清单：返回去重后的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "customer", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条货主明细；不存在时给出可读的错误说明。详情与列表同源，字段不错位。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"货主 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, x_operator: str | None = Header(default=None)) -> ActionResult:
    """登记一条货主，责任人默认为提交账号；缺字段或编码重复时说明原因。"""
    operator = _current_operator(x_operator)
    entry, missing, error = service.create_entry(payload.values, operator=operator)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if error:
        return ActionResult(ok=False, message=error)
    return ActionResult(ok=True, message="货主已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator: str | None = Header(default=None),
) -> ActionResult:
    """对单条货主执行审核客户、暂停合作、终止合作。

    仅客户编码对应的责任人本人可提交，其他账号返回 403，只能查看；信用等级保持不变。
    """
    operator = _current_operator(x_operator)
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, operator=operator)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
