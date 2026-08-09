#!/usr/bin/env python3
"""Read-only pre-packaging check for forbidden paths and sensitive literals."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


FORBIDDEN_DIRECTORIES = {
    "logs",
    "__pycache__",
    ".git",
    ".claude",
    ".reasonix",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
}
FORBIDDEN_FILES = {"config.py", ".env", "id_rsa", "id_ed25519"}
CACHE_SUFFIXES = {".pyc", ".pyo"}
SENSITIVE_FILE_RE = re.compile(
    r"(?:^|[._-])(?:token|tokens|secret|secrets|credential|credentials)(?:[._-]|$)",
    re.IGNORECASE,
)
TEXT_CONFIG_SUFFIXES = {
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".md",
    ".txt",
    ".rst",
    ".html",
    ".htm",
    ".xml",
    ".ps1",
    ".sh",
    ".cmd",
    ".bat",
}
SENSITIVE_LITERAL_RE = re.compile(
    r'''(?im)^\s*["']?(?:[A-Za-z0-9]+[_-])*'''
    r'''(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|token|secret|password|server[_-]?url|username|account)'''
    r'''(?:[_-][A-Za-z0-9]+)*["']?\s*[:=]\s*(?:'''
    r'''(?P<quote>["'])(?P<quoted>[^"'\r\n]+)(?P=quote)'''
    r'''|(?P<bare>[^\s,;#`]{12,}))'''
)
SENSITIVE_PY_LITERAL_RE = re.compile(
    r'''(?im)(?:^|[{,])\s*["']?(?:[A-Za-z0-9]+[_-])*'''
    r'''(?:api[_-]?(?:key|token)|access[_-]?token|auth[_-]?token|token|secret|password|server[_-]?url|username|account)'''
    r'''(?:[_-][A-Za-z0-9]+)*["']?\s*[:=]\s*'''
    r'''(?P<quote>["'])(?P<quoted>[^"'\r\n]+)(?P=quote)'''
)
KNOWN_SECRET_RE = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
PLACEHOLDER_RE = re.compile(
    r"^(?:|<[^>]+>|\$\{[^}]+\}|your[_ -].*|replace[_ -].*|example|placeholder|none|null|/path/to/.*)$",
    re.IGNORECASE,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _issue(code: str, path: str, detail: str) -> Dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


class PackageReadError(OSError):
    """The package tree could not be inspected deterministically."""


def scan_package(
    root: Path,
    content_loader: Optional[Callable[[Path], bytes]] = None,
) -> List[Dict[str, str]]:
    """Scan without following links or opening paths rejected by name.

    ``content_loader`` is injectable for tests. It is called only for allowed,
    text-like files after all path checks have passed.
    """
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("package root must be a directory")
    content_loader = content_loader or (lambda path: path.read_bytes())
    issues: List[Dict[str, str]] = []

    def relative(path: Path) -> str:
        return path.relative_to(root).as_posix()

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(str(directory)), key=lambda item: item.name.lower())
        except OSError as exc:
            raise PackageReadError(
                "无法读取目录 {}: {}".format(relative(directory), exc)
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            rel = relative(path)
            lower_name = entry.name.lower()
            try:
                attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
            except OSError as exc:
                raise PackageReadError("无法读取路径元数据 {}: {}".format(rel, exc)) from exc
            if entry.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                issues.append(_issue("symlink", rel, "发布包不允许符号链接或目录联接"))
                continue
            if entry.is_dir(follow_symlinks=False):
                if (
                    lower_name in FORBIDDEN_DIRECTORIES
                    or lower_name == ".cache"
                    or lower_name.endswith("_cache")
                    or lower_name.endswith("-cache")
                ):
                    issues.append(_issue("forbidden-directory", rel, "禁用目录；未读取其内容"))
                    continue
                walk(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                issues.append(_issue("unsupported-entry", rel, "不是普通文件"))
                continue
            if lower_name in FORBIDDEN_FILES or lower_name.startswith(".env."):
                issues.append(_issue("forbidden-file", rel, "敏感运行时文件；未读取其内容"))
                continue
            if path.suffix.lower() in CACHE_SUFFIXES:
                issues.append(_issue("cache-file", rel, "Python 缓存文件；未读取其内容"))
                continue
            if SENSITIVE_FILE_RE.search(entry.name):
                issues.append(_issue("sensitive-filename", rel, "疑似凭据文件；未读取其内容"))
                continue
            if path.suffix.lower() not in TEXT_CONFIG_SUFFIXES:
                continue
            try:
                text = content_loader(path).decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise PackageReadError("无法按 UTF-8 读取 {}: {}".format(rel, exc)) from exc
            literal_pattern = (
                SENSITIVE_PY_LITERAL_RE
                if path.suffix.lower() == ".py"
                else SENSITIVE_LITERAL_RE
            )
            for match in literal_pattern.finditer(text):
                value = (match.group("quoted") or match.groupdict().get("bare")).strip()
                if not PLACEHOLDER_RE.match(value):
                    issues.append(
                        _issue("sensitive-value", rel, "发现非占位的敏感配置字面量")
                    )
                    break
            else:
                if KNOWN_SECRET_RE.search(text):
                    issues.append(
                        _issue("sensitive-value", rel, "发现疑似真实 Token 或密钥字面量")
                    )

    walk(root)
    return issues


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent.parent),
        help="待发布目录（默认当前 Skill 根）",
    )
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve(strict=True)
        issues = scan_package(root)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    payload: Dict[str, Any] = {
        "root": str(root),
        "pass": not issues,
        "issue_count": len(issues),
        "issues": issues,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
