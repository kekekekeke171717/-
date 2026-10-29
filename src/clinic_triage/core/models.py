"""领域模型：预约记录、规则依据、建议与指标。

设计约束（来自访谈事实 healthcare-appointments-f05 / f22 / f32 / f40 / f45）：
建议只做"时间解释与队列信息辅助"，专业分诊判断、急症升级、加号审批
始终由医护人员确认；模型不写回业务系统。
"""
from __future__ import annotations

from dataclasses import dataclass, field


def to_minutes(hhmm: str) -> int:
    """'08:30' -> 510；空值返回 -1。"""
    hhmm = (hhmm or "").strip()
    if not hhmm:
        return -1
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes: int) -> str:
    minutes = int(round(minutes))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# 建议状态：系统只产出 PENDING，不接受即为不生效
PENDING = "PENDING"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
ESCALATED = "ESCALATED"

# 优先级带：EMERGENCY 不进排序，直接转人工
BAND_EMERGENCY = "EMERGENCY"      # 急症 / 高风险：强制转人工
BAND_PRIORITY = "PRIORITY"        # 回诊、脆弱人群：护士确认后可前置
BAND_NORMAL = "NORMAL"            # 正常排队
BAND_DEFER = "DEFER"              # 迟到 / 加号：让出当前波次，给出预计时间


@dataclass
class Patient:
    appt_id: str
    dept: str
    doctor: str
    appt_time: str
    checkin_time: str
    kind: str            # 预约 / 加号 / 回诊
    age: int
    vulnerable: bool
    emergency: bool
    triage_level: int    # 1 最紧急 .. 4 非紧急
    consult_min: int
    note: str = ""

    @property
    def appt_min(self) -> int:
        return to_minutes(self.appt_time)

    @property
    def checkin_min(self) -> int:
        return to_minutes(self.checkin_time)

    @property
    def arrived(self) -> bool:
        return self.checkin_min >= 0


@dataclass
class Reason:
    code: str
    label: str
    weight: int
    evidence: str          # 触发依据（可追溯到原记录字段）
    action: str            # 建议动作
    requires_human: bool = False


@dataclass
class Suggestion:
    patient: Patient
    reasons: list[Reason] = field(default_factory=list)
    score: int = 0
    band: str = BAND_NORMAL
    status: str = PENDING
    explain: str = ""
    order: int = 0          # 建议次序（同一医生内）

    @property
    def primary(self) -> str:
        return self.reasons[0].label if self.reasons else "正常排队"

    @property
    def needs_human(self) -> bool:
        return any(r.requires_human for r in self.reasons) or self.band == BAND_EMERGENCY


@dataclass
class Metrics:
    label: str
    median_wait: float
    p90_wait: float
    over30_ratio: float
    avg_wait: float
    served: int
    max_wait: float

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "median_wait": round(self.median_wait, 1),
            "p90_wait": round(self.p90_wait, 1),
            "avg_wait": round(self.avg_wait, 1),
            "max_wait": round(self.max_wait, 1),
            "over30_ratio": round(self.over30_ratio * 100, 1),
            "served": self.served,
        }


@dataclass
class ReviewRecord:
    """一次人工复核动作，写入 audit.jsonl。"""
    at: str
    appt_id: str
    action: str            # accept / reject / escalate
    operator: str
    reason_code: str
    note: str = ""
    snapshot_version: str = ""
    prev_status: str = ""      # 流转前状态，"" 表示本条为该业务的首次记录
    status: str = PENDING      # 流转后状态
