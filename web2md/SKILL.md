---
name: web2md
description: 抓取网页内容，生成 Typora 兼容的 Markdown 文件（含本地图片、LaTeX 公式）
---

# web2md — 网页转 Markdown

输入 URL，自动生成 Typora 可打开的 `.md` 文件，图片下载到本地 `.assets` 文件夹，数学公式转为 LaTeX。

## 触发

**仅显式调用**。用户使用 `/web2md <URL>` 或 `@web2md <URL>` 时才执行。

用户随口发 URL 但没有用 `/web2md` 前缀的，不触发。

## 执行流程

### 第一步：Python 环境准备

**只执行一次**。后续直接使用已记录的环境。

**先问用户**：「有想用的 Python 环境路径吗？直接回车我自动搜索。」

用户指定 → 验证可用性 → 记住。

用户跳过 → 自动扫描：
- `where python` / `where python3`
- `~/python_env/*/python`、`E:/work/python_env/*/python`
- 系统 PATH

找到后列给用户确认。优先选已有 `requests`/`bs4`/`markdownify`/`lxml` 的。

依赖缺失则：
```bash
"<python路径>" -m pip install requests beautifulsoup4 markdownify lxml -q
```

**记住 Python 路径** → 写入 `.claude/settings.local.json`：
```json
{ "env": { "WEB2MD_PYTHON": "<Python路径>" } }
```
后续从 `env.WEB2MD_PYTHON` 读取，不再询问。路径失效或用户要求更换时重新走此流程。

### 第二步：确保脚本存在

检查当前项目根目录是否有 `web2md.py`，没有则从本 skill 的嵌入式脚本写入。

### 第三步：执行抓取

```bash
"<python路径>" "{项目根目录}/web2md.py" "<URL>" "{项目根目录}"
```

`HTTP_PROXY` / `HTTPS_PROXY` 环境变量存在时自动使用。

### 第四步：审核数学公式

脚本 `process_math_formulas` 只能识别以下四种标签：

- Wikipedia `.mwe-math-element`
- MathJax `<script type="math/tex">`
- `<math>` 标签 (MathML)
- Sphinx/MathJax `class="math"` 元素

**以下问题脚本不能（也不应该）自动处理，必须由 Claude 读取 .md 后逐一判断修复：**

#### A. `\_` → `_`、 `\*` → `*`（markdownify 后遗症）

markdownify 把 `_` 和 `*` 当作 Markdown 斜体/粗体标记转义为 `\_` `\*`。后果：

