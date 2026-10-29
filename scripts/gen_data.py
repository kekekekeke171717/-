#!/usr/bin/env python3
"""生成合成预约数据（不含任何真实患者信息）。

为什么是"合成"而不是"脱敏真实数据"：
- 事实 f43：本轮评价记录保留 90 天，期满由质控复核删除；
- 事实 f45：审计不记录账号口令或不必要的个人信息。
所以仓库里不该出现任何真实记录，哪怕脱敏过。

场景参数来自访谈事实：
- 日均 1600 人次、导诊每日约 180 次排队咨询（f12 / f51）；
- 候诊中位数 68 分钟、爽约率 19%（f00）；
- 两套门诊并行试点，不替换现有业务（f02 / f05）。

本文件抽样"两个门诊 × 两位医生 × 一个上午"共约 116 条，用于回放演练。
回放产出的 fifo 基线候诊中位数在 60 分钟量级 —— 量级对齐访谈，绝对值不可当结论。

末尾会**故意注入 3 条脏数据**（重复签到 / 年龄越界 / 缺接诊时长），
用来演示 utils/quality.py 的拦截效果。生产接入时这一段必须删掉。

用法：python3 scripts/gen_data.py
"""
from __future__ import annotations

import csv
import os
import random

SEED = 20261029
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "appointments.csv")

DEPTS = [
    ("内科门诊", ["王砚医生", "李文迪医生"]),
    ("儿科门诊", ["赵晗医生", "周予医生"]),
]
# 一个上午的号源：08:00 起每 8 分钟一个号，接诊 10–14 分钟 → 队列必然堆积，
# 这与"候诊中位 68 分钟"的现场描述在同一量级。
SESSIONS = [("08:00", "11:50", 8)]
EARLY = (-20, 10)        # 准时/早到者的签到偏移（分钟）
LATE_RANGE = (16, 45)    # 迟到者的签到偏移
LATE_RATE = 0.18         # 迟到率，回放后 >15 分钟宽限外的即为迟到者
WALKIN_RATE = 0.07       # 现场加号占比
COMEBACK_RATE = 0.06     # 检查后回诊占比
NOSHOW_RATE = 0.19       # 爽约率：访谈给的业务基线就是 19%（f00）
EMERGENCY_RATE = 0.06    # 09:20 之后号源的急症出现概率
CONSULT_RANGE = (10, 14)  # 单人接诊时长

NOTES = ["", "", "", "复诊取报告", "老年患者需陪护", "儿童发热", "行动不便", ""]


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def build_rows() -> list[dict]:
    rnd = random.Random(SEED)
    rows: list[dict] = []
    idx = 0
    for dept, doctors in DEPTS:
        for doctor in doctors:
            for start, end, step in SESSIONS:
                h, mi = map(int, start.split(":"))
                cur = h * 60 + mi
                stop = int(end.split(":")[0]) * 60 + int(end.split(":")[1])
                # 每位医生固定抽 2 个号位做急症 —— 不用概率，是因为纯随机容易
                # 全挤到中午：那样 09:20 的默认快照就看不到 EMERGENCY 这条带，
                # 而"急症必转人工"恰恰是本项目最不能缺的演示。
                emg_slots = set(rnd.sample(range(5, 24), 2))
                slot = 0
                while cur <= stop:
                    idx += 1
                    late = rnd.random() < LATE_RATE
                    offset = (rnd.randint(*LATE_RANGE) if late
                              else rnd.randint(*EARLY))
                    kind = "预约"
                    r = rnd.random()
                    if r < WALKIN_RATE:
                        kind = "加号"
                        offset = rnd.randint(-10, 30)
                    elif r < WALKIN_RATE + COMEBACK_RATE:
                        kind = "回诊"
                    peds = dept.startswith("儿科")
                    age = rnd.randint(1, 12) if peds else rnd.randint(18, 88)
                    vulnerable = (age >= 75) or (age <= 6 and peds)
                    no_show = kind == "预约" and rnd.random() < NOSHOW_RATE
                    emergency = slot in emg_slots and not no_show
                    slot += 1
                    rows.append({
                        "appt_id": f"A{idx:04d}",
                        "dept": dept,
                        "doctor": doctor,
                        "appt_time": hhmm(cur),
                        "checkin_time": "" if no_show else hhmm(max(7 * 60 + 30, cur + offset)),
                        "kind": kind,
                        "age": age,
                        "vulnerable": 1 if vulnerable else 0,
                        "emergency": 1 if emergency else 0,
                        "triage_level": 1 if emergency else (2 if vulnerable else rnd.choice([3, 3, 4])),
                        "consult_min": rnd.randint(*CONSULT_RANGE),
                        "note": (rnd.choice(NOTES) if not emergency
                                 else "主诉胸闷、面色苍白，需优先处理"),
                    })
                    cur += step
    return rows


def inject_dirty(rows: list[dict]) -> list[dict]:
    """故意掺 3 条脏数据 —— 只为了让 quality.check 有东西可拦。"""
    dirty = []
    dup = dict(rows[2])                       # 重复签到：同一业务编号再来一条
    dup["checkin_time"] = hhmm(int(dup["appt_time"][:2]) * 60
                               + int(dup["appt_time"][3:]) + 22)
    dirty.append(dup)
    bad_age = dict(rows[5]); bad_age["age"] = 0        # 年龄越界
    dirty.append(bad_age)
    no_consult = dict(rows[9]); no_consult["consult_min"] = 0   # 缺接诊时长
    dirty.append(no_consult)
    return rows + dirty


def main() -> int:
    rows = build_rows()
    clean = len(rows)
    rows = inject_dirty(rows)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def mins(t: str) -> int:
        return int(t[:2]) * 60 + int(t[3:]) if t else -1

    late = sum(1 for r in rows if r["checkin_time"] and
               mins(r["checkin_time"]) - mins(r["appt_time"]) > 15)
    walkin = sum(1 for r in rows if r["kind"] == "加号")
    back = sum(1 for r in rows if r["kind"] == "回诊")
    emergency = sum(1 for r in rows if r["emergency"] == 1)
    no_show = sum(1 for r in rows if not r["checkin_time"])

    print(f"生成 {len(rows)} 条（含 3 条故意脏数据） -> {OUT}")
    print(f"  有效 {clean} 条：迟到 {late} / 加号 {walkin} / 回诊 {back} / "
          f"急症 {emergency} / 未签到 {no_show}")
    print("  这 3 条脏数据会被 quality.check 标为「阻断」或「提示」，")
    print("  接入真实数据时请删掉 inject_dirty()。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
