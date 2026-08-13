"""
通用工具函数模块

所有脚本共用的配置加载、路径推导、HTTP 重试、页面收集等。新增脚本只需：
    from common import SKILL_ROOT, load_config, request_with_retry, collect_space_pages
    cfg = load_config()
"""

import html
import os
import re
import sys
import time
import uuid
from urllib.parse import urljoin

from config_parser import ConfigParseError, parse_config_text

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_ROOT, 'scripts', 'config.py')

# 所有 HTTP 请求的默认超时（秒），防网络挂起卡死脚本
DEFAULT_TIMEOUT = 30
HEADING_MATH_MODES = ('literal', 'mathinline')
TOC_TARGETS = ('easy_heading', 'toc')
TOC_MACRO = 'toc'
EASY_HEADING_MACRO = 'easy-heading-free'
TOC_BOOLEAN_PARAMETERS = {
    'titleExpandClickable',
    'useNavigationHiddenMode',
    'wrapNavigationText',
}
TOC_NAVIGATION_EXPAND_OPTIONS = {
    'expand-all-by-default',
    'collapse-all-by-default',
    'collapse-all-but-headings-1',
    'collapse-all-but-headings-1-2',
    'collapse-all-but-headings-1-3',
    'collapse-all-but-headings-1-4',
    'disable-expand-collapse',
}
TOC_ALLOWED_PARAMETERS = TOC_BOOLEAN_PARAMETERS | {
    'hiddenEditedFlag',
    'navigationExpandOption',
    'selector',
    'navigationTitle',
}


class MacroConversionError(ValueError):
    """目录宏结构或配置不满足安全转换条件。"""


def get_toc_target_macro(common_config, legacy_toc_config=None):
    """读取导入与目录升级共用的目标宏，并兼容旧配置键。"""
    target = common_config.get('toc_target_macro')
    if target is None and legacy_toc_config is not None:
        target = legacy_toc_config.get('target_macro')
    if target is None:
        target = 'easy_heading'
    if target not in TOC_TARGETS:
        allowed = ' 或 '.join(TOC_TARGETS)
        raise MacroConversionError(
            f'common_config.toc_target_macro 必须是 {allowed}')
    return target


def validate_toc_macro_parameters(parameters):
    """严格校验 Easy Heading 创建参数，并返回保序副本。"""
    if not isinstance(parameters, dict):
        raise MacroConversionError('macro_parameters 必须是字典')
    unknown = set(parameters) - TOC_ALLOWED_PARAMETERS
    if unknown:
        raise MacroConversionError(
            '不支持的 Easy Heading 参数: ' + ', '.join(sorted(unknown)))
    for key, value in parameters.items():
        if not isinstance(value, str):
            raise MacroConversionError(f'macro_parameters.{key} 必须是字符串')
        if key in TOC_BOOLEAN_PARAMETERS and value not in ('true', 'false'):
            raise MacroConversionError(
                f'macro_parameters.{key} 只能是 "true" 或 "false"')
    if ('hiddenEditedFlag' in parameters
            and parameters['hiddenEditedFlag'] != 'true'):
        raise MacroConversionError(
            'macro_parameters.hiddenEditedFlag 是插件内部标记，只支持 "true"')
    expand = parameters.get('navigationExpandOption')
    if expand is not None and expand not in TOC_NAVIGATION_EXPAND_OPTIONS:
        raise MacroConversionError(
            'macro_parameters.navigationExpandOption 取值无效')
    selector = parameters.get('selector')
    if selector is not None:
        headings = [item.strip() for item in selector.split(',')]
        if (not headings or any(not re.fullmatch(r'h[1-6]', item)
                                for item in headings)
                or len(set(headings)) != len(headings)):
            raise MacroConversionError(
                'macro_parameters.selector 只能是不重复的 h1~h6，以英文逗号分隔')
    if 'navigationTitle' in parameters and not parameters['navigationTitle'].strip():
        raise MacroConversionError('macro_parameters.navigationTitle 不能为空')
    return dict(parameters)


