# ============================================================
# Confluence 工具集 — 配置模板
# ============================================================
# 使用方式：
#   1. 复制本文件到 scripts/config.py
#   2. 将占位符替换为真实值
#   3. scripts/config.py 不提交到 git（已在 .gitignore 中排除）
#
# 配置分组说明：
#   common_config      — 通用配置（四个页面脚本共用）
#   import_config      — md_import 专属配置
#   upgrade_config     — math_upgrade 专属配置
#   toc_upgrade_config — toc_upgrade 专属配置
#   export_config      — md_export 专属配置
#   debug_config       — 调试日志配置（共用）
# ============================================================


# ==================== 通用配置 ====================
common_config = {
    # 标题内行内公式的存储方式：
    #   "literal"    = 保留 $...$（Confluence 9.2.1 目录宏推荐，默认）
    #   "mathinline" = 转为原生 mathinline 宏（供其他版本/插件环境使用）
    "heading_math_mode": "literal",

    # Python 解释器的完整路径。AI 助手使用此路径执行所有 skill 脚本。
    # 可以是系统 Python、conda 环境或 venv 中的 python.exe。
    "python_path": "/path/to/your/python",

    # Confluence 服务器基础 URL，不要以 / 结尾。
    "confluence_url": "http://your-confluence-server:8090",

    # 登录用户名，仅用于标识记录，不参与 API 认证（认证由 confluence_token 完成）。
    "confluence_user": "your-username",

    # Personal Access Token (PAT)。
    # Confluence → 个人设置 → 创建和管理 Personal Access Tokens
    "confluence_token": "<your-personal-access-token>",
}


# ==================== md_import 配置 ====================
import_config = {
    # 导入页面时的默认空间 Key。可被 --space 参数覆盖。
    "space": "ALG",

    # 公式对齐方式："left" = 左对齐（原生 mathblock + alignment=left），"center" = 居中（mathblock）。
    # 与 math_upgrade 的 upgrade_config.math_align 保持一致。可被 --align 参数覆盖。
    "math_align": "left",

    # 默认父页面 ID：导入的页面挂为该页面的子页面。留空 = 不挂父级（页面建在空间根）。
    # 仅对新建页面生效（页面已存在时按标题更新，位置不变）。可被 --parent-id 参数覆盖。
    "default_parent_id": "",

    # 默认页面标题。留空 = 取 md 文件名（不含扩展名）。可被 --page-name 参数覆盖。
    "default_page_name": "",

    # 是否启用 --dir 批量树导入功能（文件夹层级 → Confluence 页面层级）。
    # 首次运行配置向导时明确询问，由用户确定是否开启。
    # 开启后可用 md_import.py --dir <根文件夹> 导入整棵树（创建/更新/移动多个页面）；
    # 未开启时使用 --dir 会报错提示（防误用）。
    "tree_import": False,

    # --dir 树导入命中已有页面的处理方式（仅树导入生效）：
    #   "confirm" = 存在需移动层级的页面时先输出预览并暂停，每次执行都等用户确认（默认，安全）
    #   "auto"    = 不确认，直接更新并移动到正确层级
    #   "off"     = 不移动：命中只更新内容，页面位置不变
    # 可被 --fix-hierarchy confirm|auto|off 参数覆盖。
    "fix_hierarchy": "confirm",

    # 自动目录宏：子标题（H2~H6）数量达到 toc_min_headings 时，自动在页面正文顶部
    # 插入 Confluence 目录宏（toc）。toc_enabled=False 关闭此功能。
    "toc_enabled": True,
    "toc_min_headings": 4,

    # 上传前 Markdown 预审（默认开启）：生成审核副本并完成 LaTeX、附件路径、
    # storage XHTML 与公式宏数量验证；只上传验证通过的副本，不修改源文件。
    "preflight_review": True,
}


