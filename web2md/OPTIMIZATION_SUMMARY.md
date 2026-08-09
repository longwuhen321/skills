# web2md 优化总结

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
### 2026-08-09：合并 codex 分支优化（配置安全 + 段落合并/转义/验证器重写 + DOM 降级）

| 类别 | 内容 |
|------|------|
| 脚本改动 | 新增 `config_literal.py`（AST + literal_eval 安全配置解析，load/check 同源，消除 exec）、`package_check.py`（发布前只读敏感文件/值检查：路径门禁 + Token 值扫描两阶段） |
| 脚本改动 | `merge_paragraphs.py` 重写：围栏掩码（`markdown_code.markdown_fenced_code_spans`）+ unescaped `$$` 状态机，公式块/围栏内逐字节保护（含内部空行）；混合 CRLF/LF/CR 行尾保留（读写禁用换行翻译） |
| 脚本改动 | `fix_escapes.py` 重写：只修数学 span（`$$` 块和 ≤2000 字符 `$...$` 块内 `\_`/`\*`），散文合法转义与代码不动 |
| 脚本改动 | `final_verify.py` 增强：悬空 `$` 检测、代码内转义不误报、表格/图片检查统一用保留换行的掩码文本、表格后缺空行 |
| 脚本改动 | `web2md.py`：配置按已知键合并（修 False 失效）、子页面失败累计 + 返回非零（保留成功产物 + 完整失败清单）、渲染后 DOM 降级通道（`--rendered-html`，URL 校验 + 同域/版本前缀/两级限制）、文件名冲突稳定 URL 哈希后缀 + Windows 保留名 |
| 测试 | selftest 60 → 100 全绿；重建 `test_custom_site.py`（8 用例）+ 新增 `test_remaining_optimizations.py`（32 用例）；test_config_sync 改临时 fixture（不读真实配置） |
| 文档 | SKILL.md 采纳：AST 解析说明、package_check 发布检查、`--rendered-html` DOM 降级通道、文件名冲突/Windows 保留名、final_verify 新检查项、"AI 清单打勾"改为人工工作流门禁、fix_escapes 只修公式 |

**过程要点**：
- 来源：`.codex/skills`（win_codex 分支 commit `474b305`，08-09 Codex 大规模优化）。移植策略：**借鉴实现不整目录复制**——纯脚本逻辑通用直接移植；SKILL.md 平台措辞（`$web2md`、`apply_patch`、Codex 网页访问）保留 claude 原样（`/web2md`、Edit、web_fetch）。
- 跨节点裸 TeX 配对：codex 版扩展为"同一块边界内仅跨中性 span、≤12 节点/2000 字符且配对唯一才自动转换"，其余 REVIEW（SKILL.md/custom-site-rules.md 同步）。
- 验证：selftest 100 全绿；`check_config_sync.py` 7 键通过。

**遗留事项更新**：
- （原）跨 DOM 节点裸 TeX 只能报告 REVIEW（2026-08-08 记录）→ 已实现受限自动转换（中性 span 内），跨块/保护子树/歧义仍 REVIEW

### 2026-08-08：proxy 配置项（config.py + web2md.py + AI 判断通道）

| | |
|------|------|
| 新功能 | `web2md_config` 新增 `proxy` 键：空字符串 = 不显式配置，requests 自动读环境变量（HTTP_PROXY/HTTPS_PROXY）；非空 = 显式配置，优先于环境变量（单一配置源，避免双源漂移）；仅支持 http:// 形式（socks5:// 需 PySocks 未安装会报错）。`web2md.py` `load_config` defaults 加 `proxy`，`main` 中 session 非空时设置 `session.proxies`（图片下载同 session 自动覆盖），打印「代理（config.py 配置）」提示 |
| 流程改动 | SKILL.md 配置段补 proxy 说明；AI 判断通道 fallback 第 2 步补「核实脚本从 config.py 读 proxy 传入 requests/curl」——AI 助手不再需要自行发现本机代理路径（本次事故教训：AI 曾不知道本机网络怎么走） |
| 配置 | `config.example.py` + 真实 `config.py` 同步补 `proxy` 键（真实值留空 = 走环境变量，当前系统已配置 HTTP_PROXY/HTTPS_PROXY）；`check_config_sync.py` 门禁 7 键全一致（退出码 0） |
| 验证 | 网络恢复后实测：环境变量代理 4/4 成功、显式 HTTP 代理 4/4 成功（各 ~3-6s）；curl 直连/代理均 3/3 全 200；selftest 60 全绿 |

**过程要点**：
- **代理发现教训**：AI 曾因不知道本机网络路径（WebFetch 平台侧失败 + 不识别 git 代理/环境变量）误判「无法访问」——proxy 配置项把答案写进 config.py，AI 第一步就读它
- **网络抖动**：验证初期环境变量代理 4/4 全失败（TLS 握手超时），用户确认「网络卡了」；恢复后 4/4 全通——排查时先排除网络抖动再判断配置问题
- **限制**：仅 http:// 代理；socks5 需装 PySocks（本机不装，直连/HTTP 代理已通，避免过度工程）

