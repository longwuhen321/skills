"""Safe parser for the five literal ``*_config`` dictionaries."""

import ast


class ConfigParseError(ValueError):
    """Configuration is not a side-effect-free set of literal dictionaries."""


def parse_config_text(text):
    """Parse literal ``*_config`` assignments without executing Python code."""
    try:
        tree = ast.parse(text, mode='exec')
    except SyntaxError as exc:
        raise ConfigParseError(f'配置语法错误: {exc.msg}（行 {exc.lineno}）') from exc

    groups = {}
    for node in tree.body:
        if (isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            continue  # module docstring
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            raise ConfigParseError(
                f'仅允许 *_config = {{...}} 字面量赋值（行 {getattr(node, "lineno", "?")}）')
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.endswith('_config'):
            raise ConfigParseError(
                f'仅允许 *_config 分组赋值（行 {getattr(node, "lineno", "?")}）')
        if target.id in groups:
            raise ConfigParseError(f'配置分组重复赋值: {target.id}')
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError) as exc:
            raise ConfigParseError(
                f'{target.id} 必须是无函数调用的字面量 dict') from exc
        if not isinstance(value, dict):
            raise ConfigParseError(f'{target.id} 必须是 dict')
        if any(not isinstance(key, str) for key in value):
            raise ConfigParseError(f'{target.id} 的键必须全部是字符串')
        groups[target.id] = value
    return groups
