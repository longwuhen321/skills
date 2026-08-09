"""Read-only publication check with a path-first sensitive-data gate."""

import argparse
import ast
import os
import re
import stat
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_DIRS = {
    'logs', '__pycache__', '.git', '.claude', '.reasonix', '.vscode',
    '.cache', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    '.tox', '.nox', '.hypothesis', '.ipynb_checkpoints',
    '.venv', 'venv', 'node_modules',
}
FORBIDDEN_FILES = {'config.py', '.env'}
FORBIDDEN_SUFFIXES = {'.pyc', '.pyo'}
TEXT_SUFFIXES = {'.md', '.py', '.txt', '.json', '.yaml', '.yml', '.toml'}
SENSITIVE_FILE_STEMS = {'credential', 'credentials'}
SENSITIVE_FILE_SUFFIXES = {'.bin', '.txt', '.key', '.pem', '.p12', '.pfx'}

KEY_VALUE_ASSIGNMENT = re.compile(
    r'''(?im)(?:^|[{,])\s*["']?([A-Za-z_][A-Za-z0-9_-]*)["']?'''
    r'''\s*[:=]\s*'''
    r'''(?:["']([^"'\r\n]+)["']|([^"'\s#,}\r\n]+))''')
BEARER_TOKEN = re.compile(r'(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{20,})')
SENSITIVE_KEY = re.compile(
    r'(?i)(?:^|[_-])(?:token|api[_-]?key)(?:$|[_-])')
KNOWN_TOKEN_PATTERNS = (
    ('OpenAI Token', re.compile(r'(?<![A-Za-z0-9_-])sk-proj-[A-Za-z0-9_-]{20,}')),
    ('GitHub Token', re.compile(r'(?<![A-Za-z0-9_])ghp_[A-Za-z0-9]{20,}')),
    ('JWT', re.compile(
        r'(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{5,}\.'
        r'[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}(?![A-Za-z0-9_-])')),
)


class PackageInspectionError(RuntimeError):
    """The requested tree could not be inspected safely."""


def _relative(path, root):
    return path.relative_to(root).as_posix()


def _looks_placeholder(value):
    lowered = value.strip().lower()
    if not lowered:
        return True
    if lowered in {'no-check', 'nocheck'}:
        return True
    if (lowered.startswith('<') and lowered.endswith('>')) or '${' in lowered:
        return True
    return any(word in lowered for word in (
        'placeholder', 'your-', 'your_', 'example', 'fixture',
        'test-token', 'env-token', 'file-token', 'sample-token',
    ))


def _is_sensitive_key(name):
    return isinstance(name, str) and SENSITIVE_KEY.search(name) is not None


def _is_forbidden_dir_name(name):
    return (name in FORBIDDEN_DIRS or name == 'cache'
            or name.endswith(('_cache', '-cache')))


def _is_forbidden_file_name(name):
    if name in FORBIDDEN_FILES or name.startswith('.env.'):
        return True
    path = Path(name)
    stem = path.stem
    if stem in SENSITIVE_FILE_STEMS:
        return True
    return (path.suffix in SENSITIVE_FILE_SUFFIXES
            and _is_sensitive_key(stem))


def _known_token_matches(text):
    for label, pattern in KNOWN_TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            yield label, match


def _scan_python(path, relative_name):
    """Scan Python literals with AST so regex source/tests are not false positives."""
    try:
        text = path.read_text(encoding='utf-8')
        tree = ast.parse(text, filename=relative_name)
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise PackageInspectionError(
            f'无法解析允许的 Python 文件 {relative_name}: {exc}') from exc

    suspicious = []

    def record(value, lineno, label):
        if isinstance(value, str) and not _looks_placeholder(value):
            suspicious.append(f'{relative_name}:{lineno}（疑似真实 {label}）')

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_node = node.value
            for target in targets:
                if isinstance(target, ast.Name) and _is_sensitive_key(target.id):
                    if isinstance(value_node, ast.Constant):
                        record(value_node.value, node.lineno,
                               f'Token 赋值: {target.id}')
        if isinstance(node, ast.Dict):
            for key_node, value_node in zip(node.keys, node.values):
                if (isinstance(key_node, ast.Constant)
                        and isinstance(key_node.value, str)
                        and _is_sensitive_key(key_node.value)
                        and isinstance(value_node, ast.Constant)):
                    record(value_node.value, value_node.lineno,
                           f'Token 赋值: {key_node.value}')
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in BEARER_TOKEN.finditer(node.value):
                if not _looks_placeholder(match.group(1)):
                    record(match.group(1), node.lineno, 'Bearer Token')
            for label, _match in _known_token_matches(node.value):
                suspicious.append(
                    f'{relative_name}:{node.lineno}（疑似真实 {label}）')
    return suspicious


