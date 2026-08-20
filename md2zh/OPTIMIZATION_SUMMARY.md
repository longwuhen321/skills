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

### 2026-08-20：SKILL 渐进式披露与文档路由回归

| 类别 | 内容 |
|------|------|
| 主入口精简 | `SKILL.md` 从 409 行压缩到 205 行，保留触发条件、模式选择、单文件主流程、树形入口、核心红线和维护入口；硬性回归上限设为 250 行 |
| 渐进式披露 | 新增 `configuration-guide.md`、`ambiguous-content-workflow.md`、`tree-translation-workflow.md`、`maintenance-rules.md`、`script-development-rules.md`；为既有 `translation-rules.md`、`translation-quality.md` 补齐正式“强制读取条件” |
| 路由与回执 | 主入口直接链接 7 份专题文档及父级维护标准/记录，并固定读取回执字段，避免脚本开发、故障修复和优化任务通过间接引用丢失必读文档 |
| 测试 | 新增 `test_documentation_routes.py` 的 5 项文档架构回归，并接入显式自测套件；最终完整自测 81/81、配置同步检查 5/5、skill 结构校验通过 |
| 最终验证 | 11 个变更文件通过 LF/尾随空白检查；19 个本地 Markdown 链接均可解析；22 文件隔离 staging 通过打包检查；运行时脚本差异为 0 |

**过程要点**：
- 文档路由采用“主入口直接链接 + 专题文档自声明强制读取条件”，不依赖读者从一份参考文档继续跳转到另一份。
- Windows 上结构校验用 `python -X utf8` 运行，避免默认代码页误判 UTF-8 文档。
- 本次只调整文档与文档回归测试；翻译管线、配置、提示词模板、命令参数和默认行为均未改变。

**遗留事项更新**：
- （原）`SKILL.md` 过长、专题规则与主流程混排 → **已完成**（409 → 205 行，并由 250 行硬门禁防回退）。
- （新增）无；完整自测为离线回归，不调用外部机器翻译服务，也不替代真实译文的人工语义审阅。

### 2026-08-11：安全配置、任务完成门禁与持久化术语表

| 类别 | 内容 |
|------|------|
| 安全与工程 | 新增 `scripts/config_literal.py`，运行期与同步检查统一使用 AST + `ast.literal_eval` 读取字面量配置，拒绝导入、函数调用、类型注解赋值和副作用语句；新增 `scripts/package_check.py`，路径优先拒绝真实配置、logs、缓存、环境/凭据文件与常见 Token，拒绝路径不读取内容 |
| 归档可靠性 | `cleanup-run` 遇同名 task-id 归档时追加唯一后缀，绝不覆盖或删除既有归档；按要求取消自动裁剪，归档保持只增 |
| 完成门禁 | `completion.json` 对 merge、render、verify、review 四阶段及产物哈希做绑定；新增显式 `mark-reviewed`，cleanup 必须确认四阶段完成、review 产物存在且哈希仍一致，任一缺失或产物变化都拒绝归档 |
| 术语复用 | 新增持久化 `glossary.json` 与 `update-glossary`：单任务默认存任务根，树形翻译可把同一路径传给各文件以跨块、跨文件复用；冲突更新显式拒绝，归档保留术语表快照 |
| 测试与验证 | 新增 `scripts/test/test_packaging.py` 并扩展 pipeline/config 回归；最终 76/76，通过完整允许文件 staging packaging check、LF 检查及 skill 结构验证 |

**过程要点**：
- completion 标记不仅记录“完成”，还记录对应产物哈希；review 不能只存在阶段布尔值，必须有 `review.md` 且在 cleanup 前未变化。
- 同名归档冲突通过时间戳/稳定唯一后缀解决，不使用覆盖或先删后写；这一安全约束意味着归档磁盘占用会持续增长。
- packaging check 对 Python 仅识别真实字符串字面量配置，对普通文本再允许无引号 Token，避免把 `TOKEN_RE = re.compile(...)` 和测试夹具误报为凭据。

