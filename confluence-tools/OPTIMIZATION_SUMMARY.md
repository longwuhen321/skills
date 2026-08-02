# confluence-tools 优化总结（2026-08-01）

> 本文档是本次大优化的工作交接摘要：记录做了什么、当前状态、以及协作风格，
> 供后续会话快速对齐，避免重复探索。

## 一、本次优化范围

### 代码层（5 个脚本 + 39 个测试用例）

| 文件 | 核心改动 |
|------|---------|
| `common.py` | `build_block_template`（left/center 宏模板）、`request_with_retry`（429/5xx 指数退避重试 + timeout）、`collect_space_pages`（分页收集）、`load_config`（CONFLUENCE_TOKEN 环境变量覆盖） |
| `md_import.py` | 公式对齐配置（`import_config.math_align` + `--align`）、标题内存匹配（绕开 CQL title bug）、版本号流程修复（原硬编码 version=2 必 409）、409 自动重试、占位符随机 token、base64 图片跳过、`\*` 控制序列归一化、图片失败汇总报告 |
| `math_upgrade.py` | 原生 `mathblock + alignment=left`（替代 mathinline+`\displaystyle` hack）、`_apply_alignment` 幂等（防版本虚涨）、span 剥壳保留内容（防 XHTML 400）、`_check_xhtml_balance` 标签配对校验（剔除 CDATA/注释防误报）、`_sanitize_latex`（`\*`→`*`）、批量遇错继续 + `--stop-on-error`、拉取失败兜底重试 |
| `debug_utils.py` | 未改动 |
| `selftest.py` | 39 个离线用例（mock 配置与网络），修改脚本后必须全绿 |

### 文档层（四方同步）

SKILL.md（配置向导规则收紧、对齐配置、容错与安全、自进化流程）／ KNOWN_ISSUES.md（8 条问题记录）／ README.md（confluence-tools 章节）／ config.example.py（math_align）／ 根目录 .gitignore（迁移 + `/config.py` 防误提交）。

## 二、真实环境验证结果

- ES 空间 204/204、ALG 空间 50/50、新空间 111/111 全量升级通过
- mathblock `alignment=left` 在 Confluence 9.2.1 服务器实测支持
- 多轮真实页面导入/升级/修复验证，全部闭环

## 三、过程中修复的 bug 序列（按时间）

1. **硬编码 version=2** → 更新已有页面必 409 → 返回真实版本号
2. **全局删 `<span>`** → 破坏编辑器格式 → 只删 math class
3. **stdout 双重 wrap** → 多模块 import 时 print 崩溃 → 幂等化
4. **`$PWD / $OLDPWD` 误识别为公式** → 正则三规则（开头 $ 后禁空白、闭合 $ 前禁空白、内容禁 `<>`）
5. **`\*` 未定义控制序列** → `_sanitize_latex` 归一化
6. **span 嵌套删除 → XHTML 400** → 剥壳保留内容 + 禁嵌套匹配
7. **XHTML 检查器 CDATA 误报**（`<mmc::Irlock>` 当标签）→ 剔除 CDATA/注释
8. **`_apply_alignment` 非幂等 → 版本虚涨**（TECS v2→v6 内容不变）→ 已 left 跳过

## 四、协作风格（本会话遵循的工作方式）

1. **先方案后动手**：写代码前输出方案（含默认值/影响范围），用户确认后才实施；方案被否就重出
2. **任务清单跟踪**：多步任务用 TaskCreate 列清单，逐步推进，不半途遗忘
3. **测试先行**：所有代码改动必须 selftest 全绿才交付；测试也随功能同步补
4. **真实环境验证**：代码改完在真实服务器验证（建测试页/跑批量），**验证产物（测试页、临时脚本）用后即清**，不留残留
5. **证据驱动排查**：遇到问题先拉数据/日志定位根因（如 debug 目录判断失败阶段），不猜
6. **文档同步**：代码、配置模板、SKILL.md、KNOWN_ISSUES、README 保持一致；发现的问题记录到 KNOWN_ISSUES（现象/根因/修复/排查方法）
7. **诚实报告**：做过什么、没做什么、验证到什么程度，如实说明；修复后明确告诉用户需要验证的部分
8. **安全优先**：token 不落盘不打印；含真实凭据的文件不读全文；删除/批量操作被安全机制拦截时停下向用户解释，等明确授权
9. **一次性脚本即用即删**：临时验证脚本跑完删除，不留在 scripts/
10. **配置驱动设计**：脚本从 config.py 自给自足，无参执行；配置项改文件即生效

