"""
Confluence 页面数学公式升级工具

功能：将 Confluence 页面的 storage format 中的原始 LaTeX 标记
      $...$ / $$...$$ / ```latex``` 升级为 Confluence 原生宏
      mathinline / mathblock。

用法:
  python math_upgrade.py --page-id ID [--space KEY] [--recursive] [--align left|center]
  python math_upgrade.py --space KEY [--align left|center]
  python math_upgrade.py --confirm <debug_folder>    # AI 助手验证后确认更新
  python math_upgrade.py --space KEY --stop-on-error  # 批量遇错即停

配置从 scripts/config.py 读取（CLI 参数可覆盖默认值）。
"""

import os
import re
import sys
import io
import time
import argparse
import datetime
import hashlib

from dependency_check import require_dependencies
require_dependencies()

import requests

# 修复 Windows GBK 终端 emoji 编码问题
# 幂等：已 wrap 过则跳过，避免多模块同时 import 时第一个 wrapper 被 GC 关闭底层流
if getattr(sys.stdout, 'encoding', '').lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from common import (SKILL_ROOT, load_config, request_with_retry,
                    collect_space_pages, collect_paginated_results,
                    build_block_template, fetch_page,
                    normalize_heading_inline_math, get_heading_math_mode,
                    compile_inline_math_pattern, inline_math_content,
                    check_xhtml_balance)
from debug_utils import cleanup_debug


def _sanitize_latex(s: str) -> str:
    """清理非法控制序列：\\* 是未定义控制序列（MathJax 报错），归一化为 *"""
    return s.replace(r'\*', '*')


