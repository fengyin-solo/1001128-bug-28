"""货主档案接口：维护货主，覆盖审核客户、暂停合作、终止合作与资料变更。

写操作（状态流转、资料变更、登记）都需要带上操作人身份，只有客户编码对应的
责任人可以提交；GET 接口不做归属限制，其他账号可查看。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.customer import CustomerService, PermissionDenied

router = APIRouter(prefix="/api/customer", tags=["货主档案"])

service = CustomerService()

LIST_FIELDS = ["客户编码", "客户名称", "客户类型", "联系人", "联系电话", "结算方式", "信用等级", "客户状态", "责任人", "责任账号", "责任部门"]
STATUSES = ["待审核", "合作中", "已暂停", "已终止"]


def identity(
    x_operator: str | None = Header(default=None, alias="X-Operator"),
    x_department: str | None = Header(default=None, alias="X-Department"),
) -> tuple[str, str]:
    """从请求头识别当前登录账号（ASCII）与所属部门。"""
    return (x_operator or "").strip(), (x_department or "").strip()


def _denied(error: PermissionDenied) -> HTTPException:
    raise HTTPException(status_code=403, detail=str(error))


@router.get("/stats")
def get_stats() -> dict[str, int]:
    """看板统计：合作中不含已暂停、已终止的停用货主。"""
    return service.stats()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出货主档案清单：返回去重后的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "customer", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按客户编码检索"),
    status: str | None = Query(default=None, description="待审核、合作中、已暂停、已终止"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按客户编码与状态过滤货主档案列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条货主明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"货主 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(
    payload: EntryPayload,
    identity: tuple[str, str] = Depends(identity)
) -> ActionResult:
    """登记一条货主，缺字段或客户编码重复时说明原因而不是静默丢弃。"""
    operator, department = identity
    try:
        entry, message = service.create_entry(payload.values, operator=operator, department=department)
    except PermissionDenied as error:
        _denied(error)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="货主已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    identity: tuple[str, str] = Depends(identity)
) -> ActionResult:
    """对单条货主执行审核客户、暂停合作、终止合作；仅责任人可提交。"""
    operator, _ = identity
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, operator=operator)
    except PermissionDenied as error:
        _denied(error)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(
    entry_id: int,
    payload: EntryPayload,
    identity: tuple[str, str] = Depends(identity)
) -> ActionResult:
    """提交货主资料变更（含信用等级）；只有该客户编码对应的责任人可以提交。"""
    operator, _ = identity
    try:
        entry, message = service.update_entry(entry_id, payload.values, operator=operator)
    except PermissionDenied as error:
        _denied(error)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
