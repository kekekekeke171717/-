"""读写与展示：CSV 载入、CSV 导出、单文件 HTML 看板。"""
from __future__ import annotations

import csv
import html
import json
import os

from ..core.models import Patient, Suggestion


def load_patients(path: str) -> list[Patient]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append(Patient(
            appt_id=r["appt_id"].strip(),
            dept=r["dept"].strip(),
            doctor=r["doctor"].strip(),
            appt_time=r["appt_time"].strip(),
            checkin_time=(r.get("checkin_time") or "").strip(),
            kind=r["kind"].strip(),
            age=int(r["age"]),
            vulnerable=str(r.get("vulnerable", "0")).strip() in ("1", "true", "True", "是"),
            emergency=str(r.get("emergency", "0")).strip() in ("1", "true", "True", "是"),
            triage_level=int(r.get("triage_level") or 4),
            consult_min=int(r.get("consult_min") or 8),
            note=(r.get("note") or "").strip(),
        ))
    return out


def write_suggestions(path: str, suggestions: list[Suggestion]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["建议次序", "业务编号", "科室", "医生", "号别", "预约时间", "签到时间",
                    "优先级带", "规则依据", "建议动作", "状态", "解释口径"])
        for s in suggestions:
            p = s.patient
            w.writerow([s.order, p.appt_id, p.dept, p.doctor, p.kind, p.appt_time,
                        p.checkin_time, s.band,
                        " / ".join(r.label for r in s.reasons) or "正常排队",
                        s.reasons[0].action if s.reasons else "按号序接诊",
                        s.status, s.explain])