**遗留事项更新**：
- （原）nav_children.py generic 兜底未在真实手写导航站点实测 → 不变
- （新增）md2zh/confluence 未加 proxy 键（最小改动原则，如需要照此模式加）


### 2026-08-08：导航收集重构（nav_children.py 基座+策略+汇总）与 AI 判断通道 fallback

| | |
|------|------|
| 重构 | `web2md.py` 导航收集 7 个函数（`_norm_nav_url`/`_strip_fragment`/`_is_descendant_of`/`_child_nav_container`/`_same_doc_tree`/`collect_children` 及内嵌 `nav_level`/`_item_section`）迁出为独立模块 `scripts/nav_children.py`——**基座 + 策略 + 汇总**架构：通用基座只写一遍（URL 规范化/current_a 定位/容器查找/层级判定/去重），策略层每主题只写差异（`strategy_sphinx`/`strategy_vitepress` + STRATEGIES 注册表，新主题追加函数即扩展），汇总 `collect_children` 返回 `{structure, children, notes}` dict（structure ∈ sphinx/vitepress/generic/unknown） |
| 新功能 | **RTD 当前项 href="#" 识别修复**（回归）：`href_raw == '#'` 且 urljoin 后 == 当前页 → 参与 current_a 定位；`#VPContent` 类真实锚点仍跳过（`== '#'` 判据天然区分）；未命中主题特征时按通用 li/ul 兜底（generic） |
| 新功能 | **notes 诊断输出**：空结果时输出「未定位到当前页/无子页面容器/被过滤/结构未识别」原因 + 定位成功信息，web2md.py 打印「🧭 导航诊断」——AI 判断子页面零网络依赖 |
| 流程改动 | SKILL.md AI 判断通道改「本地证据优先 → web_fetch 补充 → 全失败如实报告由用户确认」，核心纪律「无法核实 ≠ 确认没有」；web_fetch 失败时用 skill Python 环境核实为替代通道 |
| 测试 | 迁移 11 处 `collect_children` import（web2md → nav_children）并适配 dict 返回；新增 3 用例（RTD href="#" 识别 3 子页、RTD 叶子页 notes 诊断、布局锚点仍跳过）；selftest 57 → 60 全绿 |
| 验证 | 端到端 nuttx NSH 实跑：structure=sphinx，识别 8 子页面（customizing.html#nsh-commands 锚点变体正确过滤） |

**过程要点**：
- **回归根因**：8-02 为挡 VitePress 布局锚点加 `href.startswith('#')` 一刀切——RTD 当前项占位 href="#" 被误杀（8-02 旧逻辑在相同 DOM 实测能识别 9 子页）。教训：过滤条件要精确到语义（`== '#'` vs `startswith('#')`），一刀切必踩坑
- **策略特征检测盲区**：老测试的裸 li/ul HTML 无任何主题特征（无 generator meta/toctree class/VPSidebar）→ 策略全部未命中 → 需 generic 兜底（也覆盖手写导航的站点）；`#VPContent` 保护不依赖特征检测，`== '#'` 判据天然安全
- **决策缺陷**（独立于脚本）：AI 判断通道 web_fetch 失败无 fallback，把「无法核实」当「确认没有」；本地证据（已抓 HTML/历史清单/同站产物）被忽略。教训：AI 判断通道必须给 fallback 链 + 纪律，不能留白让 AI 即兴
- **网络通道**：WebFetch 失败是 claude.ai 平台侧预检查，与站点可达性无关；本机 Python 直连（skill 主通道）本来就通；git socks5 代理 Python 缺 PySocks 不必装（直连已通，避免过度工程）
- **CRLF 强制**：test_sphinx_conversion.py 原为 CRLF（违反仓库规范），已转 LF

**遗留事项更新**：
- （原）跨节点裸定界符配对仍靠 AI 手工修复 → 不变
- （新增）nav_children.py 的 generic 兜底在真实非 Sphinx/VitePress 站点（手写 HTML 导航）上未实测，后续遇到可补充验证
- （新增）策略特征检测目前只覆盖 Sphinx/VitePress 两族；GitBook 等新主题追加 strategy 函数 + 注册即可


### 2026-08-08：测试目录更名（scripts/debug/ → scripts/test/）

