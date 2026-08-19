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

import os, re, sys, time, mimetypes, datetime, argparse, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, unquote
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify as md
from config_literal import ConfigLiteralError, parse_literal_dict
from nav_children import collect_children

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')


def load_config() -> dict:
    """从 scripts/config.py 读取配置，返回 web2md_config 分组 dict。

    缺失/损坏时打印提示并降级为默认值（脚本仍可独立命令行运行），
    首次配置请参考 config.example.py 或运行 $web2md 配置向导。
    """
    defaults = {'python_path': '', 'timeout': 30, 'collect_children': False,
                'merge_paragraphs': False, 'table_formula_inline': True, 'page_nav': True,
                'proxy': ''}
    if not os.path.exists(CONFIG_PATH):
        print(f"⚠️ 找不到配置文件: {CONFIG_PATH}")
        print("   请先运行 $web2md 完成首次配置（复制 config.example.py → scripts/config.py）")
        return defaults
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = parse_literal_dict(f.read(), 'web2md_config')
    except (OSError, ConfigLiteralError) as e:
        print(f"⚠️ 配置文件读取失败: {e}，使用默认值")
        return defaults
    merged = dict(defaults)
    merged.update({key: cfg[key] for key in defaults if key in cfg})
    return merged


WINDOWS_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}
MAX_OUTPUT_PATH = 240
MAX_IMAGE_FILENAME = 80


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[\r\n\t]+', ' ', name)
    name = re.sub(r'[\\/:*?"<>|]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip().strip('.')
    if len(name) > max_len:
        name = name[:max_len].rstrip(' .')
    name = name or "untitled"
    windows_stem = name.split('.', 1)[0].rstrip(' .').upper()
    if windows_stem in WINDOWS_RESERVED_NAMES:
        name = ('_' + name)[:max_len].rstrip(' .') or '_'
    return name


def _canonical_source_url(source_url: str) -> str:
    try:
        parsed = urlsplit(source_url)
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
                           parsed.query, ''))
    except ValueError:
        return source_url.split('#', 1)[0]


def _output_name_budget(output_root, path_limit: int) -> int:
    root_length = len(str(Path(output_root).resolve()))
    # Longest generated path: root/name/name.assets/<image filename>.
    # Three separators + '.assets' (7) + MAX_IMAGE_FILENAME = 90 chars.
    return (path_limit - root_length - 90) // 2


def _existing_output_matches(article_dir: Path, name: str, source_url: str) -> bool:
    md_path = article_dir / f'{name}.md'
    if not md_path.is_file():
        return False
    try:
        prefix = md_path.read_text(encoding='utf-8')[:4096]
    except OSError:
        return False
    canonical = _canonical_source_url(source_url)
    for line in prefix.splitlines():
        if not line.startswith('> 原文链接: ') or '](' not in line or not line.endswith(')'):
            continue
        candidate = line.split('](', 1)[1][:-1]
        if _canonical_source_url(candidate) == canonical:
            return True
    return False


def resolve_output_name(output_root, title: str, source_url: str,
                        path_limit: int = MAX_OUTPUT_PATH) -> str:
    """Return a Windows-safe, path-budgeted folder name with stable collision hash."""
    output_root = Path(output_root)
    budget = min(80, _output_name_budget(output_root, path_limit))
    if budget < 1:
        raise ValueError(f'输出根目录过长，无法在 {path_limit} 字符路径预算内创建页面目录')
    base = sanitize_filename(title, max_len=budget)
    article_dir = output_root / base
    if not article_dir.exists() or _existing_output_matches(article_dir, base, source_url):
        return base

    digest = hashlib.sha256(_canonical_source_url(source_url).encode('utf-8')).hexdigest()
    for hash_length in (8, 12, 16, 24, 32, 64):
        suffix = '-' + digest[:hash_length]
        if len(suffix) >= budget:
            continue
        stem = sanitize_filename(title, max_len=budget - len(suffix))
        candidate = stem + suffix
        candidate_dir = output_root / candidate
        if (not candidate_dir.exists()
                or _existing_output_matches(candidate_dir, candidate, source_url)):
            return candidate
    raise ValueError('标题清洗后发生无法消解的输出路径冲突')


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
                suffix = f"_{seen_names[filename]}"
                n = n[:max(1, MAX_IMAGE_FILENAME - len(e) - len(suffix))]
                filename = f"{n}{suffix}{e}"
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
PLAIN_TEX_TOKEN = re.compile(r'\\(\(|\)|\[|\])')
PLAIN_TEX_BLOCKS = {
    'p', 'li', 'td', 'th', 'dt', 'dd', 'blockquote',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'figcaption', 'div',
}
SAFE_CROSS_TEX_TAGS = {'span'}
MAX_CROSS_TEX_NODES = 12
MAX_CROSS_TEX_CHARS = 2000


