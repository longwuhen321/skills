"""
Confluence → Markdown 导出工具 (Confluence 9.x)

将 Confluence 页面（storage format XHTML）导出为 Typora 兼容的 Markdown：

- mathblock / mathinline 原生宏 → $$...$$ / $...$（旧 mathjax 宏兼容）
- code 宏 → ```语言 围栏
- toc 宏 → [toc]
- note / info / warning / tip 等提示宏 → 引用块
- 图片附件下载到 <标题>.assets/，md 内引用改写为相对路径
- 输出目录结构：<page_id>_<标题>/<标题>.md + <标题>.assets/（页面 ID 防同名覆盖，
  导出的目录树可直接用 md_import --dir 反向导入）

用法:
  python md_export.py --page-id <ID> [--recursive|--no-recursive] [--output <目录>]
  python md_export.py --space <KEY> [--output <目录>]

配置从 scripts/config.py 读取（CLI 参数可覆盖默认值）。
"""

import os
import re
import sys
import io
import html
import json
import argparse
import secrets
import datetime

from dependency_check import require_dependencies
require_dependencies()

import requests
from pathlib import Path

# 修复 Windows GBK 终端 emoji 编码问题（幂等，与 md_import/math_upgrade 一致）
if getattr(sys.stdout, 'encoding', '').lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from bs4 import BeautifulSoup
import markdownify

from common import (SKILL_ROOT, load_config, request_with_retry,
                    collect_space_pages, collect_paginated_results, fetch_page)
from debug_utils import cleanup_debug


