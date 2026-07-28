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

import os, re, sys, time, mimetypes
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup, NavigableString
from markdownify import markdownify as md

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


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


def download_images(soup, img_dir: Path, base_url: str, session: requests.Session) -> dict:
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
                    resp = session.get(full_url, timeout=30, stream=True, headers=headers)
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
    """Wrap escaped <placeholder> text in code without touching real tags or math."""
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


def link_sphinx_headings(soup, base_url: str) -> int:
    """Replace Sphinx permalink glyphs with source-linked heading text."""
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
    """Make non-local links portable while leaving non-Sphinx fragments local."""
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


def normalize_document_html(soup, base_url: str) -> dict:
    """Normalize non-math DOM content before extracting any LaTeX."""
    sphinx = is_sphinx_document(soup)
    headings = link_sphinx_headings(soup, base_url) if sphinx else 0
    links = normalize_document_links(soup, base_url, sphinx)
    placeholders = protect_angle_placeholders(soup)
    return {
        'sphinx_headings': headings,
        'links': links,
        'placeholders': placeholders,
    }


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
        if text.startswith('\\[') and text.endswith('\\]'):
            is_display = True
            text = text[2:-2]
        elif text.startswith('\\(') and text.endswith('\\)'):
            text = text[2:-2]
        elif '\\[' in text or '\\(' in text:
            is_display = True
        else:
            is_display = math_el.name == 'div'
        if re.search(r'[\\{}^_]', text):
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

    return count


def normalize_definition_list_tables(markdown: str) -> str:
    """Unindent tables that markdownify nests under a definition-list marker."""
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
        # Remove Wikipedia chrome elements such as language bars and edit links
        for selector in [
            '.mw-pt-languages',          # Language list
            '.interlanguage-link',       # Individual language link
            '.mw-pt-languages-label',    # "languages" label
            '#p-lang-btn',               # Language button
            '.mw-pt-languages-list',     # Language list container
            '.mw-pt-translate-header',   # "Translate" header
            '.mw-pt-progress',           # Progress bar
            '.mw-pt-tools',              # Tool links
        ]:
            for tag in content.select(selector):
                tag.decompose()

    html_str = str(content)

    markdown = md(html_str, heading_style="ATX", bullets="-", strip=['meta', 'link'])
    markdown = normalize_definition_list_tables(markdown)

    # Ensure each $$ formula block occupies its own line (Wikipedia display math is
    # embedded in <p> and sticks to the end of a line after conversion)
    markdown = re.sub(r'([^\n])\$\$', lambda m: m.group(1) + '\n\n$$', markdown)
    markdown = re.sub(r'\$\$([^\n])', lambda m: '$$\n\n' + m.group(1), markdown)

    markdown = re.sub(r'\n{3,}', '\n\n', markdown)

    if is_wiki:
        markdown = re.sub(r'\[\[edit\]\([^)]*\)\]', '', markdown)
        markdown = re.sub(r'\[\[编辑\]\([^)]*\)\]', '', markdown)
        # Remove residual Wikipedia chrome: language bars + edit links
        markdown = re.sub(
            r'\n*\d+\s*languages?\s*\n(?:\n*(?:-\s*\[[^]]*\]\([^)]*\).*?\n))+',
            '\n', markdown
        )
        markdown = re.sub(r'\n*\[Edit links\]\([^)]*\).*?\n', '\n', markdown)

    return markdown


def fetch_page(url: str, session: requests.Session) -> tuple:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding or 'utf-8'
    soup = BeautifulSoup(resp.text, 'lxml')
    return soup, resp.url, resp.text


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    output_root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()

    print(f"🌐 正在获取: {url}")
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    })

    try:
        soup, final_url, _ = fetch_page(url, session)
    except Exception as e:
        print(f"❌ 获取页面失败: {e}")
        sys.exit(1)

    title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
    if title and title.get('content'):
        title_text = title['content'].strip()
    else:
        title_text = soup.title.string.strip() if soup.title and soup.title.string else "untitled"

    print(f"📄 标题: {title_text}")

    folder_name = sanitize_filename(title_text)
    assets_folder_name = f"{folder_name}.assets"
    article_dir = output_root / folder_name
    assets_dir = article_dir / assets_folder_name
    article_dir.mkdir(parents=True, exist_ok=True)

    print(f"📁 文件夹: {article_dir}")
    print(f"📁 图片夹: {assets_dir}")

    normalize_stats = normalize_document_html(soup, final_url)
    if any(normalize_stats.values()):
        print(
            "🔗 规范化文档: "
            f"标题 {normalize_stats['sphinx_headings']}，"
            f"链接 {normalize_stats['links']}，"
            f"占位符 {normalize_stats['placeholders']}"
        )

    print("🔢 处理数学公式...")
    math_count = process_math_formulas(soup)
    if math_count:
        print(f"  转换了 {math_count} 个数学公式")

    img_mapping = download_images(soup, assets_dir, final_url, session)

    print("📝 转换为 Markdown...")
    markdown_text = html_to_markdown(soup, img_mapping, final_url, assets_folder_name)

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


if __name__ == '__main__':
    main()