def build_toc_macro(target_macro, macro_parameters):
    """按通用配置生成一个新的原生 TOC 或 Easy Heading 宏。"""
    if target_macro not in TOC_TARGETS:
        allowed = ' 或 '.join(TOC_TARGETS)
        raise MacroConversionError(f'target_macro 必须是 {allowed}')
    parameters = validate_toc_macro_parameters(macro_parameters)
    macro_id = uuid.uuid4()
    if target_macro == 'toc':
        return (
            '<ac:structured-macro ac:name="toc" ac:schema-version="1" '
            f'ac:macro-id="{macro_id}"/>')
    parts = [
        '<ac:structured-macro ac:name="easy-heading-free" '
        f'ac:schema-version="1" ac:macro-id="{macro_id}">'
    ]
    for key, value in parameters.items():
        parts.append(
            f'<ac:parameter ac:name="{key}">{html.escape(value)}</ac:parameter>')
    parts.append('</ac:structured-macro>')
    return ''.join(parts)


def contains_toc_macro(storage_html):
    """判断正文是否已有原生 TOC 或 Easy Heading，忽略 CDATA 与注释。"""
    visible = re.sub(r'<!\[CDATA\[.*?\]\]>|<!--.*?-->', '', storage_html,
                     flags=re.DOTALL)
    return bool(re.search(
        r'<ac:structured-macro\b[^>]*ac:name=["\'](?:toc|easy-heading-free)["\']',
        visible, flags=re.IGNORECASE))


def get_heading_math_mode(common_config: dict) -> str:
    """读取并严格校验标题公式存储模式。"""
    mode = common_config.get('heading_math_mode', 'literal')
    if mode not in HEADING_MATH_MODES:
        allowed = ', '.join(HEADING_MATH_MODES)
        raise ValueError(
            f"common_config.heading_math_mode 无效: {mode!r}；可选值: {allowed}")
    return mode


def build_block_template(align: str) -> str:
    """根据对齐配置生成块级公式宏模板

    left 用原生 mathblock + alignment=left（Confluence 9.2.1 实例实测支持），
    center 用默认 mathblock（无 alignment 参数 = 居中）。
    md_import / math_upgrade 共用。
    """
    if align == 'left':
        return (
            '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
            '<ac:parameter ac:name="alignment">left</ac:parameter>'
            '<ac:plain-text-body><![CDATA[{content}]]></ac:plain-text-body>'
            '</ac:structured-macro>'
        )
    return (
        '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
        '<ac:plain-text-body><![CDATA[{content}]]></ac:plain-text-body>'
        '</ac:structured-macro>'
    )


def compile_inline_math_pattern(allow_raw_angle_brackets=False,
                                allow_markdown_emphasis=False):
    """编译统一行内公式规则：接受 ``$x$`` 或 ``$ x $``。

    空格必须两侧对称，因而不会把 ``$PWD / $OLDPWD`` 的两个变量跨配成
    公式。storage HTML 场景默认禁止裸 ``< >``，Markdown 保护阶段可显式
    放开，以便 ``$ 0<x<\\pi $`` 在 markdown2 转义前得到保护。
    """
    if allow_raw_angle_brackets:
        content_char = r'[^$\n]'
        edge_char = r'[^$\s]'
    elif allow_markdown_emphasis:
        content_char = r'(?:[^$<>\n]|<em>|</em>)'
        edge_char = r'(?:[^$<>\s]|<em>|</em>)'
    else:
        content_char = r'[^$<>\n]'
        edge_char = r'[^$<>\s]'
    spaced_left_boundary = r'(?<![A-Za-z0-9_\\}])'
    spaced_right_boundary = r'(?![A-Za-z0-9_\\{])'
    return re.compile(
        r'(?<![\\$])(?:'
        rf'\$(?P<tight>(?![\s$]){content_char}+?(?<![$\s]))(?<!\\)\$|'
        + spaced_left_boundary
        + rf'\$[ \t]+(?P<spaced>{edge_char}(?:{content_char}*?{edge_char})?)[ \t]+(?<!\\)\$'
        + spaced_right_boundary
        + r')(?!\$)')


def inline_math_content(match, repair_markdown_emphasis=False) -> str:
    """从统一行内公式匹配中取出规范化公式正文。"""
    content = (match.group('tight') or match.group('spaced')).strip()
    if repair_markdown_emphasis:
        content = re.sub(r'</?em>', '_', content, flags=re.IGNORECASE)
    return content


