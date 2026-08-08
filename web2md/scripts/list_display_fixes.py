"""列出或安全升级应为展示公式（$$）的行内公式。

用法：python list_display_fixes.py <markdown_file> [--apply]
  --apply 时自动把确定性候选（\\begin{aligned/cases/array/bmatrix} 或含 \\\\ 行断）
  从 $...$ 升级为 $$...$$，只改定界符，公式正文逐字节不变；
  其余候选列出供 AI 助手逐条判断。
"""
import io
import re
import sys
from markdown_code import mask_markdown_code

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def is_escaped(text, pos):
    backslashes = 0
    pos -= 1
    while pos >= 0 and text[pos] == '\\':
        backslashes += 1
        pos -= 1
    return backslashes % 2 == 1


def find_delimiter(text, delimiter, start):
    pos = start
    while True:
        pos = text.find(delimiter, pos)
        if pos < 0 or not is_escaped(text, pos):
            return pos
        pos += len(delimiter)


def inline_math_spans(text):
    """产出真实的行内公式区间，跳过完整的 $$ 块。"""
    pos = 0
    while pos < len(text):
        start = find_delimiter(text, '$', pos)
        if start < 0:
            return
        if text.startswith('$$', start):
            end = find_delimiter(text, '$$', start + 2)
            if end < 0:
                return
            pos = end + 2
            continue

        end = find_delimiter(text, '$', start + 1)
        if end < 0:
            return
        if text.startswith('$$', end):
            pos = end
            continue
        yield start, end + 1
        pos = end + 1


DISPLAY_ENVS = {'aligned', 'cases', 'array', 'bmatrix'}


def analyze_formula(inner):
    reasons = []
    envs = re.findall(r'\\begin\{([^}]+)\}', inner)
    if envs:
        reasons.append('begin:' + ','.join(envs))
    has_linebreak = bool(re.search(r'(?<!\\)\\\\(?!\\)', inner))
    if has_linebreak:
        reasons.append('多行')
    if len(inner) > 200:
        reasons.append('长度=' + str(len(inner)))
    auto_apply = bool(DISPLAY_ENVS.intersection(envs)) or has_linebreak
    return reasons, auto_apply


def display_replacement(text, start, end, inner):
    before = '' if start == 0 or text[start - 1] == '\n' else '\n\n'
    after = '' if end == len(text) or text[end] == '\n' else '\n\n'
    return before + '$$\n' + inner + '\n$$' + after


def line_text(text, pos):
    """返回 pos 所在行的完整文本。"""
    start = text.rfind('\n', 0, pos) + 1
    end = text.find('\n', pos)
    if end == -1:
        end = len(text)
    return text[start:end]


def in_table_row(line):
    """表格行判定：去除首尾空白后以 | 开头且含第二个 |（数据/表头行）。"""
    s = line.strip()
    return s.startswith('|') and s.find('|', 1) >= 0


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--apply'):
        print('用法：python list_display_fixes.py <markdown_file> [--apply]')
        sys.exit(1)

    fpath = sys.argv[1]
    apply_changes = len(sys.argv) == 3
    with open(fpath, 'r', encoding='utf-8') as f:
        text = f.read()
    scan_text = mask_markdown_code(text)

    needs_display = []
    replacements = []
    for start, end in inline_math_spans(scan_text):
        inner = text[start + 1:end - 1]
        line = text[:start].count('\n') + 1
        reasons, auto_apply = analyze_formula(inner)
        if in_table_row(line_text(text, start)):
            # 表格单元格内的公式保持 $ 行内（升级 $$ 会撕裂表格），列候选供 AI 复核
            auto_apply = False
            reasons.append('表格内（保持 $）')
        if reasons:
            needs_display.append((line, inner, reasons, auto_apply))
        if apply_changes and auto_apply:
            replacements.append((start, end, display_replacement(text, start, end, inner)))

    if replacements:
        updated = text
        for start, end, replacement in reversed(replacements):
            updated = updated[:start] + replacement + updated[end:]
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(updated)

    print('需要复核的展示公式：' + str(len(needs_display)))
    if apply_changes:
        print('已自动转换且保持公式正文不变：' + str(len(replacements)))
    print()
    for line, inner, reasons, auto_apply in needs_display:
        rstr = ' | '.join(reasons)
        action = '已自动转换' if apply_changes and auto_apply else ('可自动转换' if auto_apply else '仅复核')
        snippet = inner[:120].replace('\n', ' ')
        print('行 ' + str(line) + ': ' + rstr + ' | ' + action)
        print('  ' + snippet + '...')
        print()


if __name__ == '__main__':
    main()
