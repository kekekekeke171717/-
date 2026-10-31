# -*- coding: utf-8 -*-
"""生成答辩演示稿与配套演讲稿。

用法（仓库根目录执行）：

    python scripts/gen_ppt.py

产出：

    docs/答辩演示.pptx     原生可编辑：文本是文本框、数据是表格、图是图片，不是截图拼页
    docs/答辩演讲稿.md
    docs/答辩演讲稿.docx

设计原则：页上是"提词器"，备注里是"逐字稿"。删掉任何一页都不影响别的页。
"""

from __future__ import annotations

import os

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- 视觉规范

FONT = "Microsoft YaHei"
MONO = "Consolas"

BLUE = RGBColor(0x1B, 0x5E, 0x8C)          # 主色：医疗蓝
BLUE_DK = RGBColor(0x13, 0x44, 0x66)        # 封面 / 结束页底
BLUE_LT = RGBColor(0xE8, 0xF1, 0xF8)        # 浅蓝底
BLUE_MD = RGBColor(0x2E, 0x8B, 0xC8)       # 强调线
DARK = RGBColor(0x22, 0x36, 0x48)            # 正文
MUTED = RGBColor(0x6B, 0x7C, 0x8C)          # 次要
LINE = RGBColor(0xD8, 0xE1, 0xE9)           # 分隔线
RED = RGBColor(0xB5, 0x2C, 0x22)            # 红线
GREEN = RGBColor(0x1F, 0x7A, 0x5C)         # 达成
AMBER = RGBColor(0xB4, 0x6A, 0x05)           # 提示
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SW, SH = 13.333, 7.5          # 16:9
ML = 0.62                     # 左边距
CW = SW - 2 * ML              # 内容宽度
TOP = 1.28                    # 内容起始高度


# ---------------------------------------------------------------- 底层工具

def _typeface(run, name: str) -> None:
    """把字体名同时写进 latin / ea / cs，否则中文落回宋体。"""
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", name)


def put(box, text, size=14, bold=False, color=DARK, name=FONT,
        align=PP_ALIGN.LEFT, space_after=6, line=1.32, bullet=None, level=0):
    """往文本框里写一段，返回该段落。

    box 可以是 shape，也可以直接是 TextFrame（表格单元格用后者）。
    """
    tf = box.text_frame if hasattr(box, "text_frame") else box
    p = tf.paragraphs[0] if (len(tf.paragraphs) == 1 and not tf.text) else tf.add_paragraph()
    p.alignment = align
    p.level = level
    p.space_after = Pt(space_after)
    p.line_spacing = line
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = name
    _typeface(r, name)
    if bullet:
        r.text = bullet + " " + text
    return p


def txt(slide, left, top, width, height=0.4, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.04)
    tf.margin_top = tf.margin_bottom = 0
    return box


def rect(slide, left, top, width, height, fill, line=None, radius=None):
    from pptx.enum.shapes import MSO_SHAPE
    if radius:
        sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                    Inches(left), Inches(top), Inches(width), Inches(height))
        sh.adjustments[0] = radius
    else:
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                    Inches(left), Inches(top), Inches(width), Inches(height))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line:
        sh.line.color.rgb = line
        sh.line.width = Pt(0.75)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    return sh


def bullets(slide, items, left=ML, top=TOP, width=CW, size=14.5,
            color=DARK, gap=9, l2=13):
    """要点列表，二级自动缩进并用不同符号。"""
    y = top
    for it in items:
        lvl, text = it if isinstance(it, tuple) else (0, it)
        if lvl == 0:
            b = txt(slide, left, y, width, 0.4)
            put(b, text, size=size, color=color, bullet="▪", space_after=0)
            y += 0.30
        else:
            b = txt(slide, left + 0.34, y, width - 0.34, 0.4)
            put(b, text, size=l2, color=MUTED, bullet="–", space_after=0)
            y += 0.26
        y += gap / 72
    return y


