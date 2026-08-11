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

## [2026-08-11] 页面歧义、查询错误和过期内容可能写错页面或覆盖新版本（已修复）

- **现象**：同名页面会直接更新第一个候选，`--parent-id` 未真正消除歧义；查询异常可能被当成页面不存在后继续创建；409 重试和公式 `--confirm` 可能提交旧正文；附件或子页失败仍返回成功；递归只处理前 200 项、空间导出重复子树；未知宏、外链图片、代码宏空行或同名路径可能丢失/被改写。
- **根因**：页面查找只有“找到/没找到”两态且未按真实父级过滤；更新流程未绑定源版本/哈希；批量路径分别吞掉异常且缺公共分页器；导出在还原代码后继续全局归一化，命名只做字符清洗；未知宏与 `ri:url` 没有可逆降级；配置仍由 `exec` 执行，依赖与发布敏感项也缺统一门禁。
- **修复**：`md_import.py` 增 `FOUND / NOT_FOUND / ERROR`、父级/`--page-id` 消歧、源版本绑定和仅导入 409 可显式 `--force` 的单次重试；`math_upgrade.py` 确认前复取版本+SHA256且变化必停、零残留默认门禁和 alignment 幂等；`common.py` 提供公共分页器；`md_export.py` 统一非递归空间核心、代码占位空行处理、page ID 目录与附件 containment、`[toc]` 闭环、未知宏正文+原始 XHTML 注释及 `ri:url`/外链图；所有未处理失败令 CLI 非零。配置改 `config_parser.py` 的 AST + `ast.literal_eval`，并新增依赖/发布门禁和树计划 checkpoint `--resume`。
- **排查方法**：运行 `scripts/test/selftest.py`，重点查看 `test_regressions.py` 的多候选/三态、409、stale confirm、附件失败入口退出码、分页、未知宏/外链图、路径 containment、resume、依赖与 packaging 对抗用例；真实运行先执行 `python -X utf8 scripts/dependency_check.py` 和配置同步门禁，任何查询/附件/批量错误或非零退出码都不得当作成功继续。

## [2026-08-05] load_config 漏组装 export_config 分组：md_export 配置永远不生效

- **现象**：config.py 补写了 `export_config`（output_dir=绝对路径），但导出仍输出到默认相对目录 `confluence_export`；`python -c "import config"` 能看到配置，`load_config()` 却返回 `export_config=None`。
- **根因**：`scripts/common.py` `load_config()` 的 return dict 只组装了 4 个分组（common/import/upgrade/debug），**漏了后来新增的 `export_config`**——md_export 的 `cfg.get('export_config', {})` 永远拿到空 dict 走代码默认值。selftest 未暴露：TestMdExport 用 `patch('md_export.load_config', return_value=MOCK_CFG)`，mock 配置里有 export_config，绕过真实加载路径。
- **修复**：`scripts/common.py` `load_config()` return 增加 `'export_config': ns.get('export_config', {})`，docstring 同步为"五个分组"。
- **排查方法**：config.py 有配置但脚本行为像没读到（用默认值）时，先 `load_config()` 打印分组是否齐全，再查 `common.py` 的 return 组装是否漏了新分组；selftest 有 `test_load_config_returns_export_config` 覆盖（真实写临时 config.py 走 load_config 全路径）。
- **教训**：新增配置分组时，`common.py` 的 `load_config()` 组装、`config.example.py` 模板、SKILL.md 配置向导三处要同步——本 bug 正是"模板与向导已同步、加载器漏了"的典型。

## [2026-08-05] md_export：toc 宏嵌在 h1 内被并成一行、空 pre 导出为空代码围栏、ac:link 内链丢失

