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

### 2026-08-11：安全工程门禁与页面全链路可靠性补强

| 类别 | 内容 |
|------|------|
| 安全与工程 | 新增 `scripts/config_parser.py`，运行期与配置同步检查统一使用 AST + `ast.literal_eval` 解析五个 `*_config` 字典，拒绝导入、函数调用和副作用代码；新增 `scripts/package_check.py`，路径优先拒绝真实配置、logs、缓存/虚拟环境、环境文件、链接、凭据文件名和常见 Token；新增 `scripts/dependency_check.py`，一次实际导入并汇总 `requests`、`markdown2`、`beautifulsoup4`、`markdownify`，脚本不自行安装，缺失时先申请用户批准 |
| 页面定位与并发 | 页面查找改为 `FOUND / NOT_FOUND / ERROR` 三态，查询异常禁止按“不存在”继续创建；同名多候选默认中止，支持按真实父页面过滤或显式 `--page-id`；导入更新记录源版本，409 默认中止，仅显式 `--force` 才拉取最新版本重试一次 |
| 公式安全 | `math_upgrade --confirm` 在确认前重新拉取页面并校验源版本与 SHA256，任一变化都必须重新生成或中止，不能用 `--force` 绕过；默认要求零公式残留，显式容忍模式输出残留位置；center 删除旧 alignment，left 插入或替换；无效转义 docstring 已修正 |
| 导入导出完整性 | 附件上传/下载、树节点和批量失败统一累计并令 CLI 非零；公共分页器遍历全部页面并传播请求错误；空间导出统一调用非递归单页核心，避免重复子树；代码宏占位期间整理空行，还原后不再全局归一化 |
| 格式与路径 | 页面目录加入稳定 page ID；附件使用安全 basename 并校验解析路径位于 assets 内；导入识别独占 `[toc]` 且避免重复目录宏；未知宏保留正文及转义后的原始 XHTML 注释，`ri:url` 与外链图片地址不丢失 |
| 树形流程 | 每次树导入只构建一次页面索引，计划固化 page ID/version 并拒绝同一 page ID 被多个节点占用；checkpoint 支持 `--resume`，失败节点保留版本信息供续传 |
| 测试与文档 | 固化 `python -X utf8` 验证入口和测试能力矩阵（配置、退出码、日志隔离、CLI、依赖缺失、Windows 编码）；修正历史测试路径；最终 151/151，通过 17 个允许文件 staging packaging check、三入口 help/`SyntaxWarning`、四依赖实际导入、LF 与 skill 结构验证 |

**过程要点**：
- `md_import` 的 409 `--force` 只用于用户明确要求后的单次并发重试；`math_upgrade --confirm` 不提供 force 绕过，防止旧 `after.html` 覆盖已变化页面。
- 发布检查先按路径/元数据拒绝并剪枝，再读取允许文本；Python 文件用 AST 扫真实敏感字面量，其他文本才允许无引号 Token，`X-Atlassian-Token: nocheck` 作为固定 CSRF 哨兵放行但真实值仍拦截。
- 页面/附件失败采用“部分结果可保留、整体命令非零”的契约，调用方不能把已写入部分页面误报成全量成功。

**遗留事项更新**：
- （原）树导入无断点续传、每次重复查重 → **已完成**（单次索引 + 固化计划 + checkpoint/`--resume`，2026-08-11）。
- （原）未知宏统一降级且外链图可能丢失 → **已完成**（正文 + 原始 XHTML 注释 + `ri:url`/外链图片）。
- （新增）本轮只做离线 mock，Confluence Data Center 的真实权限、API 差异和大空间分页仍需受控实机验证；敏感值扫描为保守启发式，不替代专业密钥扫描器。

### 2026-08-08：测试目录更名（scripts/debug/ → scripts/test/）

| 类别 | 内容 |
|------|------|
| 流程改动 | 测试目录从 `scripts/debug/` 更名 `scripts/test/`——目录里存的是测试文件，`test/` 比 `debug/` 自描述；与日志目录更名同逻辑，至此全项目消除 debug 语义歧义（`logs/` 日志、`scripts/test/` 测试） |
| 磁盘 | `scripts/debug/` → `scripts/test/`（内容不动） |
| 文档 | SKILL.md 3 处 `scripts/debug` → `scripts/test`（含目录树 `│ └── test/`）；「本地测试（git 不追踪）」→「git 追踪」 |
| 测试 | selftest 从 `scripts/test/selftest.py` 运行 107 全绿（相对路径定位自动跟随，零代码改动） |

