#!/usr/bin/env python3
"""check_config_sync - 强制检查 scripts/config.py 与 config.example.py 的配置键结构同步。

只做确定性机械对比（键集合 + 值类型），不比值本身：
  - python_path / confluence_token 在 example 中是占位符、在 config.py 中是真实值，
    逐字节对比必然误报
  - 缺键的后果是脚本 .get(key, 默认值) 静默降级到默认值，本脚本把它变成显式门禁

用法：python check_config_sync.py --groups common_config,import_config,...
     （可选 --example-file / --config-file 指定对比文件；--config-text 从 stdin 读取真实配置；
       --groups 指定要检查的分组名（逗号分隔），默认全部）

退出码：0 = 同步；1 = 存在差异；2 = 无法验证（文件缺失/损坏）
"""
import argparse
import sys
from pathlib import Path

if sys.platform == 'win32':
    sys.stdin.reconfigure(encoding='utf-8', errors='replace')
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


class ConfigUnverifiable(Exception):
    """config 文件缺失或损坏，无法完成对比。"""


def parse_config_text(text):
    """解析 Python 配置文件文本，返回 {分组名: {键: 类型名}} 嵌套 dict。

    与 common.py load_config() 同样用 exec 提取，保留所有分组字典。
    损坏（语法错误等）抛 ConfigUnverifiable。
    """
    try:
        ns = {}
        exec(text, ns)
    except Exception as e:
        raise ConfigUnverifiable(f"配置解析失败: {e}")
    return {
        name: {k: type(v).__name__ for k, v in value.items()}
        for name, value in ns.items()
        if isinstance(value, dict) and name.endswith('_config')
    }


def read_config_file(path):
    """读取配置文件文本（显式 utf-8，Windows 无默认编码问题）。"""
    return Path(path).read_text(encoding='utf-8')


def check_config_sync(example_types, config_types, groups):
    """对比 example 与真实配置的键结构。返回 problems。

    problems: [(category, group, key, detail)]，category ∈ missing / extra / type
    """
    problems = []
    for group in groups:
        ex = example_types.get(group, {})
        cfg = config_types.get(group, {})
        for key in ex:
            if key not in cfg:
                problems.append(('missing', group, key,
                                 f"{group} 有键 '{key}'，config.py 未配置，将使用默认值"))
            elif cfg[key] != ex[key]:
                problems.append(('type', group, key,
                                 f"{group}.{key} 类型不一致: example={ex[key]}，config.py={cfg[key]}"))
        for key in cfg:
            if key not in ex:
                problems.append(('extra', group, key,
                                 f"config.py 有键 '{key}'，example 无此键（键名可能漂移）"))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--example-file', default=None, help='example 配置文件路径（默认 scripts 目录上级 config.example.py）')
    parser.add_argument('--config-file', default=None, help='真实配置文件路径（默认本脚本同目录 config.py）')
    parser.add_argument('--config-text', action='store_true',
                        help='从 stdin 读取真实配置文本（供配置向导写入后复核）')
    parser.add_argument('--groups', default=None,
                        help='要检查的分组名（逗号分隔，如 common_config,import_config；默认自动发现 example 中全部 *_config 分组）')
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    example_path = Path(args.example_file) if args.example_file else script_dir.parent / 'config.example.py'
    config_path = Path(args.config_file) if args.config_file else script_dir / 'config.py'

    if not example_path.exists():
        print(f"❌ example 配置文件缺失: {example_path}")
        return 2
    if not args.config_text and not config_path.exists():
        print(f"❌ 真实配置文件缺失: {config_path}")
        return 2

    try:
        example_text = read_config_file(example_path)
        example_types = parse_config_text(example_text)
    except ConfigUnverifiable as e:
        print(f"❌ example 配置无法解析: {e}")
        return 2

    try:
        config_text = sys.stdin.read() if args.config_text else read_config_file(config_path)
        config_types = parse_config_text(config_text)
    except ConfigUnverifiable as e:
        print(f"❌ 真实配置无法解析: {e}")
        return 2

    if args.groups:
        groups = [g.strip() for g in args.groups.split(',') if g.strip()]
    else:
        groups = sorted(example_types.keys())
    if not groups:
        print("❌ 未指定分组且 example 中未发现 *_config 分组")
        return 2

    problems = check_config_sync(example_types, config_types, groups)

    if not problems:
        print(f"✓ 配置同步检查通过（{len(groups)} 个分组全部一致）")
        return 0

    print("✗ 配置同步检查失败，需修复后重跑：")
    for category, group, key, detail in problems:
        print(f"  - [{category}] {detail}")
    print("修复方式：在 config.py 中补齐/修正上述键（参考 config.example.py）。")
    return 1


if __name__ == '__main__':
    sys.exit(main())
