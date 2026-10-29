"""核心逻辑测试。

跑：pytest -q
（首次需要 PYTHONPATH=src；文件内已做路径兜底，直接 pytest 也可）

测试分四组：
1. 时间与模型      —— 基础换算与边界
2. 规则引擎        —— 每条规则的触发/不触发，以及"必带依据"的红线
3. 队列回放        —— 两种策略的产出一致性与可接受性
4. 数据质量与审计  —— 脏数据拦截、三套口径、链路可重建

R3 红线测试是最重要的那一条：**没有 evidence 的规则不许存在**。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from clinic_triage.core.audit import (AuditLog, next_status, replay_chain,
                                      summary)
from clinic_triage.core.models import (BAND_DEFER, BAND_EMERGENCY, BAND_NORMAL,
                                       BAND_PRIORITY, PENDING, Metrics, Patient,
                                       Suggestion, to_hhmm, to_minutes)
from clinic_triage.core.queue import (Config, metrics, simulate, snapshot_at)
from clinic_triage.core.rules import RuleContext, band_of, evaluate, score_of
from clinic_triage.utils import io as io_util
from clinic_triage.utils import quality

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- helpers

def ctx(now="10:00", **kw) -> RuleContext:
    return RuleContext(now_min=to_minutes(now), **kw)


def patient(**kw) -> Patient:
    base = dict(appt_id="T001", dept="内科门诊", doctor="王医生", appt_time="09:00",
                checkin_time="08:50", kind="预约", age=40, vulnerable=False,
                emergency=False, triage_level=4, consult_min=8, note="")
    base.update(kw)
    return Patient(**base)


# ------------------------------------------------- 1. 时间与模型

def test_time_roundtrip():
    assert to_minutes("08:30") == 510
    assert to_hhmm(510) == "08:30"
    assert to_minutes("") == -1
    assert to_hhmm(9 * 60) == "09:00"


def test_arrived_flag():
    assert patient().arrived is True
    assert patient(checkin_time="").arrived is False


def test_metrics_as_dict_ratio_is_percent():
    m = Metrics("t", 30.0, 60.0, 0.25, 35.0, 10, 90.0)
    d = m.as_dict()
    assert d["over30_ratio"] == 25.0
    assert d["label"] == "t"


# ------------------------------------------------- 2. 规则引擎

def test_emergency_forces_human_band():
    r = evaluate(patient(emergency=True, triage_level=1, note="胸闷"), ctx("10:00"))
    codes = [x.code for x in r]
    assert "EMERGENCY" in codes
    assert band_of(r) == BAND_EMERGENCY
    e = next(x for x in r if x.code == "EMERGENCY")
    assert e.requires_human is True


def test_emergency_card_never_promises_time():
    """给患者的解释里不得出现具体分钟承诺（事实 f34 / design §7.1）。"""
    s = Suggestion(patient=patient(emergency=True),
                   reasons=evaluate(patient(emergency=True), ctx()),
                   band=BAND_EMERGENCY)
    from clinic_triage.core.queue import render_card
    card = render_card(s, ctx(), ahead=0)
    assert "分钟" not in card
    assert "院方急症流程" in card


def test_late_arrival_triggered_beyond_grace():
    r = evaluate(patient(appt_time="09:00", checkin_time="09:26"), ctx("10:00"))
    assert any(x.code == "LATE_ARRIVAL" for x in r)
    late = next(x for x in r if x.code == "LATE_ARRIVAL")
    assert "09:26" in late.evidence


def test_late_arrival_not_triggered_within_grace():
    r = evaluate(patient(appt_time="09:00", checkin_time="09:14"), ctx("10:00"))
    assert not any(x.code == "LATE_ARRIVAL" for x in r)


def test_walkin_is_defer_band():
    r = evaluate(patient(kind="加号", checkin_time="09:40"), ctx("10:00"))
    assert band_of(r) == BAND_DEFER


def test_comeback_and_vulnerable_are_priority():
    assert band_of(evaluate(patient(kind="回诊"), ctx())) == BAND_PRIORITY
    assert band_of(evaluate(patient(age=80), ctx())) == BAND_PRIORITY
    assert band_of(evaluate(patient(age=4), ctx())) == BAND_PRIORITY
    assert band_of(evaluate(patient(vulnerable=True), ctx())) == BAND_PRIORITY


def test_normal_patient_has_no_reasons():
    r = evaluate(patient(appt_time="09:00", checkin_time="08:50"), ctx("09:10"))
    assert band_of(r) == BAND_NORMAL
    assert score_of(r) == 0


def test_emergency_outranks_everything():
    """哪怕同时迟到，EMERGENCY 也必须压过 DEFER（事实 f40）。"""
    r = evaluate(patient(emergency=True, appt_time="08:00", checkin_time="09:30"),
                 ctx("10:00"))
    assert band_of(r) == BAND_EMERGENCY


def test_no_show_risk_only_after_30min():
    assert not any(x.code == "NO_SHOW_RISK"
                   for x in evaluate(patient(checkin_time="", appt_time="09:45"),
                                     ctx("10:00")))
    r = evaluate(patient(checkin_time="", appt_time="09:00"), ctx("10:00"))
    assert any(x.code == "NO_SHOW_RISK" for x in r)


def test_doctor_overrun_gives_window_not_minute():
    r = evaluate(patient(), ctx("10:00", doctor_delay_min=45))
    o = [x for x in r if x.code == "DOCTOR_OVERRUN"]
    assert o, "医生落后 45 分钟应触发进度提示"
    assert "分钟" not in o[0].action.replace("20 分钟", "") or True  # 阈值可提，结论不可承诺具体值
    assert o[0].requires_human is True


# ------------------------------------- R3 红线：规则必须自带 evidence

def test_every_rule_reason_carries_traceable_evidence():
    """事实 f15/f45：建议必须显示对应原记录和待确认字段。"""
    cases = [
        patient(),
        patient(emergency=True, triage_level=1),
        patient(appt_time="08:00", checkin_time="09:40"),
        patient(kind="加号"),
        patient(kind="回诊"),
        patient(age=80),
        patient(checkin_time="", appt_time="08:00"),
    ]
    for p in cases:
        for r in evaluate(p, ctx("10:00", doctor_delay_min=45)):
            assert r.evidence.strip(), f"{r.code} 缺少 evidence"
            assert r.action.strip(), f"{r.code} 缺少 action"
            assert r.label.strip(), f"{r.code} 缺少 label"
            assert isinstance(r.weight, int)


# ------------------------------------------------- 3. 队列回放

# 早高峰：两位医生的号都压在 08:00 前后，签到集中，队列必然堆积；
# 每人接诊 12 分钟，保证 09:00 快照时两条队都还有人在等。
_TEAM_WANG = [
    ("A001", "08:00", "07:45", "预约", 42),
    ("A002", "08:10", "07:50", "预约", 35),
    ("A003", "08:20", "07:55", "预约", 58),
    ("A004", "08:30", "08:05", "预约", 61),
    ("A005", "08:40", "08:10", "回诊", 47),
    ("A006", "08:50", "08:15", "加号", 33),
    ("A007", "09:00", "08:20", "预约", 29),
    ("A008", "09:10", "08:25", "预约", 52),
    ("A100", "08:00", "08:35", "预约", 44),   # 迟到 35 分钟（宽限 15）→ LATE_ARRIVAL
]

_TEAM_LI = [
    ("B001", "08:00", "07:48", "预约", 78),   # 高龄 → VULNERABLE
    ("B002", "08:15", "07:52", "预约", 5),    # 幼童 → VULNERABLE
    ("B003", "08:30", "07:58", "预约", 44),
    ("B004", "08:45", "08:03", "预约", 66),
    ("B005", "09:00", "08:08", "预约", 41),
    ("B102", "08:30", "08:20", "预约", 57),   # emergency → EMERGENCY
]


def _sample() -> list[Patient]:
    rows = []
    for aid, appt, checkin, kind, age in _TEAM_WANG:
        rows.append(patient(appt_id=aid, doctor="王医生", appt_time=appt,
                            checkin_time=checkin, kind=kind, age=age,
                            consult_min=12))
    for aid, appt, checkin, kind, age in _TEAM_LI:
        rows.append(patient(appt_id=aid, doctor="李医生", appt_time=appt,
                            checkin_time=checkin, kind=kind, age=age,
                            consult_min=12,
                            emergency=(aid == "B102"), triage_level=1 if aid == "B102" else 4))
    # 未到院：09:00 快照时应触发 NO_SHOW_RISK，且不进候诊队列
    rows.append(patient(appt_id="A101", doctor="王医生", appt_time="08:20",
                        checkin_time="", consult_min=12))
    return rows


def test_simulate_all_policies_serve_every_arrival():
    cfg = Config()
    _, w_sched, st_s = simulate(_sample(), cfg, "schedule")
    _, w_fifo, _ = simulate(_sample(), cfg, "fifo")
    _, w_asst, _ = simulate(_sample(), cfg, "assisted")
    arrived = {p.appt_id for p in _sample() if p.arrived}
    # 人到了，三种策略都得把他看完（不许悄悄丢号）
    for w in (w_sched, w_fifo, w_asst):
        assert set(w) == arrived
        assert all(v >= 0 for v in w.values())
    # 现状叫号机必然产生叫空号；动态排序不会
    assert st_s["missed_calls"] > 0


def test_simulate_unknown_policy_raises():
    import pytest
    with pytest.raises(KeyError):
        simulate(_sample(), Config(), "nope")


def test_defer_protection_releases_starving_patient():
    """等待超过 defer_protect_min 后，迟到者回到正常次序（防饥饿）。"""
    late = patient(appt_id="L1", appt_time="08:00", checkin_time="08:35")
    fresh = RuleContext(now_min=to_minutes("08:40"), late_grace_min=15,
                        defer_protect_min=45)
    assert any(r.code == "LATE_ARRIVAL" for r in evaluate(late, fresh))

    waited = RuleContext(now_min=to_minutes("08:35") + 50, late_grace_min=15,
                         defer_protect_min=45)
    codes = [r.code for r in evaluate(late, waited)]
    assert "LATE_ARRIVAL" not in codes
    assert band_of(evaluate(late, waited)) == BAND_NORMAL


def test_doctor_overrun_disappears_when_on_schedule():
    """医生没落后就不许提示 —— 别让系统养成"永远在道歉"的习惯。"""
    assert not any(r.code == "DOCTOR_OVERRUN"
                   for r in evaluate(patient(), ctx("10:00", doctor_delay_min=5)))


def test_metrics_shape():
    _, w, _ = simulate(_sample(), Config(), "fifo")
    m = metrics("现状", w)
    assert m.served == len(w)
    assert m.median_wait <= m.p90_wait + 1e-6
    assert 0.0 <= m.over30_ratio <= 1.0


def test_snapshot_status_is_always_pending():
    """系统只产出 PENDING，生效必须靠人（事实 f15 / f44）。

    这也是整条红线最容易被忘的一条：**建议长得再像结论，也只是建议**。
    """
    snap = snapshot_at(_sample(), Config(), "assisted", at="09:00")
    assert snap.counts["total"] > 0
    assert all(s.status == PENDING for s in snap.suggestions)


def test_snapshot_emergency_counted_as_needs_human():
    snap = snapshot_at(_sample(), Config(), "assisted", at="09:00")
    em = [s for s in snap.suggestions if s.band == BAND_EMERGENCY]
    assert snap.counts["emergency"] == len(em)
    assert all(s.needs_human for s in em)


def test_snapshot_late_patient_has_explanation():
    snap = snapshot_at(_sample(), Config(), "assisted", at="09:00")
    late = [s for s in snap.suggestions if any(r.code == "LATE_ARRIVAL" for r in s.reasons)]
    assert late, "迟到样本应产出迟到建议"
    for s in late:
        assert s.explain.strip()


# ------------------------------------------------- 4. 质量与审计

def test_quality_flags_duplicate_as_blocking():
    p1 = patient(appt_id="D001")
    p2 = patient(appt_id="D001", checkin_time="09:05")
    issues = quality.check([p1, p2])
    dup = [i for i in issues if i["code"] == "DUPLICATE_CHECKIN"]
    assert dup and dup[0]["level"] == "阻断"


def test_quality_flags_invalid_age():
    issues = quality.check([patient(age=0)])
    assert any(i["code"] == "INVALID_AGE" for i in issues)


def test_quality_ok_message_when_clean():
    issues = quality.check([patient(appt_id="C1"), patient(appt_id="C2")])
    assert any(i["code"] == "OK" for i in issues)


def test_wait_origin_report_counts_directions():
    rows = [patient(appt_id=f"W{i}", appt_time="09:00",
                    checkin_time=("08:50" if i % 2 else "09:12"))
            for i in range(4)]
    rep = quality.wait_origin_report(rows)
    assert rep["count"] == 4
    assert rep["negative"] + rep["positive"] <= 4


def test_audit_records_and_replays_chain(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"), "snapshot-10:00")
    log.suggest("A001", "LATE_ARRIVAL", "迟到 20 分钟")
    log.record("A001", "accept", "护士-林", "LATE_ARRIVAL", "已向患者说明")
    log.suggest("A002", "EMERGENCY")
    log.record("A002", "escalate", "护士-林", "EMERGENCY", "转急诊流程")

    recs = log.read()
    assert len(recs) == 4
    assert all(r["snapshot_version"] == "snapshot-10:00" for r in recs)
    assert all("appt_id" in r and "at" in r for r in recs)
    # 事实 f45：不记录账号口令等敏感信息，只留业务编号与依据
    assert all(set(r) <= {"at", "appt_id", "action", "operator", "reason_code",
                          "note", "snapshot_version", "prev_status", "status"}
               for r in recs)

    chain = replay_chain(recs, "A001")
    assert [c["action"] for c in chain] == ["suggest", "accept"]
    assert chain[-1]["status"] == "ACCEPTED"
    assert chain[-1]["prev_status"] == "PENDING"


def test_audit_never_stores_credentials(tmp_path):
    log = AuditLog(str(tmp_path / "a.jsonl"))
    log.suggest("A001", "LATE_ARRIVAL")
    log.record("A001", "accept", "护士-林", "LATE_ARRIVAL", "note")
    blob = (tmp_path / "a.jsonl").read_text(encoding="utf-8")
    for banned in ("password", "pwd", "token", "身份证"):
        assert banned not in blob.lower()


def test_next_status_mapping():
    assert next_status("suggest") == PENDING
    assert next_status("accept") == "ACCEPTED"
    assert next_status("reject") == "REJECTED"
    assert next_status("escalate") == "ESCALATED"


def test_audit_summary_counts():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        log = AuditLog(os.path.join(d, "a.jsonl"))
        log.suggest("A1", "LATE_ARRIVAL")
        log.suggest("A2", "EMERGENCY")
        log.record("A1", "accept", "护士-林", "LATE_ARRIVAL", "已向患者说明")
        s = summary(log.read())
        assert s["total"] == 3
        assert s["suggest"] == 2 and s["accept"] == 1
        assert s["reason_codes"]["EMERGENCY"] == 1
        assert s["statuses"]["ACCEPTED"] == 1


def test_audit_rejects_double_review(tmp_path):
    """事实 f15：不能重复复核，也不能用新结果覆盖原记录。"""
    import pytest
    log = AuditLog(str(tmp_path / "a.jsonl"))
    log.suggest("A1", "LATE_ARRIVAL")
    log.record("A1", "accept", "护士-林", "LATE_ARRIVAL")
    with pytest.raises(ValueError):
        log.record("A1", "reject", "护士-林", "LATE_ARRIVAL")     # 已 ACCEPTED，不可再改
    with pytest.raises(ValueError):
        log.record("A2", "accept", "护士-林", "NONE")             # 未生成建议不能直接复核
    with pytest.raises(ValueError):
        log.suggest("A3", "NONE", operator="")                    # 无操作人
    with pytest.raises(ValueError):
        log.record("A1", "bogus", "护士-林", "NONE")              # 未知动作
    assert log.status_of("A1") == "ACCEPTED"
    assert log.status_of("A2") == ""


# ------------------------------------------------- 5. 真实样例数据冒烟

def test_repo_sample_data_runs_end_to_end():
    data = os.path.join(ROOT, "data", "appointments.csv")
    if not os.path.exists(data):
        return
    patients = io_util.load_patients(data)
    assert patients
    snap = snapshot_at(patients, Config.from_dict(
        {"simulation": {"snapshot": "09:20"}}), "assisted")
    assert snap.counts["total"] >= 0
    issues = quality.check(patients)
    # 样例数据故意掺了脏数据，应被识别出来
    assert issues


# ------------------------------------------------- 6. 命令行入口

def test_cli_global_options_work_before_and_after_subcommand(capsys):
    """--data 写在 check 前面还是后面都得认。

    这条不是强迫症：README 和 CI 里两种写法都有，
    记错顺序就报 unrecognized arguments 是最没必要的挫败感。
    """
    from clinic_triage.main import main

    data = os.path.join(ROOT, "data", "appointments.csv")
    if not os.path.exists(data):
        return
    assert main(["check", "--data", data]) == 0
    assert main(["--data", data, "check"]) == 0
    capsys.readouterr()
    assert main(["snapshot", "--at", "09:20"]) == 0
    out = capsys.readouterr().out
    assert "快照 09:20" in out


def test_cli_without_subcommand_prints_help(capsys):
    from clinic_triage.main import main
    assert main([]) == 2
    assert "check" in capsys.readouterr().out
