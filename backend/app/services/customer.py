"""货主档案业务规则：状态流转、字段校验、责任归属与筛选口径都收在这里。

口径约定：
- 客户编码是货主的唯一标识，同一份档案在清单里只出现一条；脏数据在读取时合并。
- 每份档案有明确的「责任账号」，只有该账号登录后才可以提交变更（状态流转与
  资料修改），其他账号只读；「责任人」仅用于展示姓名。
- 客户状态以内部 status 为准，「客户状态」展示字段在规整时同步，列表与详情同源。
- 信用等级沿用原有评级（A/B/C/D），不新增评级口径，只做持久化与合法性校验。
"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "customer"
REQUIRED_FIELDS = ["客户编码", "客户名称", "客户类型", "责任账号"]
STATUS_ORDER = ["待审核", "合作中", "已暂停", "已终止"]
ACTION_RULES = {"审核客户": "合作中", "暂停合作": "已暂停", "终止合作": "已终止"}
# 信用评级保持原有口径，不新增也不调整顺序
CREDIT_LEVELS = ["A", "B", "C", "D"]
DEFAULT_CREDIT_LEVEL = "B"
# 停用口径：暂停与终止都不再算合作中
INACTIVE_STATUSES = ["已暂停", "已终止"]
# 资料变更允许提交的字段；客户编码、责任归属不在其中，责任人不会被顺手改掉
EDITABLE_FIELDS = ["客户名称", "客户类型", "联系人", "联系电话", "结算方式", "信用等级"]
_META_FIELDS = ["id", "status", "pending", "abnormal", "客户状态"]
_ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


class PermissionDenied(Exception):
    """操作人不是该客户编码对应的责任人，无权提交变更。"""


class CustomerService:
    def __init__(self) -> None:
        # 启动时把历史脏数据规整一次：客户状态对齐、重复客户编码合并为一条
        self._normalize()

    # ---- 数据规整 ----------------------------------------------------------

    def _normalize(self) -> None:
        rows = store.rows(MODULE)
        groups: dict[str, list[dict[str, Any]]] = {}
        passthrough: list[dict[str, Any]] = []
        for row in rows:
            code = str(row.get("客户编码") or "").strip()
            if code:
                row["客户编码"] = code
                groups.setdefault(code, []).append(row)
            else:
                passthrough.append(row)

        merged: list[dict[str, Any]] = []
        for code, dupes in groups.items():
            # 同一编码保留信息最有效的一条：业务状态越靠前（待审核 < 合作中 < 停用）越优先，
            # 停用的行不会顶掉真正在合作的档案；再以字段完整度兜底
            primary = min(
                dupes,
                key=lambda row: (
                    STATUS_ORDER.index(str(row.get("status")))
                    if row.get("status") in STATUS_ORDER
                    else len(STATUS_ORDER),
                    -sum(1 for value in row.values() if value not in (None, "")),
                ),
            )
            # 合并其余重复行的补充字段，只填空缺，不覆盖责任人与既有信用等级
            for row in dupes:
                if row is primary:
                    continue
                for key, value in row.items():
                    if key in _META_FIELDS or value in (None, ""):
                        continue
                    primary.setdefault(key, value)
            self._align_status(primary)
            merged.append(primary)
        for row in passthrough:
            self._align_status(row)
            merged.append(row)

        rows[:] = merged

    @staticmethod
    def _align_status(row: dict[str, Any]) -> None:
        """让「客户状态」展示列与内部 status 保持一致，列表/详情不再错位。"""
        status = row.get("status") if row.get("status") in STATUS_ORDER else STATUS_ORDER[0]
        row["status"] = status
        row["客户状态"] = status
        row["pending"] = status != STATUS_ORDER[-1]
        row.setdefault("责任账号", "")
        row.setdefault("责任人", "")
        row.setdefault("责任部门", "")
        # 沿用原有信用评级；历史占位/空值给默认评级，合法评级原样保留
        if str(row.get("信用等级") or "").strip() not in CREDIT_LEVELS:
            row["信用等级"] = DEFAULT_CREDIT_LEVEL

    # ---- 读取 --------------------------------------------------------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        # 规整幂等执行，保证重复编码始终只露出一条
        self._normalize()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("客户编码", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self) -> dict[str, int]:
        """看板口径：停用（暂停/终止）的货主不计入合作中。"""
        self._normalize()
        rows = store.rows(MODULE)
        return {
            "合作中": sum(1 for row in rows if row.get("status") == "合作中"),
            "待审核": sum(1 for row in rows if row.get("status") == "待审核"),
            "停用": sum(1 for row in rows if row.get("status") in INACTIVE_STATUSES),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self._normalize()
        return store.find(MODULE, entry_id)

    # ---- 写入 --------------------------------------------------------------

    def create_entry(
        self, values: dict[str, Any], *, operator: str = "", department: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values["客户编码"]).strip()
        owner_account = str(values["责任账号"]).strip()
        if not _ACCOUNT_PATTERN.match(owner_account):
            return None, "责任账号只能包含字母、数字与 ._@- 字符"
        level = str(values.get("信用等级") or DEFAULT_CREDIT_LEVEL).strip()
        if level not in CREDIT_LEVELS:
            return None, f"信用等级只能是 {'、'.join(CREDIT_LEVELS)}，原有评级口径不变"
        self._normalize()
        if any(str(row.get("客户编码") or "").strip() == code for row in store.rows(MODULE)):
            return None, f"客户编码 {code} 已存在，同一编码只能保留一条货主档案"

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["客户编码"] = code
        entry["责任账号"] = owner_account
        for field in ("客户名称", "客户类型"):
            entry[field] = str(values[field]).strip()
        # 责任人姓名用于展示；未单独填写时以登记账号兜底
        entry["责任人"] = str(values.get("责任人") or owner_account).strip()
        entry["责任部门"] = str(values.get("责任部门") or department or "").strip()
        for field in ("联系人", "联系电话", "结算方式"):
            entry[field] = str(values.get(field) or "").strip()
        entry["信用等级"] = level
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["客户状态"] = STATUS_ORDER[0]
        rows.append(entry)
        return entry, ""

    def _require_owner(self, entry: dict[str, Any], operator: str) -> None:
        if not operator:
            raise PermissionDenied("未能识别登录账号，只有该客户编码对应的责任人可以提交变更")
        if str(entry.get("责任账号") or "").strip() != operator:
            raise PermissionDenied(
                f"客户编码 {entry.get('客户编码')} 的责任账号为{entry.get('责任账号') or '—'}"
                f"（{entry.get('责任人') or '未命名'}），其他账号仅可查看"
            )

    def run_action(
        self, entry_id: int, action: str, *, operator: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"货主 {entry_id} 不存在或已归档"
        self._require_owner(entry, operator)
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于货主档案可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        self._align_status(entry)
        return entry, f"货主已{action}"

    def update_entry(
        self, entry_id: int, values: dict[str, Any], *, operator: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"货主 {entry_id} 不存在或已归档"
        self._require_owner(entry, operator)
        changes = {
            field: str(values[field]).strip()
            for field in EDITABLE_FIELDS
            if field in values and str(values[field] or "").strip()
        }
        if not changes:
            return None, "没有可提交的变更字段"
        level = changes.get("信用等级")
        if level is not None and level not in CREDIT_LEVELS:
            return None, f"信用等级只能是 {'、'.join(CREDIT_LEVELS)}，原有评级口径不变"
        entry.update(changes)
        self._align_status(entry)
        return entry, "货主档案变更已生效"