def _scan_text(path, relative_name):
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise PackageInspectionError(
            f'无法读取允许文本 {relative_name}: {exc}') from exc
    suspicious = []
    for match in KEY_VALUE_ASSIGNMENT.finditer(text):
        value = match.group(2) or match.group(3)
        if _is_sensitive_key(match.group(1)) and not _looks_placeholder(value):
            line = text.count('\n', 0, match.start()) + 1
            suspicious.append(f'{relative_name}:{line}（疑似真实 Token 赋值）')
    for match in BEARER_TOKEN.finditer(text):
        if not _looks_placeholder(match.group(1)):
            line = text.count('\n', 0, match.start()) + 1
            suspicious.append(f'{relative_name}:{line}（疑似 Bearer Token）')
    for label, match in _known_token_matches(text):
        line = text.count('\n', 0, match.start()) + 1
        suspicious.append(f'{relative_name}:{line}（疑似真实 {label}）')
    return suspicious


def _inventory(root):
    """Return (forbidden paths, candidate text files) without reading content."""
    forbidden = []
    candidates = []

    def walk(folder):
        try:
            entries = list(os.scandir(folder))
        except OSError as exc:
            raise PackageInspectionError(f'无法列出目录 {folder}: {exc}') from exc
        for entry in entries:
            path = Path(entry.path)
            rel = _relative(path, root)
            lowered = entry.name.lower()
            if _is_forbidden_dir_name(lowered):
                forbidden.append(rel + '/')
                continue
            if (_is_forbidden_file_name(lowered)
                    or path.suffix.lower() in FORBIDDEN_SUFFIXES):
                forbidden.append(rel)
                continue
            try:
                if entry.is_symlink():
                    forbidden.append(f'{rel}（符号链接）')
                    continue
                attrs = getattr(
                    entry.stat(follow_symlinks=False), 'st_file_attributes', 0)
                if attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                    forbidden.append(f'{rel}（reparse point/junction）')
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                raise PackageInspectionError(f'无法检查路径 {rel}: {exc}') from exc
            if is_dir:
                walk(path)
                continue
            if path.suffix.lower() in TEXT_SUFFIXES:
                try:
                    path.resolve().relative_to(root)
                except (OSError, ValueError):
                    forbidden.append(f'{rel}（解析后越界）')
                    continue
                candidates.append(path)

    walk(root)
    return forbidden, candidates


def inspect_package(root):
    """Return ``(forbidden, suspicious)``; never read text if paths fail."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise PackageInspectionError(f'待发布目录不存在或不是目录: {root}')
    forbidden, candidates = _inventory(root)
    if forbidden:
        return sorted(forbidden), []

    suspicious = []
    for path in candidates:
        relative_name = _relative(path, root)
        if path.suffix.lower() == '.py':
            suspicious.extend(_scan_python(path, relative_name))
        else:
            suspicious.extend(_scan_text(path, relative_name))
    return [], sorted(set(suspicious))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(SKILL_ROOT), help='待发布 Skill 目录（默认当前 Skill 根）')
    args = parser.parse_args(argv)
    try:
        forbidden, suspicious = inspect_package(args.root)
    except PackageInspectionError as exc:
        print(f'❌ 发布检查无法完成: {exc}')
        return 2
    if forbidden:
        print('❌ 待发布目录含禁止路径；未读取任何文本内容：')
        for item in forbidden:
            print(f'  - {item}')
        return 1
    if suspicious:
        print('❌ 允许文本中发现疑似敏感配置：')
        for item in suspicious:
            print(f'  - {item}')
        return 1
    print('✓ 发布检查通过（路径门禁与允许文本敏感项扫描）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