- **现象**：导出 rcS 页面（73597027）后：① `[toc]` 目录失效——md 中出现 `# [toc] 前提：`（toc 与标题合并成一行，Typora 要求 `[toc]` 独占一行才渲染目录）；② 4 个空代码围栏（``` 空 ```）——页面上是作者留白用的空等宽块，用户误以为"折叠的代码丢失"；③ 内链丢失——"查看： 。"处 `ac:link` 链接文字消失（`<ac:link><ri:page ri:content-title="rcS脚本解读"/></ac:link>`）。
- **根因**：① 原始 storage 为 `<h1><ac:structured-macro ac:name="toc" .../><br/>前提：</h1>`——toc 宏嵌在 h1 **内部**，`_convert_macros` 用占位 `<div>` **原位替换**，markdownify 把 h1 内全部内容合并输出一行；② 页面含 `<pre><br /></pre>`（无文本的空 pre），markdownify 转成空代码围栏；③ `ac:link` 宏（内链/外链/附件/用户）完全未处理，标签被 markdownify 剥掉后文字也丢。
- **修复**：`scripts/md_export.py`——① toc 分支：占位 div 不再原位替换，父元素非 document/body 时 `parent.insert_before(div)` + `macro.decompose()`，`[toc]` 独占一行；② 新增 `_drop_empty_pres`（`pre.get_text(strip=True)` 为空 → decompose），在 `_convert_macros` 前调用；③ 新增 `_convert_links`：`ac:link` → `<a>` 标签（markdownify 转 markdown 链接），ri:url → 外链、ri:page/ri:child-page → 有 content-id 生成 `${base_url}/pages/viewpage.action?pageId={id}`、无 id 保留标题文本、ri:attachment/ri:user 保留兜底文本；显示文本优先 `ac:link-body`。
- **排查方法**：md 出现 `# [toc] xxx`（toc 与标题同行）、` ``` ` 后紧跟 ` ``` ` 的空围栏、正文中链接文字消失（原文 `<ac:link>` 结构）即此类；selftest 有 `test_toc_inside_h1_stays_on_own_line` / `test_empty_pre_dropped_no_empty_fence` / `test_ac_link_page_with_id_to_markdown_link` / `test_ac_link_page_without_id_keeps_title` / `test_ac_link_url_with_body_to_markdown_link` 覆盖。

## [2026-08-04] debug 清理失效：时间戳目录扫描不到 + 完整路径排序误删最新快照

- **现象**：`debug/import` 子目录累积 43 个仍不清理（`keep_recent=20` 形同虚设）；改为递归扫描后 `debug/export` 最新快照被误删（export 目录时间戳最新却被当"最旧"优先删）。
- **根因**：两处——① `_get_timestamp_dirs` 只列 `debug_root` 直接子目录（`import/`/`upgrade/`/`export/` 3 个），时间戳目录嵌套在其下**从未被统计**；叠加原清理需"大小超 **且** 数量超"双条件，实际从不触发；② 递归修复后按**完整路径**排序，功能子目录字母序（`export`<`import`<`upgrade`）优先于时间戳，`export` 目录总排最前被误删。
- **修复**：`scripts/debug_utils.py`——清理触发改"大小/数量**二选一**即清理"（从最旧删到都达标，保留下限 keep_recent）；`_get_timestamp_dirs` 改 `os.walk` 递归扫描 `YYYYMMDD_HHMMSS` 格式目录；排序改按时间戳名（`sort(key=basename)`）。
- **排查方法**：debug 目录长期不清理时，先确认时间戳目录是否嵌套在功能子目录下（旧版只扫一层）；删除异常时检查排序键是否混入路径前缀；selftest 有 `test_cleanup_debug_by_count_when_size_ok` / `test_get_timestamp_dirs_sorted_by_name_across_subdirs` 覆盖。

## [2026-08-04] md_export：表格单元格含代码块 → GFM 围栏破坏表格结构（导出乱码）

