---
name: md2zh
description: 将英文 Markdown 分块翻译为简体中文，通过 pipeline 字节级保护格式、公式、代码和链接；仅在用户显式调用 $md2zh 时使用
---

# md2zh — Markdown 翻译为中文

把指定英文 `.md` 翻译为简体中文，同时保持 Markdown 结构及受保护内容不变。
单文件默认输出 `<stem>_zh.md`；目录树按判定规则输出镜像树。源文件始终只读。

## 触发与契约

- **仅显式调用**：只有用户使用 `$md2zh` 时执行；一般翻译讨论不触发。
- 假定源 Markdown 正确，不验证、修复、规范化或重排源文件。
- 当前 AI 助手只翻译 pipeline 暴露的块表面；**不得直接编辑完整 Markdown**。
- 不把文档正文发送给外部机器翻译服务，也不启动嵌套代理或独立模型会话，除非用户明确要求。
- 最终输出和 `.assets` 不得静默覆盖、合并或替换已有不同内容。

## 强制协议与直接路由

先确定任务类型，再直接读取下表文件；不得通过一个参考文件寻找另一个必读文件。
读取完成后，在执行脚本、翻译内容或修改文件前公开回执。

| 情形 | 继续前必须读取 |
|---|---|
| 任何单文件或树形翻译 | [translation-rules.md](references/translation-rules.md) 与 [translation-quality.md](references/translation-quality.md)（完整） |
| 首次配置、配置损坏、解释器无效、同步失败或改配置键 | [configuration-guide.md](references/configuration-guide.md)（完整） |
| state 含 `ambiguous_region` | [ambiguous-content-workflow.md](references/ambiguous-content-workflow.md)（完整） |
| 目录含至少两个翻译任务且启用树形翻译 | [tree-translation-workflow.md](references/tree-translation-workflow.md)（完整） |
| 修改任何 skill 文件 | [../SKILL_MODIFICATION_STANDARD.md](../SKILL_MODIFICATION_STANDARD.md) 与 [maintenance-rules.md](references/maintenance-rules.md)（完整） |
| 修改或新增 `scripts/*.py` | [../SKILL_MODIFICATION_STANDARD.md](../SKILL_MODIFICATION_STANDARD.md)、[maintenance-rules.md](references/maintenance-rules.md) 与 [script-development-rules.md](references/script-development-rules.md)（完整） |
| 排查或修复 bug | [../SKILL_MODIFICATION_STANDARD.md](../SKILL_MODIFICATION_STANDARD.md)、[maintenance-rules.md](references/maintenance-rules.md) 与 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)；涉及脚本时再完整读取 [script-development-rules.md](references/script-development-rules.md) |
| 优化、重构或扩展 | [../SKILL_MODIFICATION_STANDARD.md](../SKILL_MODIFICATION_STANDARD.md)、[maintenance-rules.md](references/maintenance-rules.md) 与 [OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md)；涉及脚本时再完整读取 [script-development-rules.md](references/script-development-rules.md) |

回执使用：

```text
任务类型：<单文件/树形/配置/维护>
已完整读取：<路由命中的文件>
输入范围：<源文件或目录>
输出边界：<目标位置、覆盖与外部服务约束>
```

未命中的条件性参考不预读；路由文件缺失、无法完整读取或规则冲突时停止并报告。

## 1. 环境与模式门禁

确认以下共享文件存在：

```text
scripts/md2zh_pipeline.py      scripts/config_literal.py
scripts/check_config_sync.py   scripts/scan_visible.py
scripts/apply_translations.py  scripts/package_check.py
```

缺失或损坏时不要直接重写或恢复；先报告，用户确认后才按 git 状态处理。

读取 `scripts/config.py` 的 `python_path`，用同一解释器执行：

```powershell
& "<python>" "<skill-directory>/scripts/check_config_sync.py"
```

退出码 `0` 才能继续；`1/2`、配置缺失/损坏或解释器无效时停止，并按配置路由处理。
pipeline 会把解释器写入 state，后续阶段必须继续使用同一 Python。

按可翻译任务数选择模式：

| 输入 | 模式 |
|---|---|
| 单个 `.md` | 单文件 |
| 目录内只有一个可翻译 `.md`（忽略 `.assets/`） | 单文件 |
| 目录内至少两个任务且 `tree_translation=true` | 树形；完整读取树形工作流 |
| 目录内至少两个任务且 `tree_translation=false` | 停止，请用户指定单个文件 |

## 2. 单文件 pipeline

把所有中间文件放入 `<skill-directory>/logs/intermediate/<task-id>/`；其中
`run/` 保存 manifest 和块文件，任务根保存 state、summary、glossary、candidate 与 review。

### 2.1 提取与结构计划

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" extract "<源.md>" `
  --state "<state.json>" --blocks "<blocks.json>" --project-root "<项目根>"
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" summarize `
  "<state.json>" "<summary.md>"
```

- state 是重建元数据，不暴露、不翻译、不移出当前 task-id。
- 单文件默认在 state 同级创建或复用 `glossary.json`。
- 通读 summary 的标题树、保护区间和默认分块方案，确认后才继续。
- 若 state 含模糊区域，完整读取模糊内容工作流并记录全部决策。

### 2.2 建立分块运行

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" plan-blocks `
  "<state.json>" "<task-id>/run"
