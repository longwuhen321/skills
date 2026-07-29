"""
Confluence 页面数学公式升级工具

功能：将 Confluence 页面的 storage format 中的原始 LaTeX 标记
      $...$ / $$...$$ / ```latex``` 升级为 Confluence 原生宏
      mathinline / mathblock。

用法:
  python math_upgrade.py --page-id ID [--space KEY] [--recursive] [--align left|center]
  python math_upgrade.py --space KEY [--align left|center]
  python math_upgrade.py --confirm <debug_folder>    # Claude 验证后确认更新

配置通过环境变量注入（由 Claude skill 写入 settings.local.json）：
  CONFLUENCE_URL    - Confluence 基础 URL
  CONFLUENCE_TOKEN  - Personal Access Token
  CONFLUENCE_SPACE  - 默认空间 Key（可用 --space 覆盖）
"""

import os
import re
import sys
import io
import argparse
import datetime
import requests

# 修复 Windows GBK 终端 emoji 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ── 路径推导 ──
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_ROOT, 'scripts'))
from debug_utils import cleanup_debug


def _get_config():
    """从环境变量读取配置"""
    url = os.environ.get('CONFLUENCE_URL', '')
    token = os.environ.get('CONFLUENCE_TOKEN', '')
    if not url or not token:
        print("❌ 缺少配置: CONFLUENCE_URL 和 CONFLUENCE_TOKEN 必须设置")
        sys.exit(1)
    return {
        'url': url.rstrip('/'),
        'token': token,
        'space': os.environ.get('CONFLUENCE_SPACE', ''),
        'debug_max_mb': int(os.environ.get('CONFLUENCE_DEBUG_MAX_MB', '50')),
        'debug_keep': int(os.environ.get('CONFLUENCE_DEBUG_KEEP', '20')),
    }


def _build_block_template(align: str) -> str:
    """根据对齐配置生成块级公式宏模板"""
    if align == 'left':
        return (
            '<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
            '<ac:parameter ac:name="body">\\displaystyle {content}</ac:parameter>'
            '</ac:structured-macro>'
        )
    else:
        return (
            '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
            '<ac:plain-text-body><![CDATA[{content}]]></ac:plain-text-body>'
            '</ac:structured-macro>'
        )


