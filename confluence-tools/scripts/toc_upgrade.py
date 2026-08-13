#!/usr/bin/env python3
"""在 Confluence 原生目录宏与 Easy Heading Macro 之间安全转换。"""

import argparse
import datetime
import hashlib
import io
import os
import re
import sys
import time

from dependency_check import require_dependencies
require_dependencies()

import requests

if getattr(sys.stdout, 'encoding', '').lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from common import (EASY_HEADING_MACRO, MacroConversionError, SKILL_ROOT,
                    TOC_MACRO, TOC_TARGETS, build_toc_macro,
                    check_xhtml_balance, collect_page_tree,
                    collect_space_pages, fetch_page, get_toc_target_macro,
                    load_config, update_page_storage,
                    validate_toc_macro_parameters)
from debug_utils import cleanup_debug


EASY_MACRO = EASY_HEADING_MACRO
TARGETS = TOC_TARGETS
MACRO_TOKEN_PATTERN = re.compile(
    r'<ac:structured-macro\b[^>]*?/?>|</ac:structured-macro\s*>',
    re.IGNORECASE | re.DOTALL)
MACRO_NAME_PATTERN = re.compile(
    r'\bac:name\s*=\s*(["\'])(.*?)\1', re.IGNORECASE | re.DOTALL)
PROTECTED_XHTML_PATTERN = re.compile(
    r'<!\[CDATA\[.*?\]\]>|<!--.*?-->', re.DOTALL)


validate_macro_parameters = validate_toc_macro_parameters


def _macro_name(opening_tag):
    match = MACRO_NAME_PATTERN.search(opening_tag)
    return match.group(2) if match else ''


def find_structured_macros(storage_html):
    """扫描 storage 中的结构化宏，保留每个完整宏的原始跨度。"""
    macros = []
    stack = []
    protected = iter(PROTECTED_XHTML_PATTERN.finditer(storage_html))
    current_protected = next(protected, None)
    for token in MACRO_TOKEN_PATTERN.finditer(storage_html):
        while current_protected and token.start() >= current_protected.end():
            current_protected = next(protected, None)
        if (current_protected
                and current_protected.start() <= token.start() < current_protected.end()):
            continue
        raw = token.group(0)
        if raw.lower().startswith('</'):
            if not stack:
                raise MacroConversionError('发现无对应开始标签的 structured-macro')
            opening = stack.pop()
            macros.append({
                'start': opening['start'],
                'end': token.end(),
                'name': opening['name'],
                'text': storage_html[opening['start']:token.end()],
            })
        elif raw.rstrip().endswith('/>'):
            macros.append({
                'start': token.start(),
                'end': token.end(),
                'name': _macro_name(raw),
                'text': raw,
            })
        else:
            stack.append({
                'start': token.start(),
                'name': _macro_name(raw),
            })
    if stack:
        raise MacroConversionError('发现未闭合的 structured-macro')
    return sorted(macros, key=lambda item: item['start'])


def _apply_edits(storage_html, edits):
    result = storage_html
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def normalize_toc_macros(storage_html, target_macro, macro_parameters):
    """转换页面目录宏，返回 ``(新正文, 统计)``；歧义结构拒绝修改。"""
    if target_macro not in TARGETS:
        raise MacroConversionError(
            f'target_macro 必须是 {" 或 ".join(TARGETS)}')
    parameters = validate_macro_parameters(macro_parameters)
    macros = find_structured_macros(storage_html)
    toc = [item for item in macros if item['name'] == TOC_MACRO]
    easy = [item for item in macros if item['name'] == EASY_MACRO]
    stats = {
        'toc_before': len(toc),
        'easy_before': len(easy),
        'target_macro': target_macro,
        'action': 'none',
        'changed': 0,
    }
    if len(toc) > 1 or len(easy) > 1:
        raise MacroConversionError(
            f'页面宏数量存在歧义：toc={len(toc)}, easy-heading-free={len(easy)}')

    edits = []
    if target_macro == 'easy_heading':
        if toc and easy:
            edits.append((toc[0]['start'], toc[0]['end'], ''))
            stats['action'] = 'remove_toc_keep_existing_easy'
        elif toc:
            edits.append((toc[0]['start'], toc[0]['end'],
                          build_toc_macro('easy_heading', parameters)))
            stats['action'] = 'toc_to_easy_heading'
    else:
        if easy and toc:
            edits.append((easy[0]['start'], easy[0]['end'], ''))
            stats['action'] = 'remove_easy_keep_existing_toc'
        elif easy:
            edits.append((easy[0]['start'], easy[0]['end'],
                          build_toc_macro('toc', parameters)))
            stats['action'] = 'easy_heading_to_toc'

    if edits:
        stats['changed'] = 1
    after = _apply_edits(storage_html, edits)
    after_macros = find_structured_macros(after)
    stats['toc_after'] = sum(
        item['name'] == TOC_MACRO for item in after_macros)
    stats['easy_after'] = sum(
        item['name'] == EASY_MACRO for item in after_macros)
    return after, stats