def _find_plain_close(text: str, start: int, closer: str) -> int:
    """从 start 起找第一个非转义的闭定界符（\\) / \\]）。

    闭定界符是「反斜杠 + 括号」（\\) / \\]），不是裸括号；
    \\) / \\] 前一个字符是反斜杠时视为转义（如 \\] 行距闭合），跳过。
    找不到返回 -1（随后进入有界跨节点配对；不可靠候选只报 REVIEW）。
    """
    tok = '\\' + closer
    j = text.find(tok, start)
    while j != -1:
        if j > 0 and text[j - 1] == '\\':
            j = text.find(tok, j + 1)
            continue
        return j
    return -1


def _plain_tex_tokens(text: str):
    """Return unescaped raw TeX delimiter tokens with source offsets."""
    tokens = []
    for match in PLAIN_TEX_TOKEN.finditer(text):
        backslashes = 0
        before = match.start() - 1
        while before >= 0 and text[before] == '\\':
            backslashes += 1
            before -= 1
        if backslashes % 2:
            continue
        tokens.append((match, match.group(1)))
    return tokens


def _plain_tex_block(node):
    for parent in node.parents:
        if getattr(parent, 'name', None) in PLAIN_TEX_BLOCKS:
            return parent
    return None


def _is_body_text_node(node) -> bool:
    """Accept only ordinary DOM text, excluding comments, doctypes and declarations."""
    return type(node) is NavigableString


def _cross_tex_range_is_safe(nodes, start_index, end_index, block) -> bool:
    if end_index - start_index + 1 > MAX_CROSS_TEX_NODES:
        return False
    for node in nodes[start_index:end_index + 1]:
        if is_protected_text_node(node):
            return False
        parent = node.parent
        while parent is not None and parent is not block:
            if not isinstance(parent, Tag) or parent.name not in SAFE_CROSS_TEX_TAGS:
                return False
            if is_math_container(parent):
                return False
            parent = parent.parent
        if parent is not block:
            return False

    current = nodes[start_index]
    stop = nodes[end_index]
    while current is not None and current is not stop:
        current = current.next_element
        if current is stop:
            break
        if isinstance(current, NavigableString) and not _is_body_text_node(current):
            return False
        if isinstance(current, Tag):
            if current.name in PROTECTED_TEXT_TAGS or is_math_container(current):
                return False
            if current.name not in SAFE_CROSS_TEX_TAGS:
                return False
    return current is stop


