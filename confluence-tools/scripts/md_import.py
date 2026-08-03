"""
Markdown → Confluence 导入工具 (Confluence 9.x)

认证方式：Bearer Token (PAT)，不再支持 Basic Auth 密码直连。
数学公式：mathblock / mathinline 原生宏。

用法: python md_import.py <md_file_path> [--parent-id ID] [--page-name NAME] [--space KEY]

配置从 scripts/config.py 读取（CLI 参数可覆盖默认值）。
"""

import os
import re
import sys
import io
import html
import argparse
import datetime
import secrets
import requests
from pathlib import Path

# 修复 Windows GBK 终端 emoji 编码问题
# 幂等：已 wrap 过则跳过，避免多模块同时 import 时第一个 wrapper 被 GC 关闭底层流
if getattr(sys.stdout, 'encoding', '').lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from urllib.parse import unquote
import markdown2

from common import (SKILL_ROOT, load_config, request_with_retry,
                    collect_space_pages, build_block_template)
from debug_utils import cleanup_debug


class MarkdownImporter:
    """Markdown 导入 Confluence 的主类"""

    def __init__(self, space_key=None, math_align=None, fix_hierarchy=None):
        cfg = load_config()
        common = cfg['common_config']
        import_cfg = cfg['import_config']
        debug_cfg = cfg['debug_config']

        self.base_url = common['confluence_url'].rstrip('/')
        self.space_key = space_key or import_cfg.get('space', '')
        self.math_align = math_align if math_align is not None else import_cfg.get('math_align', 'left')
        # 默认父页面 ID / 默认页面标题：配置预设，CLI 参数（--parent-id/--page-name）覆盖
        self.default_parent_id = import_cfg.get('default_parent_id', '') or None
        self.default_page_name = import_cfg.get('default_page_name', '') or None
        # 树导入（--dir）配置：tree_import 功能开关；fix_hierarchy 命中已有页面的层级处理
        self.tree_import = bool(import_cfg.get('tree_import', False))
        self.fix_hierarchy = fix_hierarchy if fix_hierarchy is not None else import_cfg.get('fix_hierarchy', 'confirm')
        # 自动目录宏：子标题（H2~H6）数量达到 toc_min_headings 时，在正文最前插入 toc 宏
        self.toc_enabled = bool(import_cfg.get('toc_enabled', True))
        self.toc_min_headings = int(import_cfg.get('toc_min_headings', 4))
        if self.fix_hierarchy not in ('confirm', 'auto', 'off'):
            self.fix_hierarchy = 'confirm'
        # 树导入时记录"标题 → 页面 id"映射，供子节点挂载/移动解析
        self._title_id_map = {}
        self.block_template = build_block_template(self.math_align)
        self.token = common['confluence_token']
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f"Bearer {self.token}",
        })
        self.headers = {
            'Content-Type': 'application/json',
            'X-Atlassian-Token': 'no-check'
        }
        # 占位符随机后缀：防止 md 原文中的注释文本与占位符撞车
        self._token = secrets.token_hex(4)
        # 收集上传失败的图片，导入结束时汇总报告
        self.failed_images = []
        # 跳过不处理的 base64 内嵌图片（data: URI）计数
        self.data_images_skipped = 0
        # 调试目录统一放在 skill 目录下
        self.debug_dir = os.path.join(SKILL_ROOT, 'debug', 'import')
        os.makedirs(self.debug_dir, exist_ok=True)
        cleanup_debug(os.path.join(SKILL_ROOT, 'debug'),
                      int(debug_cfg.get('max_size_mb', 50)),
                      int(debug_cfg.get('keep_recent', 20)))

    def _save_debug_file(self, content, name):
        """保存调试文件到时间戳子目录"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(self.debug_dir, timestamp)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{name}.html")
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"已保存调试文件: {path}")
        return path

    def _upload_attachment(self, page_id, file_path):
        """上传附件到页面，成功返回非空字符串，失败返回 None（调用方只判断成功与否）

        页面更新场景：同名附件已存在时 POST 创建返回 400
        （"Cannot add a new attachment with same file name..."）。
        此时改为查附件 id 后 POST /child/attachment/{id}/data 更新数据
        （Server/DC 端点；Cloud 为 PUT，实测本 DC 9.2.1 用 POST 返回 200）。
        """
        filename = os.path.basename(file_path)
        url = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"

        def _post_create():
            with open(file_path, 'rb') as f:
                return request_with_retry(
                    self.session, 'POST', url,
                    headers={'X-Atlassian-Token': 'no-check'},
                    files={'file': (filename, f)}
                )

        def _post_update(attachment_id):
            with open(file_path, 'rb') as f:
                return request_with_retry(
                    self.session, 'POST', f"{url}/{attachment_id}/data",
                    headers={'X-Atlassian-Token': 'no-check'},
                    files={'file': (filename, f)}
                )

        try:
            response = _post_create()
            if response.status_code in (400, 409):
                # 同名附件已存在（更新页面场景）：查附件 id 并更新数据
                lookup = request_with_retry(
                    self.session, 'GET', url, params={'filename': filename},
                    headers=self.headers)
                lookup.raise_for_status()
                results = lookup.json().get('results', [])
                if results:
                    response = _post_update(results[0]['id'])
            response.raise_for_status()
            return f'/download/attachments/{page_id}/{filename}'
        except Exception as e:
            print(f"附件上传失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)
            return None

    def _protect_code_spans(self, md_content):
        """保护所有代码区域（围栏代码块 + 行内代码），替换为占位符"""
        code_spans = []
        count = 0

        def replace_fenced(match):
            nonlocal count
            code_spans.append(('fenced', match.group(0)))
            count += 1
            return f'<!-- CODE_FENCED_{count}_{self._token} -->'

        def replace_inline_code(match):
            nonlocal count
            code_spans.append(('inline', match.group(0)))
            count += 1
            return f'<!-- CODE_INLINE_{count}_{self._token} -->'

        patterns = [
            (r'```.*?```', replace_fenced, re.DOTALL),
            (r'``.+?``', replace_inline_code, 0),
            (r'`[^`\n]+`', replace_inline_code, 0),
        ]

        protected = md_content
        for pattern, repl, flags in patterns:
            protected = re.sub(pattern, repl, protected, flags=flags)

        return protected, code_spans

    def _convert_protected_code_to_html(self, code_spans):
        """将受保护的 Markdown 代码片段分别通过 markdown2 转换为 HTML"""
        converted = {}
        for ctype, original in code_spans:
            if ctype == 'fenced':
                html = markdown2.markdown(original, extras=["fenced-code-blocks"])
            else:
                html = markdown2.markdown(original)
            html = html.strip()
            # 剥离 markdown2 添加的外层 <p>...</p> 包裹
            html = re.sub(r'^<p>(.*)</p>\s*$', r'\1', html, flags=re.DOTALL)
            converted[original] = html
        return converted

    def _restore_code_spans(self, html_content, code_spans, converted_code_html):
        """将 HTML 中的代码占位符还原为 markdown2 转换后的 HTML 代码标签"""
        restored = html_content
        for i, (ctype, original) in enumerate(code_spans):
            if ctype == 'fenced':
                placeholder = f'<!-- CODE_FENCED_{i+1}_{self._token} -->'
            else:
                placeholder = f'<!-- CODE_INLINE_{i+1}_{self._token} -->'
            html = converted_code_html.get(original, '')
            restored = restored.replace(placeholder, html)
        return restored

    def _protect_math_blocks(self, md_content):
        """用 HTML 占位符替换数学公式，防止被 markdown2 当作文本误处理"""
        math_blocks = []
        count = 0

        def replace_math_block(match):
            nonlocal count
            math_blocks.append(('math', match.group(0)))
            count += 1
            return f'<!-- MATH_BLOCK_{count}_{self._token} -->'

        def replace_inline_math(match):
            nonlocal count
            math_blocks.append(('inline_math', match.group(0)))
            count += 1
            return f'<!-- MATH_INLINE_{count}_{self._token} -->'

        def replace_latex_block(match):
            nonlocal count
            math_blocks.append(('latex', match.group(0)))
            count += 1
            return f'<!-- LATEX_BLOCK_{count}_{self._token} -->'

        patterns = [
            (r'```latex.*?```', replace_latex_block, re.DOTALL),
            (r'\$\$.*?\$\$', replace_math_block, re.DOTALL),
            # 行内公式规则：开头 $ 后禁空白、闭合 $ 前禁空白（防 $PWD / $OLDPWD 误配）、
            # 内容禁嵌套 $ 与换行；允许 < >（LaTeX 不等式，如 $0<x<\pi$）
            (r'(?<!\$)\$(?![\s$])[^$\n]+?(?<![$\s])\$(?!\$)', replace_inline_math, 0)
        ]

        protected_content = md_content
        for pattern, repl, flags in patterns:
            protected_content = re.sub(pattern, repl, protected_content, flags=flags)

        return protected_content, math_blocks

    def _restore_math_blocks(self, html_content, math_blocks):
        """恢复被保护的数学公式块"""
        restored_content = html_content

        for i, (math_type, original_math) in enumerate(math_blocks):
            if math_type == 'math':
                placeholder = f'<!-- MATH_BLOCK_{i+1}_{self._token} -->'
            elif math_type == 'inline_math':
                placeholder = f'<!-- MATH_INLINE_{i+1}_{self._token} -->'
            elif math_type == 'latex':
                placeholder = f'<!-- LATEX_BLOCK_{i+1}_{self._token} -->'
            else:
                continue

            restored_content = restored_content.replace(placeholder, original_math)

        return restored_content

    def _convert_math_blocks(self, html_content):
        """转换数学公式为 Confluence 原生宏"""

        def _clean_latex(s):
            # \* 是未定义控制序列（MathJax 报错），归一化为 *（TeX 数学模式星号合法）
            return s.replace(r'\*', '*')

        def _escape_minimal_for_latex(s):
            return _clean_latex(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 安全网：保护 HTML <code> 和 <pre> 标签内的内容
        protected_parts = re.split(
            r'(<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>|<ac:structured-macro\b[^>]*/>|<ac:structured-macro\b.*?</ac:structured-macro>)',
            html_content, flags=re.DOTALL
        )

        def convert_math_in_text(text):
            # $$...$$ 块级公式 → mathblock 宏（对齐方式由 block_template 决定）
            block_pattern = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)
            text = block_pattern.sub(
                lambda m: self.block_template.format(content=_clean_latex(m.group(1).strip())),
                text
            )

            # ```latex``` 代码块 → mathblock 宏（对齐方式由 block_template 决定）
            latex_pattern = re.compile(r'```latex(.*?)```', re.DOTALL)
            text = latex_pattern.sub(
                lambda m: self.block_template.format(content=_clean_latex(m.group(1).strip())),
                text
            )

            # $...$ 行内公式 → mathinline 宏
            # 开头 $ 后禁空白、闭合 $ 前禁空白（防 $PWD / $OLDPWD 误配）、
            # 内容禁嵌套 $ 与换行；允许 < >（LaTeX 不等式）
            inline_pattern = re.compile(r'(?<!\$)\$(?![\s$])([^$\n]+?)(?<![$\s])\$(?!\$)')
            text = inline_pattern.sub(
                lambda m: (
                    '<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
                    f'<ac:parameter ac:name="body">{_escape_minimal_for_latex(m.group(1).strip())}</ac:parameter>'
                    '</ac:structured-macro>'
                ),
                text
            )

            return text

        result_parts = []
        for i, part in enumerate(protected_parts):
            if i % 2 == 1 or part.startswith('<code') or part.startswith('<pre') or part.startswith('<ac:'):
                result_parts.append(part)
            else:
                result_parts.append(convert_math_in_text(part))

        return ''.join(result_parts)

    def _convert_code_blocks(self, html_content):
        """将 Markdown 围栏代码块转换为 Confluence code 宏"""
        language_map = {
            'c': 'cpp', 'c++': 'cpp', 'cpp': 'cpp',
            'c#': 'csharp', 'csharp': 'csharp',
            'python': 'python', 'py': 'python',
            'java': 'java', 'javascript': 'javascript', 'js': 'javascript',
            'html': 'html', 'css': 'css', 'sql': 'sql',
            'bash': 'bash', 'shell': 'bash', 'sh': 'bash',
            'json': 'json', 'xml': 'xml', 'ruby': 'ruby',
            'rb': 'ruby', 'php': 'php', 'go': 'go',
            'rust': 'rust', 'rs': 'rust'
        }

        pattern = re.compile(
            r'(?:<div class="codehilite">\s*)?'
            r'<pre>(?:<span[^>]*></span>)?<code(?: class="language-(.*?)")?>(.*?)</code></pre>'
            r'\s*(?:</div>)?',
            re.DOTALL
        )

        def replace_code(match):
            lang = match.group(1)
            code_content = html.unescape(match.group(2))
            confluence_lang = language_map.get(lang.lower(), 'none') if lang else 'none'
            code_content = code_content.replace('\\', '&#92;').replace(']]>', ']]]]><![CDATA[>')
            return (
                f'<ac:structured-macro ac:name="code">'
                f'<ac:parameter ac:name="language">{confluence_lang}</ac:parameter>'
                f'<ac:parameter ac:name="theme">Confluence</ac:parameter>'
                f'<ac:parameter ac:name="linenumbers">false</ac:parameter>'
                f'<ac:plain-text-body><![CDATA[{code_content}]]></ac:plain-text-body>'
                f'</ac:structured-macro>'
            )

        return pattern.sub(replace_code, html_content)

    def _convert_highlight_marks(self, html_content):
        """将==highlight==语法转换为加粗"""
        parts = re.split(r'(<ac:structured-macro\b[^>]*/>|<ac:structured-macro\b.*?</ac:structured-macro>)',
                         html_content, flags=re.DOTALL)
        converted_parts = []
        for part in parts:
            if part.startswith('<ac:structured-macro'):
                converted_parts.append(part)
            else:
                # ==高亮== 不跨行，防未闭合 == 吞掉后续内容
                pattern = re.compile(r'==([^\n]*?)==')
                part = pattern.sub(lambda m: f"<strong>{m.group(1).strip()}</strong>", part)
                converted_parts.append(part)
        return ''.join(converted_parts)

    def _convert_md_links(self, html_content, md_file_path, page_id):
        """将 Markdown 图片转换为 Confluence 附件引用"""
        md_dir = os.path.dirname(md_file_path)
        pattern = re.compile(r'(!\[(.*?)\]\((.*?)\))|(<img\s+.*?src=["\'](.*?)["\'].*?>)', re.IGNORECASE)
        # 保护宏 / 代码区域：mathblock 宏的 <![CDATA[ 前缀含字面 ![，LaTeX ]( 会被图片正则误判
        # 为图片链接（历史 bug：CDATA 内 \right](0) 把 0 当图片路径）。只对非保护部分做转换。
        protected_parts = re.split(
            r'(<ac:structured-macro\b[^>]*/>|<ac:structured-macro\b.*?</ac:structured-macro>|<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>)',
            html_content, flags=re.DOTALL
        )

        def replace_image(match):
            if match.group(3):
                alt_text = match.group(2) or "Image"
                img_path = match.group(3)
            elif match.group(5):
                img_path = match.group(5)
                alt_text = "Image"
            else:
                return match.group(0)

            size_params = ""
            size_match = re.search(r'{([^}]*)}', img_path)
            if size_match:
                params = size_match.group(1)
                img_path = img_path.split('{')[0]
                for param in params.split():
                    if '=' in param:
                        key, value = param.split('=')
                        size_params += f' ac:{key}="{value}"'

            if not img_path.startswith(('http', '//')):
                # data: URI（base64 内嵌图片）：不做本地文件处理，保留原始引用
                if img_path.startswith('data:'):
                    self.data_images_skipped += 1
                    return match.group(0)
                abs_path = os.path.normpath(os.path.join(md_dir, unquote(img_path)))
                if os.path.exists(abs_path):
                    attachment_url = self._upload_attachment(page_id, abs_path)
                    if attachment_url:
                        filename = os.path.basename(abs_path)
                        return f'<ac:image ac:alt="{alt_text}"{size_params}><ri:attachment ri:filename="{filename}" /></ac:image>'
                    # 上传失败：记录并在导入结束时汇总报告
                    self.failed_images.append(img_path)
                else:
                    self.failed_images.append(f"{img_path}（本地文件不存在: {abs_path}）")
            return match.group(0)

        result_parts = []
        for i, part in enumerate(protected_parts):
            if i % 2 == 1:
                result_parts.append(part)  # 宏 / 代码原样保留
            else:
                result_parts.append(pattern.sub(replace_image, part))
        return ''.join(result_parts)

    def _clean_unnecessary_backslashes(self, html_content):
        """清理 markdown2 在 HTML 转换过程中产生的多余反斜杠转义"""
        parts = re.split(r'(<ac:structured-macro\b[^>]*/>|<ac:structured-macro\b.*?</ac:structured-macro>)', html_content, flags=re.DOTALL)
        cleaned_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                cleaned_parts.append(part)
                continue
            part = re.sub(r'\\([<>#])', r'\1', part)
            part = re.sub(r'\\(&[a-z]+;)', r'\1', part)
            part = re.sub(r'\\([\\`*_{}\[\]()#+\-.!])', r'\1', part)
            part = re.sub(r'&(?!(#\d+|[a-z]+;))', '&amp;', part)
            cleaned_parts.append(part)
        return ''.join(cleaned_parts)

    def _find_page_by_title(self, title):
        """根据标题在空间中查找已有页面，返回 (page_id, version_number) 或 (None, None)

        用内存匹配而非 CQL/标题端点：Confluence 的 title 查询在 Cloud/Server
        上大小写行为相反（已知 bug），且含特殊字符的标题会导致 CQL 失败。
        先精确匹配，再大小写不敏感匹配，多个候选时提示并选第一个。
        """
        try:
            pages = collect_space_pages(self.session, self.base_url, self.space_key, headers=self.headers)
        except Exception as e:
            print(f"查找页面失败: {e}")
            return None, None
        if not pages:
            return None, None

        candidates = [p for p in pages if p[1] == title]
        if not candidates:
            candidates = [p for p in pages if p[1].lower() == title.lower()]
        if not candidates:
            return None, None

        if len(candidates) > 1:
            print("⚠️ 发现多个同名页面，将更新第一个（其余请用 --parent-id 精确定位）:")
            for pid, ptitle, _v in candidates:
                print(f"  - 「{ptitle}」(ID: {pid})")
        return candidates[0][0], candidates[0][2]

    def _create_page(self, title, content, parent_id=None):
        """通过 Confluence REST API 创建新页面，返回 (page_id, version=1) 或 (None, None)"""
        self._save_debug_file(content, "before_upload")
        url = f"{self.base_url}/rest/api/content"
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {"storage": {"value": content, "representation": "storage"}}
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        try:
            response = request_with_retry(self.session, 'POST', url, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()['id'], 1
        except Exception as e:
            print(f"页面创建失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)
            return None, None

    def _fetch_latest_version(self, page_id):
        """拉取页面当前最新版本号，供 409 版本冲突时重试"""
        url = f"{self.base_url}/rest/api/content/{page_id}"
        try:
            response = request_with_retry(self.session, 'GET', url,
                                          params={'expand': 'version'}, headers=self.headers,
                                          retry_on=(429, 500, 502, 503, 504))
            response.raise_for_status()
            return response.json()['version']['number']
        except Exception:
            return None

    def _update_page(self, page_id, title, content, version_number, ancestors=None):
        """通过 Confluence REST API 更新已有页面，返回 (page_id, new_version) 或 (None, None)

        版本冲突 (409，页面被他人修改) 时自动拉取最新版本重试一次。

        ancestors: 可选，目标父页面 ID 或列表。传值则更新时设置页面层级（移动页面）：
                   None = 不设置（保持当前位置，单文件模式默认）；[] = 移到空间根；
                   int/str = 移到指定父页面下。
        """
        self._save_debug_file(content, "before_upload")
        url = f"{self.base_url}/rest/api/content/{page_id}"
        payload = {
            "version": {"number": version_number + 1},
            "type": "page",
            "title": title,
            "body": {"storage": {"value": content, "representation": "storage"}}
        }
        if ancestors is not None:
            if isinstance(ancestors, (list, tuple)):
                payload["ancestors"] = [{"id": a} for a in ancestors]
            else:
                payload["ancestors"] = [{"id": ancestors}]
        try:
            response = request_with_retry(self.session, 'PUT', url, json=payload, headers=self.headers)
            if response.status_code == 409:
                latest = self._fetch_latest_version(page_id)
                if latest is not None:
                    print(f"⚠️ 版本冲突（v{version_number + 1}），拉取最新 v{latest} 重试...")
                    payload["version"]["number"] = latest + 1
                    response = request_with_retry(self.session, 'PUT', url,
                                                  json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()['id'], payload["version"]["number"]
        except Exception as e:
            print(f"页面更新失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)
            return None, None

    def _convert_md_to_storage(self, md_content):
        """Markdown → Confluence storage HTML（保护→转换→还原→宏转换→清理）"""
        # 0. 保护代码区域
        protected_md, code_spans = self._protect_code_spans(md_content)

        # 1. 保护数学公式
        protected_md, math_blocks = self._protect_math_blocks(protected_md)

        # 2. 转换为HTML
        html_content = markdown2.markdown(protected_md, extras=["tables", "fenced-code-blocks", "cuddled-lists"])

        # 2.5 恢复受保护的代码片段
        if code_spans:
            converted_code = self._convert_protected_code_to_html(code_spans)
            html_content = self._restore_code_spans(html_content, code_spans, converted_code)

        # 3. 恢复数学公式
        html_content = self._restore_math_blocks(html_content, math_blocks)

        # 4. 转换数学公式
        html_content = self._convert_math_blocks(html_content)

        # 5. 其他转换
        html_content = self._convert_code_blocks(html_content)
        html_content = self._convert_highlight_marks(html_content)
        html_content = self._clean_unnecessary_backslashes(html_content)
        # 5.5 清理 markdown2 在块级元素外层包裹的 <p> 标签
        # 用 (?:(?!<p).)*? 替代 .*?：防止跨段匹配吞掉段落间的 <p>/</p>，导致 XHTML 畸形
        html_content = re.sub(
            r'<p>\s*(<(?:div|pre|ac:structured-macro)[^>]*>(?:(?!<p).)*?</(?:div|pre|ac:structured-macro)>)\s*</p>',
            r'\1', html_content, flags=re.DOTALL
        )

        # 5.6 子标题数达到阈值时，在正文最前插入 Confluence 目录宏（toc）
        html_content = self._maybe_add_toc(html_content)
        return html_content

    def _maybe_add_toc(self, html_content):
        """子标题（H2~H6）数量达到阈值时，在正文最前插入 Confluence 目录宏（toc）。

        H1 一般是页面标题本身（与 Confluence 页面标题重复），不计入子标题。
        统计 markdown2 转换后的真实标题标签（代码块内文本已被 HTML 转义，不会误计）。
        """
        if not self.toc_enabled:
            return html_content
        heading_count = len(re.findall(r'<h([2-6])(?=[\s>])', html_content))
        if heading_count < self.toc_min_headings:
            return html_content
        toc_macro = ('<ac:structured-macro ac:name="toc" ac:schema-version="1" '
                     'data-layout="default"/>')
        print(f"ℹ️ 检测到 {heading_count} 个子标题（阈值 {self.toc_min_headings}），已自动插入目录宏")
        return toc_macro + html_content

    def import_markdown(self, md_file_path, parent_id=None, page_name=None):
        """Markdown 导入主函数"""
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        # 优先级：CLI --page-name > 配置 default_page_name > md 文件名（不含扩展名）
        title = page_name or self.default_page_name or Path(md_file_path).stem
        # 优先级：CLI --parent-id > 配置 default_parent_id（仅新建页面时生效）
        parent_id = parent_id or self.default_parent_id

        html_content = self._convert_md_to_storage(md_content)

        # 6. 创建或更新页面
        existing_id, existing_version = self._find_page_by_title(title)
        if existing_id:
            print(f"页面已存在 (ID: {existing_id}, v{existing_version})，执行更新...")
            page_id, current_version = self._update_page(
                existing_id, title, html_content, existing_version)
        else:
            page_id, current_version = self._create_page(title, html_content, parent_id)
        if not page_id:
            return False

        # 7. 处理图片链接（需 page_id 上传附件），在最新版本号上再 +1
        final_content = self._convert_md_links(html_content, md_file_path, page_id)
        if final_content != html_content:
            self._update_page(page_id, title, final_content, current_version)

        if self.failed_images:
            print("⚠️ 以下图片未能上传，已在页面中保留原始引用：")
            for img in self.failed_images:
                print(f"  - {img}")

        if self.data_images_skipped:
            print(f"ℹ️ 跳过 {self.data_images_skipped} 张 base64 内嵌图片（data: URI），已保留原始引用")

        print(f"✅ 导入完成: {md_file_path} → {title} (ID: {page_id})")
        return page_id

    # ==================== --dir 树导入 ====================

    def _get_page_parent(self, page_id):
        """查询页面当前父页面，返回 (parent_id, parent_title)；无父级返回 (None, None)"""
        url = f"{self.base_url}/rest/api/content/{page_id}"
        try:
            response = request_with_retry(self.session, 'GET', url,
                                          params={'expand': 'ancestors'}, headers=self.headers,
                                          retry_on=(429, 500, 502, 503, 504))
            response.raise_for_status()
            ancestors = response.json().get('ancestors', [])
            if not ancestors:
                return None, None
            p = ancestors[-1]
            return p.get('id'), p.get('title')
        except Exception:
            return None, None

    def _scan_tree(self, root_dir):
        """扫描目录树为页面节点树（--dir 模式）

        规则：每个含 .md 的文件夹 = 一个页面节点（标题=文件夹名，内容=同名 .md；
        无同名取唯一 .md；多个 .md 时跳过该节点并提示）。`.assets/` 目录不算节点。
        中间文件夹无 .md 时跳级（其子节点直接并入上层，页面层级由实际含 md 的文件夹决定）。
        """
        root = Path(root_dir)
        if not root.is_dir():
            raise SystemExit(f"❌ 目录不存在: {root_dir}")

        def scan(path):
            mds = sorted(p for p in path.iterdir()
                         if p.is_file() and p.suffix.lower() == '.md')
            md_path = None
            has_md_but_ambiguous = False
            if mds:
                same = [m for m in mds if m.stem == path.name]
                if len(same) == 1:
                    md_path = same[0]
                elif len(mds) == 1:
                    md_path = mds[0]
                else:
                    print(f"⚠️ 跳过 {path.name}：含多个 .md（{'、'.join(m.name for m in mds)}），无法确定页面内容")
                    has_md_but_ambiguous = True
            children = []
            for child in sorted(path.iterdir()):
                if child.is_dir() and not child.name.endswith('.assets'):
                    sub = scan(child)
                    if sub is not None:
                        children.append(sub)
            if md_path is None and not children and not has_md_but_ambiguous:
                return None
            return {'name': path.name, 'md_path': md_path, 'children': children}

        tree = scan(root)
        if tree is None:
            raise SystemExit(f"❌ {root_dir} 下没有任何含 .md 的文件夹")
        return tree

    def _build_plan(self, node, parent_title=None, depth=0):
        """只读生成导入计划（查重 + 当前父级判定），不执行任何写操作

        返回节点：{title, md_path, status, parent_title, depth, children}
        status: 'skip'（跳级节点）/ 'new' / 'update' / 'move'
        """
        if node['md_path'] is None:
            return {'title': node['name'], 'md_path': None, 'status': 'skip',
                    'parent_title': parent_title, 'depth': depth,
                    'children': [self._build_plan(c, parent_title, depth) for c in node['children']]}
        title = node['name']
        existing_id, _v = self._find_page_by_title(title)
        status = 'new'
        if existing_id:
            _cur_pid, cur_ptitle = self._get_page_parent(existing_id)
            if self.fix_hierarchy != 'off' and cur_ptitle != parent_title:
                status = 'move'
            else:
                status = 'update'
        return {'title': title, 'md_path': node['md_path'], 'status': status,
                'parent_title': parent_title, 'depth': depth,
                'children': [self._build_plan(c, title, depth + 1) for c in node['children']]}

    def _print_plan(self, plan):
        mark = {'new': '🆕 新建', 'update': '🔄 更新', 'move': '📦 移动'}.get(plan['status'], '')
        prefix = '  ' * plan['depth']
        if plan['status'] != 'skip':
            extra = ''
            if plan['status'] in ('new', 'move'):
                extra = f"（目标父级: {plan['parent_title'] or '根'}）"
            print(f"{prefix}{mark} {plan['title']}{extra}")
        for c in plan['children']:
            self._print_plan(c)

    def _plan_has_move(self, plan):
        if plan['status'] == 'move':
            return True
        return any(self._plan_has_move(c) for c in plan['children'])

    def _execute_plan(self, plan, parent_id=None):
        """按计划执行导入，返回结果节点。维护 _title_id_map（标题→id）供子节点挂载/移动解析。"""
        if plan['status'] == 'skip':
            children = [self._execute_plan(c, parent_id) for c in plan['children']]
            return {'title': plan['title'], 'status': 'skip', 'page_id': None, 'children': children}

        title = plan['title']
        with open(plan['md_path'], 'r', encoding='utf-8') as f:
            md_content = f.read()
        html_content = self._convert_md_to_storage(md_content)

        existing_id, existing_version = self._find_page_by_title(title)
        status = plan['status']
        page_id = None
        if existing_id:
            if status == 'move':
                # 期望父级：plan 里是标题，从 _title_id_map 解析为 id（父级应先处理完）
                target = self._title_id_map.get(plan['parent_title']) if plan['parent_title'] else []
                page_id, current_version = self._update_page(
                    existing_id, title, html_content, existing_version, ancestors=target)
            else:
                page_id, current_version = self._update_page(
                    existing_id, title, html_content, existing_version)
        else:
            page_id, current_version = self._create_page(title, html_content, parent_id)

        if not page_id:
            print(f"❌ 失败: {title}")
            for c in plan['children']:
                print(f"⏭️ 跳过 {c['title']}（父级失败）")
            return {'title': title, 'status': 'failed', 'page_id': None, 'children': []}

        self._title_id_map[title] = page_id

        # 图片处理（与单文件流程一致），在最新版本号上再 +1
        final_content = self._convert_md_links(html_content, plan['md_path'], page_id)
        if final_content != html_content:
            self._update_page(page_id, title, final_content, current_version)
        if self.failed_images:
            print(f"⚠️ {title} 以下图片未能上传：{self.failed_images}")
            self.failed_images = []
        if self.data_images_skipped:
            print(f"ℹ️ {title} 跳过 {self.data_images_skipped} 张 base64 内嵌图片")
            self.data_images_skipped = 0

        children = [self._execute_plan(c, page_id) for c in plan['children']]
        return {'title': title, 'status': status, 'page_id': page_id, 'children': children}

    def _print_results(self, res, prefix=''):
        mark = {'new': '🆕 新建', 'update': '🔄 更新', 'move': '📦 移动',
                'failed': '❌ 失败'}.get(res['status'], '')
        if res['status'] != 'skip':
            print(f"{prefix}{mark} {res['title']} (ID: {res['page_id']})")
        for c in res['children']:
            self._print_results(c, prefix + '  ')

    def import_tree(self, root_dir, plan_only=False, yes=False):
        """批量导入文件夹树（--dir 模式），保留层级关系

        plan_only: 仅输出计划（只读查重），不执行任何写操作
        yes: 跳过移动确认（配合 --plan-only 预览后二次执行）
        """
        if not self.tree_import:
            raise SystemExit(
                "❌ --dir 树导入未启用：请在 config.py 的 import_config.tree_import 设为 True")
        tree = self._scan_tree(root_dir)

        print("\n📋 导入计划：")
        plan = self._build_plan(tree)
        self._print_plan(plan)
        if plan_only:
            print("\n（仅计划，未执行任何操作）")
            return

        if self._plan_has_move(plan) and self.fix_hierarchy == 'confirm' and not yes:
            ans = input("⚠️ 检测到需移动层级的页面，确认执行？[y/N] ").strip().lower()
            if ans != 'y':
                print("已取消，未执行任何操作。")
                return

        print("\n🚀 开始导入...")
        results = self._execute_plan(plan)
        print("\n📄 导入结果：")
        self._print_results(results)
        print("✅ 树导入完成。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Markdown → Confluence 导入工具')
    parser.add_argument('md_file', nargs='?', help='Markdown 文件路径（与 --dir 二选一）')
    parser.add_argument('--dir', default=None,
                        help='批量导入文件夹树（保留层级；需 config.py 的 import_config.tree_import 开启）')
    parser.add_argument('--plan-only', action='store_true',
                        help='仅输出导入计划（新建/更新/移动，只读查重），不执行')
    parser.add_argument('--yes', action='store_true',
                        help='跳过移动确认（配合 --plan-only 预览后二次执行时使用）')
    parser.add_argument('--fix-hierarchy', default=None, choices=['confirm', 'auto', 'off'],
                        help='树导入命中已有页面的层级处理：confirm 预览确认 / auto 直接移动 / off 不移动（默认从 config.py 读取）')
    parser.add_argument('--parent-id', default=None,
                        help='父页面 ID（导入为它的子页面；默认从 config.py 的 import_config.default_parent_id 读取，留空不挂父级）')
    parser.add_argument('--page-name', default=None,
                        help='自定义页面标题（默认从 config.py 的 import_config.default_page_name 读取，为空取 md 文件名）')
    parser.add_argument('--space', default=None,
                        help='空间 Key（默认从 config.py 的 import_config.space 读取）')
    parser.add_argument('--align', default=None, choices=['left', 'center'],
                        help='公式对齐方式：left 左对齐 / center 居中（默认从 config.py 读取）')
    args = parser.parse_args()

    print("=" * 60)
    print("📘 Markdown → Confluence 导入工具")
    print("=" * 60)

    if args.dir:
        importer = MarkdownImporter(space_key=args.space, math_align=args.align,
                                    fix_hierarchy=args.fix_hierarchy)
        importer.import_tree(args.dir, plan_only=args.plan_only, yes=args.yes)
    else:
        if not args.md_file:
            parser.error("必须指定 md 文件路径，或使用 --dir 批量导入文件夹树")
        importer = MarkdownImporter(space_key=args.space, math_align=args.align)
        result = importer.import_markdown(
            args.md_file,
            parent_id=args.parent_id,
            page_name=args.page_name
        )
        print("🎉 导入成功!" if result else "❌ 导入失败，请检查调试文件。")