**遗留事项更新**：
- （原）术语表只保存在会话上下文 → **已完成**（任务级/树级 `glossary.json`，2026-08-11）。
- （原）cleanup 只检查块 accepted → **已完成**（merge/render/verify/review + 哈希门禁）。
- （新增）归档按安全要求不再裁剪，需由用户按磁盘策略人工管理；完成标记只能证明产物和审阅记录完整，不能机器判断审阅语义质量。

### 2026-08-08：测试目录更名（scripts/debug/ → scripts/test/）

| 类别 | 内容 |
|------|------|
| 流程改动 | 测试目录从 `scripts/debug/` 更名 `scripts/test/`——目录里存的是测试文件，`test/` 比 `debug/` 自描述；与日志目录更名同逻辑，至此全项目消除 debug 语义歧义（`logs/` 日志、`scripts/test/` 测试） |
| 磁盘 | `scripts/debug/` → `scripts/test/`（内容不动） |
| 文档 | SKILL.md 3 处 `scripts/debug` → `scripts/test`（含目录树 `└── test/`）；测试需入库（git 追踪） |
| 测试 | selftest 从 `scripts/test/selftest.py` 运行 40 全绿（相对路径定位自动跟随，零代码改动） |

**过程要点**：
- 与 web2md / confluence-tools 同步更名（三 skill 统一）；`debug_utils` 类文件名保留（调试工具，非测试）

**遗留事项更新**：
- （新增）历史条目仍写 `scripts/debug/`，属当时事实，保留不改


### 2026-08-08：日志目录更名（debug/ → logs/）

| 类别 | 内容 |
|------|------|
| 脚本改动 | `md2zh_pipeline.py` `default_tools_root()`：`"debug"` → `"logs"`（注释同步更新历史：`.md2zh_tools/` → `<skill>/debug/`（08-06）→ `<skill>/logs/`（08-08）） |
| 文档 | SKILL.md 10 处 `<skill-directory>/debug/` → `<skill-directory>/logs/`（日志语境）；`scripts/debug/`（测试）保留 |
| 磁盘 | `md2zh/debug/` → `md2zh/logs/`（内容不动） |
| gitignore | `/*/debug` → `/*/logs`（全局规则覆盖） |
| 测试 | selftest 40 全绿（tools_root 改动无回归） |

**过程要点**：
- 更名动机：`debug/` 与 `scripts/debug/`（测试）同名造成语义混淆；`logs/` 自描述「日志」
- 与 confluence-tools 同步更名（三 skill 统一：日志归 `<skill>/logs/`）

**遗留事项更新**：
- （新增）历史条目（08-06 迁移记录）仍写 `debug/`，属当时事实，保留不改


### 2026-08-08：skill 文档自描述规范化

| 类别 | 内容 |
|------|------|
| 流程改动 | 确立「skill 文档自描述」表达规范：结构/流程说明必须**自描述**——规则写全本文件内，复杂结构用「占位符 + 示例图」直接画出，不引用其他 skill 的规则细节，不用具体实例名（真实项目名）。md2zh/SKILL.md 全文按此规范落地 |
| 落地清单 | ① 配置向导「与 web2md / confluence-tools 同规则」→「规则见下」（本文件 L41-43 三步自含）；② 树形扫描「与 confluence-tools --dir 同扫描规则」→ 删除（扫描规则本文件 L164 已自含）；③ 树级术语表示例 `NuttShell / NSH` → 占位描述；④ 输出镜像树 `如 Commands.md` → 删具体名，格式图并入第 4 点作为输出示例（`页面A.md` / `子文件夹` 占位符）；⑤ 树形判定 `web2md 抓取单页` → 删跨 skill 引用 + 补单文件场景目录示例（`<标题>.md` / `<标题>.assets/`）；⑥ 删「与 confluence-tools 对接：可直接交给 md_import --dir 导入——完整流水线」段（skill 独立不连通，跨 skill 关系属 README 职责，不在执行指令集内） || 判定标准 | 跨 skill 引用分两类：**执行依赖**（AI 需要对方规则细节才能执行）→ 删；**对接/兼容说明**（目录结构兼容等，非执行依赖）→ 归 README 或删。SKILL.md 只装执行者（AI）需要的内容 |