| | |
|------|------|
| 流程改动 | 测试目录从 `scripts/debug/` 更名 `scripts/test/`——目录里存的是测试文件（selftest.py + test_*.py），`test/` 比 `debug/` 自描述；与日志目录更名（`debug/` → `logs/`）同逻辑，至此**全项目消除 debug 语义歧义**（`logs/` 日志、`scripts/test/` 测试、`debug_utils.py` 调试工具，各归其位） |
| 磁盘 | `scripts/debug/` → `scripts/test/`（内容不动；git 识别为 rename） |
| 文档 | SKILL.md 2 处 `scripts/debug` → `scripts/test`；「本地测试（git 不追踪）」→「git 追踪」（测试需入库）；`SKILL_MODIFICATION_STANDARD.md` / `references/script-development-rules.md` 同步 |
| 测试 | selftest 从 `scripts/test/selftest.py` 运行 57 全绿（相对路径定位自动跟随，零代码改动） |

**过程要点**：
- **⚠️ sed 误伤教训**：全局替换 `s|scripts/debug|scripts/test|g` 误伤 `scripts/debug_utils.py`（真实脚本）→ `scripts/test_utils.py`——真实文件名与测试目录同名前缀冲突，全局替换必须加边界（如 `scripts/debug/` 带斜杠）或逐一确认；已修复
- 测试需入库（用户决定）：selftest 是「改脚本必跑」的质量门，丢失则无法回归验证

**遗留事项更新**：
- （新增）历史条目（KNOWN_ISSUES / 归档日志）仍写 `scripts/debug/`，属当时事实，保留不改


### 2026-08-08：日志目录统一（web2md 日志迁入 skill 级 logs/）

| | |
|------|------|
| 流程改动 | web2md 工作目录从项目级 `{项目根}/.web2md_tools/` 迁入 skill 级 `<skill>/logs/`，与其他 skill 统一（日志归 skill 目录、项目根目录干净）；按 `<项目根名>/` 隔离（与 md2zh 的 `<task-id>/` 隔离同构） |
| 脚本改动 | `web2md.py` `_save_debug_snapshot`：`{根}/.web2md_tools/_archive/` → `<skill>/logs/_archive/<项目根名>/`（`output_root` 取目录名作隔离层，`__file__` 定位 skill 根） |
| 文档 | SKILL.md 5 处 `.web2md_tools` → `logs/intermediate/<项目根名>/` 与 `_archive/<项目根名>/`；目录结构加 `logs/`；清理约定加项目隔离层（intermediate 保留 5 轮、_archive 保留 20 条，均按项目隔离） |
| 迁移 | 旧项目 `E:/study_data/web2md/.web2md_tools/` 内容迁入 `logs/<项目根名>/web2md/`（含 KNOWN_ISSUES_PROJECT.md、快照、清单）；旧目录已删；gitignore 加 `web2md/logs/` |
| 测试 | `test_save_debug_snapshot` 断言 `.web2md_tools` → `logs`；`test_real_config_reports_drift` → `test_real_config_synced_passes`（config 已补齐）；selftest 57 全绿 |

**过程要点**：
- **web2md 清单留 skill 级 + 项目根名隔离**（而非项目级）——与 md2zh 的 `<task-id>/` 隔离同构，统一管理；不同项目的 `fix_list_roundN.md` 不会互相覆盖
- **⚠️ 命名统一教训**：最初定为 `web2md_logs/`，用户指出与 md2zh/confluence 的 `logs/` 命名不一致——同类事物必须同类命名；后统一为 `<skill>/logs/`（三 skill 一致，gitignore 一条 `/*/logs` 全覆盖）。命名应一次到位，避免反复
- `KNOWN_ISSUES_PROJECT.md`（项目级问题记录）随旧目录一并迁入 `_archive/<项目根名>/`，属项目日志，不入 skill 文档

**遗留事项更新**：
- （新增）旧项目若残留 `.web2md_tools/` 目录（未迁移的项目），后续抓取时按新路径写入；旧目录可手动删除


### 2026-08-08：skill 文档自描述规范化

| | |
|------|------|
| 流程改动 | 应用「skill 文档自描述」规范：结构/流程说明必须自描述——规则写全本文件内、复杂结构用「占位符 + 示例图」、不引用其他 skill 的规则细节、不用具体实例名（真实项目/平台名） |
| 落地清单 | 唯一跨 skill 引用 L309「仿照 confluence-tools 的配置模式」→ 改为「采用『模板 + 真实配置』分离模式」——设计溯源说明虽非执行依赖，按规范仍去除；其余全文核验无跨引用 / 无具体实例名 / 无连通断言（`父页面标题` 等目录示例均为占位符风格；`results matching` / `.search-noresults` 为 GitBook 真实 DOM 结构记录，保留） |

**过程要点**：
- 判定标准：**执行依赖**的跨 skill 引用 → 删；**对接/兼容说明** → 自描述化或删；**真实默认值/命令值/DOM 结构** → 保留
- 「仿照 confluence-tools 的配置模式」属**设计溯源**（非执行依赖），但按统一标准一律去除——即使无害的引用也删
- 全文核验合格项：目录树示例（`父页面标题` / `子页面标题`）、清单格式示例（`child.html`）、公式示例（`\( \alpha \)`、`x_{k}`）、伪公式模式示例（`**w***k*`）——均为占位符风格；L43「按当前 AI 助手平台的方式设置」已是泛化措辞