- 下标 `x_{k}` → `x\_{k}`，无法渲染
- 上标星号 `q^{*}` → `q^{\*}`, 多出无意义的 `\`

修复方式：对 `$$...$$` 和 `$...$`（限长 300 字符防孤立 `$`）内的 `\_` `\*` 做反转义。**绝不能**同时修 `\{` `\}`——它们是 `\left\{` `\right\}` 的合法组件。

#### B. 孤立 `$` 污染

Wikipedia 源码偶有孤立的 `$`（非公式用途），会被正则当成公式开头吞掉数百字散文。修复时 `$...$` 匹配必须限长 300 字符。

#### C. Wikipedia 的「伪公式」

部分简单公式 Wikipedia 用 `<b>` `<i>` `<sup>` 等 HTML 标签渲染，不走 `<math>` 标签。markdownify 转成 `**i**` `*i*` 后失去数学语义。

**这是最需要 LLM 判断的地方**——只有 Claude 能根据上下文判断 `**i**` 是四元数变量还是加粗文字。

**常见遗漏模式（不只搜 `=` 号！）：**

| 原文模式 | 含义 | 修复为 |
|----------|------|--------|
| `*x*2` | 变量+上标 | `$x^{2}$` |
| `*x* = *y*` | 等式 | `$x=y$` |
| `*a*1 + *b*2**i**` | 带下标表达式（无等号！） | `$a_{1}+b_{2}\mathbf{i}$` |
| `**i** ⋅ **j** = **k**` | 粗体变量+运算符 | `$\mathbf{i}\cdot\mathbf{j}=\mathbf{k}$` |
| `*a* + *b* **i** + *c* **j** + *d* **k**` | 四元数表达式 | `$a+b\mathbf{i}+c\mathbf{j}+d\mathbf{k}$` |
| `*S*3` | 数学符号+上标 | `$S^{3}$` |
| `*d*g(*p*, *q*)` | 函数+下标+参数 | `$d_{g}(p,q)$` |
| `*r a r*−1` | 表达式+上标 | `$rar^{-1}$` |
| `cos(*φ*)` | 数学函数 | `$\cos(\varphi)$` |

**扫描方法**：用正则 `*[a-zA-Z]*[0-9]` 搜"斜体+数字"、`*[a-zA-Z]* +` 搜"斜体+运算符"，列出全部可疑行，逐条读上下文判断。

**表格中的 `**i**` `**j**` `**k**` 保留**——乘法表表头，Markdown bold 即可。

#### D. `$$` 粘在行末

Wikipedia 把 display math `<span>` 嵌在 `<p>` 段落中，转换后 `$$` 出现在 `...is to choose $$` 这种位置。Typora 要求 `$$` 独占一行。脚本已通过正则修复：

```python
markdown = re.sub(r'([^\n])\$\$', lambda m: m.group(1) + '\n\n$$', markdown)
markdown = re.sub(r'\$\$([^\n])', lambda m: '$$\n\n' + m.group(1), markdown)
```

#### E. 检查清单

生成后逐项确认：
- [ ] `\_` 是否清零（只修 `\_`，不碰 `\{` `\}`）
- [ ] `\*` 是否清零（只修 `\*`，不碰 `\{` `\}`）
- [ ] `\begin{aligned}` 等环境中 `\\` 行断是否完整（双反斜杠）
- [ ] `\left\{` `\right\}` 是否未被破坏
- [ ] `$$` 公式块是否独占一行
- [ ] 用 `*字母*数字` + `*字母* +` 模式全量扫描伪公式，逐条确认（不能只搜 `=` ）

### 第五步：输出

告知用户文件路径，用 Typora 打开即可。

---

## 各项目固定文件

- `{项目根目录}/web2md.py` — 抓取脚本，首次使用时写入，之后保留不删
- `.claude/settings.local.json` — 记录 Python 路径（`env.WEB2MD_PYTHON`），每个项目各自记住

## 脚本关键技术要点

### 防御性设计

| 机制 | 位置 | 说明 |
|------|------|------|
| `unquote()` 图片文件名 | `download_images` | Wikipedia URL 含 `%28` `%29` `%3D` 等编码，需解码后再做文件名 |
| `is_wiki` 域名判断 | `html_to_markdown` | 语言栏/编辑链接清理、`[[edit]]` 移除仅对 `wikipedia.org` / `wikimedia.org` 生效 |
| `$$` 独占一行 | `html_to_markdown` | `([^\n])\$\$` → 前插 `\n\n`，`\$\$([^\n])` → 后插 `\n\n`，确保 Typora 识别 |
| 图片名截断 `max_len=60` | `sanitize_filename` | 避免超长文件名 |
| Wikimedia 限流退避 | `download_images` | HTTP 429 时递增等待 2/4/6 秒，Wikimedia 图片间加 0.3s 间隔 |

### 明确不要做的事

- **不要把 `\{` `\}` 当 Markdown 转义修复**——它们是 `\left\{` `\right\}` 的合法 LaTeX 组件
- **不要用正则去区分 `**i**` 是公式还是粗体**——这是 LLM 的工作，脚本做不到
- **不要对非 Wikipedia 页面做 Wikipedia 特有清洗**——`is_wiki` 兜底
- **公式修复代码不要写在脚本里**——脚本只负责标签转换和结构性调整，内容级修复由 Claude 读 .md 后手动完成

## Python 脚本（嵌入式）

以下脚本是 `web2md.py` 的完整内容。首次在某个项目执行时，如果该项目根目录下没有 `web2md.py`，则将此脚本写入 `{项目根目录}/web2md.py`，之后保留复用。

```python
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
from bs4 import BeautifulSoup
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


def process_math_formulas(soup) -> int:
    count = 0

    # 1. Wikipedia .mwe-math-element
    for math_span in soup.find_all(class_='mwe-math-element'):
        wrapper = math_span.find(class_=re.compile(r'mwe-math-mathml'))
        is_display = wrapper and 'display' in wrapper.get('class', [''])[0]
        latex = None
        annotation = math_span.find('annotation', attrs={'encoding': 'application/x-tex'})
        if annotation and annotation.string:
            latex = annotation.string.strip()
        if not latex:
            img = math_span.find('img')
            if img and img.get('alt'):
                latex = re.sub(r'^\\displaystyle\s+', '', img['alt'].strip())
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
```