**过程要点**：
- **⚠️ sed 误伤**：全局替换误伤 `scripts/debug_utils.py` → `scripts/test_utils.py`（SKILL.md 脚本完整性检查 L23），已修复——真实文件名与测试目录同名前缀，全局替换需加边界
- 与 web2md / md2zh 同步更名（三 skill 统一）；`debug_utils.py` 文件名保留（调试工具，非测试）

**遗留事项更新**：
- （新增）历史条目仍写 `scripts/debug/`，属当时事实，保留不改


### 2026-08-08：日志目录更名（debug/ → logs/）

| 类别 | 内容 |
|------|------|
| 脚本改动 | `math_upgrade.py` / `md_export.py` / `md_import.py` 各 2 处 `'debug'` → `'logs'`（路径字符串）；`debug_utils.py` `cleanup_debug` 默认参 `'debug'` → `'logs'`（标识符 `debug_dir`/`debug_utils`/`debug_root` 不动） |
| 文档 | SKILL.md 2 处日志语境 `debug/` → `logs/`（调试日志节 + 文件结构树）；`scripts/debug/`（测试）保留 |
| 磁盘 | `confluence-tools/debug/` → `confluence-tools/logs/`（内容不动） |
| gitignore | `/*/debug` → `/*/logs`（全局规则覆盖） |
| 测试 | `test_export_saves_storage_debug` 断言 `debug/export` → `logs/export`；selftest 107 全绿 |

**过程要点**：
- 更名动机：`debug/` 与 `scripts/debug/`（测试）同名造成语义混淆；`logs/` 自描述「日志」
- 与 md2zh 同步更名（三 skill 统一：日志归 `<skill>/logs/`）；`debug_dir` 等标识符保留（语义仍是"调试目录"，无歧义）

**遗留事项更新**：
- （新增）历史条目仍写 `debug/`，属当时事实，保留不改


### 2026-08-08：skill 文档自描述规范化

| 类别 | 内容 |
|------|------|
| 流程改动 | 应用「skill 文档自描述」规范：结构/流程说明必须自描述——规则写全本文件内、复杂结构用「占位符 + 示例图」、不引用其他 skill 的规则细节、不用具体实例名（真实项目/平台名）；该规范同日于 md2zh 先行确立落地，本 skill 跟进 |
| 落地清单 | ① md_export 输出结构「与 web2md 输出、md_import --dir 目录结构一致，导出的目录树**可直接用 --dir 反向导回** Confluence」→ 删 web2md 引用 + 删全部连通断言，改为**自描述输出示例图**（`<输出根>/<页面A>/<页面A>.md + <页面A>.assets/`，页面无图不产生 assets；子页面嵌套保留层级）——不再断言与其他 skill 的兼容性（结构兼容与否由读者自行判断，README 已承担跨 skill 关系说明）；② 配置确认后「写入 Bash allow 规则（Claude Code 为 .claude/settings.local.json，Reasonix 为 reasonix.toml 的 [permissions].allow）」→ 改为「写入当前 AI 助手平台的免确认白名单（按平台方式设置）」，不绑具体平台 |
| 判定标准 | **执行依赖**的跨 skill 引用 → 删（自含规则）；**对接/兼容说明**（目录结构一致）→ 自描述化或删；**真实默认值/命令值**（`confluence_export`、`--confirm latest`）→ 保留；**禁止项清单**（settings.json 等"禁止读取"对象）→ 保留 |

