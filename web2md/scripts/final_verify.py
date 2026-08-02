"""验证公式转义、展示块、Markdown 表格结构与本地图片引用。

用法：python final_verify.py <markdown_file>
先掩码代码（围栏/行内），再对公式与散文做检查。退出码 0 = 全部通过。
"""
import io
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse
from markdown_code import mask_markdown_code, unclosed_fence_start

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

if len(sys.argv) < 2:
    print('用法：python final_verify.py <markdown_file>')
    sys.exit(1)

fpath = Path(sys.argv[1]).resolve()
text = fpath.read_text(encoding='utf-8', errors='replace')
lines = text.splitlines()
scan_text = mask_markdown_code(text)
scan_lines = scan_text.splitlines()
BS = '\\'
failures = []
reviews = []


def report(label, count, bucket=failures):
    status = 'OK' if count == 0 else ('REVIEW' if bucket is reviews else 'FAIL')
    print(f'[{status}] {label}：{count}')


def is_escaped(value, pos):
    backslashes = 0
    pos -= 1
    while pos >= 0 and value[pos] == BS:
        backslashes += 1
        pos -= 1
    return backslashes % 2 == 1


def find_delimiter(value, delimiter, start):
    pos = start
    while True:
        pos = value.find(delimiter, pos)
        if pos < 0 or not is_escaped(value, pos):
            return pos
        pos += len(delimiter)


def math_spans(value):
    pos = 0
    while pos < len(value):
        start = find_delimiter(value, '$', pos)
        if start < 0:
            return
        if value.startswith('$$', start):
            end = find_delimiter(value, '$$', start + 2)
            if end < 0:
                return
            yield start, end + 2, value[start + 2:end]
            pos = end + 2
            continue
        end = find_delimiter(value, '$', start + 1)
        if end < 0:
            return
        yield start, end + 1, value[start + 1:end]
        pos = end + 1


def is_balanced_latex(value):
    depth = 0
    for pos, char in enumerate(value):
        if char not in '{}':
            continue
        if is_escaped(value, pos):
            continue
        depth += 1 if char == '{' else -1
        if depth < 0:
            return False
    return depth == 0


# 公式转义与展示定界符
esc_underscore = scan_text.count(BS + '_')
esc_star = scan_text.count(BS + '*')
left_broken = scan_text.count(BS + 'left{')
if esc_underscore:
    failures.append('存在转义下划线')
if esc_star:
    failures.append('存在转义星号')
if left_broken:
    failures.append(r'存在损坏的 \left{')
report('转义下划线', esc_underscore)
report('转义星号', esc_star)
report(r'\left{（损坏）', left_broken)

mixed_display = [
    i for i, line in enumerate(scan_lines, 1)
    if '$$' in line and line.strip() != '$$'
]
display_count = sum(line.strip() == '$$' for line in scan_lines)
if mixed_display:
    failures.append('$$ 未独占一行：' + ', '.join(map(str, mixed_display)))
if display_count % 2:
    failures.append('$$ 分隔符数量为奇数')
report('未独占一行的 $$', len(mixed_display))
report('未配对的 $$', display_count % 2)

unclosed_fence = unclosed_fence_start(text)
if unclosed_fence is not None:
    fence_line = text.count('\n', 0, unclosed_fence) + 1
    failures.append(f'代码围栏未闭合：{fence_line}')
report('未闭合的代码围栏', int(unclosed_fence is not None))

math_blocks = list(math_spans(scan_text))
unbalanced_formula_lines = [
    scan_text.count('\n', 0, start) + 1
    for start, _, latex in math_blocks
    if not is_balanced_latex(latex)
]
if unbalanced_formula_lines:
    failures.append(
        'LaTeX 花括号不平衡：' + ', '.join(map(str, unbalanced_formula_lines))
    )
report('LaTeX 花括号不平衡', len(unbalanced_formula_lines))

