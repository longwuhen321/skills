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
{
  "permissions": {
    "allow": [
      "Bash(<Python路径> *)"
    ]
  },
  "env": { "WEB2MD_PYTHON": "<Python路径>" }
}
```
后续从 `env.WEB2MD_PYTHON` 读取，不再询问。路径失效或用户要求更换时重新走此流程。
> 同时写入 Bash allow 规则，避免后续每次执行脚本都弹确认。

### 第二步：确保脚本存在

检查 `.web2md_tools/` 目录，确认以下脚本存在，没有则从本 skill 嵌入内容写入：

| 文件 | 用途 | 阶段 |
|------|------|------|
| `web2md.py` | 主抓取脚本 | 第三步 |
| `fix_escapes.py` | `\_` `\*` → `_` `*` | 第四步-A |
| `list_display_fixes.py` | 列出需 `$`→`$$` 的公式 | 第四步-B |
| `find_all_missed.py` | 扫描伪公式模式 | 第四步-C |
| `final_verify.py` | 验证：`\_` 残留、`\\` 行断 | 收尾 |

### 第三步：执行抓取

```bash
"<python路径>" "{项目根目录}/.web2md_tools/web2md.py" "<URL>" "{项目根目录}"
```

`HTTP_PROXY` / `HTTPS_PROXY` 环境变量存在时自动使用。

### 第四步：审核数学公式

脚本 `process_math_formulas` 只识别 Wikipedia `.mwe-math-element`、MathJax `<script>`、`<math>`、`class="math"`、MathJax SVG `<mjx-container>` 五种标签转为 `$...$` / `$$...$$`。

生成 .md 后，分三个阶段完成审核：

#### 阶段 A：脚本自动修复（`fix_escapes.py`）

修复 markdownify 造成的 `\_` `\*` 错误转义（下标 `x_{k}` → `x\_{k}`、上标 `q^{*}` → `q^{\*}`）。

```bash
"<python路径>" "{项目根目录}/.web2md_tools/fix_escapes.py" "{md文件路径}"
```

内部逻辑：`$$` 和 `$` 块内（限长 2000 字符防孤立 `$`）`\_` → `_`、`\*` → `*`，再全局兜底。

> **不在此阶段修 `\{` `\}`**——它们是 `\left\{` `\right\}` 的合法 LaTeX 组件。

#### 阶段 B：`$` vs `$$` 审核（`list_display_fixes.py` + Claude 判断）

```bash
"<python路径>" "{项目根目录}/.web2md_tools/list_display_fixes.py" "{md文件路径}"
```

脚本列出含 `\begin{}` 或 `\\` 行断、但仍被 `$` 包裹的公式。Claude 根据规则逐条判、逐条 Edit：

| 条件 | 判决 |
|------|------|
| `\begin{aligned/cases/array/bmatrix}` | → `$$` |
| 含 `\\` 行断（多行公式） | → `$$` |
| 其余单行公式 | 保持 `$`（`$\displaystyle...$` 在 Typora 中等同 `$$`） |

#### 阶段 C：LLM 通读循环（伪公式识别）

Wikipedia 用 `<b>` `<i>` `<sup>` 渲染的简单公式，markdownify 转成了 `**i**` `*i*`。脚本无法判断——**由 Claude 读 .md 全文**，根据上下文识别。

1. **通读** .md → 识别遗漏的伪公式（`**w***k*`、`*x*2`、`*a*1 + *b*2**i**` 等）
2. **写清单**到 `.web2md_tools/intermediate/fix_list_roundN.md`，格式：`行号 + 原文片段 → 建议修复`
3. **逐条 Edit**，修一条划一条
4. **重读复核**
5. 有遗漏 → 回到步骤 2，**直到干净**

常见遗漏模式（按类型分组）：

**A. 斜体 + 数字 → 下标或上标**

| 原文 | 修复 | 说明 |
|------|------|------|
| `*a*1` | `$a_{1}$` | 斜体字母+数字 → 下标 |
| `*x*2` | `$x^{2}$` | 需根据上下文判下标还是上标 |
| `*S*3` | `$S^{3}$` | 数学符号+上标 |
| `*r*−1` | `$r^{-1}$` | 变量+幂次 |

**B. 斜体 + 运算符 → 行内公式**

| 原文 | 修复 | 说明 |
|------|------|------|
| `*x* = *y*` | `$x=y$` | 等式 |
| `*a* + *b*` | `$a+b$` | 加法表达式 |
| `*p* − *q*` | `$p-q$` | 减法表达式 |
| `*c* = *d* = 0` | `$c=d=0$` | 链式等式 |
| `*aq* = *qa*` | `$aq=qa$` | 乘积等式 |

**C. 粗体 + 数字 / 运算符 → 向量公式**

| 原文 | 修复 | 说明 |
|------|------|------|
| `**i**2` | `$\mathbf{i}^{2}$` | 粗体+上标 |
| `**i** ⋅ **j** = **k**` | `$\mathbf{i}\cdot\mathbf{j}=\mathbf{k}$` | 粗体+运算符 |

**D. 粗体字母作为数学符号（散文中）**

| 原文 | 修复 | 说明 |
|------|------|------|
| `{1, **i**, **j**, **k**}` | `$\{1,\mathbf{i},\mathbf{j},\mathbf{k}\}$` | 集合 |
| `±**i**, ±**j**, ±**k**` | `$\pm\mathbf{i},\pm\mathbf{j},\pm\mathbf{k}$` | 带正负号 |
| `**i**, **j**, and **k** will denote` | `$\mathbf{i},\mathbf{j},\mathbf{k}$ will denote` | 散文中的符号 |
| `replacing 1 with a, **i** with b` | `replacing $1$ with $a$, $\mathbf{i}$ with $b$` | 映射定义 |

> ⚠️ 乘法表 `| **i** | **j** | **k** |` → **保留 bold**，是表格格式化非公式

**E. 函数 + 斜体参数**

| 原文 | 修复 | 说明 |
|------|------|------|
| `cos(*φ*)` | `$\cos(\varphi)$` | 三角函数 |
| `sin(*θ*)` | `$\sin(\theta)$` | 同上 |

**F. 混合粗体 + 斜体表达式**

| 原文 | 修复 | 说明 |
|------|------|------|
| `*a* + *b* **i** + *c* **j** + *d* **k**` | `$a+b\mathbf{i}+c\mathbf{j}+d\mathbf{k}$` | 四元数表达式 |
| `*a*1 + *b*1**i** + *c*1**j**` | `$a_{1}+b_{1}\mathbf{i}+c_{1}\mathbf{j}$` | 带下标表达式 |
| `*p* = *b*1**i** + *c*1**j** + *d*1**k**` | `$p=b_{1}\mathbf{i}+c_{1}\mathbf{j}+d_{1}\mathbf{k}$` | 向量定义 |

**G. 斜体含特殊符号（上标星号等）**

| 原文 | 修复 | 说明 |
|------|------|------|
| `*pq*∗` | `$pq^{*}$` | 共轭/对偶标记 |
| `*p*∗*q*` | `$p^{*}q$` | 同上 |
| `−*q*∗*p*∗` | `$-q^{*}p^{*}$` | 同上 |

**H. 数学符号/记法**

| 原文 | 修复 | 说明 |
|------|------|------|
| `*d*g(*p*, *q*)` | `$d_{g}(p,q)$` | 函数+下标+参数 |
| `*r a r*−1` | `$rar^{-1}$` | 共轭表达式 |
| `*p*s, *q*s, *p*v, *q*v` | `$p_{s},q_{s},p_{v},q_{v}$` | 变量+下标 |

**I. 数学符号与单位**

Wikipedia 用粗体/Unicode 渲染的数学符号，脚本无法识别。

**I-1. 粗体大写字母（数域/集合记号）** — Wikipedia 用 `**X**` 替代黑体板书 `\mathbb{X}`：

| 原文 | 数域 | 修复 |
|------|------|------|
| `**R**` | 实数 | `$\mathbf{R}$` |
| `**C**` | 复数 | `$\mathbf{C}$` |
| `**Z**` | 整数 | `$\mathbf{Z}$` |
| `**Q**` | 有理数 | `$\mathbf{Q}$` |
| `**N**` | 自然数 | `$\mathbf{N}$` |
| `**F**` | 域 | `$\mathbf{F}$` |
| `**H**` | 四元数 | `$\mathbf{H}$` |
| `**U**` | 酉群/算子 | `$\mathbf{U}$` |
| `**O**` | 正交群 | `$\mathbf{O}$` |
| `**S**` | 球面/特殊群 | `$\mathbf{S}$` |
| `M(2,**C**)` | 矩阵环 | `$M(2,\mathbf{C})$` |

**I-2. 角度与单位**

| 原文 | 修复 | 说明 |
|------|------|------|
| `90°` `180°` `360°` | `$90^{\circ}$` 等 | 角度度数 |
| `45′` `30″` | `$45'$` `$30''$` | 分、秒（罕见） |

