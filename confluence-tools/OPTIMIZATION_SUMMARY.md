# confluence-tools 优化总结

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

### 2026-08-03：md_import 自动目录宏（toc）

| 类别 | 内容 |
|------|------|
| 新功能 | 页面子标题（H2~H6）数量达到阈值时，导入时自动在正文顶部插入 Confluence 目录宏（`<ac:structured-macro ac:name="toc">`） |
| 配置 | `import_config.toc_enabled`（开关，默认 true）+ `import_config.toc_min_headings`（阈值，默认 4，用户确认）；H1 视为页面标题本身不计入 |
| 脚本改动 | `md_import.py` 新增 `_maybe_add_toc`（统计转换后 HTML 的 `<h2>`~`<h6>` 标签数，达标在正文最前插 toc 宏）；`_convert_md_to_storage` 末尾调用，单文件与 --dir 树导入共用 |
| 测试 | selftest +3 用例（达标插入 / 不达标不插入 / 开关关闭），58 用例全绿 |
| 验证 | 73596940（Commands）重跑导入，标题多自动补目录宏 |
| 同步 | config.example.py（+2 键）、config.py（+2 键）、SKILL.md（配置向导第 11 项、后续编号顺延） |

**过程要点**：
- toc 宏是自闭合标签，引入后暴露宏保护正则在自闭合场景的缺陷（见 KNOWN_ISSUES.md 2026-08-03，修复后 selftest 补 `test_self_closing_macro_does_not_swallow_images`）

**遗留事项更新**：
- （原）无
- （新增）toc 阈值（toc_min_headings）暂为全局配置，未做按页面覆盖

### 2026-08-03：文件夹树批量导入（--dir 模式）

| 类别 | 内容 |
|------|------|
| 新功能 | 把 web2md 输出的目录结构（标题文件夹 + 同名 .md + .assets）整棵导入 Confluence，保留层级（子文件夹 = 子页面，挂父页面下，任意深度） |
| 配置 | `import_config.tree_import`（功能开关，默认 false，配置向导首次询问）+ `import_config.fix_hierarchy`（confirm/auto/off，默认 confirm，移动前预览确认） |
| 脚本改动 | `_scan_tree`（含 .md 文件夹=节点、同名 md 优先、多 md 跳过提示、.assets 排除、无 md 中间文件夹跳级）→ `_build_plan`（只读查重+父级判定）→ `_execute_plan`（深度优先：新建挂父级/更新/按策略移动+ancestors、父级失败子节点跳过、_title_id_map 解析）；`_convert_md_to_storage` 抽取供单文件与树共用；`_update_page` 加可选 ancestors（None 保持/[] 移根/id 移父，单文件零影响） |
| CLI | `--dir <根>` / `--plan-only`（只读计划）/ `--yes`（跳过确认）/ `--fix-hierarchy`；--space/--align 默认从 config.py 读取 |
| 测试 | selftest +9 用例，55 用例全绿 |

**过程要点**：
- 用户决策：命中已有页面按 fix_hierarchy 决定是否移动（会影响空间内同名页面）；tree_import 默认关闭，开启需用户确认
- 与 md2zh 树形翻译镜像树（`<根名>_zh/`）对接：`web2md 抓取 → md2zh 翻译 → md_import --dir 导入` 完整流水线

**遗留事项更新**：
- （原）无
- （新增）树导入无断点续传（重跑会重新计划，幂等安全但重复查重）

### 2026-08-02：脚本完整性检查 + 恢复流程（容错增强）

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md「首次运行」新增脚本完整性检查（md_import.py / math_upgrade.py / common.py / selftest.py 缺失时提示按 git 恢复，不直接重写）；「容错与安全」新增脚本文件恢复条目（**先与用户确认是否需要恢复，确认后才执行** → git status 判定 → git checkout 恢复 → 版本丢失警示 → config.py 无法恢复需重跑向导） |

**过程要点**：
- 配置向导原本只检查 config.py，不检查脚本文件——脚本被删时无提示，执行直接报"文件不存在"
- git 恢复的是最近提交版本，未提交改动会丢失——重要改动需及时 commit（由用户决定提交时机）

**遗留事项更新**：
- （原）无
- （新增）无

### 2026-08-02：md_import 交互流程修正：配置优先、不再询问

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md 交互流程改为"直接读取 config.py 执行，不询问；用户主动提及变更才用 CLI 参数覆盖"；新增"取值优先级：用户显式指定 > config.py > 代码默认值"；删除冗余的"脚本自动：已存在→更新"步骤描述（属脚本内部默认逻辑） |