def _convert_cross_node_tex(soup, table_formula_inline: bool):
    """Convert uniquely paired raw delimiters across bounded neutral ``span`` nodes."""
    inline = display = 0
    while True:
        converted = False
        all_nodes = [node for node in soup.find_all(string=True)
                     if (_is_body_text_node(node)
                         and not is_protected_text_node(node))]
        for open_node in all_nodes:
            open_tokens = _plain_tex_tokens(str(open_node))
            for open_match, opener in open_tokens:
                if opener not in ('(', '['):
                    continue
                block = _plain_tex_block(open_node)
                if block is None:
                    continue
                nodes = [node for node in block.find_all(string=True)
                         if (_is_body_text_node(node)
                             and _plain_tex_block(node) is block)]
                try:
                    start_index = nodes.index(open_node)
                except ValueError:
                    continue
                next_token = None
                for node_index in range(start_index, len(nodes)):
                    node = nodes[node_index]
                    for token_match, token in _plain_tex_tokens(str(node)):
                        if node is open_node and token_match.start() <= open_match.start():
                            continue
                        next_token = (node_index, node, token_match, token)
                        break
                    if next_token:
                        break
                closer = ')' if opener == '(' else ']'
                if not next_token or next_token[3] != closer:
                    continue
                end_index, close_node, close_match, _ = next_token
                if close_node is open_node:
                    continue
                if not _cross_tex_range_is_safe(nodes, start_index, end_index, block):
                    continue

                payload_parts = [str(open_node)[open_match.end():]]
                payload_parts.extend(str(node) for node in nodes[start_index + 1:end_index])
                payload_parts.append(str(close_node)[:close_match.start()])
                payload = ''.join(payload_parts)
                if (len(payload) > MAX_CROSS_TEX_CHARS
                        or '\\(' in payload or '\\[' in payload
                        or '\\)' in payload or '\\]' in payload):
                    continue

                in_table_cell = bool(
                    table_formula_inline
                    and (block.find_parent('td') is not None or block.name in ('td', 'th')
                         or block.find_parent('th') is not None)
                )
                replacement = '$' if opener == '(' or in_table_cell else '$$'
                prefix = str(open_node)[:open_match.start()]
                suffix = str(close_node)[close_match.end():]
                open_node.replace_with(NavigableString(prefix + replacement + payload + replacement))
                for node in nodes[start_index + 1:end_index]:
                    node.replace_with(NavigableString(''))
                close_node.replace_with(NavigableString(suffix))
                if opener == '(' or in_table_cell:
                    inline += 1
                else:
                    display += 1
                converted = True
                break
            if converted:
                break
        if not converted:
            break

    review = 0
    for node in soup.find_all(string=True):
        if not _is_body_text_node(node) or is_protected_text_node(node):
            continue
        review += sum(1 for _, token in _plain_tex_tokens(str(node)) if token in ('(', '['))
    return inline, display, review


def convert_plain_tex_delimiters(soup, table_formula_inline: bool = True) -> tuple:
    """把 KaTeX auto-render / MathJax tex2jax 站点的裸 TeX 定界符转为 Typora 定界符。

    先处理文本节点内的配对；再处理同一块级容器内、最多 12 个文本节点且只跨
    中性 span 的唯一配对。跨块、受保护子树、格式化标签、歧义或超长候选保持原文。
    具体规则：
      - \\(...\\) → $...$（行内）
      - \\[...\\] → $$...$$（显示，独占一行由 html_to_markdown 的 $$ 机制兜底）
      - table_formula_inline 时，<td>/<th> 单元格内的 \\[...\\] → $...$（行内）——
        markdown 表格单元格无法容纳 $$ 块（独占行 + 空行会撕裂表格），
        行内定界符让公式留在单元格内（含 \\\\ 行断的多行公式由 AI 按
        references/custom-site-rules.md §2 的 aligned 化规则处理）
    \\[ 行距（\\[0.5em]、前字符为反斜杠）与 \\left( \\left[ 不匹配（反斜杠不在括号前），
    不受影响；class="math" 等受保护子树已由 process_math_formulas 处理，不重复转换。
    返回 (行内数, 显示数, REVIEW 数)；不可靠的跨节点候选只计 REVIEW。
    """
    inline = display = 0
    for node in soup.find_all(string=True):
        if not _is_body_text_node(node) or is_protected_text_node(node):
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
                # 可能跨节点或残缺；保留，稍后走有界跨节点配对。
                parts.append(text[i:m.end()])
                i = m.end()
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
    cross_inline, cross_display, review = _convert_cross_node_tex(
        soup, table_formula_inline)
    return inline + cross_inline, display + cross_display, review


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


WIKIPEDIA_MESSAGE_BOX_CLASSES = {
    'ambox', 'tmbox', 'ombox', 'cmbox', 'fmbox', 'imbox', 'mbox-small',
}
WIKIPEDIA_EQUATION_LABEL = re.compile(r'^Eq\.?\s*\d+$', re.IGNORECASE)


def _markdownify_fragment(tag) -> str:
    """Convert one table cell without letting markdownify see the table container."""
    fragment = ''.join(str(child) for child in tag.contents)
    converted = md(fragment, heading_style="ATX", bullets="-", strip=['meta', 'link'])
    return re.sub(r'\s*\n\s*', ' ', converted).strip()


def _direct_table_rows(table):
    """Return rows/cells owned by ``table`` and ignore any nested tables."""
    rows = []
    for row in table.find_all('tr'):
        if row.find_parent('table') is not table:
            continue
        cells = row.find_all(['td', 'th'], recursive=False)
        if cells:
            rows.append(cells)
    return rows


