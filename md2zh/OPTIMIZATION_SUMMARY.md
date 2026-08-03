# md2zh 优化总结

> 本文档是优化交接文档：记录历次大优化"改了哪些文件、验证到什么程度、
> 踩过哪些坑、遗留了什么"，供后续做优化前对齐、避免重复踩坑。
> 优化前先读本文件，优化后追加记录，保持不过时。
> 如何追加：新优化直接复制「一、优化范围」顶部的【追加模板】（HTML 注释块），
> 把模板替换为本次内容、插入到模板所在位置即可——模板即操作说明，无需理解章节结构。
> 条目按时间倒序排列（新 → 旧）：最新优化在最前，紧随模板之后（读文件时最先看到最近改动）。

## 一、优化范围

<!-- ============================ 追加模板（新优化记录写在这里） ============================
如何追加：把本注释块整体复制到它所在的位置（即「一、优化范围」顶部、最新条目之前），
将下方占位内容替换为本次优化的实际内容。条目按时间倒序（新 → 旧），最新条目在最前。
日期用系统当前时间：
Windows: Get-Date -Format "yyyy-MM-dd"；Linux/macOS: date +%F
===========================================================================

### YYYY-MM-DD：优化简述

| 类别 | 内容 |
|------|------|
| 新功能 / 脚本改动 / 流程改动 / 测试 / 验证 | 本次优化改了什么、验证到什么程度 |

**过程要点**：
- 设计决策、踩过的坑、与既有机制的交互

**遗留事项更新**：
- （原）...
- （新增）...

============================================================================
追加模板结束——复制时删除上方/下方的分隔注释与本说明，只保留替换后的正式条目
============================================================================ -->

### 2026-08-03：单文件 / 树形判定规则优化（按 .md 数量替代"是否目录"）

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md 树形翻译触发条件重写：判定依据从"用户是否指定目录"改为"目录树内可翻译 .md 任务数"（忽略 `.assets/`）——任务数 = 1（含 web2md 抓取单页的"标题文件夹 + 同名 .md + .assets"）→ 单文件流程、输出 `<stem>_zh.md` 平级；任务数 ≥ 2 → 树形流程、镜像输出 `<根名>_zh/`；判定表写入 SKILL.md「树形翻译」触发段落 |
| 流程改动 | SKILL.md 引言补"单文件 / 树形判定"指引；README.md md2zh 章节树形能力描述同步（多 .md 目录才走树形，单 .md 目录退化为单文件流程） |
| 文档 | 本条目追加；KNOWN_ISSUES 不追加（规则歧义非 bug）；不改 pipeline 脚本（无 selftest 要求） |

**过程要点**：
- 触发点：真实翻译 `Controller Diagrams`（web2md 单页结构，任务数 = 1）被旧规则判为树形、输出镜像树，用户指出"本质是单文件，.assets 只是图片目录"；用户选择平级 `_zh.md` 输出
- 判定改为"数可翻译 .md 任务数"（与树形流程 1 扫描规则同口径），任何 AI 可确定性执行，消除"是否目录"的歧义
- 最小改动：只改 SKILL.md / README.md / OPTIMIZATION_SUMMARY.md，不动 pipeline 脚本

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：不变（分块契约限制，未改 pipeline）
- （原）pipeline 独立运行：有意不做（保持不变）
- （新增）无

### 2026-08-03：记录格式对齐 web2md 模板

| 类别 | 内容 |
|------|------|
| 流程改动 | OPTIMIZATION_SUMMARY.md 从自由格式（`## [2026-08]` 列表式）改为 web2md 标准格式：追加模板（HTML 注释操作说明）+ 条目表格（类别/内容）+ 过程要点 + 遗留事项更新 + 时间倒序（新→旧） |
| 流程改动 | 历史批次（第一批～第五批 + 首次真实翻译）全部按新模板重写为正式条目；补「二、验证结果」「三、过程中的 bug 序列」「五、遗留事项」章节 |
| 流程改动 | KNOWN_ISSUES.md 同步对齐 web2md 格式（追加模板 + 倒序 + 不删除旧条目），并写入本次真实翻译的 4 条实战问题（弯引号目录名 / cleanup state 位置 / introduced syntax / empty translation） |

**过程要点**：
- 条目日期统一取系统当前时间（2026-08-03）；批次顺序在条目内以「第 N 批」标注
- 遗留事项以「（原）/（新增）」形式随条目滚动更新，不再集中堆积
- KNOWN_ISSUES 的 4 条为"已知行为/执行约定"（非脚本 bug）——现象/根因/修复/排查方法四要素齐全，修复列写执行约定与 SKILL.md 引用

**遗留事项更新**：
- （原）无
- （新增）无

### 2026-08-03：首次真实树形翻译（NuttShell (NSH)）+ 实战优化

