#!/usr/bin/env python3
"""Safely read one literal dictionary assignment from a Python config file."""

import ast


class ConfigLiteralError(ValueError):
    """The config is not a single, side-effect-free literal dictionary."""


def parse_literal_dict(text: str, group_name: str) -> dict:
    """Return ``group_name`` using AST location plus ``ast.literal_eval``.

    Only a module docstring and one direct assignment to ``group_name`` are
    accepted. Imports, calls, attribute access, additional assignments, and all
    other executable statements are rejected before any value is evaluated.
    """
    try:
        tree = ast.parse(text, mode='exec')
    except (SyntaxError, ValueError) as exc:
        raise ConfigLiteralError(f'配置语法无效: {exc}') from exc

    value_node = None
    for index, statement in enumerate(tree.body):
        if (index == 0 and isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)):
            continue
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                raise ConfigLiteralError('只允许直接赋值给配置分组名')
            target_name = statement.targets[0].id
            candidate = statement.value
        else:
            raise ConfigLiteralError(
                f'拒绝可执行语句 {type(statement).__name__}；配置只能包含字面量字典赋值'
            )
        if target_name != group_name:
            raise ConfigLiteralError(f'拒绝非目标配置赋值: {target_name}')
        if value_node is not None:
            raise ConfigLiteralError(f'{group_name} 只能赋值一次')
        value_node = candidate

    if value_node is None:
        raise ConfigLiteralError(f'{group_name} 分组缺失')
    try:
        value = ast.literal_eval(value_node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise ConfigLiteralError(
            f'{group_name} 必须是纯字面量字典，禁止函数调用、导入和副作用表达式'
        ) from exc
    if not isinstance(value, dict):
        raise ConfigLiteralError(f'{group_name} 分组不是 dict')
    if any(not isinstance(key, str) for key in value):
        raise ConfigLiteralError(f'{group_name} 的键必须全部是字符串')
    return value