class ConfluenceExporter:
    """Confluence 页面 → Typora 兼容 Markdown 导出器"""

    def __init__(self, space_key=None, recursive=None, output_dir=None):
        cfg = load_config()
        common = cfg['common_config']
        export_cfg = cfg.get('export_config', {})
        debug_cfg = cfg.get('debug_config', {})

        self.base_url = common['confluence_url'].rstrip('/')
        self.space_key = space_key or export_cfg.get('space', '')
        self.recursive = recursive if recursive is not None else bool(
            export_cfg.get('recursive', True))
        self.output_dir = Path(output_dir or export_cfg.get('output_dir', 'confluence_export'))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f"Bearer {common['confluence_token']}",
        })
        self.headers = {'Content-Type': 'application/json'}

        # 调试目录：每页原始 storage 快照（与 md_import/math_upgrade 一致的机制）
        self.debug_dir = os.path.join(SKILL_ROOT, 'logs', 'export')
        os.makedirs(self.debug_dir, exist_ok=True)
        cleanup_debug(os.path.join(SKILL_ROOT, 'logs'),
                      int(debug_cfg.get('max_size_mb', 50)),
                      int(debug_cfg.get('keep_recent', 20)))

        # 占位符随机后缀：防止与页面正文撞车
        self._token = secrets.token_hex(4)
        # CDATA 内容缓存（html.parser 不解析 CDATA，先替换为占位符）
        self._cdata = []
        # 附件列表缓存（每页拉一次）
        self._attachments_cache = {}
        # 统计
        self.stats = {'pages': 0, 'images': 0, 'failed_images': 0,
                      'skipped_macros': set()}
        self.failed_pages = []

    # ── 1. 数据获取 ──

    def fetch_page(self, page_id):
        """拉取页面详情（委托 common.fetch_page，429/5xx 已内置重试）"""
        return fetch_page(self.session, self.base_url, page_id)

    def get_child_pages(self, page_id):
        """拉取直接子页面，返回 [(id, title), ...]"""
        url = f"{self.base_url}/rest/api/content/{page_id}/child/page"
        rows = collect_paginated_results(
            self.session, url, base_url=self.base_url, params={'limit': 200})
        return [(r['id'], r['title']) for r in rows]

    def fetch_attachments(self, page_id):
        """分页拉取页面全部附件列表"""
        if page_id in self._attachments_cache:
            return self._attachments_cache[page_id]
        url = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"
        result = collect_paginated_results(
            self.session, url, base_url=self.base_url,
            params={'expand': 'version', 'limit': 200})
        self._attachments_cache[page_id] = result
        return result

    def _download_attachment(self, attachment, assets_dir):
        """下载单个附件到 assets 目录，返回本地文件名（{id}_{原名}）；失败返回 None"""
        raw_title = str(attachment.get('title', '')).replace('\\', '/')
        basename = self._sanitize_filename(raw_title.rsplit('/', 1)[-1])
        safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', str(attachment.get('id', 'attachment')))
        filename = f"{safe_id}_{basename}"
        dl = attachment.get('_links', {}).get('download')
        if not dl:
            print(f"  ⚠️ 附件无下载链接: {attachment.get('title')}")
            return None
        url = dl if dl.startswith('http') else self.base_url + dl
        try:
            resp = request_with_retry(self.session, 'GET', url, stream=True,
                                      timeout=60, retry_on=(429, 500, 502, 503, 504))
            resp.raise_for_status()
            assets_root = Path(assets_dir).resolve()
            destination = (assets_root / filename).resolve()
            try:
                destination.relative_to(assets_root)
            except ValueError:
                raise ValueError(f'附件路径越界: {filename}')
            with open(destination, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return filename
        except Exception as e:
            print(f"  ⚠️ 附件下载失败 {filename}: {e}")
            return None

    # ── 2. storage XHTML → Markdown ──

    def _placeholder(self, kind, i):
        return f"⟦MDX-{self._token}-{kind}-{i}⟧"

    def _protect_cdata(self, storage_html):
        """把 <![CDATA[...]]> 内容存起来并替换为占位符（html.parser 不解析 CDATA）"""
        self._cdata = []

        def repl(m):
            self._cdata.append(m.group(1))
            return self._placeholder('CDATA', len(self._cdata) - 1)

        return re.sub(r'<!\[CDATA\[(.*?)\]\]>', repl, storage_html, flags=re.DOTALL)

    def _macro_body_text(self, macro):
        """取宏正文文本：plain-text-body（CDATA）> body 参数 > equation 参数（旧 mathjax 宏）"""
        body = macro.find('ac:plain-text-body')
        if body is not None:
            text = body.get_text()
            m = re.fullmatch(rf'⟦MDX-{self._token}-CDATA-(\d+)⟧', text.strip())
            if m:
                return self._cdata[int(m.group(1))].strip()
            return text.strip()
        for param_name in ('body', 'equation'):
            param = macro.find('ac:parameter', {'ac:name': param_name})
            if param is not None:
                return html.unescape(param.get_text()).strip()
        return ''

    def _convert_macros(self, soup):
        """把 Confluence 宏替换为占位符元素，返回 (math_blocks, math_inlines, codes, tocs)

        math_blocks: {占位符: LaTeX}     → $$...$$
        math_inlines: {占位符: LaTeX}    → $...$
        codes: {占位符: 代码原文}        → 围栏内内容
        tocs: [占位符]                   → [toc]
        """
        math_blocks = {}
        math_inlines = {}
        codes = {}
        tocs = []
        unknowns = []
        counters = {'MB': 0, 'MI': 0, 'CODE': 0, 'TOC': 0, 'UNK': 0}

        def ph(kind):
            i = counters[kind]
            counters[kind] += 1
            return self._placeholder(kind, i)

        for macro in soup.find_all('ac:structured-macro'):
            name = macro.get('ac:name', '')
            if name in ('mathblock', 'mathjax-block-macro'):
                content = self._macro_body_text(macro)
                p = ph('MB')
                math_blocks[p] = content
                div = soup.new_tag('div')
                div.string = p
                macro.replace_with(div)
            elif name in ('mathinline', 'mathjax-inline-macro'):
                content = self._macro_body_text(macro)
                p = ph('MI')
                math_inlines[p] = content
                span = soup.new_tag('span')
                span.string = p
                macro.replace_with(span)
            elif name == 'code':
                lang = ''
                lang_param = macro.find('ac:parameter', {'ac:name': 'language'})
                if lang_param:
                    lang = lang_param.get_text(strip=True)
                content = self._macro_body_text(macro)
                p = ph('CODE')
                codes[p] = content
                pre = soup.new_tag('pre')
                code = soup.new_tag('code')
                if lang:
                    code['class'] = f'language-{lang}'
                code.string = p
                pre.append(code)
                macro.replace_with(pre)
            elif name == 'toc':
                p = ph('TOC')
                tocs.append(p)
                div = soup.new_tag('div')
                div.string = p
                # toc 宏常嵌在 h1 内（<h1><ac:toc/><br/>标题</h1>）：占位 div 移到
                # 父元素之前，保证 markdownify 输出时 [toc] 独占一行（Typora 目录要求）
                parent = macro.parent
                if parent is not None and parent.name not in ('[document]', 'html', 'body'):
                    parent.insert_before(div)
                    macro.decompose()
                else:
                    macro.replace_with(div)
            elif name in ('note', 'info', 'warning', 'error', 'tip', 'success'):
                # 提示宏 → 引用块（保留宏内部内容）
                body = macro.find(['ac:rich-text-body', 'ac:plain-text-body'])
                bq = soup.new_tag('blockquote')
                if body:
                    for child in list(body.children):
                        bq.append(child.extract())
                macro.replace_with(bq)
            elif name == 'anchor':
                macro.decompose()
            else:
                # 未知宏：保留正文，并在正文前放可还原的原始 XHTML 注释。
                raw_xhtml = str(macro)
                for i, cdata in enumerate(self._cdata):
                    raw_xhtml = raw_xhtml.replace(
                        self._placeholder('CDATA', i), cdata)
                encoded_xhtml = html.escape(raw_xhtml, quote=False).replace(
                    '--', '&#45;&#45;')
                p = ph('UNK')
                unknowns.append((p, name, encoded_xhtml))
                div = soup.new_tag('div')
                marker = soup.new_tag('span')
                marker.string = p
                div.append(marker)
                body = macro.find(['ac:rich-text-body', 'ac:plain-text-body'])
                if body is not None:
                    for child in list(body.children):
                        div.append(child.extract())
                macro.replace_with(div)
                self.stats['skipped_macros'].add(name)

        return math_blocks, math_inlines, codes, tocs, unknowns

    def _drop_empty_pres(self, soup):
        """删除空 <pre>（仅 <br>/空白，页面作者留白用）——避免 markdownify 输出空代码围栏"""
        for pre in soup.find_all('pre'):
            if not pre.get_text(strip=True):
                pre.decompose()

    def _convert_links(self, soup):
        """ac:link（内链/外链/附件/用户链接）→ <a> 标签，由 markdownify 转 markdown 链接

        ri:url → 外链；ri:page / ri:child-page → 有 content-id 时生成页面 URL，
        仅有 content-title（无 id）则保留标题文本（无法构造可靠 URL）。
        显示文本优先取 ac:link-body，缺失时用标题/URL 兜底。
        """
        for link in soup.find_all('ac:link'):
            body = link.find('ac:link-body')
            text = body.get_text(strip=True) if body else ''
            href = ''
            ri = link.find(['ri:page', 'ri:child-page', 'ri:url',
                            'ri:attachment', 'ri:user'])
            if ri is None:
                link.decompose()
                continue
            if ri.name == 'ri:url':
                href = ri.get('ri:value', '')
                if not text:
                    text = href
            elif ri.name in ('ri:page', 'ri:child-page'):
                cid = ri.get('ri:content-id', '')
                title = ri.get('ri:content-title', '')
                if not text:
                    text = title or '页面'
                if cid:
                    href = f"{self.base_url}/pages/viewpage.action?pageId={cid}"
            elif ri.name == 'ri:attachment':
                if not text:
                    text = ri.get('ri:filename', '附件')
            else:  # ri:user
                if not text:
                    text = ri.get('ri:userkey', '用户')
            if not text:
                link.decompose()
                continue
            a = soup.new_tag('a', href=href) if href else soup.new_tag('span')
            a.string = text
            link.replace_with(a)

        # ri:url may also appear directly inside an unknown macro body.
        for ri in soup.find_all('ri:url'):
            href = ri.get('ri:value', '')
            if not href:
                ri.decompose()
                continue
            a = soup.new_tag('a', href=href)
            a.string = href
            ri.replace_with(a)

    def _code_language_callback(self, el):
        """markdownify 的 convert_pre 把 <pre> 元素传给回调，需从内部
        <code class="language-xx"> 提取语言（新版 markdownify 默认无提取）"""
        code = el.find('code')
        if code is None:
            return ''
        for c in (code.get('class') or []):
            if c.startswith('language-'):
                return c[len('language-'):]
        return ''

    def _convert_images(self, soup, page_id, page_dir):
        """把附件或外链 ``ac:image`` 改写为 ``img``。

        assets 目录懒创建：页面无图时不产生 <标题>.assets/ 文件夹。
        """
        title = page_dir.name.split('_', 1)[1] if '_' in page_dir.name else page_dir.name
        assets_dir = page_dir / f"{title}.assets"
        by_name = None
        for image in soup.find_all('ac:image'):
            ri = image.find('ri:attachment')
            ri_url = image.find('ri:url')
            alt_param = image.find('ac:parameter', {'ac:name': 'alt'})
            alt = (image.get('ac:alt')
                   or (alt_param.get_text(strip=True)
                       if alt_param and alt_param.get_text(strip=True) else ''))
            if ri is None and ri_url is not None:
                external_url = ri_url.get('ri:value', '').strip()
                if external_url:
                    img = soup.new_tag(
                        'img', src=external_url, alt=alt or '图片')
                    image.replace_with(img)
                    continue
            if ri is None:
                self.stats['failed_images'] += 1
                image.replace_with('<!-- 图片未导出: 缺少附件或外链地址 -->')
                continue
            filename = ri.get('ri:filename', '')
            alt = alt or filename or '图片'
            if by_name is None:
                attachments = self.fetch_attachments(page_id)
                by_name = {a.get('title'): a for a in attachments}
            att = by_name.get(filename)
            if att:
                assets_dir.mkdir(parents=True, exist_ok=True)
                saved = self._download_attachment(att, assets_dir)
                if saved:
                    img = soup.new_tag('img', src=f'./{assets_dir.name}/{saved}', alt=alt)
                    image.replace_with(img)
                    self.stats['images'] += 1
                    continue
            self.stats['failed_images'] += 1
            image.replace_with(f'<!-- 图片未导出: {filename or "?"} -->')

    def _protect_complex_tables(self, soup):
        """表格降级保护（在宏/图片转换之后调用）

        GFM/Typora 表格单元格不能含多行围栏代码块，markdownify 把表格内的
        <pre><code> 输出为围栏会彻底破坏表格结构（行列错乱、| 误判列分隔）。
        处理：
        - 含块级内容（pre/code 等）的表格 → 整体保留为原始 HTML
          （Typora 原生渲染 HTML 表格，代码/图片/公式引用均不丢失）
        - 纯文本表格 → 继续走 GFM，但单元格文本内的 | 转义为 \\|，防止破坏列结构
        返回 {占位符: 原始 HTML 表格}，还原阶段替换回。
        """
        tables = {}
        counter = [0]

        def ph():
            p = self._placeholder('TABLE', counter[0])
            counter[0] += 1
            return p

        for table in soup.find_all('table'):
            if table.find(['pre', 'code', 'ac:structured-macro']):
                # 含块级内容 → 保留原始 HTML
                p = ph()
                tables[p] = str(table)
                div = soup.new_tag('div')
                div.string = p
                table.replace_with(div)
            else:
                # 纯文本表格 → GFM；单元格文本的 | 转义
                for cell in table.find_all(['td', 'th']):
                    for txt in cell.find_all(string=True):
                        if '|' in txt:
                            txt.replace_with(txt.replace('|', r'\|'))
        return tables

    def _convert_storage_to_markdown(self, storage_html, page_dir, page_id):
        """storage XHTML → Typora 兼容 Markdown（含图片下载与引用改写）"""
        html_content = self._protect_cdata(storage_html)
        soup = BeautifulSoup(html_content, 'html.parser')

        self._drop_empty_pres(soup)
        math_blocks, math_inlines, codes, tocs, unknowns = self._convert_macros(soup)
        self._convert_images(soup, page_id, page_dir)
        self._convert_links(soup)
        tables = self._protect_complex_tables(soup)

        md = markdownify.MarkdownConverter(
            heading_style='ATX', bullets='-',
            code_language_callback=self._code_language_callback)
        text = md.convert(str(soup))

        # 先整理结构空行。此时公式/代码/表格等载荷仍是单行占位符，
        # 因而不会压缩代码或公式载荷内部的空行。
        text = re.sub(r'\n{3,}', '\n\n', text)

        # 还原占位符（公式/代码/[toc]/未知宏注释/HTML 表格 原样输出，避免被 markdownify 转义）
        # 注意顺序：HTML 表格先还原（其内部可能含 CODE/MI/MB/TOC 等占位符），
        # 其余占位符随后做全局替换，会一并作用于刚插入的 HTML 部分。
        for p, raw in tables.items():
            text = text.replace(p, raw)
        for p, content in math_blocks.items():
            text = text.replace(p, f'$${content}$$')
        for p, content in math_inlines.items():
            text = text.replace(p, f'${content}$')
        for p, content in codes.items():
            text = text.replace(p, content)
        for p in tocs:
            text = text.replace(p, '[toc]')
        for p, name, encoded_xhtml in unknowns:
            safe_name = re.sub(r'-{2,}', '-', name).rstrip('-') or 'unknown'
            text = text.replace(
                p,
                f'<!-- 未处理的宏: {safe_name}\n'
                f'原始 Confluence XHTML: {encoded_xhtml} -->')
        for i, c in enumerate(self._cdata):
            text = text.replace(self._placeholder('CDATA', i), c)

        return text.strip() + '\n'

    # ── 3. 导出流程 ──

    def _sanitize_filename(self, name):
        """移除非法字符并避开 Windows 保留设备名。"""
        name = re.sub(r'[<>:"/\\|?*]', '', name).strip()
        name = re.sub(r'\s+', ' ', name)
        name = name.rstrip(' .') or 'untitled'
        stem = name.split('.', 1)[0].upper()
        if (stem in {'CON', 'PRN', 'AUX', 'NUL'}
                or re.fullmatch(r'(?:COM|LPT)[1-9]', stem)):
            name = '_' + name
        return name

    def _front_matter(self, page):
        """Typora front-matter：title（JSON 转义防冒号/引号破坏 YAML）、date、math"""
        when = page.get('raw', {}).get('version', {}).get('when', '')
        title = json.dumps(page['title'], ensure_ascii=False)
        return f"---\ntitle: {title}\ndate: {when}\nmath: true\n---\n\n"

    def _save_storage_debug(self, page):
        """把页面原始 storage 保存到 debug/export/<时间戳>/<page_id>_<标题>.html

        同一次运行的多页共用一个时间戳目录，便于按次排查转换问题。
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(self.debug_dir, timestamp)
        os.makedirs(folder, exist_ok=True)
        fname = f"{page['page_id']}_{self._sanitize_filename(page['title'])}.html"
        path = os.path.join(folder, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(page['storage'])
        return path

    def export_page(self, page_id, parent_path=None, recursive=None, _visited=None):
        """导出单页（recursive 时递归子页面），返回 md 文件路径"""
        if _visited is None:
            _visited = set()
        page_id = str(page_id)
        if page_id in _visited:
            print(f"⚠️ 跳过重复页面 ID: {page_id}")
            return None
        _visited.add(page_id)
        parent = Path(parent_path) if parent_path else self.output_dir
        page = self.fetch_page(page_id)
        self._save_storage_debug(page)
        title = self._sanitize_filename(page['title'])
        page_dir = parent / f"{page_id}_{title}"
        page_dir.mkdir(parents=True, exist_ok=True)

        md_text = self._convert_storage_to_markdown(page['storage'], page_dir, page_id)
        md_path = page_dir / f"{title}.md"
        md_path.write_text(self._front_matter(page) + md_text, encoding='utf-8')
        self.stats['pages'] += 1
        print(f"✅ {page['title']} → {md_path}")

        use_recursive = self.recursive if recursive is None else recursive
        if use_recursive:
            for cid, _ct in self.get_child_pages(page_id):
                try:
                    self.export_page(cid, str(page_dir), recursive=True,
                                     _visited=_visited)
                except Exception as exc:
                    self.failed_pages.append((str(cid), str(exc)))
                    print(f"❌ 子页面 {cid} 导出失败: {exc}")
        return md_path

    def export_space(self, space_key=None):
        """导出整个空间的全部页面（平铺，每页一个文件夹）"""
        key = space_key or self.space_key
        if not key:
            raise SystemExit("❌ 未指定空间 Key：用 --space 或在 config.py 的 "
                             "export_config.space 设置")
        pages = collect_space_pages(self.session, self.base_url, key)
        print(f"📂 空间「{key}」共 {len(pages)} 个页面")
        for pid, _t, _v in pages:
            try:
                # 空间清单已包含每一页；这里禁止再次递归，避免重复导出。
                self.export_page(pid, recursive=False)
            except Exception as e:
                print(f"❌ 页面 {pid} 导出失败: {e}")
                self.failed_pages.append((str(pid), str(e)))
        return not self.failed_pages and self.stats['failed_images'] == 0

    def _print_summary(self):
        line = (f"📊 导出结果: {self.stats['pages']} 页, 下载图片 {self.stats['images']} 张"
                + (f", 图片失败 {self.stats['failed_images']} 张（md 中已保留注释）"
                   if self.stats['failed_images'] else ""))
        print(line)
        if self.stats['skipped_macros']:
            print("ℹ️ 未处理的宏（已在 md 中保留为注释）: "
                  + ', '.join(sorted(self.stats['skipped_macros'])))
        if self.failed_pages:
            print(f"❌ 导出失败页面: {len(self.failed_pages)}")
            for page_id, reason in self.failed_pages:
                print(f"  - {page_id}: {reason}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Confluence → Markdown 导出工具')
    parser.add_argument('--page-id', default=None,
                        help='页面 ID（recursive 时含子页面）')
    parser.add_argument('--space', default=None,
                        help='空间 Key（批量导出整个空间）')
    parser.add_argument('--recursive', action='store_true', default=None,
                        help='导出子页面（默认从 config.py 的 export_config.recursive 读取）')
    parser.add_argument('--no-recursive', action='store_false', dest='recursive',
                        help='不递归，仅导出页面本身')
    parser.add_argument('--output', default=None,
                        help='输出根目录（默认从 config.py 的 export_config.output_dir 读取）')
    args = parser.parse_args()

    if not args.page_id and not args.space:
        parser.error("必须指定 --page-id 或 --space")

    print("=" * 60)
    print("📤 Confluence → Markdown 导出工具")
    print("=" * 60)

    exporter = ConfluenceExporter(space_key=args.space, recursive=args.recursive,
                                  output_dir=args.output)
    ok = True
    try:
        if args.page_id:
            exporter.export_page(args.page_id)
            ok = (not exporter.failed_pages
                  and exporter.stats['failed_images'] == 0)
        else:
            ok = exporter.export_space(args.space)
    except Exception as exc:
        print(f"❌ 导出失败: {exc}")
        ok = False
    finally:
        exporter._print_summary()
    sys.exit(0 if ok else 1)