def check_xhtml_balance(storage_html: str):
    """检查 storage XHTML 标签配对，返回 ``(ok, 描述)``。"""
    protected = re.sub(r'<!\[CDATA\[.*?\]\]>', '', storage_html,
                       flags=re.DOTALL)
    protected = re.sub(r'<!--.*?-->', '', protected, flags=re.DOTALL)
    stack = []
    void_tags = {'br', 'hr', 'img', 'meta', 'input', 'link', 'area',
                 'base', 'col', 'embed', 'source', 'track', 'wbr'}
    for match in re.finditer(
            r'</?([a-zA-Z][a-zA-Z0-9:_-]*)(?:\s[^>]*?)?/?>', protected):
        tag, raw = match.group(1), match.group(0)
        if raw.startswith('</'):
            if not stack or stack[-1] != tag:
                return False, f"多余闭合 </{tag}>（位置 {match.start()}）"
            stack.pop()
        elif raw.endswith('/>') or tag in void_tags:
            continue
        else:
            stack.append(tag)
    if stack:
        return False, f"未闭合标签: {stack[-5:]}"
    return True, "标签配对 OK"


def normalize_heading_inline_math(storage_html: str, mode='literal'):
    """按配置统一标题内行内公式，返回 ``(新内容, 变更数量)``。

    ``literal`` 将 mathinline/旧 mathjax 行内宏还原为 ``$...$``；
    ``mathinline`` 将标题中的 ``$...$`` 和旧宏统一为原生 mathinline。
    这里只处理 h1-h6，正文公式保持不变。
    """
    if mode not in HEADING_MATH_MODES:
        allowed = ', '.join(HEADING_MATH_MODES)
        raise ValueError(f"heading_math_mode 无效: {mode!r}；可选值: {allowed}")
    macro_pattern = re.compile(
        r'<ac:structured-macro\b'
        r'(?=[^>]*\bac:name=["\'](?:mathinline|mathjax-inline-macro)["\'])'
        r'[^>]*>.*?</ac:structured-macro>', re.DOTALL)
    parameter_pattern = re.compile(
        r'<ac:parameter\b'
        r'(?=[^>]*\bac:name=["\'](?:body|equation)["\'])'
        r'[^>]*>(.*?)</ac:parameter>', re.DOTALL)
    restored = 0

    def mathinline_macro(content):
        clean = content.replace(r'\*', '*')
        escaped = clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return (
            '<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
            f'<ac:parameter ac:name="body">{escaped}</ac:parameter>'
            '</ac:structured-macro>')

    inline_pattern = compile_inline_math_pattern(allow_markdown_emphasis=True)

    def replace_heading(match):
        nonlocal restored

        def replace_macro(macro_match):
            nonlocal restored
            parameter = parameter_pattern.search(macro_match.group(0))
            if not parameter:
                return macro_match.group(0)
            name = re.search(
                r'\bac:name=["\']([^"\']+)["\']', macro_match.group(0)).group(1)
            if mode == 'mathinline' and name == 'mathinline':
                return macro_match.group(0)
            body = re.sub(r'&amp;(lt|gt|amp);', r'&\1;', parameter.group(1))
            restored += 1
            if mode == 'literal':
                return f'${body}$'
            return mathinline_macro(body)

        opening, body, closing = match.groups()
        body = macro_pattern.sub(replace_macro, body)
        parts = []
        last = 0
        for macro in macro_pattern.finditer(body):
            text = body[last:macro.start()]

            def replace_literal(literal_match):
                nonlocal restored
                content = inline_math_content(
                    literal_match, repair_markdown_emphasis=True)
                replacement = (mathinline_macro(content) if mode == 'mathinline'
                               else f'${content}$')
                if replacement != literal_match.group(0):
                    restored += 1
                return replacement

            parts.append(inline_pattern.sub(replace_literal, text))
            parts.append(macro.group(0))
            last = macro.end()
        tail = body[last:]

        def replace_literal_tail(literal_match):
            nonlocal restored
            content = inline_math_content(
                literal_match, repair_markdown_emphasis=True)
            replacement = (mathinline_macro(content) if mode == 'mathinline'
                           else f'${content}$')
            if replacement != literal_match.group(0):
                restored += 1
            return replacement

        parts.append(inline_pattern.sub(replace_literal_tail, tail))
        body = ''.join(parts)
        return opening + body + closing

    heading_pattern = re.compile(
        r'(<h[1-6]\b[^>]*>)(.*?)(</h[1-6]>)', re.DOTALL | re.IGNORECASE)
    return heading_pattern.sub(replace_heading, storage_html), restored