**过程要点**：
- 与 md2zh 清理同款问题：md_export 的「与 web2md 输出…可直接反向导回」是跨 skill 引用 + 连通暗示（skill 独立不连通）
- **⚠️ 教训 1（首改不彻底）**：第一轮修改只删了 web2md 引用和「直接」二字，却保留了「输入一致，可反向导入」的连通断言——换说法重申了要删的东西。删断言必须删干净，不留"化妆式修改"（用户点破后，改为自描述示例图 + 不再断言任何兼容性，兼容与否由读者自行判断）
- **⚠️ 教训 2（断言必须读代码核实）**：改 md_export 输出结构前未读代码，沿用原文兼容断言。读 md_export.py:325-345,453-463 后确认：`<标题>.md` 与文件夹同名、`.assets/` 页面无图时不产生、子页面嵌套——结构与 `_scan_tree` 的"同名 md 优先"确实兼容，但兼容性是读者的判断，本 skill 不应自行断言
- **⚠️ 教训 3（规范须应用于自身输出）**：最初记录本条目时写了「（见 md2zh/OPTIMIZATION_SUMMARY.md 2026-08-08 条目）」——在禁止跨引用的规范条目里写了跨文档指针，规范没应用到自己的输出。规范定义必须自含，只留"同日于 md2zh 先行确立落地"的事实陈述
- 平台配置段（settings.local.json / reasonix.toml）是具体平台引用，对不用的用户是噪音 → 泛化为「当前 AI 助手平台的免确认白名单」
- 保留项判定：`confluence_export`（真实默认输出目录名）、`--confirm latest`（真实命令值）、独立运行示例（用法展示，非结构说明）、L31/L327 的 settings.json（"禁止读取"清单，非引用）

**遗留事项更新**：
- （新增）「skill 文档自描述」规范落地完成（本 skill SKILL.md 已无跨引用、无连通断言）


### 2026-08-08：配置同步强制门禁（check_config_sync.py，五分组全检查）

| 类别 | 内容 |
|------|------|
| 新脚本 | `check_config_sync.py`：对比 `scripts/config.py` 与 `config.example.py` 的**全部五分组**（`common_config` / `import_config` / `upgrade_config` / `export_config` / `debug_config`）**键集合 + 值类型**（`exec` 解析，与 `load_config()` 同源）；三类差异 `missing` / `extra` / `type` 逐条列出（含分组名）；退出码 0 = 同步 / 1 = 有差异 / 2 = 文件缺失或损坏；`--config-text` 从 stdin 读取（配置向导写入后复核）；`--groups` 逗号分隔指定分组（默认自动发现 example 中全部 `*_config` 分组） |
| 流程改动 | SKILL.md「首次运行」节：`config.py` 存在时先跑门禁，不一致（退出码 1/2）**中断任务**；脚本完整性检查补 `check_config_sync.py`；文件结构段同步更新 |
| 测试 | `debug/test_config_sync.py` 9 用例（真实文件同步通过 / 临时对同步 / 缺分组 / 缺键 / 多余键 / 类型不符 / 文件缺失 / 损坏 / stdin 模式）；selftest.py 改为 suite 装载（`loadTestsFromModule` + 显式加 ConfigSyncTests）→ 107 用例全绿（98 原 + 9 新） |

**过程要点**：
- **同构性核实**：所有选填键均为 `.get(key, 默认值)`（md_import.py:45-55 / math_upgrade.py:51-57 / md_export.py:65-68）——缺键必静默降级，漂移通道真实存在，与 web2md / md2zh 完全同构
- **否决先前的"不推荐"论证**：五分组部分配置合法 → 但 `load_config` 强制返回五组且选填键全 `.get`，缺键必降级无合法跳过；凭据组 token 环境变量覆盖 → 但 `CONFLUENCE_TOKEN` 只覆盖值、键本身必在（必需项），键集合对比不受影响；占位符类型坑 → md2zh 的 `max_block_chars` 同样存在，非 confluence 独有
- **五分组全检查（用户拍板 A）**：静态配置一次检查永不漂移；键在值空不拦（查存在性不比值）；`common_config` 必需键缺失本就 `sys.exit(1)`，门禁捕获的是选填键静默降级
- 踩坑：confluence selftest.py 为单文件结构（非 discover），新测试不自动发现 → `loadTestsFromModule(sys.modules[__name__])` + 显式加 ConfigSyncTests（注意别重复加载）

**遗留事项更新**：
- （新增）真实 config.py 当前五分组键与 example 一致（exit 0）；`--groups` 支持部分分组检查，后续如遇"只查某组"需求可直接传参，无需改脚本


