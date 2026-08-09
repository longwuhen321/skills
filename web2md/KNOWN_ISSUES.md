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

## [2026-08-08] Sphinx RTD 主题当前项 href="#" 被跳过，导航子页面全漏（nuttx.apache.org NSH，已修复）

- **现象**：nuttx.apache.org NSH 页面（Sphinx Read the Docs 主题）抓取时脚本报「该页面无严格导航子页面」，但页面导航下实际有 8 个子页面（Overview/Commands/Configuration Settings/customizing/builtin/installation/login/running_apps）；8-02 曾用同一站点同一套件正常抓取 9 个文件。另：AI 助手 WebFetch 失败（平台侧域名安全预检查，与站点可达性无关）后把「无法核实」当成「确认没有」→ 未走 AI 判断通道、未对照历史产物，直接交付了缺失子页面的结果。
- **根因**（两个独立问题）：
  1. **脚本回归**：`collect_children` 的 current_a 定位（web2md.py）为挡 VitePress 布局锚点（`#VPContent`）加了 `href.startswith('#')` 一刀切跳过——RTD 主题当前项导航链接恰好是 `href="#"`（靠 `li.current` class 标记当前页），被误杀 → current_a 定位失败 → 返回空。实测 8-02 前旧逻辑（`2ded7af`，无 `#` 过滤）在相同 DOM 上能完整识别 9 个子页面。
  2. **决策缺陷**：SKILL.md AI 判断通道只写了 web_fetch 核实，未定义 web_fetch 失败时的 fallback；AI 把「无法核实」静默当成「确认无子页面」，且未使用本地证据（本次已抓 HTML、历史 children_list.md、8-02 同站产物）。
- **修复**：
  1. **重构**：`web2md.py` 的导航收集（`_norm_nav_url`/`_strip_fragment`/`_child_nav_container`/`nav_level`/`_item_section`/`_same_doc_tree`/`collect_children`）全部迁出为独立模块 `scripts/nav_children.py`（基座 + 策略 + 汇总：通用基座 + `strategy_sphinx`/`strategy_vitepress` + STRATEGIES 注册表 + `collect_children` 返回 `{structure, children, notes}` 诊断 dict；`structure` ∈ sphinx/vitepress/generic/unknown）。**RTD 修复**：`href_raw == '#'`（RTD 占位）经 urljoin 后与当前页 URL 匹配 → 参与 current_a 定位；`#VPContent` 类真实锚点（`startswith('#')` 且非 `#`）仍跳过。未命中任何主题特征时按通用 li/ul 导航兜底（structure='generic'）。
  2. **诊断输出**：`collect_children` 空结果时 notes 带原因（current_a 未定位/无容器/被过滤/结构未识别），web2md.py 打印「🧭 导航诊断」，AI 助手据此判断「真没有」还是「漏识别」，不再需要网络访问。
  3. **流程**：SKILL.md AI 判断通道改为「本地证据优先 → web_fetch 补充 → 全失败如实报告由用户确认」，核心纪律「无法核实 ≠ 确认没有」。
- **排查方法**：脚本报「无导航子页面」但页面导航里明显有子页面时：① 看页面是否 RTD 主题（`nav.wy-nav-side` / `li.current`），当前项 href 是否 `#`；② 用 `nav_children.collect_children` 的 notes 诊断；③ 核对历史 `logs/intermediate/<项目根名>/children_list.md` 与同站产物；④ 网络可达性用 skill 的 Python 环境（`config.py` python_path）验证，WebFetch 失败不代表站点不可达。
- **网络路径证据**（2026-08-08 实测）：WebFetch（claude.ai 平台侧）预检查失败 `Unable to verify if domain nuttx.apache.org is safe to fetch`；本机 Python requests 直连 200（无代理环境变量）；git 代理 `socks5://127.0.0.1:7890` curl 可用、Python 缺 PySocks（不必安装，直连已通）。
- **代理配置补充**（2026-08-08 新增 `proxy` 配置键后）：系统已配置环境变量 `HTTP_PROXY`/`HTTPS_PROXY`=`http://127.0.0.1:7890`（大小写两套），requests 自动读取（`get_environ_proxies` 实测解析出 `{'https': ..., 'http': ...}`），curl 直连/代理均 200；`web2md_config.proxy` 键显式配置时优先于环境变量（单一配置源），AI 判断通道核实脚本同样从 config.py 读 proxy。验证初期曾遇网络抖动（TLS 握手超时 4/4 失败），恢复后 4/4 全通——排查时先排除网络抖动再判断配置问题。