```

manifest 绑定源哈希与分块指纹；重跑只复用同一计划下已接受且产物仍存在的块。

### 2.3 逐块翻译

1. 完整读取翻译规则和质量标准，再读取全部 `*.input.txt` 与当前 `glossary.json`。
2. 新术语写入增量 JSON，并通过 `update-glossary <state.json> <增量.json>` 合并；
   冲突译法完成上下文复核后才可使用 `--replace`。
3. 使用 `scan_visible.py` 检查可见段，用 `apply_translations.py` 生成对应 `*.output.txt`；
   不编写临时替换脚本。
4. 保持每个 `@@MD2ZH:SEG:...@@` 行原样且顺序不变；每个
   `@@MD2ZH:PROTECT:...@@` 恰好一次，配对关系不交叉。
5. 只翻译标记后的可见文字。段内可重排和换行，但译文非空、首尾无换行、
   不含空白段，任何行不得新引入块级 Markdown 标记。
6. 直接以 UTF-8 写入输出文件；禁止用 shell 管道、here-string 或 `Add-Content` 传输译文。

### 2.4 逐块验证

第一块写完后立即验证，通过后再处理其余块：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" validate-block `
  "<state.json>" "<manifest.json>" block-0001
```

单块最多初始尝试加两轮修正；失败只重做该块，已接受块不重启。
AI 复检需要修改 accepted 块时显式追加 `--replace-accepted`。

### 2.5 合并、渲染与验证

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" merge-blocks `
  "<state.json>" "<manifest.json>" "<translations.json>"
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" render `
  "<state.json>" "<translations.json>" "<candidate.md>"
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" verify `
  "<state.json>" "<translations.json>" "<candidate.md>"
```

存在 accepted translate 模糊决策时，按模糊工作流为 merge 追加 `--extra-translations`。
所有块必须 accepted；candidate 必须逐字节等于确定性重渲染结果且无保护标记。

### 2.6 AI 终检与最终输出

通读完整 candidate；长文档至少完整检查每个一级标题下的内容，并按质量标准检查
数字、漏译增译、术语、流畅性、风格和独立可理解性。把位置、类型和处理结果写入
`<task-id>/review.md`；无问题也记录已通读达标。

发现问题时只改受影响块，重新 validate（`--replace-accepted`）、merge、
`render --allow-overwrite`、verify 并重读，循环到干净。然后执行：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" mark-reviewed `
  "<state.json>" "<translations.json>" "<candidate.md>" "<review.md>"
```

按 `output_dir` 放置最终文件：空值表示源文件同级 `<stem>_zh.md`；非空值表示
`<output_dir>/<stem>_zh.md`。目标存在时停止询问，不把 candidate 覆盖权限扩展到最终文件。

源旁存在 `<stem>.assets` 时执行：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" copy-assets `
  "<源.md>" "<最终输出.md>"
```

目标 assets 已存在时不得合并或覆盖；先由用户处理冲突。

### 2.7 完成与归档

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" cleanup-run "<manifest.json>"
```

cleanup 仅在全部块 accepted，且 merge、render、verify、review 四阶段及其哈希仍有效时
把完整 task-id 移入 `logs/_archive/`。同名归档追加唯一后缀，不覆盖、不裁剪。
保留源文件、最终输出、决策日志和术语表快照。

## 3. 树形翻译

树形模式只负责扫描、共享术语表、镜像输出和失败汇总；每个文件仍完整执行上面的
单文件 pipeline。单文件失败不回滚其他文件，最终必须列出成功、失败和跳过项；
部分成功不得描述为整树完成。

## 全局红线

- 配置同步失败必须停止；全程使用 state 绑定的同一解释器。
- 源 Markdown 与源 `.assets` 始终只读，不修复、不覆盖、不移动。
- 不直接编辑完整 Markdown；只翻译 pipeline 暴露的块表面。
- SEG 行原样且有序，PROTECT 标记恰好一次；不得放宽为空译文或“尽量保留”。
- 译文只用 UTF-8 文件写入，不经 shell 文本管道。
- 当前 AI 助手完成翻译与全文终检；验证器不能代替语义审阅。
- 单块失败只修该块，不能丢弃其他 accepted 块或重启整篇。
- 输出、assets 和归档发生冲突时停止，不静默覆盖、合并或删除。
- 四阶段完成标记与产物哈希全部有效后才允许归档。
- 未经用户明确要求，不得修改共享 skill。
- 修改 `scripts/*.py` 后必须运行完整 `scripts/test/selftest.py` 并全部通过。

## 维护收尾

维护任务遵循直接路由和维护规则。bug 记录到 `KNOWN_ISSUES.md`；优化、重构和扩展
记录到 `OPTIMIZATION_SUMMARY.md`。写入前读取文档头部模板并使用系统当前日期。

任何 skill 文件变更后都运行完整 selftest、配置同步、skill 校验、文档路由测试、
`git diff --check`、LF/链接检查和隔离暂存目录的 `package_check.py`，全部通过才算完成。
