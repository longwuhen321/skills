#!/usr/bin/env python3
"""merge_paragraphs - 合并 Markdown 段落内的源码硬换行（通用能力，所有站点适用）。

markdownify 保留 HTML 源码的硬换行（每行 ~90 字符），把自然段切成 2-6 行短行，
在 Typora 中观感像分段。本脚本把段落合并为整段一行：

  - 普通段落：连续非空行合并为一行（空格连接，保留首行缩进）
  - 列表项：-/*/+ 前缀行 + 后续 2 空格缩进文字续行合并为一行（去尾部 hard-break 空格）
  - 保护（逐字节不动）：
      $$ 公式块内部、公式标签行（缩进 + 行尾两空格，含原始 CRLF/LF/CR 行尾）、嵌套子列表项、
      Sphinx 定义列表（term + 缩进定义段 / ": " 前缀行）、标题/引用/图片/围栏、
      表格行（| 开头）
  - 双空行压缩为单个（块外）

用法：python merge_paragraphs.py <md文件> [更多文件...]

规则要点（踩坑记录见 KNOWN_ISSUES.md 2026-08-07）：
  - 列表项续行判断必须用原始行（strip() 后永远没有前导空格）
  - 空行压缩条件保留单个空行（skip >= 1 时输出一个空行，勿写成 >= 2）
"""

import re
import sys
from markdown_code import markdown_fenced_code_spans

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LIST_HEAD = re.compile(r'^(\s*)([-*+])\s')
LIST_CONT = re.compile(r'^\s{2,}\S')
FORMULA_TAG_HARD_BREAK = re.compile(r'^\s+\S.* {2}$')


def _split_physical_lines(text: str):
    """Return ``(content, eol)`` records while preserving mixed CRLF/LF/CR endings."""
    if not text:
        return [('', '')]
    records = []
    start = 0
    for match in re.finditer(r'\r\n|\r|\n', text):
        records.append((text[start:match.start()], match.group(0)))
        start = match.end()
    if start < len(text):
        records.append((text[start:], ''))
    return records


def _join_physical_lines(records) -> str:
    return ''.join(content + eol for content, eol in records)


def _count_unescaped_double_dollars(value: str) -> int:
    count = 0
    pos = 0
    while True:
        pos = value.find('$$', pos)
        if pos < 0:
            return count
        backslashes = 0
        before = pos - 1
        while before >= 0 and value[before] == '\\':
            backslashes += 1
            before -= 1
        if backslashes % 2 == 0:
            count += 1
        pos += 2


def _protected_line_mask(markdown: str) -> list[bool]:
    """Mark fenced-code and display-math lines that must remain unchanged."""
    records = _split_physical_lines(markdown)
    lines = [content for content, _ in records]
    protected = [False] * len(lines)
    spans = markdown_fenced_code_spans(markdown)
    offset = 0
    span_index = 0
    for index, (line, eol) in enumerate(records):
        line_end = offset + len(line) + len(eol)
        while span_index < len(spans) and spans[span_index][1] <= offset:
            span_index += 1
        if span_index < len(spans):
            start, end = spans[span_index]
            protected[index] = start < line_end and end > offset
        offset = line_end

    in_math = False
    for index, line in enumerate(lines):
        if protected[index]:
            continue
        delimiter_count = _count_unescaped_double_dollars(line)
        if in_math or delimiter_count:
            protected[index] = True
        if delimiter_count % 2:
            in_math = not in_math
    return protected


def _is_structure_line(line: str) -> bool:
    stripped = line.strip()
    return (
        FORMULA_TAG_HARD_BREAK.match(line) is not None
        or
        stripped.startswith('#')
        or stripped.startswith('>')
        or stripped.startswith('![')
        or stripped == '---'
        or stripped.startswith(': ')
        or stripped.startswith('|')
    )


def merge_markdown_paragraphs(markdown: str) -> str:
    """合并段落内的源码硬换行，返回处理后的 Markdown 文本。"""
    records = _split_physical_lines(markdown)
    lines = [content for content, _ in records]
    protected = _protected_line_mask(markdown)
    out = []
    i = 0
    n = len(lines)

    while i < n:
        l = lines[i]
        s = l.strip()

        # 围栏代码与 $$ 公式块（含内部空行）逐字节保留。
        if protected[i]:
            out.append(records[i])
            i += 1
            continue

        if s == '':
            out.append(records[i])
            i += 1
            continue

        # 标题 / 引用 / 图片 / 水平线 / 定义列表标记 / 表格行：单独保留
        if _is_structure_line(l):
            out.append(records[i])
            i += 1
            continue

        # 列表项：首行 + 2 空格缩进文字续行
        m = LIST_HEAD.match(l)
        if m:
            indent = m.group(1)
            cont_indent = indent + '  '
            unit = [l]
            j = i + 1
            while j < n:
                lj = lines[j]
                sj = lj.strip()
                if protected[j] or sj == '' or _is_structure_line(lj):
                    break
                if LIST_HEAD.match(lj):      # 新的列表项（含子列表项）
                    break
                if lj.startswith(cont_indent) and LIST_CONT.match(lj):
                    unit.append(lj)
                    j += 1
                else:
                    break
            if len(unit) > 1:
                merged = unit[0].rstrip()
                for u in unit[1:]:
                    merged += ' ' + u.strip()
                out.append((merged, records[j - 1][1]))
            else:
                out.append(records[i])
            i = j
            continue

        # 普通段落：连续非空、非特殊、非缩进行 合并
        unit = [l]
        j = i + 1
        while j < n:
            lj = lines[j]
            sj = lj.strip()
            if protected[j] or sj == '' or _is_structure_line(lj):
                break
            if LIST_HEAD.match(lj):
                break
            if lj.startswith(' ') and LIST_CONT.match(lj):
                break   # 缩进行（定义列表段/公式标签行/列表续行）不在普通段落里合并
            unit.append(lj)
            j += 1
        if len(unit) > 1:
            merged = unit[0].rstrip()
            for u in unit[1:]:
                merged += ' ' + u.strip()
            out.append((merged, records[j - 1][1]))
        else:
            out.append(records[i])
        i = j

    # 双空行压缩为单个（围栏代码 / $$ 块内部不动）
    text = _join_physical_lines(out)
    records = _split_physical_lines(text)
    protected = _protected_line_mask(text)
    final = []
    pending_blanks = []
    for index, (line, eol) in enumerate(records):
        if protected[index]:
            if pending_blanks:
                final.append(pending_blanks[0])
            pending_blanks = []
            final.append((line, eol))
            continue
        if line.strip() == '':
            pending_blanks.append((line, eol))
            continue
        if pending_blanks:
            final.append(pending_blanks[0])
        pending_blanks = []
        final.append((line, eol))
    # 与旧行为一致：文件尾多余空行全部移除，只保留上一内容行已有的行尾。
    return _join_physical_lines(final)


def main():
    if len(sys.argv) < 2:
        print("用法: python merge_paragraphs.py <md文件> [更多文件...]")
        sys.exit(1)
    for path in sys.argv[1:]:
        try:
            with open(path, encoding='utf-8', newline='') as f:
                text = f.read()
        except OSError as e:
            print(f"❌ 读取失败: {path}: {e}")
            sys.exit(1)
        merged = merge_markdown_paragraphs(text)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(merged)
        print(f"✅ 已合并段落: {path}")


if __name__ == '__main__':
    main()
