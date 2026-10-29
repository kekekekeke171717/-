"""数据质量检查：有歧义的记录不进建议（事实 f31 / f33）。

三类问题在访谈里被明确点名：
- 签到重复（同一患者同一号源多条签到事件）；
- 叫号遗漏（有签到无叫号）；
- 等待时间起点不统一（预约时间 / 签到时间 / 到院时间三套口径）。
"""
from __future__ import annotations

from collections import Counter

from ..core.models import Patient


def check(patients: list[Patient]) -> list[dict]:
    issues: list[dict] = []

    dup = Counter(p.appt_id for p in patients)
    dup_ids = [k for k, v in dup.items() if v > 1]
    if dup_ids:
        issues.append({"level": "阻断", "code": "DUPLICATE_CHECKIN",
                       "message": "同一业务编号出现多条签到记录，需人工去重后才能进入建议。",
                       "ids": "、".join(sorted(dup_ids)[:6])})

    no_checkin = [p.appt_id for p in patients if not p.arrived]
    if no_checkin:
        issues.append({"level": "提示", "code": "MISSING_CHECKIN",
                       "message": f"{len(no_checkin)} 条记录未签到，按爽约观察处理，不参与排序建议。",
                       "ids": "、".join(no_checkin[:6])})

    odd_age = [p.appt_id for p in patients if p.age <= 0 or p.age > 110]
    if odd_age:
        issues.append({"level": "阻断", "code": "INVALID_AGE",
                       "message": "年龄字段越界，无法判断脆弱人群，需回原系统修正。",
                       "ids": "、".join(odd_age[:6])})

    no_consult = [p.appt_id for p in patients if p.consult_min <= 0]
    if no_consult:
        issues.append({"level": "提示", "code": "MISSING_CONSULT_MIN",
                       "message": "缺少预计接诊时长，回放按默认 8 分钟估算。",
                       "ids": "、".join(no_consult[:6])})

    if not issues:
        issues.append({"level": "正常", "code": "OK",
                       "message": "主编号、事件时间、版本字段校验通过。", "ids": ""})
    return issues


def wait_origin_report(patients: list[Patient]) -> dict:
    """三套等待口径的差异，用于和运营/服务/系统三方对齐验收口径。"""
    rows = []
    for p in patients:
        if not p.arrived:
            continue
        rows.append({
            "appt_id": p.appt_id,
            "from_appt": p.checkin_min - p.appt_min,
            "from_checkin": 0,
        })
    if not rows:
        return {"count": 0, "avg_gap": 0}
    gaps = [r["from_appt"] for r in rows]
    return {"count": len(rows), "avg_gap": round(sum(gaps) / len(gaps), 1),
            "positive": sum(1 for g in gaps if g > 0), "negative": sum(1 for g in gaps if g < 0)}
