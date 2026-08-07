#!/usr/bin/env python3
"""
web2md - 将网页抓取为 Markdown 文件，图片下载到本地 .assets 文件夹。
输出结构适配 Typora：
    ./{标题}/
    ├── {标题}.md
    └── {标题}.assets/
        ├── image1.png
        ├── image2.jpg
        └── ...

用法：python web2md.py <URL> [输出目录]
"""

import os, re, sys, time, mimetypes, datetime, argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, unquote
import requests
from bs4 import BeautifulSoup, NavigableString
from markdownify import markdownify as md

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')


def load_config() -> dict:
    """从 scripts/config.py 读取配置，返回 web2md_config 分组 dict。

    缺失/损坏时打印提示并降级为默认值（脚本仍可独立命令行运行），
    首次配置请参考 config.example.py 或运行 /web2md 配置向导。
    """
    defaults = {'python_path': '', 'timeout': 30, 'collect_children': False,
                'merge_paragraphs': False, 'table_formula_inline': True, 'page_nav': True}
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️ 找不到配置文件: {CONFIG_PATH}")
        print("   请先运行 /web2md 完成首次配置（复制 config.example.py → scripts/config.py）")
        return defaults
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            exec(f.read(), ns := {})
    except Exception as e:
        print(f"⚠️ 配置文件读取失败: {e}，使用默认值")
        return defaults
    cfg = ns.get('web2md_config', {})
    merged = dict(defaults)
    merged.update({k: v for k, v in cfg.items() if v})
    return merged


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[\r\n\t]+', ' ', name)
    name = re.sub(r'[\\/:*?"<>|]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip().strip('.')
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "untitled"


def get_image_ext(url: str, content_type: str = "") -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in {'.png','.jpg','.jpeg','.gif','.svg','.webp','.bmp','.ico','.tiff','.tif'}:
        return ext
    ct = content_type.lower()
    if 'image/' in ct:
        guess = mimetypes.guess_extension(ct.split(';')[0].strip())
        if guess:
            return guess
    return '.png'


def download_images(soup, img_dir: Path, base_url: str, session: requests.Session, timeout: int = 30) -> dict:
    img_dir.mkdir(parents=True, exist_ok=True)
    mapping, seen_names = {}, {}

    imgs = soup.find_all('img')
    print(f"  找到 {len(imgs)} 张图片")

    for i, img in enumerate(imgs):
        src = img.get('src') or img.get('data-src') or ''
        if not src:
            continue
        full_url = urljoin(base_url, src)
        if full_url.startswith('data:'):
            continue
        if '/math/render/' in full_url or '/math/' in full_url:
            continue

        try:
            print(f"  [{i+1}/{len(imgs)}] 下载: {full_url[:100]}...")
            headers = {'Referer': base_url}
            resp = None
            is_wikimedia = 'wikimedia.org' in full_url or 'wikipedia.org' in full_url
            for attempt in range(3):
                try:
                    resp = session.get(full_url, timeout=timeout, stream=True, headers=headers)
                    if resp.status_code == 429 and is_wikimedia:
                        wait = (attempt + 1) * 2
                        print(f"    限流(429)，{wait}秒后重试...")
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    break
                except requests.exceptions.ConnectionError:
                    if attempt < 2:
                        time.sleep(1)
                        continue
                    raise
            if resp is None or resp.status_code != 200:
                raise Exception(f"下载失败 (status={resp.status_code if resp else 'N/A'})")
            if is_wikimedia and i < len(imgs) - 1:
                time.sleep(0.3)

            original_name = unquote(os.path.basename(urlparse(full_url).path)) or "image"
            ext = get_image_ext(full_url, resp.headers.get('Content-Type', ''))
            base_name = sanitize_filename(os.path.splitext(original_name)[0], max_len=60)
            filename = base_name + ext

            if filename in seen_names:
                seen_names[filename] += 1
                n, e = os.path.splitext(filename)
                filename = f"{n}_{seen_names[filename]}{e}"
            else:
                seen_names[filename] = 0

            filepath = img_dir / filename
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            mapping[src] = filename
            print(f"    -> {filename}")

        except Exception as e:
            print(f"    ❌ 失败: {e}")
            mapping[src] = None

    return mapping


def is_balanced_latex(text: str) -> bool:
    """LaTeX 花括号配对检查，跳过被反斜杠转义的括号"""
    depth = 0
    for i, char in enumerate(text):
        if char not in '{}':
            continue
        backslashes = 0
        j = i - 1
        while j >= 0 and text[j] == '\\':
            backslashes += 1
            j -= 1
        if backslashes % 2:
            continue
        depth += 1 if char == '{' else -1
        if depth < 0:
            return False
    return depth == 0


def wikipedia_latex(math_span):
    """从 annotation / img alt 中选平衡且更完整的 TeX 源（annotation 文本可能被截断）"""
    candidates = []
    annotation = math_span.find('annotation', attrs={'encoding': 'application/x-tex'})
    if annotation and annotation.string:
        candidates.append(annotation.string.strip())
    img = math_span.find('img')
    if img and img.get('alt'):
        candidates.append(img['alt'].strip())
    if not candidates:
        return None

    balanced = [latex for latex in candidates if is_balanced_latex(latex)]
    return max(balanced or candidates, key=len)


PLACEHOLDER_TEXT = re.compile(r'<[A-Za-z][^<>\n]*>')
PROTECTED_TEXT_TAGS = {'code', 'pre', 'script', 'style', 'math'}


def is_math_container(tag) -> bool:
    if not getattr(tag, 'name', None):
        return False
    if tag.name == 'math':
        return True
    if tag.name == 'script' and re.search(r'math/tex', tag.get('type', '')):
        return True
    classes = tag.get('class', [])
    return 'math' in classes or 'mwe-math-element' in classes


def is_protected_text_node(node) -> bool:
    for parent in node.parents:
        if parent.name in PROTECTED_TEXT_TAGS or is_math_container(parent):
            return True
    return False


def protect_angle_placeholders(soup) -> int:
    """把转义后的 <占位符> 文本包成 <code>，不碰真实 HTML 标签、代码与数学内容"""
    count = 0
    candidates = list(soup.find_all(string=PLACEHOLDER_TEXT))
    for node in candidates:
        if is_protected_text_node(node):
            continue
        value = str(node)
        matches = list(PLACEHOLDER_TEXT.finditer(value))
        if not matches:
            continue
        last = 0
        for match in matches:
            if match.start() > last:
                node.insert_before(NavigableString(value[last:match.start()]))
            code = soup.new_tag('code')
            code.string = match.group(0)
            node.insert_before(code)
            count += 1
            last = match.end()
        if last < len(value):
            node.insert_before(NavigableString(value[last:]))
        node.extract()
    return count


def is_sphinx_document(soup) -> bool:
    generator = soup.find('meta', attrs={'name': re.compile(r'^generator$', re.I)})
    content = generator.get('content', '') if generator else ''
    return 'sphinx' in content.lower() or soup.select_one('a.headerlink') is not None


def is_gitbook_document(soup) -> bool:
    """GitBook 3.x 页面：meta[generator] 含 GitBook，或存在搜索面板 #book-search-results"""
    generator = soup.find('meta', attrs={'name': re.compile(r'^generator$', re.I)})
    content = generator.get('content', '') if generator else ''
    return 'gitbook' in content.lower() or soup.select_one('#book-search-results') is not None


def remove_gitbook_chrome(soup) -> int:
    """移除 GitBook 非正文结构：顶部导航栏 .book-header 与搜索模板

    注意：GitBook 3.x 的正文容器 .search-noresults 嵌套在 #book-search-results 内部，
    因此只能删除搜索模板 div（.has-results / .no-result），绝不能整体删除
    #book-search-results 容器，否则正文会一起丢失。
    必须在 normalize_document_links 之前调用——.book-header 的 <a href=".."> 若先被
    规范化为指向站点根的绝对链接，删除时会留下难以清理的残留。
    """
    count = 0
    for sel in ('.book-header', '#book-search-results .has-results', '#book-search-results .no-results'):
        for el in soup.select(sel):
            el.decompose()
            count += 1
    return count


def link_sphinx_headings(soup, base_url: str) -> int:
    """把 Sphinx 锚点符号替换为链接到源章节的标题文本"""
    count = 0
    for heading in soup.find_all(re.compile(r'^h[1-6]$')):
        headerlink = heading.find('a', class_='headerlink')
        if not headerlink or not headerlink.get('href'):
            continue
        source_url = urljoin(base_url, headerlink['href'])
        headerlink.extract()
        if heading.find('a'):
            continue
        source_link = soup.new_tag('a', href=source_url)
        for child in list(heading.contents):
            source_link.append(child.extract())
        heading.append(source_link)
        count += 1
    return count


def normalize_document_links(soup, base_url: str, sphinx: bool) -> int:
    """让非本地链接可移植；非 Sphinx 页面的片段链接保持本地"""
    count = 0
    for link in soup.find_all('a', href=True):
        if any(is_math_container(parent) for parent in link.parents):
            continue
        href = link['href'].strip()
        if not href or href.startswith(('data:', 'javascript:', 'mailto:', 'tel:')):
            continue
        if href.startswith('#') and not sphinx:
            continue
        absolute = urljoin(base_url, href)
        if absolute != href:
            link['href'] = absolute
            count += 1
    return count


def normalize_document_html(soup, base_url: str, title_text=None) -> dict:
    """提取任何 LaTeX 之前，先规范化非数学的 DOM 内容（链接/标题/占位符）"""
    sphinx = is_sphinx_document(soup)
    if is_gitbook_document(soup):
        # 先删 GitBook 导航/搜索模板，避免其链接被绝对化后残留
        remove_gitbook_chrome(soup)
    duplicate_h1 = strip_duplicate_h1(soup, title_text)
    headings = link_sphinx_headings(soup, base_url) if sphinx else 0
    links = normalize_document_links(soup, base_url, sphinx)
    placeholders = protect_angle_placeholders(soup)
    return {
        'sphinx_headings': headings,
        'links': links,
        'placeholders': placeholders,
        'duplicate_h1': duplicate_h1,
    }


def strip_duplicate_h1(soup, title_text) -> int:
    """剥离页面自身与脚本前缀标题重复的第一个 h1（extract_title 优先取第一个非空 h1，
    两者文本相同时，脚本前缀 `# {title}` 已涵盖它，避免 md 出现两个同名 H1）。
    含 math/code/pre/script/style 子树的 h1 不剥离——保护公式载荷与代码格式。
    """
    if not title_text:
        return 0
    h1 = soup.find('h1')
    if not h1:
        return 0
    if any(t.name in PROTECTED_TEXT_TAGS or is_math_container(t) for t in h1.find_all(True)):
        return 0
    if clean_title_math(_clean_invisible_chars(h1.get_text(strip=True))) != title_text:
        return 0
    h1.decompose()
    return 1


def _mathml_to_latex(el) -> str:
    """Recursively convert MathML elements to LaTeX string."""
    if el is None:
        return ''
    if isinstance(el, str):
        return el

    tag = el.name if hasattr(el, 'name') else None
    if not tag:
        return el.get_text() if hasattr(el, 'get_text') else str(el)

    children = list(el.children) if hasattr(el, 'children') else []
    child_texts = [_mathml_to_latex(c) for c in children]
    inner = ''.join(child_texts).strip()

    if tag == 'math':
        return inner
    elif tag == 'mi':
        func_names = {'sin','cos','tan','cot','sec','csc',
                      'arcsin','arccos','arctan',
                      'sinh','cosh','tanh','coth',
                      'log','ln','lg','exp',
                      'lim','sup','inf','max','min',
                      'det','dim','gcd','deg','arg',
                      'ker','hom','Pr','mod'}
        if inner in func_names:
            return '\\' + inner + ' '
        return inner
    elif tag == 'mn':
        return inner
    elif tag == 'mo':
        mo_map = {
            '=': '=', '+': '+', '-': '-', '−': '-',
            '×': '\\times ', '*': '*', '/': '/',
            '(': '(', ')': ')', '[': '[', ']': ']',
            '→': '\\to ',
            '≤': '\\leq ', '≥': '\\geq ',
            '≠': '\\neq ', '≈': '\\approx ',
            '≡': '\\equiv ', '∝': '\\propto ',
            '∈': '\\in ',
            '±': '\\pm ',
            '∞': '\\infty ',
            '⋅': '\\cdot ',
            '…': '\\dots ',
            ',': ',', '.': '.',
            '⁡': '', '⁢': '', '⁣': '', '⁤': '',
        }
        return mo_map.get(inner, inner)
    elif tag == 'mtext':
        if inner == '' or inner.isspace():
            return ' '
        return '\\text{' + inner + '}'
    elif tag == 'msub':
        return child_texts[0] + '_{' + child_texts[1] + '}'
    elif tag == 'msup':
        return child_texts[0] + '^{' + child_texts[1] + '}'
    elif tag == 'msubsup':
        return child_texts[0] + '_{' + child_texts[1] + '}^{' + child_texts[2] + '}'
    elif tag == 'mfrac':
        return '\\frac{' + child_texts[0] + '}{' + child_texts[1] + '}'
    elif tag == 'msqrt':
        return '\\sqrt{' + inner + '}'
    elif tag == 'mroot':
        return '\\sqrt[' + child_texts[1] + ']{' + child_texts[0] + '}'
    elif tag == 'mover':
        accent = el.find('mo')
        accent_text = accent.get_text().strip() if accent else ''
        if accent_text in ('¯',):
            return '\\bar{' + child_texts[0] + '}'
        elif accent_text in ('→', '⟶'):
            return '\\vec{' + child_texts[0] + '}'
        elif accent_text in ('^', '̂'):
            return '\\hat{' + child_texts[0] + '}'
        elif accent_text in ('˜', '~', '̃'):
            return '\\tilde{' + child_texts[0] + '}'
        elif accent_text in ('¨',):
            return '\\ddot{' + child_texts[0] + '}'
        return '\\dot{' + child_texts[0] + '}'
    elif tag == 'munder':
        return '\\underset{' + child_texts[1] + '}{' + child_texts[0] + '}'
    elif tag == 'munderover':
        return '\\underset{' + child_texts[1] + '}{\\overset{' + child_texts[2] + '}{' + child_texts[0] + '}}'
    elif tag in ('mrow', 'mstyle', 'merror', 'mphantom', 'mpadded', 'semantics', 'TeXAtom', 'maction'):
        return inner
    elif tag == 'mspace':
        return ' '
    elif tag == 'menclose':
        return '\\boxed{' + inner + '}'
    elif tag == 'mtable':
        # Build matrix from table rows
        rows = []
        for tr in el.find_all('mtr', recursive=False) or el.find_all('mtr'):
            cells = [_mathml_to_latex(td) for td in tr.find_all('mtd', recursive=False) or tr.find_all('mtd')]
            if cells:
                rows.append(' & '.join(cells))
        if not rows:
            return inner
        n_cols = max(r.count('&') + 1 for r in rows)
        if n_cols == 1 and len(rows) <= 4:
            # Column vector: use inline notation without extra brackets
            return ', '.join(r.strip().rstrip('\\\\') for r in rows)
        col_spec = 'c' * n_cols
        return '\\begin{bmatrix}\n' + ' \\\\\n'.join(rows) + '\n\\end{bmatrix}'
    elif tag == 'mtr':
        return ' & '.join(child_texts) + ' \\\\'
    elif tag == 'mlabeledtr':
        return ' & '.join(child_texts[1:]) + ' \\\\'
    elif tag == 'mtd':
        return inner
    else:
        return inner


def process_math_formulas(soup) -> int:
    count = 0

    # 1. Wikipedia .mwe-math-element
    for math_span in soup.find_all(class_='mwe-math-element'):
        wrapper = math_span.find(class_=re.compile(r'mwe-math-mathml'))
        is_display = wrapper and 'display' in wrapper.get('class', [''])[0]
        latex = wikipedia_latex(math_span)
        if latex:
            d = '$$\n' if is_display else '$'
            s = '\n$$' if is_display else '$'
            math_span.replace_with(f'{d}{latex}{s}')
            count += 1

    # 2. Sphinx / MathJax class="math"
    for math_el in soup.find_all(class_=re.compile(r'\bmath\b')):
        text = math_el.get_text().strip()
        if not text:
            continue
        is_display = False
        # 是否被 \(...\) / \[...\] LaTeX 定界符完整包裹——被包裹即视为公式，
        # 即使正文为纯字母（如 \(L=W\)、\(AR\)）也需转换，不能靠 \{}^_ 过滤
        delimited = False
        if text.startswith('\\[') and text.endswith('\\]'):
            is_display = True
            delimited = True
            text = text[2:-2]
        elif text.startswith('\\(') and text.endswith('\\)'):
            delimited = True
            text = text[2:-2]
        elif '\\[' in text or '\\(' in text:
            is_display = True
            delimited = True
        else:
            is_display = math_el.name == 'div'
        if delimited or re.search(r'[\\{}^_]', text):
            d = '$$\n' if is_display else '$'
            s = '\n$$' if is_display else '$'
            math_el.replace_with(f'{d}{text}{s}')
            count += 1

    # 3. <script type="math/tex">
    for script_tag in soup.find_all('script', attrs={'type': re.compile(r'math/tex')}):
        latex = script_tag.string
        if latex:
            latex = latex.strip()
            is_display = 'mode=display' in script_tag.get('type', '')
            d = '$$\n' if is_display else '$'
            s = '\n$$' if is_display else '$'
            script_tag.replace_with(f'{d}{latex}{s}')
            count += 1

    # 4. <math> tags (MathML)
    for math_tag in soup.find_all('math'):
        latex = None
        annotation = math_tag.find('annotation', attrs={'encoding': 'application/x-tex'})
        if annotation and annotation.string:
            latex = annotation.string.strip()
        is_display = (
            math_tag.get('display') == 'block'
            or math_tag.get('mode') == 'display'
            or math_tag.get('displaystyle') == 'true'
        )
        if latex:
            d = '$$\n' if is_display else '$'
            s = '\n$$' if is_display else '$'
            math_tag.replace_with(f'{d}{latex}{s}')
            count += 1

    # 5. MathJax SVG <mjx-container> (e.g. PX4 docs, VitePress sites)
    for container in soup.find_all('mjx-container'):
        is_display = container.get('display') == 'true'
        assistive = container.find('mjx-assistive-mml')
        if assistive:
            math_tag = assistive.find('math')
            if math_tag:
                latex = _mathml_to_latex(math_tag)
                if latex:
                    # Post-process: fix decomposed function names (MathJax SVG
                    # splits "sin" into <mi>s</mi><mi>i</mi><mi>n</mi> etc.)
                    func_names = [
                        'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
                        'arcsin', 'arccos', 'arctan',
                        'sinh', 'cosh', 'tanh', 'coth',
                        'log', 'ln', 'lg', 'exp',
                        'lim', 'sup', 'inf', 'max', 'min',
                        'det', 'dim', 'gcd', 'deg', 'arg',
                        'ker', 'hom', 'mod',
                    ]
                    for fn in sorted(func_names, key=len, reverse=True):
                        # Match function name that is NOT already prefixed with backslash
                        # Must be followed by (, space, or end-of-string
                        latex = re.sub(
                            r'(?<!\\)\b' + re.escape(fn) + r'(?=[(\s]|$)',
                            '\\\\' + fn + ' ',
                            latex
                        )
                    d = '$$\n' if is_display else '$'
                    s = '\n$$' if is_display else '$'
                    container.replace_with(f'{d}{latex}{s}')
                    count += 1

    return count


PLAIN_TEX_OPEN = re.compile(r'\\([\[(])')


def _find_plain_close(text: str, start: int, closer: str) -> int:
    """从 start 起找第一个非转义的闭定界符（\\) / \\]）。

    闭定界符是「反斜杠 + 括号」（\\) / \\]），不是裸括号；
    \\) / \\] 前一个字符是反斜杠时视为转义（如 \\] 行距闭合），跳过。
    找不到返回 -1（= 跨节点配对，交 AI 复核）。
    """
    tok = '\\' + closer
    j = text.find(tok, start)
    while j != -1:
        if j > 0 and text[j - 1] == '\\':
            j = text.find(tok, j + 1)
            continue
        return j
    return -1


def convert_plain_tex_delimiters(soup, table_formula_inline: bool = True) -> tuple:
    """把 KaTeX auto-render / MathJax tex2jax 站点的裸 TeX 定界符转为 Typora 定界符。

    只处理文本节点内的配对：
      - \\(...\\) → $...$（行内）
      - \\[...\\] → $$...$$（显示，独占一行由 html_to_markdown 的 $$ 机制兜底）
      - table_formula_inline 时，<td>/<th> 单元格内的 \\[...\\] → $...$（行内）——
        markdown 表格单元格无法容纳 $$ 块（独占行 + 空行会撕裂表格），
        行内定界符让公式留在单元格内（含 \\\\ 行断的多行公式由 AI 按
        references/custom-site-rules.md §2 的 aligned 化规则处理）
    \\[ 行距（\\[0.5em]、前字符为反斜杠）与 \\left( \\left[ 不匹配（反斜杠不在括号前），
    不受影响；class="math" 等受保护子树已由 process_math_formulas 处理，不重复转换。
    跨节点配对（定界符与内容被 span 打断）不做替换，返回疑似计数交 AI 复核。
    返回 (行内数, 显示数, 跨节点疑似数)。
    """
    inline = display = cross = 0
    for node in soup.find_all(string=True):
        if is_protected_text_node(node):
            continue
        text = str(node)
        if not text or ('\\(' not in text and '\\[' not in text):
            continue
        in_table_cell = bool(table_formula_inline
                             and (node.find_parent('td') is not None
                                  or node.find_parent('th') is not None))
        parts = []
        i = 0
        changed = False
        while i < len(text):
            m = PLAIN_TEX_OPEN.search(text, i)
            if not m:
                parts.append(text[i:])
                break
            # \\[ 行距等：开定界符前一个字符是反斜杠 → 跳过
            if m.start() > 0 and text[m.start() - 1] == '\\':
                parts.append(text[i:m.end()])
                i = m.end()
                continue
            opener, closer, repl = m.group(1), (')' if m.group(1) == '(' else ']'), \
                                   ('$' if (m.group(1) == '(' or in_table_cell) else '$$')
            j = _find_plain_close(text, m.end(), closer)
            if j == -1:
                # 跨节点配对（或本站残缺定界符）：保留原文，交 AI 复核
                parts.append(text[i:m.end()])
                i = m.end()
                cross += 1
                continue
            parts.append(text[i:m.start()] + repl + text[m.end():j] + repl)
            changed = True
            if m.group(1) == '(' or in_table_cell:
                inline += 1
            else:
                display += 1
            i = j + 2   # 跳过整个闭定界符（\ 和括号两个字符）
        if changed:
            node.replace_with(NavigableString(''.join(parts)))
    return inline, display, cross


def _paragraph_stats(text: str) -> tuple:
    """统计 Markdown 中普通段落被源码硬换行切碎的情况。

    忽略 $$ 块、标题、引用、图片、列表项等非普通段落结构。
    返回 (切碎段数, 总段数)；切碎 = 段内 >=2 行且每行 <80 字符。
    """
    lines = text.splitlines()
    blocks, cur = [], []
    in_math = False
    for l in lines:
        s = l.strip()
        if s.startswith('$$'):
            in_math = not in_math
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if in_math:
            continue
        if s == '':
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if s.startswith(('#', '>', '![')) or s.startswith(('- ', '* ', '+ ')):
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if l.startswith(' ') and re.match(r'^\s{2,}\S', l):
            continue   # 缩进行（列表续行/定义列表段/公式标签行）不属于普通段落
        cur.append(l)
    if cur:
        blocks.append(cur)
    chopped = sum(1 for b in blocks if len(b) >= 2 and max(len(x) for x in b) < 80)
    return chopped, len(blocks)


def normalize_definition_list_tables(markdown: str) -> str:
    """去掉 markdownify 嵌套在定义列表标记下的表格缩进，让 Typora 能解析"""
    lines = markdown.splitlines()
    normalized = []
    i = 0
    while i < len(lines):
        match = re.match(r'^:\s+(\|.*\|)\s*$', lines[i])
        if not match:
            normalized.append(lines[i])
            i += 1
            continue

        normalized.append(match.group(1))
        i += 1
        while i < len(lines):
            row = re.match(r'^(?: {4}|\t)(\|.*\|)\s*$', lines[i])
            if not row:
                break
            normalized.append(row.group(1))
            i += 1
    return '\n'.join(normalized)


def ensure_table_separators(markdown: str) -> str:
    """表格块（连续 | 开头行）后若非空行则补空行，避免表格与公式块/段落粘连。

    markdownify 在表格后紧邻块级元素（KaTeX 公式块、段落）时不输出空行，
    表格行与下一块之间缺少空行会让 Typora 渲染错乱（如「表格行 + $$ 块」粘连）。
    补空行是机械操作，不影响内容；已有空行时不动。
    """
    lines = markdown.split('\n')
    out = []
    i = 0
    n = len(lines)
    while i < n:
        l = lines[i]
        out.append(l)
        if l.strip().startswith('|'):
            while i + 1 < n and lines[i + 1].strip().startswith('|'):
                i += 1
                out.append(lines[i])
            if i + 1 < n and lines[i + 1].strip():
                out.append('')
        i += 1
    return '\n'.join(out)


def html_to_markdown(soup, img_mapping: dict, base_url: str, assets_folder_name: str) -> str:
    is_wiki = 'wikipedia.org' in base_url or 'wikimedia.org' in base_url

    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        if src in img_mapping and img_mapping[src]:
            local_path = f"./{assets_folder_name}/{img_mapping[src]}"
            img['src'] = local_path
            if img.get('data-src'):
                img['data-src'] = local_path

    content = (
        soup.find('article') or
        soup.find('main') or
        soup.find(class_=re.compile(r'\b(?:content|article|post|entry)\b', re.I)) or
        soup.find(id=re.compile(r'\b(?:content|article|post|entry)\b', re.I)) or
        soup.body or
        soup
    )

    for tag in content.find_all(['script', 'style', 'nav', 'footer', 'iframe', 'noscript']):
        tag.decompose()
    if is_wiki:
        for tag in content.find_all(class_='mw-editsection'):
            tag.decompose()
        for tag in content.find_all(class_='mw-editsection-like'):
            tag.decompose()
        # 移除 Wikipedia 语言栏和编辑链接等 chrome 元素
        for selector in [
            '.mw-pt-languages',          # 语言列表
            '.interlanguage-link',       # 单个语言链接
            '.mw-pt-languages-label',    # "languages" 标签
            '#p-lang-btn',               # 语言按钮
            '.mw-pt-languages-list',     # 语言列表容器
            '.mw-pt-translate-header',   # "Translate" 头部
            '.mw-pt-progress',           # 进度条
            '.mw-pt-tools',              # 工具链接
        ]:
            for tag in content.select(selector):
                tag.decompose()

    html_str = str(content)

    markdown = md(html_str, heading_style="ATX", bullets="-", strip=['meta', 'link'])
    markdown = normalize_definition_list_tables(markdown)
    markdown = ensure_table_separators(markdown)

    # 确保 $$ 公式块独占一行（Wikipedia display math 嵌入 <p> 中，转换后黏在行末）
    markdown = re.sub(r'([^\n])\$\$', lambda m: m.group(1) + '\n\n$$', markdown)
    markdown = re.sub(r'\$\$([^\n])', lambda m: '$$\n\n' + m.group(1), markdown)

    markdown = re.sub(r'\n{3,}', '\n\n', markdown)

    if is_wiki:
        markdown = re.sub(r'\[\[edit\]\([^)]*\)\]', '', markdown)
        markdown = re.sub(r'\[\[编辑\]\([^)]*\)\]', '', markdown)
        # 移除 Wikipedia chrome 残留：语言栏 + 编辑链接
        markdown = re.sub(
            r'\n*\d+\s*languages?\s*\n(?:\n*(?:-\s*\[[^]]*\]\([^)]*\).*?\n))+',
            '\n', markdown
        )
        markdown = re.sub(r'\n*\[Edit links\]\([^)]*\).*?\n', '\n', markdown)

    return markdown


def fetch_page(url: str, session: requests.Session, timeout: int = 30) -> tuple:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding or 'utf-8'
    soup = BeautifulSoup(resp.text, 'lxml')
    return soup, resp.url, resp.text


TITLE_MATH_UNICODE = {
    # 希腊字母（小写）
    '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ',
    '\\epsilon': 'ε', '\\varepsilon': 'ε', '\\zeta': 'ζ', '\\eta': 'η',
    '\\theta': 'θ', '\\vartheta': 'ϑ', '\\iota': 'ι', '\\kappa': 'κ',
    '\\lambda': 'λ', '\\mu': 'μ', '\\nu': 'ν', '\\xi': 'ξ', '\\pi': 'π',
    '\\rho': 'ρ', '\\sigma': 'σ', '\\varsigma': 'ς', '\\tau': 'τ',
    '\\upsilon': 'υ', '\\phi': 'φ', '\\varphi': 'φ', '\\chi': 'χ',
    '\\psi': 'ψ', '\\omega': 'ω',
    # 希腊字母（大写）
    '\\Gamma': 'Γ', '\\Delta': 'Δ', '\\Theta': 'Θ', '\\Lambda': 'Λ',
    '\\Xi': 'Ξ', '\\Pi': 'Π', '\\Sigma': 'Σ', '\\Upsilon': 'Υ',
    '\\Phi': 'Φ', '\\Psi': 'Ψ', '\\Omega': 'Ω',
    # 常用运算符/符号
    '\\times': '×', '\\cdot': '·', '\\pm': '±', '\\mp': '∓',
    '\\rightarrow': '→', '\\leftarrow': '←', '\\Rightarrow': '⇒',
    '\\Leftrightarrow': '⇔', '\\leq': '≤', '\\geq': '≥', '\\neq': '≠',
    '\\approx': '≈', '\\infty': '∞', '\\in': '∈', '\\notin': '∉',
    '\\subset': '⊂', '\\subseteq': '⊆', '\\supset': '⊃', '\\supseteq': '⊇',
    '\\cup': '∪', '\\cap': '∩', '\\oplus': '⊕', '\\otimes': '⊗',
    '\\propto': '∝', '\\dots': '…', '\\ldots': '…', '\\cdots': '⋯',
    '\\partial': '∂', '\\nabla': '∇', '\\sum': 'Σ', '\\prod': '∏',
    '\\int': '∫', '\\sqrt': '√', '\\degree': '°',
}


def clean_title_math(text: str) -> str:
    """把标题中的裸 TeX 数学命令转 Unicode、去掉 \( \) \[ \] 定界符并压缩空白。

    部分站点作者在标题里用数学模式写希腊字母（如 `<h1>The \( \alpha \) filter</h1>`），
    若原样进入 sanitize_filename，`\` 会被当作路径分隔符替换成 `-`（文件夹乱码），
    且 md 前缀 H1 会残留裸定界符。此处做机械清理：定界符去除 + 常见命令映射 +
    空白压缩；未映射的 LaTeX 命令保留原样（不误删），由 AI 酌情调整。
    """
    text = text.replace(r'\(', ' ').replace(r'\)', ' ').replace(r'\[', ' ').replace(r'\]', ' ')
    for cmd in sorted(TITLE_MATH_UNICODE, key=len, reverse=True):
        text = re.sub(r'(?<![A-Za-z])' + re.escape(cmd) + r'(?![A-Za-z])',
                      TITLE_MATH_UNICODE[cmd], text)
    return re.sub(r'\s+', ' ', text).strip()


def extract_title(soup):
    """从页面提取标题（优先主标题 h1，其次 og:title/<title>，去掉 ' | 站点名' 后缀）

    同时清除零宽/不可见字符（如 U+200B 零宽空格，部分站点 h1 自带），并把裸 TeX
    数学命令转为 Unicode（clean_title_math）——避免混入文件夹名与 md 标题时乱码。
    """
    h1 = soup.find('h1')
    if h1 and h1.get_text(strip=True):
        return clean_title_math(_clean_invisible_chars(h1.get_text(strip=True)))
    title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
    if title and title.get('content'):
        return clean_title_math(_clean_invisible_chars(title['content'].strip().split(' | ')[0].strip()))
    if soup.title and soup.title.string:
        return clean_title_math(_clean_invisible_chars(soup.title.string.strip().split(' | ')[0].strip()))
    return "untitled"


_INVISIBLE_CHARS = re.compile(
    '[\u200b\u200c\u200d\u2060\ufeff\u00a0\u200e\u200f\uf0c1]'
)


def _clean_invisible_chars(text):
    """清除零宽与不可见字符（U+200B/U+200C/U+200D/U+2060/U+FEFF/U+00A0/U+200E/U+200F）"""
    return _INVISIBLE_CHARS.sub('', text)


def _norm_nav_url(u):
    """导航 URL 规范化：先去 fragment（锚点），再去尾部 / 与 .html / index.html / index
    （无扩展名），便于目录形式、.html 文件形式、服务器重定向去扩展名的形式互相匹配"""
    u = _strip_fragment(u)
    u = u.rstrip('/')
    if u.endswith('/index.html'):
        u = u[:-len('/index.html')]
    elif u.endswith('/index'):
        u = u[:-len('/index')]
    elif u.endswith('.html'):
        u = u[:-len('.html')]
    return u.rstrip('/')


def _strip_fragment(u):
    """去掉 URL fragment（锚点），用于判断链接是否指向当前页面自身"""
    try:
        return urlsplit(u)._replace(fragment='').geturl()
    except ValueError:
        return u.split('#')[0]


def _is_descendant_of(elm, ancestor):
    """elm 是否位于 ancestor 子树内"""
    n = elm.parent
    while n is not None:
        if n is ancestor:
            return True
        n = n.parent
    return False


def _child_nav_container(a):
    """current_a 所在的子页面导航容器。

    - VitePress 分组结构：current_a 在 div.item 里 → 所在 section（level-N）内的
      其他 div.item 链接即子页面，返回该 section。
    - Sphinx 嵌套结构：current_a 在 li/section 里 → 其内的嵌套 ul / div.items 为子页面。
    - 无子页面容器（叶子页面、顶层平铺页面——导航树中的相邻链接只是兄弟页面或
      整棵文档树）返回 None，调用方视为无导航子页面。
    """
    parent = a.parent
    if parent is not None and parent.name == 'div' and 'item' in (parent.get('class') or []):
        node = parent.parent
        while node is not None:
            if node.name == 'section':
                if any(l is not a for l in node.find_all('a', href=True)):
                    return node
                return None
            node = node.parent
        return None
    node = parent
    while node is not None:
        name = getattr(node, 'name', None)
        if name in ('li', 'section'):
            for sub in node.find_all('ul'):
                if not _is_descendant_of(a, sub) and sub.find('a', href=True):
                    return sub
            for sub in node.find_all('div'):
                cls = sub.get('class', []) if hasattr(sub, 'get') else []
                if 'items' in cls and not _is_descendant_of(a, sub) and sub.find('a', href=True):
                    return sub
            return None
        node = node.parent
    return None


def _same_doc_tree(href, base_url, base_dir):
    """href 是否与 base_url 同域且共享目录前缀（排除外部站点、版本/语言切换等非子页面链接）"""
    try:
        h = urlsplit(href)
        b = urlsplit(base_url)
    except ValueError:
        return False
    if h.netloc != b.netloc:
        return False
    return h.path.startswith(base_dir)


def collect_children(soup, base_url):
    """解析侧边栏导航 toctree，返回当前页面节点下的子/孙页面（嵌套 dict 列表）

    每项: {'title': 导航标题, 'url': 绝对 URL, 'children': [...]}
    深度限制: 1 = 直接子页面，2 = 孙页面，更深不取。
    找不到当前节点时返回空列表（此时视为无导航子页面）。

    实现与具体标签解耦（兼容 Sphinx 的 li/ul 与 VitePress 的 div/section）：
      - 定位 current_a 后，向上找最近"还包含其他链接"的祖先作容器
      - 子/孙层级按 a 与容器之间经过的 li/section 层数判定（当前页=0，子=1，孙=2）
    """
    current_a = None
    base_norm = _norm_nav_url(base_url)
    base_stripped = _strip_fragment(base_norm)
    for a in soup.find_all('a', href=True):
        # 纯锚点链接（#VPContent、#章节标题等）不参与当前节点定位——
        # 它们去 fragment 后与当前页 URL 相同，会把 current_a 误定位到布局/正文锚点
        href_raw = a.get('href', '').strip()
        if href_raw.startswith(('#', 'javascript:', 'mailto:')):
            continue
        href = _norm_nav_url(urljoin(base_url, href_raw))
        if _strip_fragment(href) == base_stripped:
            current_a = a
            break
    if current_a is None:
        return []

    # 子页面容器：current_a 所在项（li/section）内的嵌套导航 ul/div.items。
    # 无嵌套容器说明当前页面是叶子页或顶层平铺页（导航树中的相邻链接是兄弟页面或
    # 整棵文档树，不是子页面），视为无导航子页面。
    container = _child_nav_container(current_a)
    if container is None:
        return []

    def nav_level(a):
        """a 与 container 之间的层级容器数（ul / div.item / 嵌套 div.items；当前页=0，子=1，孙=2）。

        - ul：Sphinx 嵌套层级容器。
        - div.item：VitePress 链接容器（每个链接一个）。
        - div.items：VitePress 内容容器——仅当不是 container 的直接子级时计一层
          （container 直接子级的 div.items 是顶层内容列表，不是嵌套层级）。
        container 本身是 ul/div.items/div.item 时补计 1 级。
        """
        depth = 0
        n = a.parent
        while n is not None and n is not container:
            name = getattr(n, 'name', None)
            cls = n.get('class', []) if hasattr(n, 'get') else []
            if name == 'ul' or (name == 'div' and 'item' in cls):
                depth += 1
            elif name == 'div' and 'items' in cls:
                if n.parent is not container:
                    depth += 1
            n = n.parent
        cname = getattr(container, 'name', None)
        ccls = container.get('class', []) if hasattr(container, 'get') else []
        if cname == 'ul' or (cname == 'div' and ('items' in ccls or 'item' in ccls)):
            depth += 1
        return depth

    seen = set()
    accepted_stripped = set()   # 已接受链接去 fragment 后的 URL，用于识别同页锚点变体
    items1 = []   # (a, title, url) 子页面
    items2 = []   # (a, title, url) 孙页面
    base_dir = ''
    try:
        _p = urlsplit(base_norm).path
        if _p.endswith('/index'):
            # 服务器把 index.html 重定向为 /index：最后一段是目录名
            base_dir = _p[:-len('/index')] + '/'
        else:
            # 普通页面：最后一段是文件名，取所在目录
            base_dir = _p.rsplit('/', 1)[0] + '/'
    except ValueError:
        pass
    for a in container.find_all('a', href=True):
        if a is current_a:
            continue
        title = a.get_text(strip=True)
        href = urljoin(base_url, a.get('href', ''))
        if not title or href.startswith(('#', 'javascript:', 'mailto:')):
            continue
        # 只接受同域且共享目录前缀的链接（排除外部站点、版本/语言切换等）
        if not _same_doc_tree(href, base_url, base_dir):
            continue
        # 指向当前页面自身的链接（单页文档的章节锚点 commands.html#xxx）不是子页面
        stripped = _strip_fragment(_norm_nav_url(href))
        if stripped == base_stripped:
            continue
        # 指向某个已接受页面的锚点变体（customizing.html#xxx 与 customizing.html 同页，
        # 无论平铺为兄弟子项还是嵌套为孙级）→ 不是独立页面，跳过，避免重复抓取同一页面互相覆盖
        if stripped in accepted_stripped:
            continue
        if href in seen:
            continue
        seen.add(href)
        accepted_stripped.add(stripped)
        d = nav_level(a)
        if d == 1:
            items1.append((a, title, href))
        elif d == 2:
            items2.append((a, title, href))

    def _item_section(a):
        """a 的"项容器"（孙页面挂载锚点）。

        - Sphinx：a 所在 li（其嵌套 ul 是孙页面）。
        - VitePress：a 所在 div.item 的包裹容器 VPSidebarItem（level-N div），
          其嵌套 div.items 是孙页面；div.item 本身太窄，孙页面不在其内。
        """
        n = a.parent
        while n is not None and n is not container:
            name3 = getattr(n, 'name', None)
            cls3 = n.get('class', []) if hasattr(n, 'get') else []
            if name3 in ('section', 'li'):
                return n
            if name3 == 'div' and 'item' in cls3:
                p3 = n.parent
                # VitePress: 返回包裹 div.item 的 VPSidebarItem 容器——普通子页面是
                # div.level-N（is-link），可展开分组是 section.level-N（collapsible），
                # 两者都带 level- class；div.item 本身太窄，孙页面不在其内
                if (p3 is not None and p3 is not container and p3.name in ('div', 'section')
                        and any('level-' in c for c in (p3.get('class') or []))):
                    return p3
                return n
            n = n.parent
        return None

    result = []
    for a1, t1, u1 in items1:
        sec1 = _item_section(a1)
        kids = []
        if sec1 is not None:
            sec1_link_ids = {id(l) for l in sec1.find_all('a', href=True)}
            for a2, t2, u2 in items2:
                n = a2.parent
                inside = False
                while n is not None and n is not container:
                    if n is sec1:
                        inside = True
                        break
                    n = n.parent
                if inside:
                    # 孙页面指向其直接父页面自身的锚点（customizing.html#xxx）不是独立页面，跳过，避免重复抓取同一页面互相覆盖
                    if _strip_fragment(_norm_nav_url(u2)) == _strip_fragment(_norm_nav_url(u1)):
                        continue
                    kids.append({'title': t2, 'url': u2, 'children': []})
        result.append({'title': t1, 'url': u1, 'children': kids})
    return result


def _save_debug_snapshot(output_root, raw_html, label='fetch'):
    """处理失败时保存原始页面快照到 {项目根目录}/.web2md_tools/_archive/（排查用）"""
    archive_dir = Path(output_root) / '.web2md_tools' / '_archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = archive_dir / f'{label}_{ts}.html'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(raw_html)
    return path


def process_page(soup, final_url, raw_html, title_text, output_root, cfg, session):
    """处理单个页面：规范化 → 公式 → 图片 → Markdown → 落盘到 output_root/标题文件夹/

    返回 (folder_name, md_path)；失败返回 None（已保存调试快照）。
    """
    folder_name = sanitize_filename(title_text)
    assets_folder_name = f"{folder_name}.assets"
    article_dir = output_root / folder_name
    assets_dir = article_dir / assets_folder_name
    article_dir.mkdir(parents=True, exist_ok=True)

    print(f"📄 标题: {title_text}")
    print(f"📁 文件夹: {article_dir}")

    try:
        normalize_stats = normalize_document_html(soup, final_url, title_text)
        if any(normalize_stats.values()):
            print(
                "🔗 规范化文档: "
                f"标题 {normalize_stats['sphinx_headings']}，"
                f"链接 {normalize_stats['links']}，"
                f"占位符 {normalize_stats['placeholders']}，"
                f"重复 H1 {normalize_stats['duplicate_h1']}"
            )

        print("🔢 处理数学公式...")
        math_count = process_math_formulas(soup)
        if math_count:
            print(f"  转换了 {math_count} 个数学公式")

        # KaTeX auto-render / MathJax tex2jax 站点：公式是裸文本 \(...\) / \[...\] 定界符，
        # 无 class="math" 等标记，此处兜底转换（跨节点配对交 AI 复核）
        inline_n, display_n, cross_n = convert_plain_tex_delimiters(
            soup, cfg.get('table_formula_inline', True))
        if inline_n or display_n or cross_n:
            print(
                f"  🔎 检测到裸 TeX 定界符（KaTeX auto-render 站点）: "
                f"行内 {inline_n}，显示 {display_n}，跨节点疑似 {cross_n}"
            )
            print("  ✅ 已自动转换为 $ / $$ 定界符")
            if cross_n:
                print(f"  ⚠️ {cross_n} 处疑似跨节点配对（定界符与内容被标签打断），需 AI 助手复核（见 references/custom-site-rules.md）")

        img_mapping = download_images(soup, assets_dir, final_url, session, cfg['timeout'])

        print("📝 转换为 Markdown...")
        markdown_text = html_to_markdown(soup, img_mapping, final_url, assets_folder_name)

        # 段落切碎检测：源码硬换行切碎的段落 → 提示可合并（通用能力，所有站点适用）
        chopped, total = _paragraph_stats(markdown_text)
        if total and chopped / total >= 0.5:
            print(
                f"  📋 段落切碎检测: {chopped}/{total} 段被源码硬换行切碎（≥50%），"
                f"建议启用段落合并（config merge_paragraphs 或 --merge-paragraphs）"
            )
        if cfg.get('merge_paragraphs'):
            from merge_paragraphs import merge_markdown_paragraphs
            markdown_text = merge_markdown_paragraphs(markdown_text)
            print("  📋 已合并段落内的源码硬换行（merge_paragraphs）")

        md_path = article_dir / f"{folder_name}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(f"# {title_text}\n\n")
            f.write(f"> 原文链接: [{final_url}]({final_url})\n\n")
            f.write(markdown_text)

        success_count = sum(1 for v in img_mapping.values() if v)
        print(f"\n✅ 完成!")
        print(f"   Markdown: {md_path}")
        print(f"   图片: {success_count}/{len(img_mapping)} 张下载成功")
        print(f"   用 Typora 打开: {md_path}")
        return folder_name, md_path
    except Exception as e:
        snapshot = _save_debug_snapshot(output_root, raw_html)
        print(f"❌ 处理失败: {e}")
        print(f"📄 已保存原始页面快照（排查用）: {snapshot}")
        return None


def parse_children_list(path):
    """解析 AI 助手写的子页面清单文件，返回与 collect_children 相同的嵌套 dict 列表。

    清单格式（AI 助手生成，可读可编辑；脚本只做机械解析）：
        # 注释行（忽略）
        - 子页面标题 | https://.../child.html
          - 孙页面标题 | https://.../grand.html    （2 空格缩进 = 孙页面，最多 2 级）
        - 另一个子页面 | https://.../other.html | 备注（| 后的备注忽略）

    列表标记支持 - / *；URL 可带 <> 包裹；缩进超过 2 级、缺 URL 的行跳过并警告。
    标题仅用于展示，落盘文件夹名仍以页面实际标题为准（与 collect_children 行为一致）。
    """
    items = []
    try:
        lines = open(path, encoding='utf-8').read().splitlines()
    except OSError as e:
        raise ValueError(f'无法读取子页面清单: {e}')
    parents = {}   # depth -> 当前该深度的最后节点
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        m = re.match(r'^(\s*)[-*]\s+(.*)$', raw)
        if not m:
            print(f'  ⚠️ 清单第 {lineno} 行格式无效，跳过: {raw[:60]}')
            continue
        depth = len(m.group(1)) // 2
        body = m.group(2).strip()
        parts = body.split('|')
        title = parts[0].strip()
        url = parts[1].strip().strip('<>') if len(parts) > 1 else ''
        if not url:
            print(f'  ⚠️ 清单第 {lineno} 行缺少 URL，跳过: {raw[:60]}')
            continue
        node = {'title': title or url, 'url': url, 'children': []}
        if depth == 0:
            items.append(node)
        elif depth == 1:
            parent = parents.get(0)
            if parent is None:
                print(f'  ⚠️ 清单第 {lineno} 行孙页面缺少父页面，跳过: {raw[:60]}')
                continue
            parent['children'].append(node)
        else:
            print(f'  ⚠️ 清单第 {lineno} 行缩进超过 2 级（孙页面最深层级），忽略: {raw[:60]}')
            continue
        parents[depth] = node
    return items


def build_nav_block(entries, depth=0):
    """递归生成 Sub-pages 导航列表（children_list/导航顺序，孙页面嵌套缩进）。

    链接路径含空格时必须用 < > 包裹——final_verify 的链接正则
    ([^\\s)\\n]+) 在空格处截断，不带 < > 会误报「相对链接目标不存在」。
    """
    lines = []
    for e in entries:
        lines.append(f"{'  ' * depth}- [{e['title']}](<./{e['rel']}>)")
        sub = build_nav_block(e.get('children', []), depth + 1)
        if sub:
            lines.append(sub)
    return '\n'.join(lines)


def append_nav_block(md_path, entries):
    """父页面 md 末尾追加 Sub-pages 导航块（有子/孙页面时调用，page_nav 开启时）"""
    block = '\n\n## Sub-pages\n\n' + build_nav_block(entries) + '\n'
    with open(md_path, 'a', encoding='utf-8') as f:
        f.write(block)


def _fetch_child_tree(node, output_root, cfg, session, depth, prefix=''):
    """抓取导航树中的一个子/孙节点，落盘到 output_root 下（标题文件夹嵌套），递归孙页面。

    返回 {'title': 实际标题, 'rel': 相对父 md 的链接路径, 'children': [孙节点...]}，
    供父页面生成 Sub-pages 导航块；抓取失败返回 None。
    """
    pad = '  ' * depth
    print(f"{pad}📂 子页面「{node['title']}」({node['url']})")
    try:
        soup, final_url, raw_html = fetch_page(node['url'], session, cfg['timeout'])
    except Exception as e:
        print(f"{pad}❌ 获取失败: {e}")
        return None
    title_text = extract_title(soup)
    result = process_page(soup, final_url, raw_html, title_text, output_root, cfg, session)
    if result is None:
        return None
    folder, _ = result
    rel = f"{prefix}{folder}/{folder}.md"
    grandchildren = []
    for grand in node.get('children', []):
        g = _fetch_child_tree(grand, output_root / folder, cfg, session, depth + 1,
                              prefix=f"{prefix}{folder}/")
        if g:
            grandchildren.append(g)
    return {'title': title_text, 'rel': rel, 'children': grandchildren}


def fetch_and_process(url, output_root, cfg, session, children_mode=False, children_list=None):
    """抓取一个页面并按标题文件夹落盘。

    children_mode: 解析侧边栏导航递归抓取子/孙页面（规则路径）。
    children_list: AI 助手提供的子页面清单（--children-from），非 None 时优先于规则解析。
    """
    print(f"🌐 获取: {url}")
    try:
        soup, final_url, raw_html = fetch_page(url, session, cfg['timeout'])
    except Exception as e:
        print(f"❌ 获取页面失败: {e}")
        return False
    title_text = extract_title(soup)
    # 先收集导航子页面：process_page 内部的 html_to_markdown 会删除 <nav>，必须在处理页面之前解析
    if children_list is not None:
        children = children_list
    elif children_mode:
        children = collect_children(soup, final_url)
    else:
        children = []
    result = process_page(soup, final_url, raw_html, title_text, output_root, cfg, session)
    if result is None:
        return False
    folder, _ = result
    if children_list is not None and not children:
        print("  (清单无有效子页面)")
        return True
    if not children_mode and children_list is None:
        return True

    if not children:
        print("  (该页面无严格导航子页面)")
        return True
    print(f"  📂 发现 {len(children)} 个导航子页面，开始逐个抓取...")
    child_root = output_root / folder
    nav_entries = []
    for child in children:
        info = _fetch_child_tree(child, child_root, cfg, session, 1)
        if info:
            nav_entries.append(info)
    if cfg.get('page_nav', True) and nav_entries:
        append_nav_block(child_root / f"{folder}.md", nav_entries)
        print(f"  📑 已在父页面末尾追加 Sub-pages 导航块（{len(nav_entries)} 个子页面）")
    return True


def main():
    parser = argparse.ArgumentParser(description='web2md - 网页转 Markdown（含导航子页面批量获取）')
    parser.add_argument('url', help='目标网页 URL')
    parser.add_argument('output_root', nargs='?', default='.', help='输出根目录（默认当前目录）')
    parser.add_argument('--children', action='store_true', default=None,
                        help='收集导航子页面（覆盖 config.py 的 collect_children）')
    parser.add_argument('--no-children', action='store_false', dest='children',
                        help='不收集导航子页面（覆盖 config.py 的 collect_children）')
    parser.add_argument('--children-from', metavar='FILE',
                        help='从 AI 助手写的子页面清单文件抓取子/孙页面（优先于规则解析；格式见 SKILL.md）')
    parser.add_argument('--merge-paragraphs', action='store_true', default=None,
                        help='转换后合并段落内的源码硬换行（覆盖 config.py 的 merge_paragraphs）')
    parser.add_argument('--table-formula-inline', action='store_true', default=None,
                        help='表格单元格内显示公式行内化（覆盖 config.py 的 table_formula_inline）')
    parser.add_argument('--no-table-formula-inline', action='store_false', dest='table_formula_inline',
                        help='不将表格单元格内显示公式行内化（覆盖 config.py 的 table_formula_inline）')
    parser.add_argument('--page-nav', action='store_true', default=None,
                        help='父页面末尾追加 Sub-pages 导航块（覆盖 config.py 的 page_nav）')
    parser.add_argument('--no-page-nav', action='store_false', dest='page_nav',
                        help='不追加 Sub-pages 导航块（覆盖 config.py 的 page_nav）')
    args = parser.parse_args()

    url = args.url
    output_root = Path(args.output_root)
    cfg = load_config()
    collect = args.children if args.children is not None else bool(cfg.get('collect_children', False))
    if args.merge_paragraphs is not None:
        cfg['merge_paragraphs'] = args.merge_paragraphs
    if args.table_formula_inline is not None:
        cfg['table_formula_inline'] = args.table_formula_inline
    if args.page_nav is not None:
        cfg['page_nav'] = args.page_nav
    children_list = None
    if args.children_from:
        try:
            children_list = parse_children_list(args.children_from)
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)
        collect = True

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })

    print("=" * 60)
    print(f"🌐 web2md: {url}")
    if children_list is not None:
        print(f"   子页面清单: {args.children_from}（{len(children_list)} 项，优先于规则解析）")
    else:
        print(f"   导航子页面收集: {'开启' if collect else '关闭'}")
    print("=" * 60)

    ok = fetch_and_process(url, output_root, cfg, session, children_mode=collect, children_list=children_list)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
