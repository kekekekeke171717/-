"""规则引擎：把现场异常翻译成可解释的"次序建议"。

每条规则都带三样东西：
1. evidence —— 触发依据，必须能追溯回原记录字段；
2. action   —— 建议动作，只描述"建议"，不写回业务系统；
3. explain  —— 给患者/家属的统一解释口径（避免护士各说各话）。

规则权重只用于排序，不用于"风险评分"对外宣称；急症一律强制转人工
（事实 f40：紧急症状按院方流程升级，不能把预约顺序置于临床优先级之上）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import (BAND_DEFER, BAND_EMERGENCY, BAND_NORMAL, BAND_PRIORITY,
                     Patient, Reason, to_hhmm)


@dataclass
class RuleContext:
    now_min: int
    late_grace_min: int = 15
    overrun_min: int = 20
    vulnerable_age_high: int = 75
    vulnerable_age_low: int = 6
    doctor_delay_min: int = 0      # 该医生当前实际进度落后计划的分钟数
    snapshot_version: str = "v0"
    defer_protect_min: int = 45    # 让位保护：等到这个分钟数就停止让位


def _passed_protection(p: Patient, ctx: RuleContext) -> bool:
    """让位保护（防饥饿）。

    迟到和加号让出波次是有代价的：如果每次排序都无条件让位，
    队尾的人可能永远排不上（回放里出现过单个患者等待 200+ 分钟的情况）。
    这不是"给迟到者的奖励"，而是把访谈里护士最常抱怨的一句话制度化：

        "迟到患者与现场加号混在队列里，护士反复解释次序"（事实 f10）

    超过保护时长后回到正常排队，并明确告诉患者"已转为正常次序"，
    省掉护士新一轮的解释。
    """
    if not p.arrived:
        return False
    return (ctx.now_min - p.checkin_min) >= ctx.defer_protect_min


def _r_late(p: Patient, ctx: RuleContext) -> Reason | None:
    if not p.arrived or p.kind == "加号":
        return None
    delta = p.checkin_min - p.appt_min
    if delta <= ctx.late_grace_min:
        return None
    if _passed_protection(p, ctx):
        return None
    return Reason(
        code="LATE_ARRIVAL",
        label="迟到超过宽限",
        weight=15,
        evidence=f"预约 {p.appt_time}，签到 {p.checkin_time}，超时 {delta - ctx.late_grace_min} 分钟"
                 f"（宽限 {ctx.late_grace_min} 分钟）",
        action="排入本时段末尾，给出新的预计叫号时段；不取消号源",
    )


def _r_walkin(p: Patient, ctx: RuleContext) -> Reason | None:
    if p.kind != "加号":
        return None
    if _passed_protection(p, ctx):
        return None
    return Reason(
        code="WALK_IN",
        label="现场加号",
        weight=10,
        evidence=f"号别=加号，预约时间 {p.appt_time}，签到 {p.checkin_time or '未签到'}",
        action="排在预约患者之后、迟到患者之前；加号是否放行由医生/护士确认",
        requires_human=True,
    )


def _r_comeback(p: Patient, ctx: RuleContext) -> Reason | None:
    if p.kind != "回诊":
        return None
    return Reason(
        code="COMEBACK",
        label="检查后回诊",
        weight=40,
        evidence=f"号别=回诊，签到 {p.checkin_time or '未签到'}，备注：{p.note or '无'}",
        action="插入当前就诊后的第 1 位，避免重复排队",
    )


def _r_vulnerable(p: Patient, ctx: RuleContext) -> Reason | None:
    hits = []
    if p.age >= ctx.vulnerable_age_high:
        hits.append(f"年龄 {p.age} ≥ {ctx.vulnerable_age_high}")
    if p.age <= ctx.vulnerable_age_low:
        hits.append(f"年龄 {p.age} ≤ {ctx.vulnerable_age_low}")
    if p.vulnerable:
        hits.append("登记为行动不便/需陪护")
    if not hits:
        return None
    return Reason(
        code="VULNERABLE",
        label="脆弱人群",
        weight=25,
        evidence="；".join(hits),
        action="同一时段内优先于普通患者，并提示家属陪同",
    )


def _r_overrun(p: Patient, ctx: RuleContext) -> Reason | None:
    if ctx.doctor_delay_min <= ctx.overrun_min:
        return None
    return Reason(
        code="DOCTOR_OVERRUN",
        label="医生进度落后",
        weight=20,
        evidence=f"{p.doctor} 实际进度落后计划 {ctx.doctor_delay_min} 分钟"
                 f"（阈值 {ctx.overrun_min} 分钟）",
        # 事实 f44：这类情况要标注触发原因与接手人，不能只给一句模糊提醒，
        # 因此必须由护士向患者口头更正后生效。
        action="对患者给出更正后的预计时段，不承诺具体分钟；由导诊核实后口头传达",
        requires_human=True,
    )


def _r_emergency(p: Patient, ctx: RuleContext) -> Reason | None:
    if not p.emergency:
        return None
    return Reason(
        code="EMERGENCY",
        label="急症/高风险提示",
        weight=100,
        evidence=f"分诊等级 {p.triage_level}，备注：{p.note or '主诉提示'}",
        action="立即转临床升级，不进入排序建议；由医护人员按院方流程处理",
        requires_human=True,
    )


def _r_no_show(p: Patient, ctx: RuleContext) -> Reason | None:
    if p.arrived:
        return None
    if ctx.now_min - p.appt_min <= 30:
        return None
    return Reason(
        code="NO_SHOW_RISK",
        label="超时未签到",
        weight=12,
        evidence=f"预约 {p.appt_time}，至 {to_hhmm(ctx.now_min)} 仍未签到",
        action="列入爽约观察，不自动作废号源；由导诊核实后再处理",
        requires_human=True,
    )


RULES = (_r_emergency, _r_late, _r_comeback, _r_vulnerable,
         _r_overrun, _r_walkin, _r_no_show)


def evaluate(p: Patient, ctx: RuleContext) -> list[Reason]:
    """返回该患者命中的全部规则依据（按权重降序）。"""
    reasons = [r for r in (rule(p, ctx) for rule in RULES) if r]
    return sorted(reasons, key=lambda r: -r.weight)


def band_of(reasons: list[Reason]) -> str:
    codes = {r.code for r in reasons}
    if "EMERGENCY" in codes:
        return BAND_EMERGENCY
    if codes & {"COMEBACK", "VULNERABLE"}:
        return BAND_PRIORITY
    if codes & {"LATE_ARRIVAL", "WALK_IN"}:
        return BAND_DEFER
    return BAND_NORMAL


def score_of(reasons: list[Reason]) -> int:
    """不叠加同类规则，取最高权重 + 其余权重的一半，避免堆叠刷分。"""
    if not reasons:
        return 0
    top = reasons[0].weight
    rest = sum(r.weight for r in reasons[1:]) * 0.5
    return int(round(top + rest))
