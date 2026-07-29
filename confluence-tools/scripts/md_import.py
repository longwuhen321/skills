"""
Markdown → Confluence 导入工具 (Confluence 9.x)

认证方式：Bearer Token (PAT)，不再支持 Basic Auth 密码直连。
数学公式：mathblock / mathinline 原生宏。

用法: python md_import.py <md_file_path> [--parent-id ID] [--page-name NAME] [--space KEY]

配置通过环境变量注入（由 Claude skill 写入 settings.local.json）：
  CONFLUENCE_URL    - Confluence 基础 URL
  CONFLUENCE_TOKEN  - Personal Access Token
  CONFLUENCE_SPACE  - 默认空间 Key（可用 --space 覆盖）
  CONFLUENCE_DEBUG_MAX_MB  - 调试日志阈值，默认 50
  CONFLUENCE_DEBUG_KEEP    - 调试日志保留数，默认 20
"""

import os
import re
import sys
import io
import argparse
import requests
from pathlib import Path

# 修复 Windows GBK 终端 emoji 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from urllib.parse import unquote
import markdown2
import html
import datetime

# ── 路径推导 ──
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_ROOT, 'scripts'))
from debug_utils import cleanup_debug


def _get_config():
    """从环境变量读取配置，缺失必填项则报错退出"""
    url = os.environ.get('CONFLUENCE_URL', '')
    token = os.environ.get('CONFLUENCE_TOKEN', '')
    if not url or not token:
        print("❌ 缺少配置: CONFLUENCE_URL 和 CONFLUENCE_TOKEN 必须设置")
        print("   请先运行 /confluence-tools 完成首次配置")
        sys.exit(1)
    return {
        'url': url.rstrip('/'),
        'token': token,
        'space': os.environ.get('CONFLUENCE_SPACE', ''),
        'debug_max_mb': int(os.environ.get('CONFLUENCE_DEBUG_MAX_MB', '50')),
        'debug_keep': int(os.environ.get('CONFLUENCE_DEBUG_KEEP', '20')),
    }