## [2026-08-07] merge_paragraphs 把表格行当普通段落合并成单行，表格后与公式块粘连（kalmanfilter.net，已修复）

- **现象**：转换产物中表格全部拍扁成单行（如 `|  | Notes | | --- | --- | | a | b |`），且表格行与后续 `$$` 公式块之间无空行（Typora 渲染异常）。kalman1d 页 5 个表格全部损坏，之前（alphabeta 页）误判为「markdownify 把行列合并成单行」，实际根因在 merge_paragraphs。
- **根因**：`merge_paragraphs.py` 的「普通段落」合并逻辑把 `|` 开头的表格行当普通段落——连续表格行被空格连接合并成一行；表格行与紧邻的 `$$` 块之间也无空行（markdownify 在表格后紧邻块级元素时不输出空行）。验证：把 30 行 `|` 开头行喂给 merge，输出只剩 5 行。
- **修复**：三处——
  1. `scripts/merge_paragraphs.py`：表格行（strip 后以 `|` 开头）加入特殊行保护（与标题/引用同列），普通段落合并与列表项续行循环均 break 表格行，不再合并/吞并；
  2. `scripts/web2md.py` 新增 `ensure_table_separators()`（html_to_markdown 内、markdownify 输出后无条件调用）：表格块（连续 `|` 行）后若非空行则补空行，表格与 `$$` 块/段落不再粘连；不依赖 merge 开关；
  3. `scripts/final_verify.py`：表格检测循环新增「行 N 表格后缺空行」FAIL 检查（有分隔行的真表格，块后下一行非空即报），兜底防御。
  4. **同链发现第二个缺陷**：`merge_paragraphs.py` 的空行压缩在 `$$` 行切换 in_math 状态时未先 flush `skip`，`$$` 块前的空行（含第 2 步补的空行）被吞——修复为 `$$` 分支先 `if skip >= 1: final.append('')` 再切换状态。
- **排查方法**：产物表格成单行 → 先查是否启用 merge（config `merge_paragraphs`），把表格段喂给 `merge_markdown_paragraphs` 复现；表格后 `$$` 粘连、或任意块级元素后紧邻 `$$` 无空行 → 检查 merge 空行压缩是否吞掉 `$$` 前空行（已修复）。回归测试 `test_table_rows_not_merged` / `test_table_rows_not_absorbed_into_paragraph` / `test_blank_before_math_block_kept`（MergeParagraphsTests）+ `TableSeparatorTests` 5 用例（ensure_table_separators 补空行/不动 + final_verify 报错/通过）；selftest 94 用例全绿；kalman1d 真实页面端到端验证：5 个多行表格完好、表格后缺空行 0。

## [2026-08-07] 页面标题含裸 TeX 定界符导致文件夹名乱码（kalmanfilter.net，已修复）

