"""Import-check the complete confluence-tools dependency set; never install it."""

import importlib
import sys


REQUIREMENTS = (
    ('requests', 'requests'),
    ('markdown2', 'markdown2'),
    ('bs4', 'beautifulsoup4'),
    ('markdownify', 'markdownify'),
)


def dependency_failures():
    """Return every failed import as ``(pip, import_name, exception)``."""
    failures = []
    for import_name, pip_name in REQUIREMENTS:
        try:
            importlib.import_module(import_name)
        except Exception as exc:
            failures.append((pip_name, import_name, exc))
    return failures


def missing_dependencies():
    """Return pip package names whose modules cannot actually be imported."""
    return [pip_name for pip_name, _import_name, _exc in dependency_failures()]


def _report_failures(failures):
    names = ', '.join(pip_name for pip_name, _import_name, _exc in failures)
    print('❌ Python 依赖无法导入: ' + names)
    for pip_name, import_name, exc in failures:
        print(f'   - {pip_name}（import {import_name}）: '
              f'{type(exc).__name__}: {exc}')


def require_dependencies():
    """Exit nonzero with one complete report when any dependency is missing."""
    failures = dependency_failures()
    if not failures:
        return
    _report_failures(failures)
    print('   脚本不会自行安装。请先取得用户批准，再由 AI 助手执行 pip install。')
    raise SystemExit(1)


def main():
    failures = dependency_failures()
    if failures:
        _report_failures(failures)
        print('   本检查只报告问题，不会安装或修改环境。')
        return 1
    print('✓ Python 依赖检查通过: requests, markdown2, beautifulsoup4, markdownify')
    return 0


if __name__ == '__main__':
    sys.exit(main())