**过程要点**：
- 起因：用户指出「与 web2md / confluence-tools 同规则」这类跨 skill 引用不可取——skill 执行时上下文只有本 SKILL.md，引用指向的内容根本不在上下文里；且被引用的两份规则本身不一致（confluence 禁 AskUserQuestion、web2md 未写），语义上无从遵循
- 关键区分：**清理 ≠ 规范化**——工作成果是「确立了占位符 + 示例图的表达规范」而非「删了什么」；此规范可复用于其他 skill 文档
- 对「与 confluence-tools 对接」段的取舍：目录结构兼容是真实设计（`_zh` 仅单文件、树形同名 md 均为此），但「可直接交给」暗示了不存在的连通；改为自描述格式图 + 删除对接段，兼容性信息由 README 承担
- 具体实例名（`Commands.md` / `NuttShell / NSH`）与「自包含」原则冲突——它们本质是隐性外部参照，削弱格式图的通用性

**遗留事项更新**：
- （新增）「skill 文档自描述」规范确立落地；README.md 保留跨 skill 关系说明（总览文档职责），本 skill SKILL.md 已无跨引用


### 2026-08-08：配置同步强制门禁（check_config_sync.py，复用 web2md 方案）

| 类别 | 内容 |
|------|------|
| 新脚本 | `check_config_sync.py`：对比 `scripts/config.py` 与 `config.example.py` 的 `md2zh_config` **键集合 + 值类型**（`exec` 解析，与 `load_global_config()` 同源）；三类差异 `missing` / `extra` / `type` 逐条列出；退出码 0 = 同步 / 1 = 有差异 / 2 = 文件缺失或损坏；`--config-text` 从 stdin 读取（配置向导写入后复核）；`--group` 参数化分组名（默认 `md2zh_config`，web2md 版无此参数） |
| 流程改动 | SKILL.md：`python_path` 存在且有效 → 先跑门禁，不一致（退出码 1/2）**中断任务**；向导第 3 步写入后立即复核；脚本完整性检查补 `check_config_sync.py`；配置段 / 文件结构 / 固化的核心约束（新增配置键时旧 config.py 会被门禁拦下）同步更新 |
| 测试 | `debug/test_config_sync.py` 9 用例（真实文件同步通过 / 临时对同步 / 缺键 / 多余键 / 类型不符 / 文件缺失 / 损坏 / stdin 模式 / `--group` 自定义分组）；selftest.py 改为 suite 显式装载三组用例 → 40 用例全绿（31 原 + 9 新） |

**过程要点**：
- **同构性核实**：`load_global_config()`（md2zh_pipeline.py:256-295）与 web2md `load_config()` 完全同构——选填键 `output_dir` / `tree_translation` / `max_block_chars` 缺失时 defaults 兜底**静默降级**，只 `python_path` / `ambiguous_content_decider` 两个必需键缺失才抛错 → 漂移通道存在，门禁有价值
- **configure 不能作为补齐途径**：`configure_project`（md2zh_pipeline.py:215-253）是重建式写入，缺键时 `_read_config_value` 回退默认值（L234-244）→ 缺失新键只能手动编辑 config.py 补齐
- **复用方式**：从 web2md 复制 + 加 `--group` 参数化（约 10 行），不跨 skill 共享脚本（各自完整性约定）
- 踩坑：md2zh selftest.py 是单文件结构（非 web2md 的 discover），新测试不自动发现 → 改为 suite 显式装载；`test_config_sync.py` 的临时文件场景返回码 2 曾误判（stdin 模式跳过 config 文件存在性检查）

**遗留事项更新**：
- （新增）真实 config.py 当前 5 键与 example 一致（exit 0），门禁防未来漂移；新增配置键时 configure 无法补齐，需手动编辑 config.py



### 2026-08-06：SKILL.md / KNOWN_ISSUES.md 审查修复（4 个问题）

