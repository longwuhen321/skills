#!/usr/bin/env python3
"""Read-only release check for forbidden paths and likely embedded secrets."""

import argparse
import os
import re
import stat
import sys
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


DENIED_DIRECTORIES = {
    'logs', '__pycache__', '.git', '.claude', '.reasonix', '.vscode',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.cache', 'cache', 'caches',
}
DENIED_FILE_NAMES = {'config.py', '.env'}
DENIED_SUFFIXES = {'.pyc', '.pyo'}
TEXT_SUFFIXES = {
    '.md', '.py', '.txt', '.json', '.yaml', '.yml', '.toml', '.ini', '.cfg',
    '.ps1', '.sh', '.bat', '.cmd', '.html', '.htm', '.css', '.js', '.ts',
}
BARE_ASSIGNMENT_SUFFIXES = {
    '.md', '.txt', '.rst', '.yaml', '.yml', '.toml', '.ini', '.cfg',
    '.html', '.htm', '.xml',
}
TOKEN_NAME = re.compile(r'(^|[._-])tokens?([._-]|$)', re.IGNORECASE)
REPARSE_ATTRIBUTE = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
SECRET_ASSIGNMENT = re.compile(
    r'''(?im)(?:^|[,{}])\s*["']?'''
    r'''((?:[A-Za-z0-9]+[_-])*(?:token|api[_-]?key|secret|password|passwd)'''
    r'''(?:[_-][A-Za-z0-9]+)*)["']?\s*(?::|=(?!=))\s*(?:'''
    r'''(?P<quote>["'])(?P<quoted>[^"'\r\n]*)(?P=quote)'''
    r'''|(?P<bare>\$\{[^}\r\n]+\}|[^\s,;#`}\]]+))'''
)
KNOWN_SECRET = re.compile(
    r'''(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}'''
    r'''|gh[pousr]_[A-Za-z0-9]{30,}'''
    r'''|AKIA[0-9A-Z]{16}'''
    r'''|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})'''
)
PLACEHOLDERS = {
    '', 'token', 'your_token', 'your-token', 'your token', 'replace-me',
    'replace_me', 'changeme', 'change-me', 'placeholder', 'example', 'redacted',
    'none', 'null', 'env-token', 'env_token', 'file-token', 'file_token',
    'sample-token', 'sample_token', 'test-token', 'test_token',
}


class PackageReadError(RuntimeError):
    """The requested package tree could not be inspected completely."""


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _is_placeholder(value: str) -> bool:
    raw = value.strip()
    normalized = raw.strip('<>{}[]').strip().casefold()
    return (
        normalized in PLACEHOLDERS
        or (raw.startswith('${') and raw.endswith('}'))
        or normalized.startswith(('your_', 'your-', 'replace_', 'replace-'))
        or normalized.startswith('/path/to/')
    )


def _denied_file_reason(path: Path):
    name = path.name.casefold()
    if name == 'config.py':
        return '禁止打包真实 config.py'
    if name in DENIED_FILE_NAMES or name.startswith('.env.'):
        return '禁止打包环境配置文件'
    if path.suffix.casefold() in DENIED_SUFFIXES:
        return '禁止打包 Python 缓存文件'
    if TOKEN_NAME.search(name):
        return '禁止打包 Token 文件'
    return None


def _scan_text_file(path: Path, root: Path) -> list[str]:
    if path.suffix.casefold() not in TEXT_SUFFIXES and path.name != 'SKILL.md':
        return []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PackageReadError(
            f'{_relative(path, root)}: 无法读取以完成检查（{exc}）'
        ) from exc
    if b'\x00' in raw:
        return []
    text = raw.decode('utf-8', errors='replace')
    issues = []
    for match in SECRET_ASSIGNMENT.finditer(text):
        value = match.group('quoted')
        if value is None:
            if path.suffix.casefold() not in BARE_ASSIGNMENT_SUFFIXES:
                continue
            value = match.group('bare').strip()
        if not _is_placeholder(value):
            line = text.count('\n', 0, match.start()) + 1
            issues.append(
                f'{_relative(path, root)}:{line}: 疑似敏感值（{match.group(1)}）'
            )
    if not issues:
        for match in KNOWN_SECRET.finditer(text):
            line = text.count('\n', 0, match.start()) + 1
            issues.append(
                f'{_relative(path, root)}:{line}: 疑似敏感值（已知 Token 格式）'
            )
    return issues


def scan_package(root) -> list[str]:
    """Return release-blocking issues without changing the tree.

    Rejected files are reported from metadata only and never opened. Rejected
    directories are not traversed. Symlinks are rejected and never followed.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise PackageReadError(f'{root}: Skill 根目录不存在或不是目录')
    issues = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
        except OSError as exc:
            raise PackageReadError(
                f'{_relative(directory, root)}: 无法枚举目录（{exc}）'
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            rel = _relative(path, root)
            try:
                is_symlink = entry.is_symlink()
                attributes = getattr(
                    entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
            except OSError as exc:
                raise PackageReadError(
                    f'{rel}: 无法读取路径元数据（{exc}）'
                ) from exc
            if is_symlink:
                issues.append(f'{rel}: 禁止打包符号链接')
                continue
            if attributes & REPARSE_ATTRIBUTE:
                issues.append(f'{rel}: 禁止打包 reparse point/junction')
                continue
            if entry.is_dir(follow_symlinks=False):
                if entry.name.casefold() in DENIED_DIRECTORIES:
                    issues.append(f'{rel}/: 禁止打包目录（未读取其内容）')
                else:
                    pending.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                issues.append(f'{rel}: 不支持的文件类型')
                continue
            reason = _denied_file_reason(path)
            if reason:
                issues.append(f'{rel}: {reason}（未读取文件内容）')
                continue
            issues.extend(_scan_text_file(path, root))
    return sorted(issues)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--root', default=str(Path(__file__).resolve().parent.parent),
        help='待发布 Skill 根目录（默认当前 web2md Skill）',
    )
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f'❌ Skill 根目录不存在或不是目录: {root}')
        return 2
    try:
        issues = scan_package(root)
    except PackageReadError as exc:
        print(f'❌ packaging check 无法完成: {exc}')
        return 2
    if issues:
        print('✗ packaging check 未通过：')
        for issue in issues:
            print(f'  - {issue}')
        return 1
    print('✓ packaging check 通过：未发现禁用目录、私有配置、缓存或疑似敏感值')
    return 0


if __name__ == '__main__':
    sys.exit(main())