# aligned 公式完整性
aligned_bad = 0
aligned_pattern = re.compile(r'\\(begin|end)\{aligned\}')
aligned_markers_in_math = 0
for _, _, latex in math_blocks:
    depth = 0
    damaged = False
    for match in aligned_pattern.finditer(latex):
        aligned_markers_in_math += 1
        depth += 1 if match.group(1) == 'begin' else -1
        if depth < 0:
            damaged = True
    if damaged or depth:
        aligned_bad += 1
aligned_bad += len(aligned_pattern.findall(scan_text)) - aligned_markers_in_math
if aligned_bad:
    failures.append('aligned 公式包含损坏转义')
report('aligned 公式损坏', aligned_bad)


# 非代码、非数学的 Markdown 语义
semantic_chars = list(scan_text)
for start, end, _ in math_blocks:
    for pos in range(start, end):
        if semantic_chars[pos] not in '\r\n':
            semantic_chars[pos] = ' '
semantic_text = ''.join(semantic_chars)

html_tags = {
    'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'code', 'col',
    'colgroup', 'dd', 'del', 'details', 'div', 'dl', 'dt', 'em',
    'figcaption', 'figure', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'hr', 'i', 'img', 'ins', 'kbd', 'li', 'mark', 'ol', 'p', 'pre',
    's', 'small', 'span', 'strong', 'sub', 'summary', 'sup', 'table',
    'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul', 'var',
}
placeholder_lines = []
for match in re.finditer(r'<([A-Za-z][^<>\n]*)>', semantic_text):
    inner = match.group(1).strip()
    if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', inner):
        continue
    name = inner.split()[0].lower().rstrip('/')
    if name not in html_tags:
        placeholder_lines.append(semantic_text.count('\n', 0, match.start()) + 1)
placeholder_lines = sorted(set(placeholder_lines))
if placeholder_lines:
    failures.append(
        '正文中存在未保护的尖括号占位符：'
        + ', '.join(map(str, placeholder_lines))
    )
report('未保护的尖括号占位符', len(placeholder_lines))

sphinx_glyphs = semantic_text.count('')
if sphinx_glyphs:
    failures.append('存在残留的 Sphinx 标题永久链接图标')
report('Sphinx 标题图标残留', sphinx_glyphs)

markdown_link_pattern = re.compile(
    r'(?<!!)\[[^\]\n]*\]\((?:<([^>\n]+)>|([^\s)\n]+))'
)
link_scan_chars = list(semantic_text)
for match in re.finditer(r'!\[[^\]]*\]\((?:<[^>\n]+>|[^)\n]+)\)', semantic_text):
    for pos in range(match.start(), match.end()):
        if link_scan_chars[pos] not in '\r\n':
            link_scan_chars[pos] = ' '
link_scan_text = ''.join(link_scan_chars)
missing_relative_links = []
legacy_sphinx_anchors = []
for match in markdown_link_pattern.finditer(link_scan_text):
    target = (match.group(1) or match.group(2)).strip()
    if target.startswith('#cmd'):
        legacy_sphinx_anchors.append(target)
        continue
    parsed = urlparse(target)
    if parsed.scheme or target.startswith(('#', '/', '//')):
        continue
    relative_path = unquote(parsed.path)
    if not re.search(r'[./\\]', relative_path):
        continue
    if relative_path and not (fpath.parent / relative_path).is_file():
        missing_relative_links.append(target)
if missing_relative_links:
    failures.append('相对链接目标不存在')
if legacy_sphinx_anchors:
    failures.append('存在未保留的 Sphinx #cmd 锚点')
report('失效的相对链接', len(missing_relative_links))
report('遗留的 Sphinx #cmd 锚点', len(legacy_sphinx_anchors))

