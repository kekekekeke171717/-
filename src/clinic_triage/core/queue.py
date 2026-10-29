"""队列回放与建议排序。

两种策略跑同一份到达过程：
- fifo      ：现状基线，谁先签到谁先看（迟到/加号/回诊混在队列里）；
- assisted  ：建议策略，急症转人工、回诊插入、脆弱人群同段优先、
              迟到与加号让出当前波次，但每一条都必须护士复核后才生效。

回放结果只用于"方案对比与验收基线"，不等于试点结论（见 docs/01-业务挖掘.md）。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .models import (BAND_DEFER, BAND_EMERGENCY, BAND_PRIORITY, Metrics,
                     Patient, Suggestion, to_hhmm)
from .rules import RuleContext, band_of, evaluate, score_of


@dataclass
class Config:
    late_grace_min: int = 15
    overrun_min: int = 20
    vulnerable_age_high: int = 75
    vulnerable_age_low: int = 6
    defer_protect_min: int = 45      # 让位保护：等待超过这个分钟数就恢复正常次序
    call_grace_min: int = 5           # 现状叫号机的空等时长：叫不到人等这么久再跳过
    max_recall: int = 2               # 同一个号最多叫几轮，叫不来就按爽约处理
    recall_gap_min: int = 15          # 过号后隔多久再叫一次
    day_start: int = 8 * 60
    day_end: int = 17 * 60
    snapshot: str = "09:20"

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        rules = raw.get("rules", {}) or {}
        sim = raw.get("simulation", {}) or {}
        from .models import to_minutes
        return cls(
            late_grace_min=int(rules.get("late_grace_min", 15)),
            overrun_min=int(rules.get("overrun_min", 20)),
            vulnerable_age_high=int(rules.get("vulnerable_age_high", 75)),
            vulnerable_age_low=int(rules.get("vulnerable_age_low", 6)),
            defer_protect_min=int(rules.get("defer_protect_min", 45)),
            call_grace_min=int(rules.get("call_grace_min", 5)),
            max_recall=int(rules.get("max_recall", 2)),
            recall_gap_min=int(rules.get("recall_gap_min", 15)),
            day_start=to_minutes(str(sim.get("day_start", "08:00"))),
            day_end=to_minutes(str(sim.get("day_end", "17:00"))),
            snapshot=str(sim.get("snapshot", "09:20")),
        )


NEVER = 10 ** 6          # 未签到者视为"永不就绪"（预约了号但人没来）


def arrival_of(p: Patient) -> int:
    """医生最早能为其服务的时刻；未签到（爽约）返回 NEVER。"""
    return p.checkin_min if p.arrived else NEVER


def _key_fifo(p: Patient, ctx: RuleContext):
    return (p.checkin_min, p.appt_min, p.appt_id)


def _key_schedule(p: Patient, ctx: RuleContext):
    """现状叫号规则：死守预约号序。

    这是很多门诊叫号机的默认行为 —— 先叫 08:00 的号，没人应就等，
    再叫 08:08 的号。爽约和迟到因此会顺着队列传染给后面每一个人。
    """
    return (p.appt_min, p.checkin_min, p.appt_id)


def _key_assisted(p: Patient, ctx: RuleContext):
    reasons = evaluate(p, ctx)
    band = band_of(reasons)
    rank = {BAND_EMERGENCY: 0, BAND_PRIORITY: 1, "NORMAL": 2, BAND_DEFER: 3}[band]
    # 回诊优先于脆弱人群；同带内按签到先后
    comeback = 0 if any(r.code == "COMEBACK" for r in reasons) else 1
    return (rank, comeback, p.checkin_min, p.appt_id)


POLICIES = {"schedule": _key_schedule, "fifo": _key_fifo, "assisted": _key_assisted}


def simulate(patients: list[Patient], cfg: Config,
             policy: str = "schedule") -> tuple[dict, dict, dict]:
    """多医生单服务台回放，返回 (start_times, wait_times, stats)。

    三种策略跑同一份到达过程：

    | policy     | 含义                                             |
    |------------|--------------------------------------------------|
    | `schedule` | 现状：按预约号序叫号，叫不到人就空等再跳过         |
    | `fifo`     | 参考线：谁先签到谁先看（理论上的无浪费上限）       |
    | `assisted` | 建议：动态排序 + 分带让位，每条都要人工复核才生效 |

    **数学事实要说清楚**：在"医生从不空等"的假设下，
    Σ等待 = Σ开始时刻 − Σ到达时刻，是一个与排序无关的常数。
    所以任何纯排序优化都只是把等待从一群人转移给另一群人，
    真正的收益只能来自"减少叫号空转"这类吞吐损失 —— 这正是
    `schedule` 与 `assisted` 的差距来源（事实 f00 爽约率 19%）。

    急诊在任何策略下都插到最前，但调用方必须知道：
    真实场景中这一步由医护人工确认，不是算法说了算。
    """
    key = POLICIES[policy]
    by_doctor: dict[str, list[Patient]] = {}
    for p in patients:
        by_doctor.setdefault(p.doctor, []).append(p)

    starts: dict[str, float] = {}
    waits: dict[str, float] = {}
    misses = 0        # 叫空号次数
    for doctor, group in by_doctor.items():
        clock = cfg.day_start
        waiting: list[Patient] = list(group)
        waiting.sort(key=arrival_of)
        served = 0
        skipped: dict[str, int] = {}
        next_call: dict[str, int] = {}   # 过号冷却：这个时刻之前不再叫他
        while waiting:
            ctx = RuleContext(now_min=int(clock), late_grace_min=cfg.late_grace_min,
                              overrun_min=cfg.overrun_min,
                              vulnerable_age_high=cfg.vulnerable_age_high,
                              vulnerable_age_low=cfg.vulnerable_age_low,
                              defer_protect_min=cfg.defer_protect_min,
                              doctor_delay_min=doctor_delay(group, served, clock, cfg))
            if policy == "schedule":
                # 叫号机不挑人，只认号序：哪怕后面的人早就到了，也先叫前面那个号
                pool = [p for p in waiting
                        if next_call.get(p.appt_id, 0) <= clock]
                if not pool:                       # 全部在"过号冷却"里，等最早解禁的那个
                    clock = min(next_call.get(p.appt_id, 0) for p in waiting)
                    continue
                nxt = min(pool, key=lambda p: key(p, ctx))
                if arrival_of(nxt) > clock:
                    # 叫不到人：先空等 grace；还没来就过号，recall_gap 分钟后再叫一轮
                    target = arrival_of(nxt)
                    clock += (cfg.call_grace_min if target >= NEVER
                              else min(target - clock, cfg.call_grace_min))
                    if arrival_of(nxt) > clock:
                        misses += 1
                        n = skipped.get(nxt.appt_id, 0) + 1
                        skipped[nxt.appt_id] = n
                        if n >= cfg.max_recall and target >= NEVER:
                            waiting.remove(nxt)     # 叫满轮次仍没来，按爽约处理
                        else:
                            next_call[nxt.appt_id] = clock + cfg.recall_gap_min
                        continue
            else:
                ready = [p for p in waiting if arrival_of(p) <= clock]
                if not ready:
                    nxt = min(waiting, key=arrival_of)
                    if arrival_of(nxt) >= NEVER:
                        break
                    clock = arrival_of(nxt)        # 直接招呼下一个已经到的人
                    continue
                nxt = min(ready, key=lambda p: key(p, ctx))
            waiting.remove(nxt)
            starts[nxt.appt_id] = clock
            waits[nxt.appt_id] = clock - nxt.checkin_min
            clock += max(3, nxt.consult_min)
            served += 1
    return starts, waits, {"missed_calls": misses, "served": served}


def doctor_delay(group: list[Patient], served: int, clock: int, cfg: Config) -> int:
    """医生实际进度落后计划分钟数：已服务人数 vs 计划应完成人数。"""
    if served <= 0:
        return 0
    planned = sum(p.consult_min for p in group[:served])
    return max(0, int(clock - cfg.day_start - planned))


def metrics(label: str, waits: dict[str, float]) -> Metrics:
    vals = sorted(waits.values())
    if not vals:
        return Metrics(label, 0, 0, 0, 0, 0, 0)
    p90 = vals[min(len(vals) - 1, int(len(vals) * 0.9))]
    return Metrics(
        label=label,
        median_wait=statistics.median(vals),
        p90_wait=p90,
        avg_wait=sum(vals) / len(vals),
        max_wait=max(vals),
        over30_ratio=sum(1 for v in vals if v > 30) / len(vals),
        served=len(vals),
    )


@dataclass
class Snapshot:
    at: int
    waiting: list[Patient]
    suggestions: list[Suggestion]
    counts: dict


def snapshot_at(patients: list[Patient], cfg: Config, policy: str = "fifo",
                at: str | None = None) -> Snapshot:
    """取某一时刻的候诊队列，并生成建议（状态一律 PENDING）。"""
    from .models import to_minutes
    now = to_minutes(at or cfg.snapshot)
    starts, _, _ = simulate(patients, cfg, policy)
    waiting = []
    for p in patients:
        if not p.arrived or p.checkin_min > now:
            continue
        st = starts.get(p.appt_id)
        if st is None or st >= now:      # 尚未开始接诊
            waiting.append(p)

    out: list[Suggestion] = []
    served_by_doctor: dict[str, int] = {}
    for p in patients:
        st = starts.get(p.appt_id)
        if st is not None and st < now and p.arrived:
            served_by_doctor[p.doctor] = served_by_doctor.get(p.doctor, 0) + 1

    for doctor, group in _group_by_doctor(waiting).items():
        delay = doctor_delay(patients_by_doctor(patients, doctor),
                             served_by_doctor.get(doctor, 0), now, cfg)
        ctx = RuleContext(now_min=now, late_grace_min=cfg.late_grace_min,
                          overrun_min=cfg.overrun_min,
                          vulnerable_age_high=cfg.vulnerable_age_high,
                          vulnerable_age_low=cfg.vulnerable_age_low,
                          defer_protect_min=cfg.defer_protect_min,
                          doctor_delay_min=delay,
                          snapshot_version=f"snapshot-{to_hhmm(now)}")
        ordered = sorted(group, key=lambda p: _key_assisted(p, ctx))
        for i, p in enumerate(ordered, 1):
            reasons = evaluate(p, ctx)
            s = Suggestion(patient=p, reasons=reasons, score=score_of(reasons),
                           band=band_of(reasons), order=i)
            s.explain = render_card(s, ctx, ahead=i - 1)
            out.append(s)

    counts = {
        "total": len(out),
        "emergency": sum(1 for s in out if s.band == BAND_EMERGENCY),
        "priority": sum(1 for s in out if s.band == BAND_PRIORITY),
        "defer": sum(1 for s in out if s.band == BAND_DEFER),
        "human": sum(1 for s in out if s.needs_human),
    }
    return Snapshot(at=now, waiting=waiting, suggestions=out, counts=counts)


def patients_by_doctor(patients: list[Patient], doctor: str) -> list[Patient]:
    return [p for p in patients if p.doctor == doctor]


def _group_by_doctor(patients: list[Patient]) -> dict[str, list[Patient]]:
    out: dict[str, list[Patient]] = {}
    for p in patients:
        out.setdefault(p.doctor, []).append(p)
    return out


def render_card(s: Suggestion, ctx: RuleContext, ahead: int) -> str:
    """生成给患者/家属的解释卡片：只说依据与预计，不承诺结果。"""
    p = s.patient
    codes = [r.code for r in s.reasons]
    head = ""
    if "EMERGENCY" in codes:
        return ("这位患者已完成分诊，主诉提示需要优先处理。请按院方急症流程升级，"
                "系统不参与排序，也不提供时间承诺。")
    if "COMEBACK" in codes:
        head = "您已完成检查、现在回诊，按门诊规则安排在下一位。"
    elif "VULNERABLE" in codes:
        head = "考虑到年龄与行动情况，我们已为您做优先安排。"
    elif "LATE_ARRIVAL" in codes:
        late = p.checkin_min - p.appt_min - ctx.late_grace_min
        head = (f"您的预约时间是 {p.appt_time}，签到时间 {p.checkin_time}，"
                f"比预约晚 {late} 分钟；按规则排在本时段预约患者之后。")
    elif "WALK_IN" in codes:
        head = "您是现场加号，需要在已预约患者之后安排。"
    else:
        head = "您已进入候诊队列。"

    ahead_txt = f"当前前面还有 {ahead} 位。" if ahead else "下一位即可安排。"
    overrun = ""
    if "DOCTOR_OVERRUN" in codes:
        overrun = "医生正在处理临时情况，进度落后，预计时间可能顺延。"
    tail = "实际叫号以现场为准，如有不适请立即告知护士。"
    return f"{head}{ahead_txt}{overrun}{tail}"
