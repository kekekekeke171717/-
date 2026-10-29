"""可直接运行的最小示例 —— 看完这个你就懂这个库在干什么。

    python examples/demo.py

演示五件事：
1. 一条迟到记录会产生什么样的建议（必须带依据，否则不许出门）
2. 同一批数据，三种叫号策略的候诊差多少 —— 以及"为什么纯排序救不了候诊"
3. 让位保护：没有它，队尾的人会被无限往后推
4. 急症：系统唯一会做的事是让路
5. 审计流水长什么样，怎么按业务编号重建链路

全程不写任何文件到任何业务系统。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from clinic_triage.core.audit import AuditLog, replay_chain
from clinic_triage.core.models import Patient, Suggestion, to_minutes
from clinic_triage.core.queue import (Config, metrics, render_card, simulate,
                                      snapshot_at)
from clinic_triage.core.rules import RuleContext, band_of, evaluate, score_of

BAR = "─" * 68


def line(title: str) -> None:
    print(f"\n{BAR}\n  {title}\n{BAR}")


# ---------------------------------------------------------------- 数据

WANG = [
    # appt_id, 预约, 签到, 号别, 年龄, 备注
    ("A001", "08:00", "07:45", "预约", 42, ""),
    ("A002", "08:10", "07:50", "预约", 35, ""),
    ("A003", "08:20", "07:55", "预约", 58, ""),
    ("A004", "08:30", "08:05", "预约", 61, ""),
    ("A005", "08:40", "08:10", "回诊", 47, "取了化验单回来复诊"),
    ("A006", "08:50", "08:15", "加号", 33, "现场加号"),
    ("A007", "09:00", "08:20", "预约", 29, ""),
    ("A008", "09:10", "08:25", "预约", 52, ""),
    ("A009", "09:20", "08:30", "预约", 22, ""),
    ("A100", "08:00", "08:35", "预约", 44, "迟到 35 分钟"),
    ("A200", "09:30", "", "预约", 48, "爽约：号留了，人没来"),
]
LI = [
    ("B001", "08:00", "07:48", "预约", 78, "高龄"),
    ("B002", "08:15", "07:52", "预约", 5, "幼童"),
    ("B003", "08:30", "07:58", "预约", 44, ""),
    ("B004", "08:45", "08:03", "预约", 66, ""),
    ("B005", "09:00", "08:08", "预约", 41, ""),
    ("B006", "09:15", "08:12", "预约", 55, ""),
    ("B102", "08:30", "08:20", "预约", 57, "胸闷、大汗 → 急症标记"),
    ("B200", "09:30", "", "预约", 60, "爽约：号留了，人没来"),
]


def build_day() -> list[Patient]:
    """一小天门诊：17 位挂号，其中 1 位迟到、1 位加号、1 位回诊、
    1 位高龄、1 位幼童、1 位急症、2 位爽约 —— 现实里有的麻烦这里都有。"""
    rows = []
    for aid, appt, checkin, kind, age, note in WANG:
        rows.append(Patient(appt_id=aid, dept="内科门诊", doctor="王医生",
                            appt_time=appt, checkin_time=checkin, kind=kind,
                            age=age, vulnerable=(age >= 75 or age <= 6),
                            emergency=False, triage_level=4,
                            consult_min=10, note=note))
    for aid, appt, checkin, kind, age, note in LI:
        rows.append(Patient(appt_id=aid, dept="内科门诊", doctor="李医生",
                            appt_time=appt, checkin_time=checkin, kind=kind,
                            age=age, vulnerable=(age >= 75 or age <= 6),
                            emergency=(aid == "B102"),
                            triage_level=1 if aid == "B102" else 4,
                            consult_min=10, note=note))
    return rows


def make_ctx(cfg: Config, now: str, **kw) -> RuleContext:
    return RuleContext(now_min=to_minutes(now),
                       late_grace_min=cfg.late_grace_min,
                       overrun_min=cfg.overrun_min,
                       vulnerable_age_high=cfg.vulnerable_age_high,
                       vulnerable_age_low=cfg.vulnerable_age_low,
                       defer_protect_min=cfg.defer_protect_min,
                       snapshot_version=f"snapshot-{now}", **kw)


# ---------------------------------------------------------------- ①

def demo_one_suggestion():
    line("① 一条迟到记录 → 一条建议（没有依据的建议不许出门）")
    cfg = Config()
    p = next(x for x in build_day() if x.appt_id == "A100")
    ctx = make_ctx(cfg, "09:00", doctor_delay_min=25)

    reasons = evaluate(p, ctx)
    s = Suggestion(patient=p, reasons=reasons, score=score_of(reasons),
                   band=band_of(reasons), order=7)
    s.explain = render_card(s, ctx, ahead=6)

    print(f"业务编号 {p.appt_id} · {p.dept} / {p.doctor} · {p.kind}")
    print(f"预约 {p.appt_time} · 签到 {p.checkin_time} · 备注：{p.note or '—'}")
    print(f"优先级带 {s.band} · 状态 {s.status} · 建议序号 {s.order}")
    print("\n命中规则：")
    for r in reasons:
        print(f"  · [{r.code}] {r.label}")
        print(f"      依据：{r.evidence}")
        print(f"      动作：{r.action}")
        print(f"      需人工确认：{'是' if r.requires_human else '否'}")
    print(f"\n护士要照着念的解释口径：\n  {s.explain}")


# ---------------------------------------------------------------- ②

def demo_policy_compare():
    line("② 三种叫号策略，同一批到达过程")
    cfg = Config()
    ps = build_day()
    _, w_sched, st_s = simulate(ps, cfg, "schedule")
    _, w_fifo, _ = simulate(ps, cfg, "fifo")
    _, w_asst, st_a = simulate(ps, cfg, "assisted")

    rows = [("现状 · 按号序叫号", metrics("x", w_sched), st_s["missed_calls"]),
            ("建议策略 · 复核后", metrics("x", w_asst), st_a["missed_calls"]),
            ("参考线 · 纯先到先看", metrics("x", w_fifo), 0)]
    print(f"  {'策略':<20}{'中位':>8}{'P90':>8}{'均值':>8}{'最长':>8}{'叫空号':>8}")
    for label, m, miss in rows:
        print(f"  {label:<18}{m.median_wait:>8.1f}{m.p90_wait:>8.1f}"
              f"{m.avg_wait:>8.1f}{m.max_wait:>8.1f}{miss:>8}")

    a = rows[0][1].avg_wait
    b = rows[1][1].avg_wait
    print(f"\n  平均候诊 {(b - a) / a * 100:+.1f}%，叫空号从 "
          f"{rows[0][2]} 次降到 {rows[1][2]} 次。")
    print("""
  这里有个容易踩的坑，值得单独说：

    在"医生从不空等"的假设下，
        Σ等待时间 = Σ开始时刻 − Σ到达时刻
    是一个与排序方式**无关**的常数。
    也就是说：纯排序只能把等待从一群人转移给另一群人，谁都不欠谁。
    真正能压低总量的，只有减少叫号空转这类**吞吐损失**，
    这正是"按号序叫号"和"动态排序"之间的差距来源。

  所以：中位数的下降有一部分是转移，均值的下降才是净收益。汇报时说均值。""")


# ---------------------------------------------------------------- ③

def demo_starvation():
    line("③ 让位保护：为什么必须有它")
    cfg = Config()
    p = next(x for x in build_day() if x.appt_id == "A100")

    for waiting, label in ((0, "刚开始等"), (50, "已经等了 50 分钟")):
        now = p.checkin_min + waiting
        ctx = RuleContext(now_min=now, late_grace_min=cfg.late_grace_min,
                          overrun_min=cfg.overrun_min,
                          vulnerable_age_high=75, vulnerable_age_low=6,
                          defer_protect_min=cfg.defer_protect_min)
        codes = [r.code for r in evaluate(p, ctx)]
        print(f"  {label}：命中 {codes or '无'} → "
              f"{'仍然让出波次' if 'LATE_ARRIVAL' in codes else '回到正常次序'}")

    print(f"""
  保护阈值 defer_protect_min = {cfg.defer_protect_min} 分钟。
  没有这条规则时，回放里出现过单个患者被推到 200 分钟以上 ——
  迟到的人永远排不上，护士就得一遍遍解释"再等等"。
  这不是给迟到者的奖励，是把现状里最费口舌的那件事制度化。""")


# ---------------------------------------------------------------- ④

def demo_emergency():
    line("④ 急症：系统唯一会做的事是让路")
    p = next(x for x in build_day() if x.appt_id == "B102")
    ctx = make_ctx(Config(), "09:00")
    for r in evaluate(p, ctx):
        print(f"  [{r.code}] {r.label}（需人工确认：{'是' if r.requires_human else '否'}）")
        print(f"    依据：{r.evidence}")
        print(f"    动作：{r.action}")
    print(f"\n  优先级带 = {band_of(evaluate(p, ctx))} —— 不参与排序，结构性地让出去。")
    print("  注意 engine 里没有任何一处把 emergency 的权重拿去和普通患者比大小：")
    print("  一旦允许比分，就等于承认某种情况下预约顺序可以压过临床优先级（事实 f40 禁止）。")


# ---------------------------------------------------------------- ⑤

def demo_audit():
    line("⑤ 审计：出了问题能不能重建当时现场？")
    cfg = Config()
    snap = snapshot_at(build_day(), cfg, "assisted", at="09:00")

    with tempfile.TemporaryDirectory() as d:
        log = AuditLog(os.path.join(d, "audit.jsonl"), "snapshot-09:00")
        for s in snap.suggestions:
            log.suggest(s.patient.appt_id,
                        s.reasons[0].code if s.reasons else "NONE",
                        note=s.reasons[0].evidence if s.reasons else "按号序接诊")
        first = snap.suggestions[0].patient.appt_id
        log.record(first, "accept", "护士-林亦舟", "REVIEWED", "已向患者说明次序")
        log.suggest("B102", "EMERGENCY")
        log.record("B102", "escalate", "护士-林亦舟", "EMERGENCY", "按院方流程转诊")

        print(f"按业务编号 {first} 重建链路：")
        for c in replay_chain(log.read(), first):
            print(f"  {c['at']}  {c['action']:<8} {c['operator']:<10} "
                  f"{c['reason_code']:<14} {c['prev_status'] or '（首次）'} → {c['status']}")

        print("\n  系统只产出 PENDING，最终状态只能由人产生。重复复核会被拒绝：")
        try:
            log.record(first, "reject", "护士-林亦舟", "REVIEWED")
        except ValueError as e:
            print(f"  ValueError: {e}")


def main() -> int:
    print(BAR)
    print("  clinic-triage-copilot · 最小示例")
    print("  做的事：次序建议。不做的事：诊断、写回、替医生决策。")
    print(BAR)
    demo_one_suggestion()
    demo_policy_compare()
    demo_starvation()
    demo_emergency()
    demo_audit()
    print(f"\n{BAR}\n  完整看板：python -m clinic_triage.main demo → out/dashboard.html\n{BAR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
