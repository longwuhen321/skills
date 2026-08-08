#!/usr/bin/env python3
"""nav_children - 导航子/孙页面收集（多策略识别 + 汇总供 AI 判断）。

设计思路（为什么这么分层）
==========================
导航收集要回答一个问题：**当前页面在导航树下的直接子页面（含孙页面）是谁？**
它对所有文档主题成立的不变量是：

    「导航树里必然有一个链接指向当前页面（否则用户无法从导航进入该页）」

所以识别分三步，全部基于这个不变量，与具体主题解耦：
  1. 定位 current_a —— 遍历导航链接，URL 规范化后与当前页 URL 匹配，命中即当前节点；
  2. 找容器 —— current_a 所在项（li/section/div.item）内的嵌套导航容器（ul/div.items）；
  3. 收集 —— 容器内其他链接按层级（子=1，孙=2）挂载，过滤同页锚点/外部站点/重复。

多主题差异只出现在「当前项如何标记」与「容器用什么标签」上：
  - Sphinx 经典 / Furo：当前项链接带完整页面 URL（li.current + 正常 href）；
  - Sphinx RTD（Read the Docs）：当前项链接是 href="#" 占位（靠 li.current class 标记）；
  - VitePress：当前项链接带完整 URL，容器是 div.item / section.level-N。

因此这里采用「基座 + 策略」分层：
  - 通用基座（本文件下半部分）：URL 规范化、current_a 定位、容器查找、层级判定、去重——
    只写一遍，所有策略共用；
  - 策略函数（strategy_*）：只写「差异」——特征检测 + current_a 微调参数，返回收集结果；
  - 汇总（collect_children）：顺序跑全部策略，输出 structure / children / notes。

**如何扩展新主题**：新增一个 strategy_xxx(soup, base_url) 函数（特征检测 + 调用基座），
把它追加进 STRATEGIES 列表即可，无需改基座。
收集空结果时 notes 会带诊断（检测到的结构特征、导航链接样例、空原因），AI 助手
据此判断「真没有」还是「漏识别」，不需要再访问页面。

踩坑记录（为什么基座有 allow_hash_current 参数）
================================================
2026-08-08 回归：为挡 VitePress 布局锚点（#VPContent 干扰 current_a 定位）曾一刀切
跳过所有 href 以 '#' 开头的链接——结果误杀 Sphinx RTD 主题的当前项占位 href="#"，
导致 nuttx.apache.org 等 RTD 站点报「无严格导航子页面」（实测 8-02 旧逻辑在相同
DOM 上能完整识别 9 个子页面）。因此定位时必须区分：
  - href_raw == '#'        —— RTD 当前项占位（经 urljoin 后 == 当前页 URL）→ 参与定位；
  - href_raw.startswith('#') 且非 '#'（如 #VPContent）—— 页面内锚点 → 绝不参与定位。
"""

import re
import re
import re
from urllib.parse import urljoin, urlsplit

# ---------------------------------------------------------------------------
# 通用基座
# ---------------------------------------------------------------------------


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


def _is_descendant_of(elm, ancestor):
    """elm 是否位于 ancestor 子树内"""
    n = elm.parent
    while n is not None:
        if n is ancestor:
            return True
        n = n.parent
    return False


def _find_container(current_a):
    """current_a 所在的子页面导航容器。

    - Sphinx 嵌套结构：current_a 在 li/section 里 → 其内的嵌套 ul / div.items 为子页面。
    - VitePress 分组结构：current_a 在 div.item 里 → 所在 section（level-N）内的
      其他 div.item 链接即子页面，返回该 section。
    - 无子页面容器（叶子页面、顶层平铺页面——导航树中的相邻链接只是兄弟页面或
      整棵文档树）返回 None，调用方视为无导航子页面。
    """
    parent = current_a.parent
    if parent is not None and parent.name == 'div' and 'item' in (parent.get('class') or []):
        node = parent.parent
        while node is not None:
            if node.name == 'section':
                if any(l is not current_a for l in node.find_all('a', href=True)):
                    return node
                return None
            node = node.parent
        return None
    node = parent
    while node is not None:
        name = getattr(node, 'name', None)
        if name in ('li', 'section'):
            for sub in node.find_all('ul'):
                if not _is_descendant_of(current_a, sub) and sub.find('a', href=True):
                    return sub
            for sub in node.find_all('div'):
                cls = sub.get('class', []) if hasattr(sub, 'get') else []
                if 'items' in cls and not _is_descendant_of(current_a, sub) and sub.find('a', href=True):
                    return sub
            return None
        node = node.parent
    return None