def request_with_retry(session, method, url, max_retries=3, timeout=DEFAULT_TIMEOUT,
                       retry_on=(429,), **kwargs):
    """带状态码重试的 HTTP 请求封装

    批量操作可能触发 429 限流（Server/DC 官方未提供限流文档，此为防御性重试）；
    瞬时 5xx（500/502/503/504）也建议重试，见各 GET 调用处。
    指数退避重试，优先尊重响应头 Retry-After。
    重试耗尽后返回最后一次响应，由调用方 raise_for_status 处理。

    注意：写操作（POST/PUT）不要传 5xx，避免非幂等请求被重复执行。
    """
    for attempt in range(max_retries):
        resp = session.request(method, url, timeout=timeout, **kwargs)
        if resp.status_code not in retry_on:
            return resp
        delay = 2 ** attempt
        try:
            delay = int(resp.headers.get('Retry-After', delay))
        except (ValueError, TypeError):
            pass
        print(f"⚠️ HTTP {resp.status_code}，{delay}s 后重试（第 {attempt + 1}/{max_retries} 次）")
        time.sleep(delay)
    return resp


def collect_paginated_results(session, url, *, base_url=None, params=None,
                              headers=None, page_size=200):
    """Fetch every ``results`` page and propagate request/JSON errors.

    Confluence endpoints vary: newer responses expose ``_links.next`` while
    older ones require ``start``/``limit`` pagination until an empty page.
    """
    all_results = []
    request_url = url
    request_params = dict(params or {})
    request_params.setdefault('limit', page_size)
    request_params.setdefault('start', 0)
    fallback_start = int(request_params['start'])
    while True:
        resp = request_with_retry(
            session, 'GET', request_url, params=request_params or None,
            headers=headers, retry_on=(429, 500, 502, 503, 504))
        resp.raise_for_status()
        data = resp.json()
        results = data.get('results')
        if not isinstance(results, list):
            raise ValueError(f"分页响应缺少 results 列表: {request_url}")
        all_results.extend(results)

        links = data.get('_links')
        next_link = links.get('next') if isinstance(links, dict) else None
        if next_link:
            request_url = urljoin(base_url or request_url, next_link)
            request_params = None
            continue
        if isinstance(links, dict) or not results:
            break

        limit = int(request_params.get('limit', page_size))
        fallback_start += limit
        request_params = dict(params or {})
        request_params['limit'] = limit
        request_params['start'] = fallback_start
    return all_results


def collect_space_page_records(session, base_url, space_key, headers=None,
                               page_size=200):
    """Return complete page records including direct parent metadata."""
    if not space_key:
        raise ValueError('空间 Key 为空，无法收集页面')
    rows = collect_paginated_results(
        session, f"{base_url}/rest/api/content", base_url=base_url,
        headers=headers, page_size=page_size,
        params={
            'spaceKey': space_key,
            'type': 'page',
            'expand': 'version,ancestors',
            'limit': page_size,
        })
    records = []
    for row in rows:
        ancestors = row.get('ancestors') or []
        records.append({
            'id': str(row['id']),
            'title': row['title'],
            'version': row['version']['number'],
            'parent_id': str(ancestors[-1]['id']) if ancestors else None,
        })
    return records


def collect_space_pages(session, base_url, space_key, headers=None, page_size=200):
    """分页拉取空间内全部页面元数据，返回 [(id, title, version), ...]

    供 md_import（标题内存匹配）与 math_upgrade（空间批量升级）共用。
    空间页数多时可能触发 429，已内置重试。
    """
    records = collect_space_page_records(
        session, base_url, space_key, headers=headers, page_size=page_size)
    return [(row['id'], row['title'], row['version']) for row in records]


