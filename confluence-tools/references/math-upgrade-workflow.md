# 数学公式升级流程

## 强制读取条件

执行 `math_upgrade.py` 的单页、页面树、空间升级或 `--confirm` 前，必须完整读取本文件。
读取后先向用户说明：“已读取 `references/math-upgrade-workflow.md`，将按公式零残留、
版本和内容哈希保护规则执行。”

## 命令入口

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> [--align left|center] [--ai-verify]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> --recursive [--max-depth N]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --space <KEY>
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --confirm <debug目录|latest>
```

## 范围与参数

- `--page-id`：单页；配合 `--recursive` 处理页面树；`--max-depth 0` 表示不限。
- `--space`：处理空间内全部页面，每个页面只处理一次。
- `--align left`：每个 `mathblock` 使用唯一 `alignment=left`；已有值替换为 left。
- `--align center`：删除已有 alignment 参数，使用原生居中默认值。
- `--no-auto-update`：只生成 debug，不提交。
- `--ai-verify`：机械验证通过后等待人工确认；不能绕过 XHTML、宏数量或残留门禁。
- `--stop-on-error`：批量遇错即停；默认继续并在末尾汇总失败页面。
- `--allow-math-residuals`：显式允许残留并报告 `类型@行:列`；默认任何残留均失败。

## 转换与确认安全

- 转换必须幂等：内容已达目标状态时不 PUT、不增加版本。
- 默认要求正文中 `$...$`、`$$...$$` 和 latex 围栏零残留。
- 标题公式读取 `common_config.heading_math_mode`：`literal` 保留标题字面公式并只在
  完整标题范围内豁免残留；`mathinline` 把标题字面公式和旧行内宏统一为原生行内宏。
- `--confirm` 使用 debug 中的 page ID、源版本和源 SHA256，重新拉取当前页面；
  版本或正文任一变化都拒绝提交旧 `after.html`，没有 `--force` 绕过。
- 批量中任一页面验证、拉取或 PUT 失败，最终退出码必须非零。
- 真实空间升级前确认范围；真实测试页在验证后按精确 ID 删除，不触碰其他页面。

