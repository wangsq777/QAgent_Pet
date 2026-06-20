#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QAgent Pet - AI产品经理作品集生成脚本
纯Python标准库实现，无需安装任何外部依赖
生成目标：秋招AI产品经理岗位能力证明
"""

import zipfile
import os
import uuid
import datetime
from xml.etree.ElementTree import Element, SubElement, tostring

# ============================================================
# OOXML 工具函数
# ============================================================

def qname(tag):
    """返回带命名空间的XML标签"""
    return f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{tag}"

def r_qname(tag):
    return f"{{http://schemas.openxmlformats.org/officeDocument/2006/relationships}}{tag}"

def write_xml_str(elem):
    """将Element写入为带XML声明的UTF-8字节串"""
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + tostring(elem, encoding='utf-8')

# ============================================================
# DOCX 构建器
# ============================================================

class DocxBuilder:
    def __init__(self):
        self.files = {}  # {path_in_zip: bytes}
        self.rels = {}   # {part_name: [(rel_id, rel_type, target)]}
        self.content_types = {}  # {ext/partname: content_type}
        self.next_img_id = 1

    def add_file(self, path, content_bytes, content_type=None):
        self.files[path] = content_bytes
        if content_type:
            self.content_types[path] = content_type

    def add_rel(self, part, rel_id, rel_type, target):
        if part not in self.rels:
            self.rels[part] = []
        self.rels[part].append((rel_id, rel_type, target))

    def build(self, output_path):
        # [Content_Types].xml
        ct = Element("{http://schemas.openxmlformats.org/package/2006/content-types}Types")
        defaults = {
            'rels': 'application/vnd.openxmlformats-package.relationships+xml',
            'xml': 'application/xml',
        }
        for ext, ctype in defaults.items():
            d = SubElement(ct, "{http://schemas.openxmlformats.org/package/2006/content-types}Default")
            d.set("Extension", ext)
            d.set("ContentType", ctype)
        for part, ctype in self.content_types.items():
            ov = SubElement(ct, "{http://schemas.openxmlformats.org/package/2006/content-types}Override")
            ov.set("PartName", part if part.startswith("/") else "/" + part)
            ov.set("ContentType", ctype)
        self.add_file("[Content_Types].xml", write_xml_str(ct))

        # Relationships
        for part, rel_list in self.rels.items():
            rels_elem = Element("{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
            for rid, rtype, target in rel_list:
                r = SubElement(rels_elem, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
                r.set("Id", rid)
                r.set("Type", rtype)
                r.set("Target", target)
            rel_path = part.rstrip("/") + "/_rels/.rels" if part != "/" else "_rels/.rels"
            self.add_file(rel_path, write_xml_str(rels_elem))

        # 打包ZIP
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path, data in self.files.items():
                zf.writestr(path, data)

# ============================================================
# WordprocessingML 构建助手
# ============================================================

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

def w(tag):
    return f"{{{W}}}{tag}"

def make_element(tag, attrib=None, text=None):
    el = Element(tag, attrib or {})
    if text is not None:
        el.text = text
    return el

def add_run(para, text, bold=False, size=24, color="000000", font="Arial", italic=False, underline=False):
    """向段落添加一个文本运行"""
    r = SubElement(para, w("r"))
    rPr = SubElement(r, w("rPr"))
    if bold:
        b = SubElement(rPr, w("b"))
        b.set(w("val"), "1")
    if italic:
        i = SubElement(rPr, w("i"))
        i.set(w("val"), "1")
    if underline:
        u = SubElement(rPr, w("u"))
        u.set(w("val"), "single")
    sz = SubElement(rPr, w("sz"))
    sz.set(w("val"), str(size))
    szCs = SubElement(rPr, w("szCs"))
    szCs.set(w("val"), str(size))
    col = SubElement(rPr, w("color"))
    col.set(w("val"), color)
    fn = SubElement(rPr, w("rFonts"))
    fn.set(w("ascii"), font)
    fn.set(w("hAnsi"), font)
    fn.set(w("eastAsia"), font)
    t = SubElement(r, w("t"))
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return r

def new_paragraph(alignment="left", spacing_before=0, spacing_after=0, spacing_line=360, indent_left=0):
    """创建新段落"""
    p = Element(w("p"))
    pPr = SubElement(p, w("pPr"))
    if alignment == "center":
        jc = SubElement(pPr, w("jc"))
        jc.set(w("val"), "center")
    elif alignment == "right":
        jc = SubElement(pPr, w("jc"))
        jc.set(w("val"), "right")
    elif alignment == "both":
        jc = SubElement(pPr, w("jc"))
        jc.set(w("val"), "both")
    if spacing_before or spacing_after or spacing_line:
        sp = SubElement(pPr, w("spacing"))
        if spacing_before:
            sp.set(w("before"), str(spacing_before))
        if spacing_after:
            sp.set(w("after"), str(spacing_after))
        if spacing_line:
            sp.set(w("line"), str(spacing_line))
            sp.set(w("lineRule"), "auto")
    if indent_left:
        ind = SubElement(pPr, w("ind"))
        ind.set(w("left"), str(indent_left))
    return p

def set_paragraph_shading(para, color):
    """给段落添加背景色"""
    pPr = para.find(w("pPr"))
    if pPr is None:
        pPr = SubElement(para, w("pPr"))
    shd = SubElement(pPr, w("shd"))
    shd.set(w("val"), "clear")
    shd.set(w("fill"), color)

def set_paragraph_border_bottom(para, color="2E75B6", size=6):
    """给段落添加底部边框"""
    pPr = para.find(w("pPr"))
    if pPr is None:
        pPr = SubElement(para, w("pPr"))
    pb = SubElement(pPr, w("pBdr"))
    bottom = SubElement(pb, w("bottom"))
    bottom.set(w("val"), "single")
    bottom.set(w("sz"), str(size))
    bottom.set(w("color"), color)
    bottom.set(w("space"), "1")

def add_page_break(para):
    """在段落中添加分页符"""
    r = SubElement(para, w("r"))
    br = SubElement(r, w("br"))
    br.set(w("type"), "page")

def new_table(columns, rows, col_widths=None):
    """创建表格"""
    tbl = Element(w("tbl"))
    tblPr = SubElement(tbl, w("tblPr"))
    tblW = SubElement(tblPr, w("tblW"))
    tblW.set(w("w"), "9360")
    tblW.set(w("type"), "dxa")
    # 边框
    tblBorders = SubElement(tblPr, w("tblBorders"))
    for edge in ["top", "left", "bottom", "right", "insideH", "insideV"]:
        b = SubElement(tblBorders, w(edge))
        b.set(w("val"), "single")
        b.set(w("sz"), "4")
        b.set(w("color"), "BFBFBF")
        b.set(w("space"), "0")
    # 网格
    tblGrid = SubElement(tbl, w("tblGrid"))
    if col_widths:
        for cw in col_widths:
            gc = SubElement(tblGrid, w("gridCol"))
            gc.set(w("w"), str(cw))
    return tbl

def add_table_row(tbl, cells_text, header=False, col_widths=None):
    """向表格添加行"""
    tr = SubElement(tbl, w("tr"))
    for i, text in enumerate(cells_text):
        tc = SubElement(tr, w("tc"))
        tcPr = SubElement(tc, w("tcPr"))
        if col_widths and i < len(col_widths):
            tcW = SubElement(tcPr, w("tcW"))
            tcW.set(w("w"), str(col_widths[i]))
            tcW.set(w("type"), "dxa")
        if header:
            shd = SubElement(tcPr, w("shd"))
            shd.set(w("val"), "clear")
            shd.set(w("fill"), "2E75B6")
        # 边距
        mar = SubElement(tcPr, w("tcMar"))
        for edge_name in ["top", "left", "bottom", "right"]:
            m = SubElement(mar, w(edge_name))
            m.set(w("w"), "80" if edge_name in ["top", "bottom"] else "120")
            m.set(w("type"), "dxa")
        p = new_paragraph()
        add_run(p, text, bold=header, size=20 if header else 20, color="FFFFFF" if header else "333333")
        tc.append(p)
    return tr

def make_document_xml(paragraphs):
    """生成document.xml"""
    doc = Element(w("document"), {
        f"{{{W}}}conformance": "transitional"
    })
    body = SubElement(doc, w("body"))

    # 页面设置
    sectPr = SubElement(body, w("sectPr"))
    pgSz = SubElement(sectPr, w("pgSz"))
    pgSz.set(w("w"), "11906")  # A4
    pgSz.set(w("h"), "16838")
    pgMar = SubElement(sectPr, w("pgMar"))
    pgMar.set(w("top"), "1440")
    pgMar.set(w("right"), "1440")
    pgMar.set(w("bottom"), "1440")
    pgMar.set(w("left"), "1440")

    for p in paragraphs:
        body.append(p)

    return write_xml_str(doc)

# ============================================================
# 作品集内容定义
# ============================================================

def build_portfolio():
    paragraphs = []

    # ===== 封面 =====
    # 空白占位
    for _ in range(6):
        p = new_paragraph(spacing_line=400)
        add_run(p, "", size=28)
        paragraphs.append(p)

    # 项目名称
    p = new_paragraph("center", spacing_after=200)
    add_run(p, "QAgent Pet", bold=True, size=56, color="2E75B6")
    paragraphs.append(p)

    # 副标题
    p = new_paragraph("center", spacing_after=100)
    add_run(p, "QQ智能宠物伴侣 Agent", bold=False, size=32, color="595959")
    paragraphs.append(p)

    p = new_paragraph("center", spacing_after=60)
    add_run(p, "—— AI产品经理作品集 ——", size=24, color="808080")
    paragraphs.append(p)

    # 分隔线
    p = new_paragraph("center", spacing_before=300, spacing_after=300)
    add_run(p, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", size=18, color="CCCCCC")
    paragraphs.append(p)

    # 基本信息
    info_lines = [
        ("参赛项目：", "腾讯AI产品校园大赛 · QQ赛道"),
        ("产品定位：", "基于大语言模型的多角色虚拟宠物情感陪伴应用"),
        ("技术栈：", "FastAPI + SQLite + MiniMax LLM + 原生前端"),
        ("开发周期：", "2026年4月 — 2026年6月（持续迭代中）"),
        ("当前版本：", "v1.3.0"),
    ]
    for label, value in info_lines:
        p = new_paragraph("center", spacing_after=60, spacing_line=320)
        add_run(p, label, bold=True, size=22, color="2E75B6")
        add_run(p, value, size=22, color="333333")
        paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 目录页 =====
    p = new_paragraph(spacing_after=120)
    add_run(p, "目  录", bold=True, size=36, color="2E75B6")
    paragraphs.append(p)
    set_paragraph_border_bottom(p, "2E75B6", 8)

    toc_items = [
        "一、产品概述与核心价值",
        "二、市场分析与用户洞察",
        "三、核心功能架构",
        "四、AI产品设计深度思考",
        "五、技术架构理解",
        "六、产品迭代与版本演进",
        "七、产品数据与验证成果",
        "八、个人能力矩阵与项目贡献",
        "九、项目展望与商业化思考",
    ]
    for i, item in enumerate(toc_items):
        p = new_paragraph(spacing_before=60, spacing_after=60, spacing_line=400)
        add_run(p, item, size=24, color="333333")
        paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第一章：产品概述与核心价值 =====
    paragraphs.extend(section_header("一、产品概述与核心价值"))

    paragraphs.extend(body_text(
        "QAgent Pet 是一款基于AI大语言模型的智能宠物伴侣应用。用户可以选择不同性格的虚拟宠物（Hot Dog、Cold Cat、鼠鼠），或通过AI自定义创建专属宠物，与它们进行自然语言对话互动。宠物具备情绪感知、长期记忆、主动关怀、日程管理、天气查询等能力，真正模拟了\"有生命的陪伴者\"而非\"冷冰冰的对话工具\"。"
    ))

    paragraphs.extend(body_text(
        "一句话定位：让AI不再只是工具，而是有记忆、有温度、有主动性的数字生命伴侣。"
    ))

    p = new_paragraph(spacing_before=200, spacing_after=120)
    add_run(p, "▎核心差异化价值", bold=True, size=26, color="2E75B6")
    paragraphs.append(p)

    values = [
        ("主动关怀，而非被动响应", "三只宠物拥有不同的主动互动阈值（Hot Dog 1天、鼠鼠 2天、Cold Cat 3天），超过阈值会主动发起问候。这不是简单的定时推送——Cold Cat有50%概率选择性回复、鼠鼠被吓到会躲起来、主动互动被回应后亲密度大幅增长。"),
        ("记忆延续，而非每次从零开始", "独创双通道记忆架构：10条短期对话记忆 + 向量语义检索历史相关记忆 + LLM话题感知触发长期记忆压缩。宠物不会\"失忆\"，关系随时间积累。"),
        ("个性化角色，而非千人一面", "三只预置宠物拥有截然不同的性格（热情/高冷/憨厚）、说话风格、交互节奏和情绪响应策略。同时支持AI生成自定义宠物，用户可创建完全独一无二的专属伴侣。"),
        ("情感连接，而非功能叠加", "8字段用户画像自动提取、5种情绪感知与差异化响应、4级亲密度成长体系——所有功能服务于一个核心目标：让用户感受到真实的陪伴和情感连接。"),
    ]
    for title, desc in values:
        p = new_paragraph(spacing_before=80, spacing_after=40)
        add_run(p, f"✦ {title}：", bold=True, size=22, color="333333")
        add_run(p, desc, size=20, color="555555")
        paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第二章：市场分析与用户洞察 =====
    paragraphs.extend(section_header("二、市场分析与用户洞察"))

    paragraphs.extend(body_text(
        "在移动互联网时代，Z世代年轻人面临着\"社交过载但情感孤独\"的矛盾。微信好友几百人，但深夜想说心里话时找不到人；社交媒体刷不完，但真实的情感连接感却在下降。AI陪伴类产品（如Character.AI、Replika）在海外的爆火，验证了\"AI情感陪伴\"这一赛道的巨大潜力。"
    ))

    p = new_paragraph(spacing_before=180, spacing_after=100)
    add_run(p, "▎目标用户画像", bold=True, size=26, color="2E75B6")
    paragraphs.append(p)

    # 用户画像表格
    tbl = new_table(3, 5, [2200, 3580, 3580])
    add_table_row(tbl, ["用户群体", "核心痛点", "产品价值主张"], header=True, col_widths=[2200, 3580, 3580])
    add_table_row(tbl, ["Z世代学生/职场新人", "独居孤独感、倾诉需求、压力无处释放", "有温度的情感陪伴、情绪识别与安慰"], col_widths=[2200, 3580, 3580])
    add_table_row(tbl, ["二次元/虚拟社交爱好者", "对虚拟角色有情感投射，追求个性化", "多角色+自定义宠物，满足个性化偏好"], col_widths=[2200, 3580, 3580])
    add_table_row(tbl, ["轻度心理健康关注者", "不需要专业心理咨询但需要情绪出口", "情绪感知+主动关怀，低门槛情绪支持"], col_widths=[2200, 3580, 3580])
    add_table_row(tbl, ["生活节奏快、健忘人群", "日程管理混乱，缺乏提醒机制", "AI自然提取日程+性格化提醒"], col_widths=[2200, 3580, 3580])
    paragraphs.append(tbl)

    p = new_paragraph(spacing_before=180, spacing_after=100)
    add_run(p, "▎竞品分析", bold=True, size=26, color="2E75B6")
    paragraphs.append(p)

    tbl2 = new_table(4, 6, [2340, 2340, 2340, 2340])
    add_table_row(tbl2, ["维度", "QAgent Pet", "Character.AI", "Replika", "传统聊天机器人"], header=True, col_widths=[2340, 2340, 2340, 2340])
    add_table_row(tbl2, ["角色多样性", "3预置+AI自定义生成", "海量UGC角色", "单一AI伴侣", "单一预设角色"], col_widths=[2340, 2340, 2340, 2340])
    add_table_row(tbl2, ["主动互动", "√ 差异化主动关怀机制", "被动响应为主", "部分主动推送", "完全被动"], col_widths=[2340, 2340, 2340, 2340])
    add_table_row(tbl2, ["长期记忆", "√ 双通道+向量检索+话题压缩", "有限上下文", "记忆摘要", "基本无记忆"], col_widths=[2340, 2340, 2340, 2340])
    add_table_row(tbl2, ["亲密度体系", "√ 4级成长+行为影响", "无", "有情感等级", "无"], col_widths=[2340, 2340, 2340, 2340])
    add_table_row(tbl2, ["多宠物互访", "√ 跨宠物串门通信", "群聊功能", "无", "无"], col_widths=[2340, 2340, 2340, 2340])
    paragraphs.append(tbl2)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第三章：核心功能架构 =====
    paragraphs.extend(section_header("三、核心功能架构"))

    paragraphs.extend(body_text(
        "QAgent Pet 的产品功能架构围绕\"让AI宠物具备生命感\"这一核心理念设计，分为六大功能模块："
    ))

    modules = [
        ("🟦 模块一：角色系统", [
            "3只预置宠物：Hot Dog（热情）、Cold Cat（高冷）、鼠鼠（憨厚胆小）",
            "每只宠物拥有完整的性格定义、说话风格、交互节奏和情绪响应策略",
            "宠物状态机：normal（正常）/ hiding（躲藏）/ excited（兴奋）/ selective（选择性回复）",
            "AI自定义宠物：用户设定名称、类型、性格标签、口头禅、习惯 → LLM生成完整System Prompt",
            "自定义宠物持久化存储（SQLite），支持增删改查",
        ]),
        ("🟦 模块二：对话与情绪系统", [
            "自然语言对话：基于宠物角色设定的拟人化回复",
            "5种情绪感知：happy / sad / anxious / tired / neutral",
            "情绪差异化响应：同一条消息，不同宠物有截然不同的安慰/鼓励/陪伴策略",
            "口头禅概率控制：代码层动态注入替代System Prompt硬编码，控制口头禅出现频率",
            "工具调用：天气查询（Open-Meteo免费API）、日程提取、日常分享",
        ]),
        ("🟦 模块三：记忆系统（核心亮点）", [
            "短期记忆：最近10条完整对话消息，保证当前对话连贯性",
            "向量语义检索：通过Embedding向量检索历史相关记忆，补充上下文",
            "话题感知长期记忆压缩：LLM自动检测话题变化，触发压缩摘要（≤200字）",
            "用户画像：8字段自动提取（地区/身份/兴趣/职业/性格/活跃时段/情绪倾向/其他）",
        ]),
        ("🟦 模块四：亲密度成长体系", [
            "4级亲密度：陌生(0-20) → 熟悉(21-50) → 亲密(51-80) → 挚友(81+)",
            "多因素影响：互动频次+1、情绪低落时+2、主动关怀被回应+3、疏远惩罚-1/天",
            "亲密度影响宠物行为：等级越高，宠物越主动、越亲密、分享越多",
        ]),
        ("🟦 模块五：主动关怀系统", [
            "差异化阈值：Hot Dog 1天、鼠鼠 2天、Cold Cat 3天",
            "每日分享：约33%概率分享宠物\"日常\"，营造宠物有独立生活的感觉",
            "特殊行为：鼠鼠3天未互动被吓到并躲藏5分钟、Cold Cat选择性回复",
            "日程提醒：从对话中自然提取日程，到期时用符合人设的方式提醒",
        ]),
        ("🟦 模块六：宠物串门通信（创新功能）", [
            "两只独立宠物在聊天窗口内自动对话（中心化协调器模式）",
            "上下文隔离设计：每只宠物只用自己的人格，对方信息作为受限context注入",
            "支持用户旁观或插话参与，最多自动6轮对话",
            "串门结束自动生成记忆摘要，写入双方长期记忆",
            "角色混淆防护：三层保障（Prompt结构层+规则层+后处理层）",
        ]),
    ]
    for title, items in modules:
        p = new_paragraph(spacing_before=160, spacing_after=60)
        add_run(p, title, bold=True, size=22, color="2E75B6")
        paragraphs.append(p)
        for item in items:
            p = new_paragraph(spacing_after=30, indent_left=360)
            add_run(p, f"• {item}", size=20, color="444444")
            paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第四章：AI产品设计深度思考 =====
    paragraphs.extend(section_header("四、AI产品设计深度思考"))

    design_topics = [
        {
            "title": "设计决策1：为什么是\"宠物\"而非\"助手\"？",
            "content": [
                "在项目初期，面临的核心产品定位问题是：我们要做一个AI助手还是AI宠物？最终选择了\"宠物\"定位，核心理由：",
                "• 情感连接 > 效率工具：助手被期待\"有用\"，宠物被期待\"有爱\"。用户对宠物的容错率更高，情感投入更深。",
                "• 角色化降低预期：当AI说错话时，\"这只傻狗又在犯蠢\"比\"这个AI怎么这么笨\"的体验好得多。",
                "• 主动互动合理化：助手主动推送是\"打扰\"，宠物主动来找你是\"想念\"——同样的行为，不同角色定位下的用户感知天差地别。",
                "• 记忆需求自然成立：用户不会要求计算器记住自己，但会期待宠物记得\"上次我说的那件事\"。",
            ]
        },
        {
            "title": "设计决策2：双通道记忆架构的设计逻辑",
            "content": [
                "AI产品的记忆系统设计面临一个核心矛盾：上下文窗口有限 vs 用户期望无限记忆。单靠\"取最近N条\"会丢失关键历史信息；单靠\"全文检索\"成本高且噪声大。",
                "我们的解决方案——双通道架构：",
                "• 通道一（短期记忆）：最近10条完整对话，保证当前对话流畅不割裂",
                "• 通道二（向量语义检索）：将历史对话做Embedding，按语义相似度检索补充上下文",
                "• 长期记忆压缩：LLM感知话题变化 → 自动触发压缩 → 生成摘要写入长期记忆表",
                "这种设计解决了三个核心问题：上下文窗口效率最大化、关键历史信息不会被遗忘、记忆存储成本可控。",
            ]
        },
        {
            "title": "设计决策3：主动关怀的\"阈值差异化\"设计",
            "content": [
                "如果所有宠物都在1天后发同样的\"我想你了\"，用户会立刻意识到这是机械规则。差异化设计让规则变成了\"性格\"：",
                "• Hot Dog（热情）：1天就忍不住来找你 → 用户觉得\"它真的很粘我\"",
                "• 鼠鼠（胆小）：2天才敢鼓起勇气 → 用户觉得\"它好可爱好害羞\"",
                "• Cold Cat（高冷）：3天还爱理不理 → 用户觉得\"果然是只傲娇猫\"",
                "同样的\"主动关怀\"能力，通过差异化参数变成了三个截然不同的\"性格表达\"。这是产品设计的核心——用参数差异化创造感知差异化。",
            ]
        },
        {
            "title": "设计决策4：Prompt工程的\"隐式产品设计\"",
            "content": [
                "在AI产品中，Prompt不是技术细节，而是产品设计的核心载体。我们的Prompt工程体现了以下产品设计原则：",
                "• 结构化分层：System Prompt（角色定义）→ 长期记忆 → 用户画像 → 亲密度 → Skills注入 → 短期对话，层次分明且可独立维护",
                "• 差异化注入：每个宠物的角色定义、情绪响应策略、交互节奏都是独立模块，新增宠物只需添加配置",
                "• 约束而非控制：用\"规则区\"约束边界（如不暴露主人隐私、不扮演对方角色），但给LLM充分的表达自由度",
                "• 口头禅概率控制：代码层动态注入替代硬编码，解决了\"宠物一句话反复说显得假\"的体验问题",
                "• 安全防御：XML注入过滤、工具调用白名单、参数Schema校验——安全设计贯穿Prompt全链路",
            ]
        },
        {
            "title": "设计决策5：串门通信的\"上下文隔离\"设计",
            "content": [
                "宠物串门功能面临的最大挑战是\"角色混淆\"——如何在同一个对话窗口内让两只宠物保持各自人格？",
                "我们的三层隔离方案：",
                "• Prompt结构层：<system>只放发言宠物自身完整人格，对方信息降级为≤50字的<visit_context>",
                "• 规则层：显式指令\"你只能扮演{自己的名字}，不能模仿或扮演{对方名字}\"",
                "• 后处理层：检测并移除回复中可能出现的\"对方名字:\"前缀",
                "这个设计体现了AI产品经理在\"多Agent协作\"场景下的核心能力——边界定义、上下文管理、异常兜底。",
            ]
        },
    ]

    for topic in design_topics:
        p = new_paragraph(spacing_before=200, spacing_after=80)
        add_run(p, f"▎{topic['title']}", bold=True, size=24, color="2E75B6")
        paragraphs.append(p)
        for line in topic["content"]:
            if line.startswith("•"):
                p = new_paragraph(spacing_after=30, indent_left=360)
                add_run(p, line, size=20, color="444444")
            else:
                p = new_paragraph(spacing_after=60)
                add_run(p, line, size=20, color="333333")
            paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第五章：技术架构理解 =====
    paragraphs.extend(section_header("五、技术架构理解"))

    paragraphs.extend(body_text(
        "作为AI产品经理，不需要写代码，但必须理解技术边界、能力上限和实现成本，才能做出合理的需求决策。以下是我对QAgent Pet技术架构的理解："
    ))

    p = new_paragraph(spacing_before=160, spacing_after=80)
    add_run(p, "▎系统架构设计", bold=True, size=24, color="2E75B6")
    paragraphs.append(p)

    arch_items = [
        ("表现层", "单文件HTML/CSS/JS（宠物选择页、聊天页、自定义宠物页、串门面板）"),
        ("服务层", "FastAPI异步框架 → 7个路由模块（会话/聊天/自定义宠物/串门/记忆/画像/天气）"),
        ("AI层", "MiniMax API（主对话/情绪识别/日程提取/记忆压缩/画像提取/欢迎语生成）"),
        ("数据层", "SQLite（7张表）→ 用户/会话/消息/记忆/日程/画像/自定义宠物/串门记录"),
        ("记忆层", "双通道 → 短期记忆(DB) + 向量语义检索(Embedding + 余弦相似度)"),
    ]
    for layer, desc in arch_items:
        p = new_paragraph(spacing_after=30, indent_left=360)
        add_run(p, f"• {layer}：", bold=True, size=20, color="2E75B6")
        add_run(p, desc, size=20, color="444444")
        paragraphs.append(p)

    p = new_paragraph(spacing_before=160, spacing_after=80)
    add_run(p, "▎关键AI能力映射", bold=True, size=24, color="2E75B6")
    paragraphs.append(p)

    tbl3 = new_table(3, 8, [2800, 2800, 3760])
    add_table_row(tbl3, ["AI能力", "实现方式", "产品价值"], header=True, col_widths=[2800, 2800, 3760])
    tech_items = [
        ("对话生成", "LLM System Prompt + 上下文组装", "拟人化、性格一致的角色对话体验"),
        ("情绪识别", "LLM Prompt分类（5标签）", "宠物感知情绪、差异化回应策略"),
        ("语义检索", "Embedding向量 + 余弦相似度", "历史相关记忆召回，对话不\"失忆\""),
        ("记忆压缩", "LLM话题感知触发 + 摘要生成", "长期记忆沉淀，上下文窗口效率最大化"),
        ("日程提取", "LLM结构化输出（JSON）", "从自然对话中无感提取日程"),
        ("画像提取", "LLM多轮分析输出8字段", "宠物\"了解\"主人的个人特质"),
        ("Prompt生成", "LLM角色生成器（自定义宠物）", "用户轻松创建专属宠物人格"),
    ]
    for item in tech_items:
        add_table_row(tbl3, item, col_widths=[2800, 2800, 3760])
    paragraphs.append(tbl3)

    p = new_paragraph(spacing_before=160, spacing_after=80)
    add_run(p, "▎技术选型的产品考量", bold=True, size=24, color="2E75B6")
    paragraphs.append(p)

    tech_thinking = [
        "FastAPI而非Flask/Django：异步架构对于需要等待LLM API响应的场景至关重要，避免请求阻塞",
        "SQLite而非MySQL/PostgreSQL：竞赛Demo阶段轻量化优先，无需部署额外数据库服务，后续可无缝迁移",
        "原生前端而非React/Vue：Demo阶段迭代速度优先，单文件JS足够表达交互，降低开发成本和上手门槛",
        "OpenAI兼容API格式：解耦具体LLM服务商，可随时切换DeepSeek/MiniMax/智谱，不锁定单一供应商",
        "向量检索当前方案 vs 向量数据库：当前用SQLite+Python计算余弦相似度适合Demo规模，生产环境需迁移至ChromaDB/Milvus",
    ]
    for item in tech_thinking:
        p = new_paragraph(spacing_after=40, indent_left=360)
        add_run(p, f"• {item}", size=20, color="444444")
        paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第六章：产品迭代与版本演进 =====
    paragraphs.extend(section_header("六、产品迭代与版本演进"))

    paragraphs.extend(body_text(
        "QAgent Pet 经历了从0到1的完整产品迭代周期，每个版本都有明确的产品目标、需求优先级和交付成果。以下是关键迭代历程："
    ))

    versions = [
        ("v1.0.0（2026年4月）", "核心MVP", [
            "3只预置宠物基本对话 | 情绪感知（5种标签）| 亲密度系统 | 日程记忆 | 天气查询 | 主动关怀基础机制 | 记忆面板",
        ]),
        ("v1.1.0（2026年5月27日）", "记忆系统全面重构", [
            "双通道上下文检索（10条短期记忆 + 向量语义检索）| 话题感知长期记忆压缩（LLM自动触发）| 用户画像从3字段扩展至8字段 | 自定义宠物UI重做（新增狮子/熊猫/老虎形象）",
        ]),
        ("v1.2.0（2026年5月29日）", "体验细节打磨", [
            "口头禅概率控制：代码层动态注入替代System Prompt硬编码 | 滑动窗口检测口头禅频率 | 4个Prompt文件统一改造 | 前端UI优化",
        ]),
        ("v1.3.0（2026年6月3日）", "自定义宠物全链路", [
            "自定义宠物从内存字典迁移到SQLite持久化存储 | 5个CRUD API接口 | Hot Dog口头禅BUG修复 | 3个前端UI Bug修复 | 用户身份隔离",
        ]),
        ("v1.4.0（2026年6月14日）", "创新功能：宠物串门", [
            "跨宠物串门通信（Phase 1 + Phase 2）| 中心化协调器模式 | 三层角色混淆防护 | 串门记忆沉淀 | 前端串门面板 | 8项安全漏洞追踪与修复",
        ]),
        ("v1.5.0（2026年6月15日）", "安全加固与优化", [
            "串门功能安全审计（8项漏洞追踪VIS-1~8）| 多轮安全修复（Prompt注入/CORS/认证/限流/日志）| 数据库性能优化（WAL模式/索引）",
        ]),
    ]

    for ver, goal, items in versions:
        p = new_paragraph(spacing_before=160, spacing_after=40)
        add_run(p, f"▎{ver} —— {goal}", bold=True, size=22, color="2E75B6")
        paragraphs.append(p)
        for item in items:
            p = new_paragraph(spacing_after=20, indent_left=360)
            add_run(p, f"✦ {item}", size=20, color="555555")
            paragraphs.append(p)

    p = new_paragraph(spacing_before=180, spacing_after=80)
    add_run(p, "▎迭代策略总结", bold=True, size=24, color="2E75B6")
    paragraphs.append(p)
    for item in [
        "P0先行：核心对话+角色系统 → P1增强：记忆+情感 → P2优化：体验+安全 → P3创新：串门+扩展",
        "每次迭代都有明确的用户可感知价值交付，而非纯技术优化",
        "安全与体验并重：每个版本都包含安全审计、Bug修复和性能优化",
        "文档驱动：所有需求通过产品方案文档→需求实现文档→计划文档→更新日志→演示方案，形成完整的产品文档体系",
    ]:
        p = new_paragraph(spacing_after=30, indent_left=360)
        add_run(p, f"• {item}", size=20, color="444444")
        paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第七章：产品数据与验证成果 =====
    paragraphs.extend(section_header("七、产品数据与验证成果"))

    paragraphs.extend(body_text(
        "虽然作为竞赛Demo项目暂未上线公测，但项目的产品质量可以从以下维度得到验证："
    ))

    data_points = [
        ("代码规模", "26个Python后端文件 + 3个HTML页面 + 3个CSS文件 + 3个JS文件"),
        ("API端点", "13个RESTful API端点（会话/聊天/自定义宠物/串门/记忆/画像/天气）"),
        ("数据表", "8张SQLite表（users/pet_sessions/messages/long_term_memories/schedules/user_profiles/memory_vectors/custom_pets/pet_visits/pet_visit_messages）"),
        ("AI调用链路", "单次聊天最高触发7种LLM调用（主回复/情绪提取/日程提取/话题检测/记忆压缩/用户画像/日常分享）"),
        ("记忆系统", "双通道架构：10条短期记忆 + 向量语义检索 + 话题感知LLM自动压缩"),
        ("安全审计", "发现并追踪27项安全漏洞/优化项（Critical 1 + High 6 + Medium 10 + Low 10）"),
        ("产品文档", "6份完整文档（产品方案/需求实现/开发计划/更新日志/演示方案/安全审计）"),
        ("演示方案", "6幕完整演示脚本 + 11项检查清单 + 9类故障兜底方案"),
        ("迭代记录", "6个主要版本 + 30+项功能/修复/优化变更"),
    ]
    for label, value in data_points:
        p = new_paragraph(spacing_after=30)
        add_run(p, f"• {label}：", bold=True, size=20, color="2E75B6")
        add_run(p, value, size=20, color="444444")
        paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第八章：个人能力矩阵与项目贡献 =====
    paragraphs.extend(section_header("八、个人能力矩阵与项目贡献"))

    paragraphs.extend(body_text(
        "在QAgent Pet项目中，我承担了AI产品经理的核心角色，覆盖从需求定义到产品交付的完整链路。以下是我在该项目中展现的核心能力："
    ))

    capabilities = [
        {
            "title": "🔷 产品规划与需求管理",
            "items": [
                "独立完成产品方案文档撰写，从市场分析到功能定义到技术选型",
                "制定清晰的版本迭代路线图（P0→P1→P2→P3优先级体系）",
                "需求文档覆盖API定义、数据库设计、Prompt工程、前端页面、部署方案——可直接交付开发",
                "产出了完整的需求实现文档（1000+行），包含所有接口的请求/响应/错误码定义",
            ]
        },
        {
            "title": "🔷 AI产品设计能力",
            "items": [
                "设计了双通道记忆架构（短期+向量检索+长期压缩），解决了AI\"失忆\"的核心体验问题",
                "设计了差异化主动关怀机制，用参数差异化创造感知差异化（同一功能 → 三种性格表达）",
                "设计了上下文隔离的多Agent串门通信方案，包含三层角色混淆防护",
                "设计了5种情绪→4种宠物→20种差异化响应策略矩阵",
                "系统性地设计了Prompt工程体系：分层组装、角色差异化、安全约束、动态注入",
            ]
        },
        {
            "title": "🔷 技术理解与边界判断",
            "items": [
                "理解LLM的Token限制→设计上下文组装策略（各层Token预估和控制）",
                "理解SQLite的性能边界→制定数据表设计和索引优化方案",
                "理解API费用的成本结构→设计LLM调用链路优化（并发/降级/缓存）",
                "理解Web安全→独立完成27项安全漏洞审计和修复优先级路线图",
                "理解OpenAI兼容协议→确保技术选型的供应商解耦",
            ]
        },
        {
            "title": "🔷 用户体验思维",
            "items": [
                "设计了宠物状态机（normal/hiding/excited/selective），让宠物行为\"有逻辑\"而非随机",
                "设计了口头禅概率控制机制，解决\"AI重复说同一句话\"的常见体验痛点",
                "设计了亲密度成长曲线，让用户感受到\"关系随时间变化\"",
                "设计了6幕演示脚本，每幕对应一个核心用户价值点，演示节奏可控",
            ]
        },
        {
            "title": "🔷 项目管理与文档能力",
            "items": [
                "维护了完整的项目文档体系：产品方案→需求文档→计划→更新日志→演示方案→安全审计",
                "产出了本地演示方案：包含启动步骤、6幕脚本、11项检查清单、9类故障兜底",
                "产出了安全审计报告：27项漏洞详细追踪（含复现步骤、修复方案、优先级路线图）",
                "产出了优化建议追踪：10+项性能/可维护性/部署优化建议",
            ]
        },
        {
            "title": "🔷 安全意识",
            "items": [
                "在需求阶段就将安全纳入设计考量（API Key管理、输入过滤、CORS配置）",
                "主动进行全代码安全审计，发现并追踪27项安全漏洞",
                "制定修复优先级路线图（P0→P1→P2→P3），平衡安全与交付节奏",
                "针对新增功能（串门）进行专项安全审计，发现8项新漏洞",
            ]
        },
    ]

    for cap in capabilities:
        p = new_paragraph(spacing_before=180, spacing_after=60)
        add_run(p, cap["title"], bold=True, size=22, color="2E75B6")
        paragraphs.append(p)
        for item in cap["items"]:
            p = new_paragraph(spacing_after=20, indent_left=360)
            add_run(p, f"✦ {item}", size=20, color="444444")
            paragraphs.append(p)

    # 分页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    # ===== 第九章：项目展望与商业化思考 =====
    paragraphs.extend(section_header("九、项目展望与商业化思考"))

    paragraphs.extend(body_text(
        "从产品经理视角，我对QAgent Pet的未来发展和商业化路径有以下思考："
    ))

    future_topics = [
        ("短期优化（1-3个月）", [
            "流式输出（SSE）：将回复从\"等待后一次性显示\"改为\"逐字流式输出\"，大幅提升对话体验",
            "语音对话：接入TTS/ASR，让宠物\"能说会听\"，增强陪伴的真实感",
            "宠物成长系统：外观变化+性格微调+技能解锁，让长期用户有持续的新鲜感",
            "记忆系统升级：迁移至ChromaDB/Milvus向量数据库，支持更大规模记忆和更低检索延迟",
        ]),
        ("中期扩展（3-6个月）", [
            "多端适配：微信小程序版本（降低使用门槛、契合QQ生态）",
            "宠物市场：用户可分享/交易自定义宠物配置，形成UGC生态",
            "多人联机：跨用户的宠物串门+主人共同旁观/参与（Phase 3）",
            "情感数据洞察：基于用户情绪趋势提供心理健康轻报告（需充分考虑隐私合规）",
        ]),
        ("商业化思考", [
            "Freemium模型：基础宠物免费，高级宠物/自定义宠物/更多记忆容量付费",
            "虚拟物品：宠物装扮（配饰/场景/特效）→ 低客单价、高复购率",
            "订阅制：记忆无限容量+高级AI模型+专属客服 → 月度/年度订阅",
            "B端场景：企业定制AI形象（品牌吉祥物AI化）、校园心理健康辅助工具",
        ]),
        ("风险与挑战", [
            "情感依赖风险：用户过度依赖AI陪伴可能导致现实社交退化 → 需设计\"鼓励线下社交\"机制",
            "数据隐私：对话内容高度私密 → 需本地方案或端到端加密",
            "内容安全：LLM可能产生不当内容 → 需持续完善安全过滤体系",
            "用户留存：陪伴类产品如何突破\"新鲜感过后弃用\"的魔咒 → 关键在记忆系统和成长系统",
        ]),
    ]

    for title, items in future_topics:
        p = new_paragraph(spacing_before=160, spacing_after=60)
        add_run(p, f"▎{title}", bold=True, size=22, color="2E75B6")
        paragraphs.append(p)
        for item in items:
            p = new_paragraph(spacing_after=20, indent_left=360)
            add_run(p, f"• {item}", size=20, color="444444")
            paragraphs.append(p)

    # 结束页
    p = new_paragraph()
    add_page_break(p)
    paragraphs.append(p)

    for _ in range(5):
        p = new_paragraph(spacing_line=400)
        add_run(p, "", size=28)
        paragraphs.append(p)

    p = new_paragraph("center", spacing_after=60)
    add_run(p, "感谢阅读", bold=True, size=44, color="2E75B6")
    paragraphs.append(p)

    p = new_paragraph("center", spacing_after=200)
    add_run(p, "QAgent Pet · AI产品经理作品集", size=24, color="808080")
    paragraphs.append(p)

    p = new_paragraph("center", spacing_after=60)
    add_run(p, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", size=18, color="CCCCCC")
    paragraphs.append(p)

    p = new_paragraph("center", spacing_after=40)
    add_run(p, "本项目为腾讯AI产品校园大赛参赛作品", size=20, color="999999")
    paragraphs.append(p)

    return paragraphs

def section_header(title):
    """生成章节标题"""
    result = []
    p = new_paragraph(spacing_before=60, spacing_after=40)
    add_run(p, title, bold=True, size=32, color="2E75B6")
    result.append(p)
    set_paragraph_border_bottom(p, "2E75B6", 6)

    p = new_paragraph(spacing_after=120)
    add_run(p, "", size=12)
    result.append(p)
    return result

def body_text(text):
    """生成正文段落"""
    result = []
    p = new_paragraph(spacing_after=120, spacing_line=360, alignment="both")
    add_run(p, text, size=21, color="333333")
    result.append(p)
    return result

# ============================================================
# 主流程
# ============================================================

def main():
    print("🚀 正在生成 QAgent Pet AI产品经理作品集...")
    print()

    # 构建文档内容
    paragraphs = build_portfolio()

    # 生成document.xml
    doc_xml = make_document_xml(paragraphs)

    # 创建DOCX
    builder = DocxBuilder()

    # 添加主文档
    builder.add_file("word/document.xml", doc_xml,
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")

    # 添加关系
    builder.add_rel("/", "rId1",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
                    "word/document.xml")

    # 确定输出路径
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "QAgent_Pet_AI产品经理作品集.docx")
    builder.build(output_path)

    print(f"✅ 作品集已生成：{output_path}")
    print(f"📄 文件大小：{os.path.getsize(output_path) / 1024:.1f} KB")
    print()
    print("📋 作品集包含以下内容：")
    print("  一、产品概述与核心价值")
    print("  二、市场分析与用户洞察")
    print("  三、核心功能架构")
    print("  四、AI产品设计深度思考（5个关键设计决策）")
    print("  五、技术架构理解")
    print("  六、产品迭代与版本演进")
    print("  七、产品数据与验证成果")
    print("  八、个人能力矩阵与项目贡献（6大能力维度）")
    print("  九、项目展望与商业化思考")

if __name__ == "__main__":
    main()
