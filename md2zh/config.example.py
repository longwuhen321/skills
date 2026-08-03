# ============================================================
# md2zh — 配置模板
# ============================================================
# 使用方式：
#   1. 复制本文件到 scripts/config.py
#   2. 将占位符替换为真实值
#   3. scripts/config.py 不提交到 git（已在 .gitignore 中排除）
# ============================================================


# ==================== md2zh 配置 ====================
md2zh_config = {
    # Python 解释器的完整路径。AI 助手使用此路径执行 scripts/md2zh_pipeline.py。
    # 可以是系统 Python、conda 环境或 venv 中的 python.exe。
    "python_path": "/path/to/your/python",
}

# 说明：
# - 翻译项目级配置（{项目根}/.md2zh_tools/config.json：ambiguous_content_decider=user|ai、
#   python-mode=auto|explicit）由 pipeline 的 configure 子命令管理，不在此配置。
# - 分块数量、块大小等由 pipeline 自动按文档结构调整，无需配置。
