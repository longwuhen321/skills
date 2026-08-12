# Markdown 导入流程

## 强制读取条件

执行 `md_import.py` 的单页导入、文件夹树导入或断点恢复前，必须完整读取本文件。
读取后先向用户说明：“已读取 `references/md-import-workflow.md`，将按导入范围、
预审、页面消歧和并发保护规则执行。”

## 命令入口

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" "<md文件>" [--page-id ID] [--parent-id ID] [--page-name NAME] [--space KEY] [--align left|center] [--force] [--preflight-review|--no-preflight-review]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" --dir "<根文件夹>" [--space KEY] [--align left|center] [--fix-hierarchy confirm|auto|off] [--plan-only] [--yes] [--force] [--preflight-review|--no-preflight-review]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" --resume "<tree_plan.json>" [--yes] [--force]
```

## 通用流程

1. 使用用户指定的 Markdown 文件或目录，并直接读取 `import_config`；不重复询问配置已有值。
2. 用户主动指定 `--space`、`--parent-id`、`--page-id`、`--page-name`、`--align`
   等参数时覆盖配置；不得自行推断更窄或更宽范围。
3. 先计算最终 `preflight_review`。开启时，按 `SKILL.md` 的直接路由，在任何远端写入前
   同时完整读取 `md-import-preflight-rules.md`，预审全部待写文件；只上传验证通过的审核副本，
   不修改源文件，附件仍按源 Markdown 目录解析。关闭时明确提示风险。
4. 任一必要页面、附件或树节点失败时，整体命令返回非零；不得把部分成功报告为全部成功。

## 页面定位与并发

- `--page-id` 是精确选择器。否则按空间 + 标题查找；`--parent-id` 同时参与同名消歧。
- 查询严格返回 `FOUND`、`NOT_FOUND` 或 `ERROR`。只有 `NOT_FOUND` 可以新建；
  同名多候选、分页失败、API 异常均为 `ERROR`，禁止猜测或误建。
- 新建页面时 `default_parent_id` 或 `--parent-id` 决定父级；更新已有页面时位置默认不变。
- 更新提交使用查询时取得的源版本。409 默认失败；仅用户明确要求并传 `--force` 时，
  才拉取最新版本重试一次。
- 图片上传失败时保留原始引用、汇总失败项，并将页面或树节点标记为失败。
- `data:` URI 不作为本地附件上传，保留原始引用并汇总提示。

## Markdown 与 storage 规则

- 独占一行的 `[toc]` 转为一个原生 `toc` 宏；自动插入前先检查是否已有目录宏。
- H2～H6 数量达到 `toc_min_headings` 且 `toc_enabled=true` 时，才自动插入目录宏。
- 标题 H1～H6 按 `common_config.heading_math_mode` 处理：`literal` 保留 `$...$`，
  `mathinline` 使用原生行内宏；正文公式仍按导入转换规则处理。
- Confluence storage 必须保持 XHTML 合法；代码、公式、宏和 CDATA 先保护再转换，
  `<br>` / `<hr>` 使用自闭合形式。

## 文件夹树导入

- 每个含 `.md` 的文件夹是一个页面；优先使用与文件夹同名的 `.md`；子文件夹是子页面，
  `.assets/` 只作为附件源；没有 `.md` 的中间文件夹跳级。
- 流程：扫描建树 → 一次拉取空间索引 → 生成只读计划 → 处理移动确认 → 父先子后执行。
- 计划固化 page ID 和 version；同一 page ID 被多个节点命中时整批拒绝。
- `fix_hierarchy=confirm`：存在移动时每次展示计划并等待确认；`auto`：直接移动；
  `off`：更新正文但不移动。
- `--plan-only` 只生成计划；`--yes` 可跳过重复确认。
- 每个成功节点都更新 `tree_plan.json`。中断后用 `--resume` 跳过已完成节点；
  恢复模式启动时不得先清理日志，以免检查点在读取前被删除。
- 树导入开启预审时，必须先验证全部待写页面；任何一个预审失败时零远端写入。

## 完成检查

- 报告页面 ID、版本以及成功/失败汇总。
- 树导入核对页面数量和父子关系；附件失败不得隐藏。
- 真实测试只操作明确授权的测试页面，完成后按精确 ID 删除。
