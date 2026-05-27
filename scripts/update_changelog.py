#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
QAgent Pet 文档变更管理脚本
功能：
1. append_readme_changelog - 在 README.md 中追加/创建版本追踪记录
2. append_revision_record - 在需求实现文档的修订记录表中追加新行
3. remove_implemented_sections - 标记已实现的需求章节
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

# Fix Unicode output on Windows GBK terminals
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def append_readme_changelog(
    readme_path: str,
    version: str,
    summary: str,
    details: str = ""
) -> str:
    """
    在 README.md 中追加版本追踪记录。
    如果没有 ## 版本追踪 章节，则在 ## 未来展望 之前创建。
    """
    path = Path(readme_path)
    if not path.exists():
        raise FileNotFoundError(f"README 文件不存在: {readme_path}")

    content = path.read_text(encoding="utf-8")
    today = date.today().strftime("%Y-%m-%d")

    # 构建新条目
    new_entry = f"\n### {version} ({today})\n\n- **摘要**: {summary}\n"
    if details:
        for detail in details.split("；"):
            detail = detail.strip()
            if detail:
                new_entry += f"- {detail}\n"

    changelog_header = "## 版本追踪"
    future_header = "## 未来展望"

    if changelog_header in content:
        # 已有版本追踪章节，追加到该章节末尾（在下一个 ## 之前）
        lines = content.splitlines()
        new_lines = []
        in_changelog = False
        appended = False

        for i, line in enumerate(lines):
            new_lines.append(line)
            if line.strip() == changelog_header:
                in_changelog = True
            elif in_changelog and line.startswith("## ") and line.strip() != changelog_header:
                # 到达下一个 ## 章节，在此之前插入
                # 回退一行，插入新条目
                new_lines.pop()
                new_lines.append(new_entry.rstrip("\n"))
                new_lines.append("")
                new_lines.append(line)
                in_changelog = False
                appended = True

        if not appended:
            # 版本追踪是最后一个章节，直接在末尾追加
            new_lines.append(new_entry.rstrip("\n"))
            new_lines.append("")

        content = "\n".join(new_lines)

    elif future_header in content:
        # 在未来展望之前插入
        content = content.replace(
            future_header,
            f"{changelog_header}\n{new_entry}\n\n{future_header}"
        )
    else:
        # 在文件末尾追加
        content = content.rstrip("\n") + f"\n\n---\n\n{changelog_header}\n{new_entry}\n"

    path.write_text(content, encoding="utf-8")
    return f"✅ 已在 README.md 中追加版本 {version} 的追踪记录"


def append_revision_record(
    doc_path: str,
    version: str,
    content: str,
    author: str = "-"
) -> str:
    """
    在需求实现文档的 文档修订记录 表格中追加新行。
    表格格式：
    | **版本** | **修订日期** | **修订人** | **修订内容** |
    """
    path = Path(doc_path)
    if not path.exists():
        raise FileNotFoundError(f"文档不存在: {doc_path}")

    text = path.read_text(encoding="utf-8")
    today = date.today().strftime("%Y-%m-%d")

    # 查找修订记录表格的最后一行数据行
    # 表格行格式: | V1.0 | 2026-04-22 | - | 初始版本... |
    revision_pattern = re.compile(r"^\|\s+V\d+\.\d+\s+\|", re.MULTILINE)
    matches = list(revision_pattern.finditer(text))

    if not matches:
        raise ValueError("未找到修订记录表格的数据行")

    # 找到最后一个版本号所在行，在其后插入新行
    last_match = matches[-1]
    last_line_start = last_match.start()
    last_line_end = text.find("\n", last_match.start())

    # 构建新行（保持对齐）
    new_row = f"\n  V{version}       {today}     {author}      {content}"

    # 找到该行结束位置
    insert_pos = text.find("\n", last_line_end)
    if insert_pos == -1:
        insert_pos = len(text)

    updated_text = text[:last_line_end + 1] + new_row + text[last_line_end + 1:]
    path.write_text(updated_text, encoding="utf-8")

    return f"✅ 已在需求实现文档中追加修订记录 V{version}"