class MarkdownImporter:
    """Markdown 导入 Confluence 的主类"""

    def __init__(self, space_key=None):
        cfg = _get_config()
        self.base_url = cfg['url']
        self.space_key = space_key or cfg['space']
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f"Bearer {cfg['token']}",
        })
        self.headers = {
            'Content-Type': 'application/json',
            'X-Atlassian-Token': 'no-check'
        }
        # 调试目录统一放在 skill 目录下
        self.debug_dir = os.path.join(SKILL_ROOT, 'debug', 'import')
        os.makedirs(self.debug_dir, exist_ok=True)
        cleanup_debug(os.path.join(SKILL_ROOT, 'debug'),
                      cfg['debug_max_mb'],
                      cfg['debug_keep'])

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
        """上传附件并返回下载链接"""
        filename = os.path.basename(file_path)
        url = f"{self.base_url}/rest/api/content/{page_id}/child/attachment"

        try:
            with open(file_path, 'rb') as f:
                response = self.session.post(
                    url,
                    headers={'X-Atlassian-Token': 'no-check'},
                    files={'file': (filename, f)}
                )
            response.raise_for_status()
            return f'/download/attachments/{page_id}/{filename}'
        except Exception as e:
            print(f"附件上传失败: {e}")
            return None

    def _protect_code_spans(self, md_content):
        """保护所有代码区域（围栏代码块 + 行内代码），替换为占位符"""
        code_spans = []
        count = 0

        def replace_fenced(match):
            nonlocal count
            code_spans.append(('fenced', match.group(0)))
            count += 1
            return f'<!-- CODE_FENCED_{count} -->'

        def replace_inline_code(match):
            nonlocal count
            code_spans.append(('inline', match.group(0)))
            count += 1
            return f'<!-- CODE_INLINE_{count} -->'

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
                placeholder = f'<!-- CODE_FENCED_{i+1} -->'
            else:
                placeholder = f'<!-- CODE_INLINE_{i+1} -->'
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
            return f'<!-- MATH_BLOCK_{count} -->'

        def replace_inline_math(match):
            nonlocal count
            math_blocks.append(('inline_math', match.group(0)))
            count += 1
            return f'<!-- MATH_INLINE_{count} -->'

        def replace_latex_block(match):
            nonlocal count
            math_blocks.append(('latex', match.group(0)))
            count += 1
            return f'<!-- LATEX_BLOCK_{count} -->'

        patterns = [
            (r'```latex.*?```', replace_latex_block, re.DOTALL),
            (r'\$\$.*?\$\$', replace_math_block, re.DOTALL),
            (r'(?<!\$)\$(?!\$)[^$]*?(?<!\$)\$(?!\$)', replace_inline_math, re.DOTALL)
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
                placeholder = f'<!-- MATH_BLOCK_{i+1} -->'
            elif math_type == 'inline_math':
                placeholder = f'<!-- MATH_INLINE_{i+1} -->'
            elif math_type == 'latex':
                placeholder = f'<!-- LATEX_BLOCK_{i+1} -->'
            else:
                continue

            restored_content = restored_content.replace(placeholder, original_math)

        return restored_content

    def _convert_math_blocks(self, html_content):
        """转换数学公式为 Confluence 原生宏"""

        def _escape_minimal_for_latex(s):
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        # 安全网：保护 HTML <code> 和 <pre> 标签内的内容
        protected_parts = re.split(
            r'(<code[^>]*>.*?</code>|<pre[^>]*>.*?</pre>|<ac:structured-macro\b.*?</ac:structured-macro>)',
            html_content, flags=re.DOTALL
        )

        def convert_math_in_text(text):
            # $$...$$ 块级公式 → mathblock 宏
            block_pattern = re.compile(r'\$\$(.*?)\$\$', re.DOTALL)
            text = block_pattern.sub(
                lambda m: (
                    '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                    f'<ac:plain-text-body><![CDATA[{m.group(1).strip()}]]></ac:plain-text-body>'
                    '</ac:structured-macro>'
                ),
                text
            )

            # ```latex``` 代码块 → mathblock 宏
            latex_pattern = re.compile(r'```latex(.*?)```', re.DOTALL)
            text = latex_pattern.sub(
                lambda m: (
                    '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                    f'<ac:plain-text-body><![CDATA[{m.group(1).strip()}]]></ac:plain-text-body>'
                    '</ac:structured-macro>'
                ),
                text
            )

            # $...$ 行内公式 → mathinline 宏
            inline_pattern = re.compile(r'(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)', re.DOTALL)
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
        parts = re.split(r'(<ac:structured-macro.*?</ac:structured-macro>)',
                         html_content, flags=re.DOTALL)
        converted_parts = []
        for part in parts:
            if part.startswith('<ac:structured-macro'):
                converted_parts.append(part)
            else:
                pattern = re.compile(r'==(.*?)==', re.DOTALL)
                part = pattern.sub(lambda m: f"<strong>{m.group(1).strip()}</strong>", part)
                converted_parts.append(part)
        return ''.join(converted_parts)

    def _convert_md_links(self, html_content, md_file_path, page_id):
        """将 Markdown 图片转换为 Confluence 附件引用"""
        md_dir = os.path.dirname(md_file_path)
        pattern = re.compile(r'(!\[(.*?)\]\((.*?)\))|(<img\s+.*?src=["\'](.*?)["\'].*?>)', re.IGNORECASE)

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
                abs_path = os.path.normpath(os.path.join(md_dir, unquote(img_path)))
                if os.path.exists(abs_path):
                    attachment_url = self._upload_attachment(page_id, abs_path)
                    if attachment_url:
                        filename = os.path.basename(img_path)
                        return f'<ac:image ac:alt="{alt_text}"{size_params}><ri:attachment ri:filename="{filename}" /></ac:image>'
            return match.group(0)

        return pattern.sub(replace_image, html_content)

    def _clean_unnecessary_backslashes(self, html_content):
        """清理 markdown2 在 HTML 转换过程中产生的多余反斜杠转义"""
        parts = re.split(r'(<ac:structured-macro.*?</ac:structured-macro>)', html_content, flags=re.DOTALL)
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
        """根据标题在空间中查找已有页面，返回 (page_id, version_number) 或 (None, None)"""
        url = f"{self.base_url}/rest/api/content"
        params = {
            'title': title,
            'spaceKey': self.space_key,
            'expand': 'version'
        }
        try:
            response = self.session.get(url, params=params, headers=self.headers)
            response.raise_for_status()
            results = response.json().get('results', [])
            if results:
                page = results[0]
                return page['id'], page['version']['number']
        except Exception as e:
            print(f"查找页面失败: {e}")
        return None, None

    def _create_page(self, title, content, parent_id=None):
        """通过 Confluence REST API 创建新页面"""
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
            response = self.session.post(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()['id']
        except Exception as e:
            print(f"页面创建失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)
            return None

    def _update_page(self, page_id, title, content, version_number):
        """通过 Confluence REST API 更新已有页面"""
        self._save_debug_file(content, "before_upload")
        url = f"{self.base_url}/rest/api/content/{page_id}"
        payload = {
            "version": {"number": version_number + 1},
            "type": "page",
            "title": title,
            "body": {"storage": {"value": content, "representation": "storage"}}
        }
        try:
            response = self.session.put(url, json=payload, headers=self.headers)
            response.raise_for_status()
            return response.json()['id']
        except Exception as e:
            print(f"页面更新失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(e.response.text)
            return None

    def import_markdown(self, md_file_path, parent_id=None, page_name=None):
        """Markdown 导入主函数"""
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        title = page_name if page_name else Path(md_file_path).stem

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
        html_content = re.sub(
            r'<p>\s*(<(?:div|pre|ac:structured-macro)[^>]*>.*?</(?:div|pre|ac:structured-macro)>)\s*</p>',
            r'\1', html_content, flags=re.DOTALL
        )

        # 6. 创建或更新页面
        existing_id, existing_version = self._find_page_by_title(title)
        if existing_id:
            print(f"页面已存在 (ID: {existing_id}, v{existing_version})，执行更新...")
            page_id = self._update_page(existing_id, title, html_content, existing_version)
        else:
            page_id = self._create_page(title, html_content, parent_id)
        if not page_id:
            return False

        # 7. 处理图片链接
        final_content = self._convert_md_links(html_content, md_file_path, page_id)
        if final_content != html_content:
            update_url = f"{self.base_url}/rest/api/content/{page_id}"
            payload = {
                "version": {"number": 2},
                "title": title,
                "type": "page",
                "body": {"storage": {"value": final_content, "representation": "storage"}}
            }
            self.session.put(update_url, json=payload, headers=self.headers)

        print(f"✅ 导入完成: {md_file_path} → {title} (ID: {page_id})")
        return page_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Markdown → Confluence 导入工具')
    parser.add_argument('md_file', help='Markdown 文件路径')
    parser.add_argument('--parent-id', default=None, help='父页面 ID')
    parser.add_argument('--page-name', default=None, help='自定义页面标题')
    parser.add_argument('--space', default=None, help='空间 Key（覆盖环境变量 CONFLUENCE_SPACE）')
    args = parser.parse_args()

    print("=" * 60)
    print("📘 Markdown → Confluence 导入工具")
    print("=" * 60)

    importer = MarkdownImporter(space_key=args.space)
    result = importer.import_markdown(
        args.md_file,
        parent_id=args.parent_id,
        page_name=args.page_name
    )
    print("🎉 导入成功!" if result else "❌ 导入失败，请检查调试文件。")
