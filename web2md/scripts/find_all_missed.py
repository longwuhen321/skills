"""Find ALL remaining *x* and **x** patterns that look like math variables.
Usage: python find_all_missed.py <markdown_file>"""
import re, sys, io
from markdown_code import mask_markdown_code
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1]
with open(fpath, 'r', encoding='utf-8') as f:
    lines = mask_markdown_code(f.read()).splitlines(keepends=True)

italic_math = re.compile(
    r'\*[a-zA-Z]\*(?:[0-9]+|(?:\xa0)?[⋅×+\-\=]|(?:\xa0)?\*\*[ijk]\*\*)'
)
bold_math = re.compile(
    r'\*\*[ijk]\*\*(?:[0-9]+|(?:\xa0)?[⋅×+\-\=])'
)

for i, line in enumerate(lines):
    lineno = i + 1
    stripped = line.strip()
    if not stripped:
        continue
    if stripped.startswith('|') or stripped.startswith('#'):
        continue
    if stripped.startswith('$$') or stripped.startswith('>'):
        continue
    if stripped.startswith('!['):
        continue

    clean = re.sub(r'\$\$[\s\S]*?\$\$', '', stripped)
    clean = re.sub(r'\$[^$]+?\$', '', clean)

    im = italic_math.findall(clean)
    bm = bold_math.findall(clean)

    if im or bm:
        print(f'行 {lineno}:')
        if im:
            print(f'  斜体: {im}')
        if bm:
            print(f'  粗体:   {bm}')
        print(f'  文本:   {clean[:150]}')
        print()