**遗留事项更新**：
- （原）web2md 待后续按需通读 → **（已完成）**本 skill SKILL.md 自描述规范化落地
- （新增）README.md 保留跨 skill 关系说明（总览文档职责），不属自描述规范范围


### 2026-08-08：配置同步强制门禁（check_config_sync.py）

| | |
|------|------|
| 新脚本 | `check_config_sync.py`：对比 `scripts/config.py` 与 `config.example.py` 的 `web2md_config` **键集合 + 值类型**（`exec` 解析，与 `load_config()` 同源）；三类差异 `missing` / `extra` / `type` 逐条列出；退出码 0 = 同步 / 1 = 有差异 / 2 = 文件缺失或损坏；`--config-text` 从 stdin 读取（供配置向导写入后复核，此时跳过 config 文件存在性检查） |
| 流程改动 | SKILL.md 第一步：`config.py` 存在且 `python_path` 有效 → **先跑门禁**，不一致（退出码 1/2）**中断任务**，补齐后重跑；向导第 5 步写入后立即复核；第二步表格、目录结构、配置段、固化的核心约束（新增配置键时旧 config.py 会被门禁拦下）同步更新；**收尾自查**：会话改动过 `scripts/*.py` / `SKILL.md` / `config.example.py` / `references/*.md` 时向用户提出记录建议（bug → KNOWN_ISSUES.md；优化 → OPTIMIZATION_SUMMARY.md），**是否记录由用户决定**（对应用户原则：我们出决策建议、由客户拍板，不自动强制补记） |
| 测试 | `debug/test_config_sync.py` 8 用例（真实文件漂移断言 / 临时对同步 / 缺键 / 多余键 / 类型不符 / 文件缺失 / 损坏 / stdin 模式），selftest 49 → 57 全绿 |
| 文档 | `script-development-rules.md` 防御性设计表新增「配置同步门禁」条目；真实 `config.py` 补齐缺失的 `merge_paragraphs` / `table_formula_inline` / `page_nav` 三键（门禁从 exit 1 → exit 0） |

**过程要点**：
- **只比结构不比 `python_path` 值**——example 是占位符、config.py 是真实路径，逐字节对比必然误报；键集合 + 值类型是唯一可靠判据
- **缺键的后果是 `load_config()` 静默降级默认值**（web2md.py defaults 合并），门禁把「用户以为开了实际没开」（如 collect_children 新增时旧 config 无键）变成显式中断
- 踩坑：Windows 子进程 `input=` 模式下 stdout 默认 GBK，打印 `✗`/`✓` 会 UnicodeEncodeError → stdin/stdout 均 reconfigure utf-8；`--config-text` 模式跳过 config 文件存在性检查（配置从 stdin 来）；测试里 `TemporaryDirectory` 块内创建的文件在块外使用已删除（子进程返回 2 排查）

**遗留事项更新**：
- （新增）配置向导第 5 步目前只写 `python_path`，新增配置键仍需手动在 `config.py` 补齐——门禁只拦截不自动补，向导可考虑后续覆盖全部键


### 2026-08-07：父页面 Sub-pages 导航块（page_nav）

| | |
|------|------|
| 新功能 | `page_nav`（默认 true）：抓取到子/孙页面后，父页面 md 末尾自动追加 Sub-pages 导航块；顺序 = children_list / 导航收集顺序，孙页面嵌套缩进；`--page-nav` / `--no-page-nav` CLI 覆盖 |
| 关键点 | **链接路径含空格必须 `< >` 包裹**——final_verify 链接正则 `[^\s)\n]+` 在空格处截断，不带 `< >` 误报「相对链接目标不存在」；`< >` 是 markdown 标准语法，Typora 可点击 |
| 测试 | 107 → 111 用例（导航块生成 4 个：平级/孙嵌套/空格包裹/追加），selftest 全绿 |

关键认知（2026-08-07）：
1. `_fetch_child_tree` 返回子/孙页面的**实际标题（文件夹名）与相对链接路径**（递归拼接前缀），导航块在子页面全部落盘后追加——链接目标必然存在
2. 递归 join 时 `lines.extend(字符串)` 会把字符串**逐字符拆开**（孙页面行全散）——用 `append`；该 bug 被新增测试捕获
3. 展示版先在 Multivariate Kalman Filter.md 验证（12 链接 + final_verify 全绿）再固化



### 2026-08-07：表格单元格内显示公式行内化（table_formula_inline）