**I-3. Unicode 运算符**

| 原文 | 修复 | 说明 |
|------|------|------|
| `±x` `±i` | `$\pm x$` | 正负号+变量 |
| `a ⋅ b` | `$a \cdot b$` | 点乘 |
| `a × b` | `$a \times b$` | 叉乘（`2 × 2` 维度保留 Unicode） |
| `a ∗ b` | `$a * b$` | 卷积/星乘 |
| `−x` | `$-x$` | Unicode 减号 |

**I-4. 不等号与关系符**

| 原文 | 修复 |
|------|------|
| `a ≤ b` | `$a \leq b$` |
| `a ≥ b` | `$a \geq b$` |
| `a ≠ b` | `$a \neq b$` |
| `a ≈ b` | `$a \approx b$` |
| `a ≡ b` | `$a \equiv b$` |
| `a ∼ b` | `$a \sim b$` |
| `a ∝ b` | `$a \propto b$` |

**I-5. 集合与逻辑符号**

| 原文 | 修复 |
|------|------|
| `x ∈ S` | `$x \in S$` |
| `x ∉ S` | `$x \notin S$` |
| `A ⊂ B` | `$A \subset B$` |
| `A ⊆ B` | `$A \subseteq B$` |
| `A ∪ B` | `$A \cup B$` |
| `A ∩ B` | `$A \cap B$` |
| `∀x` | `$\forall x$` |
| `∃x` | `$\exists x$` |