def _split_formula_cell(text: str):
    """Split a leading Markdown math span from an optional note/label."""
    text = text.strip()
    if text.startswith('$$'):
        match = re.match(r'^\$\$(.*?)\$\$(.*)$', text, re.DOTALL)
    elif text.startswith('$'):
        match = re.match(r'^\$(.*?)\$(.*)$', text, re.DOTALL)
    else:
        match = None
    if not match:
        return None, text
    return match.group(1).strip(), match.group(2).strip()


def _is_layout_note(text: str) -> bool:
    """Accept only narrow equation labels/parenthetical notes beside formula cells."""
    plain = re.sub(r'\[([^]]+)\]\([^)]+\)', r'\1', text)
    plain = re.sub(r'[*_`]', '', plain).strip()
    return bool(
        WIKIPEDIA_EQUATION_LABEL.fullmatch(plain)
        or re.match(r'^\(?\s*using\b', plain, re.IGNORECASE)
        or re.match(
            r'^\(?\s*(?:commutativity|associativity|distributivity)\b',
            plain,
            re.IGNORECASE,
        )
    )


def _formula_layout_rows(table):
    """Classify a Wikipedia formula layout table and return converted cell rows."""
    if table.find('th') or table.find('caption'):
        return None
    rows = _direct_table_rows(table)
    if not rows:
        return None

    converted_rows = []
    formula_cells = blank_cells = unsupported_cells = 0
    rows_with_formula = 0
    for row in rows:
        converted = []
        row_has_formula = False
        for cell in row:
            cell_markdown = _markdownify_fragment(cell)
            if not cell_markdown:
                blank_cells += 1
                converted.append(('', ''))
                continue
            formula, rest = _split_formula_cell(cell_markdown)
            if formula is not None:
                formula_cells += 1
                row_has_formula = True
                if rest and not _is_layout_note(rest):
                    unsupported_cells += 1
                converted.append((formula, rest))
            else:
                if not _is_layout_note(cell_markdown):
                    unsupported_cells += 1
                converted.append((None, cell_markdown))
        if row_has_formula:
            rows_with_formula += 1
        converted_rows.append(converted)

    classes = {str(value).lower() for value in table.get('class', [])}
    explicit_presentation = (
        str(table.get('role', '')).lower() == 'presentation'
        or 'numblk' in classes
    )
    if explicit_presentation:
        return converted_rows if formula_cells else None

    # Unlabelled Wikipedia formula layouts use blank spacer cells but no semantic
    # headers/caption. Require every row to carry math and reject unknown prose so
    # genuine data tables containing occasional formulas remain tables.
    if (formula_cells >= 2 and blank_cells >= 1 and unsupported_cells == 0
            and rows_with_formula == len(rows)):
        return converted_rows
    return None


def _render_formula_layout(rows) -> str:
    formula_rows = []
    trailing = []
    for row in rows:
        formulas = []
        for formula, rest in row:
            if formula:
                formulas.append(formula)
            if rest:
                trailing.append(rest)
        if formulas:
            formula_rows.append(r' \qquad '.join(formulas))

    if len(formula_rows) == 1:
        body = formula_rows[0]
    elif any(r'\begin{aligned}' in row for row in formula_rows):
        separator = ' ' + r'\\' + '\n'
        body = r'\begin{gathered}' + '\n' + separator.join(formula_rows) + '\n' + r'\end{gathered}'
    else:
        aligned_rows = []
        for index, row in enumerate(formula_rows):
            suffix = r' \\' if index < len(formula_rows) - 1 else ''
            aligned_rows.append('&' + row + suffix)
        body = r'\begin{aligned}' + '\n' + '\n'.join(aligned_rows) + '\n' + r'\end{aligned}'

    result = ['$$', body, '$$']
    result.extend(trailing)
    return '\n'.join(result)


def _render_wikipedia_message_box(table) -> str:
    cells = [cell for row in _direct_table_rows(table) for cell in row]
    candidates = [_markdownify_fragment(cell) for cell in cells]
    message = max((value for value in candidates if value), key=len, default='')
    if not message:
        return ''
    return '\n'.join('> ' + line if line else '>' for line in message.splitlines())