| | |
|------|------|
| 新功能 | `table_formula_inline`（默认 true）：`convert_plain_tex_delimiters` 把 `<td>`/`<th>` 内 `\[...\]` → `$...$` 行内，防 `$$` 块 + 空行撕裂表格；`--table-formula-inline` / `--no-table-formula-inline` CLI 覆盖 |
| 配套 | `list_display_fixes` 表格行内公式（`|` 开头行）不自动升级 `$$`（列为「表格内（保持 $）」候选）；SKILL.md 阶段 B/D、custom-site-rules.md §2、script-development-rules.md 防御表同步 |
| 测试 | 103 → 110 用例（td/th 行内化 6 个 + list_display_fixes 表格内不升级 3 个），selftest 全绿 |

关键认知（2026-08-07 处理 kalmanfilter.net 推导表沉淀）：
1. markdown 表格单元格无法容纳 `$$` 块（独占行 + 空行结束表格）——单元格内公式行内化是唯一出路
2. 表格单元格内 `$...$` 含 `\` 在 Typora **不换行**（inline 模式 `\` 无效）+ `\left...\right` 跨行不配对（渲染失败/回退单行）→ 多行公式需 AI 改写为 `$\begin{aligned}...\end{aligned}$`（单物理行、`\` 换行、`&` 对齐、外层跨行括号改 `\Bigg( \Bigg)` 手动大小）——**判断由 AI 做，脚本只做行内化**
3. 用户编辑器会在块间自动插入空行（表格行间/代码围栏内），破坏表格与围栏配对——交付前需检查「空行前后都是 `|` 行」模式并清理；围栏修复脚本的切片边界必须精确（含/不含开闭标记，off-by-one 会连锁破坏后续代码块的定位锚点）

遗留事项更新：
- 表格内多行公式 aligned 化由 AI 在阶段 C/D 处理（脚本不自动改公式结构）


### 2026-08-07：页面自身 h1 与脚本前缀标题重复时剥离（单 H1 方案）

| 类别 | 内容 |
|------|------|
| 脚本改动 | `web2md.py` 新增 `strip_duplicate_h1(soup, title_text)`：页面第一个非空 h1 文本（`_clean_invisible_chars` + `get_text(strip=True)`）与 `extract_title` 提取标题完全相同时剥离该 h1（脚本前缀 `# {title}` 已涵盖它，避免 md 出现两个同名 H1）；`normalize_document_html` 增加可选参 `title_text=None`（缺省不剥离，旧调用方/测试向后兼容），stats 新增 `duplicate_h1` 计数，`process_page` 传入 title_text 并在规范化报告输出「重复 H1 N」 |
| 保护机制 | h1 内含 math/code/pre/script/style 子树时不剥离（`PROTECTED_TEXT_TAGS` + `is_math_container` 守卫）——公式载荷与代码格式绝不因标题去重丢失；比较源与 `extract_title` 同源（同一 get_text 路径），不存在误判路径 |
| 流程改动 | SKILL.md 第三步 DOM 规范化说明补一句「页面自身与提取标题重复的 h1 自动剥离」 |
| 测试 | `test_custom_site.py` 新增 `StripDuplicateH1Tests` 8 用例（重复剥离/不同 h1 保留/无 title/无 h1/math 守卫/code 守卫/空白容忍/`normalize_document_html` 入口与向后兼容）→ selftest 78 用例全绿（原 70 + 新 8） |
| 验证 | 真实端到端（kalmanfilter.net/background.html 抓到临时目录）：规范化报告「重复 H1 1」，md 前缀 H1 后直接接正文、无双 H1；验证产物用后即清 |

**过程要点**：
- 触发场景：kalmanfilter.net 等自定义站点 h1 在正文容器里被完整保留，与脚本前缀 H1 同名重复（Sphinx/GitBook 站点的 h1 多在 chrome 区被清理，通常无此问题；Sphinx 页面 h1 带 headerlink 链接时也一并去除——源章节可溯性由前缀「原文链接」承担）
- 设计取舍：剥离发生在 DOM 规范化层（`normalize_document_html` 内、公式提取前），不比对 md 文本——Sphinx 标题链接化后 md 形态多变，DOM 层文本比较更稳；守卫只保 math/code 类子树，普通嵌套标签（`<em>`/`<span>`）不阻止剥离（文本相同即视为重复）
- 与 `extract_title` 的耦合：title_text 非空 h1 存在时必取自第一个 h1，故比较天然同源；og:title 兜底路径仅在无非空 h1 时生效，无 h1 则无可剥离对象

**遗留事项更新**：
- （原）跨节点裸定界符配对仍靠 AI 手工修复 → 不变
- （原）`merge_paragraphs` 默认 false，靠切碎检测提示启用 → 不变
- （新增）无

### 2026-08-07：脚本技术要点外置（references/script-development-rules.md）