## 五、遗留事项

- **草稿清理**：Confluence 9.2.1 REST API 无法删除页面草稿（尝试 5 种方式均失败，草稿是编辑器私有机制）。"未发布更改"标记的草稿无害，关闭浏览器标签页随会话清理；顽固残留需管理员后台处理
- **P3 未做**（有意不做的）：atlassian-python-api 依赖、批量并发处理
- **配置向导**：SKILL.md 已收紧规则（必需项缺失即中断、禁止预填历史配置、先问后找），新会话跑 `/confluence-tools` 时应遵守

## 六、环境速查

- Confluence：9.2.1（http://<confluence-server>:8090），PAT Bearer 认证
- Python：`D:/path/to/python/python.exe`（有 requests/markdown2）
- 空间（2026-08-01 统计）：ES（204 页）、ALG（50 页）、数学知识空间（111 页）
- 测试命令：`"<python>" scripts/selftest.py` → 42 用例全绿（截至当前，含后增的 3 个配置用例）

## 七、后续优化记录

> 按 SKILL.md 自进化规则追加：每次 skill 自我优化后，把改动/问题/遗留更新记录于此。

### [2026-08] md_import 配置化：default_parent_id / default_page_name

- **改动**：`md_import.py` 新增读取 `import_config.default_parent_id`（默认父页面 ID，留空不挂父级）与 `import_config.default_page_name`（默认页面标题，留空取 md 文件名）；取值优先级 **CLI 参数（--parent-id / --page-name）> 配置 > 默认值**
- **行为确认（用户决策）**：父级**仅新建页面生效**（已存在页面按标题整空间查重更新、位置不变）；`--page-name` 参数保留
- **同步文件**：`config.example.py`（+2 键）、`scripts/config.py`（+2 键空值）、`SKILL.md`（配置向导第 7/8 项、交互步骤、CLI 注释、文件结构补 OPTIMIZATION_SUMMARY 行、自进化章节新增优化前读取/优化后追加规则）
- **测试**：`selftest.py` +3 用例（配置读取/新建挂父级/CLI 覆盖），42 用例全绿
- **文档清理**：README 与本文档第六节用例数 39→42；本文档第六节内网地址改占位符（`http://<confluence-server>:8090`）；空间统计标注时点
- **遗留**：README 未提 CLI 参数细节（保持现状）；config.py 中新键为空值，需使用时手动填入

### [2026-08] Claude 措辞通用化 + claude_verify → ai_verify 重构

- **动机**：skill 原为 Claude 时代编写，文档与配置特指 Claude；改为中性表述，任何 AI 助手（Claude Code / Reasonix 等）均可执行
- **文档措辞**：SKILL.md / config.example.py / math_upgrade.py 中"Claude 验证 / Claude 依赖 / 不用 Claude"等 → "AI 助手 / AI 验证 / 不依赖 AI 助手"
- **键名重构（破坏性）**：`upgrade_config.claude_verify` → `ai_verify`；CLI `--claude-verify` / `--no-claude-verify` → `--ai-verify` / `--no-ai-verify`（同步 math_upgrade.py / config.example.py / config.py / selftest.py / SKILL.md 五处）
- **README**：标题 `Claude Code Skills` → `AI Agent Skills`，导语/安装章节标注"AI 助手（Claude Code / Reasonix 等）"
- **测试**：42 用例全绿（键名改动无回归）
- **注意**：旧配置键 `claude_verify` 与旧参数已失效，历史命令需改用 `--ai-verify`；config.py 的键名已同步迁移