**I-6. 箭头**

| 原文 | 修复 | 说明 |
|------|------|------|
| `f: A → B` | `$f: A \to B$` | 函数映射 |
| `x ↦ y` | `$x \mapsto y$` | 元素映射 |
| `A ⇒ B` | `$A \Rightarrow B$` | 蕴含 |
| `A ⇔ B` | `$A \Leftrightarrow B$` | 等价 |
| 表头 `→` | 保留 Unicode | 表格格式化 |

**I-7. 其他常见符号**

| 原文 | 修复 |
|------|------|
| `∞` | `$\infty$` |
| `∂f/∂x` | `$\partial f / \partial x$` |
| `∇f` | `$\nabla f$` |
| `√x` | `$\sqrt{x}$` |

> **判断边界**：与变量/数字/等号紧邻 → 转 `$...$`；维度 `2 × 2`、表格箭头 → 保留。表头 `| **i** |` → 保留。

> **NBSP 陷阱**：Wikipedia 公式常用 `\xa0`（non-breaking space），精确文本匹配时 `**i\xa0⋅\xa0j**` 可能被漏掉，需额外检查。

辅助扫描（可选）：

```bash
"<python路径>" "{项目根目录}/.web2md_tools/find_all_missed.py" "{md文件路径}"
```

#### 收尾验证（`final_verify.py`）

```bash
"<python路径>" "{项目根目录}/.web2md_tools/final_verify.py" "{md文件路径}"
```

确认：`\_` 清零、`\*` 清零、`\\` 行断完整、`\left\{` 未破坏、`$$` 独占一行、LLM 清单全部打勾。

### 第五步：输出

告知用户文件路径，用 Typora 打开即可。

---

## 各项目固定文件

- `.web2md_tools/web2md.py` — 主抓取脚本
- `.web2md_tools/fix_escapes.py` — 阶段 A：`\_` `\*` 修复
- `.web2md_tools/list_display_fixes.py` — 阶段 B：列出 `$`→`$$` 候选
- `.web2md_tools/find_all_missed.py` — 阶段 C：伪公式扫描
- `.web2md_tools/final_verify.py` — 收尾验证
- `.web2md_tools/intermediate/` — LLM 清单 `fix_list_roundN.md`
- `.claude/settings.local.json` — 记录 Python 路径（`env.WEB2MD_PYTHON`），每个项目各自记住

