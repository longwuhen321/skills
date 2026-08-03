# -*- coding: utf-8 -*-
"""扫描翻译块 input.txt，列出含可见文本的 SEG 内容行（供 AI 翻译）

用法:
    python scan_visible.py <input.txt> [input2.txt ...]

输出格式: [SEG号] 可见文本（跳过空行与纯 PROTECT 标记行）
可见文本 = 内容行不含 @@MD2ZH:PROTECT:@@ 标记，即需要翻译的裸文本。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def scan(path):
    lines = open(path, encoding='utf-8-sig').read().split('\n')
    for i, line in enumerate(lines):
        if line.startswith('@@MD2ZH:SEG:'):
            content = lines[i + 1] if i + 1 < len(lines) else ''
            stripped = content.strip()
            if stripped and '@@MD2ZH:PROTECT:' not in content:
                num = line.split(':')[3].rstrip('@')
                print(f'[{num}] {stripped}')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in sys.argv[1:]:
        print(f'=== {path} ===')
        scan(path)


if __name__ == '__main__':
    main()