def write_report(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


BAND_STYLE = {
    "EMERGENCY": ("急症·转人工", "tag-red"),
    "PRIORITY": ("优先复核", "tag-amber"),
    "DEFER": ("让出波次", "tag-blue"),
    "NORMAL": ("正常排队", "tag-gray"),
}


def render_dashboard(path: str, ctx: dict) -> None:
    rows = []
    for s in ctx["suggestions"]:
        p = s.patient
        band_label, band_cls = BAND_STYLE.get(s.band, ("待定", "tag-gray"))
        reasons = "".join(
            f'<span class="chip" title="{html.escape(r.evidence)}">{html.escape(r.label)}</span>'
            for r in s.reasons) or '<span class="chip chip-empty">无异常</span>'
        rows.append(f"""
      <tr data-id="{p.appt_id}" data-band="{s.band}" class="row-{s.band.lower()}">
        <td class="num">{s.order}</td>
        <td><div class="pid">{html.escape(p.appt_id)}</div>
            <div class="sub">{html.escape(p.dept)} · {html.escape(p.doctor)}</div></td>
        <td>{html.escape(p.kind)}<div class="sub">预约 {p.appt_time} · 签到 {p.checkin_time or "—"}</div></td>
        <td>{reasons}</td>
        <td class="act">{html.escape(s.reasons[0].action if s.reasons else "按号序接诊")}</td>
        <td><span class="tag {band_cls}">{band_label}</span></td>
        <td class="ops">
          <button class="ok" data-act="accept" data-code="{s.reasons[0].code if s.reasons else 'NONE'}">接受</button>
          <button class="no" data-act="reject" data-code="{s.reasons[0].code if s.reasons else 'NONE'}">驳回</button>
        </td>
      </tr>""")

    replay = ctx["replay"]
    base, asst = replay["schedule"], replay["assisted"]
    upper = replay["fifo"]
    missed = ctx.get("missed_calls", {})
    emg = ctx.get("emergency", {})

    def delta(key):
        b, a = base[key], asst[key]
        d = (a - b) / b * 100 if b else 0
        cls = "down" if d < 0 else "up"
        return f'<span class="{cls}">{d:+.1f}%</span>'

    kpis = f"""
    <div class="kpi"><div class="k-label">候诊中位数（回放）</div>
      <div class="k-value">{asst['median_wait']}<span>分钟</span></div>
      <div class="k-foot">现状 {base['median_wait']} 分钟 · {delta('median_wait')}</div></div>
    <div class="kpi"><div class="k-label">平均候诊（验收口径）</div>
      <div class="k-value">{asst['avg_wait']}<span>分钟</span></div>
      <div class="k-foot">现状 {base['avg_wait']} 分钟 · {delta('avg_wait')}</div></div>
    <div class="kpi"><div class="k-label">叫空号次数</div>
      <div class="k-value">{missed.get('assisted', 0)}<span>次</span></div>
      <div class="k-foot">现状 {missed.get('schedule', 0)} 次 · 每次都会顺延给后面所有人</div></div>
    <div class="kpi"><div class="k-label">待人工复核</div>
      <div class="k-value">{ctx['counts']['human']}<span>条</span></div>
      <div class="k-foot">急症转人工 {ctx['counts']['emergency']} 条 · 全天标记 {emg.get('flagged', 0)} 例</div></div>
    """

    quality = "".join(
        f'<li><b>{html.escape(q["level"])}</b> {html.escape(q["message"])}'
        f'<span class="mono">{html.escape(q["ids"])}</span></li>'
        for q in ctx["quality"]) or "<li>未发现阻断性数据问题。</li>"

    def cmp_row(label, key, unit="分钟", note=""):
        return (f'<tr><td>{label}</td><td>{base[key]}{unit}</td>'
                f'<td><b>{asst[key]}{unit}</b> {note}</td>'
                f'<td>{upper[key]}{unit}</td></tr>')

    compare_rows = "".join([
        cmp_row("候诊中位数", "median_wait"),
        cmp_row("P90 候诊", "p90_wait"),
        cmp_row("平均候诊（验收口径）", "avg_wait", note=delta("avg_wait")),
        cmp_row("超 30 分钟占比", "over30_ratio", unit="%", note=delta("over30_ratio")),
        cmp_row("最长候诊", "max_wait"),
        f'<tr><td>叫空号次数</td><td>{missed.get("schedule", 0)} 次</td>'
        f'<td><b>{missed.get("assisted", 0)} 次</b></td><td>0 次</td></tr>',
    ])
    avg_gap = round(abs(asst["avg_wait"] - upper["avg_wait"]), 1)
    emg_flagged = emg.get("flagged", 0)
    emg_arrived = emg.get("arrived", 0)
    emg_ids = "、".join(emg.get("ids") or []) or "—"
    emg_wait_now = emg.get("schedule_wait", 0)
    emg_wait_new = emg.get("assisted_wait", 0)
    emg_advice = html.escape(emg.get("advice", "—"))

    doc = HTML_TEMPLATE.format(
        clinic=html.escape(ctx["clinic"]),
        snapshot=html.escape(ctx["snapshot"]),
        version=html.escape(ctx["version"]),
        kpis=kpis,
        rows="".join(rows),
        quality=quality,
        compare_rows=compare_rows,
        avg_gap=avg_gap,
        emg_flagged=emg_flagged, emg_arrived=emg_arrived, emg_ids=emg_ids,
        emg_wait_now=emg_wait_now, emg_wait_new=emg_wait_new, emg_advice=emg_advice,
        base_json=json.dumps(base, ensure_ascii=False),
        asst_json=json.dumps(asst, ensure_ascii=False),
        generated=html.escape(ctx["generated"]),
        total=len(ctx["suggestions"]),
        rule_rows="".join(
            f'<tr><td>{html.escape(k)}</td><td class="num">{v}</td></tr>'
            for k, v in ctx["rule_counts"].items()),
    )
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{clinic} · 门诊分诊协作助手（MVP）</title>
<style>
  :root {{
    --bg:#F5F8FC; --card:#FFFFFF; --line:#E3EBF5; --ink:#1B2A3B; --muted:#6B7A90;
    --blue:#2E75B6; --blue-d:#1F4E79; --green:#1F9D74; --amber:#C9861A; --red:#C0392B;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif; font-size:13px; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:22px 20px 40px; }}
  header {{ display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }}
  h1 {{ font-size:19px; margin:0 0 6px; letter-spacing:.3px; }}
  .meta {{ color:var(--muted); font-size:12px; }}
  .badge {{ background:#FFF6E6; border:1px solid #F0D9AE; color:#9A6A12;
    padding:6px 12px; border-radius:999px; font-size:12px; white-space:nowrap; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:18px 0 14px; }}
  .kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px;
    box-shadow:0 1px 2px rgba(27,42,59,.04); }}
  .k-label {{ color:var(--muted); font-size:12px; }}
  .k-value {{ font-size:26px; font-weight:700; color:var(--blue-d); margin:6px 0 4px; }}
  .k-value span {{ font-size:12px; font-weight:400; color:var(--muted); margin-left:4px; }}
  .k-foot {{ font-size:11.5px; color:var(--muted); }}
  .down {{ color:var(--green); font-weight:600; }}
  .up {{ color:var(--red); font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:1fr 300px; gap:14px; align-items:start; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    box-shadow:0 1px 2px rgba(27,42,59,.04); overflow:hidden; }}
  .card h2 {{ font-size:13.5px; margin:0; padding:13px 16px; border-bottom:1px solid var(--line);
    display:flex; justify-content:space-between; align-items:center; }}
  .card h2 small {{ font-weight:400; color:var(--muted); font-size:11.5px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; font-weight:600; color:var(--muted); font-size:11.5px;
    padding:9px 12px; background:#FAFCFE; border-bottom:1px solid var(--line); }}
  td {{ padding:10px 12px; border-bottom:1px solid #F1F5FA; vertical-align:top; }}
  tr:last-child td {{ border-bottom:none; }}
  .num {{ width:34px; color:var(--muted); }}
  .pid {{ font-weight:600; font-size:12.5px; }}
  .sub {{ color:var(--muted); font-size:11px; margin-top:2px; }}
  .chip {{ display:inline-block; background:#EFF5FC; color:var(--blue-d); border:1px solid #DCE8F7;
    border-radius:6px; padding:2px 7px; font-size:11px; margin:1px 4px 1px 0; }}
  .chip-empty {{ background:#F5F7FA; color:var(--muted); border-color:#EDF1F6; }}
  .tag {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; white-space:nowrap; }}
  .tag-red {{ background:#FDECEA; color:var(--red); border:1px solid #F5C6C0; }}
  .tag-amber {{ background:#FFF6E6; color:var(--amber); border:1px solid #F0D9AE; }}
  .tag-blue {{ background:#EFF5FC; color:var(--blue); border:1px solid #D6E5F7; }}
  .tag-gray {{ background:#F4F6F9; color:var(--muted); border:1px solid #E7ECF3; }}
  .act {{ color:#33475B; max-width:210px; }}
  .ops {{ white-space:nowrap; }}
  button {{ font-family:inherit; font-size:11.5px; padding:5px 10px; border-radius:6px;
    border:1px solid #D6E5F7; background:#fff; color:var(--blue); cursor:pointer; }}
  button.no {{ border-color:#EAD9D5; color:#A4544A; margin-left:6px; }}
  button:hover {{ filter:brightness(.97); }}
  .done {{ color:var(--green); font-weight:600; }}
  .done.rej {{ color:#A4544A; }}
  .row-emergency {{ background:#FFFBF8; }}
  .side {{ display:grid; gap:14px; }}
  .audit {{ max-height:230px; overflow:auto; padding:10px 14px; font-size:11.5px; }}
  .audit div {{ padding:5px 0; border-bottom:1px dashed #EEF3F9; color:#33475B; }}
  .audit .t {{ color:var(--muted); margin-right:6px; }}
  .foot {{ margin-top:16px; color:var(--muted); font-size:11.5px; line-height:1.7;
    background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
  .foot b {{ color:#33475B; }}
  ul.q {{ margin:6px 0 0; padding-left:18px; color:#33475B; }}
  ul.q li {{ margin-bottom:6px; }}
  .mono {{ font-family:Consolas,monospace; color:var(--muted); font-size:11px; margin-left:6px; }}
  @media (max-width:980px) {{ .kpis {{ grid-template-columns:repeat(2,1fr); }}
    .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>{clinic} · 门诊预约与分诊协作助手</h1>
      <div class="meta">快照 {snapshot} · 数据版本 {version} · 生成时间 {generated} · 只读快照，不写回 HIS</div>
    </div>
    <div class="badge">建议状态：待人工复核（不自动生效）</div>
  </header>

  <section class="kpis">{kpis}</section>

  <div class="grid">
    <div class="card">
      <h2>候诊复核队列 <small>按建议次序排列 · 每条都需护士确认</small></h2>
      <table>
        <thead><tr><th>#</th><th>患者 / 科室</th><th>号别</th><th>规则依据</th><th>建议动作</th><th>优先级</th><th>复核</th></tr></thead>
        <tbody id="rows">{rows}</tbody>
      </table>
    </div>

    <div class="side">
      <div class="card">
        <h2>复核与审计 <small>本地演示</small></h2>
        <div class="audit" id="audit">
          <div><span class="t">系统</span>已生成 {total} 条建议，等待复核</div>
        </div>
      </div>
      <div class="card">
        <h2>规则命中 <small>本快照</small></h2>
        <table><tbody>{rule_rows}</tbody></table>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>全天回放对比 <small>同一批到达过程 · 只用于方案对比，不等于试点结论</small></h2>
    <table>
      <thead><tr><th>指标</th><th>现状 · 按号序叫号</th><th>建议策略 · 复核后</th>
        <th>参考线 · 纯先到先看</th></tr></thead>
      <tbody>{compare_rows}</tbody>
    </table>
    <div style="padding:12px 16px 14px;color:var(--muted);font-size:11.5px;line-height:1.75">
      <b style="color:#33475B">怎么读这张表：</b>现状叫号机认号不认人 —— 叫到空号就干等，
      一次浪费顺着队列传给后面所有人，所以<b>平均</b>候诊被拉高。
      建议策略直接招呼已经到了的人，把这部分吞吐损失拿回来。
      <br>「参考线」是纯按到达先后排序的结果。在「医生从不空等」的前提下，
      总等待时间与排序无关 —— 所以不能指望排序<b>总量</b>变好，它做的是重新分配：
      让多数人少等，同时必须有人多等。目前建议策略的平均候诊与参考线相差
      {avg_gap} 分钟/人，说明排序能拿的空间基本到顶；再往下压降只能加号源或改排班。
      <br><b style="color:#33475B">代价要说在前面：</b>建议策略的最长等待比现状更长 ——
      迟到与加号被有意识地往后放，这部分人承担了排序的成本。
      是否接受这个代价，是院方的管理决定，不是算法能替你做的。
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>全天急症回顾 <small>快照里看不到他们，因为他们从不排队 —— 这样才是对的</small></h2>
    <div style="padding:12px 16px 14px;color:#33475B;font-size:12px;line-height:1.8">
      全天标记 <b>{emg_flagged}</b> 例，实际到院 <b>{emg_arrived}</b> 例
      （业务编号 {emg_ids}）。<br>
      回放中他们的候诊时间：现状 <b>{emg_wait_now}</b> 分钟 →
      建议策略 <b>{emg_wait_new}</b> 分钟。<br>
      <span style="color:var(--muted)">处置口径：{emg_advice}。</span>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <h2>数据质量提示 <small>有歧义的记录不进建议</small></h2>
    <div style="padding:12px 16px"><ul class="q">{quality}</ul></div>
  </div>

  <div class="foot">
    <b>边界说明：</b>本页只做“时间解释与队列信息辅助”。系统不自动叫号、不自动分诊、不写回 HIS、不改医嘱；
    急症提示一律转人工，临床优先级不得被预约顺序覆盖。复核动作正式版由后端写入 audit.jsonl，
    本页的按钮仅用于演示交互与状态流转。
  </div>
</div>

<script>
// 回放对比表由 Python 侧直接渲染（三档策略都在页面上了），这里只保留复核交互演示。
const REPLAY = {base_json};

const audit = document.getElementById('audit');
function log(msg) {{
  const d = document.createElement('div');
  const t = new Date().toLocaleTimeString('zh-CN', {{hour12:false}});
  d.innerHTML = `<span class="t">${{t}}</span>${{msg}}`;
  audit.prepend(d);
}}
document.querySelectorAll('button[data-act]').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const tr = btn.closest('tr');
    const id = tr.dataset.id, act = btn.dataset.act, code = tr.dataset.code;
    const ops = tr.querySelector('.ops');
    const ok = act === 'accept';
    ops.innerHTML = `<span class="done ${{ok ? '' : 'rej'}}">${{ok ? '已接受（待签核）' : '已驳回'}}</span>`;
    log(`${{id}} · ${{ok ? '接受建议' : '驳回建议'}} · 依据 ${{code}} · 操作人 演示护士`);
  }});
}});
</script>
</body>
</html>"""