| 类别 | 内容 |
|------|------|
| 重构 | SKILL.md「## 脚本关键技术要点」整章（防御性设计表 15 条 + 明确不要做的事 8 条）迁移至新文件 `references/script-development-rules.md`，SKILL.md 留一行触发指针（改动 `scripts/*.py` 前必读，正常转换不读） |
| 流程改动 | 固化核心约束补「改动脚本前先读该文件、改动后同步该文件（防御性设计表按实际机制增删改）」；目录结构 references/ 补一行 |
| 设计取舍 | 沿用 2026-08-03 既有原则：**执行约束留 SKILL.md 不外置**（阶段 C 核心纪律含"判断必须由 AI 做/脚本只做机械操作 AI 全审"，与「明确不要做的事」重叠的两条在阶段 C 已有副本，外置无约束真空）；只有"脚本开发者知识"（防御机制+红线）外置按需读 |
| 验证 | grep 全文件确认旧内容零残留、引用一致（指针/目录/约束三处）；无脚本改动，selftest 不需重跑 |

**过程要点**：
- 外置判定标准：读者是"改脚本的 AI"（偶尔）而非"转换的 AI"（每次）→ 外置；执行约束一律留在 SKILL.md 常驻
- 与 `formula-conversion-rules.md`（阶段 C 查表）、`custom-site-rules.md`（检测命中）、`KNOWN_ISSUES.md`（事后排查）形成四文件分工：事前机制 / 转换规则 / 站点模式 / 历史坑

**遗留事项更新**：
- （原）跨节点裸定界符配对仍靠 AI 手工修复 → 不变
- （原）`merge_paragraphs` 默认 false，靠切碎检测提示启用 → 不变
- （新增）无

### 2026-08-07：非平台结构页面（自定义站点）能力——裸定界符转换 + 段落合并 + 检测诊断

| 类别 | 内容 |
|------|------|
| 新功能 | `web2md.py` 新增 `convert_plain_tex_delimiters`：KaTeX auto-render / MathJax tex2jax 站点的裸文本 `\(...\)` / `\[...\]` 定界符自动转换（DOM 文本节点级，跳过 math/code 子树；保护 `\\[` 行距、`\left(` `\left[` 天然不匹配；跨节点配对不替换、计数输出交 AI 复核）——`process_math_formulas` 的 5 种标记之外的兜底 |
| 新功能 | `_paragraph_stats` 段落切碎检测（≥50% 且行 <80 字符时输出提示）+ 诊断报告（「检测到裸 TeX 定界符」「跨节点疑似」「段落切碎检测」），AI 据此走 `references/custom-site-rules.md` |
| 新功能 | `scripts/merge_paragraphs.py`（新脚本）：段落源码硬换行合并（普通段落一行 / 列表项续行并入 / `$$` 块、公式标签行、嵌套子列表、Sphinx 定义列表保护 / 双空行压缩）；config `merge_paragraphs`（默认 false）+ CLI `--merge-paragraphs`，web2md.py 转换后自动应用 |
| 流程改动 | SKILL.md：第四步开头加「非平台结构页面」触发指针（命中→按需读 `references/custom-site-rules.md`）；第五步改「段落合并（可选，通用能力）与输出」；脚本表/目录结构/配置说明/防御性设计表同步；`config.example.py` 补 `merge_paragraphs` 模板 |
| 新文件 | `references/custom-site-rules.md`：非平台结构页面特征清单、裸定界符转换规则、扩展兼容通用排查法（`\require{...}`）、处理流程——只写模式不写站点名，案例归 KNOWN_ISSUES.md |
| 测试 | `scripts/debug/test_custom_site.py` 新 22 用例（裸定界符 10：行内/显示/多行块/行距保护/`\left` 不匹配/粘连正文/去重/多公式单节点/跨节点识别/混合；段落统计 3；段落合并 9：普通段落/列表续行/公式块逐字节/定义列表×2/双空行/标签行/CLI）→ selftest 70 用例全绿 |
| 验证 | 离线回归（fetch_home.html 快照 → process_page 全流程）：自动转换 124 行内 + 57 显示、残留全零、`\\[0.5em]` 行距 3 处保留、段落合并生效、fix_escapes/list_display_fixes 后 final_verify 全绿 |

