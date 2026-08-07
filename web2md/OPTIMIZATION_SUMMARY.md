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