**过程要点**：
- 问题：交互流程仍是早期版本（每次导入询问父页面/标题/空间），与配置向导"后续调用不再询问"矛盾——实际导入时每次三连问
- 说明：脚本本身早已支持该优先级（配置化时实现），本次仅修正文档描述，无代码改动

**遗留事项更新**：
- （原）无
- （新增）无

### 2026-08-02：Claude 措辞通用化 + claude_verify → ai_verify 重构

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md / config.example.py / math_upgrade.py 中"Claude 验证 / Claude 依赖 / 不用 Claude"等 → "AI 助手 / AI 验证 / 不依赖 AI 助手" |
| 脚本改动（破坏性） | `upgrade_config.claude_verify` → `ai_verify`；CLI `--claude-verify` / `--no-claude-verify` → `--ai-verify` / `--no-ai-verify`（同步 math_upgrade.py / config.example.py / config.py / selftest.py / SKILL.md 五处） |
| 流程改动 | README 标题 `Claude Code Skills` → `AI Agent Skills`，导语/安装章节标注"AI 助手（Claude Code / Reasonix 等）" |
| 测试 | 42 用例全绿（键名改动无回归） |

**过程要点**：
- 动机：skill 原为 Claude 时代编写，文档与配置特指 Claude；改为中性表述，任何 AI 助手均可执行
- 旧配置键 `claude_verify` 与旧参数已失效，历史命令需改用 `--ai-verify`；config.py 的键名已同步迁移

**遗留事项更新**：
- （原）无
- （新增）无

### 2026-08-02：md_import 配置化：default_parent_id / default_page_name

| 类别 | 内容 |
|------|------|
| 脚本改动 | `md_import.py` 新增读取 `import_config.default_parent_id`（默认父页面 ID，留空不挂父级）与 `import_config.default_page_name`（默认页面标题，留空取 md 文件名）；取值优先级 **CLI 参数（--parent-id / --page-name）> 配置 > 默认值** |
| 流程改动 | 父级**仅新建页面生效**（已存在页面按标题整空间查重更新、位置不变）；`--page-name` 参数保留（用户决策） |
| 测试 | selftest +3 用例（配置读取/新建挂父级/CLI 覆盖），42 用例全绿 |
| 同步 | config.example.py（+2 键）、scripts/config.py（+2 键空值）、SKILL.md（配置向导第 7/8 项、交互步骤、CLI 注释、文件结构补 OPTIMIZATION_SUMMARY 行、自进化章节新增优化前读取/优化后追加规则） |
| 文档清理 | README 与本文档第六节用例数 39→42；内网地址改占位符（`http://<confluence-server>:8090`）；空间统计标注时点 |

**过程要点**：
- 用户决策：--page-name 保留 + 新增 default_page_name 配置（非删除参数）

**遗留事项更新**：
- （原）无
- （新增）README 未提 CLI 参数细节（保持现状）；config.py 中新键为空值，需使用时手动填入

### 2026-08-01：confluence-tools 大优化交接（初始工程化）

| 类别 | 内容 |
|------|------|
| 脚本改动 | `common.py`：`build_block_template`（left/center 宏模板）、`request_with_retry`（429/5xx 指数退避重试 + timeout）、`collect_space_pages`（分页收集）、`load_config`（CONFLUENCE_TOKEN 环境变量覆盖） |
| 脚本改动 | `md_import.py`：公式对齐配置（`import_config.math_align` + `--align`）、标题内存匹配（绕开 CQL title bug）、版本号流程修复（原硬编码 version=2 必 409）、409 自动重试、占位符随机 token、base64 图片跳过、`\*` 控制序列归一化、图片失败汇总报告 |
| 脚本改动 | `math_upgrade.py`：原生 `mathblock + alignment=left`（替代 mathinline+`\displaystyle` hack）、`_apply_alignment` 幂等（防版本虚涨）、span 剥壳保留内容（防 XHTML 400）、`_check_xhtml_balance` 标签配对校验（剔除 CDATA/注释防误报）、`_sanitize_latex`（`\*`→`*`）、批量遇错继续 + `--stop-on-error`、拉取失败兜底重试 |
| 测试 | `selftest.py` 39 个离线用例（mock 配置与网络），修改脚本后必须全绿 |
| 文档同步 | SKILL.md（配置向导规则收紧、对齐配置、容错与安全、自进化流程）／ KNOWN_ISSUES.md（8 条问题记录）／ README.md（confluence-tools 章节）／ config.example.py（math_align）／ 根目录 .gitignore（迁移 + `/config.py` 防误提交） |