**过程要点**：
- 踩坑 1：`_find_plain_close` 最初用 `text.find(closer)` 找**裸括号**而非 `\)` 序列 → 所有公式误判"跨节点"（selftest 立即暴露）；闭定界符跳过 `i = j + 2`（含 `\` 和括号两字符），写成 `j+1` 会残留单个括号字符
- 踩坑 2：空行压缩条件必须 `skip >= 1` 时输出一个空行（写成 `>= 2` 会删光段落间空行——真实事故曾致整文件无空行，靠备份恢复）
- 踩坑 3：列表项续行判断必须用原始行（`strip()` 后永远没有前导空格）；Windows 子进程捕获 emoji 输出需 `errors='replace'`（GBK 解码抛 UnicodeDecodeError）
- 设计取舍：段落合并默认关闭（不改变已知平台现有输出）；跨节点定界符不做自动转换（AI 复核）；`\xcancel` 类扩展兼容不穷举宏包，提供通用排查法
- 顺带清理：`PLAIN_TEX_CLOSE` 正则改实现后成死代码，已删

**遗留事项更新**：
- （原）纯 JS 渲染导航的站点可能需要扩展 → 不变
- （原）`config.py` 的 `collect_children` 默认 false → 不变
- （新增）跨节点定界符配对仍靠 AI 手工修复（脚本只计数提示）
- （新增）`merge_paragraphs` 默认 false，靠切碎检测提示启用；Sphinx 定义列表等结构的保护规则已实现但只经离线用例验证，真实 Sphinx 页面批量场景待实测

### 2026-08-04：补 --children-from 与 collect_children 回归测试 + 文档同步

| 类别 | 内容 |
|------|------|
| 测试 | `test_sphinx_conversion.py` +8 用例：`parse_children_list` 清单解析 5 用例（嵌套 / 注释备注 / 深层级 / 缺 URL 与无父孙页 / `*` 与 `<>` 与错误路径）+ `collect_children` 3 用例（`#VPContent` 纯锚点不干扰 current_a、普通页 `.html` 重定向归一化、collapsible 分组孙页面挂载）——对应 08-03 KNOWN_ISSUES 声称已加但实际丢失的 C1-C5 / V6 / V7 |
| 测试 | selftest 49 用例全绿（实测，2026-08-04） |
| 文档同步 | OPTIMIZATION_SUMMARY / KNOWN_ISSUES 用例数统一为 49、历史编号 V5/V6/V7 改为实际描述性测试名；README web2md 用例数 41→49、删除"同时写入 Bash allow 规则"句（与 SKILL.md 第一步"按平台方式设置免确认白名单"一致）；遗留事项双轨合并 |

**过程要点**：
- 丢失原因推测：08-04 早间测试文件被整批恢复（时间戳 08:39:55 一致）时，未提交的新增用例随工作区丢失；代码 `parse_children_list`（web2md.py:942）、`_norm_nav_url` `.html` 归一化、`_item_section` div/section 放宽均仍在
- 测试命名沿用现有描述性风格（非历史编号），KNOWN_ISSUES 中的 V5/V6/V7 引用已改为实际测试名
- 顺带修复：新增用例中 `empty.md` 写入曾因缩进错误掉出 `TemporaryDirectory` 块导致 FileNotFoundError，已修正缩进（与测试本身无关）

**遗留事项更新**：
- （原）`--children-from` 依赖站点静态渲染侧边栏 → 不变
- （原）清单是 AI 手工维护的产物，多页批量抓取时 AI 需逐个页面写清单 → 不变
- （新增）无

### 2026-08-03：阶段 C 公式规则外置（references/formula-conversion-rules.md）

| 类别 | 内容 |
|------|------|
| 流程改动 | SKILL.md 阶段 C 从约 200 行内嵌规则表瘦身为 ~30 行：五步流程 + 分类索引表（A–I / S / F2，含触发条件 + 参考章节）+ 核心纪律（判断由 AI 做、脚本只做 str.replace、表格粗体保留等） |
| 新文件 | `references/formula-conversion-rules.md`：伪公式 A–H、Unicode 符号 I-1~I-7（含判断边界、NBSP 陷阱）、Sphinx 页面遗留公式模式、碎片化行内公式序列、辅助扫描工具，全部按章节号组织 |
| 流程改动 | 涉及 LaTeX 语法转换细节时按索引读取参考文件对应章节（低频符号表不常驻上下文）；阶段 D 第 5 点对 Sphinx 遗留的引用改为 `references/formula-conversion-rules.md` §3；文件结构章节补 references/ |
| 对齐 | 与 md2zh `references/translation-rules.md` 的"规则独立文件 + 按需读取"模式统一 |

**过程要点**：
- 设计取舍：核心流程纪律（不用正则/自动判断、审核全部、候选写清单）**留在 SKILL.md 不外置**——它们是执行约束而非查表项，外置会稀释约束力；只有"转换规则表"外置
- 防漏读：分类索引表自带"触发条件"列，AI 通读时先扫索引命中类别再读参考文件，索引即检查清单

**遗留事项更新**：
- （原）无
- （新增）`find_all_missed.py` 的防御性表引用未逐条核对（脚本行为未变，仅文档位置调整）；参考文件后续新增符号类别时直接追加章节号即可

### 2026-08-03：子页面收集 AI 判断通道（--children-from）

