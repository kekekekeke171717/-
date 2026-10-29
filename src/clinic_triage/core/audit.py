"""审计链：每条建议的生成、复核、改动都可按业务编号重建。

对应事实 f45：保留业务编号、资料版本、事实引用、建议结果、人工改动和签核人；
不记录账号口令或不必要的个人信息。

状态机刻意做成"单向且必须由人推进"：

     suggest（系统）      accept / reject / escalate（人工）
    "" ──────────────▶ PENDING ─────────────────────────▶ ACCEPTED / REJECTED / ESCALATED
                          ▲
                          └── 终态不可逆，不可重复复核（事实 f15：错误结果不覆盖原记录）

系统只能产出 PENDING。**没有人点确认，建议就不生效。**
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from .models import ACCEPTED, ESCALATED, PENDING, REJECTED, ReviewRecord

ACTIONS = {"suggest": PENDING, "accept": ACCEPTED, "reject": REJECTED,
           "escalate": ESCALATED}

ALLOWED = {
    "": {PENDING},                      # 尚未生成建议 → 只能由系统 suggest
    PENDING: {ACCEPTED, REJECTED, ESCALATED},
    ACCEPTED: set(),
    REJECTED: set(),
    ESCALATED: set(),
}


class AuditLog:
    def __init__(self, path: str, snapshot_version: str = ""):
        self.path = path
        self.snapshot_version = snapshot_version
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def record(self, appt_id: str, action: str, operator: str, reason_code: str,
               note: str = "", status: str | None = None) -> ReviewRecord:
        """落一条审计流水。

        `status` 为该业务**当前**状态；留空时自动从流水里推断，
        这样调用方不可能"跳过 suggest 直接复核"，也不会出现重复复核。
        """
        target = ACTIONS.get(action)
        if target is None:
            raise ValueError(f"未知动作: {action}")
        prev = self.status_of(appt_id) if status is None else status
        allowed = ALLOWED.get(prev, set())
        if target not in allowed:
            raise ValueError(f"状态 {prev or '（未生成）'} 不允许执行 {action}"
                             f"（事实 f15：不可重复复核、不可覆盖原记录）")
        if not operator.strip():
            raise ValueError("动作必须记录操作人（不得借用他人账号，事实 f41）")
        rec = ReviewRecord(
            at=datetime.now().isoformat(timespec="seconds"),
            appt_id=appt_id,
            action=action,
            operator=operator,
            reason_code=reason_code,
            note=note,
            snapshot_version=self.snapshot_version,
            prev_status=prev,
            status=target,
        )
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        return rec

    def suggest(self, appt_id: str, reason_code: str, note: str = "",
                operator: str = "system") -> ReviewRecord:
        """系统生成建议 —— 唯一能产出 PENDING 的入口。"""
        return self.record(appt_id, "suggest", operator, reason_code, note, status="")

    def read(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def status_of(self, appt_id: str) -> str:
        """某条业务当前处于什么状态（最后一条流水说了算）。"""
        last = ""
        for r in self.read():
            if r.get("appt_id") == appt_id:
                last = r.get("status", "")
        return last


def next_status(action: str) -> str:
    return ACTIONS[action]


def replay_chain(records: list[dict], appt_id: str) -> list[dict]:
    """按业务编号重建一次处理链，用于审计抽检（事实 f45）。"""
    return [r for r in records if r.get("appt_id") == appt_id]


def summary(records: list[dict]) -> dict:
    out: dict = {"suggest": 0, "accept": 0, "reject": 0, "escalate": 0, "total": 0}
    reason_codes: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for r in records:
        a = r.get("action")
        if a in out:
            out[a] += 1
        out["total"] += 1
        rc = r.get("reason_code") or ""
        if rc:
            reason_codes[rc] = reason_codes.get(rc, 0) + 1
        st = r.get("status") or ""
        if st:
            statuses[st] = statuses.get(st, 0) + 1
    out["reason_codes"] = dict(sorted(reason_codes.items(), key=lambda kv: -kv[1]))
    out["statuses"] = statuses
    return out