| 类别 | 内容 |
|------|------|
| 文档 | ① SKILL.md「文件结构」树补 `debug/` 目录（原遗漏，与「任务产物与清理」章节不一致）及 .gitignore 说明；② SKILL.md render 表述澄清：render 只写入 `<candidate.md>`，最终文件位置由 AI 读 output_dir 放置（原表述"render 输出位置读 output_dir"与实际实现不符）；③ SKILL.md UTF-8 直写补充：文件工具不可用时允许 .NET WriteAllText（UTF-8 无 BOM）直写，禁管道/Add-Content；④ SKILL.md 配置章节补 `--tools-root` 说明；⑤ KNOWN_ISSUES.md L38 旧路径 `{项目根}/.md2zh_tools/` 更新为 `<skill-directory>/debug/` |
| 流程改动 | 用户发起"通读 skill 查遗漏/矛盾"审查；4 个问题（2 实质 + 1 表述 + 1 可选）全部修复 |
| 测试 | 纯文档改动（SKILL.md / KNOWN_ISSUES.md），不涉及 scripts/*.py，无需 selftest |

**过程要点**：
- 审查方法：SKILL.md 全文 ↔ config.example.py / scripts/config.py / pipeline `--help` 实测子命令 / KNOWN_ISSUES.md 逐项比对
- 确认一致项：配置 5 字段、11 个子命令、_archive 20 条、cleanup-run state 契约、debug/ 7 处路径统一
- L230「历史遗留 config.json」与 extract 的 `--project-root` 是有意保留（历史事实/参数仍在用），不改

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）debug/ 已建但未有真实任务写入 → 本次仍未写入，待下次翻译验证日志落点


### 2026-08-06：SKILL.md 补「残留任务清理」约定（对齐 web2md 日志清理纪律）

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md「任务产物与清理」新增「残留任务清理」条：`intermediate/` 中非本次任务/已确认弃用的任务目录，任务结束后人工清理（删除或移入 `_archive/`）；`cleanup-run` 拒收的 unfinished 任务先处理未完成块或确认弃用后人工删除 |
| 文档 | 纯 SKILL.md 改动，不涉及 scripts/*.py（无需 selftest） |

**过程要点**：
- 触发：用户询问"web2md 中的日志删除逻辑你同步过来吗"——对照发现 web2md 有 intermediate 保留 5 轮 / _archive 保留 20 条的编排约定；md2zh 的 _archive 20 条已由 cleanup_run 脚本强制（更严格），但 intermediate 缺"残留任务清理"约定（unfinished 任务会被 cleanup 拒收而永久滞留）
- 用户决策：方案 1（SKILL.md 编排约定，最小改动），不采用方案 2（pipeline 加清理子命令）
- web2md 的"保留最近 5 轮"不照搬：md2zh 的 intermediate 是单次任务快照（cleanup 即归档），无"多轮清单"形态

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）debug/ 已建但未有真实任务写入 → 本次仍未写入，待下次翻译验证日志落点


### 2026-08-06：日志产物迁移到 skill 根 debug/（覆盖"保持项目根"决策）

| 类别 | 内容 |
|------|------|
| 流程改动 | 日志产物根从 `{项目根}/.md2zh_tools/` 迁移到 `<skill-directory>/debug/`（`decision_logs/`、`intermediate/`、`_archive/` 三个子目录整体迁移）；旧日志保留项目根原处不迁移；debug/ 文件夹已建 |
| 脚本改动 | `md2zh_pipeline.py`：新增 `default_tools_root()`（skill 根/debug）与 `state_tools_root()`（旧 state 无 tools_root 时回退 `project_root/.md2zh_tools`）；extract 的 decision_log 路径改用 tools_root 且 state 增 `tools_root` 字段；`decision_log_path` / `plan_blocks` / `cleanup_run` 改用 `state_tools_root`；extract CLI 增 `--tools-root`（selftest 隔离用，正常流程不用） |
| 测试 | selftest：setUp 增 `self.tools`（临时目录下的隔离日志根）；全部 extract 调用加 `--tools-root self.tools`；archive 断言改 `self.tools/_archive` → 31 用例全绿（初始 3 失败为 `_extract_multi` 漏传参数，修复后通过） |
| 文档 | SKILL.md 7 处 `{项目根}/.md2zh_tools` → `<skill-directory>/debug/`（run 目录/review.md/归档/中间产物/决策日志/产物树/验证清理）；历史遗留 config.json 说明保留；.gitignore 加 `md2zh/debug/` |

**过程要点**：
- 覆盖 2026-08-05"用户决策：位置保持项目根（web2md 同构）"——用户改主意，日志改放 skill 根 debug/
- 兼容：旧 state（无 tools_root 字段）的 decision_log_path / plan / cleanup 回退到 `project_root/.md2zh_tools`，已归档/中断任务不受影响
- 关键坑 1：selftest 若用写死的 tools_root 会污染真实 skill/debug/ → `--tools-root` 临时覆盖（与 `--config` 同模式）
- 关键坑 2：`.gitignore` 追加时注释与规则写在同一行（`#` 开头导致规则失效）且中文乱码 → 拆两行、直接 UTF-8 写正确中文
- `--project-root` 保留（仅用于记录源文件相对路径，决策日志可追溯源位置）

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）pipeline 独立运行：有意不做（保持不变）
- （新增）debug/ 目录已建但尚未有真实任务写入，待下次翻译验证日志落点


### 2026-08-05：分块/翻译/收尾三大改造（标题区间分块 + summarize + 段落级 unit + AI 终检 + 归档）

| 类别 | 内容 |
|------|------|
| 新功能 | ① `max_block_chars` 配置项（字符单位，默认 16000，建议 10000–24000）：单块**可译内容**（可见文本，不含保护内容）上限；② 分块重写为**标题区间优先**——每个标题章节（含文件头）默认独立成块，超限章节在 unit 边界拆；③ `summarize` 子命令（主流程）：结构摘要 md（标题树到 3 级/每章节可译字符/代码公式块位置/默认分块方案表），AI 通读后确认默认方案或给调整指令；④ **段落级 unit**：普通段落合并为多行 unit，译文可自由断句/换行/重排（物理行数不受限），禁空行/禁行首块级标记/禁首尾换行，渲染按源区间行尾风格还原换行；⑤ AI 终检：render 后 AI 通读完整译文对照 translation-quality.md 四章检查，review.md 落盘，循环到干净；⑥ `cleanup-run` 改为**归档**到 `.md2zh_tools/_archive/`（最多 20 条目，超出删最旧） |
| 脚本改动 | `md2zh_pipeline.py`：translatable_chars/build_translation_blocks 重写、summarize_document、extract 段落合并（paragraph_buffer + prev_line_end 连续性）、translation_block_surface/parse_block_surface 多行契约（按 SEG 切分）、validate_translated_template 删单行闸门、validate_no_introduced_syntax 逐行块级检查、deterministic_render 行尾还原（line_ending_style）、cleanup_run 归档、state schema 3→4、CONFIG_PY_TEMPLATE/configure/load/CLI 加 max_block_chars；`scan_visible.py`/`apply_translations.py` 按 SEG 切分多行段 |
| 测试 | selftest 17→29 用例全绿：段落合并断言、多行 roundtrip 字节一致、重排译文 accepted、空行拒绝、cleanup 归档断言、summarize 要素断言、configure max_block_chars 3 用例、辅助脚本多行段 2 例 |
| 文档 | SKILL.md：配置列表/流程（extract→summarize→AI 确认→plan→翻译→终检→cleanup 归档）/翻译注意事项/产物结构（_archive）/配置章节/容错与安全（结构摘要）；config.example.py 与 scripts/config.py 加 max_block_chars |

**过程要点**：
- 踩坑 1：段落合并连续性判断用 `abs_start == buffer.end` 永远不成立（行间有换行符）→ 改用 `line.start == prev_line_end`（含换行）
- 踩坑 2：surface 解析（splitlines）剥离 `\r`，渲染后 Windows 行尾变 `\n` 字节不一致 → `line_ending_style` 按源区间首个换行风格还原译文 `\n`
- 踩坑 3：`validate_translated_template` 残留单行闸门（"must not change physical line boundaries"）→ 删除，多行契约统一由 parse_block_surface 把关
- 踩坑 4：summarize 的 heading_counts 用 str key 与 int level 不匹配 → 统一 int
- 踩坑 5：cleanup 测试被既有契约拦截（state 必须在任务目录内，KNOWN_ISSUES 已记录）
- 设计要点：行尾还原只对含 `\n` 的译文生效（单行 unit 不受影响）；段落边界保持（空行拒绝）保障结构；`_archive` 与 web2md 同构（intermediate + _archive + 保留上限）
- 用户决策：位置保持项目根（web2md 同构）；组织方式 web2md 式（intermediate + _archive）；max_block_chars 按可译内容（源可见文本）计，系数 1

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：**已完成**（段落级 unit，2026-08-05 落地）→ 移除
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）既有项目旧版 `.md2zh_tools/config.json`：按 SKILL.md「历史遗留」说明直接删除
- （新增）summarize 的 AI 调整指令通道（--plan-override）：摘要已产出，指令解析+校验未实现，当前靠 AI 读摘要后人工决定（无调整用默认方案）
- （新增）引用块/列表项仍为行级 unit（第一版范围，prefix 方案列为后续）


### 2026-08-05：新增翻译质量评判标准必读文件（translation-quality.md）

| 类别 | 内容 |
|------|------|
| 流程改动 | 新建 `references/translation-quality.md`：用户提供的"信达雅 + 硬性错误 / 流畅性 / 风格适配 / 自检方法"评判标准，整理为结构化文档；文件头注明"翻译前必读"及边界（评判译文文字本身，格式/公式/代码由 pipeline 保护，不因译文自由而改变） |
| 文档 | SKILL.md 三处同步：契约章节必读清单（translation-rules.md + translation-quality.md）、第 6 步复核改为"按评判标准复核"、文件结构章节加新文件 |

**过程要点**：
- 用户原文本含对话性语句（"可以发出来帮你诊断"）与 emoji，整理时删除，保留全部标准要点
- 不涉及 scripts/*.py，无需 selftest

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：不变（分块契约单行 segment 限制，段落级 unit 方案已提出待用户决策）
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）既有项目旧版 `.md2zh_tools/config.json`：按 SKILL.md「历史遗留」说明直接删除
- （新增）无


### 2026-08-05：新增 tree_translation 配置项（树形翻译开关）

| 类别 | 内容 |
|------|------|
| 新功能 | `md2zh_config` 新增 `tree_translation`（bool，默认 true）：true = 指定目录且树内可翻译 .md ≥ 2 个时按树形流程镜像输出（现状行为）；false = 目录不再自动触发树形，遇多个可翻译 .md 时停下询问用户指定单个文件 |
| 脚本改动 | `CONFIG_PY_TEMPLATE` 加 `tree_translation` 字段；`configure_project` 加参数（缺省用 `_read_config_value` 保留现值，非 bool 按 True 兜底）；`load_global_config` 返回 `tree_translation`（非 bool 按 True 兜底）；configure CLI 加 `--tree-translation {true,false}`（未提供 = None = 保留现值） |
| 配置 | `config.example.py` 与真实 `scripts/config.py` 均加 `"tree_translation": True`（注释说明语义）；SKILL.md 配置列表/判定表注/配置章节/临时覆盖说明 4 处同步 |
| 测试 | selftest +3 用例（写入 false 断言 / 缺省保留现值 / 默认 true）→ 17 用例全绿（exit=0） |

**过程要点**：
- 树形翻译本身是 AI 编排（SKILL.md 流程），pipeline 无树形逻辑——配置项只做读写承载，判定规则写入 SKILL.md（AI 读配置决定流程）
- 沿用 output_dir 的"configure 临时覆盖 + 缺省保留现值"模式，selftest 断言 `assertIs` 区分 bool 与真值
- 默认 true 保持现状行为：未配置过该键的旧 config.py 由 load 兜底（非 bool → True）

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：不变（分块契约限制，未改 pipeline）
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）既有项目旧版 `.md2zh_tools/config.json`：按 SKILL.md「历史遗留」说明直接删除
- （新增）无


### 2026-08-05：output_dir 由 CLI 参数改为配置项（修正上一条）

| 类别 | 内容 |
|------|------|
| 流程改动 | 用户澄清需求：输出目录是**配置项**而非调用参数。`md2zh_config` 新增 `output_dir`（选填）：留空 `""` = 输出在源文件同级（默认）；指定 = 输出到该目录（自动创建）+ 源旁 `<stem>.assets` 一并复制（图片引用不变）。SKILL.md 撤回"调用参数 --output-dir"描述（开头/触发/第 6 步/树形第 4 步全部改为读 `md2zh_config.output_dir`） |
| 脚本改动 | `CONFIG_PY_TEMPLATE` 加 `output_dir` 字段；`configure_project` 加 `--output-dir`（可选，缺省时用 `_read_config_value` 宽松保留现有 config.py 的 output_dir 现值，损坏/缺失按 `""`）；`load_global_config` 返回 `output_dir`（非字符串按 `""` 兜底）；`copy-assets` 子命令不变（AI 读配置后决定是否调用） |
| 配置 | `config.example.py` 与真实 `scripts/config.py` 均加 `"output_dir": ""`（注释说明语义） |
| 测试 | selftest +2 用例：configure 写 output_dir（`--output-dir D:/out` 断言写入）；configure 不带 `--output-dir` 时保留现值（decider 改 ai 后 output_dir 仍为 D:/out）→ 14 用例全绿（exit=0） |

**过程要点**：
- 上一条（同日）误把需求实现为 CLI 调用参数 `--output-dir`；用户澄清"是配置项才对"。修正方向：配置为主，configure 向导的 `--output-dir` 作为临时覆盖保留（符合"CLI 参数只用于临时覆盖"）
- `_read_config_value` 宽松读取：configure 重写整个 config.py 时必须保留 output_dir 现值，否则每次向导都会把用户设置清空
- output_dir 不进 state.json（不影响 pipeline 渲染逻辑，仅 AI 编排层读取）

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：不变（分块契约限制，未改 pipeline）
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）既有项目旧版 `.md2zh_tools/config.json`：按 SKILL.md「历史遗留」说明直接删除
- （新增）无


### 2026-08-05：输出目录参数 + .assets 复制（copy-assets 子命令）

| 类别 | 内容 |
|------|------|
| 新功能 | `/md2zh` 调用可带 `--output-dir <目录>`：留空 = 输出在源文件同级（默认，行为不变）；指定 = 输出到 `<目录>/<stem>_zh.md`（目录自动创建）。源旁存在 `<stem>.assets` 时**一并复制**到输出目录，保证 md 内相对图片引用（如 `![](Guide.assets/x.png)`）不失效 |
| 脚本改动 | `md2zh_pipeline.py` 新增 `copy-assets <源.md> <输出.md>` 子命令：按**源文件同名** `<stem>.assets` 目录递归复制到输出位置（`shutil.copytree(dirs_exist_ok=True)`），目录名保持源 stem（不是 `_zh.assets`）以维持图片引用；无 assets 文件夹 → `{"copied": false}` 不算错误；输出 JSON 含 source/target/copied/files |
| 测试 | `selftest.py` +2 用例（有 assets 递归复制且目录名保持源 stem；无 assets 不报错不动输出目录）→ 12 用例全绿（exit=0） |
| 文档 | SKILL.md：开头输出说明 + 触发章节补 `--output-dir` 参数；单文件流程第 6 步补 render 输出位置约定与 `copy-assets` 命令；树形流程第 4 步补镜像树根位置（指定目录）与逐文件夹 `.assets` 复制 |

**过程要点**：
- 关键设计：复制目录名用**源 stem**（`doc.assets`）而非输出文件名 stem（`doc_zh.assets`）——md 内图片引用基于源文件名，改名会导致图片失效
- copy-assets 不读配置、无 runtime 校验（纯文件操作），未挂 `--config`
- 树形流程：镜像树根 = 指定目录；每个文件夹的 `.assets` 由 AI 逐文件调 `copy-assets` 复制（与单文件同命令）
- 契约不变：输出已存在仍停下询问覆盖

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：不变（分块契约限制，未改 pipeline）
- （原）pipeline 独立运行：有意不做（保持不变）
- （原）既有项目旧版 `.md2zh_tools/config.json`：按 SKILL.md「历史遗留」说明直接删除
- （新增）无


### 2026-08-05：配置全局化（废弃项目级 .md2zh_tools/config.json）

| 类别 | 内容 |
|------|------|
| 流程改动 | 配置从两级（skill 级 `scripts/config.py` + 项目级 `.md2zh_tools/config.json`）合并为**一份全局配置** `scripts/config.py`：`md2zh_config` = `python_path`（必填）+ `ambiguous_content_decider`（user/ai）；用户决策：configure 子命令保留（改写全局）、python 配置与 web2md 对齐（只留 `python_path`，无 mode；auto 探测仅向导兜底）、旧 config.json 删除 |
| 脚本改动 | `md2zh_pipeline.py`：新增 `global_config_path()` / `load_global_config()`（exec 读取 config.py，缺失/损坏 → ConfigRequiredError 提示向导）/ `CONFIG_PY_TEMPLATE`（configure 原子写回）；删除 `project_config_path` / `load_project_config` / `python_candidates` / `PYTHON_MODES` 与 mode 分支；`resolve_python(python_path)` 显式路径校验 + 缺省探测当前解释器；`ensure_current_python(config)` 直接校验 sys.executable == config.python_path；`configure` 去掉 `project_root` 参数（无使用者）；`extract`/`configure` 加 `--config`（CLI 临时覆盖，selftest 隔离用） |
| 配置 | `config.example.py` 增 `ambiguous_content_decider` 键 + 借鉴 web2md 注释质量（防坑说明）；真实 `scripts/config.py` 补 decider 默认 user、python_path 保留现值 |
| 测试 | `selftest.py`：`--config` 指向临时文件隔离真实配置；`test_configure_writes_project_config` → `test_configure_writes_global_config`（exec 读回校验 python_path + decider）→ 10 用例全绿（exit=0） |
| 文档 | SKILL.md 配置向导章节合并为单级、configure 命令去掉 `--python-mode`、产物结构图删 config.json、补"历史遗留 config.json 不再读取"；translation-rules.md 读配置表述改为 skill 级 |

**过程要点**：
- 踩坑 1：`CONFIG_PY_TEMPLATE` 用 `.format()` 时字面花括号 `{`/`}` 被当字段 → KeyError，转义为 `{{`/`}}` 后修复
- 踩坑 2：configure 自动探测初版扫候选列表（.venv/venv → PATH → py → current），多 Python 机器上先命中 PATH 的 `C:\Python314\python.EXE` 而当前解释器是 python311 → `same_executable` 校验拒绝、configure 失败；参考 web2md 模式（脚本不做探测，候选扫描是 AI 向导的工作）修正为**缺省只探测当前解释器**（AI 正用它跑 pipeline，必然满足"全程同一个 Python"），删除 `python_candidates`，`configure` 去掉 `project_root` 参数
- `--config` 参数经 parents 共享 parser 加到 configure/extract（唯二读配置的命令）；其余命令用 state 内 snapshot（runtime/decision_source），不读配置
- 全 skill grep 复核无 `config.json` / `python-mode` / `PYTHON_MODES` 残留；工作区内无遗留 config.json
- 向导禁止预填约束不受影响：configure 写入的是用户确认后的值

**遗留事项更新**：
- （原）术语表文件化：仍待做（模型内存跨块保留）
- （原）逐行断句的翻译质感：不变（分块契约限制，未改 pipeline）
- （原）pipeline 独立运行：有意不做（保持不变）
- （新增）既有项目若残留旧版 `.md2zh_tools/config.json`：不再读取，按 SKILL.md「历史遗留」说明直接删除


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
- selftest 全部用例全绿
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

- **术语表文件化**：已落地 `glossary.json`，支持任务级保存、树级共享及归档快照（2026-08-11）
- **逐行断句的翻译质感**：分块契约单行 segment 模式限制，未改 pipeline（如需流畅断行需跨行合并，改动大）
- **pipeline 独立运行**：有意不做（用户明确不需要——翻译核心依赖 AI 助手会话，pipeline 只是编排工具）
- **归档增长**：同名归档不覆盖且不自动裁剪，磁盘空间需按用户策略人工管理（2026-08-11）
- **审阅语义**：`completion.json` 能验证 review 产物及哈希完整性，无法机器判断人工审阅质量（2026-08-11）
