#!/usr/bin/env python3
"""Safely load literal Python configuration groups without executing code."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict


class LiteralConfigError(ValueError):
    """The configuration is not a side-effect-free literal module."""


def parse_config_group(text: str, group: str, source: str = "<config>") -> Dict[str, Any]:
    """Return one literal dict assignment from a Python config module.

    Only a module docstring and simple name assignments whose values are accepted by
    ``ast.literal_eval`` are allowed. Imports, calls, control flow, attribute writes,
    duplicate assignments and every other executable statement are rejected.
    """
    try:
        module = ast.parse(text, filename=source, mode="exec")
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise LiteralConfigError("配置语法无效: {}".format(exc)) from exc

    assignments: Dict[str, Any] = {}
    for index, statement in enumerate(module.body):
        if (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue

        name = None
        value_node = None
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            value_node = statement.value
        else:
            raise LiteralConfigError(
                "第 {} 行包含不允许的 {}；配置只允许字面量赋值".format(
                    getattr(statement, "lineno", "?"), type(statement).__name__
                )
            )

        if name in assignments:
            raise LiteralConfigError("配置项 {} 被重复赋值".format(name))
        try:
            assignments[name] = ast.literal_eval(value_node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
            raise LiteralConfigError(
                "第 {} 行的 {} 不是安全字面量；函数调用和表达式不允许".format(
                    getattr(value_node, "lineno", "?"), name
                )
            ) from exc

    config = assignments.get(group)
    if not isinstance(config, dict):
        raise LiteralConfigError("{} 分组缺失或不是 dict".format(group))
    if not all(isinstance(key, str) for key in config):
        raise LiteralConfigError("{} 的所有键必须是字符串".format(group))
    return config


def load_config_group(path: Path, group: str) -> Dict[str, Any]:
    path = Path(path)
    return parse_config_group(path.read_text(encoding="utf-8-sig"), group, str(path))