### 2026-08-08：新增收尾自查（记录建议由用户决定）

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md「自进化」节新增「收尾自查」：会话改动过 `scripts/*.py` / `SKILL.md` / `config.example.py` / `references/*.md` 时，向用户提出记录建议（bug → KNOWN_ISSUES.md；优化 → OPTIMIZATION_SUMMARY.md），**是否记录、记录到哪由用户决定**——不自动强制补记（对应用户原则：我们出决策建议、由客户拍板） |
| 说明 | 与 web2md / md2zh 三 skill 同步新增（同措辞）；web2md 的优化条目见其 OPTIMIZATION_SUMMARY 2026-08-08 |

**过程要点**：
- 补上「固化方案」覆盖不到的空隙：原「修复后向用户提出固化方案」只在错误修复后触发，纯优化（如新增配置项）不在其列；收尾自查覆盖任何改动
- 此前讨论过 config 同步门禁（check_config_sync.py）是否同步到本 skill——**结论：不推荐**：五分组结构（部分配置合法）误报面 > 捕获面、凭据组 token 可环境变量覆盖、占位符类型坑（如 `default_parent_id: ""` str vs 真实 int）、且与「配置来源唯一原则」哲学冲突；已有「运行期配置补齐」机制覆盖实际漂移场景

**遗留事项更新**：
- （新增）config 同步门禁待用户后续决定是否讨论落地



### 2026-08-04：debug 清理策略调整 + md_export 原始 storage 快照

| 类别 | 内容 |
|------|------|
| 脚本改动 | `debug_utils.py`：清理触发改"大小/数量二选一即清理"（原需双条件同时超，实际从不触发）；`_get_timestamp_dirs` 改 `os.walk` 递归扫描 `YYYYMMDD_HHMMSS` 时间戳目录（原只扫 debug_root 直接子目录，嵌套的时间戳目录从未被统计）；排序改按时间戳名（修复完整路径排序被功能子目录字母序干扰、误删 export 快照的 bug，见 KNOWN_ISSUES 2026-08-04） |
| 脚本改动 | `md_export.py`：每页原始 storage 存 `debug/export/<时间戳>/<page_id>_<标题>.html`（同一次运行共用一个时间戳目录），纳入统一 cleanup_debug 清理 |
| 测试 | selftest +4 用例（数量超即清理 / 保留下限 / 跨目录按时间戳排序 / export 快照生成），79 → 83 全绿；TestMdExport 隔离 `md_export.SKILL_ROOT` 到临时目录防污染真实 debug/ |
| 验证 | 真实运行：debug/import 43→0、upgrade 37→20（保留最近 20 个）、export 快照 `73596957_...html` 生成且保留 |

**过程要点**：
- 用户质疑"keep_recent=20 但目录超过 20"引出排查：根因是时间戳目录嵌套在功能子目录下、旧 `_get_timestamp_dirs` 只扫一层 + 双条件触发，两因素叠加导致清理从未真正执行
- 排序 bug 在真实验证中暴露（export 最新快照被误删），说明真实验证能发现离线用例覆盖不到的组合问题；已补跨目录排序回归用例
- 旁路发现：直接 `python -c` 调 debug_utils 打印 🗑️ emoji 会 GBK `UnicodeEncodeError`（无 UTF-8 wrap 的入口）；真实脚本入口（md_import/math_upgrade/md_export）顶部均有 wrap，不受影响

**遗留事项更新**：
- （原）无
- （新增）无

### 2026-08-04：md_export 新增——Confluence → Markdown 导出（基于原型工程化）

