"""货主档案业务规则：责任人鉴权、客户编码去重、状态流转与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "customer"
CODE_FIELD = "客户编码"
OWNER_FIELD = "责任人"
DISPLAY_STATUS_FIELD = "客户状态"
# 信用等级只能由既有评级体系给出，状态流转一律不改它，故列入受保护字段。
PROTECTED_FIELDS = ["信用等级", "客户编码"]
REQUIRED_FIELDS = ["客户编码", "客户名称", "客户类型"]
STATUS_ORDER = ["待审核", "合作中", "已暂停", "已终止"]
# 已暂停、已终止都属于停用，不再计入合作中。
ACTIVE_STATUS = "合作中"
ACTION_RULES = {"审核客户": "合作中", "暂停合作": "已暂停", "终止合作": "已终止"}
NEGATIVE_ACTIONS = []


class PermissionError(Exception):
    """非责任人尝试提交变更时抛出，由路由层翻译成 403。"""


class CustomerService:
    # ---- 查询口径 -------------------------------------------------------
    def _visible_rows(self) -> list[dict[str, Any]]:
        """同一份客户编码只保留一条（取最早登记的一条），避免清单里重复出现。"""
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in store.rows(MODULE):
            code = str(row.get(CODE_FIELD, "")).strip()
            if code in seen:
                continue
            seen.add(code)
            unique.append(row)
        return unique

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._visible_rows()
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(CODE_FIELD, ""))]
        if status:
            # 以页面口径的「客户状态」为准过滤，停用状态不再被算进合作中。
            rows = [row for row in rows if str(row.get(DISPLAY_STATUS_FIELD, "")) == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def active_count(self) -> int:
        """合作中货主数：仅统计「合作中」，已暂停、已终止不计入。"""
        return sum(
            1
            for row in self._visible_rows()
            if str(row.get(DISPLAY_STATUS_FIELD, "")) == ACTIVE_STATUS
        )

    # ---- 写入 -----------------------------------------------------------
    def create_entry(
        self, values: dict[str, Any], *, operator: str = ""
    ) -> tuple[dict[str, Any] | None, list[str], str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        code = str(values[CODE_FIELD]).strip()
        if any(str(row.get(CODE_FIELD, "")).strip() == code for row in store.rows(MODULE)):
            return None, [], f"客户编码 {code} 已存在，同一份货主只能登记一条"
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in ("客户编码", "客户名称", "客户类型", "联系人", "联系电话", "结算方式", "所属部门"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["信用等级"] = values.get("信用等级") or "待评级"
        # 新建货主的责任人就是提交登记的账号本人。
        entry[OWNER_FIELD] = str(values.get(OWNER_FIELD) or operator).strip()
        entry["status"] = STATUS_ORDER[0]
        entry[DISPLAY_STATUS_FIELD] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], ""

    def run_action(self, entry_id: int, action: str, *, operator: str = "") -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"货主 {entry_id} 不存在或已归档"
        # 只有客户编码对应责任人本人能提交变更，其他账号只读，越权直接拦下。
        owner = str(entry.get(OWNER_FIELD, "")).strip()
        if not operator or operator != owner:
            raise PermissionError(f"仅责任人「{owner}」可提交该货主的变更，当前账号「{operator}」只能查看")
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于货主档案可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        # 状态流转：内部 status 与页面「客户状态」同步，信用等级等其他字段保持原样。
        entry["status"] = target
        entry[DISPLAY_STATUS_FIELD] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"货主已{action}"