| 类别 | 内容 |
|------|------|
| 验证 | 真实树形翻译：web2md 输出树 `E:\study_data\web2md\NuttShell (NSH)` → 镜像树 `NuttShell (NSH)_zh/`，9 文件 / 25 块 / 约 400 段可见文本，全部 validate accepted + verify pass；中间产物清理，保留 config.json + 决策日志 |
| 流程改动 | SKILL.md 树形输出命名修正：镜像树输出**与源同名** `.md`（对接 `md_import --dir` "同名 md 优先"规则；`_zh` 后缀仅单文件模式） |
| 脚本改动 | 固化 `scripts/scan_visible.py`（列块内可见文本行，跳过 PROTECT/空行）+ `scripts/apply_translations.py`（按 SEG 映射 JSON 写回 output，未映射行原样保留）——替代手写临时脚本 |
| 流程改动 | SKILL.md「翻译执行注意事项」：空译文被拒 / 译文禁 Markdown 语法字符 / state 放任务目录否则 cleanup 拒绝 / 弯引号目录名用单引号拼接 |
| 测试 | selftest +3 用例（apply 替换+PROTECT 保留、未映射行原样、scan 只列可见文本）→ 10 用例全绿 |

**过程要点**：
- 流程实测跑通：configure(ai) → 逐文件 extract/plan → 逐块翻译 → validate（3 处失败均单块修正，失败隔离生效）→ merge → render → verify → 镜像落盘 → 清理
- 踩坑：空译文被 validate 拒绝；`\u201c` 经 PowerShell 转义成字面反斜杠被判"introduced Markdown syntax"（中文引号直接书写）；块 10 文件名是 `block-0010` 非 `block-00010`；state 放 TEMP 导致 `cleanup-run` 拒绝清理（state 应放任务目录内）；弯引号目录名在 PowerShell 双引号中被误解析

**遗留事项更新**：
- （原）术语表文件化待做 → 仍待做（模型内存跨块保留）
- （原）真实环境验证待用户发起 → 已完成（本次）
- （新增）逐行断句的翻译质感受分块契约限制（单行 segment 模式），未改 pipeline

### 2026-08-03：树形翻译支持（第五批）

| 类别 | 内容 |
|------|------|
| 新功能 | 支持翻译多文件目录树（web2md `collect_children` 输出结构：标题文件夹 + 同名 .md + .assets）；SKILL.md 新增「树形翻译」章节 |
| 流程改动 | 扫描树（每含 .md 文件夹 = 任务，同名 md 优先，与 confluence-tools --dir 同规则）→ 树级共享术语表 → 逐文件跑完整 pipeline（独立 task-id/状态/产物）→ 镜像输出 `<根名>_zh/` → 失败隔离 + 汇总 |
| 对接 | 输出镜像树可直接 `md_import --dir` 导入 Confluence——完整流水线 `web2md 抓取 → md2zh 翻译 → confluence 页面树` |
| 实现 | pipeline 脚本零改动（单文件流程循环编排，AI 助手执行） |

**过程要点**：
- 用户决策：输出位置 = 镜像树 `<根名>_zh/`；术语表 = 树级共享
- README.md md2zh 章节同步补树形能力说明

**遗留事项更新**：
- （原）SKILL.md 重写待做 → 已完成（第四批）
- （新增）无

### 2026-08-03：文档结构对齐（第四批：对照 confluence-tools 补齐）

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md（8005B → 11722B）补 6 章节：容错与安全（失败隔离/断点续传/决策日志/编码安全/凭据安全）、任务产物与清理（.md2zh_tools 结构 + cleanup-run 边界）、文件结构、实现前检查点（必过）、真实环境验证的清理（必过） |
| 流程改动 | README.md md2zh 章节从旧版纯 prompt 描述重写为新架构（分块编排/字节级保护/确定性校验/质量保障） |
| 说明 | 未加"独立运行"章节（用户明确不需要——翻译核心依赖 AI 助手会话，pipeline 只是编排工具） |

**过程要点**：
- 对照 confluence-tools 的文档结构逐项补齐，对齐后差异仅为有意保留的"独立运行"

**遗留事项更新**：
- （原）无
- （新增）无

### 2026-08-03：工程化核心与收尾（第二批 + 第三批）

| 类别 | 内容 |
|------|------|
| 脚本改动 | 移植 `scripts/md2zh_pipeline.py`（.codex 版 77KB，纯标准库 Python，无第三方依赖/无 API 调用）；decider 配置值通用化 `codex → ai` |
| 测试 | `scripts/tests/selftest.py`：7 个离线黑盒用例（configure 写入 / ai decider / 分块 PROTECT / 端到端 roundtrip 字节级一致 / 契约违规拒绝×2），全绿 |
| 流程改动 | SKILL.md 重写（3.7KB 纯 prompt → 8KB 编排流程）：触发/契约/两级配置向导（skill 级 config.py + 项目级 .md2zh_tools/config.json）/脚本完整性检查（先确认再恢复）/extract→决策→plan→逐块翻译→validate→merge→render→verify→cleanup 全流程/测试/自进化/固化约束，措辞通用化（AI 助手） |
| 脚本改动 | `references/translation-rules.md`：移植 .codex 版（3554B），2 处 Codex → AI assistant 通用化 |

