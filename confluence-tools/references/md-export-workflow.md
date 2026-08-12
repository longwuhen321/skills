# Markdown 导出流程

## 强制读取条件

执行 `md_export.py` 的单页、页面树或空间导出前，必须完整读取本文件。
读取后先向用户说明：“已读取 `references/md-export-workflow.md`，将按分页、附件和安全路径规则执行。”

## 命令入口

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py" --page-id <ID> [--recursive|--no-recursive] [--output <目录>]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py" --space <KEY> [--output <目录>]
```

## 转换结果

- `mathblock` → `$$...$$`，`mathinline` → `$...$`，兼容旧 mathjax 宏。
- code 宏 → 语言围栏；`toc` → 独占一行的 `[toc]`；note/info/warning → 引用块。
- 未知宏保留可读正文，并附带 HTML 转义的原始 Confluence XHTML 注释；
  注释中的 `--` 转为 `&#45;&#45;`。
- `ri:url`、外链图片和未知宏正文中的独立 URL 保留。
- 代码、公式、目录宏使用占位符穿过正文空行规范化；代码恢复后禁止再次全局整理空行。

## 输出结构

```text
<输出根>/
└── <页面ID>_<页面标题>/
    ├── <页面标题>.md
    ├── <页面标题>.assets/        # 页面有附件图片时才创建
    └── <子页面ID>_<子页面标题>/  # 递归导出时保留层级
        └── <子页面标题>.md
```

- 页面目录包含稳定 page ID，避免同名覆盖。
- 页面标题和附件名移除路径字符、尾随点/空格；Windows 保留名加安全前缀。
- 附件文件名使用附件 ID + basename，并验证解析路径仍在页面 assets 目录内。
- 下载失败时在 Markdown 保留说明，并使整体任务返回失败。

## 范围和分页

- `--page-id`：导出单页；`--recursive` 时递归导出后代并嵌套目录。
- `--space`：空间索引已经包含全部页面，按平铺方式每页导出一次；不得对每页再次递归。
- 页面、子页面和附件列表必须通过公共分页器拉取全量；HTTP 或 JSON 错误直接失败，
  不把截断结果当作成功。
- `--output` 覆盖 `export_config.output_dir`；支持相对和绝对路径。
- 每页原始 storage 保存到 `logs/export/`，用于诊断但不代替导出结果校验。