- **现象**：md_export 导出含代码表格的页面（apriltag 方案精准降落实测），Typora 打开表格乱码——行列错乱、`|` 被误判列分隔；md 中表格单元格出现 ` ``` ` 围栏横跨多行。
- **根因**：GFM/Typora 表格单元格不能含多行围栏代码块。markdownify 把表格内的 `<pre><code>` 直接输出为围栏（` ``` `），围栏横跨单元格结构；代码内 `|`（如 `||`）未转义，进一步破坏列分割。
- **修复**：`scripts/md_export.py` 新增 `_protect_complex_tables`（宏/图片转换后、markdownify 前调用）：含 `pre`/`code`/`ac:` 的表格整体保留为**原始 HTML**（占位符还原，Typora 原生渲染 HTML 表格，代码/图片/公式引用不丢）；纯文本表格走 GFM 且单元格文本 `|` → `\|`。同时修正占位符还原顺序——HTML 表格先还原（其内部含 CODE/MI/MB 占位符），其余占位符随后全局替换，否则表格内占位符残留。
- **排查方法**：导出的 md 中表格单元格出现 ` ``` ` 围栏或行列错乱即此类；selftest 有 `test_table_with_code_kept_as_html` / `test_table_pipe_escaped_in_gfm` / `test_table_html_code_placeholder_restored` 覆盖。

## [2026-08-04] ==高亮== 正则误配 base64 图片 padding，`<strong>` 进入 src 属性 → 导入 400

- **现象**：含内嵌 base64 图片（`![](data:image/png;base64,...== "title")`）的页面导入报
  `400 Error parsing xhtml: Unexpected character '<' (code 60) in attribute value`；
  调试 HTML 中 `<img src="data:...base64<strong>"`，`<strong>` 混入 src 属性值
  （Altitude Mode (Fixed-Wing) 页面实测，首次 --dir 导入 12 页仅此页失败）。
- **根因**：`_convert_highlight_marks` 的 `==高亮==` 正则 `==([^\n]*?)==` 把 base64
  data URI 的 `==` 结尾（base64 padding）当作高亮标记；同一行内两个 base64 图片的
  `==` 被配对成高亮，中间整段（含 `<img>` 标签）被包成 `<strong>` 并写进 `src`
  属性，生成畸形 XHTML，Confluence 拒绝解析（报错特征：code 60 = 裸 `<` 出现在属性值）。
- **修复**：`scripts/md_import.py` `_convert_highlight_marks` 的 re.split 保护模式增加
  `<img\b[^>]*>` 分支（与既有宏/代码保护一致），`<img>` 标签整体跳过高亮转换；
  该函数在 `_convert_md_links` 之前执行，img 随后由后者正常处理（data: URI 保留原始引用）。
- **排查方法**：导入 400 报 `Unexpected character '<' (code 60) in attribute value` 且
  md 含 base64 内嵌图片时，查 `debug/import/*/before_upload.html` 是否 `<strong>` 出现在
  `<img src="...">` 属性内；selftest 有 `test_highlight_marks_ignore_base64_padding` 覆盖。

## [2026-08-03] 自闭合宏（toc 目录宏）破坏保护段分割，图片被吞不转换

- **现象**：TECS 页面（73596957）导入后 3 张图片不显示，storage 中 `<ri:attachment>` 引用
  数少于 md 中图片数；页面顶部有 toc 宏时 `_convert_md_links` 只转换了部分图片。
  源 md 是标准 `![alt](path)` 语法，导入无失败报告。
- **根因**：toc 宏是**自闭合**标签 `<ac:structured-macro ac:name="toc" .../>`，没有
  `</ac:structured-macro>` 闭合标签。宏保护正则 `.*?</ac:structured-macro>`（非贪婪）从
  自闭合宏开始匹配到**后面第一个成对宏**（如 mathinline）的闭合标签，把中间所有内容
  （含图片）误判为"宏内部"而跳过转换。自闭合宏由 2026-08-02 新增的 toc 自动目录功能引入。
- **修复**：`scripts/md_import.py` 4 处（`_convert_math_blocks` / `_convert_code_blocks` /
  `_convert_md_links` / `_clean_unnecessary_backslashes`）与 `scripts/math_upgrade.py`
  verify 残留检测（`re.sub` 去宏处）的宏保护正则统一改为
  `<ac:structured-macro\b[^>]*/>|<ac:structured-macro\b.*?</ac:structured-macro>`
  二选一（先匹配自闭合，再匹配成对）；math_upgrade 173 行原有模式即此，属对齐。
- **排查方法**：页面图片缺失且无失败报告时，看 `debug/import/*/before_upload.html` 是否残留
  未转换的 `<img>` 标签；或打印 `_convert_md_links` 的 `protected_parts` 分段，若图片所在段
  被标记为保护段（i 为奇数）即此因。selftest 有
  `test_self_closing_macro_does_not_swallow_images` 覆盖。

## [2026-08-02] 更新页面时同名附件上传 400，图片引用被覆盖为原始 markdown 路径

- **现象**：对已导入页面重跑 md_import（更新场景），4 张图片全部
  `附件上传失败: 400 ... /child/attachment`，结束时图片引用被写成
  `./Laplace transform - Wikipedia.assets/...`（原始 md 相对路径），页面图片变死链。
- **根因**：`_upload_attachment` 只用 POST `/child/attachment` 创建附件；同名附件已存在时
  Confluence 返回 400 `Cannot add a new attachment with same file name`（Server/DC 不允许
  重复创建），上传失败后 `_convert_md_links` 退回 `match.group(0)` 原始引用，
  **覆盖**首次导入的正确 `<ri:attachment>` 引用。
- **修复**：`scripts/md_import.py` `_upload_attachment` 遇 400/409 时
  `GET /child/attachment?filename=<name>` 查附件 id，再
  `POST /child/attachment/{id}/data` 更新数据。注意端点区分：**Server/DC 用 POST**，
  Cloud 文档是 PUT（实测 DC 9.2.1 POST 返回 200，PUT 返回 405）。
- **排查方法**：更新导入报"附件上传失败: 400 ... same file name"即此类；selftest 有
  `test_upload_attachment_updates_existing` 覆盖（mock session.request 按
  create 400 → GET 200 → update 200 顺序）。

## [2026-08-02] mathblock CDATA 内 LaTeX `](0)` 被图片正则误判

- **现象**：导入含 `$$...\\left[e^{-sX}\\right](0)....$$` 的 md 时，结束时误报
  `⚠️ 图片未能上传: 0（本地文件不存在: .../0）`，页面内容本身未损坏。
- **根因**：`_convert_md_links` 图片正则 `!\[(.*?)\]\((.*?)\)` 匹配了 mathblock 宏的
  `<![CDATA[` 前缀（字面 `![`），非贪婪 `(.*?)\]\(` 又恰好吞到 LaTeX 的 `\\right](`，
  `0` 被当成图片路径。该函数对**整个 HTML**（含已转换宏）做正则，未保护宏区域。
- **修复**：`scripts/md_import.py` `_convert_md_links` 先 `re.split` 保护
  `<ac:structured-macro>`/`<code>`/`<pre>` 区域（复用 `_convert_math_blocks` 既有模式），
  图片正则只作用于非保护部分。
- **排查方法**：导入结束报"本地文件不存在: <数字/短串>"且页面无此图即此类；selftest 有
  `test_md_links_ignores_macro_cdata` 覆盖。

## [2026-08-02] 行内公式含不等式（< >）未被识别导致导入 400

- **现象**：md 内 `$0<x<\pi$` 导入报
  `400 Error parsing xhtml: Unexpected character '&' (code 38) expected space, or '>' or '/>'`，
  调试 HTML 出现裸 `<x`。markdown2 对 `$0<x<\pi$` 转义不一致：`<x` 被当潜在标签保留为裸 `<`，
  `<\p` 却转成 `&lt;`，产物为 `$0<x&lt;\pi$`。
- **根因**：行内公式正则内容禁 `<`/`>`（`[^$<>\n]`，防 `$PWD / $OLDPWD` 跨 span 配对而加）。
  md 阶段 `_protect_math_blocks` 漏掉含不等式的公式 → markdown2 转出裸 `<x` →
  HTML 阶段 `_convert_math_blocks` 仍禁 `<` → `$0<x&lt;\pi$` 残留 →
  Confluence 把 `<x` 当标签解析，标签内遇到 `&` 报 400。
- **修复**：仅 `scripts/md_import.py` 两处放宽（`_protect_math_blocks` 与 `_convert_math_blocks`，
  `[^$<>\n]` → `[^$\n]`）。md 阶段是纯文本无标签，放宽安全；HTML 阶段 md 源不含
  storage span 结构，放宽可接受。**`scripts/math_upgrade.py` 不放宽**：它处理 Confluence
  storage 格式，`<` 已转义为 `&lt;` 实体，能通过旧正则 `[^$<>\n]`，本来就可匹配；
  放宽反而让 `$PWD</span>...<span>$OLDPWD` 跨 span 配对（回归
  `test_shell_variables_not_math`）。错误放宽后已回滚（见下方"踩坑"）。
- **排查方法**：400 报 `Unexpected character '&' ... expected space, or '>' or '/>'` +
  调试 HTML 存在裸 `<x` 即此类；selftest 有
  `test_inline_math_inequality_protected`（md_import，裸 `<` 形式）与
  `test_inline_math_inequality_converts`（math_upgrade，storage 实体 `&lt;` 形式）覆盖。
- **踩坑**：曾把 math_upgrade.py 同步放宽，导致 `TestMathUpgrade.test_shell_variables_not_math`
  失败（`$PWD</span>...<span>$OLDPWD` 被跨标签配对）——storage 与 markdown 文本的
  `<` 存在形式不同（实体 vs 裸字符），两脚本的正则规则**不能盲目统一**，需按输入格式区分。

## [2026-08-01] 幂等性缺陷：重复升级导致版本号虚涨

- **现象**：已转换完成的页面每次重跑 math_upgrade 都报告"转换 N 处"
  并 PUT 版本 +1（TECS 页面 v2→v6），但页面内容字节级无变化。
- **根因**：`_apply_alignment` 对已是 `alignment=left` 的 mathblock 宏仍执行
  "移除参数+重新插入"（结果字节不变），`total_changes>0` → 每次都提交。
- **修复**：`scripts/math_upgrade.py` `_apply_alignment` 检测到宏已含
  `alignment=left` 时直接跳过（不重写、不计数）；重跑已转换页面 =
  "无需转换" = 版本不涨。
- **排查方法**：页面版本持续增长但内容无变化时，重跑一次看是否报
  "无需转换"；selftest 有 `test_apply_alignment_idempotent_when_already_left`
  覆盖。

## [2026-08-01] XHTML 配对检查器误报（CDATA 代码文本当标签）

- **现象**：verify 报 `多余闭合 </ac:plain-text-body>`，但页面宏数量正确、
  无公式残留；同类页面（含 C++ 代码宏）批量升级被批量拦截。
- **根因**：`_check_xhtml_balance` 未剔除 CDATA/注释——代码宏 CDATA 内的
  `<mmc::Irlock>`、`if (x < y)` 等文本被正则当成 HTML 标签入栈，污染
  配对栈，导致真正的 `</ac:plain-text-body>` 误判为多余闭合。
- **修复**：`scripts/math_upgrade.py` `_check_xhtml_balance` 先剔除
  `<!\[CDATA\[...\]\]>` 与 `<!--...-->` 再配对。
- **排查方法**：verify 报"多余闭合"且宏数量正确时，先确认页面是否含代码
  宏；selftest 有 `test_xhtml_balance_ignores_cdata_and_comments` 覆盖。

## [2026-08-01] span 删除导致 XHTML 不配对（PUT 400）

- **现象**：批量升级个别页面 PUT 报
  `400 Error parsing xhtml: Unexpected close tag </span>; expected </td>`。
  典型场景：表格单元格内 math span 嵌套
  `<td><span class="math-inline"><span>$x$</span></span></td>`。
- **根因**：span 删除正则 `<span[^>]*class=...math...>.*?</span>` 用非贪婪
  `.*?</span>`——嵌套 span 时把内层 `</span>` 当成自己的闭合，删完留下
  外层的孤立 `</span>`；且会整段删掉 span 内的公式内容。
- **修复**：`scripts/math_upgrade.py` 新增 `_strip_math_spans`：
  只剥"内容无嵌套 span"的 math span 的壳（**保留内容**），嵌套 span 原样
  保留；`verify()` 新增 `_check_xhtml_balance` 栈式标签配对校验
  （支持 ac:/ri: 前缀与 HTML 空元素），PUT 前拦截不配对 XHTML。
- **排查方法**：PUT 400 "Error parsing xhtml" 时看 verify 报告的
  "XHTML 标签配对" 行；selftest 有 `test_nested_math_span_kept_balanced`、
  `test_xhtml_balance_checker` 覆盖。

## [2026-08-01] mathinline 宏内 `\*` 未定义控制序列渲染报错

- **现象**：页面公式宏渲染报 `Undefined control sequence \*`（MathJax 不识别
  `\*`），如共轭符号写成了 `q^\* = a-bi-cj-dk`。
- **根因**：原始 LaTeX 文本中的 `\*` 被原样搬入宏 body，转换引擎只做
  `& < >` 转义，未清理非法控制序列。
- **修复**：`scripts/math_upgrade.py` 新增 `_sanitize_latex`（`\*` → `*`），
  应用于 convert() 的 block/latex/inline 三处及旧宏升级；
  `scripts/md_import.py` 的 `_clean_latex` 同步（inline body + block CDATA）。
  `*` 是 TeX 数学模式合法字符（渲染为星号）。
- **排查方法**：页面宏报 Undefined control sequence 时，先拉 storage 查宏
  body/CDATA 内的 `\*`；selftest 有 `test_undefined_control_seq_star_sanitized`
  用例（math_upgrade 与 md_import 各一）。

## [2026-08-01] 批量升级偶发"拉取失败"（无 debug 记录）

- **现象**：空间模式批量升级时个别页面报 `❌ 拉取失败`，debug 目录无该页面
  记录（可据此判定失败阶段：无 debug = 拉取失败；有 debug = verify/PUT 失败）。
  重跑同一页面可成功，属瞬时性问题。
- **根因**：fetch_page 网络/服务器瞬时错误（内网抖动、5xx），GET 未重试。
- **修复**：`scripts/common.py` `request_with_retry` 增加 `retry_on` 参数支持
  5xx 重试；math_upgrade 的 fetch_page / get_child_pages 与 collect_space_pages
  传 `retry_on=(429,500,502,503,504)`；`process_single` 拉取失败再兜底
  等待 3s 重试一次。
- **排查方法**：批量升级失败后看 debug 目录有无该页面记录判断失败阶段；
  无记录先重跑该页面确认是否瞬时问题。

## [2026-08-01] bash 变量 $PWD / $OLDPWD 被误识别为行内公式

- **现象**：页面正文（非代码宏内）出现 `$PWD / $OLDPWD` 时被转成 mathinline
  宏，且宏内容吞入 HTML 标签（`body=PWD&lt;/span&gt;...`），页面渲染错乱。
  典型结构：`<span><span>$PWD</span><span> / </span><span>$OLDPWD</span></span>`，
  正则把第一个 `$` 与 `$OLDPWD` 的 `$` 配对成公式。
- **根因**：行内公式正则只禁 `$` 和换行，未防：
  1) 闭合 `$` 前是空白（`$PWD / $OLDPWD` 跨变量配对）；
  2) 内容含 HTML 标签字符 `<`/`>`（跨 span 吞标签）。
- **修复**：`scripts/math_upgrade.py` + `scripts/md_import.py` 的行内公式正则
  统一为：开头 `$` 后禁空白、闭合 `$` 前禁空白、内容禁 `<`/`>`/`$`/换行；
  mathblock 内容同步禁 `<`/`>`；verify 残留检测正则同步。
- **排查方法**：升级后页面出现 body 含 `&lt;`/`&gt;` 的 mathinline 宏即为此类；
  selftest 有 `test_shell_variables_not_math` / `test_currency_not_math` 覆盖。

## [2026-08-01] base64 内嵌图片被当本地文件路径处理

- **现象**：md 内 `![alt](data:image/png;base64,...)` 内嵌图片导入后，控制台
  把整段 base64 当作"本地文件不存在"打印，失败报告刷屏。
- **根因**：md_import.py `_convert_md_links` 只排除了 `http`/`//` 前缀，
  未识别 `data:` URI，base64 内容被当成本地路径去 `os.path.exists` 判断。
- **修复**：`scripts/md_import.py` `_convert_md_links` 增加 `data:` 前缀分支
  ——跳过本地处理、保留原始引用、不进入失败报告，导入结束提示
  "跳过 N 张 base64 内嵌图片"。计数存 `self.data_images_skipped`。
- **排查方法**：导入输出中出现超长"本地文件不存在"且路径以 `data:` 开头，
  即为此类图片；selftest 有 `test_data_uri_image_skipped` 用例覆盖。

## [2026-08-01] `<p>` 标签错位导致导入 400

- **现象**：段落以行内公式（mathinline）开头、后接 mathblock 段时，导入报
  `400 Error parsing xhtml: Unexpected close tag </p>`，调试 HTML 中出现
  有 `</p>` 无 `<p>`（或反之）的段落。
- **根因**：md_import.py 5.5 步清理块级元素外层 `<p>` 的正则使用
  `.*?</ac:structured-macro>` + DOTALL，`.*?` 可跨段落延伸，把中间的
  `</p><p>` 吞进捕获组，导致两段标签各剩一半。
- **修复**：`scripts/md_import.py` 5.5 步改为 `(?:(?!<p).)*?` 防跨段匹配
  （组内禁止出现 `<p` 开标签，阻止跨段落延伸）。
- **排查方法**：导入失败时看 `debug/import/*/before_upload.html` 找不成对
  的 `<p>`；本地可用 XML 解析（把 `ac:`/`ri:` 前缀替换为空后）快速校验
  标签配对，配平即 OK。