def fetch_page(session, base_url, page_id, expand='body.storage,version,space'):
    """拉取单个页面详情（storage 正文 + 版本 + 空间），返回 dict

    md_export / math_upgrade 共用。429 与瞬时 5xx 自动重试。
    返回键：page_id / title / version / space_key / storage / raw
    """
    url = f"{base_url}/rest/api/content/{page_id}"
    params = {'expand': expand}
    resp = request_with_retry(session, 'GET', url, params=params,
                              retry_on=(429, 500, 502, 503, 504))
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


def update_page_storage(session, base_url, page_info, new_storage):
    """以源页面版本为基准更新 storage，返回更新后的版本号。"""
    url = f"{base_url}/rest/api/content/{page_info['page_id']}"
    new_version = page_info['version'] + 1
    payload = {
        'version': {'number': new_version},
        'title': page_info['title'],
        'type': 'page',
        'space': {'key': page_info['space_key']},
        'body': {
            'storage': {
                'value': new_storage,
                'representation': 'storage',
            }
        },
    }
    response = request_with_retry(session, 'PUT', url, json=payload)
    if not response.ok:
        print(f"  PUT 失败 ({response.status_code}): {response.text[:500]}")
    response.raise_for_status()
    return new_version


def get_child_pages(session, base_url, page_id):
    """分页读取直属子页面，返回 ``[(id, title), ...]``。"""
    url = f"{base_url}/rest/api/content/{page_id}/child/page"
    rows = collect_paginated_results(
        session, url, base_url=base_url,
        params={'limit': 200, 'expand': 'version'})
    return [(str(row['id']), row['title']) for row in rows]


def collect_page_tree(session, base_url, root_id, max_depth=0):
    """广度优先收集根页面及其子页面；``max_depth=0`` 表示不限层级。"""
    response = request_with_retry(
        session, 'GET', f"{base_url}/rest/api/content/{root_id}",
        params={'expand': 'version'}, retry_on=(429, 500, 502, 503, 504))
    response.raise_for_status()
    queue = [(str(root_id), response.json()['title'], 0)]
    result = []
    seen = set()
    while queue:
        page_id, title, depth = queue.pop(0)
        if max_depth and depth > max_depth:
            continue
        if page_id in seen:
            continue
        seen.add(page_id)
        result.append((page_id, title, depth))
        for child_id, child_title in get_child_pages(
                session, base_url, page_id):
            queue.append((child_id, child_title, depth + 1))
    return result


def load_config():
    """从 scripts/config.py 读取配置，返回 dict

    配置文件定义了六个分组字典：
        common_config   — 通用（url、token、python_path 等）
        import_config   — md_import 专属（space）
        upgrade_config  — math_upgrade 专属（对齐、递归、页面等）
        toc_upgrade_config — toc_upgrade 专属（目标宏、范围、Easy 参数）
        export_config   — md_export 专属（输出目录、递归、空间）
        debug_config    — 调试日志（阈值、保留数）

    返回值即为这六个 dict 组成的 dict，脚本按需取用。
    缺失文件时报错退出并引导用户首次配置。
    """
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 找不到配置文件: {CONFIG_PATH}")
        print("   请先运行 $confluence-tools 完成首次配置")
        print("   或手动复制 config.example.py → scripts/config.py 后填入真实值")
        sys.exit(1)

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            ns = parse_config_text(f.read())
    except (OSError, ConfigParseError) as e:
        print(f"❌ 配置文件读取失败: {e}")
        sys.exit(1)

    # 组装为嵌套 dict
    common = ns.get('common_config', {})

    # 环境变量覆盖真实凭据（优先于 config.py），共享机器/CI 上可不落盘 token
    env_token = os.environ.get('CONFLUENCE_TOKEN')
    effective_token = env_token or common.get('confluence_token')
    if not common.get('confluence_url') or not effective_token:
        print("❌ common_config 缺少 confluence_url 或 confluence_token")
        print("   请先运行 $confluence-tools 完成首次配置")
        sys.exit(1)

    if env_token:
        common['confluence_token'] = env_token

    return {
        'common_config': common,
        'import_config': ns.get('import_config', {}),
        'upgrade_config': ns.get('upgrade_config', {}),
        'toc_upgrade_config': ns.get('toc_upgrade_config', {}),
        'export_config': ns.get('export_config', {}),
        'debug_config': ns.get('debug_config', {}),
    }