# ==================== math_upgrade 配置 ====================
upgrade_config = {
    # 默认目标页面 ID。设了之后不传 --page-id 也能直接跑。
    # 留空表示每次必须通过 CLI 指定。
    "default_page": "",

    # 空间模式（不传 --page-id 时）的默认空间 Key。
    "space": "ES",

    # 公式对齐方式："left" = 左对齐（原生 mathblock + alignment=left），"center" = 居中（mathblock）。
    # 可被 --align 参数覆盖。
    "math_align": "left",

    # 验证通过后是否自动更新页面。False = 仅生成 debug 文件不提交。
    # 可被 --no-auto-update 参数覆盖。
    "auto_update": True,

    # 是否转换后暂停等待人工验证。True = 生成 debug 后停止，等 AI 助手审核后 --confirm 提交。
    # 可被 --ai-verify / --no-ai-verify 参数覆盖。
    "ai_verify": False,

    # 指定 --page-id 时默认是否递归处理子页面。
    # 可被 --recursive / --no-recursive 参数覆盖。
    "recursive": True,

    # 递归最大层级，0 = 不限制。可被 --max-depth 参数覆盖。
    "max_depth": 0,
}


# ==================== toc_upgrade 配置 ====================
toc_upgrade_config = {
    # 转换后的目标宏：
    #   "easy_heading" = 将原生“目录”(toc) 宏转换为 Easy Heading Macro
    #   "toc"          = 将 Easy Heading Macro 转换为原生“目录”(toc) 宏
    # 可被 --target easy_heading|toc 覆盖。
    "target_macro": "easy_heading",

    # 默认目标页面 ID。留空时必须通过 --page-id 或 --space 指定范围。
    "default_page": "",

    # 空间模式的默认空间 Key。留空表示不默认执行空间批量修改。
    "space": "",

    # 指定页面时，默认是否同时处理该页面的全部子页面（不限制层级）。
    # 可被 --recursive / --no-recursive 覆盖。
    "recursive": False,

    # 验证通过后是否自动更新。False = 只生成 debug 文件，不提交。
    # 可被 --no-auto-update 覆盖。
    "auto_update": True,

    # 是否生成 debug 后暂停，等待 --confirm 确认提交。
    # 可被 --ai-verify / --no-ai-verify 覆盖。
    "ai_verify": False,

    # 仅在“toc → Easy Heading”新建宏时使用；页面中已有 Easy Heading
    # 宏时保留原参数，不用这里的值覆盖。适配截图中的 Easy Heading Macro 3.6.3；
    # 前三项取自参考页面 68223008，隐藏侧边目录项按本次需求默认开启。
    "macro_parameters": {
        # 点击标题是否展开/折叠对应内容。可选："true" / "false"。
        "titleExpandClickable": "true",

        # 插件内部编辑标记。参考页面值为 "true"，建议保持不变。
        "hiddenEditedFlag": "true",

        # 目录树默认展开策略。可选：
        # "expand-all-by-default"、"collapse-all-by-default"、
        # "collapse-all-but-headings-1"、"collapse-all-but-headings-1-2"、
        # "collapse-all-but-headings-1-3"、"collapse-all-but-headings-1-4"、
        # "disable-expand-collapse"。
        "navigationExpandOption": "expand-all-by-default",

        # 是否默认隐藏侧边目录，鼠标悬停时显示。可选："true" / "false"。
        "useNavigationHiddenMode": "true",

        # 常用可选项（按需取消注释）：
        # 参与目录的标题层级；只能由 h1~h6 组成，以英文逗号分隔。
        # "selector": "h1,h2,h3",
        # 目录文字是否自动换行。可选："true" / "false"。
        # "wrapNavigationText": "false",
        # 自定义目录标题，不能为空。
        # "navigationTitle": "目录",
    },
}


# ==================== md_export 配置 ====================
export_config = {
    # 默认导出输出根目录（相对当前工作目录；也支持绝对路径，如 "D:/out"；
    # 可被 --output 参数覆盖）。
    "output_dir": "confluence_export",

    # --page-id 时默认是否递归导出子页面（可被 --recursive / --no-recursive 覆盖）。
    "recursive": True,

    # 空间模式（--space 未传时）的默认空间 Key。
    "space": "",
}


# ==================== 调试日志 ====================
debug_config = {
    # 调试日志总大小超过此阈值（MB）时自动清理最旧的目录。
    "max_size_mb": 50,

    # 自动清理时至少保留最近 N 个时间戳子目录。
    "keep_recent": 20,
}