| 类别 | 内容 |
|------|------|
| 新功能 | `--children-from <file>`：AI 助手写子/孙页面清单（`{项目}/.web2md_tools/intermediate/children_list.md`），脚本解析后按清单抓取落盘——规则解析（`collect_children`）降级为默认快速路径，AI 通道为并行完整通道（新主题漏识别/规则异常时 AI 接管，不再依赖改规则） |
| 脚本改动 | `web2md.py` 新增 `parse_children_list()`（清单机械解析：注释/备注忽略、缩进=层级≤2、缺 URL/无父孙页面跳过并警告、`-`/`*` 标记、`<>` 剥除）；`fetch_and_process` 支持外部 children_list（优先于规则）；`main` 新增 `--children-from` 参数 |
| 流程改动 | `SKILL.md` 新增「AI 助手判断通道」小节（web_fetch 读导航 → 写清单 → `--children-from` 执行），同步修正触发条件表述、intermediate 说明、清理约定、测试说明、防御性表 |
| 测试 | `test_sphinx_conversion.py` 新增 C1-C5 共 5 用例（清单解析：嵌套/注释/备注/深层级/缺 URL/星号/<>/无父孙页面/文件缺失/空清单）→ selftest 49 用例全绿（2026-08-04 实测校正） |
| 验证 | 真实端到端：清单（2 子 + 1 孙）→ 嵌套落盘正确（`父/子/孙` 三层文件夹，孙页面挂在子页面下） |

**过程要点**：
- 清单位置约定：`intermediate/children_list.md`（AI 写入范围在项目工作区内；skill 目录沙箱不可写）
- 落盘文件夹名仍以页面实际标题为准（清单标题仅展示用），与规则路径行为一致
- 清单解析坚持"脚本只做机械解析、AI 做语义判断"——不引入正则/自动筛选

**遗留事项更新**：
- （原）`collect_children` 只按导航树收集子+孙 → 现在规则失效时可由 AI 清单兜底，无需改规则
- （新增）`--children-from` 依赖站点静态渲染侧边栏（AI 的 web_fetch 才能看到导航文本）；纯 JS 渲染站点仍需另行处理
- （新增）清单是 AI 手工维护的产物，多页批量抓取时 AI 需逐个页面写清单（规则路径仍适合已知站点批量场景）

### 2026-08-02：导航子页面批量获取

| 类别 | 内容 |
|------|------|
| 新功能 | `collect_children`：解析侧边栏导航，收集严格导航子页面 + 孙页面（深度≤2）；`--children`/`--no-children` CLI 覆盖；`config.py` 的 `collect_children` 开关（默认 false） |
| 重构 | 抽出 `extract_title`（h1 优先、去站点后缀）、`process_page`（单页落盘）、`fetch_and_process` + `_fetch_child_tree`（递归批量抓取）；main 改 argparse |
| 输出 | 按页面标题文件夹嵌套落盘（父/子/孙），非法字符替换 |
| 测试 | 28 → 34 用例（导航解析 Sphinx+VitePress 双结构、标题命名、快照等） |

### 2026-08-01~02：脚本单份化 + 移植 Codex 增量

- 5 个内嵌脚本 → `scripts/` 独立文件；新增 `markdown_code.py`（掩码）
- 移植 Codex 版：DOM 规范化 8 函数、`list_display_fixes --apply`、`final_verify` 全量验证；保留 `mjx-container` 支持
- config.py 配置模式；平台通用化（"Claude"→"AI 助手"）
- 排障体系：新增 `KNOWN_ISSUES.md`、自进化章节、产物清理约定

## 二、验证结果

- PX4 `config_fw/` 端到端：父 + 4 子页面抓取、标题文件夹嵌套落盘正确
- Wikipedia 单页：58 公式、429 退避、13/13 图片
- selftest 全部用例全绿（实测）

## 三、过程中的 bug 序列

1. VitePress 侧边栏用 `div/section` 而非 `ul/li` → 标签无关算法（容器查找 + `ul`/`div.items` 层级计数）
2. `collect_children` 在 `process_page` 后调用：`html_to_markdown` 会删 `<nav>` → 先收集再处理
3. `<title>` 带站点后缀 → `extract_title` 优先 h1、去 ` | ` 后缀
4. 目录 URL 与 `index.html` 形式不匹配 → `_norm_nav_url` 双向归一化
5. 测试数据 href 与 base_url 版本号不一致 → 测试统一

## 四、协作风格

先方案后动手（用户确认才实施）／任务清单跟踪／测试先行（selftest 全绿才交付）／真实环境端到端验证／证据驱动排查（抓真实 HTML 分析，不猜）／文档同步／诚实报告／安全优先／一次性脚本即删。

## 五、遗留事项

- 导航收集范围限定侧边栏导航树（子+孙，**不递归子页面正文引用**，设计如此）；规则失效/新主题漏识别时由 `--children-from` AI 通道兜底（已实现，2026-08-03）
- 导航解析已验证 Sphinx li/ul 与 VitePress div/section；纯 JS 渲染导航的站点可能需要扩展
- 标题文件夹命名由 AI 助手酌情调整（须符合规范），脚本默认 `sanitize_filename`
- `config.py` 的 `collect_children` 默认 false，需用户开启
- `config.py` 的 `merge_paragraphs` 默认 false，靠切碎检测提示启用（2026-08-07）
- 跨节点裸定界符配对仍靠 AI 手工修复（脚本只计数提示，2026-08-07）