- **现象**：kalmanfilter.net 的 alphabeta 页 `<h1>` 是 `The \( \alpha -\beta -\gamma \) filter`——作者用 KaTeX 数学模式写希腊字母。转换后：① 文件夹名变成 `The -( -alpha --beta --gamma -) filter`（每个 `\` 被替换成 `-`）；② md 前缀 H1 保留未转换的裸 `\(...\)` 定界符。
- **根因**：`extract_title` 原样提取标题文本；`sanitize_filename` 把 `\`（Windows 路径分隔符）替换为 `-`（`[\\/:*?"<>|]` → `-`）；脚本前缀 `# {title}` 直接写提取文本，未经任何公式转换。
- **修复**：`scripts/web2md.py` 新增 `TITLE_MATH_UNICODE` 映射表 + `clean_title_math()`——去掉 `\( \) \[ \]` 定界符、希腊字母与常用运算符转 Unicode（`\alpha`→α、`\times`→× 等）、压缩空白；**未映射的 LaTeX 命令保留原样不误删**（交 AI 酌情调整）。`extract_title` 三条路径（h1 / og:title / `<title>`）与 `strip_duplicate_h1` 的比较都走同一清理，保证命名、前缀标题、重复 H1 剥离三者一致。回归测试 `TitleMathCleanTests` 7 用例 + `test_h1_with_bare_tex_title_stripped`，selftest 86 用例全绿。
- **排查方法**：转换产物文件夹名出现 `-( -alpha` 类乱码、或 md 首行标题含 `\(` 时即为此类；修复后文件夹/文件/前缀标题自动干净，仅当标题含未映射命令（如 `\frac`）残留时才需 AI 手动调整（参考本页最终人工改为 `The α-β-γ filter`）。

## [2026-08-07] KaTeX auto-render 裸 TeX 定界符漏转换（kalmanfilter.net，已修复）

- **现象**：kalmanfilter.net 首页（自定义站点）用 KaTeX auto-render 渲染公式，源码 HTML 中公式是**裸文本** `\(...\)`（125 处）与 `\[...\]`（60 处），没有包在 `class="math"` / `<math>` / MathJax `<script>` 等脚本能识别的标记里（全页仅 1 处 `class="math"` 被转换）。脚本报告「转换了 1 个数学公式」，185 处公式以 `\(...\)` / `\[...\]` 原样残留到 Markdown。该站同时混用 `$$...$$` 与 `\[...\]` 两种显示定界符。
- **根因**：`process_math_formulas` 只识别 5 种标记（Wikipedia `.mwe-math-element`、MathJax `<script>`、`<math>` MathML、`class="math"`、`<mjx-container>`）；SKILL.md §3 的「`\(...\)` 已由脚本自动转 `$...$`」只覆盖 Sphinx 的 `class="math"` 内定界符，KaTeX auto-render 站点的裸文本定界符（非 Sphinx 结构）不在脚本处理范围内。
- **修复**：`scripts/web2md.py` 新增 `convert_plain_tex_delimiters`（`process_math_formulas` 之后运行，DOM 文本节点级，跳过 code/pre/script/style/math 子树）：单文本节点内配对 `\(...\)` → `$...$`、`\[...\]` → `$$...$$`；保护 `\\[` 行距（开定界符前字符是反斜杠）、`\left(` `\left[`（反斜杠不在括号前，天然不匹配）、`\\)`/`\\]` 转义；`\]` 后粘连正文由现有 `$$` 独占一行机制自动拆行；跨节点配对（定界符与内容被标签打断）不做替换，计数输出交 AI 复核。另新增 `_paragraph_stats` 段落切碎检测与「非平台结构页面」诊断输出（触发 AI 读取 `references/custom-site-rules.md`）。回归测试 `scripts/debug/test_custom_site.py` 12 用例全绿。
- **排查方法**：脚本输出「检测到裸 TeX 定界符: 行内 N，显示 N，跨节点疑似 N」即命中此类；跨节点疑似需 AI 通读定位修复（如合并打断的 span 或手工补定界符）。

## [2026-08-07] markdownify 保留源码硬换行，段落被切碎（kalmanfilter.net，已修复）

- **现象**：转换产物中每个自然段被 HTML 源码硬换行切成 2–6 行短行（kalmanfilter.net 首页 226 个普通段落中 71 个被切碎 + 8 个列表项含续行），在 Typora 中观感像分段。该问题是通用模式（HTML 源码按编辑习惯每行 ~90 字符硬换行，非自定义站点特有）。
- **根因**：markdownify 保留 HTML 文本节点内的源码换行；密集短段落放大了 Typora 主题段间距的感知。
- **修复**：新增 `scripts/merge_paragraphs.py`（`merge_markdown_paragraphs` 函数 + CLI）：普通段落连续非空行合并为一行（空格连接、保留首行缩进）；列表项 `-/*/+` 前缀行 + 后续 2 空格缩进文字续行并入首行（去尾部 hard-break 空格）；`$$` 公式块内部、公式标签行（缩进 + 行尾两空格）、嵌套子列表、Sphinx 定义列表（term + 缩进定义段 / `: ` 前缀行）逐字节保护；双空行压缩为单个（块外）。配置 `merge_paragraphs`（默认 false）+ CLI `--merge-paragraphs`；web2md.py 在 `_paragraph_stats` 切碎检测命中（≥50%）时提示启用。
- **排查方法**：抓取报告「段落切碎检测: N/M 段」命中时启用 `--merge-paragraphs`；合并后重跑 final_verify 确认结构未破坏。**踩坑记录**：① 空行压缩条件必须 `skip >= 1` 时输出一个空行（写成 `>= 2` 会误删全部段落间空行——曾致整个文件变成无空行，靠备份恢复）；② 列表项续行判断必须用原始行（`strip()` 后永远没有前导空格，会漏合并）；③ Windows 子进程捕获脚本输出需 `errors='replace'`（emoji 输出按 GBK 编码解码会抛 UnicodeDecodeError）。

## [2026-08-03] collect_children 在 VitePress 普通页面漏识别（纯锚点/.html 重定向/可展开分组，已修复）

- **现象**：`modules/modules_main.html`（VitePress 普通页面，非 index）在导航下有 9 个子页面 + 10 个孙页面，但 `collect_children` 误报"该页面无严格导航子页面"；AI 判断通道确认页面导航真实存在。
- **根因**（4 个关联点，均为同一排查链发现）：
  1. **纯锚点链接干扰 current_a 定位**：VitePress 布局锚点 `#VPContent` 与正文标题锚点（`#modules-commands-reference` 等）去 fragment 后与当前页 URL 相同，且 DOM 中先于导航出现——定位循环未跳过 `#` 开头链接，`current_a` 命中 `div.Layout` 锚点 → 容器定位失败。
  2. **普通页面 `.html` 后缀不归一化**：服务器把 `modules_main.html` 重定向为 `modules_main`（去扩展名），导航链接却带 `.html`——`_norm_nav_url` 只处理 `index.html`/`index`（目录页场景），普通页面两种形式不匹配。
  3. **带 fragment 的 URL 不触发 `.html` 归一化**：`commands.html#mount` 的 `.html` 被 `#mount` 挡住 → 与 base（纯 URL）归一化结果不一致，单页文档锚点误判（selftest S4/S5/S6 回归失败暴露）。
  4. **可展开分组孙页面挂载失败**：Drivers 是 `section.VPSidebarItem level-2 collapsible`（可展开分组）而非普通子页面的 `div.level-2`——`_item_section` 只接受 `p3.name == 'div'`，对分组返回过窄的 `div.item`，孙页面（10 个驱动分类）inside 检查失败全部漏挂。
- **修复**：`scripts/web2md.py`——① current_a 定位循环跳过 `href` 以 `#`/`javascript:`/`mailto:` 开头的链接；② `_norm_nav_url` 增加 `.html` 后缀归一化（`elif u.endswith('.html')`）；③ `_norm_nav_url` 开头先 `_strip_fragment` 再去扩展名（保证带锚点 URL 与纯 URL 归一化一致）；④ `_item_section` 的包裹容器条件放宽为 `p3.name in ('div', 'section')` 且带 level- class（兼容 collapsible 分组）。回归测试 `test_collect_children_layout_anchor_not_interfering`（纯锚点不干扰）/`test_collect_children_plain_page_html_redirect`（普通页 .html 重定向）/`test_collect_children_collapsible_group_grandchild`（可展开分组孙页面挂载）新增，selftest 49 用例全绿（2026-08-04 实测）。
- **排查方法**：VitePress 站点规则路径误报"无子页面"时，先核对 `final_url` 是否被重定向为去 `.html` 形式（普通页 vs index 页）；再检查页面 DOM 中是否存在 `#VPContent` 类布局锚点先于导航出现；孙页面缺失时检查分组是否为 `section.level-N collapsible`（非 `div.level-N`）。

## [2026-08-03] final_verify 图片路径含括号被正则截断误报缺失（已修复）

- **现象**：图片引用路径含成对括号（如 `![](./Acro Mode (Fixed-Wing).assets/acrobatic_fw.C7FhNtUe.png)`，目录名来自页面标题"Acro Mode (Fixed-Wing)"）时，验证器误报"缺失的本地图片"FAIL；文件实际存在。
- **根因**：`final_verify.py` 图片正则 `!\[[^\]]*\]\((?:<([^>]+)>|([^)]+))\)` 的 `([^)]+)` 在路径第一个 `)`（`(Fixed-Wing)` 的闭合括号）处截断，target 变成 `./Acro Mode (Fixed-Wing`。
- **修复**：`scripts/final_verify.py` 图片解析改为**括号深度扫描**：先用 `!\[[^\]]*\]\(` 定位起点，再从起点扫描找匹配的 `)`（`(` +1、`)` -1，深度 0 时闭合），`<...>` 尖括号形式保留；data URI 内成对括号（svg 的 `translate(0 -289.062)`）可正确跳过。
- **排查方法**：验证器 FAIL 的缺失路径以 `(XXX`（未闭合）结尾且同名文件存在于 .assets 时即为此类；页面标题含括号时生成的目录名必然含括号，图片引用都会触发。

## [2026-08-03] collect_children 不识 VitePress 导航结构（div.item/section 平铺）与 /index 重定向形式（已修复）

- **现象**：docs.px4.io（VitePress 主题）的章节目录页 `flight_modes_fw/index.html` 在导航下有 11 个子页面，但 `collect_children` 返回"该页面无严格导航子页面"；此前（2026-08-03 上一条目）的修复只覆盖 Sphinx 的 li/ul 嵌套结构。
- **根因**：① VitePress 侧边栏结构是 `nav > div.group > section.level-N > div.items > div.item > a`——子页面与当前页**平铺在同一 section 内**（各有 div.item 包裹），没有 Sphinx 的嵌套 ul；旧 `_child_nav_container` 只找嵌套 ul/div.items，找不到就返回 None。② 服务器把 `index.html` 重定向为 `/flight_modes_fw/index`（无扩展名），`_norm_nav_url` 只处理 `/index.html` 后缀，导致 base_url 规范化后与页面链接不匹配，`current_a` 定位失败。③ `nav_level` 把 VitePress 顶层 `div.items`（container 直接子）误当层级容器，子页面全被算成孙级（depth=2）。
- **修复**：`scripts/web2md.py`——① `_child_nav_container` 增加 VitePress 分支：current_a 的父是 `div.item` 时，返回其所在 section（level-N）作为子页面容器；无子页面（a 直接平铺在 div.items 里，如 px4_basic_concepts）返回 None 不误抓兄弟页面；② `_norm_nav_url` 支持 `/index`（无扩展名）后缀；`base_dir` 计算对 `/index` 结尾精确取目录；③ `nav_level` 计 `div.item`，`div.items` 仅当不是 container 直接子级时计层；④ `_item_section` 对 VitePress 返回 div.item 的包裹容器 VPSidebarItem（level-N div），保证孙页面正确挂载。回归测试 11 场景（Sphinx 7 + VitePress 4，含真实结构 div.items 包裹、/index 形式）全绿。
- **排查方法**：日志出现"该页面无严格导航子页面"但页面导航里明显有子页面时：先看页面 HTML 是 Sphinx（li/ul）还是 VitePress（section/div.item/div.items）；再核对 `final_url` 是否被重定向为 `/index` 无扩展名形式（`_norm_nav_url` 是否匹配）。

## [2026-08-03] final_verify 图片 title 后缀误报缺失图片（已修复）

- **现象**：带 title 的图片引用 `![](path "Some Title")` 被报「缺失的本地图片」FAIL，文件实际存在；不带 title 的图片引用正常。
- **根因**：`final_verify.py` 图片引用正则 `!\[[^\]]*\]\((?:<([^>]+)>|([^)]+))\)` 的 `([^)]+)` 贪婪捕获了 `path "Some Title"` 整体（含 title），`Path.is_file()` 匹配失败。
- **修复**：`scripts/final_verify.py` 提取 target 后剥离 title 后缀：`re.sub(r'\s+["\x27][^"\x27]*["\x27]\s*$', '', target).strip()`（用 `\x27` 避开引号转义；写入补丁时注意普通字符串中 `\'` 会被转义吞掉反斜杠，务必用双反斜杠或 `\x27`）。
- **排查方法**：验证器 FAIL 的路径以 ` "标题"` 结尾、但同名文件存在于 .assets 时即为此类；负例（引用不存在的图片、含/不含 title）应仍报 FAIL。

## [2026-08-03] collect_children 顶层平铺页面整树误抓（已修复）

- **现象**：docs.px4.io 等「顶层页面平铺」导航站点（Furo 主题，所有一级页面在同一 toctree ul 下），当前页面在导航树中**没有子页面**时，`collect_children` 仍收集了 98 个「子页面」并逐个抓取——包括兄弟章节（Assembling a Multicopter 等）、外部站点（px4.io、qgroundcontrol.com、mavsdk.mavlink.io）、版本切换（main/v1.16/v1.14/v1.13）、语言切换（zh/ko/uk），甚至正文列表里的链接和指向当前页面自身的递归链接。
- **根因**：容器定位逻辑「从 current_a 向上找还包含其他链接的最近祖先」——顶层叶子页所在项（li）内没有嵌套导航，容器一路扩大到整棵导航树；`nav_level` 对树内所有链接的层级数恰好都是 1/2，全部被当作子/孙页面。
- **修复**：`scripts/web2md.py` 三处：① 新增 `_child_nav_container()`——子页面容器改为「current_a 所在项（li/section）内的嵌套 ul/div.items」，无嵌套容器（叶子页/顶层平铺页）直接返回空列表，**不再向上扩大到整树**；② 新增 `_same_doc_tree()`——收集时过滤与 base_url 不同域或不共享目录前缀的链接（排除外部站点、版本/语言切换）；③ `nav_level()` 对 ul/div.items 容器补计 1 级（container 语义从「祖先」变为「子页面容器」后层级数少 1）。保留原有单页文档锚点（`_strip_fragment`）与锚点变体（`accepted_stripped`）过滤。
- **排查方法**：日志出现「发现 N 个导航子页面」且子页面含兄弟章节/外部域名/版本切换链接时即为此类；回归场景：顶层叶子页返回空、父页面返回子/孙页面、外部/版本/语言链接被过滤、单页文档锚点返回空、锚点变体跳过、孙级锚点跳过、找不到当前节点返回空（7 个场景全绿）。

## [2026-08-02] collect_children 同页锚点变体仍被当子页面重复抓取（已修复）

- **现象**：多页文档中某页面在导航里自带章节锚点链接（如 `customizing.html#nsh-commands`）时，该锚点被收集为子/孙页面；递归抓取时与目标页面（customizing.html）同 URL、同标题，写入同一文件夹互相覆盖——内容无损但浪费请求、子页面收集数虚高。
- **根因**：`_strip_fragment` 过滤只与**根父页（base_url）** 比较；锚点变体去 fragment 后等于**另一个子页面**（嵌套为孙级，或平铺为兄弟子项）而非根页，绕过了过滤。
- **修复**：`scripts/web2md.py` `collect_children` 两层防护：① 收集循环维护 `accepted_stripped`（已接受链接去 fragment 后的 URL），任何链接与已接受页面同页即跳过——覆盖平铺兄弟与嵌套孙级两种形态；② 孙页面挂载循环再判「孙页面与直接父页面（u1）同页」跳过。新增回归测试 `test_collect_children_flat_anchor_sibling_skipped` / `test_collect_children_grandchild_anchor_to_parent_skipped`。
- **排查方法**：子页面收集日志出现「子页面标题与其他页面相同、产物互相覆盖」且非单页文档时，检查导航中是否有 `页.html#xxx` 形式的锚点链接（平铺或嵌套）；与单页文档过滤（`test_collect_children_ignores_same_page_anchors`）为同族场景。

## [2026-08-02] extract_title 残留 Sphinx 锚点图标 U+F0C1（已修复）

- **现象**：文件夹名/文件名/md 首行标题带 `Commands`（Sphinx 锚点图标，U+F0C1），正文标题已被 normalize 清理但提取标题未覆盖。
- **根因**：`_INVISIBLE_CHARS` 正则缺 `\uf0c1`，只覆盖零宽/NBSP/BOM 等。
- **修复**：`scripts/web2md.py` `_INVISIBLE_CHARS` 追加 `\uf0c1`。新增回归测试 `test_extract_title_strips_sphinx_anchor_icon`（覆盖 h1 与 `<title>` 两条路径）。
- **排查方法**：转换后 grep `` 应无残留（含文件夹名）；若只有首行标题残留即为此类。

## [2026-08-02] collect_children 把单页文档章节锚点误当子页面（已修复）

- **现象**：NuttX 等单页文档（侧边栏子项全部是 `当前页.html#xxx` 章节锚点）时，collect_children 把数十个锚点当子页面，逐个重新抓取同一页面并覆盖写入同一文件，最终只剩最后一次内容；子页面收集产物无效且耗时。
- **根因**：`_norm_nav_url` 不去锚点；子链接过滤只用 `href.startswith('#')` 拦相对锚点，`commands.html#xxx` 这类「完整 URL + 锚点」未被拦截。
- **修复**：`scripts/web2md.py` 新增 `_strip_fragment()`（urlsplit 去 fragment）；`collect_children` 中 current_a 定位与子链接过滤均改为「去 fragment 后的规范化 URL 与当前页面比较」，同页链接一律跳过；current 链接带锚点也能正常定位。新增回归测试 `test_collect_children_ignores_same_page_anchors` / `test_collect_children_current_link_with_anchor`。
- **排查方法**：转换日志出现「发现 N 个导航子页面」且子页面标题与父页相同、产物相互覆盖时，即为此类；用上述测试或核对 nav 子链接是否全部指向当前页锚点。

## [2026-08-02] GitBook 导航 h1 与搜索模板混入正文（已修复）

- **现象**：GitBook 3.x 页面转换后两类结构残留：① 顶部导航栏 `.book-header` 的 `<h1><a href="..">标题</a></h1>` 被转成 `# [标题](站点根URL)`——与脚本 title H1、正文标题三重重复，且链接指向站点根而非精确章节；② 隐藏搜索面板 `#book-search-results` 的模板（`results matching "..."` / `No results matching "..."`）被转进 .md 尾部。
- **根因**：`normalize_document_html` 只针对 Sphinx（`is_sphinx_document`）做标题/链接规范化，未识别 GitBook 的导航栏与搜索模板 DOM。
- **修复**：`scripts/web2md.py` 新增 `is_gitbook_document()`（`meta[generator]` 含 GitBook 或存在 `#book-search-results`）与 `remove_gitbook_chrome()`，在 `normalize_document_html` 中、`normalize_document_links` **之前**调用——先删 `.book-header` 与 `#book-search-results` 内的 `.has-results` / `.no-results` 模板 div，避免其 `<a href="..">` 被绝对化后残留。**关键陷阱**：GitBook 3.x 的正文容器 `.search-noresults` 嵌套在 `#book-search-results` 内部，只能删模板 div，绝不能整体删除容器（否则正文丢失）；模板 class 是 `no-results`（带 s）。新增回归测试 `test_gitbook_chrome_removed`（`scripts/tests/test_sphinx_conversion.py`）。
- **排查方法**：GitBook 页面转换后 grep `results matching` / `No results`（搜索模板）与 `# [标题](站点根/)`（导航 h1）；若正文整体消失，说明 `remove_gitbook_chrome` 误删了 `#book-search-results` 容器——检查选择器是否只命中 `.has-results` / `.no-results`。

## [2026-08-02] class="math" 纯字母公式被 \{}^_ 过滤漏转（已修复）

- **现象**：Sphinx 页面的纯字母内联公式（如 `\(L=W\)`、`\(AR\)`、`\(x, y, z\)`、`\(n=1.0\)`）在生成的 .md 中残留 `\(...\)` 语法，Typora 无法渲染。同页面还伴随三类 Sphinx 遗留：方程编号锚点混入公式块（`$$` 内 `(5)#\[...\]`）、裸 LaTeX 文本命令（`\textsl{...}`）、`aligned` 环境内的 `\label`。
- **根因**：`web2md.py` `process_math_formulas` 的 class="math" 分支用 `re.search(r'[\\{}^_]', text)` 决定是否转换——该检查在剥离 `\(` `\)` 定界符之后进行，纯字母公式正文不含 `\{}^_` 因而被漏掉。
- **修复**：`scripts/web2md.py` class="math" 分支引入 `delimited` 标志——凡被 `\(...\)` / `\[...\]` 定界符完整包裹的元素无条件转换（`if delimited or re.search(...)`），仅对无定界符包裹的文本保留原有过滤；新增回归测试 `test_math_plain_letter_delimited_formulas`（`scripts/tests/test_sphinx_conversion.py`）。
- **排查方法**：转换后 grep `\(` / `\)` 应无残留；同页面还需人工检查：`$$` 块内 `(N)#` 编号锚点、裸 `\textsl{...}` / 其他 LaTeX 命令、`aligned`/`split` 环境内 `\label`（MathJax 3 仅限编号环境，嵌套会报错导致公式渲染失败）。

## [2026-08-01] 抓取/转换失败无调试快照（已修复）

- **现象**：页面抓取成功但转换/下载/写出阶段抛异常时，进程只打印错误并退出，原始 HTML 不落盘——`final_verify` 报错后无法回溯转换前的页面结构，排查只能重新抓取。
- **根因**：`web2md.py` 的 `main()` 中 `fetch_page` 返回的原始 HTML 只用于转换，未在任何失败路径保存。
- **修复**：`scripts/web2md.py` 新增 `_save_debug_snapshot()`，`main()` 在转换/写出阶段捕获异常时，把原始 HTML 写入 `{项目根目录}/.web2md_tools/_archive/fetch_YYYYMMDD_HHMMSS.html`（成功路径不落盘）。
- **排查方法**：失败时看 `{项目根目录}/.web2md_tools/_archive/` 是否有 `fetch_*.html`；把快照喂给 `process_math_formulas` / `normalize_document_html` 可离线复现；selftest 有 `test_save_debug_snapshot` 覆盖。

## [2026-08-09] fix_escapes 不再全局替换散文（codex 优化合并，已修复）

- **现象**：阶段 A 运行后，散文中表示字面量的 `\_` / `\*`（如 `foo\_bar` 想显示为 `foo_bar`）被替换成 `_` / `*`，可能意外变成强调或下划线语法。
- **根因**：`fix_escapes.py` 旧版在完成公式块修复后，对**代码外全部文本**做全局 `\_`→`_`、`\*`→`*` 兜底——它分不清"公式内的转义"与"散文中刻意写的字面转义"（Markdown 里 `\_` 本来就是字面下划线的写法）。
- **修复**（2026-08-09 合并 codex 优化）：`fix_escapes.py` 重写为**只修复数学 span**——`$$` 块和长度 ≤2000 字符的 `$...$` 块内替换 `\_`/`\*`；散文中的合法 Markdown 转义、代码内容、未配对 `$` 一律逐字节不动。SKILL.md 阶段 A 说明同步更新。
- **排查方法**：交付的 .md 中原本显示字面下划线/星号的散文被改成强调语法时，即为此类（旧版行为，已修复）；新版如仍见散文 `\_` 残留属正常（字面转义），在阶段 C 通读复核时留意。

## [2026-08-01] fix_escapes 全局兜底会替换散文中的合法字面转义

- **现象**：阶段 A 运行后，散文中表示字面量的 `\_` / `\*`（如 `foo\_bar` 想显示为 `foo_bar`）被替换成 `_` / `*`，可能意外变成强调或下划线语法。
- **根因**：`fix_escapes.py` 的 `fix_outside_code` 在完成公式块修复后，对**代码外全部文本**做全局 `\_`→`_`、`\*`→`*` 兜底——它分不清"公式内的转义"与"散文中刻意写的字面转义"（Markdown 里 `\_` 本来就是字面下划线的写法）。
- **修复**：保留兜底逻辑（上游 Codex 版同款行为，公式修复收益大于散文误改风险）；已在 SKILL.md 阶段 A 增加提示："代码外全局兜底也会把散文中合法表示字面量的 `\_` / `\*` 一并替换，复核时留意这类非公式转义。"
- **排查方法**：交付的 .md 中原本显示字面下划线/星号的散文被改成强调语法时，即为此类；在阶段 C 通读复核时留意。
