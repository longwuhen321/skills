#!/usr/bin/env python3
"""merge_paragraphs - 合并 Markdown 段落内的源码硬换行（通用能力，所有站点适用）。

markdownify 保留 HTML 源码的硬换行（每行 ~90 字符），把自然段切成 2-6 行短行，
在 Typora 中观感像分段。本脚本把段落合并为整段一行：

  - 普通段落：连续非空行合并为一行（空格连接，保留首行缩进）
  - 列表项：-/*/+ 前缀行 + 后续 2 空格缩进文字续行合并为一行（去尾部 hard-break 空格）
  - 保护（逐字节不动）：
      $$ 公式块内部、公式标签行（缩进 + 行尾两空格）、嵌套子列表项、
      Sphinx 定义列表（term + 缩进定义段 / ": " 前缀行）、标题/引用/图片/围栏
  - 双空行压缩为单个（块外）

用法：python merge_paragraphs.py <md文件> [更多文件...]

规则要点（踩坑记录见 KNOWN_ISSUES.md 2026-08-07）：
  - 列表项续行判断必须用原始行（strip() 后永远没有前导空格）
  - 空行压缩条件保留单个空行（skip >= 1 时输出一个空行，勿写成 >= 2）
"""

import re
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

LIST_HEAD = re.compile(r'^(\s*)([-*+])\s')
LIST_CONT = re.compile(r'^\s{2,}\S')


def merge_markdown_paragraphs(markdown: str) -> str:
    """合并段落内的源码硬换行，返回处理后的 Markdown 文本。"""
    lines = markdown.split('\n')
    out = []
    i = 0
    n = len(lines)

    while i < n:
        l = lines[i]
        s = l.strip()

        # 公式块：$$ 行切换状态，块内逐字节保留
        if s.startswith('$$'):
            out.append(l)
            i += 1
            continue

        if s == '':
            out.append('')
            i += 1
            continue

        # 标题 / 引用 / 图片 / 围栏 / 水平线 / 定义列表标记：单独保留
        if (s.startswith('#') or s.startswith('>') or s.startswith('![')
                or s.startswith('```') or s == '---' or s.startswith(': ')):
            out.append(l)
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
                if sj == '' or sj.startswith('$$') or sj.startswith('#') or sj.startswith('>') \
                        or sj.startswith('![') or sj.startswith('```') or sj.startswith(': '):
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
                out.append(merged)
            else:
                out.append(unit[0])
            i = j
            continue

        # 普通段落：连续非空、非特殊、非缩进行 合并
        unit = [l]
        j = i + 1
        while j < n:
            lj = lines[j]
            sj = lj.strip()
            if sj == '' or sj.startswith('$$') or sj.startswith('#') or sj.startswith('>') \
                    or sj.startswith('![') or sj.startswith('```') or sj == '---' or sj.startswith(': '):
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
            out.append(merged)
        else:
            out.append(unit[0])
        i = j

    # 双空行压缩为单个（块外；$$ 块内部不动）
    text = '\n'.join(out)
    final = []
    skip = 0
    in_math = False
    for l in text.split('\n'):
        if l.strip().startswith('$$'):
            in_math = not in_math
            final.append(l)
            continue
        if in_math:
            final.append(l)
            continue
        if l.strip() == '':
            skip += 1
            continue
        if skip >= 1:
            final.append('')
        skip = 0
        final.append(l)
    if skip >= 1:
        final.append('')
    return '\n'.join(final)


def main():
    if len(sys.argv) < 2:
        print("用法: python merge_paragraphs.py <md文件> [更多文件...]")
        sys.exit(1)
    for path in sys.argv[1:]:
        try:
            with open(path, encoding='utf-8') as f:
                text = f.read()
        except OSError as e:
            print(f"❌ 读取失败: {path}: {e}")
            sys.exit(1)
        merged = merge_markdown_paragraphs(text)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(merged)
        print(f"✅ 已合并段落: {path}")


if __name__ == '__main__':
    main()