class ConfluenceMathUpdater:
    """拉取 Confluence 页面，将原始 $LaTeX$ 标记升级为原生宏"""

    def __init__(self, space_key=None, math_align=None, auto_update=None,
                 ai_verify=None, allow_math_residuals=False):
        cfg = load_config()
        common = cfg['common_config']
        upgrade_cfg = cfg['upgrade_config']
        debug_cfg = cfg['debug_config']

        self.base_url = common['confluence_url'].rstrip('/')
        self.heading_math_mode = get_heading_math_mode(common)
        self.space_key = space_key or upgrade_cfg.get('space', '')
        self.default_page = upgrade_cfg.get('default_page', '') or None
        self.math_align = math_align if math_align is not None else upgrade_cfg.get('math_align', 'left')
        self.auto_update = auto_update if auto_update is not None else upgrade_cfg.get('auto_update', True)
        self.ai_verify = ai_verify if ai_verify is not None else upgrade_cfg.get('ai_verify', False)
        self.allow_math_residuals = bool(allow_math_residuals)
        self.recursive = upgrade_cfg.get('recursive', True)
        self.max_depth = int(upgrade_cfg.get('max_depth', 0))
        self.block_template = build_block_template(self.math_align)
        self.debug_dir = os.path.join(SKILL_ROOT, 'logs', 'upgrade')

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

    # ── 1. 拉取页面 ──
    def fetch_page(self, page_id):
        """拉取页面详情（委托 common.fetch_page，429/5xx 已内置重试）"""
        return fetch_page(self.session, self.base_url, page_id)

    # ── 2. 转换引擎 ──
    def _upgrade_old_macros(self, storage_html):
        upgraded = 0

        def replace_old_macro(m):
            nonlocal upgraded
            eq_match = re.search(
                r'<ac:parameter ac:name="equation">(.*?)</ac:parameter>',
                m.group(0), re.DOTALL)
            if eq_match:
                upgraded += 1
                return self.block_template.format(content=_sanitize_latex(eq_match.group(1)))
            return m.group(0)

        result = re.sub(
            r'<ac:structured-macro ac:name="mathjax-inline-macro"[^>]*>.*?</ac:structured-macro>',
            replace_old_macro,
            storage_html, flags=re.DOTALL)
        return result, upgraded

    @staticmethod
    def _strip_math_spans(html):
        """剥掉 math class span 的壳（保留内容），返回 (html, 剥壳数)

        内容部分不允许出现 span 标签（`<span` / `</span`），因此嵌套 span
        不匹配、原样保留，保证标签配对完整。
        """
        pattern = re.compile(
            r'<span[^>]*class=["\'][^"\']*math[^"\']*["\'][^>]*>'
            r'(?P<inner>(?:[^<]|<(?!/?span\b)[^>]*>)*)'
            r'</span>')
        stripped = 0

        def unwrap(m):
            nonlocal stripped
            stripped += 1
            return m.group('inner')

        return pattern.sub(unwrap, html), stripped

    def _apply_alignment(self, storage_html):
        r"""Apply the selected alignment to every existing mathblock.

        ``left`` inserts or replaces the alignment parameter. ``center`` removes
        it because the native mathblock default is centered.
        """
        realigned = 0
        alignment_re = re.compile(
            r'<ac:parameter\b[^>]*ac:name=["\']alignment["\'][^>]*>'
            r'.*?</ac:parameter>', re.DOTALL)

        def set_alignment(m):
            nonlocal realigned
            macro = m.group(0)
            params = alignment_re.findall(macro)
            if self.math_align == 'left' and len(params) == 1 \
                    and re.search(r'>\s*left\s*</ac:parameter>', params[0]):
                return macro
            updated = alignment_re.sub('', macro)
            if self.math_align == 'left':
                updated = re.sub(
                    r'(<ac:structured-macro\b[^>]*>)',
                    r'\1<ac:parameter ac:name="alignment">left</ac:parameter>',
                    updated, count=1)
            if updated == macro:
                return macro
            realigned += 1
            return updated

        result = re.sub(
            r'<ac:structured-macro\b(?=[^>]*\bac:name=["\']mathblock["\'])[^>]*>'
            r'(?:(?!</ac:structured-macro>).)*?</ac:structured-macro>',
            set_alignment, storage_html, flags=re.DOTALL)
        return result, realigned

    def convert_math(self, storage_html):
        def escape_latex(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 剥离旧版 mathjax 插件生成的 math span（class 含 math）的壳，保留内容。
        # 只处理内容不含嵌套 span 的 math span：
        #   - 嵌套 span 不匹配 → 结构原样保留，杜绝孤立 </span> 导致 XHTML 400
        #   - 剥壳保留内容 → 公式文本不丢，后续 convert 正常转换
        storage_html, span_removed = self._strip_math_spans(storage_html)

        macros_before_heading = len(re.findall(r'<ac:structured-macro\b', storage_html))
        storage_html, heading_changed = normalize_heading_inline_math(
            storage_html, self.heading_math_mode)
        heading_macro_delta = (
            len(re.findall(r'<ac:structured-macro\b', storage_html))
            - macros_before_heading)
        storage_html, old_upgraded = self._upgrade_old_macros(storage_html)

        protected_parts = re.split(
            r'(<h[1-6]\b[^>]*>.*?</h[1-6]>|'
            r'<ac:structured-macro\b(?:[^>]*/>|.*?</ac:structured-macro>)|'
            r'<code[^>]*>.*?</code>|'
            r'<pre[^>]*>.*?</pre>|'
            r'</?(?:td|tr|th|table|thead|tbody|p|div|h[1-6]|li|ul|ol|br|hr|img|a|strong|blockquote)[^>]*/?>)',
            storage_html, flags=re.DOTALL)

        def convert(text):
            # 块级公式内容禁 HTML 标签字符 < >（防跨 span 吞标签）
            block_before = len(re.findall(r'[$][$]([^$<>]+?)[$][$]', text, re.DOTALL))
            text = re.sub(
                r'[$][$]([^$<>]+?)[$][$]',
                lambda m: self.block_template.format(content=_sanitize_latex(m.group(1).strip())),
                text, flags=re.DOTALL)

            latex_before = len(re.findall(r'```latex(.*?)```', text, re.DOTALL))
            text = re.sub(
                r'```latex(.*?)```',
                lambda m: self.block_template.format(content=_sanitize_latex(m.group(1).strip())),
                text, flags=re.DOTALL)

            inline_count = 0
            upgraded_count = 0

            def replace_inline(m):
                nonlocal inline_count, upgraded_count
                content = _sanitize_latex(inline_math_content(
                    m, repair_markdown_emphasis=True))
                is_complex = (m.group('spaced') is None
                              and '=' in content and len(content) > 20)
                if is_complex:
                    upgraded_count += 1
                    return self.block_template.format(content=content)
                else:
                    inline_count += 1
                    return (
                        '<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
                        f'<ac:parameter ac:name="body">{escape_latex(content)}</ac:parameter>'
                        '</ac:structured-macro>')

            text = compile_inline_math_pattern(
                allow_markdown_emphasis=True).sub(replace_inline, text)

            return text, {
                'inline': inline_count,
                'block': block_before + upgraded_count,
                'latex': latex_before,
                'upgraded': upgraded_count,
            }

        result_parts = []
        stats = {'inline': 0, 'block': 0, 'latex': 0, 'upgraded': 0,
                 'old_macro_upgraded': old_upgraded, 'span_removed': span_removed,
                 'heading_math_changed': heading_changed,
                 'heading_macro_delta': heading_macro_delta,
                 'heading_inline_restored': (
                     heading_changed if self.heading_math_mode == 'literal' else 0)}

        for i, part in enumerate(protected_parts):
            if i % 2 == 1:
                result_parts.append(part)
            else:
                converted, s = convert(part)
                result_parts.append(converted)
                for k in stats:
                    if k in s:
                        stats[k] += s[k]

        return ''.join(result_parts), stats

    def save_debug(self, page_info, before, after, stats):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(self.debug_dir, timestamp)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'before.html'), 'w', encoding='utf-8') as f:
            f.write(before)
        with open(os.path.join(folder, 'after.html'), 'w', encoding='utf-8') as f:
            f.write(after)
        with open(os.path.join(folder, 'info.txt'), 'w', encoding='utf-8') as f:
            f.write(f"页面 ID: {page_info['page_id']}\n")
            f.write(f"标题: {page_info['title']}\n")
            f.write(f"版本: {page_info['version']}\n")
            f.write("源内容 SHA256: "
                    + hashlib.sha256(before.encode('utf-8')).hexdigest() + "\n")
            f.write(f"转换时间: {timestamp}\n")
            f.write(f"旧宏升级 (mathjax-inline → mathblock): {stats.get('old_macro_upgraded', 0)} 处\n")
            f.write(f"行内公式 ($...$ → mathinline):  {stats['inline']} 处\n")
            f.write(f"块级公式 ($$...$$ → mathblock): {stats['block']} 处\n")
            f.write(f"latex 块 (```latex → mathblock): {stats['latex']} 处\n")
            f.write(f"其中 $...$ 升级为 mathblock: {stats.get('upgraded', 0)} 处\n")
            f.write(f"标题公式按 {self.heading_math_mode} 模式归一化: "
                    f"{stats.get('heading_math_changed', 0)} 处\n")
            f.write(f"mathblock 对齐调整 (→ left): {stats.get('realigned', 0)} 处\n")
            f.write(f"剥离 mathjax span 壳: {stats.get('span_removed', 0)} 处\n")
        print(f"调试文件已保存: {folder}")
        return folder

    @staticmethod
    def _check_xhtml_balance(html):
        return check_xhtml_balance(html)

    def verify(self, before, after, stats):
        report = []
        passed = True
        balanced, balance_report = self._check_xhtml_balance(after)
        report.append(f"XHTML 标签配对: {balance_report}")
        if not balanced:
            passed = False
        before_macros = len(re.findall(r'<ac:structured-macro\b', before))
        after_macros = len(re.findall(r'<ac:structured-macro\b', after))
        heading_macro_delta = stats.get(
            'heading_macro_delta', -stats.get('heading_inline_restored', 0))
        expected = (before_macros + stats['inline'] + stats['block']
                    + stats['latex'] + heading_macro_delta)
        report.append(f"已有宏: {before_macros} → 转换后宏: {after_macros} (预期 {expected})")
        if after_macros != expected:
            report.append(f"  ⚠️ 宏数量不匹配，差 {after_macros - expected}")
            passed = False
        else:
            report.append("  ✅ 宏数量正确")

        heading_protection = (
            r'<h[1-6]\b[^>]*>.*?</h[1-6]>|'
            if self.heading_math_mode == 'literal' else '')
        protected_pattern = re.compile(
            heading_protection +
            r'<ac:structured-macro\b[^>]*/>|'
            r'<ac:structured-macro\b.*?</ac:structured-macro>|'
            r'<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>', re.DOTALL)

        def mask(match):
            return ''.join('\n' if char == '\n' else ' ' for char in match.group(0))

        unprotected_after = protected_pattern.sub(mask, after)
        residual_patterns = {
            'inline': compile_inline_math_pattern(allow_markdown_emphasis=True),
            'block': re.compile(r'[$][$]([^$<>]+?)[$][$]', re.DOTALL),
            'latex': re.compile(r'```latex(.*?)```', re.DOTALL),
        }
        residuals = []
        counts = {}
        for kind, pattern in residual_patterns.items():
            matches = list(pattern.finditer(unprotected_after))
            counts[kind] = len(matches)
            for match in matches:
                line = unprotected_after.count('\n', 0, match.start()) + 1
                line_start = unprotected_after.rfind('\n', 0, match.start())
                column = match.start() - line_start
                residuals.append(f'{kind}@{line}:{column}')
        remaining_inline = counts['inline']
        remaining_block = counts['block']
        remaining_latex = counts['latex']
        report.append(f"未转换残留: inline={remaining_inline}, block={remaining_block}, latex={remaining_latex}")
        residual_count = len(residuals)
        if residual_count == 0:
            report.append("  ✅ 无残留")
        elif self.allow_math_residuals:
            report.append("  ⚠️ 已显式允许残留: " + ', '.join(residuals))
        else:
            report.append("  ❌ 存在未转换公式: " + ', '.join(residuals))
            passed = False
        return passed, '\n'.join(report)

    def update_page(self, page_info, new_storage):
        url = f"{self.base_url}/rest/api/content/{page_info['page_id']}"
        new_version = page_info['version'] + 1
        payload = {
            "version": {"number": new_version},
            "title": page_info['title'],
            "type": "page",
            "space": {"key": page_info['space_key']},
            "body": {"storage": {"value": new_storage, "representation": "storage"}}
        }
        resp = request_with_retry(self.session, 'PUT', url, json=payload)
        if not resp.ok:
            print(f"  PUT 失败 ({resp.status_code}): {resp.text[:500]}")
        resp.raise_for_status()
        return new_version

    def get_child_pages(self, page_id):
        url = f"{self.base_url}/rest/api/content/{page_id}/child/page"
        rows = collect_paginated_results(
            self.session, url, base_url=self.base_url,
            params={'limit': 200, 'expand': 'version'})
        return [(r['id'], r['title']) for r in rows]

    def process_single(self, page_id, depth=0, page_title=''):
        indent = "  " * depth
        try:
            page_info = self.fetch_page(page_id)
        except Exception as e:
            # 瞬时网络/服务器抖动：等待后重试一次（5xx 已在请求层重试，这里是兜底）
            time.sleep(3)
            try:
                page_info = self.fetch_page(page_id)
            except Exception as e2:
                return False, f"{indent}❌ 拉取失败: {e2}"

        before = page_info['storage']
        after, stats = self.convert_math(before)
        after, realigned = self._apply_alignment(after)
        stats['realigned'] = realigned

        total = stats['inline'] + stats['block'] + stats['latex']
        old_up = stats.get('old_macro_upgraded', 0)
        heading_changed = stats.get(
            'heading_math_changed', stats.get('heading_inline_restored', 0))
        total_changes = total + old_up + realigned + heading_changed

        if total_changes == 0:
            return True, f"{indent}  {page_info['title']} (v{page_info['version']}) — 无需转换"

        self.save_debug(page_info, before, after, stats)

        passed, report = self.verify(before, after, stats)
        if not passed:
            return False, f"{indent}❌ {page_info['title']}: 验证未通过\n{report}"

        if self.ai_verify:
            return True, (f"{indent}  {page_info['title']} (v{page_info['version']}) "
                          f"— 转换 {total_changes} 处, ⏸️ 等待 AI 助手验证")

        if self.auto_update:
            try:
                new_version = self.update_page(page_info, after)
            except Exception as e:
                err_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    err_msg = e.response.text[:200]
                return False, f"{indent}❌ {page_info['title']}: PUT 失败 — {err_msg}"
            return True, (f"{indent}  {page_info['title']} (v{new_version}) "
                          f"— inline:{stats['inline']} block:{stats['block']} "
                          f"heading:{heading_changed} old:{old_up} realigned:{realigned}")

        return True, f"{indent}  {page_info['title']} — 转换 {total_changes} 处 (未自动更新)"

    def confirm_update(self, debug_folder=None):
        if debug_folder is None:
            dirs = sorted(os.listdir(self.debug_dir))
            if not dirs:
                print("❌ 找不到 debug 目录，请先运行转换")
                return False
            debug_folder = os.path.join(self.debug_dir, dirs[-1])

        after_path = os.path.join(debug_folder, 'after.html')
        if not os.path.exists(after_path):
            print(f"❌ 找不到 {after_path}")
            return False

        with open(after_path, 'r', encoding='utf-8') as f:
            after = f.read()

        info_path = os.path.join(debug_folder, 'info.txt')
        page_id = None
        source_version = None
        source_hash = None
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('页面 ID:'):
                        page_id = line.split(':', 1)[1].strip()
                    elif line.startswith('版本:'):
                        source_version = int(line.split(':', 1)[1].strip())
                    elif line.startswith('源内容 SHA256:'):
                        source_hash = line.split(':', 1)[1].strip()

        if not page_id:
            print("❌ 无法从 debug 文件获取页面 ID")
            return False
        if source_version is None or not source_hash:
            print("❌ debug 元数据缺少源版本或 SHA256；请重新生成转换结果")
            return False

        page_info = self.fetch_page(page_id)
        current_hash = hashlib.sha256(page_info['storage'].encode('utf-8')).hexdigest()
        stale = page_info['version'] != source_version or current_hash != source_hash
        if stale:
            print(f"❌ 页面自转换后已变化（源 v{source_version}，当前 v{page_info['version']}）；"
                  "拒绝提交过期结果，请重新生成转换结果。")
            return False
        new_version = self.update_page(page_info, after)
        print(f"  ✅ 页面已更新: v{page_info['version']} → v{new_version}")
        print(f"  链接: {self.base_url}/spaces/{page_info['space_key']}/pages/{page_id}")
        return True

    def collect_tree(self, root_id, max_depth=0):
        result = []
        queue = [(root_id, '', 0)]
        r = request_with_retry(
            self.session, 'GET',
            f"{self.base_url}/rest/api/content/{root_id}",
            params={'expand': 'version'}, retry_on=(429, 500, 502, 503, 504))
        r.raise_for_status()
        root_title = r.json()['title']
        queue[0] = (root_id, root_title, 0)
        seen = set()

        while queue:
            pid, ptitle, pdepth = queue.pop(0)
            if max_depth and pdepth > max_depth:
                continue
            if pid in seen:
                continue
            seen.add(pid)
            result.append((pid, ptitle, pdepth))
            children = self.get_child_pages(pid)
            for cid, ctitle in children:
                queue.append((cid, ctitle, pdepth + 1))
        return result

    def _run_batch(self, all_pages, stop_on_error=False):
        """批量处理公共逻辑：默认遇错继续，末尾汇总失败列表

        all_pages: [(id, title, depth), ...] 三元组列表
        """
        total = len(all_pages)
        print(f"共 {total} 个页面待处理\n")
        success_count = 0
        failures = []
        for i, entry in enumerate(all_pages):
            pid, ptitle = entry[0], entry[1]
            pdepth = entry[2] if len(entry) > 2 else 0
            indent = pdepth * '  '
            print(f"[{i+1}/{total}] {indent}「{ptitle}」(ID: {pid})")
            success, msg = self.process_single(pid, pdepth, ptitle)
            print(f"  {msg}")
            if success:
                success_count += 1
            else:
                failures.append((pid, ptitle))
                if stop_on_error:
                    break
        print()
        print("=" * 60)
        if failures:
            print(f"汇总: {success_count}/{total} 成功, ❌ {len(failures)} 个页面失败:")
            for pid, ptitle in failures:
                print(f"  - 「{ptitle}」(ID: {pid})")
        else:
            print(f"汇总: {success_count}/{total} 成功 ✅ 全部完成")
        return not failures and success_count == total

    def run_space(self, space_key, stop_on_error=False):
        print(f"\n📂 拉取空间「{space_key}」所有页面...")
        all_pages = collect_space_pages(self.session, self.base_url, space_key)
        # 公共版本返回 (id, title, version)，批量处理只关心 (id, title, depth)
        all_pages = [(pid, ptitle, 0) for pid, ptitle, _v in all_pages]
        return self._run_batch(all_pages, stop_on_error=stop_on_error)

    def run_recursive(self, page_id, max_depth=0, stop_on_error=False):
        print("\n📂 收集子页面树...")
        all_pages = self.collect_tree(page_id, max_depth)
        return self._run_batch(all_pages, stop_on_error=stop_on_error)

    def run_single(self, page_id):
        print(f"\n处理: 页面 (ID: {page_id})")
        success, msg = self.process_single(page_id, 0, '')
        print(f"\n{msg}")
        return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Confluence 数学公式升级工具')
    parser.add_argument('--page-id', default=None, help='单个页面 ID（默认从 config.py 读取）')
    parser.add_argument('--space', default=None, help='空间 Key（默认从 config.py 读取）')
    parser.add_argument('--recursive', action='store_true', default=None,
                        help='递归处理子页面（默认从 config.py 读取）')
    parser.add_argument('--no-recursive', action='store_false', dest='recursive',
                        help='不递归，仅处理单个页面')
    parser.add_argument('--max-depth', type=int, default=-1, help='递归最大深度（-1=读取 config，0=不限）')
    parser.add_argument('--align', default=None, choices=['left', 'center'], help='公式对齐方式（默认从 config.py 读取）')
    parser.add_argument('--ai-verify', action='store_true', default=None,
                        help='转换后暂停等待 AI 助手验证（默认从 config.py 读取）')
    parser.add_argument('--no-ai-verify', action='store_false', dest='ai_verify',
                        help='不暂停，直接更新')
    parser.add_argument('--no-auto-update', action='store_true', help='不自动更新，仅生成 debug 文件')
    parser.add_argument('--stop-on-error', action='store_true',
                        help='批量处理时遇到失败立即停止（默认继续处理并末尾汇总）')
    parser.add_argument('--confirm', default=None, help='AI 助手验证后确认更新（传入 debug 目录路径）')
    parser.add_argument('--allow-math-residuals', action='store_true',
                        help='显式允许验证后仍有公式残留；默认任何残留都失败')

    args = parser.parse_args()

    if args.confirm:
        with ConfluenceMathUpdater() as updater:
            ok = updater.confirm_update(
                args.confirm if args.confirm != 'latest' else None)
        sys.exit(0 if ok else 1)

    with ConfluenceMathUpdater(
            space_key=args.space,
            math_align=args.align,
            auto_update=False if args.no_auto_update else None,
            ai_verify=args.ai_verify,
            allow_math_residuals=args.allow_math_residuals) as updater:
        page_id = args.page_id or updater.default_page
        recursive = args.recursive if args.recursive is not None else updater.recursive
        max_depth = args.max_depth if args.max_depth >= 0 else updater.max_depth

        if not page_id and not updater.space_key:
            parser.error("必须指定 --page-id 或 --space，或在 config.py 的 upgrade_config 中设置 default_page 或 space")

        print("=" * 60)
        print("🔍 Confluence 数学公式升级工具")
        align_label = '左对齐 (mathblock + alignment=left)' if updater.math_align == 'left' else '居中 (mathblock)'
        print(f"  对齐: {align_label}")
        print("=" * 60)

        try:
            if page_id and recursive:
                ok = updater.run_recursive(
                    page_id, max_depth=max_depth,
                    stop_on_error=args.stop_on_error)
            elif page_id:
                ok = updater.run_single(page_id)
            else:
                ok = updater.run_space(
                    updater.space_key, stop_on_error=args.stop_on_error)
        except Exception as exc:
            print(f"❌ 执行失败: {exc}")
            ok = False
    sys.exit(0 if ok else 1)
