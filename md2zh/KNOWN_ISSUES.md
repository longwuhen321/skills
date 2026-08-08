# KNOWN_ISSUES — 已知问题与修复记录

> 排查需修改 `scripts/*.py` 的问题时读取本文件。
> 如何追加：新条目直接复制文件顶部的【追加模板】（HTML 注释块），把模板替换为本次
> 修复内容即可——模板所在位置就是插入位置（最新条目之前），无需理解结构。
> 条目按时间倒序排列（新 → 旧）：最新修复在最前，紧随模板之后（排查时最先看到最近修复）。
> 不删除旧条目。

---

<!-- ============================ 追加模板（新修复记录写在这里） ============================
如何追加：把本注释块整体复制到它所在的位置（即「历史条目」列表顶部、最新条目之前），
将下方占位内容替换为本次修复的实际内容。条目按时间倒序（新 → 旧），最新条目在最前。
日期用系统当前时间：
Windows: Get-Date -Format "yyyy-MM-dd"；Linux/macOS: date +%F
===========================================================================

## [YYYY-MM-DD] 问题简述
- **现象**：...
- **根因**：...
- **修复**：`scripts/xxx.py` 何处、怎么改
- **排查方法**：下次如何快速定位/验证

============================================================================
追加模板结束——复制时删除上方/下方的分隔注释与本说明，只保留替换后的正式条目
============================================================================ -->

## [2026-08-03] 含弯引号的目录名在 PowerShell 双引号字符串中被误解析（已知行为）

- **现象**：`NSH “Built-In” Applications` 这类含弯引号（`“”`）的目录路径放进 PowerShell 双引号字符串（`"$outRoot\NSH “Built-In” Applications\..."`）时报 `ParserError: UnexpectedToken`，`New-Item`/`Copy-Item` 失败。
- **根因**：PowerShell 把 `“` `”` 也当作字符串定界符，弯引号内容被拆成位置参数。
- **修复**：无脚本改动（环境行为）。执行约定：含弯引号的路径拼接用**单引号字符串 + 变量拼接**（`$outRoot + '\NSH “Built-In” Applications\...'`）；已写入 SKILL.md「翻译执行注意事项」。
- **排查方法**：PowerShell 报 `UnexpectedToken`/`PositionalParameterNotFound` 且路径含中文弯引号时即此类。

## [2026-08-03] cleanup-run 拒绝清理：state 不在任务目录内（已知行为）

- **现象**：`cleanup-run` 报 `refusing to clean an invalid block run path`，任务目录残留无法自动清理。
- **根因**：`md2zh_pipeline.py` `cleanup_run` 校验 `path_is_within(state_path, task_dir)`——state.json 放在任务目录外（如系统 TEMP）时校验失败；只有 state/blocks 等中间产物位于 `<skill-directory>/debug/intermediate/<task-id>/` 内才允许清理。
- **修复**：执行约定：extract 的 `--state`/`--blocks` 放任务目录内（`intermediate/<task>/`），随任务清理；已写入 SKILL.md「翻译执行注意事项」。
- **排查方法**：cleanup 报 `invalid block run path` 时检查 state 文件路径是否在 `<task-id>/` 内（`manifest.state_path`）。

## [2026-08-03] validate-block 报 "introduced Markdown syntax"：译文引入反斜杠/转义字符（已知行为）

- **现象**：译文含字面 `\`（如经 PowerShell 写入的 `\u201c`）时 validate 报 `unit-xxxx introduced Markdown syntax outside protected markers`。
- **根因**：`validate_no_introduced_syntax` 检查译文是否引入原文没有的 Markdown 语法字符（`\`、`*`、`[` `]` 等）。PowerShell 双引号字符串不解析 `\uXXXX` 转义，`\u201c` 以字面 6 字符写入文件 → 反斜杠被判定为新语法。
- **修复**：执行约定：译文用中文引号（`“”`）直接书写，不写 `\u` 转义；`apply_translations.py` 用 utf-8-sig 读映射（容错 BOM）；已写入 SKILL.md「翻译执行注意事项」。
- **排查方法**：validate 报 `introduced Markdown syntax` 时，检查译文内容行的反斜杠来源（shell 转义 vs 原文保护标记）。

## [2026-08-03] validate-block 报 "empty translation"：SEG 内容行译文为空（已知行为）

- **现象**：某内容行映射为空字符串时 validate 报 `unit-xxxx has an empty translation`。
- **根因**：`parse_block_surface`/`validate_block` 契约要求每个 SEG 内容行都有非空译文——空译文会被视为契约违规（防止翻译丢行）。
- **修复**：执行约定：每个 SEG 内容行**必须有译文**（无可见文本的块直接复制 input 为 output，不写空映射）；已写入 SKILL.md「翻译执行注意事项」。
- **排查方法**：validate 报 `empty translation` 时查对应 SEG 号的内容行是否被映射为空串。

---

（更多条目待追加：遇到非一次性错误并修复后，按顶部模板追加。）