### [2026-08] md_import 交互流程修正：配置优先、不再询问

- **问题**：SKILL.md 交互流程仍是早期版本（每次导入询问父页面/标题/空间），与配置向导"后续调用不再询问"矛盾——实际导入时每次三连问
- **修复**：交互流程改为"直接读取 config.py 执行，不询问；用户主动提及变更才用 CLI 参数覆盖"；新增"取值优先级：用户显式指定 > config.py > 代码默认值"；删除冗余的"脚本自动：已存在→更新"步骤描述（属脚本内部默认逻辑）
- **说明**：脚本本身早已支持该优先级（上一轮配置化），本次仅修正文档描述，无代码改动

### [2026-08] 脚本完整性检查 + 恢复流程（容错增强）

- **问题**：配置向导只检查 config.py，不检查脚本文件——脚本被删时无提示，执行直接报"文件不存在"
- **修复**：SKILL.md「首次运行」新增脚本完整性检查（md_import.py / math_upgrade.py / common.py / selftest.py 缺失时提示按 git 恢复，不直接重写）；「容错与安全」新增脚本文件恢复条目（**先与用户确认是否需要恢复，确认后才执行** → git status 判定 → git checkout 恢复 → 版本丢失警示 → config.py 无法恢复需重跑向导）
- **注意**：git 恢复的是最近提交版本，未提交改动会丢失——重要改动需及时 commit（由用户决定提交时机）

### [2026-08] 文件夹树批量导入（--dir 模式）

- **能力**：把 web2md 输出的目录结构（标题文件夹 + 同名 .md + .assets）整棵导入 Confluence，保留层级（子文件夹 = 子页面，挂父页面下，任意深度）
- **配置**：`import_config.tree_import`（功能开关，默认 false，配置向导首次询问）+ `import_config.fix_hierarchy`（confirm/auto/off，默认 confirm，移动前预览确认）
- **实现**：`_scan_tree`（含 .md 文件夹=节点、同名 md 优先、多 md 跳过提示、.assets 排除、无 md 中间文件夹跳级）→ `_build_plan`（只读查重+父级判定）→ `_execute_plan`（深度优先：新建挂父级/更新/按策略移动+ancestors、父级失败子节点跳过、_title_id_map 解析）；`_convert_md_to_storage` 抽取供单文件与树共用；`_update_page` 加可选 ancestors（None 保持/[] 移根/id 移父，单文件零影响）
- **CLI**：`--dir <根>` / `--plan-only`（只读计划）/ `--yes`（跳过确认）/ `--fix-hierarchy`；--space/--align 默认从 config.py 读取
- **测试**：selftest +9 用例，55 用例全绿
- **注意**：命中已有页面按 fix_hierarchy 决定是否移动（会影响空间内同名页面）；tree_import 默认关闭，开启需用户确认

### [2026-08] md_import 自动目录宏（toc）

- **能力**：页面子标题（H2~H6）数量达到阈值时，导入时自动在正文顶部插入 Confluence 目录宏（`<ac:structured-macro ac:name="toc">`）
- **配置**：`import_config.toc_enabled`（开关，默认 true）+ `import_config.toc_min_headings`（阈值，默认 4，用户确认）；H1 视为页面标题本身不计入
- **实现**：`md_import.py` 新增 `_maybe_add_toc`（统计转换后 HTML 的 `<h2>`~`<h6>` 标签数，达标在正文最前插 toc 宏）；`_convert_md_to_storage` 末尾调用，单文件与 --dir 树导入共用
- **测试**：selftest +3 用例（达标插入 / 不达标不插入 / 开关关闭），58 用例全绿
- **同步文件**：config.example.py（+2 键）、config.py（+2 键）、SKILL.md（配置向导第 11 项、后续编号顺延）、OPTIMIZATION_SUMMARY.md（本段）
- **真实验证**：73596940（Commands）重跑导入，标题多自动补目录宏
