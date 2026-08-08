# ============================================================
# web2md — 配置模板
# ============================================================
# 使用方式：
#   1. 复制本文件到 scripts/config.py
#   2. 将占位符替换为真实值
#   3. scripts/config.py 不提交到 git（已在 .gitignore 中排除）
#
# 配置分组说明：
#   web2md_config — 通用配置（所有脚本共用）
# ============================================================


# ==================== 通用配置 ====================
web2md_config = {
    # Python 解释器的完整路径。AI 助手使用此路径执行所有 skill 脚本。
    # 可以是系统 Python、conda 环境或 venv 中的 python.exe。
    "python_path": "/path/to/your/python",

    # 抓取页面的请求代理（HTTP/HTTPS 请求统一使用）。
    # 空字符串 "" = 不显式配置，交给 requests 自动读取环境变量（HTTP_PROXY/HTTPS_PROXY）。
    # 非空 = 显式配置，优先于环境变量（单一配置源，避免双源漂移）。
    # 仅支持 http:// 形式（如 "http://127.0.0.1:7890"）；socks5:// 需要 PySocks 未安装会报错。
    # AI 判断通道（web_fetch 失败时的核实脚本）同样从本配置读取代理。
    "proxy": "",

    # 抓取页面的请求超时（秒），防网络挂起卡死脚本。
    "timeout": 30,

    # 是否在抓取页面时收集导航子页面（解析侧边栏 toctree，含子/孙页面）。
    # true = 额外抓取当前页面在导航树下的子页面并嵌套落盘；false = 只抓当前页面（默认）。
    # 可被 CLI 参数 --children / --no-children 覆盖。
    "collect_children": False,

    # 是否在转换后合并段落内的源码硬换行（普通段落合并为一行，列表项续行并入首行）。
    # 适用于 HTML 源码硬换行把自然段切碎的站点（多为自定义站点；Sphinx/GitBook 通常不触发）。
    # true = 合并；false = 保留源码换行（默认）。可被 CLI 参数 --merge-paragraphs 覆盖。
    "merge_paragraphs": False,

    # 是否把表格单元格（<td>/<th>）内的显示公式 \[...\] 行内化为 $...$（默认 true）。
    # markdown 表格单元格无法容纳 $$ 块（独占行 + 空行会撕裂表格），行内化让公式留在
    # 单元格内；含 \\ 行断的多行公式由 AI 按 custom-site-rules.md §2 的 aligned 化规则改写。
    # true = 行内化（默认）；false = 保持显示公式转换（表格可能被撕裂，需 AI 重建）。
    # 可被 CLI 参数 --table-formula-inline / --no-table-formula-inline 覆盖。
    "table_formula_inline": True,

    # 是否在抓取到子/孙页面时，于父页面 md 末尾追加 Sub-pages 导航块（默认 true）。
    # 导航块按 children_list / 导航解析顺序列出子页面（孙页面嵌套缩进），链接为本地
    # 相对路径（路径含空格时用 < > 包裹，final_verify 链接正则要求）。
    # true = 追加（默认）；false = 不追加。可被 CLI 参数 --page-nav / --no-page-nav 覆盖。
    "page_nav": True,
}
