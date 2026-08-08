# -*- coding: utf-8 -*-
"""按 SEG 号翻译映射生成块的 output.txt（供 AI 翻译后写回）

用法:
    python apply_translations.py <input.txt> <output.txt> <translations.json>

translations.json 格式: {"SEG号": "译文", ...}
- 映射中出现的 SEG 内容段替换为译文（译文可多行，自由断句）；未出现的段原样保留
- 每个 SEG 内容段必须有译文（空译文会被 validate-block 拒绝）
- 译文不得引入空行（段落边界保持），避免引入 Markdown 语法字符（\\ * [ ] 等）
- 输出 UTF-8 无 BOM
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def apply(input_path, output_path, mapping):
    text = open(input_path, encoding='utf-8-sig').read()
    lines = text.split('\n')
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('@@MD2ZH:SEG:'):
            out.append(line)
            num = line.split(':')[3].rstrip('@')
            i += 1
            content_lines = []
            while i < len(lines) and not lines[i].startswith('@@MD2ZH:SEG:'):
                content_lines.append(lines[i])
                i += 1
            translated = mapping.get(num)
            if translated is None:
                out.extend(content_lines)
            else:
                out.extend(translated.split('\n'))
        else:
            out.append(line)
            i += 1
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    _, input_path, output_path, mapping_path = sys.argv
    mapping = json.load(open(mapping_path, encoding='utf-8-sig'))
    apply(input_path, output_path, mapping)
    print(f'OK: {output_path}')


if __name__ == '__main__':
    main()