def table(slide, headers, rows, left=ML, top=TOP, width=CW, widths=None,
          size=11.5, head_size=11.5, row_h=0.34, head_h=0.38,
          aligns=None, highlight=None):
    """原生表格，可直接在 PowerPoint 里改字。"""
    r, c = len(rows) + 1, len(headers)
    gf = slide.shapes.add_table(r, c, Inches(left), Inches(top),
                                Inches(width), Inches(head_h + row_h * len(rows)))
    tbl = gf.table
    tbl.first_row = True
    tbl.horz_banding = False

    if widths:
        total = sum(widths)
        for i, w in enumerate(widths):
            tbl.columns[i].width = Emu(int(Inches(width) * w / total))
    tbl.rows[0].height = Inches(head_h)
    for i in range(1, r):
        tbl.rows[i].height = Inches(row_h)

    aligns = aligns or [PP_ALIGN.LEFT] * c
    for j, h in enumerate(headers):
        cell = tbl.cell(0, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = BLUE
        cell.margin_left = cell.margin_right = Inches(0.08)
        cell.margin_top = cell.margin_bottom = Inches(0.02)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        put(cell.text_frame, h, size=head_size, bold=True, color=WHITE,
            align=aligns[j], space_after=0)

    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = BLUE_LT if i % 2 == 0 else WHITE
            cell.margin_left = cell.margin_right = Inches(0.08)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            col = DARK
            if highlight and (i - 1) in highlight:
                col = highlight[(i - 1)]
            put(cell.text_frame, str(val), size=size, color=col,
                align=aligns[j], space_after=0)
    return gf


def note(slide, text: str) -> None:
    """写备注栏。备注是纯文本，渲染不了 Markdown，所以把 ** 去掉。"""
    slide.notes_slide.notes_text_frame.text = text.replace("**", "").strip()


def header(slide, title: str, kicker: str = "", size=26):
    rect(slide, 0, 0, SW, 1.02, BLUE)
    rect(slide, 0, 1.02, SW, 0.035, BLUE_MD)
    b = txt(slide, ML, 0.16, 9.6, 0.72, MSO_ANCHOR.MIDDLE)
    put(b, title, size=size, bold=True, color=WHITE, space_after=0)
    if kicker:
        k = txt(slide, 9.9, 0.18, 2.8, 0.66, MSO_ANCHOR.MIDDLE)
        put(k, kicker, size=11.5, color=RGBColor(0xB9, 0xD8, 0xEE),
            align=PP_ALIGN.RIGHT, space_after=0)


def footer(slide, idx: int, total: int):
    rect(slide, ML, 7.02, CW, 0.012, LINE)
    f = txt(slide, ML, 7.08, 7.0, 0.28)
    put(f, "clinic-triage-copilot · 门诊预约与分诊协作助手（MVP）",
        size=9, color=MUTED, space_after=0)
    p = txt(slide, SW - ML - 2.0, 7.08, 2.0, 0.28)
    put(p, f"{idx} / {total}", size=9, color=MUTED,
        align=PP_ALIGN.RIGHT, space_after=0)


# ---------------------------------------------------------------- 内容定义

TOTAL = 23

def build(prs: Presentation):
    blank = prs.slide_layouts[6]

    # ---- 1 封面 ----------------------------------------------------------
    s = prs.slides.add_slide(blank)
    rect(s, 0, 0, SW, SH, BLUE_DK)
    rect(s, 0, 0, 0.16, SH, BLUE_MD)
    b = txt(s, 1.0, 1.85, 11.4, 1.3)
    put(b, "门诊预约与分诊协作助手", size=44, bold=True, color=WHITE, space_after=0)
    b = txt(s, 1.0, 3.05, 11.4, 0.8)
    put(b, "一个只读的「次序解释引擎」MVP", size=25, color=RGBColor(0x9E, 0xCB, 0xE8), space_after=0)
    rect(s, 1.0, 4.05, 3.4, 0.03, BLUE_MD)
    b = txt(s, 1.0, 4.35, 11.4, 1.2)
    put(b, "从 35 条访谈事实，到一个能跑起来的原型", size=16, color=RGBColor(0xC7, 0xD9, 0xE6), space_after=8)
    put(b, "FDE Discovery Lab · healthcare-appointments 场景", size=16, color=RGBColor(0xC7, 0xD9, 0xE6), space_after=0)
    b = txt(s, 1.0, 6.35, 11.4, 0.4)
    put(b, "答辩汇报 · 2026-10-31 · github.com/kekekekeke171717/-",
        size=11, color=RGBColor(0x8A, 0xA8, 0xBE), space_after=0)
    note(s, """
各位老师好。我汇报的题目是《门诊预约与分诊协作助手》。

先说清楚它**不是**什么：它不是一套新的分诊系统，也不做自动诊断。
它只是一个"次序解释引擎" —— 回答门诊里最常吵起来的三件事：谁排在我前面、为什么、
我还要等多久。

这个项目不是我想出来的。需求来自 FDE Discovery Lab 的「门诊预约与分诊协作」场景，
我对其中 6 个岗位做了结构化访谈，拿到 35 条带原文证据的事实。
后面每一页的设计决定，我都会标出它对应的事实编号，可以逐条追溯。

汇报预计 15 分钟，之后请各位老师指正。
""")

    # ---- 2 一句话定位 ----------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "一句话定位", "01 定位")
    b = txt(s, ML, TOP + 0.05, CW, 0.75)
    put(b, "不做自动分诊，只把「谁先看、为什么、等多久」这三件事讲清楚。",
        size=21, bold=True, color=BLUE, space_after=0)

    cards = [
        ("01", "谁排在我前面，为什么？",
         "迟到患者与现场加号混在队列里，护士反复解释次序", "f10"),
        ("02", "我还要等多久？",
         "患者以到院算等待、叫号系统以签到算、运营以预约时间算", "f50 / f53"),
        ("03", "我前面的医生去哪了？",
         "医生临时处理急诊，排班未同步，患者却收到准点到诊通知", "f11"),
    ]
    x = ML
    w = (CW - 2 * 0.28) / 3
    for num, q, ev, fid in cards:
        rect(s, x, TOP + 1.05, w, 2.55, BLUE_LT)
        rect(s, x, TOP + 1.05, w, 0.045, BLUE)
        t = txt(s, x + 0.26, TOP + 1.32, w - 0.5)
        put(t, num, size=27, bold=True, color=RGBColor(0xB9, 0xD2, 0xE4), space_after=0)
        t = txt(s, x + 0.26, TOP + 1.85, w - 0.5, 1.0)
        put(t, q, size=16.5, bold=True, color=DARK, space_after=0)
        t = txt(s, x + 0.26, TOP + 2.6, w - 0.5, 0.9)
        put(t, ev, size=12, color=MUTED, space_after=0)
        t = txt(s, x + 0.26, TOP + 3.22, w - 0.5, 0.3)
        put(t, "事实依据 " + fid, size=10.5, color=BLUE, space_after=0)
        x += w + 0.28

    b = txt(s, ML, 6.1, CW, 0.7)
    put(b, "所以本 MVP 的全部功能，就是让这三句话有统一、可追溯、可复核的答案。",
        size=15, color=DARK, space_after=4)
    put(b, "刻意不做：不打通三方系统做实时写入（f32 只读）、不给风险评分（f40）、"
           "不把节省工时当现金回款（f03）。", size=12.5, color=MUTED, space_after=0)
    footer(s, 2, TOTAL)
    note(s, """
这一页是全篇的锚点，请老师们记住这句话：**我们解决的是"解释"，不是"诊断"**。

门诊真正卡住的地方，不是医生不会看病，而是三句问不出口、答不上来的话。
第一句来自导诊护士林亦舟：迟到的人和现场加号的人混在一条队里，她每天要反复解释
为什么那个人排在你前面。第二句来自患者服务主管叶书：同样一段等待，患者按到院算、
叫号系统按签到算、运营按预约时间算，三个部门三个数。第三句是医生临时去处理急诊，
排班没同步，可患者早就收到了"请准时到诊"的短信。

这三句话，右边都标了事实编号。后面所有设计，都是从这三句话长出来的。
""")

    # ---- 3 议程 ----------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "汇报路线", "02 议程")
    items = [
        ("01", "需求从哪来", "6 个角色 × 35 条事实，以及这条决策链上谁能一票否决"),
        ("02", "现状与症结", "主流程节点、三系统孤岛、以及四个被忽略的症结"),
        ("03", "四条关键洞察", "口径冲突、脏数据隔离、让位上限、纯排序的极限"),
        ("04", "方案与 MVP", "两张流程图对着看：一个节点的位移；四条命令与四样产出"),
        ("05", "商业化与风险", "行业盘子、错位定位、16 万报价、验收口径与局限"),
    ]
    y = TOP + 0.1
    for num, t, d in items:
        rect(s, ML, y, 1.16, 0.86, BLUE_LT)
        t2 = txt(s, ML, y, 1.16, 0.86, MSO_ANCHOR.MIDDLE)
        put(t2, num, size=27, bold=True, color=BLUE, align=PP_ALIGN.CENTER, space_after=0)
        t2 = txt(s, ML + 1.42, y + 0.1, 5.0, 0.4)
        put(t2, t, size=18, bold=True, color=DARK, space_after=0)
        t2 = txt(s, ML + 1.42, y + 0.52, 10.6, 0.4)
        put(t2, d, size=12.5, color=MUTED, space_after=0)
        y += 0.98
    footer(s, 3, TOTAL)
    note(s, """
汇报分五段：需求来源、现状症结、四条洞察、方案与 MVP、商业化与风险。

如果时间紧，老师们重点看第三和第四段 —— 那两页是这次作业真正有价值的部分：
一个是"排序救不了候诊"这个反直觉的结论，一个是两张流程图对比时我刻意做的取舍。
""")

    # ---- 4 需求从哪来 -----------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "需求从哪来", "03 需求")
    put(txt(s, ML, TOP, CW, 0.4),
        "Discovery Lab 系统化访谈 · 事实集是设计、报价、验收的唯一依据",
        size=17, bold=True, color=BLUE, space_after=0)

    bullets(s, [
        (0, "来源：FDE Discovery Lab「门诊预约与分诊协作」场景（healthcare-appointments）"),
        (1, "对门诊运营主任、导诊护士、排班管理员、门诊系统工程师、医疗质控专员、"
            "患者服务主管 6 个岗位做结构化访谈"),
        (0, "产出：35 条事实，每条保留访谈原话 + 证据编号（医疗-00x）+ 验收口径"),
        (1, "刻意不改写原话 —— 改写一次，信息就损失一次"),
        (0, "用法：仓库里设计文档、代码注释、贡献指南红线，引用的都是同一套编号 f00–f55"),
        (1, "评审时每个设计决定都要能指回一条事实；指不回的，就是设计者的臆想"),
    ], top=TOP + 0.62, size=14.5)

    y = TOP + 3.5
    rect(s, ML, y, CW, 1.45, BLUE_LT)
    put(txt(s, ML + 0.3, y + 0.16, CW - 0.6, 0.35),
        "决策链路（事实 f04）", size=13.5, bold=True, color=BLUE, space_after=0)
    stages = ["门诊运营主任\n推动立项", "医疗质控专员\n可否决上线", "患者服务主管\n参与结果验收"]
    x = ML + 0.3
    w = (CW - 0.6 - 2 * 0.5) / 3
    for i, st in enumerate(stages):
        rect(s, x, y + 0.58, w, 0.66, WHITE)
        t = txt(s, x, y + 0.58, w, 0.66, MSO_ANCHOR.MIDDLE)
        for j, line in enumerate(st.split("\n")):
            put(t, line, size=(12.5 if j == 0 else 11),
                bold=(j == 0), color=(DARK if j == 0 else MUTED),
                align=PP_ALIGN.CENTER, space_after=0)
        if i < 2:
            a = txt(s, x + w, y + 0.78, 0.5, 0.3)
            put(a, "→", size=15, color=BLUE_MD, align=PP_ALIGN.CENTER, space_after=0)
        x += w + 0.5

    put(txt(s, ML, 6.35, CW, 0.5),
        "这条链路决定了文档写给谁看：运营看收益、质控看风险、服务看口径 —— 三个视角缺一不可。",
        size=13, color=DARK, space_after=0)
    footer(s, 4, TOTAL)
    note(s, """
需求不是我坐在电脑前想出来的。Discovery Lab 这个板块本身就是一套访谈工具，
我按它对 6 个岗位逐一提问，最后拿到 35 条事实，每条都带原话和证据编号。

这里有个关键：我**没有**改写原话。原因很实在 —— 访谈原话里藏着大量限定条件，
一旦翻译成"需求描述"，那些限定就没了，后面设计就会跑偏。

屏幕右边这条决策链路是事实 f04 给的：运营主任推立项，质控专员可以因为关键风险
否决上线，服务主管参与结果验收。这一条非常重要 —— 它决定了我的文档不能只写给
一个人看。运营看收益、质控看风险、服务看口径，三个视角缺一不可，
少任何一个，试点都过不了会签。
""")

    # ---- 5 六个角色 -------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "六个角色 · 谁说了算", "03 需求")
    table(s,
          ["编号", "角色", "姓名", "他/她真正关心什么", "能否否决上线"],
          [
              ["R1", "门诊运营主任", "顾明岚", "目标、预算、立项", "立项发起人"],
              ["R2", "导诊护士", "林亦舟", "现场怎么顺手、别背锅", "否"],
              ["R3", "排班管理员", "唐映秋", "规则版本、交接留痕", "否"],
              ["R4", "门诊系统工程师", "秦芮", "数据能不能接、有没有权限", "否"],
              ["R5", "医疗质控专员", "傅景", "风险、审计、留存", "** 可以否决（关键风险）**"],
              ["R6", "患者服务主管", "叶书", "指标口径、投诉处理", "参与服务结果验收"],
          ],
          widths=[0.7, 1.5, 0.9, 4.2, 2.6],
          size=13, head_size=13, row_h=0.42)
    put(txt(s, ML, 5.15, CW, 0.9),
        "R5 是全篇最需要盯住的人：质控专员能否决上线，所以「急症一律转人工」"
        "和「每条建议可追溯」不是加分项，是通行证。",
        size=13.5, color=DARK, space_after=4)
    put(txt(s, ML, 5.62, CW, 0.5),
        "R2 是每天真正用它的人：她不愿意为了看建议而离开现有终端 "
        "—— 这一条直接决定了 MVP 的形态。",
        size=12.5, color=MUTED, space_after=0)
    footer(s, 5, TOTAL)
    note(s, """
这六个角色不是凑数，他们各自卡着项目的一个环节。

R1 顾主任给目标和预算：候诊中位数从 68 分钟降到 40 分钟，爽约率从 19% 降到 10%，
首期预算 16 万。R5 傅景是医疗质控专员 —— 他是唯一能一票否决的人。
这一条我在设计时反复掂量：只要有一条建议查无实据，或者系统敢对急症患者给出
"预计还要等 12 分钟"这种承诺，这个试点就过不了质控关。

R2 林护士是每天真正用它的人。她在访谈里说得很直白：高峰期只能使用现有终端，
离开业务现场去补录会延误处理。这句话我记下来了 —— 它直接决定了我的 MVP 输出
是一个静态 HTML 文件，而不是又一个需要登录的新 App。
能在护士站那台老机器上打开，比什么都重要。
""")

    # ---- 6 现场三句原话 ---------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "决定项目形态的三句话", "03 需求")
    quotes = [
        ("f00", "门诊运营主任 · 顾明岚",
         "候诊中位数 68 分钟，报告说 25 分钟 —— 目标 40 分钟；爽约率 19%，目标 10%",
         "指标口径先打架"),
        ("f10", "导诊护士 · 林亦舟",
         "迟到患者与现场加号混在队列里，护士反复解释次序",
         "解释没有统一口径"),
        ("f50 / f53", "患者服务主管 · 叶书",
         "患者以到院算等待，叫号系统以签到算等待，运营以预约时间算等待",
         "三种口径并存"),
    ]
    y = TOP + 0.05
    for fid, who, q, tag in quotes:
        rect(s, ML, y, CW, 1.34, BLUE_LT)
        rect(s, ML, y, 0.05, 1.34, BLUE)
        t = txt(s, ML + 0.34, y + 0.16, 1.44, 0.36)
        put(t, fid, size=15, bold=True, color=BLUE, space_after=0)
        t = txt(s, ML + 1.95, y + 0.18, 3.2, 0.32)
        put(t, who, size=12.5, color=MUTED, space_after=0)
        t = txt(s, ML + 0.34, y + 0.62, CW - 2.6, 0.5)
        put(t, q, size=15.5, bold=True, color=DARK, space_after=0)
        t = txt(s, SW - ML - 2.5, y + 0.66, 2.2, 0.34)
        put(t, tag, size=12, color=AMBER, align=PP_ALIGN.RIGHT, space_after=0)
        y += 1.5
    footer(s, 6, TOTAL)
    note(s, """
我把 35 条事实浓缩成这三句，因为它们分别指向三个不同层面的问题 ——
而且这三个层面，恰好是三个不同的角色提出的。

第一句是运营主任给的：报告说候诊 25 分钟，实际中位数 68 分钟。
注意这不是数据错误，是**统计口径不同**。所以我说这不是数据质量问题，是立场问题。

第二句是护士：她每天要反复解释次序。这是**解释缺位** —— 她有判断，但没有能拿出来的依据。

第三句最狠：同样一段等待，三个部门三个数。这不是谁算错了，是各自站在自己的立场上定义"等待"。

后面所有的设计，都是为了让这三句话有统一的答案。
""")

    # ---- 7 现状流程 -------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "现状流程（AS-IS）", "04 现状")
    img = os.path.join(ROOT, "docs", "images", "flow-current.png")
    h = 5.35
    w = h * 1440 / 2412
    s.shapes.add_picture(img, Inches(ML), Inches(TOP - 0.02), height=Inches(h))
    rx = ML + w + 0.34
    rw = SW - ML - rx
    put(txt(s, rx, TOP, rw, 0.4), "主流程（事实 f01）",
        size=14, bold=True, color=BLUE, space_after=0)
    bullets(s, [
        (0, "预约 → 到院登记 → 分诊 → 候诊 → 接诊 → 检查交接"),
        (0, "退回上一节点时必须保留原因，不许只写「已处理」（f20）"),
        (0, "四个节点责任人分散在三个人身上（f20 / f21）"),
        (0, "没有统一视图：预约平台、HIS、叫号系统各管一段（f30）"),
        (0, "解释次序靠护士的记忆与个人便签（f10 / f14）"),
    ], left=rx, top=TOP + 0.52, width=rw, size=13.5, l2=12, gap=7)
    footer(s, 7, TOTAL)
    note(s, """
左边是现状流程图。我先讲流程本身：预约、到院登记、分诊、候诊、接诊、检查交接。
这是访谈里两个角色（运营主任 f01、排班管理员 f20）分别确认过的，说明流程本身
在院内是有共识的。

真正的问题不在这条线，而在线外面的东西：

第一，退回上一节点时只写"已处理"，不留原因。这是排班管理员明确提的 ——
流程能倒回去，但倒回去的原因没人记。

第二，四个节点的责任人分散在三个人身上，交接靠口头。

第三，三个系统各管一段，谁也没有全貌。

第四，也是最要命的 —— 解释次序这件事，靠护士的记忆和她自己的便签。
""")

    # ---- 8 四个症结 -------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "四个症结 · 以及为什么先做基线", "04 现状")
    cards = [
        ("没有基线", "f01",
         "管理层还没有分别量出每个节点的等待和处理时间。\n"
         "→ 现在不能承诺「缩短 X 分钟」，因为还没有可对比的基线。"),
        ("三系统孤岛", "f30",
         "预约平台、HIS、叫号系统账号权限独立维护，\n"
         "业务状态没有统一视图。"),
        ("关键信息在便签里", "f14",
         "同事常把关键说明留在个人便签或群里再补录，\n"
         "这些说明没有随单据交接。"),
        ("异常不留痕", "f20 / f11",
         "退回只写「已处理」；医生临时处理急诊，\n"
         "排班未同步，患者却已收到准点通知。"),
    ]
    x = ML
    w = (CW - 0.3) / 2
    h = 2.2
    for i, (t, fid, d) in enumerate(cards):
        top = TOP + 0.05 if i < 2 else TOP + 0.05 + h + 0.28
        cx = ML + (i % 2) * (w + 0.3)
        rect(s, cx, top, w, h, BLUE_LT)
        rect(s, cx, top, 0.045, h, BLUE)
        put(txt(s, cx + 0.28, top + 0.2, w - 0.5, 0.4), t,
            size=18, bold=True, color=DARK, space_after=0)
        put(txt(s, cx + 0.28, top + 0.68, w - 0.5, 0.3), "依据 " + fid,
            size=11, color=BLUE, space_after=0)
        tb = txt(s, cx + 0.28, top + 1.1, w - 0.55, h - 1.25)
        for k, line in enumerate(d.split("\n")):
            put(tb, line, size=12.5,
                color=(DARK if line.startswith("→") else MUTED), space_after=3)
    rect(s, ML, 6.32, CW, 0.56, WHITE, LINE)
    put(txt(s, ML + 0.24, 6.44, CW - 0.5, 0.4),
        "第一阶段必须先做基线测量，再谈优化 —— 这就是本 MVP 以「回放」形态存在的直接原因。",
        size=13.5, bold=True, color=BLUE, space_after=0)
    footer(s, 8, TOTAL)
    note(s, """
把访谈读完之后，我归纳出四个症结。它们的共同点是：**都不靠加一个系统解决**。

第一个最容易被忽略 —— 院方连每个节点各花多久都没量过。
这意味着"帮你缩短 20 分钟"这句话现在根本说不出口，因为你没有基线可以对比。
所以我第一阶段做的是"回放"，不是"优化"。先把数字算出来，再谈改进。

剩下三个：系统孤岛、信息在便签里、异常不留痕。
这三条看着是技术问题，其实都是**责任链条断裂** —— 交接没留痕、说明没跟着单据走、
退回没说原因。所以我的方案里，审计和留痕不是"合规负担"，它就是产品本身。
""")

    # ---- 9 洞察① 三套口径 -------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "洞察 ① · 三套「等待」口径是最大的隐性冲突", "05 洞察")
    table(s,
          ["部门 / 角色", "等待起点", "倾向的结果", "本项目处理"],
          [
              ["患者", "到院", "最长", "三套并存，分别记录"],
              ["叫号系统", "签到", "居中", "三套并存，分别记录"],
              ["运营", "预约时间", "最短", "三套并存，分别记录"],
          ],
          widths=[2.0, 1.6, 1.7, 4.5],
          size=13.5, head_size=13.5, row_h=0.46)
    rect(s, ML, 3.55, CW, 1.15, BLUE_LT)
    put(txt(s, ML + 0.3, 3.72, CW - 0.6, 0.4),
        "这不是数据质量问题，是立场问题。", size=17, bold=True, color=BLUE, space_after=0)
    put(txt(s, ML + 0.3, 4.18, CW - 0.6, 0.5),
        "所以方案不能「选一个正确的」，必须三套并存并明示差异 —— "
        "MVP 的 quality.wait_origin_report() 就干这个。\n"
        "谁要是偷偷合并成一个数，试点验收那天一定吵架。",
        size=13, color=DARK, space_after=0)
    put(txt(s, ML, 5.05, CW, 0.4), "事实依据：f50 / f53", size=11.5, color=MUTED, space_after=0)
    footer(s, 9, TOTAL)
    note(s, """
第一条洞察，也是我认为这次作业里最有价值的一条。

同样一个患者，同样一段等待，三个部门算出三个数：患者按到院算，最长；
叫号系统按签到算，居中；运营按预约时间算，最短。

请注意我的判断 —— 这**不是**数据质量问题，是立场问题。
每个部门都没算错，他们只是站在自己需要负责的那个口径上。

所以方案不能"选一个正确的"。一旦你偷偷合并成一个数，
试点验收那天三方一定吵架，而且吵的是数据不是方案。

我的做法是让三套口径并存、并明示差异，代码里专门有个
wait_origin_report 来量化"三个口径差多少"。
把分歧摆到台面上，而不是替谁做决定。
""")

    # ---- 10 洞察② 脏数据隔离 ----------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "洞察 ② · 脏数据必须隔离，而不是修复", "05 洞察")
    put(txt(s, ML, TOP, CW, 0.4), "访谈点名的三类脏数据（事实 f31）",
        size=14.5, bold=True, color=BLUE, space_after=0)
    for i, tag in enumerate(["签到重复", "叫号遗漏", "等待时间起点不统一"]):
        cx = ML + i * (CW / 3)
        rect(s, cx + 0.04, TOP + 0.5, CW / 3 - 0.16, 0.62, BLUE_LT)
        put(txt(s, cx + 0.04, TOP + 0.68, CW / 3 - 0.16, 0.4), tag,
            size=14.5, bold=True, color=DARK, align=PP_ALIGN.CENTER, space_after=0)

    put(txt(s, ML, TOP + 1.4, CW, 0.4), "规定动作（事实 f33）",
        size=14.5, bold=True, color=BLUE, space_after=0)
    bullets(s, [
        (0, "先校验「号源、医生排班、签到与叫号时间、分诊规则」里的主编号、事件时间、版本字段"),
        (0, "有歧义的记录进入人工修复队列，不进入自动推荐样本"),
        (1, "代码落实：quality.check() 产出的问题分「阻断」「提示」两级"),
        (1, "被标「阻断」的记录不参与任何建议计算 —— 宁可少给几条，也不给一条查无实据的"),
    ], top=TOP + 1.92, size=14, l2=12.5, gap=8)

    rect(s, ML, 5.35, CW, 1.0, BLUE_LT)
    put(txt(s, ML + 0.3, 5.52, CW - 0.6, 0.7),
        "这条决定了 MVP 的分层：先体检，再建议。"
        "因为一条查不到依据的建议，比没有建议更糟 —— 它会让护士背锅。",
        size=14, bold=True, color=BLUE, space_after=0)
    footer(s, 9 + 1, TOTAL)
    note(s, """
第二条洞察来自系统工程师秦芮。她在访谈里直接点名了三类脏数据：
签到重复、叫号遗漏、等待时间起点不统一。

而排班管理员那边给出了处理原则（f33）：有歧义的记录进人工修复队列，
**不进入自动推荐样本**。

这句话我照着做进了代码：质量检查的输出分「阻断」和「提示」两级，
被标阻断的记录不参与任何建议计算。

为什么要这么狠？因为一条查不到依据的建议，比没有建议更糟。
护士拿着它去跟患者解释，解释错了，锅是她的。
所以我的原则是：宁可少给几条建议，也绝不给一条查无实据的建议。
""")

    # ---- 11 洞察③ 让位上限 -----------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "洞察 ③ · 让位必须有上限", "05 洞察")
    bullets(s, [
        (0, "起因：只做「迟到者让出波次」这一条规则，队尾的人会被无限往后推"),
        (1, "MVP 早期回放里出现过单个患者等待 200 分钟以上 —— 规则越对，个例越惨"),
        (0, "机制：defer_protect_min（默认 45 分钟）"),
        (1, "等待超过阈值就自动转回正常次序，并且明确告诉患者「已转为正常次序」"),
        (0, "边界：这不是给迟到者的奖励，是把最费口舌的那件事制度化"),
        (1, "护士不用再临场判断「这次要不要通融」，规则替她挡住压力"),
        (0, "同类约束：急症 EMERGENCY 不参与任何排序；weight 只在同一带内比较，不跨带（f40）"),
    ], size=14.5, l2=12.5, gap=8)

    rect(s, ML, 4.85, CW, 1.5, BLUE_LT)
    put(txt(s, ML + 0.3, 5.02, CW - 0.6, 0.4),
        "为什么 weight 不能跨带比较", size=14.5, bold=True, color=BLUE, space_after=0)
    put(txt(s, ML + 0.3, 5.45, CW - 0.6, 0.85),
        "如果把「迟到 15 分」和「急症 100 分」放进同一个分值体系排序，"
        "就等于在数值上默认了「某种情况下迟到可以压过急症」——\n"
        "而 f40 明确禁止这种可能。所以权重只在带内生效，带与带之间是硬隔离。",
        size=13, color=DARK, space_after=0)
    footer(s, 11, TOTAL)
    note(s, """
第三条洞察是我自己踩坑踩出来的，值得单独讲。

我一开始只做了"迟到者让出波次"这一条规则，逻辑上完全正确。
但回放跑出来，有个患者等了 200 多分钟 —— 因为前面不断有迟到的人插进来，
他就被无限往后推。规则越正确，个例越惨。

所以加了 defer_protect_min，默认 45 分钟：等超过 45 分钟就自动转回正常次序，
并且明确告诉患者"您已转为正常次序"。

这里我要强调一句：这不是给迟到者的奖励。它的真正作用，
是把"护士要不要通融"这个最费口舌的临场判断，变成了一条制度。
护士不用再顶着患者的压力做决定，规则替她挡住了。

同类约束还有一条：规则权重的比较只在同一个优先级带内部生效，
绝不跨带。因为一旦跨带，就等于在数值上默认了"某种情况迟到可以压过急症"，
而 f40 是明令禁止的。
""")

    # ---- 12 洞察④ 核心 ----------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "洞察 ④ · 纯排序救不了候诊长度（核心结论）", "05 洞察")
    rect(s, ML, TOP, CW, 0.62, BLUE_LT)
    put(txt(s, ML + 0.28, TOP + 0.17, CW - 0.5, 0.4),
        "前提（医生从不空等）：  Σ等待时间 = Σ开始时刻 − Σ到达时刻  =  与排序方式无关的常数",
        size=14.5, bold=True, color=BLUE, space_after=0)
    table(s,
          ["策略", "候诊中位数", "平均候诊", "最长候诊", "叫空号"],
          [
              ["现状 · 按号序叫号", "47.5 分钟", "46.9 分钟", "130 分钟", "25 次"],
              ["建议策略 · 动态排序", "19.5 分钟", "38.4 分钟（−18.1%）", "155 分钟", "0 次"],
              ["参考线 · 纯先到先看", "34.0 分钟", "39.2 分钟", "112 分钟", "0 次"],
          ],
          widths=[3.1, 1.9, 2.9, 1.7, 1.3],
          top=TOP + 0.85, size=13.5, head_size=13, row_h=0.46,
          highlight={1: GREEN},
          aligns=[PP_ALIGN.LEFT] + [PP_ALIGN.CENTER] * 4)
    bullets(s, [
        (0, "平均候诊 −18.1%，已贴着参考线（相差 0.8 分钟/人）→ 排序能拿的空间基本到顶"),
        (1, "想再往下压，只能加号源或改排班，继续调规则是在浪费时间"),
        (0, "中位降了 58.9%，但含「转移」成分，不能直接当净收益汇报"),
        (0, "最长等待反而变长：130 → 155 分钟 —— 迟到与加号被有意识地往后放"),
        (1, "这部分人替大家承担了成本。这个代价要不要接受，是院方的管理决定"),
    ], top=TOP + 2.85, size=14, l2=12.5, gap=7)
    footer(s, 12, TOTAL)
    note(s, """
这一页是整份作业的核心，请老师们给我两分钟。

这条洞察**不在访谈里**，是我从数据里算出来的，但它决定了整个方案能不能兑现承诺。

在"医生从不空等"的前提下，Σ等待时间 = Σ开始时刻 减 Σ到达时刻，
这是一个与排序方式无关的常数。换句话说：**纯排序只能把等待从一群人转移给另一群人，
它不改变总量。**

那什么能改变总量？只有减少吞吐损失 —— 也就是那个 19% 爽约率造成的叫号空转。
现状叫号机认号不认人，叫到空号就干等，一次浪费顺着队列传给后面所有人。

我用三种策略跑了同一批到达过程：现状平均 46.9 分钟，建议策略 38.4 分钟，
降了 18.1%。而"纯先到先看"的理论参考线是 39.2 分钟 ——
建议策略已经比它还好 0.8 分钟。

结论是：**排序能拿的空间基本到顶了**，再想往下压只能加号源或改排班。

这个结论比"我们能降 40%"有用得多，也比它诚实。我还要说一句代价：
最长等待反而从 130 分钟涨到 155 分钟，因为迟到和加号被有意识地往后放，
这部分人替大家承担了成本。这个代价要不要接受，是院方的管理决定，
不是算法能替谁拍板的。
""")

    # ---- 13 TO-BE --------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "转型后流程（TO-BE）", "06 方案")
    img = os.path.join(ROOT, "docs", "images", "flow-future.png")
    h = 5.35
    w = h * 1440 / 2718
    s.shapes.add_picture(img, Inches(ML), Inches(TOP - 0.02), height=Inches(h))
    rx = ML + w + 0.34
    rw = SW - ML - rx
    put(txt(s, rx, TOP, rw, 0.4), "四道闸门（每层都有事实依据）",
        size=14, bold=True, color=BLUE, space_after=0)
    bullets(s, [
        (0, "① 只读快照管道：预约平台 + HIS + 叫号系统按业务编号对齐，带时间戳与版本（f32 / f34）"),
        (0, "② 质量闸门：阻断 / 提示两级，有歧义记录不进建议（f33）"),
        (0, "③ 规则引擎：6 条规则，每条必带 evidence，否则不给合并（f15）"),
        (0, "④ 分带建议 → 人工复核 → 追加写审计（f44 / f45）"),
        (0, "降级：接口中断时用带时间戳的上一份快照，界面显示「暂未更新」（f35）"),
    ], left=rx, top=TOP + 0.5, width=rw, size=13.5, l2=12, gap=7)
    footer(s, 13, TOTAL)
    note(s, """
这是转型后的流程图。我把它拆成四道闸门，每一道都能指回一条事实。

第一道是只读快照管道：三个系统按业务编号对齐，每份数据都带时间戳和版本号。
第二道是质量闸门：有问题的记录在这里被拦下，不进建议。
第三道是规则引擎：六条规则，每条都必须带 evidence，没有证据的规则不给合并。
第四道是分带建议加人工复核，最后追加写进审计。

这里有个降级设计要特别提一下：接口断了怎么办？
答案是继续用带时间戳的上一份快照，界面上显示"暂未更新"。
为什么不直接停？因为现状是护士靠嘴解释，系统停了她照样要解释 ——
那不如让她看着一份过期的、但明确标注了过期的数据。
""")

    # ---- 14 一个节点的位移 -------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "两张图之差：一个节点的位移", "06 方案")
    b = txt(s, ML, TOP + 0.15, CW, 0.7)
    put(b, "判断权没有移动，移动的只是支撑判断的信息。",
        size=24, bold=True, color=BLUE, align=PP_ALIGN.CENTER, space_after=0)

    y = TOP + 1.35
    h = 1.75
    w = (CW - 0.5) / 2
    for i, (tag, who, desc) in enumerate([
        ("现状 AS-IS", "「解释次序」", "护士凭记忆临时拼凑\n依据散在三个系统里，拿不出来"),
        ("转型后 TO-BE", "「解释次序」", "护士照着统一口径念\n每条都带原始依据与快照版本"),
    ]):
        cx = ML + i * (w + 0.5)
        fill = BLUE_LT if i == 1 else WHITE
        rect(s, cx, y, w, h, fill, LINE)
        rect(s, cx, y, w, 0.045, BLUE_MD if i == 1 else MUTED)
        put(txt(s, cx + 0.3, y + 0.2, w - 0.6, 0.35), tag,
            size=13, bold=True, color=MUTED, space_after=0)
        put(txt(s, cx + 0.3, y + 0.62, w - 0.6, 0.45), who,
            size=20, bold=True, color=BLUE, space_after=0)
        tb = txt(s, cx + 0.3, y + 1.15, w - 0.6, 0.55)
        for k, line in enumerate(desc.split("\n")):
            put(tb, line, size=12.5, color=MUTED, space_after=2)
    rect(s, ML, 5.5, CW, 0.85, BLUE_LT)
    put(txt(s, ML + 0.3, 5.68, CW - 0.6, 0.55),
        "差别不在「加了几个系统」，而在这一个节点的位移："
        "专业分诊判断始终由医护确认（f05 / f40），系统只负责把依据摆到护士面前。",
        size=14.5, bold=True, color=BLUE, space_after=0)
    footer(s, 14, TOTAL)
    note(s, """
把两张图放在一起看，差别不在"加了几个系统"，而在**一个节点的位移**。

这个节点就是"解释次序"。

现状下，这件事是护士凭记忆临时拼凑 —— 她其实判断得不错，
但依据散在三个系统里，她拿不出来，患者不信。

转型后，这件事变成护士照着统一口径念 —— 判断还是她做，
但每条建议底下都压着原始依据和快照版本，她照着念就行。

所以我给这张 PPT 的标题是：**判断权没有移动，移动的只是支撑判断的信息。**

这一点非常重要，因为它回答了一个必然会被问到的问题：
"你们这个系统是不是在替医生做分诊？" —— 不是。
系统只负责把依据摆到护士面前，专业判断始终由医护确认。
""")

    # ---- 15 架构 ---------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "架构：四层，单向依赖", "06 方案")
    layers = [
        ("展示层", "io.render_dashboard()  →  out/dashboard.html（单文件、无外部资源）", BLUE),
        ("编排层", "main.py   check / snapshot / demo / serve", RGBColor(0x2E, 0x7C, 0xA8)),
        ("业务层", "core/queue.py（回放与排序）· core/rules.py（规则）· core/audit.py（审计）",
         RGBColor(0x3D, 0x99, 0xC4)),
        ("数据层", "utils/config.py · utils/io.py · utils/quality.py · core/models.py",
         RGBColor(0x5A, 0xB0, 0xD6)),
    ]
    y = TOP + 0.1
    for name, desc, color in layers:
        rect(s, ML, y, 1.5, 0.85, color)
        put(txt(s, ML, y, 1.5, 0.85, MSO_ANCHOR.MIDDLE), name,
            size=16, bold=True, color=WHITE, align=PP_ALIGN.CENTER, space_after=0)
        rect(s, ML + 1.5, y, CW - 1.5, 0.85, BLUE_LT)
        put(txt(s, ML + 1.78, y, CW - 2.1, 0.85, MSO_ANCHOR.MIDDLE), desc,
            size=13, color=DARK, space_after=0)
        if name != "数据层":
            a = txt(s, ML + 0.55, y + 0.85, 0.4, 0.22)
            put(a, "▲", size=9, color=MUTED, align=PP_ALIGN.CENTER, space_after=0)
        y += 1.06

    rect(s, ML, 5.55, CW, 1.15, WHITE, LINE)
    put(txt(s, ML + 0.3, 5.7, CW - 0.6, 0.9),
        "单向依赖是刻意的：业务层不认识 HTML，展示层不做决策。\n"
        "将来换成企业微信卡片或护士站大屏，规则代码一行都不用改。",
        size=13.5, color=DARK, space_after=0)
    footer(s, 15, TOTAL)
    note(s, """
架构上我做了四层，而且是严格的单向依赖。

展示层只管把东西画出来，输出的是一个单文件 HTML，没有任何外部资源引用 ——
这一点是为了院内网络环境准备的，离线双击就能开。

编排层是 CLI 入口，四个子命令。

业务层是核心：队列回放、规则、审计。

数据层是配置、读写、数据质量和模型。

单向依赖的意思是：业务层根本不知道 HTML 的存在，展示层也不做任何决策。
为什么要这么较真？因为一旦将来要换成企业微信卡片、或者护士站那块大屏，
我只改展示层，规则代码一行都不用动。这对一个要进医院的项目很重要 ——
你不知道下次要接的是什么终端。
""")

    # ---- 16 六条规则 -------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "规则引擎 · 每条规则必须有四样东西", "06 方案")
    table(s,
          ["code", "规则", "动作倾向", "依据"],
          [
              ["EMERGENCY", "急症标记 / 一级分诊", "**强制转人工，不参与排序**", "f40 / f42"],
              ["LATE_ARRIVAL", "迟到超过宽限 15 分钟", "让出当前波次", "f10 / f31"],
              ["WALK_IN", "现场加号混入预约队列", "标注来源与预计时段", "f10"],
              ["COMEBACK", "回诊患者（检查后复诊）", "优先复核带", "f01"],
              ["VULNERABLE", "高龄 ≥75 / 低龄 ≤6", "优先复核带", "脆弱人群保护"],
              ["DOCTOR_OVERRUN", "医生进度落后 >20 分钟", "更正预计时段，不承诺分钟", "f11 / f34"],
          ],
          widths=[1.9, 3.0, 4.1, 1.5],
          size=13, head_size=13, row_h=0.44)
    rect(s, ML, 4.6, CW, 1.65, BLUE_LT)
    put(txt(s, ML + 0.3, 4.76, CW - 0.6, 1.4),
        "code      机器可读代号，进审计\n"
        "label     人可读标签，上看板\n"
        "weight    仅用于带内排序，不对外宣称「风险分」\n"
        "evidence  可追溯到原记录 —— **没有 evidence 的规则不给合并**",
        size=13, color=DARK, space_after=0)
    footer(s, 16, TOTAL)
    note(s, """
规则引擎的设计有一条硬规矩：每条规则必须带四样东西。

code 是机器读的，进审计；label 是给人看的，上看板；weight 只在同一个优先级带内部
排序用；evidence 是可追溯到原记录的那句话。

这里最要紧的是 evidence —— 没有 evidence 的规则，不给合并。这条写在贡献指南里，
叫 R3。

为什么定这条规矩？因为事实 f15 里护士说了：建议必须显示对应原记录和待确认字段，
错误结果不能覆盖原记录。她要的不是一个结论，是**能拿出去给人看的依据**。

另外我再强调一下 weight 的作用范围：它只在带内排序，不对外宣称是"风险分"。
因为我们不做临床判断，一旦给出一个分数，外界就会按分数理解，那就越界了。
""")

    # ---- 17 MVP 四条命令 --------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "MVP · 四条命令，各自为谁服务", "06 方案")
    table(s,
          ["命令", "作用", "谁用"],
          [
              ["check", "数据质量体检：主编号、事件时间、版本字段校验，歧义记录隔离",
               "门诊系统工程师（f33）"],
              ["snapshot", "打印某一时刻的建议队列，纯文本，可直接贴进聊天窗口",
               "导诊护士快速核对"],
              ["demo", "全量回放，产出看板 / 清单 / JSON / 审计流水四样",
               "门诊运营主任看效果"],
              ["serve", "本地只读预览服务，浏览器里翻页", "试点现场宣讲"],
          ],
          widths=[1.5, 6.6, 3.6],
          size=13, head_size=13, row_h=0.5)
    put(txt(s, ML, 4.5, CW, 0.4), "产出四件", size=14.5, bold=True, color=BLUE, space_after=0)
    for i, (n, d) in enumerate([
        ("dashboard.html", "单文件看板，双击就能看，无需联网"),
        ("suggestions.csv", "次序建议清单，每条含规则依据与解释口径"),
        ("replay.json", "回放结果与指标，供程序化核对"),
        ("audit.jsonl", "审计流水：建议生成即留痕，追加写、不可覆盖"),
    ]):
        cx = ML + i * (CW / 4)
        rect(s, cx + 0.04, 5.0, CW / 4 - 0.16, 1.15, BLUE_LT)
        put(txt(s, cx + 0.22, 5.15, CW / 4 - 0.5, 0.35), n,
            size=12.5, bold=True, color=BLUE, space_after=0)
        put(txt(s, cx + 0.22, 5.5, CW / 4 - 0.5, 0.6), d,
            size=11, color=MUTED, space_after=0)
    footer(s, 17, TOTAL)
    note(s, """
MVP 一共四条命令，每条命令都对应一个具体的岗位。

check 给系统工程师用，做数据质量体检；snapshot 给护士用，打印某一时刻的建议队列，
纯文本可以直接贴进聊天窗口；demo 给运营主任看效果，跑全量回放；serve 用于试点现场宣讲。

跑完产出四样东西：单文件看板、建议清单、回放 JSON、审计流水。

这里有个刻意的设计：运行时**零第三方依赖**，只用标准库，Python 3.9 就能跑。
为什么要这么克制？因为院内装包要过审批。依赖越少，这个项目越容易真的进得去。
这不是技术洁癖，是交付考虑。
""")

    # ---- 18 看板 ----------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "看板长什么样", "06 方案")
    cols = [
        ("左侧 · 队列分带", BLUE, [
            "急症 · 转人工", "优先复核", "让出波次", "正常排队",
            "", "四条带硬隔离：带与带之间不做数值比较",
        ]),
        ("中间 · 建议卡", RGBColor(0x2E, 0x8B, 0xC8), [
            "每位患者一张卡", "", "必定带「依据」", "必定带「给患者的解释口径」",
            "", "例：考虑到年龄与行动情况，已为您做优先安排，"
                "当前前面还有 1 位。实际叫号以现场为准。",
        ]),
        ("右侧 · 边界面板", RGBColor(0x5A, 0xB0, 0xD6), [
            "数据截止时间", "人机协作边界", "转人工触发条件",
            "指标口径差值", "", "顶部永远显示数据截止时间 —— "
            "让护士回答患者前先确认数据新鲜度",
        ]),
    ]
    x = ML
    w = (CW - 2 * 0.3) / 3
    for title, color, lines in cols:
        rect(s, x, TOP + 0.05, w, 0.62, color)
        put(txt(s, x, TOP + 0.05, w, 0.62, MSO_ANCHOR.MIDDLE), title,
            size=15, bold=True, color=WHITE, align=PP_ALIGN.CENTER, space_after=0)
        rect(s, x, TOP + 0.67, w, 4.0, BLUE_LT)
        tb = txt(s, x + 0.24, TOP + 0.9, w - 0.48, 3.6)
        for k, line in enumerate(lines):
            if line == "":
                continue
            bullet = "▪" if k < 4 else None
            put(tb, line, size=12.5,
                color=(DARK if k < 4 else MUTED),
                bullet=bullet, space_after=6)
        x += w + 0.3

    rect(s, ML, 5.85, CW, 0.9, WHITE, LINE)
    put(txt(s, ML + 0.3, 6.0, CW - 0.6, 0.65),
        "关键取舍：所有「急诊 / 待复核」的卡片默认状态是「待人工确认」，"
        "必须有人点确认才流转（事实 f44：须标注触发原因、接手人和确认时间，"
        "不能只给一句模糊提醒）。",
        size=13.5, bold=True, color=BLUE, space_after=0)
    footer(s, 18, TOTAL)
    note(s, """
看板分三块。

左边是队列分带：急症转人工、优先复核、让出波次、正常排队。
这里的关键设计是四条带**硬隔离** —— 带与带之间不做数值比较，
急症永远在第一位且永不参与排序。

中间是建议卡，每位患者一张。每张卡底下必定压着两样东西：
一是"依据"，比如"预约 09:04，签到 09:13，年龄 78"；
二是"给患者的解释口径"，就是护士照着念的那句话。

右边是边界面板，放的是那些"不发生场景下不允许含糊"的东西：
数据截止时间、人机协作边界、转人工触发条件、以及三套口径的差值。

我要特别说一句关键取舍：所有急诊和待复核的卡片，默认状态都是"待人工确认"，
必须有人点了确认才流转。这是事实 f44 的要求 —— 转人工时要标注触发原因、
接手人和确认时间，不能只给一句模糊提醒。
""")

    # ---- 19 红线 ----------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "红线 · 明确不做什么", "06 方案")
    table(s,
          ["明确不做", "为什么", "依据"],
          [
              ["自动分诊 / 诊断 / 医嘱 / 处方",
               "范围限于「时间解释与队列信息辅助」，专业判断由医护确认", "f05"],
              ["写回 HIS / 预约平台 / 叫号系统",
               "接口权限为只读；任何写回都不在范围内", "f32"],
              ["实时秒级推送",
               "试点阶段每天两次授权更新，超时须标注「暂未更新」", "f34"],
              ["多院区 / 住院 / 医保结算",
               "超出首期试点范围（f05 明确两院区门诊先行）", "f05"],
              ["用节省工时直接推算 ROI",
               "收益须扣除维护与人工复核成本；本方案必然增加复核工时", "f03"],
          ],
          widths=[3.7, 5.9, 1.4],
          size=13, head_size=13, row_h=0.52,
          aligns=[PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.CENTER])
    rect(s, ML, 4.95, CW, 1.35, BLUE_LT)
    put(txt(s, ML + 0.3, 5.12, CW - 0.6, 1.1),
        "贡献指南里的两条硬性约束（代码评审一票否决）：\n"
        "  R1  任何情况下不得写回业务系统\n"
        "  R2  急症一律转人工，不得给出任何时间承诺",
        size=13.5, bold=True, color=BLUE, space_after=0)
    footer(s, 19, TOTAL)
    note(s, """
这一页是"不做什么"的清单。我认为对医疗项目来说，这一页比"做了什么"更重要。

不做自动分诊、诊断、医嘱、处方 —— 因为访谈里范围就定死了：时间解释与队列信息辅助，
专业判断由医护确认。

不写回 HIS、预约平台、叫号系统 —— 接口权限就是只读的，
而且一旦开了写接口，责任边界立刻模糊：数据错了算谁的？

不做实时秒级推送 —— 试点阶段每天两次授权更新，超时必须标注"暂未更新"。
这一条看着是技术限制，其实是保护：避免护士把历史快照当成实时承诺说出去。

最后一条最容易被注水：不用节省工时直接推算 ROI。
运营主任明确要求扣除维护与人工复核成本 —— 因为本方案**必然增加复核工时**。
它把"反复口头解释"的低价值时间，换成了"看一眼确认"的高价值时间，
但你不能说这是净省钱。

这五条我写进了贡献指南，R1 和 R2 是代码评审的一票否决项。
""")

    # ---- 20 行业 ----------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "行业：盘子、政策与我们切在哪", "07 商业化")
    table(s,
          ["年份", "2020", "2021", "2022", "2023", "2024", "2025E"],
          [
              ["规模（亿元）", "5.2", "8.4", "13.8", "22.4", "36.5", "**59.5**"],
              ["同比", "—", "+61.5%", "+64.3%", "+62.3%", "+62.9%", "+63.0%"],
          ],
          widths=[1.9, 1.5, 1.5, 1.5, 1.5, 1.5, 2.7],
          size=13, head_size=12.5, row_h=0.42,
          aligns=[PP_ALIGN.LEFT] + [PP_ALIGN.CENTER] * 6)
    bullets(s, [
        (0, "六年扩容逾十倍，2020–2025 复合增速约 62.8%；2026–2031 回落到约 21.5%"),
        (1, "增速回落是基数抬升的自然结果，不是需求萎缩 —— 但甲方会更抠 ROI"),
        (0, "采购逻辑已从「连通」转向「分析」与「运营效率」，我们卖的正是运营效率薄层"),
        (0, "政策抓手：智慧服务分级评估（可立项）、门诊质量管理 0.2% 导医配备（可测算）、"
            "DRG/DIP（成本核算压到门诊）"),
    ], top=TOP + 2.05, size=13.5, l2=12, gap=7)
    rect(s, ML, 5.9, CW, 0.85, BLUE_LT)
    put(txt(s, ML + 0.3, 6.06, CW - 0.6, 0.6),
        "关键数字：三级医院核心门诊模块部署率已超八成，但真正把数据用起来的不到两成。\n"
        "存量不是没有系统，是系统没被用起来 —— 我们要做的是激活，不是替换。",
        size=13.5, bold=True, color=BLUE, space_after=0)
    footer(s, 20, TOTAL)
    note(s, """
行业这块我讲三个数字就够了。

第一个是盘子：2020 年 5.2 亿，2025 年预计 59.5 亿，六年十倍，复合增速 62.8%。
但未来五年会回落到 21.5% —— 这不是需求萎缩，是基数抬高了。
对我们的含义是：高速增长的年份里甲方愿意为"故事"付钱，
增速回落的年份里甲方只认 ROI。所以我们的报价必须保守。

第二个是渗透率：三级医院核心门诊模块部署率超过八成，但真正把数据用起来的不到两成。
这句话我建议抄进每一份方案 —— **存量不是没有系统，是系统没被用起来**。
所以我们的定位是激活，不是替换，这跟访谈里 f05 的要求（并行试点不替换）完全对上。

第三个是政策抓手，它解决"钱从哪个科目出"的问题：
智慧服务分级评估让门诊有了独立立项的理由；
门诊质量管理规定要求按日均门诊量 0.2% 配备导医 —— 按日均 1600 人次算就是
3.2 个人力当量，我们的解释卡片替代的正是其中的"重复解释"部分。
""")

    # ---- 21 报价 / 里程碑 / 验收 -------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "报价、里程碑与验收口径", "07 商业化")
    table(s,
          ["阶段", "内容", "金额（元）", "周期"],
          [
              ["**A 试点**", "集成 + 规则 + 看板 + 培训 + 验收", "**160,000**", "4 周"],
              ["B 推广", "扩展至全门诊科室", "每科室 20,000–40,000 / 年", "达标次年"],
              ["C 规模化", "按年门诊量阶梯计费", "面议", "—"],
          ],
          widths=[1.7, 5.2, 3.6, 1.9],
          size=12.5, head_size=12.5, row_h=0.4)
    table(s,
          ["周次", "目标", "参与方"],
          [
              ["W1", "基线测量完成（节点耗时报告、三套口径对照表）", "排班管理员、系统工程师"],
              ["W2", "只读对接 + 脏数据清单", "系统工程师、质控专员"],
              ["W3", "并行运行启动（看板上线、首周建议清单、培训）", "导诊护士、排班管理员"],
              ["W4", "稳定运行与验收（指标对比、审计样本、验收报告）", "全体 + 运营主任签核"],
          ],
          widths=[1.1, 7.3, 4.0],
          top=TOP + 2.05, size=12, head_size=12, row_h=0.4)
    put(txt(s, ML, 6.35, CW, 0.55),
        "付款 40 / 30 / 20 / 10；不含：写回 · 诊断 · 加号审批 · 硬件 · 机房改造 · 等保评测。"
        "口径一旦在验收前改写，数据就失去意义 —— 这一条请在合同里写死。",
        size=12.5, color=MUTED, space_after=0)
    footer(s, 21, TOTAL)
    note(s, """
报价三段式：试点固定总价 16 万，与访谈里运营主任给的首期预算完全一致；
推广按科室年订阅，每科室 2 到 4 万；规模化按门诊量阶梯。

为什么要 40% 预付款？因为行业平均应收账款周转天数已经从 2020 年的 170 天
拉长到 220 天以上。我们这种小额试点没有现金流去扛两百天账期。
这一条写在明处，比事后催款体面。

里程碑四周：第一周建基线，第二周只读对接加脏数据清单，
第三周并行运行，第四周验收。每周收集三个岗位的误判例子，
**先复测指标再改规则版本** —— 这是 f55 的要求，它防的是团队为了数字好看反复调参。

最后一句请老师们记住：**口径一旦在验收前改写，数据就失去意义**。这一条建议写进合同。
""")

    # ---- 22 已知局限 -------------------------------------------------------
    s = prs.slides.add_slide(blank)
    header(s, "已知局限 · 诚实清单", "08 复盘")
    bullets(s, [
        (0, "data/appointments.csv 是合成数据，指标绝对值不具参考意义；"
            "只有相对差值代表规则的作用方向"),
        (0, "DOCTOR_OVERRUN 目前是静态参数注入，未实现真正的医生进度预测"),
        (0, "队列模型是单医生单队列串行，未建模检查返回后再候诊的二次排队"),
        (0, "看板是静态 HTML，没有实现「护士点击确认」的写回"),
        (1, "这符合只读约束，但也意味着复核动作需在纸质或原系统完成 —— 是真实的使用成本"),
        (0, "规则权重由业务判断设定，尚未经过真实数据标定"),
    ], size=14, l2=12.5, gap=8)
    rect(s, ML, 5.45, CW, 1.2, BLUE_LT)
    put(txt(s, ML + 0.3, 5.62, CW - 0.6, 0.95),
        "第 1 条和第 5 条最重要：不要拿着「中位下降 X%」去汇报。\n"
        "它证明的是「这套规则在当前假设下会这样排序」，不是「上线就能降 X%」。",
        size=14, bold=True, color=RED, space_after=0)
    footer(s, 22, TOTAL)
    note(s, """
最后一页是局限清单，我主动讲，不等老师问。

第一，数据是合成的。指标的绝对值没有参考意义，
真正有意义的只有"先到先看"和"建议策略"之间的相对差值 —— 它代表规则的作用方向。

第二，医生进度落后这条规则目前是静态参数注入，不是真正的预测。

第三，队列模型只做了单医生单队列，没有建模检查回来之后的二次排队。

第四，看板是静态的，没有实现"护士点击确认"的写回。这符合只读约束，
但代价是复核动作还得在纸质或原系统完成 —— 这是真实的使用成本，不能假装不存在。

第五，规则权重是我按业务判断设的，没有经过真实数据标定。

第一条和第五条最重要，我再说一遍：**不要拿着"中位下降 X%"去汇报**。
它证明的是"这套规则在当前假设下会这样排序"，不是"上线就能降 X%"。
""")

    # ---- 23 结语 ----------------------------------------------------------
    s = prs.slides.add_slide(blank)
    rect(s, 0, 0, SW, SH, BLUE_DK)
    rect(s, 0, 0, 0.16, SH, BLUE_MD)
    b = txt(s, 1.0, 1.5, 11.4, 0.9)
    put(b, "三句话收尾", size=36, bold=True, color=WHITE, space_after=0)
    rect(s, 1.0, 2.5, 3.0, 0.03, BLUE_MD)
    lines = [
        "我们只解决三件事 —— 谁先看、为什么、等多久",
        "系统只给建议，决定永远由人来做",
        "先建基线再谈优化；口径写死再谈收益",
    ]
    y = 2.95
    for i, line in enumerate(lines):
        rect(s, 1.0, y, 11.3, 0.82, RGBColor(0x1A, 0x4E, 0x74))
        put(txt(s, 1.32, y + 0.16, 0.6, 0.5), f"0{i + 1}",
            size=20, bold=True, color=RGBColor(0x7F, 0xB6, 0xDB), space_after=0)
        put(txt(s, 2.05, y + 0.2, 9.8, 0.5), line,
            size=19, color=WHITE, space_after=0)
        y += 1.0
    b = txt(s, 1.0, 6.3, 11.4, 0.5)
    put(b, "github.com/kekekekeke171717/- · Apache-2.0 · 合成数据，不含任何真实患者信息",
        size=11.5, color=RGBColor(0x8A, 0xA8, 0xBE), space_after=0)
    note(s, """
最后用三句话收尾。

第一句：我们只解决三件事 —— 谁先看、为什么、等多久。不多做一点点。

第二句：系统只给建议，决定永远由人来做。急症一律转人工，建议永不自动生效。

第三句：先建基线再谈优化，口径写死再谈收益。这两条顺序反了，项目迟早要还。

项目已经在 GitHub 上开源，Apache-2.0 许可，用的是合成数据，
不含任何真实患者信息。

我的汇报到这里，请各位老师批评指正。
""")


# ---------------------------------------------------------------- 演讲稿导出

# 每页建议时长（秒）。总计约 17 分钟，留了缓冲；★ 为重点页，不要压缩。
TIME = {1: 30, 2: 70, 3: 20, 4: 45, 5: 35, 6: 60, 7: 45, 8: 35,
        9: 55, 10: 30, 11: 35, 12: 100, 13: 45, 14: 60, 15: 30,
        16: 30, 17: 35, 18: 40, 19: 45, 20: 35, 21: 45, 22: 45, 23: 30}
KEY = {2, 6, 12, 14, 19, 22}          # 重点页


def dump_script(path_md: str, path_docx: str) -> None:
    prs2 = Presentation()
    build(prs2)

    paras: list[tuple[str, str]] = []
    for i, s in enumerate(prs2.slides, start=1):
        title = ""
        for sh in s.shapes:
            if sh.has_text_frame and sh.text_frame.text.strip():
                title = sh.text_frame.text.strip().split("\n")[0]
                break
        body = ""
        if s.has_notes_slide:
            body = "\n".join(x.strip() for x in
                             s.notes_slide.notes_text_frame.text.split("\n")).strip()
        paras.append((title, body))

    total = sum(TIME.values())
    lines = ["# 答辩演讲稿 · 门诊预约与分诊协作助手（MVP）", ""]
    lines.append("> 与 `答辩演示.pptx` 逐页对应 —— 讲稿同时写在该页的**备注栏**里，"
             "放映时用「演示者视图」即可看到。")
    lines.append(f"> 完整稿约 **{total // 60} 分钟**（正常语速约 220 字/分钟）。"
             "★ 为重点页，时间不够时优先保留。")
    lines.append("")
    lines.append("## 时间预算")
    lines.append("")
    lines.append("| 页 | 内容 | 建议时长 |")
    lines.append("|---:|---|---:|")
    for i, (t, _) in enumerate(paras, start=1):
        star = " ★" if i in KEY else ""
        lines.append(f"| {i} | {t}{star} | {TIME[i]} 秒 |")
    lines.append(f"| **合计** | | **{total // 60} 分 {total % 60} 秒** |")
    lines.append("")
    lines.append("> 15 分钟版本怎么剪：第 5、8、15、16、18 页各压到 15 秒以内，"
             "第 20、21 页合并成一页讲。第 12 页不要剪，它是全篇的支点。")
    lines.append("")
    for i, (title, body) in enumerate(paras, start=1):
        star = " ★ 重点" if i in KEY else ""
        lines.append("---")
        lines.append("")
        lines.append(f"## 第 {i} 页 · {title}{star}")
        lines.append("")
        lines.append(f"*建议 {TIME[i]} 秒*")
        lines.append("")
        lines.append(body)
        lines.append("")

    with open(path_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt as DPt, RGBColor as DColor

        doc = Document()
        st = doc.styles["Normal"]
        st.font.name = "Microsoft YaHei"
        st.font.size = DPt(11)
        st.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

        h = doc.add_heading("答辩演讲稿 · 门诊预约与分诊协作助手（MVP）", level=0)
        p = doc.add_paragraph()
        r = p.add_run("与 答辩演示.pptx 逐页对应；每页讲稿也已写入该页备注栏，"
                      "放映时用「演示者视图」查看。通篇约 15 分钟。")
        r.font.size = DPt(10.5)
        r.font.color.rgb = DColor(0x6B, 0x7C, 0x8C)
        doc.add_paragraph()

        for i, (title, body) in enumerate(paras, start=1):
            star = " ★ 重点" if i in KEY else ""
            hh = doc.add_heading(f"第 {i} 页 · {title}{star}", level=1)
            for run in hh.runs:
                run.font.color.rgb = DColor(0x1B, 0x5E, 0x8C)
            tip = doc.add_paragraph()
            tr = tip.add_run(f"建议 {TIME[i]} 秒")
            tr.font.size = DPt(9.5)
            tr.font.color.rgb = DColor(0x6B, 0x7C, 0x8C)
            tip.paragraph_format.space_after = DPt(4)
            for para in body.split("\n"):
                if para.strip():
                    doc.add_paragraph(para.strip())
            doc.add_paragraph()

        doc.save(path_docx)
        print(f"  -> {path_docx}")
    except Exception as exc:              # pragma: no cover
        print(f"  (跳过 docx：{exc})")


def main() -> None:
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    build(prs)

    out_pptx = os.path.join(ROOT, "docs", "答辩演示.pptx")
    prs.save(out_pptx)
    print(f"  -> {out_pptx}  ({len(prs.slides.__iter__.__self__._sldIdLst)} 页)")

    dump_script(os.path.join(ROOT, "docs", "答辩演讲稿.md"),
                os.path.join(ROOT, "docs", "答辩演讲稿.docx"))


if __name__ == "__main__":
    main()