def flatten_wikipedia_layout_tables(content) -> dict:
    """Replace presentation-only Wikipedia tables with Markdown block placeholders.

    Formula alignment tables become display math; Wikipedia message boxes become
    blockquotes. Semantic tables are left untouched for markdownify.
    """
    replacements = {}
    for table in list(content.find_all('table')):
        if table.find_parent('table') is not None:
            continue
        classes = {str(value).lower() for value in table.get('class', [])}
        block = ''
        if classes & WIKIPEDIA_MESSAGE_BOX_CLASSES:
            block = _render_wikipedia_message_box(table)
        else:
            rows = _formula_layout_rows(table)
            if rows:
                block = _render_formula_layout(rows)
        if not block:
            continue
        token = f'WEB2MDWIKILAYOUTBLOCK{len(replacements) + 1:04d}'
        placeholder = BeautifulSoup(f'<p>{token}</p>', 'lxml').p
        table.replace_with(placeholder)
        replacements[token] = block
    return replacements


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

    layout_blocks = flatten_wikipedia_layout_tables(content) if is_wiki else {}
    html_str = str(content)

    markdown = md(html_str, heading_style="ATX", bullets="-", strip=['meta', 'link'])
    for token, block in layout_blocks.items():
        # A Wikipedia layout table can sit inside a definition-list <dd>.
        # markdownify prefixes that placeholder with ``:   ``; consume the
        # marker together with the token so it does not survive as an empty row.
        marker = re.compile(r'^:[ \t]*' + re.escape(token) + r'[ \t]*$', re.MULTILINE)
        markdown, replaced = marker.subn(lambda _match: block, markdown)
        if not replaced:
            markdown = markdown.replace(token, block)
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


def _page_identity(url: str):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    path = parsed.path.rstrip('/')
    if path.endswith('/index.html'):
        path = path[:-len('/index.html')]
    elif path.endswith('/index'):
        path = path[:-len('/index')]
    elif path.endswith('.html'):
        path = path[:-len('.html')]
    return (
        parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip('/'), parsed.query,
    )


def _snapshot_matches_page(rendered_soup, page_url: str, declared_url=None):
    """Validate rendered snapshot page metadata before trusting its navigation."""
    exact_candidates = []
    if declared_url:
        exact_candidates.append(('命令行 --rendered-url', declared_url))
    canonical = rendered_soup.find('link', rel=lambda value: value and 'canonical' in value)
    if canonical and canonical.get('href'):
        exact_candidates.append(('canonical', urljoin(page_url, canonical['href'])))
    for attrs in ({'property': 'og:url'}, {'name': 'twitter:url'}):
        meta = rendered_soup.find('meta', attrs=attrs)
        if meta and meta.get('content'):
            exact_candidates.append((next(iter(attrs.values())), urljoin(page_url, meta['content'])))

    expected = _page_identity(page_url)
    if exact_candidates:
        for source, candidate in exact_candidates:
            if _page_identity(candidate) != expected:
                return False, f'{source} 与当前页面 URL 不一致: {candidate}'
        return True, ''

    base = rendered_soup.find('base', href=True)
    if base:
        candidate = urlsplit(urljoin(page_url, base['href']))
        expected_url = urlsplit(page_url)
        if expected_url.query:
            return False, 'base href 无法核实带 query 的页面 identity；请提供 --rendered-url'
        base_path = candidate.path
        if not base_path.endswith('/'):
            base_path = base_path.rsplit('/', 1)[0] + '/'
        if ((candidate.scheme.lower(), candidate.netloc.lower())
                == (expected_url.scheme.lower(), expected_url.netloc.lower())
                and expected_url.path.startswith(base_path)):
            return True, ''
        return False, f'base href 与当前页面域名/版本路径不一致: {base["href"]}'
    return False, '快照缺少 --rendered-url、canonical/og:url 或可校验的 base href'


VERSION_PATH_SEGMENT = re.compile(
    r'^(?:v?\d+(?:[._-]\d+)*(?:[-_]?(?:alpha|beta|rc)\d*)?'
    r'|latest|stable|current|main|master|dev|nightly)$',
    re.IGNORECASE,
)