**过程要点**：
- 真实环境验证：ES 空间 204/204、ALG 空间 50/50、新空间 111/111 全量升级通过；mathblock `alignment=left` 在 Confluence 9.2.1 服务器实测支持
- 协作风格（10 条）与遗留事项见下方章节，本批确立后沿用至今

**遗留事项更新**：
- （原）无
- （新增）草稿清理不可行（REST API 无法删草稿）；P3 有意不做：atlassian-python-api 依赖、批量并发处理

## 二、验证结果

- ES 空间 204/204、ALG 空间 50/50、新空间 111/111 全量升级通过
- mathblock `alignment=left` 在 Confluence 9.2.1 服务器实测支持
- toc 自动目录宏真实验证：73596940（Commands）重跑导入，标题多自动补目录宏
- 多轮真实页面导入/升级/修复验证（含 --dir 树导入、同名附件更新、自闭合宏修复后回归），全部闭环
- selftest：58 用例全绿（截至 2026-08-03，含 toc +3 用例）

## 三、过程中的 bug 序列（按时间）

1. **硬编码 version=2** → 更新已有页面必 409 → 返回真实版本号
2. **全局删 `<span>`** → 破坏编辑器格式 → 只删 math class
3. **stdout 双重 wrap** → 多模块 import 时 print 崩溃 → 幂等化
4. **`$PWD / $OLDPWD` 误识别为公式** → 正则三规则（开头 $ 后禁空白、闭合 $ 前禁空白、内容禁 `<>`）
5. **`\*` 未定义控制序列** → `_sanitize_latex` 归一化
6. **span 嵌套删除 → XHTML 400** → 剥壳保留内容 + 禁嵌套匹配
7. **XHTML 检查器 CDATA 误报**（`<mmc::Irlock>` 当标签）→ 剔除 CDATA/注释
8. **`_apply_alignment` 非幂等 → 版本虚涨**（TECS v2→v6 内容不变）→ 已 left 跳过
9. **行内公式含不等式（< >）未被识别 → 导入 400** → md_import 两处放宽（math_upgrade 不放宽，见 KNOWN_ISSUES 08-02）
10. **mathblock CDATA 内 `](0)` 被图片正则误判** → `_convert_md_links` 保护宏区域
11. **同名附件上传 400 → 图片引用被覆盖** → `GET 查附件 id` + `POST {id}/data` 更新
12. **自闭合宏（toc）破坏保护段分割** → 宏保护正则二选一（自闭合/成对）

## 四、协作风格（本仓库通用约定）

1. **先方案后动手**：写代码前输出方案（含默认值/影响范围），用户确认后才实施；方案被否就重出
2. **任务清单跟踪**：多步任务用任务列表推进，不半途遗忘
3. **测试先行**：所有代码改动必须 selftest 全绿才交付；测试也随功能同步补
4. **真实环境验证**：代码改完在真实服务器验证（建测试页/跑批量），**验证产物用后即清**，不留残留
5. **证据驱动排查**：遇到问题先拉数据/日志定位根因（如 debug 目录判断失败阶段），不猜
6. **文档同步**：代码、配置模板、SKILL.md、KNOWN_ISSUES、README 保持一致
7. **诚实报告**：做过什么、没做什么、验证到什么程度，如实说明
8. **安全优先**：token 不落盘不打印；含真实凭据的文件不读全文；删除/批量操作被安全机制拦截时停下向用户解释，等明确授权
9. **一次性脚本即用即删**：临时验证脚本跑完删除，不留在 scripts/
10. **配置驱动设计**：脚本从 config.py 自给自足，无参执行；配置项改文件即生效

## 五、遗留事项

- **草稿清理**：Confluence 9.2.1 REST API 无法删除页面草稿（尝试 5 种方式均失败，草稿是编辑器私有机制）。"未发布更改"标记的草稿无害，关闭浏览器标签页随会话清理；顽固残留需管理员后台处理
- **P3 未做**（有意不做的）：atlassian-python-api 依赖、批量并发处理
- **README 未提 CLI 参数细节**（保持现状）
- **config.py 新键空值**（default_parent_id / default_page_name 等）需使用时手动填入
- **树导入无断点续传**（重跑重新计划，幂等安全但重复查重）
- **toc 阈值无按页面覆盖**（全局配置）

## 六、环境速查

- Confluence：9.2.x（http://<confluence-server>:8090），PAT Bearer 认证
- Python：`<python 解释器路径>`（需安装 requests / markdown2）
- 测试命令：`"<python>" scripts/selftest.py` → 全部用例全绿（截至 2026-08-03 为 58 用例）