def _nav_level(a, container):
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


def _item_section(a, container):
    """a 的「项容器」（孙页面挂载锚点）。

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


def _collect_base(soup, base_url, allow_hash_current):
    """通用子/孙页面收集（所有策略共用），返回 (children, notes)。

    allow_hash_current: 是否允许 href="#"（RTD 当前项占位）参与 current_a 定位。
      - Sphinx RTD 等主题需要（当前项链接是 href="#" 占位）；
      - VitePress 必须禁止（布局锚点 #VPContent 等纯锚点会干扰定位，见模块头踩坑记录）。

    notes 是给 AI 助手的诊断信息（结构特征、空原因、链接样例），空结果时尤其重要——
    AI 据此判断「真没有子页面」还是「漏识别」，无需再访问页面。
    """
    notes = []
    current_a = None
    base_norm = _norm_nav_url(base_url)
    base_stripped = _strip_fragment(base_norm)
    for a in soup.find_all('a', href=True):
        href_raw = a.get('href', '').strip()
        # 纯锚点链接（#VPContent、#章节标题等）不参与当前节点定位——
        # 它们去 fragment 后与当前页 URL 相同，会把 current_a 误定位到布局/正文锚点。
        # 唯一例外：RTD 当前项占位 href="#"（allow_hash_current 时）——它经 urljoin
        # 后就是当前页 URL，正是我们要找的导航当前项。
        if href_raw.startswith(('#', 'javascript:', 'mailto:')):
            if href_raw == '#' and allow_hash_current:
                href = _norm_nav_url(urljoin(base_url, href_raw))
                if _strip_fragment(href) == base_stripped:
                    current_a = a
                    break
            continue
        href = _norm_nav_url(urljoin(base_url, href_raw))
        if _strip_fragment(href) == base_stripped:
            current_a = a
            break
    if current_a is None:
        notes.append('未定位到当前页导航链接（current_a=None）；若是 RTD 主题可能被 href="#" 占位挡住，'
                     '或导航链接形式与页面 URL 不匹配')
        return [], notes

    # 子页面容器：current_a 所在项（li/section）内的嵌套导航 ul/div.items。
    # 无嵌套容器说明当前页面是叶子页或顶层平铺页（导航树中的相邻链接是兄弟页面或
    # 整棵文档树，不是子页面），视为无导航子页面。
    container = _find_container(current_a)
    if container is None:
        notes.append('当前页导航项内无嵌套子页面容器——可能是叶子页/顶层平铺页（无子页面），'
                     '或导航结构未被识别')
        return [], notes
    notes.append(f'当前页导航项（{current_a.get_text(strip=True)[:40] or "无标题"}）'
                 f'定位成功，容器=<{container.name}>')

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
        d = _nav_level(a, container)
        if d == 1:
            items1.append((a, title, href))
        elif d == 2:
            items2.append((a, title, href))

    result = []
    for a1, t1, u1 in items1:
        sec1 = _item_section(a1, container)
        kids = []
        if sec1 is not None:
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
    if not result:
        notes.append('容器内未收集到合格子页面（全部被同页锚点/外部/重复过滤）')
    return result, notes


# ---------------------------------------------------------------------------
# 策略层（每种主题一个，只写「差异」；新增主题追加函数 + 注册进 STRATEGIES）
# ---------------------------------------------------------------------------

def strategy_sphinx(soup, base_url):
    """Sphinx 文档（Read the Docs / Furo / 经典主题等）。

    特征：meta[generator] 含 Sphinx/Docutils，或存在 li.toctree-* / a.headerlink。
    当前项标记：
      - 经典 / Furo：链接带完整页面 URL → 基座默认路径直接命中；
      - RTD：当前项链接是 href="#" 占位（li.current class 标记）→ 必须允许纯占位参与定位。
    子页面容器：li/section 内嵌套 ul（_find_container Sphinx 分支）。
    """
    generator = soup.find('meta', attrs={'name': re.compile(r'^generator$', re.I)})
    content = generator.get('content', '') if generator else ''
    is_sphinx = 'sphinx' in content.lower() or 'docutils' in content.lower() \
        or soup.select_one('li[class*="toctree"]') is not None \
        or soup.select_one('a.headerlink') is not None
    if not is_sphinx:
        return None, None, '特征未命中（无 Sphinx generator / toctree / headerlink）'
    children, notes = _collect_base(soup, base_url, allow_hash_current=True)
    return 'sphinx', children, notes


def strategy_vitepress(soup, base_url):
    """VitePress 文档（docs.px4.io 等）。

    特征：VPSidebar 结构（div.VPSidebar / div.item / section.level-N）。
    当前项标记：链接带完整 URL（router-link-active class）→ 基座默认路径命中；
      必须禁止 href="#" 参与定位（布局锚点 #VPContent 干扰，见模块头踩坑记录）。
    子页面容器：div.item 所在 section（_find_container VitePress 分支）。
    """
    is_vitepress = soup.select_one('div.VPSidebar') is not None \
        or soup.select_one('div.item') is not None \
        or soup.select_one('section[class*="level-"]') is not None
    if not is_vitepress:
        return None, None, '特征未命中（无 VPSidebar / div.item / section.level-*）'
    children, notes = _collect_base(soup, base_url, allow_hash_current=False)
    return 'vitepress', children, notes


STRATEGIES = [
    strategy_sphinx,
    strategy_vitepress,
    # 新增主题在此追加：strategy_gitbook(soup, base_url) 等
]


# ---------------------------------------------------------------------------
# 汇总入口（web2md.py 唯一调用点）
# ---------------------------------------------------------------------------

def collect_children(soup, base_url):
    """解析侧边栏导航 toctree，返回当前页面节点下的子/孙页面。

    返回 dict（与旧版返回 list 不同，2026-08-08 重构）：
      {
        'structure': 'sphinx' | 'vitepress' | 'unknown',   # 命中的策略名
        'children': [{'title', 'url', 'children': [...]}],  # 子/孙页面（深度 ≤ 2）
        'notes': [str, ...],                                # 诊断信息（供 AI 助手判断）
      }

    找不到当前节点 / 无子页面容器时 children 为空（此时视为无导航子页面），
    notes 会说明「为什么空」——AI 据此判断是真没有还是漏识别。

    实现与具体标签解耦（兼容 Sphinx 的 li/ul 与 VitePress 的 div/section）：
      - 定位 current_a 后，向上找最近"还包含其他链接"的祖先作容器
      - 子/孙层级按 a 与容器之间经过的 li/section 层数判定（当前页=0，子=1，孙=2）
    """
    notes = []
    for strategy in STRATEGIES:
        structure, children, strategy_notes = strategy(soup, base_url)
        if strategy_notes:
            notes.append(f'[{structure or "?"}] ' + '；'.join(strategy_notes))
        if children is not None:
            # 命中策略：children 可能是空 list（真无子页面）或含子页面
            return {
                'structure': structure,
                'children': children,
                'notes': notes,
            }
    # 所有策略都未命中特征（无 generator / toctree / VPSidebar 等标记的裸导航页面，
    # 多为手写 HTML 或精简测试结构）→ 按通用 li/ul 导航兜底收集。
    # allow_hash_current=True 是安全的：current_a 定位只有 href_raw == '#'（RTD 占位）
    # 且 urljoin 后等于当前页才命中，布局锚点（#VPContent 等）被 == '#' 判据天然排除。
    children, base_notes = _collect_base(soup, base_url, allow_hash_current=True)
    notes.append('[generic] 未命中任何主题特征，按通用 li/ul 导航收集（' + '；'.join(base_notes) + '）')
    return {'structure': 'generic', 'children': children, 'notes': notes}