### 目录结构规范

`.web2md_tools/` 顶层只放可复用的核心脚本，一次性调试/诊断脚本放入 `_archive/`：

```
.web2md_tools/
├── web2md.py              ← 主抓取
├── fix_escapes.py          ← 阶段 A：\_ \* 修复
├── list_display_fixes.py   ← 阶段 B：$→$$ 候选列表
├── find_all_missed.py      ← 阶段 C：伪公式扫描
├── final_verify.py         ← 收尾验证
├── intermediate/           ← LLM 清单 fix_list_roundN.md
└── _archive/               ← 调试脚本、临时测试等一次性文件
```

- 项目根目录禁止散放 `.py` / `.txt` / `.json`（除 `.claude/` 外）
- LLM 生成的中间清单 → `intermediate/`
- 非复用的一次性脚本 → `_archive/`

---

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
- **即使用脚本执行替换，判断必须由 Claude 做**——`**i**` → `$\mathbf{i}$` 这类转换，脚本只能做精确的 `str.replace`（Claude 手写每一条 old→new 对），不能用正则或自动判断。区分「表格粗体」和「数学符号粗体」是上下文理解，脚本做不到
- **脚本只做机械操作，Claude 审核全部**——脚本负责 `\_` → `_`、`\*` → `*`、`$$` 独占一行等机械修改。但这些修改可能出错（修漏、修错、修坏）——Claude 必须通读全文，逐一验证每个公式是否渲染正确，包括脚本改过的和没改过的。不以「脚本已处理过」为由跳过，质量优先，不省 token

## Python 脚本（嵌入式）

以下脚本是 `web2md.py` 的完整内容。首次在某个项目执行时，如果 `.web2md_tools/web2md.py` 不存在，则写入，之后保留复用。

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

---

## 辅助脚本（嵌入式）

以下四个脚本随主脚本 `web2md.py` 一起写入 `.web2md_tools/`，每个项目初次使用时检查并写入。

### fix_escapes.py（阶段 A）

```python
"""Fix \_ -> _ and \* -> * inside $...$ and $$...$$ blocks.
Do NOT touch \{ \} (legitimate LaTeX)."""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1]
with open(fpath, 'r', encoding='utf-8') as f:
    text = f.read()

BS = chr(92)
before_us = text.count(BS + '_')
before_st = text.count(BS + '*')

def fix_block(m):
    content = m.group(0)
    content = content.replace(BS + '_', '_')
    content = content.replace(BS + '*', '*')
    return content

# Fix display math ($$...$$)
text = re.sub(r'\$\$[\s\S]*?\$\$', fix_block, text)
# Fix inline math ($...$, max 2000 chars to avoid dangling $)
text = re.sub(r'\$[^$]{1,2000}\$', fix_block, text)
# Global fallback for any remaining
text = text.replace(BS + '_', '_')
text = text.replace(BS + '*', '*')

after_us = text.count(BS + '_')
after_st = text.count(BS + '*')
left_brace = text.count(r'\left{')
print(f'\\_: {before_us} -> {after_us} ({before_us - after_us} replaced)')
print(f'\\*: {before_st} -> {after_st} ({before_st - after_st} replaced)')
print(f'\\left{{ (broken): {left_brace}')

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(text)
print('Saved.')
```

### list_display_fixes.py（阶段 B）

