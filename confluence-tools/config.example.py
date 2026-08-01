# ============================================================
# Confluence 工具集 — 配置模板
# ============================================================
# 使用方式：
#   1. 复制本文件到 scripts/config.py
#   2. 将占位符替换为真实值
#   3. scripts/config.py 不提交到 git（已在 .gitignore 中排除）
#
# 配置分组说明：
#   common_config      — 通用配置（两个脚本共用）
#   import_config      — md_import 专属配置
#   upgrade_config     — math_upgrade 专属配置
#   debug_config       — 调试日志配置（共用）
# ============================================================


# ==================== 通用配置 ====================
common_config = {
    # Python 解释器的完整路径。Claude 使用此路径执行所有 skill 脚本。
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

    # 是否转换后暂停等待人工验证。True = 生成 debug 后停止，等 Claude 审核后 --confirm 提交。
    # 可被 --claude-verify / --no-claude-verify 参数覆盖。
    "claude_verify": False,

    # 指定 --page-id 时默认是否递归处理子页面。
    # 可被 --recursive / --no-recursive 参数覆盖。
    "recursive": True,

    # 递归最大层级，0 = 不限制。可被 --max-depth 参数覆盖。
    "max_depth": 0,
}


# ==================== 调试日志 ====================
debug_config = {
    # 调试日志总大小超过此阈值（MB）时自动清理最旧的目录。
    "max_size_mb": 50,

    # 自动清理时至少保留最近 N 个时间戳子目录。
    "keep_recent": 20,
}