def _navigation_scope_prefix(path: str) -> str:
    """Return a slash-terminated tree/version prefix without collapsing ``/v1`` to ``/``."""
    segments = [segment for segment in path.split('/') if segment]
    version_index = None
    for index, segment in enumerate(segments):
        if VERSION_PATH_SEGMENT.fullmatch(segment):
            version_index = index
    if version_index is not None:
        return '/' + '/'.join(segments[:version_index + 1]) + '/'
    if not segments:
        return '/'
    if path.endswith('/'):
        return '/' + '/'.join(segments) + '/'

    last = segments[-1].casefold()
    if last in ('index', 'index.html', 'index.htm') or '.' in last:
        parent_segments = segments[:-1]
        return '/' + ('/'.join(parent_segments) + '/' if parent_segments else '')
    if len(segments) == 1:
        return '/' + segments[0] + '/'
    return '/' + '/'.join(segments[:-1]) + '/'


def _navigation_scope(url: str, page_url: str) -> bool:
    try:
        child = urlsplit(urljoin(page_url, url))
        page = urlsplit(page_url)
    except ValueError:
        return False
    base_dir = _navigation_scope_prefix(page.path)
    return (
        child.scheme.lower() == page.scheme.lower()
        and child.netloc.lower() == page.netloc.lower()
        and child.path.startswith(base_dir)
    )


def _validate_navigation_tree(children, page_url: str):
    """Re-check same-domain/version scope and hard-limit navigation to two levels."""
    accepted = []
    rejected = 0
    for child in children:
        if not _navigation_scope(child.get('url', ''), page_url):
            rejected += 1
            continue
        grandchildren = []
        for grand in child.get('children', []):
            if not _navigation_scope(grand.get('url', ''), page_url):
                rejected += 1
                continue
            if grand.get('children'):
                rejected += len(grand['children'])
            grandchildren.append({
                'title': grand.get('title') or grand.get('url', ''),
                'url': grand.get('url', ''),
                'children': [],
            })
        accepted.append({
            'title': child.get('title') or child.get('url', ''),
            'url': child.get('url', ''),
            'children': grandchildren,
        })
    return accepted, rejected