blockquote_syntax_lines = []
for index, line in enumerate(lines):
    if not re.match(r'^\s*\*\*Command Syntax\**[:.]?\s*$', line, re.I):
        continue
    next_index = index + 1
    while next_index < len(lines) and not lines[next_index].strip():
        next_index += 1
    if next_index < len(lines) and re.match(r'^\s*>\s+(?!```)', lines[next_index]):
        blockquote_syntax_lines.append(next_index + 1)
if blockquote_syntax_lines:
    reviews.append(
        '命令语法疑似被转换为引用块：'
        + ', '.join(map(str, blockquote_syntax_lines))
    )
report('命令语法引用块', len(blockquote_syntax_lines), reviews)


# Markdown 表格结构
def table_cells(line):
    stripped = line.strip()
    if stripped.startswith('|'):
        stripped = stripped[1:]
    if stripped.endswith('|'):
        stripped = stripped[:-1]
    return re.split(r'(?<!\\)\|', stripped)


def is_separator(cells):
    return all(re.fullmatch(r'\s*:?-{3,}:?\s*', cell) for cell in cells)


definition_tables = [
    i for i, line in enumerate(lines, 1) if re.match(r'^\s*:\s+\|', line)
]
indented_tables = [
    i for i, line in enumerate(lines, 1) if re.match(r'^(?: {4}|\t)\|', line)
]
if definition_tables:
    failures.append('表格仍嵌套在定义列表中')
if indented_tables:
    failures.append('表格仍有代码块级缩进')
report('定义列表中的表格', len(definition_tables))
report('缩进表格', len(indented_tables))

index = 0
while index < len(lines):
    if not lines[index].strip().startswith('|'):
        index += 1
        continue
    start = index
    block = []
    while index < len(lines) and lines[index].strip().startswith('|'):
        block.append(lines[index])
        index += 1
    rows = [table_cells(line) for line in block]
    separators = [i for i, cells in enumerate(rows) if is_separator(cells)]
    line_no = start + 1
    if not separators:
        reviews.append(f'行 {line_no} 表格没有分隔行')
        continue
    expected = len(rows[separators[0]])
    if any(len(cells) != expected for cells in rows):
        failures.append(f'行 {line_no} 表格列数不一致')
    header = rows[separators[0] - 1] if separators[0] else []
    if header and all(not cell.strip() for cell in header):
        reviews.append(f'行 {line_no} 表头为空，需要语义复核')
    for offset, cells in enumerate(rows):
        comma_cells = sum(cell.rstrip().endswith((',', '，')) for cell in cells)
        if comma_cells >= 2 and any('(' in cell for cell in cells) and any(')' in cell for cell in cells):
            reviews.append(f'行 {line_no + offset} 可能把一个元组拆成多个单元格')

report('表格失败项', sum('表格' in item for item in failures))
report('表格语义复核项', len(reviews), reviews)

# 本地图片引用
image_pattern = re.compile(r'!\[[^\]]*\]\((?:<([^>]+)>|([^)]+))\)')
missing_images = []
remote_relative = []
for match in image_pattern.finditer(text):
    target = (match.group(1) or match.group(2)).strip()
    lowered = target.lower()
    if lowered.startswith(('http://', 'https://', 'data:')):
        continue
    if target.startswith(('/', '//')):
        remote_relative.append(target)
        continue
    local_path = fpath.parent / Path(unquote(target.replace('/', '\\')))
    if not local_path.is_file():
        missing_images.append(str(local_path))
if missing_images:
    failures.append('本地图片引用不存在')
if remote_relative:
    reviews.append('仍有站点相对图片引用')
report('缺失的本地图片', len(missing_images))
report('未本地化的相对图片', len(remote_relative), reviews)
for path in missing_images:
    print('  ' + path)

print()
if failures:
    print('验证失败：')
    for item in failures:
        print('- ' + item)
if reviews:
    print('需要 AI 助手复核：')
    for item in reviews:
        print('- ' + item)
if not failures and not reviews:
    print('公式与 Markdown 结构均验证通过！')

sys.exit(1 if failures or reviews else 0)
