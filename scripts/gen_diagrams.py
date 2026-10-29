#!/usr/bin/env python3
"""生成两张流程图（现状 / 数智化转型后）。

风格对齐参考示意图：标题区 + 场景范围条 + 纵向主流程（含判断菱形）+
右侧兜底面板 + 角色与职责卡片 + 待验证事项 + 注脚。

用法: python3 scripts/gen_diagrams.py
输出: docs/images/flow-current.svg / .png
      docs/images/flow-future.svg / .png
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------- 设计常量
W = 720
MARGIN = 34
CONTENT_R = W - MARGIN
MAIN_X, MAIN_W = MARGIN, 272
CX = MAIN_X + MAIN_W / 2
BR_X, BR_W = 326, 142
PANEL_X, PANEL_W = 482, 204
GAP = 20

NAVY = "#1F3864"
INK = "#34495E"
MUTED = "#6B7A90"
FAINT = "#8A97A8"
BLUE = "#2E75B6"
LINE = "#4A6484"
BOX_STROKE = "#BFD6EF"
BAND_FILL = "#EFF5FC"
BAND_STROKE = "#DCE8F7"
PANEL_FILL = "#F7FAFE"
PANEL_STROKE = "#B9CDE6"
GOLD = "#D9BE7E"
FONT = "'Microsoft YaHei','PingFang SC','Noto Sans SC',sans-serif"

# ---------------------------------------------------------------- 文本工具


def char_w(ch: str, size: float) -> float:
    if ord(ch) > 0x2E80:
        return size * 1.0
    if ch in "·| ":
        return size * 0.4
    if ch.isupper():
        return size * 0.62
    return size * 0.55


def text_w(s: str, size: float) -> float:
    return sum(char_w(c, size) for c in s)


def wrap(s: str, size: float, maxw: float) -> list[str]:
    lines, cur, cur_w = [], "", 0.0
    for ch in s:
        w = char_w(ch, size)
        if cur_w + w > maxw and cur:
            lines.append(cur)
            cur, cur_w = "", 0.0
        cur += ch
        cur_w += w
    if cur:
        lines.append(cur)
    return lines


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


class Svg:
    def __init__(self):
        self.parts: list[str] = []

    def add(self, s: str):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill="#fff", stroke=BOX_STROKE, rx=6, sw=1.1,
             dash=None, shadow=False):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        f = ' filter="url(#soft)"' if shadow else ""
        self.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                 f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}{f}/>')

    def text(self, x, y, s, size=9, fill=INK, weight=400, anchor="start", ls=0):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" '
                 f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}" '
                 f'letter-spacing="{ls}">{esc(s)}</text>')

    def lines(self, x, y, rows, size=8.4, fill=MUTED, lh=11.6, anchor="start", weight=400):
        for i, r in enumerate(rows):
            self.text(x, y + i * lh, r, size, fill, weight, anchor)

    def path(self, d, color=LINE, sw=1.1, dash=None, head=True):
        ds = f' stroke-dasharray="{dash}"' if dash else ""
        m = ' marker-end="url(#arrow)"' if head else ""
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{ds}{m}/>')

    def vline(self, x, y1, y2, color=LINE, sw=1.1, dash=None, head=True):
        self.path(f"M{x:.1f} {y1:.1f} L{x:.1f} {y2:.1f}", color, sw, dash, head)

    def hline(self, x1, x2, y, color=LINE, sw=1.1, dash=None, head=True):
        self.path(f"M{x1:.1f} {y:.1f} L{x2:.1f} {y:.1f}", color, sw, dash, head)

    def chip(self, x, y, s, size=8.2, fill=NAVY):
        w = text_w(s, size) + 12
        self.rect(x - w / 2, y - 9, w, 14, "#FFFFFF", "#DCE7F4", rx=3, sw=0.8)
        self.text(x, y + 1.4, s, size, fill, 700, "middle")


# ---------------------------------------------------------------- 流程构件


class Builder:
    """纵向主流程构建器：自动补连接箭头。"""

    def __init__(self):
        self.svg = Svg()
        self.nodes: list[dict] = []
        self.y = 0
        self.next_label = None

    def label(self, text):
        self.next_label = text

    def _slot(self, gap=GAP):
        self.y += gap

    def pill(self, text, w=190):
        self._slot()
        x = CX - w / 2
        self.svg.rect(x, self.y, w, 34, "#F1F7FE", BOX_STROKE, rx=17, shadow=True)
        self.svg.text(CX, self.y + 22, text, 9.6, NAVY, 700, "middle")
        self.nodes.append(dict(kind="pill", top=self.y, bottom=self.y + 34,
                               label=self.next_label))
        self.next_label = None
        self.y += 34
        return self

    def box(self, title, sub=None, x=MAIN_X, w=MAIN_W, fill="#FFFFFF",
            stroke=BOX_STROKE, tsize=10, ssize=8.2, accent=None, main=True, gap=GAP):
        self._slot(gap)
        tl = wrap(title, tsize, w - 26)
        sl = wrap(sub, ssize, w - 26) if sub else []
        h = 16 + len(tl) * 13.6 + (len(sl) * 11.4 + 2 if sl else 0) + 8
        self.svg.rect(x, self.y, w, h, fill, stroke, rx=7, shadow=True)
        if accent:
            self.svg.add(f'<rect x="{x:.1f}" y="{self.y + 9:.1f}" width="3" '
                         f'height="{h - 18:.1f}" rx="1.5" fill="{accent}"/>')
        self.svg.lines(x + 14, self.y + 20, tl, tsize, NAVY, 13.6, weight=600)
        if sl:
            self.svg.lines(x + 14, self.y + 20 + len(tl) * 13.6 + 1.2, sl, ssize, MUTED, 11.4)
        if main:
            self.nodes.append(dict(kind="box", top=self.y, bottom=self.y + h,
                                   label=self.next_label))
        self.next_label = None
        self.y += h
        return self.y

    def diamond(self, title, sub=None, w=252, h=80):
        self._slot()
        x = MAIN_X + (MAIN_W - w) / 2
        cy = self.y + h / 2
        self.svg.add(f'<path d="M{CX:.1f} {self.y:.1f} L{x + w:.1f} {cy:.1f} '
                     f'L{CX:.1f} {self.y + h:.1f} L{x:.1f} {cy:.1f} Z" fill="#F9FBFF" '
                     f'stroke="{GOLD}" stroke-width="1.2" filter="url(#soft)"/>')
        tl = wrap(title, 9.4, w * 0.60)
        sl = wrap(sub, 7.6, w * 0.58) if sub else []
        total = len(tl) * 12.2 + (len(sl) * 10.2 if sl else 0)
        ty = cy - total / 2 + 8.4
        self.svg.lines(CX, ty, tl, 9.4, NAVY, 12.2, "middle", 700)
        if sl:
            self.svg.lines(CX, ty + len(tl) * 12.2 + 0.6, sl, 7.6, MUTED, 10.2, "middle")
        self.nodes.append(dict(kind="diamond", top=self.y, bottom=self.y + h,
                               cy=cy, label=self.next_label, right=x + w))
        self.next_label = None
        self.y += h
        return self

    def branch(self, cy, label, title, sub=None, fill="#FFFFFF", stroke=BOX_STROKE,
               dy=-22, tsize=9, ssize=7.4):
        """从菱形右顶点引出的分支节点。"""
        svg = self.svg
        by = cy + dy
        svg.path(f"M{CX + 126:.1f} {cy:.1f} L{BR_X - 2:.1f} {cy:.1f}", head=True)
        svg.chip((CX + 126 + BR_X) / 2, cy - 9, label)
        tl = wrap(title, tsize, BR_W - 24)
        sl = wrap(sub, ssize, BR_W - 24) if sub else []
        h = 14 + len(tl) * 12.2 + (len(sl) * 10.2 if sl else 0) + 8
        svg.rect(BR_X, by, BR_W, h, fill, stroke, rx=6, shadow=True)
        svg.lines(BR_X + 12, by + 18, tl, tsize, NAVY, 12.2, weight=600)
        if sl:
            svg.lines(BR_X + 12, by + 18 + len(tl) * 12.2 + 1, sl, ssize, MUTED, 10.2)
        return by, h

    def links(self):
        for a, b in zip(self.nodes, self.nodes[1:]):
            self.svg.vline(CX, a["bottom"] + 1, b["top"] - 1.5)
            if b["label"]:
                self.svg.chip(CX + 18, (a["bottom"] + b["top"]) / 2 + 3.5, b["label"], 7.8)
        return self.svg


def band(svg, y, label, text, label_w=0):
    rows = wrap(text, 8.8, CONTENT_R - MAIN_X - 118)
    h = max(48, 26 + len(rows) * 12.4 + 8)
    svg.rect(MAIN_X, y, CONTENT_R - MAIN_X, h, BAND_FILL, BAND_STROKE, rx=6)
    svg.add(f'<rect x="{MAIN_X + 12}" y="{y + 15}" width="3" height="14" rx="1.5" fill="{BLUE}"/>')
    svg.text(MAIN_X + 22, y + 26, label, 9.2, NAVY, 700)
    x0 = MAIN_X + 22 + text_w(label, 9.2) + 12
    svg.text(x0, y + 26, rows[0], 8.8, INK)
    if len(rows) > 1:
        svg.lines(MAIN_X + 22, y + 26 + 12.4, rows[1:], 8.8, INK, 12.4)
    return y + h


def header(svg, title, subtitle, tag, h_total):
    svg.parts.insert(0, f'<rect x="0" y="0" width="{W}" height="{h_total:.0f}" fill="#FFFFFF"/>')
    svg.add(f'<rect x="0" y="0" width="{W}" height="3.5" fill="{BLUE}"/>')
    svg.text(MARGIN, 46, title, 18.6, NAVY, 700, ls=0.3)
    svg.text(MARGIN, 66, subtitle, 9.0, MUTED)
    tw = text_w(tag, 8.4) + 22
    svg.rect(CONTENT_R - tw, 28, tw, 22, "#F1F7FD", "#D8E6F6", rx=11)
    svg.text(CONTENT_R - tw / 2, 42.6, tag, 8.4, BLUE, 700, "middle")
    svg.add(f'<path d="M{MARGIN} 79 L{CONTENT_R} 79" stroke="#E4EBF5" stroke-width="1"/>')


def section(svg, y, title, note=None):
    svg.add(f'<rect x="{MAIN_X}" y="{y - 9.5:.1f}" width="3" height="12.5" rx="1.5" fill="{BLUE}"/>')
    svg.text(MAIN_X + 10, y, title, 11.2, NAVY, 700)
    if note:
        svg.text(CONTENT_R, y - 1, note, 8.2, FAINT, 400, "end")
    svg.add(f'<path d="M{MAIN_X} {y + 9.5:.1f} L{CONTENT_R} {y + 9.5:.1f}" '
            f'stroke="#E4EBF5" stroke-width="0.9"/>')
    return y + 9.5


def role_cards(svg, y, roles, cols=3):
    gap = 10
    cw = (CONTENT_R - MAIN_X - gap * (cols - 1)) / cols
    row_h = 66
    for i, (icon, name, duty) in enumerate(roles):
        r, c = divmod(i, cols)
        x = MAIN_X + c * (cw + gap)
        yy = y + r * (row_h + 9)
        svg.rect(x, yy, cw, row_h, "#FFFFFF", "#E2EBF7", rx=6, shadow=True)
        svg.rect(x + 10, yy + 12, 22, 22, "#EAF2FB", "#D5E4F7", rx=5)
        svg.text(x + 21, yy + 27.5, icon, 9.6, BLUE, 700, "middle")
        svg.text(x + 39, yy + 26, name, 8.9, NAVY, 700)
        svg.lines(x + 10, yy + 44, wrap(duty, 7.5, cw - 20)[:3], 7.5, MUTED, 9.6)
    rows = (len(roles) + cols - 1) // cols
    return y + rows * (row_h + 9)


def note_box(svg, y, items, cols=2):
    body_w = CONTENT_R - MAIN_X
    col_w = (body_w - 24) / cols
    per = (len(items) + cols - 1) // cols
    rows = [wrap(it, 8.0, col_w - 12) for it in items]
    max_rows = max(len(r) for r in rows)
    h = 14 + per * (max_rows * 11.4 + 4)
    svg.rect(MAIN_X, y, body_w, h, "#FCFDFF", "#E2EBF7", rx=6)
    for i, rw in enumerate(rows):
        c, r = divmod(i, per)
        x = MAIN_X + 14 + c * col_w
        yy = y + 16 + r * (max_rows * 11.4 + 4)
        svg.add(f'<circle cx="{x + 2:.1f}" cy="{yy - 2.6:.1f}" r="1.7" fill="{BLUE}" opacity="0.6"/>')
        svg.lines(x + 10, yy, rw, 8.0, INK, 11.4)
    return y + h


def panel(svg, y, title, entries, h=None):
    x, w = PANEL_X, PANEL_W
    hh = 46
    for t, s in entries:
        tl = wrap(t, 8.5, w - 26)
        sl = wrap(s, 7.3, w - 28) if s else []
        hh += 12 + len(tl) * 10.6 + len(sl) * 9.4 + 8
    hh = h or hh + 4
    svg.rect(x, y, w, hh, PANEL_FILL, PANEL_STROKE, rx=8, dash="5 4", sw=1.2)
    svg.text(x + 13, y + 22, title, 9.8, NAVY, 700)
    svg.add(f'<path d="M{x + 13} {y + 30:.1f} L{x + w - 13} {y + 30:.1f}" stroke="#CBDCEE" '
            f'stroke-width="0.8" stroke-dasharray="3 3"/>')
    cy = y + 40
    for t, s in entries:
        tl = wrap(t, 8.5, w - 26)
        sl = wrap(s, 7.3, w - 28) if s else []
        bh = 12 + len(tl) * 10.6 + len(sl) * 9.4 + 4
        svg.rect(x + 12, cy, w - 24, bh, "#FFFFFF", "#DDE9F6", rx=5)
        svg.lines(x + 20, cy + 13.5, tl, 8.5, NAVY, 10.6, weight=600)
        if sl:
            svg.lines(x + 20, cy + 13.5 + len(tl) * 10.6, sl, 7.3, MUTED, 9.4)
        cy += bh + 7
    return y + hh


def footnote(svg, y, text):
    svg.add(f'<path d="M{MARGIN} {y:.1f} L{CONTENT_R} {y:.1f}" stroke="#E7EDF6" stroke-width="0.8"/>')
    svg.lines(MARGIN, y + 14, wrap(text, 7.7, CONTENT_R - MAIN_X), 7.7, FAINT, 10.4)


def defs(h):
    return f'''<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="8.2" refY="5" markerWidth="6.2" markerHeight="6.2"
          orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="{LINE}"/></marker>
  <filter id="soft" x="-25%" y="-25%" width="150%" height="150%">
    <feDropShadow dx="0" dy="1.2" stdDeviation="1.5" flood-color="#1F3864" flood-opacity="0.075"/>
  </filter>
</defs><rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1:.0f}" fill="none" stroke="#E9EFF7"/>'''


# ---------------------------------------------------------------- 现状


def build_current():
    b = Builder()
    y = band(b.svg, 94, "场景范围",
             "东湖门诊中心 · 两个常规门诊：日均 1600 人次，候诊中位数 68 分钟（目标 40 分钟），"
             "爽约率 19%，导诊每日约 180 次排队咨询；预约平台 / HIS / 叫号系统三套并存。")
    b.y = y + 4
    panel_y = y + 12

    b.pill("患者预约或现场挂号")
    b.box("到院登记与签到", "自助机 / 人工窗口签到取号；重复签到靠护士人工判断")
    b.box("预检分诊", "护士按主诉与生命体征判定科室与优先级，只记在分诊单上")
    b.box("候诊等待", "叫号系统按签到顺序排队；迟到、现场加号、检查回诊混在同一队列")
    b.diamond("是否出现次序争议或异常？", "迟到 / 加号 / 回诊 / 医生临时处理急诊")
    dys = b.nodes[-1]["cy"]
    b.label("否")
    b.box("按号序接诊", "医生按叫号顺序接诊；实际顺序与系统记录常不一致")
    b.box("接诊与检查交接", "开检查单 → 患者往返 → 结果回传 → 回诊插队无统一规则")
    b.diamond("本次就诊是否完成？", "需复诊 / 需住院 / 需转诊")
    d2 = b.nodes[-1]["cy"]
    b.label("是")
    b.box("离开门诊 / 进入下一环节", "住院、转诊或复诊由医生口头告知，患者自行办理")

    by, bh = b.branch(dys, "是", "导诊人工协调", "查纸质记录、问医生、口头解释", dy=-24)
    by2, bh2 = b.branch(d2, "否", "返回候诊继续等待", "重复排队，等待重新起算", dy=-18)
    # 人工协调后回到候诊（虚线回路）
    b.svg.path(f"M{BR_X + BR_W + 1:.1f} {by + 22:.1f} L{BR_X + BR_W + 6:.1f} {by + 22:.1f} "
               f"L{BR_X + BR_W + 6:.1f} {dys - 96:.1f} L{MAIN_X + MAIN_W + 6:.1f} {dys - 96:.1f}",
               color="#9FB4CC", dash="4 3", head=True)
    b.svg.text(BR_X + BR_W + 10, dys - 50, "回到队列", 7.2, FAINT)

    # 右侧：现状断点
    panel(b.svg, panel_y, "现状断点（人工兜底）", [
        ("三套等待口径", "患者按到院、叫号按签到、运营按预约时间，验收不可比"),
        ("排班未同步", "医生临时处理急诊，患者仍收到准点到诊通知"),
        ("解释不留痕", "关键说明留在便签与群聊，未随单据交接"),
        ("节点无计时", "只能靠一线感受定位瓶颈，无法归因"),
        ("急症靠经验", "升级路径依赖个人判断，签核人与时限未定"),
        ("无统一视图", "预约平台 / HIS / 叫号系统各自维护，跨系统核对耗时"),
    ])

    b.links()
    svg = b.svg
    y = b.y + 30
    y = section(svg, y, "角色与职责", "6 个岗位 · 实验室访谈角色")
    y = role_cards(svg, y + 12, [
        ("运", "门诊运营主任 · 顾明岚", "定目标与预算、推动立项；不能单方决定分诊规则变更"),
        ("护", "导诊护士 · 林亦舟", "现场排序与解释；只能复核建议，不越权改状态"),
        ("排", "排班管理员 · 唐映秋", "写清输入输出与交接；不代替质控签核"),
        ("系", "系统工程师 · 秦芮", "只读排班与队列；不开放写接口与医嘱变更"),
        ("质", "质控专员 · 傅景", "急症升级与越权拦截；可因关键风险否决上线"),
        ("服", "患者服务主管 · 叶书", "受理投诉与口径对齐；未经确认不承诺结果"),
    ])
    y += 26
    y = section(svg, y, "待验证事项", "现状侧证据缺口")
    y = note_box(svg, y + 12, [
        "预约 → 登记 → 分诊 → 候诊 → 接诊 → 检查交接，逐节点耗时分布",
        "迟到、现场加号、检查回诊各占队列的比例与时段分布",
        "三套等待口径差异对“候诊 68 分钟”基线的影响幅度",
        "便签 / 群聊说明的交接遗漏率与重复解释次数",
        "急症升级的实际触发次数、签核人与响应时限",
        "重复签到、叫号遗漏记录的占比与人工修复方式",
    ])
    y += 22
    footnote(svg, y, "注：本图为基于 6 岗位访谈与实验室事实记录还原的现状示意，属待验证假设；"
                     "节点耗时、占比与口径差异需用历史资料回放与现场计时核实后再定稿。")
    return b.svg, y + 38


# ---------------------------------------------------------------- 转型后


def build_future():
    b = Builder()
    y = band(b.svg, 94, "转型范围",
             "首期只在两个常规门诊做并行试点：只读排班与队列，只辅助“时间解释与队列信息”；"
             "专业分诊判断、急症升级、加号审批仍由医护人员确认，不替换现有业务、不写回 HIS。")
    b.y = y + 4
    panel_y = y + 12

    b.pill("预约 / 挂号（号源与规则同源）")
    b.box("到院签到（唯一事件去重）", "同一患者同一号源仅保留一条签到事件，冲突入人工修复队列")
    b.box("预检分诊（护士判定）", "主诉与生命体征由护士录入；系统只给提示，不下诊断")
    b.box("队列状态聚合（只读快照）", "预约平台 + HIS + 叫号系统按业务编号对齐，带时间戳与版本")
    recheck_y = (b.nodes[-1]["top"] + b.nodes[-1]["bottom"]) / 2
    recheck_y = (b.nodes[-1]["top"] + b.nodes[-1]["bottom"]) / 2
    b.diamond("数据是否可校验、无冲突？", "主编号 / 事件时间 / 版本字段")
    d1 = b.nodes[-1]["cy"]
    b.label("是")
    b.box("异常识别与建议生成", "迟到 / 加号 / 回诊 / 排班未同步 / 脆弱人群；输出规则依据与解释话术，状态=待复核")
    b.diamond("是否命中急症或高风险触发？", "紧急症状 / 排班未同步 / 版本冲突 / 越权")
    d2 = b.nodes[-1]["cy"]
    b.label("否")
    b.box("护士复核（接受 / 修改 / 驳回）", "显示原记录与待确认字段；改动留痕，不覆盖原建议")
    b.box("队列按复核结果更新 + 解释卡片", "统一口径话术给患者：预计等待、次序依据、下一步")
    b.box("接诊 → 检查交接 → 结束", "回诊插队按规则提示，仍由护士确认后生效")
    b.box("周度复盘与规则版本更新", "误判样本、指标复测、规则生效日期与适用范围登记",
          fill="#F7FBF8", stroke="#CFE3D6")

    by, bh = b.branch(d1, "否", "人工修复队列", "系统工程师 / 排班管理员核对，不进建议", dy=-22)
    by2, bh2 = b.branch(d2, "是", "立即转临床升级", "按院方流程处理、质控签核；不进排序建议",
                        fill="#FFF9EE", stroke="#EBD3A2", dy=-26)
    b.svg.text(BR_X, by2 + bh2 + 12, "临床优先级不得被预约顺序覆盖", 7.2, "#B08948")
    # 修复后重新校验
    b.svg.path(f"M{BR_X + BR_W:.1f} {by + 20:.1f} L{BR_X + BR_W + 7:.1f} {by + 20:.1f} "
               f"L{BR_X + BR_W + 7:.1f} {recheck_y:.1f} L{MAIN_X + MAIN_W - 4:.1f} {recheck_y:.1f}",
               color="#9FB4CC", dash="4 3", head=True)
    b.svg.text(BR_X + BR_W + 10, recheck_y - 8, "修复后重新校验", 7, FAINT)

    panel(b.svg, panel_y, "人工兜底与权限边界", [
        ("只读不写", "不写回 HIS、不自动叫号、不自动分诊、不改医嘱"),
        ("急症 100% 转人工", "质控可否决上线；触发停止条件即复盘"),
        ("中断降级", "用带时间戳只读快照，显示“暂未更新”"),
        ("歧义不进建议", "未校验记录进人工修复队列，不参与推荐"),
        ("全链留痕", "业务编号 / 版本 / 引用 / 改动 / 签核人"),
        ("周度反馈", "收集误判例子，先复测指标再改规则版本"),
        ("不替换业务", "并行试点，原有人工流程始终保留"),
    ])

    b.links()
    svg = b.svg
    y = b.y + 30
    y = section(svg, y, "角色与职责（人机分工）", "系统只给建议，岗位保留决定权")
    y = role_cards(svg, y + 12, [
        ("运", "门诊运营主任 · 顾明岚", "确认口径与试点范围，主持周度复盘与是否扩面"),
        ("护", "导诊护士 · 林亦舟", "复核建议、使用解释卡片；可暂停并转排班核对"),
        ("排", "排班管理员 · 唐映秋", "核对排班未同步、分派异常、超时升级到运营主任"),
        ("系", "系统工程师 · 秦芮", "维护快照与去重补齐，统计歧义记录比例"),
        ("质", "质控专员 · 傅景", "确认急症升级路径、审计链与停止条件"),
        ("服", "患者服务主管 · 叶书", "统一对外解释口径，受理投诉并关联业务编号"),
    ])
    y += 26
    y = section(svg, y, "试点验收与停止条件", "两个常规门诊 · 并行试点 4 周")
    y = note_box(svg, y + 12, [
        "候诊中位数 68 → ≤54 分钟（降幅 ≥20%），口径书面固定",
        "爽约率 19% → 10%，分母与排除规则三方签字确认",
        "急症识别提示 100% 转人工，且可追溯到签核人与时间",
        "导诊排队咨询 180 → ≤120 次/日，交接遗漏可计数",
        "停止条件：越权写操作、急症被排序覆盖、口径未定即出结论",
        "任一停止条件触发 → 暂停试点，由质控与运营主任复盘",
    ])
    y += 22
    footnote(svg, y, "注：本图为数智化转型后的目标流程示意，用于方案评审与试点对齐；"
                     "接口读写范围、签核人与时限仍需与系统工程师、质控专员逐项书面确认。")
    return b.svg, y + 38


# ---------------------------------------------------------------- 输出


def render(svg: Svg, h: float, out_svg: str):
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h:.0f}" '
            f'viewBox="0 0 {W} {h:.0f}" font-family="{FONT}">')
    body = "".join(svg.parts)
    doc = head + body + defs(h) + "</svg>"
    with open(out_svg, "w", encoding="utf-8") as f:
        f.write(doc)


def to_png(svg_path: str, png_path: str, height: float):
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(edge):
        print("  ! 未找到 Edge，跳过 PNG")
        return
    html = os.path.join(tempfile.gettempdir(),
                        os.path.basename(svg_path).replace(".svg", ".preview.html"))
    src = "file:///" + os.path.abspath(svg_path).replace("\\", "/")
    with open(html, "w", encoding="utf-8") as f:
        f.write('<html><body style="margin:0;background:#fff">'
                f'<img src="{src}" width="{W}" height="{height:.0f}" '
                'style="display:block"></body></html>')
    cmd = [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=2",
           f"--screenshot={os.path.abspath(png_path)}",
           f"--window-size={W},{int(height)}",
           "file:///" + os.path.abspath(html).replace("\\", "/")]
    try:                       # 覆盖旧图；删不掉也无所谓，Edge 会直接覆盖
        os.remove(png_path)
    except OSError:
        pass
    subprocess.run(cmd, capture_output=True, timeout=180)
    try:                       # 临时预览页，删不掉也不影响结果
        os.remove(html)
    except OSError:
        pass
    if os.path.exists(png_path):
        print(f"  -> {png_path} ({os.path.getsize(png_path) // 1024} KB)")
    else:
        print("  ! PNG 未生成，SVG 仍可用（docs/images/*.svg）")


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "docs", "images")
    os.makedirs(out, exist_ok=True)

    svg, bottom = build_current()
    header(svg, "东湖门诊中心 ｜ 门诊预约与分诊协作 · 现状流程图",
           "基于 6 岗位访谈与实验室事实记录还原；现状为待验证假设，节点耗时需现场计时核实。",
           "现状 AS-IS", bottom)
    p = os.path.join(out, "flow-current.svg")
    render(svg, bottom, p)
    print("saved", p)
    to_png(p, os.path.join(out, "flow-current.png"), bottom)

    svg2, bottom2 = build_future()
    header(svg2, "东湖门诊中心 ｜ 门诊预约与分诊协作 · 数智化转型后流程图",
           "目标流程：只读快照 + 规则建议 + 护士复核 + 全链留痕；专业判断与急症升级保留在医护一侧。",
           "目标 TO-BE", bottom2)
    p2 = os.path.join(out, "flow-future.svg")
    render(svg2, bottom2, p2)
    print("saved", p2)
    to_png(p2, os.path.join(out, "flow-future.png"), bottom2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