**过程要点**：
- 实测验证：configure(explicit) → extract（4 units / 1 block）→ plan-blocks → 原样翻译 validate(accepted) → merge → render（sha256 与源一致）→ verify(pass)
- `validate-block` 契约闸门：删 SEG 行 / 加多余行均被拒（selftest 覆盖）

**遗留事项更新**：
- （原）无
- （新增）术语表文件化：当前按 SKILL.md 约定"任务级术语表跨块保留"（模型内存），未独立落盘（可选后续）

### 2026-08-03：工程化骨架（第一批）

| 类别 | 内容 |
|------|------|
| 新功能 | 配置体系：`config.example.py` + `scripts/config.py`（`md2zh_config.python_path`），gitignore 排除 |
| 脚本改动 | 移植 pipeline 至 `scripts/`（decider 值通用化 `codex → ai`） |
| 流程改动 | 自进化文档：`KNOWN_ISSUES.md` / `OPTIMIZATION_SUMMARY.md` 建立（本文件） |

**过程要点**：
- 背景：md2zh 原为纯 prompt skill（仅 3.7KB SKILL.md，模型直接翻译整篇），未脚本化；对照 web2md / confluence-tools 的工程化模式（共享 scripts/ + config 体系 + selftest + 自进化 + 完整性检查）补齐骨架
- 配置模板同步原则：新增配置项时同时更新 config.example.py 与 SKILL.md 配置说明

**遗留事项更新**：
- （原）无
- （新增）SKILL.md 仍为旧版（纯 prompt 流程）→ 第二批重写；selftest 待建 → 第二批；配置向导待写入 SKILL.md → 第二批

## 二、验证结果

- NuttShell (NSH) 真实树形翻译：9 文件 / 25 块 / 约 400 段可见文本，全部 validate accepted + verify pass（确定性渲染，链接/代码/命令名字节级保留）
- selftest 10 用例全绿（pipeline 7 + 辅助脚本 3）
- pipeline 端到端：configure → extract → plan-blocks → 原样翻译 → validate → merge → render（sha256 与源一致）→ verify(pass)
- 契约校验实测：空译文、SEG 行缺失/多余、译文引入 Markdown 语法均被 validate 拒绝

## 三、过程中的 bug 序列

1. **空译文被拒**：SEG 内容行译文为空 → `unit-xxxx has an empty translation` → 每个内容行必须有译文
2. **`\u201c` 字面转义被判 Markdown 语法**：PowerShell 不解析 `\u` 转义，写入文件的 `\u201c` 反斜杠触发 `introduced Markdown syntax` → 译文用中文引号直接书写
3. **块 10 文件名格式**：`block-000%d` 对 10 生成 `block-00010`（应为 `block-0010`）→ 两位数 `%02d` 或按 manifest 实际文件名
4. **state 放 TEMP 导致 cleanup 拒绝**：`cleanup_run` 校验 state 在任务目录内（`path_is_within`）→ state/blocks 放 `intermediate/<task>/` 内
5. **PowerShell 弯引号目录名解析**：`NSH “Built-In” Applications` 在双引号字符串中被当参数分隔 → 单引号拼接
6. **selftest 断言索引**：`_create_page` 签名 `(title, content, parent_id)`，title 在 `call_args[0][0]`（首轮误用 `[0][1]` 失败 2 次后修正）

## 四、协作风格

1. **先方案后动手**：写代码/改文档前输出方案，用户确认后才实施；方案被否就重出
2. **任务清单跟踪**：多步任务用任务列表推进，不半途遗忘
3. **测试先行**：所有脚本改动必须 selftest 全绿才交付；测试随功能同步补
4. **真实环境验证**：验证产物（临时文件/任务目录）用后即清
5. **证据驱动排查**：先拉数据/日志定位根因，不猜
6. **文档同步**：代码、配置模板、SKILL.md、KNOWN_ISSUES、OPTIMIZATION_SUMMARY、README 保持一致
7. **诚实报告**：做过什么、没做什么、验证到什么程度，如实说明
8. **安全优先**：真实凭据只存在于 gitignore 排除的 config.py；不读含凭据文件全文；删除/批量操作先向用户解释等授权
9. **配置驱动设计**：脚本从 config.py 自给自足；CLI 参数只做临时覆盖
10. **恢复被删脚本前先征得用户确认**

## 五、遗留事项

- **术语表文件化**：当前按 SKILL.md 约定"任务级术语表跨块保留"（模型内存），未独立落盘（可选后续）
- **逐行断句的翻译质感**：分块契约单行 segment 模式限制，未改 pipeline（如需流畅断行需跨行合并，改动大）
- **pipeline 独立运行**：有意不做（用户明确不需要——翻译核心依赖 AI 助手会话，pipeline 只是编排工具）