def mark_implemented_sections(
    doc_path: str,
    section_markers: list[str]
) -> str:
    """
    在需求实现文档中标记已实现的章节。
    section_markers: 章节标题列表，如 ["10. 可自定义宠物 Agent 需求"]
    """
    path = Path(doc_path)
    if not path.exists():
        raise FileNotFoundError(f"文档不存在: {doc_path}")

    text = path.read_text(encoding="utf-8")
    messages = []

    for marker in section_markers:
        # 查找章节标题（## 或 # 开头）
        pattern = re.compile(
            rf"^#+\s+{re.escape(marker)}.*$",
            re.MULTILINE
        )
        match = pattern.search(text)
        if match:
            # 在标题后添加已实现标记
            title_line = match.group(0)
            if "✅ 已实现" not in title_line:
                new_title = f"{title_line} ✅ 已实现"
                text = text.replace(title_line, new_title)
                messages.append(f"  - 已标记: {marker}")
            else:
                messages.append(f"  - 跳过（已标记）: {marker}")
        else:
            messages.append(f"  - 未找到: {marker}")

    path.write_text(text, encoding="utf-8")
    return "✅ 已实现的章节标记完成:\n" + "\n".join(messages)


def remove_sections(doc_path: str, section_titles: list[str]) -> str:
    """
    从需求实现文档中移除指定章节（包括其所有子内容，直到下一个同级或更高级标题）。
    """
    path = Path(doc_path)
    if not path.exists():
        raise FileNotFoundError(f"文档不存在: {doc_path}")

    text = path.read_text(encoding="utf-8")
    messages = []

    for title in section_titles:
        # 匹配标题行，获取其级别
        match = re.search(
            rf"^(#+)\s+{re.escape(title)}.*\n",
            text, re.MULTILINE
        )
        if not match:
            messages.append(f"  - 未找到章节: {title}")
            continue

        heading_level = len(match.group(1))
        start = match.start()

        # 找到下一个同级或更高级标题
        end_pattern = re.compile(
            rf"^#{{{1,{heading_level}}}}\s+",
            re.MULTILINE
        )
        next_match = end_pattern.search(text, match.end())
        end = next_match.start() if next_match else len(text)

        # 移除该章节
        removed_content = text[start:end]
        text = text[:start] + text[end:]

        # 清理多余的空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        messages.append(f"  - 已移除: {title} ({len(removed_content)} 字符)")

    path.write_text(text, encoding="utf-8")
    return "✅ 已实现的章节已移除:\n" + "\n".join(messages)


def main():
    parser = argparse.ArgumentParser(
        description="QAgent Pet 文档变更管理工具"
    )
    subparsers = parser.add_subparsers(dest="action", help="操作类型")

    # 子命令: readme - 追加 README 版本追踪
    readme_parser = subparsers.add_parser("readme", help="追加 README.md 版本追踪")
    readme_parser.add_argument("--path", required=True, help="README.md 文件路径")
    readme_parser.add_argument("--version", required=True, help="版本号，如 1.2.0")
    readme_parser.add_argument("--summary", required=True, help="一行更新摘要")
    readme_parser.add_argument("--details", default="", help="详细变更列表，用；分隔")

    # 子命令: revision - 追加需求实现文档修订记录
    revision_parser = subparsers.add_parser("revision", help="追加需求实现文档修订记录")
    revision_parser.add_argument("--path", required=True, help="文档路径")
    revision_parser.add_argument("--version", required=True, help="版本号，如 1.2.0")
    revision_parser.add_argument("--content", required=True, help="修订内容描述")
    revision_parser.add_argument("--author", default="-", help="修订人")

    # 子命令: mark - 标记已实现的章节
    mark_parser = subparsers.add_parser("mark", help="标记已实现的章节")
    mark_parser.add_argument("--path", required=True, help="文档路径")
    mark_parser.add_argument("--sections", nargs="+", required=True, help="要标记的章节标题列表")

    # 子命令: remove - 移除已实现的章节
    remove_parser = subparsers.add_parser("remove", help="移除已实现的章节")
    remove_parser.add_argument("--path", required=True, help="文档路径")
    remove_parser.add_argument("--sections", nargs="+", required=True, help="要移除的章节标题列表")

    args = parser.parse_args()

    if args.action == "readme":
        result = append_readme_changelog(
            args.path, args.version, args.summary, args.details
        )
    elif args.action == "revision":
        result = append_revision_record(
            args.path, args.version, args.content, args.author
        )
    elif args.action == "mark":
        result = mark_implemented_sections(args.path, args.sections)
    elif args.action == "remove":
        result = remove_sections(args.path, args.sections)
    else:
        parser.print_help()
        sys.exit(1)

    try:
        print(result)
    except UnicodeEncodeError:
        # Fallback for terminals that can't handle Unicode
        print(result.encode('ascii', errors='replace').decode('ascii'))


if __name__ == "__main__":
    main()
