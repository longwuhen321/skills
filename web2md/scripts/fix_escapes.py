"""Fix \_ -> _ and \* -> * inside $...$ and $$...$$ blocks.
Do NOT touch \{ \} (legitimate LaTeX)."""
import re, sys, io
from markdown_code import mask_markdown_code, transform_outside_markdown_code
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1]
with open(fpath, 'r', encoding='utf-8') as f:
    text = f.read()

BS = chr(92)
scan_text = mask_markdown_code(text)
before_us = scan_text.count(BS + '_')
before_st = scan_text.count(BS + '*')

def fix_block(m):
    content = m.group(0)
    content = content.replace(BS + '_', '_')
    content = content.replace(BS + '*', '*')
    return content

def fix_outside_code(value):
    # Fix display math ($$...$$)
    value = re.sub(r'\$\$[\s\S]*?\$\$', fix_block, value)
    # Fix inline math ($...$, max 2000 chars to avoid dangling $)
    value = re.sub(r'\$[^$]{1,2000}\$', fix_block, value)
    # Global fallback for any remaining text outside Markdown code.
    value = value.replace(BS + '_', '_')
    return value.replace(BS + '*', '*')


text = transform_outside_markdown_code(text, fix_outside_code)

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