class ConfluenceMathUpdater:
    """拉取 Confluence 页面，将原始 $LaTeX$ 标记升级为原生宏"""

    def __init__(self, space_key=None, math_align='center'):
        cfg = _get_config()
        self.base_url = cfg['url']
        self.space_key = space_key or cfg['space']
        self.math_align = math_align
        self.block_template = _build_block_template(self.math_align)
        self.debug_dir = os.path.join(SKILL_ROOT, 'debug', 'upgrade')

        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f"Bearer {cfg['token']}",
            'Content-Type': 'application/json',
        })

        os.makedirs(self.debug_dir, exist_ok=True)
        cleanup_debug(os.path.join(SKILL_ROOT, 'debug'),
                      cfg['debug_max_mb'],
                      cfg['debug_keep'])

    # ── 1. 拉取页面 ──
    def fetch_page(self, page_id):
        url = f"{self.base_url}/rest/api/content/{page_id}"
        params = {'expand': 'body.storage,version,space'}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return {
            'page_id': data['id'],
            'title': data['title'],
            'version': data['version']['number'],
            'space_key': data['space']['key'],
            'storage': data['body']['storage']['value'],
            'raw': data,
        }

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
                return self.block_template.format(content=eq_match.group(1))
            return m.group(0)

        result = re.sub(
            r'<ac:structured-macro ac:name="mathjax-inline-macro"[^>]*>.*?</ac:structured-macro>',
            replace_old_macro,
            storage_html, flags=re.DOTALL)
        return result, upgraded

    def _rewrap_mathblocks(self, storage_html):
        if self.math_align == 'center':
            return storage_html, 0

        rewrapped = 0

        def convert_to_inline(m):
            nonlocal rewrapped
            cdata = re.search(r'<!\[CDATA\[(.*?)\]\]>', m.group(0), re.DOTALL)
            if cdata:
                rewrapped += 1
                content = cdata.group(1).strip()
                return self.block_template.format(content=content)
            return m.group(0)

        result = re.sub(
            r'<ac:structured-macro ac:name="mathblock"[^>]*>.*?</ac:structured-macro>',
            convert_to_inline, storage_html, flags=re.DOTALL)
        return result, rewrapped

    def convert_math(self, storage_html):
        def escape_latex(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        storage_html = re.sub(r'<span[^>]*>', '', storage_html)
        storage_html = storage_html.replace('</span>', '')

        storage_html, old_upgraded = self._upgrade_old_macros(storage_html)

        protected_parts = re.split(
            r'(<ac:structured-macro\b(?:[^>]*/>|.*?</ac:structured-macro>)|'
            r'<code[^>]*>.*?</code>|'
            r'<pre[^>]*>.*?</pre>|'
            r'</?(?:td|tr|th|table|thead|tbody|p|div|h[1-6]|li|ul|ol|br|hr|img|a|strong|em|blockquote)[^>]*/?>)',
            storage_html, flags=re.DOTALL)

        def convert(text):
            block_before = len(re.findall(r'[$][$](.+?)[$][$]', text, re.DOTALL))
            text = re.sub(
                r'[$][$](.+?)[$][$]',
                lambda m: self.block_template.format(content=m.group(1).strip()),
                text, flags=re.DOTALL)

            latex_before = len(re.findall(r'```latex(.*?)```', text, re.DOTALL))
            text = re.sub(
                r'```latex(.*?)```',
                lambda m: self.block_template.format(content=m.group(1).strip()),
                text, flags=re.DOTALL)

            inline_count = 0
            upgraded_count = 0

            def replace_inline(m):
                nonlocal inline_count, upgraded_count
                content = m.group(1).strip()
                is_complex = ('=' in content and len(content) > 20)
                if is_complex:
                    upgraded_count += 1
                    return self.block_template.format(content=content)
                else:
                    inline_count += 1
                    return (
                        '<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
                        f'<ac:parameter ac:name="body">{escape_latex(content)}</ac:parameter>'
                        '</ac:structured-macro>')

            text = re.sub(
                r'(?<![$])[$](?![$])(.+?)(?<![$])[$](?![$])',
                replace_inline, text, flags=re.DOTALL)

            return text, {
                'inline': inline_count,
                'block': block_before + upgraded_count,
                'latex': latex_before,
                'upgraded': upgraded_count,
            }

        result_parts = []
        stats = {'inline': 0, 'block': 0, 'latex': 0, 'upgraded': 0,
                 'old_macro_upgraded': old_upgraded}

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
            f.write(f"转换时间: {timestamp}\n")
            f.write(f"旧宏升级 (mathjax-inline → mathblock): {stats.get('old_macro_upgraded', 0)} 处\n")
            f.write(f"行内公式 ($...$ → mathinline):  {stats['inline']} 处\n")
            f.write(f"块级公式 ($$...$$ → mathblock): {stats['block']} 处\n")
            f.write(f"latex 块 (```latex → mathblock): {stats['latex']} 处\n")
            f.write(f"其中 $...$ 升级为 mathblock: {stats.get('upgraded', 0)} 处\n")
        print(f"调试文件已保存: {folder}")
        return folder

    def verify(self, before, after, stats):
        report = []
        passed = True
        before_macros = len(re.findall(r'<ac:structured-macro\b', before))
        after_macros = len(re.findall(r'<ac:structured-macro\b', after))
        expected = before_macros + stats['inline'] + stats['block'] + stats['latex']
        report.append(f"已有宏: {before_macros} → 转换后宏: {after_macros} (预期 {expected})")
        if after_macros != expected:
            report.append(f"  ⚠️ 宏数量不匹配，差 {after_macros - expected}")
            passed = False
        else:
            report.append("  ✅ 宏数量正确")

        unprotected_after = re.sub(
            r'<ac:structured-macro\b.*?</ac:structured-macro>|<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>',
            '', after, flags=re.DOTALL)
        remaining_inline = len(re.findall(
            r'(?<![$])[$](?![$])(.+?)(?<![$])[$](?![$])', unprotected_after, re.DOTALL))
        remaining_block = len(re.findall(r'[$][$](.+?)[$][$]', unprotected_after, re.DOTALL))
        remaining_latex = len(re.findall(r'```latex(.*?)```', unprotected_after, re.DOTALL))
        report.append(f"未转换残留: inline={remaining_inline}, block={remaining_block}, latex={remaining_latex}")
        if remaining_inline + remaining_block + remaining_latex <= 2:
            report.append("  ✅ 无残留" if remaining_inline + remaining_block + remaining_latex == 0
                          else f"  ⚠️ 少量残留 (≤2)，可能为孤立字符，跳过")
        else:
            report.append("  ⚠️ 存在未转换的公式")
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
        resp = self.session.put(url, json=payload)
        if not resp.ok:
            print(f"  PUT 失败 ({resp.status_code}): {resp.text[:500]}")
        resp.raise_for_status()
        return new_version

    def get_child_pages(self, page_id):
        url = f"{self.base_url}/rest/api/content/{page_id}/child/page"
        params = {'limit': 200, 'expand': 'version'}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return [(r['id'], r['title']) for r in resp.json().get('results', [])]

    def process_single(self, page_id, depth=0, page_title='', auto_update=True, claude_verify=False):
        indent = "  " * depth
        try:
            page_info = self.fetch_page(page_id)
        except Exception as e:
            return False, f"{indent}❌ 拉取失败: {e}"

        before = page_info['storage']
        after, stats = self.convert_math(before)
        after, rewrapped = self._rewrap_mathblocks(after)

        total = stats['inline'] + stats['block'] + stats['latex']
        old_up = stats.get('old_macro_upgraded', 0)
        total_changes = total + old_up + rewrapped

        if total_changes == 0:
            return True, f"{indent}  {page_info['title']} (v{page_info['version']}) — 无需转换"

        self.save_debug(page_info, before, after, stats)

        if claude_verify:
            return True, (f"{indent}  {page_info['title']} (v{page_info['version']}) "
                          f"— 转换 {total_changes} 处, ⏸️ 等待 Claude 验证")

        passed, report = self.verify(before, after, stats)
        if not passed:
            return False, f"{indent}❌ {page_info['title']}: 验证未通过\n{report}"

        if auto_update:
            try:
                new_version = self.update_page(page_info, after)
            except Exception as e:
                err_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    err_msg = e.response.text[:200]
                return False, f"{indent}❌ {page_info['title']}: PUT 失败 — {err_msg}"
            return True, (f"{indent}  {page_info['title']} (v{new_version}) "
                          f"— inline:{stats['inline']} block:{stats['block']} "
                          f"old:{old_up} rewrapped:{rewrapped}")

        return True, f"{indent}  {page_info['title']} — 转换 {total_changes} 处 (未自动更新)"

    def confirm_update(self, debug_folder=None):
        if debug_folder is None:
            dirs = sorted(os.listdir(self.debug_dir))
            if not dirs:
                print("❌ 找不到 debug 目录，请先运行转换")
                return
            debug_folder = os.path.join(self.debug_dir, dirs[-1])

        after_path = os.path.join(debug_folder, 'after.html')
        if not os.path.exists(after_path):
            print(f"❌ 找不到 {after_path}")
            return

        with open(after_path, 'r', encoding='utf-8') as f:
            after = f.read()

        info_path = os.path.join(debug_folder, 'info.txt')
        page_id = None
        if os.path.exists(info_path):
            with open(info_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('页面 ID:'):
                        page_id = line.split(':', 1)[1].strip()
                        break

        if not page_id:
            print("❌ 无法从 debug 文件获取页面 ID")
            return

        page_info = self.fetch_page(page_id)
        new_version = self.update_page(page_info, after)
        print(f"  ✅ 页面已更新: v{page_info['version']} → v{new_version}")
        print(f"  链接: {self.base_url}/spaces/{page_info['space_key']}/pages/{page_id}")

    def collect_space_pages(self, space_key):
        all_pages = []
        start = 0
        limit = 200
        while True:
            url = f"{self.base_url}/rest/api/content"
            params = {
                'spaceKey': space_key,
                'type': 'page',
                'limit': limit,
                'start': start,
                'expand': 'version',
            }
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get('results', [])
            if not results:
                break
            all_pages.extend([(r['id'], r['title']) for r in results])
            start += limit
        return all_pages

    def collect_tree(self, root_id, max_depth=0):
        result = []
        queue = [(root_id, '', 0)]
        try:
            r = self.session.get(
                f"{self.base_url}/rest/api/content/{root_id}",
                params={'expand': 'version'})
            r.raise_for_status()
            root_title = r.json()['title']
            queue[0] = (root_id, root_title, 0)
        except Exception:
            return result

        while queue:
            pid, ptitle, pdepth = queue.pop(0)
            if max_depth and pdepth > max_depth:
                continue
            result.append((pid, ptitle, pdepth))
            try:
                children = self.get_child_pages(pid)
            except Exception:
                children = []
            for cid, ctitle in children:
                queue.append((cid, ctitle, pdepth + 1))
        return result

    def run_space(self, space_key, auto_update=True, claude_verify=False):
        print(f"\n📂 拉取空间「{space_key}」所有页面...")
        all_pages = self.collect_space_pages(space_key)
        print(f"共 {len(all_pages)} 个页面待处理\n")
        success_count = 0
        failed = None
        for i, (pid, ptitle) in enumerate(all_pages):
            print(f"[{i+1}/{len(all_pages)}] 「{ptitle}」(ID: {pid})")
            success, msg = self.process_single(pid, 0, ptitle, auto_update=auto_update, claude_verify=claude_verify)
            print(f"  {msg}")
            if success:
                success_count += 1
            else:
                failed = (pid, ptitle)
                break
        print()
        print("=" * 60)
        print(f"汇总: {success_count}/{len(all_pages)} 成功", end='')
        if failed:
            print(f", ❌ 中断于「{failed[1]}」(ID: {failed[0]})")
        else:
            print(" ✅ 全部完成")

    def run_recursive(self, page_id, auto_update=True, claude_verify=False, max_depth=0):
        print("\n📂 收集子页面树...")
        all_pages = self.collect_tree(page_id, max_depth)
        print(f"共 {len(all_pages)} 个页面待处理\n")
        success_count = 0
        failed = None
        for i, (pid, ptitle, pdepth) in enumerate(all_pages):
            print(f"[{i+1}/{len(all_pages)}] {pdepth * '  '}「{ptitle}」(ID: {pid})")
            success, msg = self.process_single(pid, pdepth, ptitle, auto_update=auto_update, claude_verify=claude_verify)
            print(f"  {msg}")
            if success:
                success_count += 1
            else:
                failed = (pid, ptitle)
                break
        print()
        print("=" * 60)
        print(f"汇总: {success_count}/{len(all_pages)} 成功", end='')
        if failed:
            print(f", ❌ 中断于「{failed[1]}」(ID: {failed[0]})")
        else:
            print(" ✅ 全部完成")

    def run_single(self, page_id, auto_update=True, claude_verify=False):
        print(f"\n处理: 页面 (ID: {page_id})")
        success, msg = self.process_single(page_id, 0, '', auto_update=auto_update, claude_verify=claude_verify)
        print(f"\n{msg}")
        if not success:
            sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Confluence 数学公式升级工具')
    parser.add_argument('--page-id', default=None, help='单个页面 ID')
    parser.add_argument('--space', default=None, help='空间 Key（处理整个空间）')
    parser.add_argument('--recursive', action='store_true', help='递归处理子页面（需 --page-id）')
    parser.add_argument('--max-depth', type=int, default=0, help='递归最大深度（0=不限）')
    parser.add_argument('--align', default='left', choices=['left', 'center'], help='公式对齐方式，默认 left')
    parser.add_argument('--claude-verify', action='store_true', help='转换后暂停等待 Claude 验证')
    parser.add_argument('--no-auto-update', action='store_true', help='不自动更新，仅生成 debug 文件')
    parser.add_argument('--confirm', default=None, help='Claude 验证后确认更新（传入 debug 目录路径）')

    args = parser.parse_args()

    if args.confirm:
        updater = ConfluenceMathUpdater(math_align='left')
        updater.confirm_update(args.confirm if args.confirm != 'latest' else None)
        sys.exit(0)

    if not args.page_id and not args.space:
        parser.error("必须指定 --page-id 或 --space")

    print("=" * 60)
    print("🔍 Confluence 数学公式升级工具")
    align_label = '左对齐 (mathinline+\\displaystyle)' if args.align == 'left' else '居中 (mathblock)'
    print(f"  对齐: {align_label}")
    print("=" * 60)

    updater = ConfluenceMathUpdater(space_key=args.space, math_align=args.align)
    auto_update = not args.no_auto_update

    if args.page_id and args.recursive:
        updater.run_recursive(args.page_id, auto_update=auto_update,
                              claude_verify=args.claude_verify, max_depth=args.max_depth)
    elif args.page_id:
        updater.run_single(args.page_id, auto_update=auto_update, claude_verify=args.claude_verify)
    else:
        updater.run_space(args.space, auto_update=auto_update, claude_verify=args.claude_verify)