class ConfluenceTocUpdater:
    """按单页、完整子树或空间范围归一化目录宏。"""

    def __init__(self, space_key=None, target_macro=None, auto_update=None,
                 ai_verify=None):
        cfg = load_config()
        common = cfg['common_config']
        toc_cfg = cfg['toc_upgrade_config']
        debug_cfg = cfg['debug_config']

        self.base_url = common['confluence_url'].rstrip('/')
        self.space_key = (
            space_key if space_key is not None else toc_cfg.get('space', ''))
        self.default_page = toc_cfg.get('default_page', '') or None
        self.target_macro = (
            target_macro if target_macro is not None
            else get_toc_target_macro(common, toc_cfg))
        if self.target_macro not in TARGETS:
            raise MacroConversionError(
                f'target_macro 必须是 {" 或 ".join(TARGETS)}')
        self.recursive = bool(toc_cfg.get('recursive', False))
        self.auto_update = (
            auto_update if auto_update is not None
            else bool(toc_cfg.get('auto_update', True)))
        self.ai_verify = (
            ai_verify if ai_verify is not None
            else bool(toc_cfg.get('ai_verify', False)))
        self.macro_parameters = validate_macro_parameters(
            toc_cfg.get('macro_parameters', {}))
        self.debug_dir = os.path.join(SKILL_ROOT, 'logs', 'toc_upgrade')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f"Bearer {common['confluence_token']}",
            'Content-Type': 'application/json',
        })
        os.makedirs(self.debug_dir, exist_ok=True)
        cleanup_debug(os.path.join(SKILL_ROOT, 'logs'),
                      int(debug_cfg.get('max_size_mb', 50)),
                      int(debug_cfg.get('keep_recent', 20)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.session.close()

    def fetch_page(self, page_id):
        return fetch_page(self.session, self.base_url, page_id)

    def update_page(self, page_info, new_storage):
        return update_page_storage(
            self.session, self.base_url, page_info, new_storage)

    def convert(self, storage_html):
        return normalize_toc_macros(
            storage_html, self.target_macro, self.macro_parameters)

    def save_debug(self, page_info, before, after, stats):
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        folder = os.path.join(self.debug_dir, timestamp)
        os.makedirs(folder, exist_ok=False)
        with open(os.path.join(folder, 'before.html'), 'w', encoding='utf-8') as f:
            f.write(before)
        with open(os.path.join(folder, 'after.html'), 'w', encoding='utf-8') as f:
            f.write(after)
        with open(os.path.join(folder, 'info.txt'), 'w', encoding='utf-8') as f:
            f.write(f"页面 ID: {page_info['page_id']}\n")
            f.write(f"标题: {page_info['title']}\n")
            f.write(f"版本: {page_info['version']}\n")
            f.write('源内容 SHA256: '
                    + hashlib.sha256(before.encode('utf-8')).hexdigest() + '\n')
            f.write('转换后 SHA256: '
                    + hashlib.sha256(after.encode('utf-8')).hexdigest() + '\n')
            f.write(f"目标宏: {self.target_macro}\n")
            f.write(f"操作: {stats['action']}\n")
            f.write(f"转换前: toc={stats['toc_before']}, easy={stats['easy_before']}\n")
            f.write(f"转换后: toc={stats['toc_after']}, easy={stats['easy_after']}\n")
            f.write('Easy Heading 新建参数: '
                    + repr(self.macro_parameters) + '\n')
        print(f"  调试文件已保存: {folder}")
        return folder

    def verify(self, after, stats):
        balanced, report = check_xhtml_balance(after)
        if not balanced:
            return False, f'XHTML 验证失败: {report}'
        if self.target_macro == 'easy_heading':
            valid = stats['toc_after'] == 0 and stats['easy_after'] == 1
        else:
            valid = stats['easy_after'] == 0 and stats['toc_after'] == 1
        if not valid:
            return False, (
                '目标宏数量验证失败: '
                f"toc={stats['toc_after']}, easy={stats['easy_after']}")
        return True, report

    def process_single(self, page_id, depth=0, page_title=''):
        indent = '  ' * depth
        try:
            page_info = self.fetch_page(page_id)
        except Exception:
            time.sleep(3)
            try:
                page_info = self.fetch_page(page_id)
            except Exception as exc:
                return False, f'{indent}❌ 拉取失败: {exc}'

        before = page_info['storage']
        try:
            after, stats = self.convert(before)
        except MacroConversionError as exc:
            return False, f"{indent}❌ {page_info['title']}: {exc}"
        if not stats['changed']:
            return True, (
                f"{indent}{page_info['title']} (v{page_info['version']}) — 无需转换")

        self.save_debug(page_info, before, after, stats)
        passed, report = self.verify(after, stats)
        if not passed:
            return False, f"{indent}❌ {page_info['title']}: {report}"
        if self.ai_verify:
            return True, (
                f"{indent}{page_info['title']} (v{page_info['version']}) — "
                f"{stats['action']}，等待确认")
        if self.auto_update:
            try:
                new_version = self.update_page(page_info, after)
            except Exception as exc:
                return False, f"{indent}❌ {page_info['title']}: PUT 失败 — {exc}"
            return True, (
                f"{indent}{page_info['title']} (v{new_version}) — {stats['action']}")
        return True, (
            f"{indent}{page_info['title']} — {stats['action']}（未自动更新）")

    def confirm_update(self, debug_folder=None):
        if debug_folder is None:
            directories = sorted(
                name for name in os.listdir(self.debug_dir)
                if os.path.isdir(os.path.join(self.debug_dir, name)))
            if not directories:
                print('❌ 找不到 toc_upgrade debug 目录')
                return False
            debug_folder = os.path.join(self.debug_dir, directories[-1])
        after_path = os.path.join(debug_folder, 'after.html')
        info_path = os.path.join(debug_folder, 'info.txt')
        if not os.path.exists(after_path) or not os.path.exists(info_path):
            print('❌ debug 目录缺少 after.html 或 info.txt')
            return False
        with open(after_path, 'r', encoding='utf-8') as f:
            after = f.read()
        metadata = {}
        with open(info_path, 'r', encoding='utf-8') as f:
            for line in f:
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip()] = value.strip()
        page_id = metadata.get('页面 ID')
        try:
            source_version = int(metadata.get('版本', ''))
        except ValueError:
            source_version = None
        source_hash = metadata.get('源内容 SHA256')
        after_hash = metadata.get('转换后 SHA256')
        debug_target = metadata.get('目标宏')
        if (not page_id or source_version is None or not source_hash
                or not after_hash or debug_target not in TARGETS):
            print('❌ debug 元数据缺少页面 ID、版本、哈希或目标宏')
            return False
        if hashlib.sha256(after.encode('utf-8')).hexdigest() != after_hash:
            print('❌ after.html 已被修改，拒绝提交')
            return False
        balanced, balance_report = check_xhtml_balance(after)
        if not balanced:
            print(f'❌ after.html XHTML 验证失败: {balance_report}')
            return False
        macros = find_structured_macros(after)
        toc_count = sum(item['name'] == TOC_MACRO for item in macros)
        easy_count = sum(item['name'] == EASY_MACRO for item in macros)
        target_valid = (
            (debug_target == 'easy_heading' and toc_count == 0 and easy_count == 1)
            or (debug_target == 'toc' and easy_count == 0 and toc_count == 1))
        if not target_valid:
            print('❌ after.html 目标宏数量验证失败')
            return False
        page_info = self.fetch_page(page_id)
        current_hash = hashlib.sha256(
            page_info['storage'].encode('utf-8')).hexdigest()
        if page_info['version'] != source_version or current_hash != source_hash:
            print('❌ 页面已变化，拒绝提交过期转换结果')
            return False
        new_version = self.update_page(page_info, after)
        print(f"  ✅ 页面已更新: v{source_version} → v{new_version}")
        return True

    def _run_batch(self, pages, stop_on_error=False):
        total = len(pages)
        successes = 0
        failures = []
        print(f'共 {total} 个页面待处理')
        for index, entry in enumerate(pages, start=1):
            page_id, title = entry[0], entry[1]
            depth = entry[2] if len(entry) > 2 else 0
            print(f'[{index}/{total}] {"  " * depth}{title} (ID: {page_id})')
            success, message = self.process_single(page_id, depth, title)
            print(f'  {message}')
            if success:
                successes += 1
            else:
                failures.append((page_id, title))
                if stop_on_error:
                    break
        print(f'汇总: {successes}/{total} 成功，{len(failures)} 失败')
        for page_id, title in failures:
            print(f'  - {title} (ID: {page_id})')
        return not failures and successes == total

    def run_single(self, page_id):
        success, message = self.process_single(page_id)
        print(message)
        return success

    def run_recursive(self, page_id, stop_on_error=False):
        pages = collect_page_tree(self.session, self.base_url, page_id)
        return self._run_batch(pages, stop_on_error=stop_on_error)

    def run_space(self, space_key, stop_on_error=False):
        pages = [
            (page_id, title, 0)
            for page_id, title, _version in collect_space_pages(
                self.session, self.base_url, space_key)
        ]
        return self._run_batch(pages, stop_on_error=stop_on_error)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Confluence 目录宏 / Easy Heading Macro 双向转换工具')
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--page-id', default=None, help='目标页面 ID')
    scope.add_argument('--space', default=None, help='整个空间 Key')
    parser.add_argument('--target', choices=TARGETS, default=None,
                        help='目标宏：easy_heading 或 toc')
    parser.add_argument('--recursive', action='store_true', default=None,
                        help='处理根页面及其全部子页面，不限制层级')
    parser.add_argument('--no-recursive', action='store_false', dest='recursive',
                        help='只处理单个页面')
    parser.add_argument('--ai-verify', action='store_true', default=None,
                        help='生成 debug 后暂停，等待确认')
    parser.add_argument('--no-ai-verify', action='store_false', dest='ai_verify',
                        help='不暂停确认')
    parser.add_argument('--no-auto-update', action='store_true',
                        help='只生成 debug，不提交页面更新')
    parser.add_argument('--stop-on-error', action='store_true',
                        help='批量处理遇错立即停止')
    parser.add_argument('--confirm', default=None,
                        help='提交指定 debug 目录；latest 表示最新目录')
    args = parser.parse_args(argv)

    try:
        space_override = '' if args.page_id is not None else args.space
        with ConfluenceTocUpdater(
                space_key=space_override,
                target_macro=args.target,
                auto_update=False if args.no_auto_update else None,
                ai_verify=args.ai_verify) as updater:
            if args.confirm:
                return updater.confirm_update(
                    None if args.confirm == 'latest' else args.confirm)
            page_id = (
                args.page_id if args.page_id is not None
                else (None if args.space is not None else updater.default_page))
            recursive = (
                args.recursive if args.recursive is not None else updater.recursive)
            if page_id and updater.space_key:
                parser.error('页面范围与空间范围不能同时生效，请清空其中一个配置')
            if not page_id and not updater.space_key:
                parser.error(
                    '必须指定 --page-id 或 --space，或在 toc_upgrade_config 中设置默认范围')
            print('=' * 60)
            print('Confluence 目录宏双向转换')
            print(f'目标宏: {updater.target_macro}')
            print('=' * 60)
            if page_id and recursive:
                return updater.run_recursive(
                    page_id, stop_on_error=args.stop_on_error)
            if page_id:
                return updater.run_single(page_id)
            return updater.run_space(
                updater.space_key, stop_on_error=args.stop_on_error)
    except MacroConversionError as exc:
        print(f'❌ 配置错误: {exc}')
        return False
    except Exception as exc:
        print(f'❌ 执行失败: {exc}')
        return False


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
