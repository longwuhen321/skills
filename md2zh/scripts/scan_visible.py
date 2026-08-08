# -*- coding: utf-8 -*-
"""扫描翻译块 input.txt，列出含可见文本的 SEG 内容段（供 AI 翻译）

用法:
    python scan_visible.py <input.txt> [input2.txt ...]

输出格式: [SEG号] 可见文本（跳过空段与纯 PROTECT 标记段）
可见文本 = 内容行不含 @@MD2ZH:PROTECT:@@ 标记，即需要翻译的裸文本。
SEG 后的多行内容属于同一段（段落级 unit），合并显示。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def scan(path):
    lines = open(path, encoding='utf-8-sig').read().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('@@MD2ZH:SEG:'):
            num = line.split(':')[3].rstrip('@')
            i += 1
            content_lines = []
            while i < len(lines) and not lines[i].startswith('@@MD2ZH:SEG:'):
                content_lines.append(lines[i])
                i += 1
            text = '\n'.join(content_lines).strip()
            if text and '@@MD2ZH:PROTECT:' not in text:
                print(f'[{num}] {text}')
        else:
            i += 1


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in sys.argv[1:]:
        print(f'=== {path} ===')
        scan(path)


if __name__ == '__main__':
    main()
