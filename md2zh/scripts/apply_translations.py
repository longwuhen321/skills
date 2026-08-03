# -*- coding: utf-8 -*-
"""按 SEG 号翻译映射生成块的 output.txt（供 AI 翻译后写回）

用法:
    python apply_translations.py <input.txt> <output.txt> <translations.json>

translations.json 格式: {"SEG号": "译文", ...}
- 映射中出现的 SEG 内容行替换为译文；未出现的行原样保留（PROTECT 行等）
- 每个 SEG 内容行必须有译文（空译文会被 validate-block 拒绝）
- 译文避免引入 Markdown 语法字符（\\ * [ ] 等），引号用中文引号直接书写
- 输出 UTF-8 无 BOM
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def apply(input_path, output_path, mapping):
    text = open(input_path, encoding='utf-8-sig').read()
    lines = text.split('\n')
    out, skip = [], False
    for i, line in enumerate(lines):
        if skip:
            skip = False
            continue
        if line.startswith('@@MD2ZH:SEG:'):
            out.append(line)
            num = line.split(':')[3].rstrip('@')
            content = lines[i + 1] if i + 1 < len(lines) else ''
            out.append(mapping.get(num, content))
            skip = True
        else:
            out.append(line)
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
