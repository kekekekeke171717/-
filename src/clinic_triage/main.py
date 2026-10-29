"""门诊预约与分诊协作助手 · 入口。

用法：
    python -m clinic_triage.main demo      # 回放 + 生成看板与建议清单
    python -m clinic_triage.main snapshot  # 只打印某一时刻的建议队列
    python -m clinic_triage.main check     # 只做数据质量检查
    python -m clinic_triage.main serve     # 启动本地预览（127.0.0.1:8765）

所有输出都写在 out/ 下，不触碰任何业务系统。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

if __package__ in (None, ""):  # 允许 python src/clinic_triage/main.py 直接运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clinic_triage.core.audit import AuditLog, summary
from clinic_triage.core.models import to_hhmm
from clinic_triage.core.queue import Config, metrics, simulate, snapshot_at
from clinic_triage.utils import config as cfg_util
from clinic_triage.utils import io as io_util
from clinic_triage.utils import quality

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _paths(args) -> dict:
    root = args.root or ROOT
    return {
        "root": root,
        "data": args.data or os.path.join(root, "data", "appointments.csv"),
        "out": args.out or os.path.join(root, "out"),
        "cfg": args.config or os.path.join(root, "config", "default.yaml"),
    }


def _load(args):
    p = _paths(args)
    raw = cfg_util.load(p["cfg"])
    cfg = Config.from_dict(raw)
    patients = io_util.load_patients(p["data"])
    return p, raw, cfg, patients


def cmd_check(args) -> int:
    p, raw, cfg, patients = _load(args)
    issues = quality.check(patients)
    print(f"记录数 {len(patients)} · 现场 {raw.get('clinic', {}).get('name', '')}")
    for it in issues:
        print(f"[{it['level']}] {it['code']} {it['message']} {it['ids']}")
    gap = quality.wait_origin_report(patients)
    print(f"签到-预约时间差：均值 {gap['avg_gap']} 分钟，"
          f"提前 {gap['negative']} 人 / 迟到 {gap['positive']} 人")
    return 0


def cmd_snapshot(args) -> int:
    p, raw, cfg, patients = _load(args)
    snap = snapshot_at(patients, cfg, policy="assisted", at=args.at)
    print(f"快照 {to_hhmm(snap.at)} · 候诊 {snap.counts['total']} 人 · "
          f"急症转人工 {snap.counts['emergency']} · 待复核 {snap.counts['human']}")
    for s in snap.suggestions:
        tags = " / ".join(r.label for r in s.reasons) or "正常"
        print(f"{s.order:>2}. {s.patient.appt_id} {s.patient.kind:<2} "
              f"{s.patient.doctor:<6} [{tags}] -> {s.reasons[0].action if s.reasons else '按号序'}")
    return 0


def _emergency_stats(patients, waits_sched, waits_asst) -> dict:
    """全天急症回顾 —— 快照里通常看不到他们，因为他们从不排队。

    这才是对的：急症走院方流程，不进排序建议（事实 f40）。
    但审计要能回答"今天有几位、等多久、系统有没有给出时间承诺"。
    """
    import statistics

    flagged = [p for p in patients if p.emergency]
    arrived = [p for p in flagged if p.arrived]

    def med(d: dict) -> float:
        vals = [d[p.appt_id] for p in arrived if p.appt_id in d]
        return round(statistics.median(vals), 1) if vals else 0.0

    return {
        "flagged": len(flagged),
        "arrived": len(arrived),
        "ids": [p.appt_id for p in arrived][:8],
        "schedule_wait": med(waits_sched),
        "assisted_wait": med(waits_asst),
        "advice": "全部按院方流程转人工处理，系统未提供任何时间承诺",
    }


def cmd_demo(args) -> int:
    p, raw, cfg, patients = _load(args)
    os.makedirs(p["out"], exist_ok=True)

    _, waits_sched, st_sched = simulate(patients, cfg, "schedule")
    _, waits_asst, st_asst = simulate(patients, cfg, "assisted")
    _, waits_fifo, _ = simulate(patients, cfg, "fifo")
    sched = metrics("现状·按号序叫号", waits_sched)
    asst = metrics("建议策略·复核后", waits_asst)
    upper = metrics("参考线·纯先到先看", waits_fifo)

    snap = snapshot_at(patients, cfg, policy="assisted", at=args.at)
    version = f"snapshot-{to_hhmm(snap.at)}"

    audit = AuditLog(os.path.join(p["out"], "audit.jsonl"), version)
    io_util.write_suggestions(os.path.join(p["out"], "suggestions.csv"), snap.suggestions)

    # 事实 f45：每条建议都必须先留痕，才能谈复核 —— 系统的痕迹从这里开始
    for s in snap.suggestions:
        audit.suggest(s.patient.appt_id,
                      s.reasons[0].code if s.reasons else "NONE",
                      note=s.reasons[0].evidence if s.reasons else "按号序接诊")

    rule_counts: dict[str, int] = {}
    for s in snap.suggestions:
        for r in s.reasons:
            rule_counts[r.label] = rule_counts.get(r.label, 0) + 1
    rule_counts = dict(sorted(rule_counts.items(), key=lambda kv: -kv[1]))

    io_util.render_dashboard(os.path.join(p["out"], "dashboard.html"), {
        "clinic": raw.get("clinic", {}).get("name", "东湖门诊中心"),
        "snapshot": to_hhmm(snap.at),
        "version": version,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "suggestions": snap.suggestions,
        "counts": snap.counts,
        "replay": {"schedule": sched.as_dict(), "assisted": asst.as_dict(),
                   "fifo": upper.as_dict()},
        "missed_calls": {"schedule": st_sched["missed_calls"],
                         "assisted": st_asst["missed_calls"]},
        "quality": quality.check(patients),
        "rule_counts": rule_counts or {"无异常": snap.counts["total"]},
        "audit": summary(audit.read()),
        "emergency": _emergency_stats(patients, waits_sched, waits_asst),
    })

    io_util.write_report(os.path.join(p["out"], "replay.json"), {
        "config": {"snapshot": to_hhmm(snap.at), "policy": "assisted"},
        "schedule": sched.as_dict(),
        "assisted": asst.as_dict(),
        "fifo": upper.as_dict(),
        "missed_calls": {"schedule": st_sched["missed_calls"],
                         "assisted": st_asst["missed_calls"]},
        "counts": snap.counts,
        "rules": rule_counts,
        "audit_summary": summary(audit.read()),
    })

    def row(m):
        return (f"  {m.label:<16} 中位 {m.median_wait:5.1f}  P90 {m.p90_wait:5.1f}  "
                f"均值 {m.avg_wait:5.1f}  超30分 {m.over30_ratio * 100:4.1f}%  "
                f"最长 {m.max_wait:6.1f}")

    print("回放对比（同一批到达过程，单位为分钟）")
    print(row(sched))
    print(row(asst))
    print(row(upper))
    dm = (asst.median_wait - sched.median_wait) / sched.median_wait * 100
    am = (asst.avg_wait - sched.avg_wait) / sched.avg_wait * 100
    gap_raw = asst.avg_wait - upper.avg_wait
    gap = -gap_raw if gap_raw < 0 else gap_raw
    print(f"  中位候诊 {dm:+.1f}% · 平均候诊 {am:+.1f}%"
          "（事实 f02 的验收口径：候诊等待时间下降 20%）")
    print(f"  平均候诊与参考线相差 {gap:.1f} 分钟/人 —— 在「医生不空等」的前提下，"
          "总等待时间不受排序影响，")
    print("  收益来自少叫几次空号；再往下要压降，只能加号源或改排班，而不是继续调规则。")
    print(f"  叫空号：现状 {st_sched['missed_calls']} 次 → 建议策略 {st_asst['missed_calls']} 次")
    print("  ⚠ 回放只用于方案对比与方法验证，不等于试点结论。")
    print(f"\n快照 {to_hhmm(snap.at)}：候诊 {snap.counts['total']} 人，"
          f"急症转人工 {snap.counts['emergency']} 条，待复核 {snap.counts['human']} 条")
    print("输出：")
    for name in ("dashboard.html", "suggestions.csv", "replay.json", "audit.jsonl"):
        fp = os.path.join(p["out"], name)
        if os.path.exists(fp):
            print(f"  - {fp} ({os.path.getsize(fp) // 1024} KB)")
    return 0


def cmd_serve(args) -> int:
    import functools
    import http.server
    import socketserver

    p = _paths(args)
    dashboard = os.path.join(p["out"], "dashboard.html")
    if not os.path.exists(dashboard):
        cmd_demo(args)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=p["out"])
    port = args.port
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"看板已启动： http://127.0.0.1:{port}/dashboard.html   （Ctrl+C 结束）")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


def _common_args() -> argparse.ArgumentParser:
    """全局参数放在子命令前或后都要能写 —— 不然记错顺序就报 unrecognized。

    default=SUPPRESS 是关键：子命令没写这个参数时，不要拿 None 覆盖
    前面已经给过的值。
    """
    ap = argparse.ArgumentParser(add_help=False)
    for name, help_text in (("--data", "预约数据 CSV 路径"),
                            ("--config", "配置文件路径"),
                            ("--out", "输出目录"),
                            ("--root", "项目根目录")):
        ap.add_argument(name, default=argparse.SUPPRESS, help=help_text)
    return ap


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="clinic-triage",
                                 description="门诊预约与分诊协作助手（MVP）")
    ap.add_argument("--data", help="预约数据 CSV 路径")
    ap.add_argument("--config", help="配置文件路径")
    ap.add_argument("--out", help="输出目录")
    ap.add_argument("--root", help="项目根目录")
    common = _common_args()
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="回放并生成看板", parents=[common])
    d.add_argument("--at", help="快照时刻，如 09:20")
    d.set_defaults(func=cmd_demo)
    s = sub.add_parser("snapshot", help="打印某时刻建议队列", parents=[common])
    s.add_argument("--at", help="快照时刻，如 09:20")
    s.set_defaults(func=cmd_snapshot)
    c = sub.add_parser("check", help="数据质量检查", parents=[common])
    c.set_defaults(func=cmd_check)
    v = sub.add_parser("serve", help="本地预览看板", parents=[common])
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--at", help="快照时刻")
    v.set_defaults(func=cmd_serve)
    return ap


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
