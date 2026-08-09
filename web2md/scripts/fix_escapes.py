r"""Fix \_ -> _ and \* -> * inside $...$ and $$...$$ blocks.
Do NOT touch prose, Markdown code, or \{ \} (legitimate LaTeX)."""
import sys, io
from markdown_code import mask_markdown_code, transform_outside_markdown_code
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1]
with open(fpath, 'r', encoding='utf-8') as f:
    text = f.read()

BS = chr(92)
scan_text = mask_markdown_code(text)
before_us = scan_text.count(BS + '_')
before_st = scan_text.count(BS + '*')

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
        delimiter = '$$' if value.startswith('$$', start) else '$'
        end = find_delimiter(value, delimiter, start + len(delimiter))
        if end < 0:
            return
        yield start, end + len(delimiter), delimiter
        pos = end + len(delimiter)


def fix_math(value):
    pieces = []
    pos = 0
    for start, end, delimiter in math_spans(value):
        pieces.append(value[pos:start])
        content = value[start:end]
        if delimiter == '$$' or len(content) <= 2002:
            content = content.replace(BS + '_', '_').replace(BS + '*', '*')
        pieces.append(content)
        pos = end
    pieces.append(value[pos:])
    return ''.join(pieces)


text = transform_outside_markdown_code(text, fix_math)

scan_text = mask_markdown_code(text)
after_us = scan_text.count(BS + '_')
after_st = scan_text.count(BS + '*')
left_brace = scan_text.count(r'\left{')
print(f'\\_: {before_us} -> {after_us}（已替换 {before_us - after_us} 处）')
print(f'\\*: {before_st} -> {after_st}（已替换 {before_st - after_st} 处）')
print(f'\\left{{（损坏）: {left_brace}')

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(text)
print('已保存。')
