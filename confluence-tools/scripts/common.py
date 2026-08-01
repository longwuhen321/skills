"""
通用工具函数模块

所有脚本共用的配置加载、路径推导、HTTP 重试、页面收集等。新增脚本只需：
    from common import SKILL_ROOT, load_config, request_with_retry, collect_space_pages
    cfg = load_config()
"""

import os
import sys
import time

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SKILL_ROOT, 'scripts', 'config.py')

# 所有 HTTP 请求的默认超时（秒），防网络挂起卡死脚本
DEFAULT_TIMEOUT = 30


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


def collect_space_pages(session, base_url, space_key, headers=None, page_size=200):
    """分页拉取空间内全部页面元数据，返回 [(id, title, version), ...]

    供 md_import（标题内存匹配）与 math_upgrade（空间批量升级）共用。
    空间页数多时可能触发 429，已内置重试。
    """
    if not space_key:
        print("❌ 空间 Key 为空，无法收集页面")
        return []
    all_pages = []
    start = 0
    url = f"{base_url}/rest/api/content"
    while True:
        params = {
            'spaceKey': space_key,
            'type': 'page',
            'limit': page_size,
            'start': start,
            'expand': 'version',
        }
        resp = request_with_retry(session, 'GET', url, params=params, headers=headers,
                                  retry_on=(429, 500, 502, 503, 504))
        resp.raise_for_status()
        results = resp.json().get('results', [])
        if not results:
            break
        all_pages.extend(
            (r['id'], r['title'], r['version']['number']) for r in results)
        start += page_size
    return all_pages


def load_config():
    """从 scripts/config.py 读取配置，返回 dict

    配置文件定义了四个分组字典：
        common_config   — 通用（url、token、python_path 等）
        import_config   — md_import 专属（space）
        upgrade_config  — math_upgrade 专属（对齐、递归、页面等）
        debug_config    — 调试日志（阈值、保留数）

    返回值即为这四个 dict 组成的 dict，脚本按需取用。
    缺失文件时报错退出并引导用户首次配置。
    """
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 找不到配置文件: {CONFIG_PATH}")
        print("   请先运行 /confluence-tools 完成首次配置")
        print("   或手动复制 config.example.py → scripts/config.py 后填入真实值")
        sys.exit(1)

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            exec(f.read(), ns := {})
    except Exception as e:
        print(f"❌ 配置文件读取失败: {e}")
        sys.exit(1)

    # 组装为嵌套 dict
    common = ns.get('common_config', {})
    if not common.get('confluence_url') or not common.get('confluence_token'):
        print("❌ common_config 缺少 confluence_url 或 confluence_token")
        print("   请先运行 /confluence-tools 完成首次配置")
        sys.exit(1)

    # 环境变量覆盖真实凭据（优先于 config.py），共享机器/CI 上可不落盘 token
    env_token = os.environ.get('CONFLUENCE_TOKEN')
    if env_token:
        common['confluence_token'] = env_token

    return {
        'common_config': common,
        'import_config': ns.get('import_config', {}),
        'upgrade_config': ns.get('upgrade_config', {}),
        'debug_config': ns.get('debug_config', {}),
    }