```python
"""List inline $ formulas that should be $$ display math."""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1]
with open(fpath, 'r', encoding='utf-8') as f:
    text = f.read()

# Find $$...$$ spans
display_spans = [(m.start(), m.end()) for m in re.finditer(r'\$\$[\s\S]*?\$\$', text)]

def inside_display(pos):
    for s, e in display_spans:
        if s <= pos < e:
            return True
    return False

needs_display = []
for m in re.finditer(r'\$[^$]{1,2000}\$', text):
    if inside_display(m.start()):
        continue
    inner = m.group()[1:-1]
    line = text[:m.start()].count('\n') + 1
    reasons = []

    envs = re.findall(r'\\begin\{([^}]+)\}', inner)
    if envs:
        reasons.append('begin:' + ','.join(envs))
    if re.search(r'\\\\[a-zA-Z\[]', inner):
        reasons.append('multi-line')
    n = len(inner)
    if n > 200:
        reasons.append('len=' + str(n))

    if reasons:
        needs_display.append((line, inner, reasons))

print('Formulas that need $ -> $$ : ' + str(len(needs_display)))
print()
for line, inner, reasons in needs_display:
    rstr = ' | '.join(reasons)
    snippet = inner[:120].replace('\n', ' ')
    print('Line ' + str(line) + ': ' + rstr)
    print('  ' + snippet + '...')
    print()
```

### find_all_missed.py（阶段 C 辅助）

```python
"""Find ALL remaining *x* and **x** patterns that look like math variables.
Usage: python find_all_missed.py <markdown_file>"""
import re, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1]
with open(fpath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

italic_math = re.compile(
    r'\*[a-zA-Z]\*(?:[0-9]+|(?:\xa0)?[⋅×+\-\=]|(?:\xa0)?\*\*[ijk]\*\*)'
)
bold_math = re.compile(
    r'\*\*[ijk]\*\*(?:[0-9]+|(?:\xa0)?[⋅×+\-\=])'
)

for i, line in enumerate(lines):
    lineno = i + 1
    stripped = line.strip()
    if not stripped:
        continue
    if stripped.startswith('|') or stripped.startswith('#'):
        continue
    if stripped.startswith('$$') or stripped.startswith('>'):
        continue
    if stripped.startswith('!['):
        continue

    clean = re.sub(r'\$\$[\s\S]*?\$\$', '', stripped)
    clean = re.sub(r'\$[^$]+?\$', '', clean)

    im = italic_math.findall(clean)
    bm = bold_math.findall(clean)

    if im or bm:
        print(f'Line {lineno}:')
        if im:
            print(f'  italic: {im}')
        if bm:
            print(f'  bold:   {bm}')
        print(f'  text:   {clean[:150]}')
        print()
```

### final_verify.py（收尾验证）

```python
"""Final verification: check \\ _ & are all correct."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

fpath = sys.argv[1] if len(sys.argv) > 1 else None
if fpath is None:
    print('Usage: python final_verify.py <markdown_file>')
    sys.exit(1)

with open(fpath, 'rb') as f:
    raw = f.read()

text = raw.decode('utf-8', errors='replace')
BS = chr(92)

# 1. Escaped underscores
esc_underscore = text.count(BS + '_')
print(f'[{"OK" if esc_underscore == 0 else "FAIL"}] Escaped underscores: {esc_underscore}')

# 2. Escaped asterisks
esc_star = text.count(BS + '*')
print(f'[{"OK" if esc_star == 0 else "FAIL"}] Escaped asterisks: {esc_star}')

# 3. Check for broken \left{ (missing backslash)
left_broken = text.count(chr(92) + 'left{')
print(f'[{"OK" if left_broken == 0 else "FAIL"}] \\left{{ (broken): {left_broken}')

# 4. Check each aligned formula
all_ok = True
for m in re.finditer(r'\\begin\{aligned\}', text):
    start = text.rfind('$', 0, m.start())
    end = text.find('$', m.end())
    if start >= 0 and end >= 0:
        formula = text[start:end+1]
        line = text[:m.start()].count('\n') + 1

        line_breaks = formula.count(BS + BS)
        amp_count = formula.count('&')

        bad = 0
        pos = 0
        while True:
            pos = formula.find(BS + '{', pos)
            if pos < 0:
                break
            prev = formula[pos-1] if pos > 0 else ''
            if prev == BS:
                pos += 2
                continue
            if prev.isalpha():
                pos += 1
                continue
            bad += 1
            pos += 1

        status = 'OK' if bad == 0 else 'FAIL (' + str(bad) + ' broken)'
        if bad > 0:
            all_ok = False
        print(f'Line {line}: \\\\={line_breaks}, &=&={amp_count}, broken={bad} [{status}]')

if all_ok:
    print('\nAll formulas pass!')
else:
    print('\nSome formulas still have issues.')
```