| 类别 | 内容 |
|------|------|
| 新功能 | `scripts/md_export.py`：把 Confluence 页面（storage XHTML）导出为 Typora 兼容 Markdown——mathblock/mathinline 原生宏 → `$$...$$`/`$...$`（旧 mathjax 宏兼容）、code → ```语言 围栏、toc → `[toc]`、note/info/warning → 引用块、未知宏 → 注释保留；图片下载到 `<标题>.assets/`（`{附件id}_{原名}` 防重名，页面无图不建目录）；输出 `<标题>/<标题>.md + .assets/` 与 web2md / `md_import --dir` 目录结构对齐，导出树可闭环反向导入 |
| 脚本改动 | `common.py` 新增 `fetch_page`（md_export / math_upgrade 共用，429/5xx 重试）；`math_upgrade.py` 的 fetch_page 改为委托 common.fetch_page（行为与返回结构不变，无回归） |
| 配置 | `export_config` 分组：output_dir（默认 confluence_export，相对 cwd）/ recursive（默认 true）/ space；同步 config.example.py + scripts/config.py + SKILL.md（配置向导 19-21 项、子命令第 4 项、md_export 章节、文件结构） |
| CLI | `--page-id` / `--space` / `--recursive` / `--no-recursive` / `--output`；默认值走 config.py，CLI 覆盖 |
| 测试 | selftest +16 用例（TestMdExport：宏还原/CDATA 反转义/图片引用与 .assets 懒创建/树导出结构/递归开关/front-matter），60 → 76 全绿 |
| 验证 | 真实页面导出：73596957（TECS，34 mathblock + 190 mathinline + 7 图）、12714011（apriltag，74 code + 5 图）——front-matter/[toc]/`$$...$$`/`$...$`/表格/图片引用/代码围栏全部正确，`\frac` 未被 markdownify 转义 |

**过程要点**：
- 原型 `E:\study_data\code\python\test\confluence_to_markdown.py` 只认 v8 第三方 mathjax 宏、Basic Auth、独立配置；正式版改 PAT Bearer + 原生 mathblock/mathinline 支持 + 复用 common.py + `export_config` 配置
- markdownify 两个坑：① `convert()` 接收 **HTML 字符串**而非 soup（内部重新解析，传 soup 会 `'NoneType' object is not callable`）；② 新版默认**无** `language-` 提取且 `code_language_callback` 收到的是 `<pre>` 元素——需自定义回调从内部 `<code class="language-xx">` 提取
- CDATA 用占位符保护（html.parser 不解析 CDATA）；公式/代码/[toc]/未知宏注释全部走「占位符 → markdownify 后还原」，避免被 markdownify 转义（`\frac`、`_` 等）
- 真实页面边缘情况（均为源数据如此，转换忠实）：toc 宏嵌在 `<h1>` 内 → 输出 `# [toc] ...`；code 宏无 language 参数 → 空语言围栏
- 依赖：新增 beautifulsoup4 + markdownify（目标环境已装；脚本实例化时检测缺失并提示）

**遗留事项更新**：
- （原）无
- （新增）md_export 首版未知宏统一降级为注释（Confluence 内置 panel/lorem 等未专门处理）；toc 嵌标题内未做提取到标题外；`\_` 转义为 markdownify 默认行为（Typora 渲染正常）

### 2026-08-04：selftest 重复用例清理 + 文档数字/参数同步

| 类别 | 内容 |
|------|------|
| 脚本改动 | `scripts/selftest.py` 删除 `TestMdImport` 内重复定义的 `test_upload_attachment_updates_existing`（旧版 session.post/get mock 与新版 session.request 版本共存，旧版被覆盖成死代码），仅保留新版 |
| 测试 | 60 用例全绿（实测，2026-08-04；文档原 58 为更早时点遗留） |
| 文档同步 | README / SKILL.md / OPTIMIZATION_SUMMARY 用例数统一为 60；SKILL.md「升级数学公式」补 `--confirm` 参数说明（math_upgrade.py:525 已有该参数，与 config.example.py 注释对齐）；SKILL.md 文件结构"见 skills/.gitignore"笔误改为"见根目录 .gitignore" |

**过程要点**：
- 08-04 未提交的 base64 高亮保护修复（KNOWN_ISSUES 条目 + `md_import.py` `<img>` 保护 + selftest highlight 用例）保留不动，本次仅清理重复用例与同步文档
- 实测基线：confluence 60 / web2md 49 / md2zh 10 全绿

**遗留事项更新**：
- （原）无
- （新增）无

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
- selftest：全部用例全绿（实测）

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
- **树导入断点续传**：已实现单次页面索引、固化 page ID/version 的计划和 checkpoint `--resume`（2026-08-11）
- **toc 阈值无按页面覆盖**（全局配置）
- **实机验证**：2026-08-11 本轮新增的歧义消除、分页、并发与 resume 仅完成离线 mock，仍需在受控真实空间验证权限/API 差异

## 六、环境速查

- Confluence：9.2.1（Data Center，build 9109），PAT Bearer 认证
- Python：`<python 解释器路径>`（需安装 requests / markdown2 / beautifulsoup4 / markdownify；执行前由 `dependency_check.py` 一次实际导入预检）
- 测试命令：`"<python>" -X utf8 scripts/test/selftest.py` → 全部用例通过