def collect_navigation(static_soup, page_url: str, rendered_html=None, rendered_url=None):
    """Collect static navigation, falling back to a validated rendered DOM snapshot."""
    static_result = dict(collect_children(static_soup, page_url))
    static_children, rejected = _validate_navigation_tree(static_result['children'], page_url)
    static_result['children'] = static_children
    static_result['source'] = 'static'
    static_result['review_required'] = False
    if rejected:
        static_result.setdefault('notes', []).append(
            f'静态导航有 {rejected} 项超出同域/同版本/两级范围，已拒绝')
    if static_children or rendered_html is None:
        notes_text = '\n'.join(static_result.get('notes', []))
        static_navigation_missing = (
            static_result.get('structure') in ('unknown', 'generic')
            or '未定位到当前页' in notes_text
        )
        if not static_children and rendered_html is None and static_navigation_missing:
            static_result.setdefault('notes', []).append(
                'REVIEW: 静态导航为空且没有渲染后 DOM 快照；请提供快照或 --children-from 清单')
            static_result['review_required'] = True
        return static_result

    rendered_soup = BeautifulSoup(rendered_html, 'lxml')
    valid, reason = _snapshot_matches_page(rendered_soup, page_url, rendered_url)
    if not valid:
        static_result.setdefault('notes', []).append(
            f'REVIEW: 渲染后 DOM 快照未通过基准 URL 校验（{reason}）；未使用快照')
        static_result['review_required'] = True
        return static_result

    rendered_result = dict(collect_children(rendered_soup, page_url))
    children, rendered_rejected = _validate_navigation_tree(
        rendered_result['children'], page_url)
    rendered_result['children'] = children
    rendered_result['source'] = 'rendered'
    rendered_result['review_required'] = not bool(children)
    rendered_result['notes'] = list(static_result.get('notes', [])) + [
        '静态导航为空，已使用通过基准 URL 校验的渲染后 DOM 快照'
    ] + list(rendered_result.get('notes', []))
    if rendered_rejected:
        rendered_result['notes'].append(
            f'渲染后导航有 {rendered_rejected} 项超出同域/同版本/两级范围，已拒绝')
    if not children:
        rendered_result['notes'].append(
            'REVIEW: 渲染后 DOM 仍未得到可核实子页面；请使用 --children-from 清单')
    return rendered_result


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
    r"""把标题中的裸 TeX 数学命令转 Unicode、去掉 \( \) \[ \] 定界符并压缩空白。

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


def _save_debug_snapshot(output_root, raw_html, label='fetch'):
    """处理失败时保存原始页面快照到 <skill>/logs/_archive/<项目根名>/（排查用）"""
    project_name = Path(output_root).resolve().name or 'default'
    archive_dir = (Path(__file__).resolve().parent.parent / 'logs' / '_archive' / project_name)
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
    try:
        folder_name = resolve_output_name(output_root, title_text, final_url)
        assets_folder_name = f"{folder_name}.assets"
        article_dir = output_root / folder_name
        assets_dir = article_dir / assets_folder_name
        article_dir.mkdir(parents=True, exist_ok=True)

        print(f"📄 标题: {title_text}")
        print(f"📁 文件夹: {article_dir}")

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
        # 无 class="math" 等标记，此处兜底转换（可靠跨节点配对自动转，其余报 REVIEW）
        inline_n, display_n, review_n = convert_plain_tex_delimiters(
            soup, cfg.get('table_formula_inline', True))
        if inline_n or display_n or review_n:
            print(
                f"  🔎 检测到裸 TeX 定界符（KaTeX auto-render 站点）: "
                f"行内 {inline_n}，显示 {display_n}，REVIEW {review_n}"
            )
            if inline_n or display_n:
                print("  ✅ 可靠配对已自动转换为 $ / $$ 定界符")
            if review_n:
                print(f"  ⚠️ {review_n} 处不可靠配对仅报告 REVIEW，需 AI 助手复核（见 references/custom-site-rules.md）")

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


def _fetch_child_tree(node, output_root, cfg, session, depth, prefix='', failures=None):
    """抓取导航树中的一个子/孙节点，落盘到 output_root 下（标题文件夹嵌套），递归孙页面。

    返回 {'title': 实际标题, 'rel': 相对父 md 的链接路径, 'children': [孙节点...]}，
    供父页面生成 Sub-pages 导航块；抓取失败返回 None，并把失败 URL 追加到 failures。
    """
    if failures is None:
        failures = []
    pad = '  ' * depth
    print(f"{pad}📂 子页面「{node['title']}」({node['url']})")
    try:
        soup, final_url, raw_html = fetch_page(node['url'], session, cfg['timeout'])
    except Exception as e:
        failures.append(node['url'])
        print(f"{pad}❌ 获取失败 [{node['url']}]: {e}")
        return None
    title_text = extract_title(soup)
    result = process_page(soup, final_url, raw_html, title_text, output_root, cfg, session)
    if result is None:
        failures.append(node['url'])
        print(f"{pad}❌ 处理失败 [{node['url']}]")
        return None
    folder, _ = result
    rel = f"{prefix}{folder}/{folder}.md"
    grandchildren = []
    for grand in node.get('children', []):
        g = _fetch_child_tree(grand, output_root / folder, cfg, session, depth + 1,
                              prefix=f"{prefix}{folder}/", failures=failures)
        if g:
            grandchildren.append(g)
    return {'title': title_text, 'rel': rel, 'children': grandchildren}


def fetch_and_process(url, output_root, cfg, session, children_mode=False, children_list=None,
                      rendered_html=None, rendered_url=None):
    """抓取一个页面并按标题文件夹落盘。

    children_mode: 解析侧边栏导航递归抓取子/孙页面（规则路径）。
    children_list: AI 助手提供的子页面清单（--children-from），非 None 时优先于规则解析。
    rendered_html/rendered_url: 静态导航为空时使用并校验的渲染后 DOM 快照。
    """
    print(f"🌐 获取: {url}")
    try:
        soup, final_url, raw_html = fetch_page(url, session, cfg['timeout'])
    except Exception as e:
        print(f"❌ 获取页面失败: {e}")
        return False
    title_text = extract_title(soup)
    navigation_review_required = False
    # 先收集导航子页面：process_page 内部的 html_to_markdown 会删除 <nav>，必须在处理页面之前解析
    if children_list is not None:
        children = children_list
    elif children_mode:
        # nav_children.collect_children 返回 dict：{structure, children, notes}；
        # 命中策略时 children 可能为空（真无子页面），未命中时 structure='unknown' 且
        # notes 带诊断——两种情况都不影响主流程，打印 notes 供 AI 助手判断
        nav_result = collect_navigation(
            soup, final_url, rendered_html=rendered_html, rendered_url=rendered_url)
        children = nav_result['children']
        navigation_review_required = bool(nav_result.get('review_required'))
        if nav_result.get('source') == 'rendered':
            print('  🧭 静态导航为空，启用渲染后 DOM 降级通道')
        if nav_result['notes']:
            for note in nav_result['notes']:
                print(f"  🧭 导航诊断: {note}")
        if not children and nav_result['structure'] != 'unknown':
            print(f"  (该页面无严格导航子页面，structure={nav_result['structure']})")
        elif not children:
            print(f"  (导航结构未识别（structure=unknown），无子页面收集)")
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
        if navigation_review_required:
            print("  ❌ 导航仍有 REVIEW，需提供可靠 DOM 快照或 --children-from 清单")
            return False
        return True
    print(f"  📂 发现 {len(children)} 个导航子页面，开始逐个抓取...")
    child_root = output_root / folder
    nav_entries = []
    failed_urls = []
    for child in children:
        info = _fetch_child_tree(child, child_root, cfg, session, 1, failures=failed_urls)
        if info:
            nav_entries.append(info)
    if cfg.get('page_nav', True) and nav_entries:
        append_nav_block(child_root / f"{folder}.md", nav_entries)
        print(f"  📑 已在父页面末尾追加 Sub-pages 导航块（{len(nav_entries)} 个子页面）")
    if failed_urls:
        print(f"  ❌ 子页面批次失败：{len(failed_urls)} 个 URL（成功产物已保留）")
        for failed_url in failed_urls:
            print(f"     - {failed_url}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='web2md - 网页转 Markdown（含导航子页面批量获取）')
    parser.add_argument('url', help='目标网页 URL')
    parser.add_argument('output_root', nargs='?', default='.', help='输出根目录（默认当前目录）')
    parser.add_argument('--children', action='store_true', default=None,
                        help='收集导航子页面（覆盖 config.py 的 collect_children）')
    parser.add_argument('--no-children', action='store_false', dest='children',
                        help='不收集导航子页面（覆盖 config.py 的 collect_children）')
    nav_input = parser.add_mutually_exclusive_group()
    nav_input.add_argument('--children-from', metavar='FILE',
                           help='从 AI 助手写的子页面清单文件抓取子/孙页面（优先于规则解析；格式见 SKILL.md）')
    nav_input.add_argument('--rendered-html', metavar='FILE',
                           help='静态导航为空时使用浏览器保存的渲染后 DOM 快照')
    parser.add_argument('--rendered-url', metavar='URL',
                        help='渲染后 DOM 快照对应的页面 URL（用于基准 URL 校验）')
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
    if args.rendered_url and not args.rendered_html:
        parser.error('--rendered-url 必须与 --rendered-html 一起使用')

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
    rendered_html = None
    if args.rendered_html:
        try:
            rendered_html = Path(args.rendered_html).read_text(encoding='utf-8')
        except OSError as e:
            print(f'❌ 无法读取渲染后 DOM 快照: {e}')
            sys.exit(1)
        collect = True

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })
    # 代理：config.py 的 proxy 显式配置优先于环境变量（单一配置源）；
    # 空字符串时 requests 自动读 HTTP_PROXY/HTTPS_PROXY 环境变量
    if cfg.get('proxy'):
        session.proxies = {'http': cfg['proxy'], 'https': cfg['proxy']}
        print(f"   代理（config.py 配置）: {cfg['proxy']}")

    print("=" * 60)
    print(f"🌐 web2md: {url}")
    if children_list is not None:
        print(f"   子页面清单: {args.children_from}（{len(children_list)} 项，优先于规则解析）")
    elif rendered_html is not None:
        print(f"   渲染后 DOM 降级快照: {args.rendered_html}")
    else:
        print(f"   导航子页面收集: {'开启' if collect else '关闭'}")
    print("=" * 60)

    ok = fetch_and_process(
        url, output_root, cfg, session, children_mode=collect,
        children_list=children_list, rendered_html=rendered_html,
        rendered_url=args.rendered_url)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
