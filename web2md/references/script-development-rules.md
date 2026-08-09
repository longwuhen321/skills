# 脚本开发规则（脚本关键技术要点）

> 按需读取：**修改或新增 `scripts/*.py` 之前必读本文件**（对齐既有防御机制与红线，
> 避免破坏设计）；正常转换流程不读。
> 更新约束：改动脚本后须同步本文件（防御性设计表按实际机制增删改）；
> 修改 `scripts/*.py` 后必须跑 `scripts/test/selftest.py` 全绿才算完成。

## 防御性设计

| 机制 | 位置 | 说明 |
|------|------|------|
| `unquote()` 图片文件名 | `download_images` | Wikipedia URL 含 `%28` `%29` `%3D` 等编码，需解码后再做文件名 |
| `wikipedia_latex` 择优 | `process_math_formulas` #1 | annotation 文本可能被截断，选花括号平衡且更完整的 img alt TeX 源 |
| 受保护子树 DOM 规范化 | `normalize_document_html` | 链接/标题/占位符清理在公式提取前完成，math/code 子树不动 |
| 文本节点占位符保护 | `protect_angle_placeholders` | 把转义占位符包成 `<code>`，不碰真实 HTML 标签与 math/code 内容 |
| 代码掩码 | `markdown_code.py` | fix_escapes / list_display_fixes / find_all_missed / final_verify 全部忽略围栏与行内代码；`markdown_fenced_code_spans` 供段落合并器复用同一套反引号 / 波浪号围栏识别 |
| 配置字面量解析 | `config_literal.py` / `load_config` / `check_config_sync.py` | AST 只允许一项普通 `web2md_config = {...}` 直接赋值，再用 `ast.literal_eval` 取值；`AnnAssign` 带注解赋值、导入、调用、属性访问、其他赋值和副作用语句在执行前拒绝。运行加载与同步门禁共用同一解析器，禁止重新引入 `exec` |
| 配置同步门禁 | `check_config_sync.py` | 对比 `scripts/config.py` 与 `config.example.py` 的 `web2md_config` **键集合 + 值类型**；只比结构不比 `python_path` 值（占位符 vs 真实路径天然不同）；不一致退出码 1（缺失/多余/类型不匹配逐条列出），文件缺失/损坏退出码 2；`--config-text` 从 stdin 读取供向导写入后复核 |
| 发布敏感检查 | `package_check.py` | `--root` 只读扫描待发布目录：先按路径拒绝 `config.py`、`.env*`、logs、缓存、Token 文件、符号链接及 junction/reparse point；禁用目录不进入，被拒文件不打开；再检查允许文本中的 Token 前后缀键（如 `api_token` / `auth_token` / `confluence_token`）的引号或无引号真实值及已知 Token 格式。0/1/2 分别为通过/发现禁项/无法完整读取 |
| `is_wiki` 域名判断 | `html_to_markdown` | 语言栏/编辑链接清理、`[[edit]]` 移除仅对 `wikipedia.org` / `wikimedia.org` 生效 |
| 定义列表表格去缩进 | `normalize_definition_list_tables` | 去掉 markdownify 的 `:   ` 与四空格嵌套，让 Typora 能解析表格 |
| `$$` 独占一行 | `html_to_markdown` | `([^\n])\$\$` → 前插 `\n\n`，`\$\$([^\n])` → 后插 `\n\n`，确保 Typora 识别 |
| Windows 安全输出名 | `sanitize_filename` / `resolve_output_name` | 处理非法字符与保留名；保留名判断前对第一个点前的 stem 去除 Windows 会忽略的尾随空格/点。按 `root/name/name.assets/<图片文件>` 计算路径预算；清洗冲突时追加规范化源 URL 的稳定 SHA-256 前缀，不覆盖既有不同来源目录 |
| 同页锚点过滤 | `collect_children` | 单页文档章节锚点（`commands.html#xxx`）与孙级锚点（`父页.html#xxx`）经 `_strip_fragment` 去 fragment 后与当前页/直接父页 URL 相同 → 跳过，避免重复抓取同一页面互相覆盖 |
| 导航收集分层（基座+策略+汇总） | `nav_children.py` | 通用基座（URL 规范化/current_a 定位/容器查找/层级判定/去重）只写一遍；策略层每主题只写差异（`strategy_sphinx`/`strategy_vitepress` + STRATEGIES 注册表）；汇总 `collect_children` 返回 `{structure, children, notes}` dict。**新主题 = 追加 strategy 函数 + 注册**，不动基座 |
| RTD 当前项 href="#" 参与定位 | `nav_children._collect_base` | Sphinx RTD 主题当前项导航链接是 `href="#"` 占位（靠 `li.current` class 标记），`href_raw == '#'` 且 urljoin 后 == 当前页 → 参与 current_a 定位；`#VPContent` 类真实锚点（`startswith('#')` 且非 `#`）仍跳过——`== '#'` 判据天然区分两者（2026-08-08 回归教训：一刀切跳过 `#` 开头链接曾误杀 RTD） |
| 导航空结果诊断（notes） | `nav_children.collect_children` / `web2md.py` fetch_and_process | 空结果时 notes 输出「未定位到当前页/无子页面容器/被过滤/结构未识别」原因 + 定位成功信息，web2md.py 打印「🧭 导航诊断」——AI 助手据此判断「真没有」还是「漏识别」，零网络依赖；未命中任何主题特征时按通用 li/ul 兜底（structure='generic'） |
| 渲染后导航降级 | `collect_navigation` / `--rendered-html` | 只在静态导航为空时采用渲染 DOM；用 `--rendered-url` 或 canonical/og:url/base 校验快照基准，页面 identity 保留 query。版本段（如 `v1.15` / `latest`）形成稳定路径前缀，`/v1` 不得退化为 `/` 接受 `/v2`，再限制同域与两级深度。不可校验或仍为空时报告 REVIEW 并令 CLI 非零退出，转 `--children-from`；已识别且已定位的真实叶子页正常通过 |
| 裸定界符配对保护 | `convert_plain_tex_delimiters` | 同正文节点配对 `\(...\)`/`\[...\]`；跨节点只允许同一块边界、最多 12 个文本节点/2000 字符、仅中性 `span` 且下一定界符唯一匹配。Comment、Doctype/声明等非正文 `NavigableString` 不参与；候选跨越它们时保持整棵 DOM 原样并计 REVIEW。跨块、math/code 保护子树、格式化标签、歧义/超限同样保持原文；跳过 `\\[` 行距，`\left(` / `\left[` 天然不匹配 |
| 重复 H1 剥离守卫 | `strip_duplicate_h1` | 页面自身 h1 文本与 `extract_title` 提取标题相同时剥离（避免与脚本前缀 `# {title}` 重复）；含 math/code/pre/script/style 子树的 h1 不剥离；比较与 `extract_title` 同源，不存在误判路径 |
| 标题数学清理 | `clean_title_math` | 标题含裸 TeX 定界符/命令（如 `\( \alpha \)`）时去定界符 + 希腊字母/常用运算符转 Unicode + 压缩空白；未映射命令保留不误删；`extract_title` 与 `strip_duplicate_h1` 共用同一清理，保证命名、前缀 H1、去重三者一致 |
| 段落合并结构保护 | `merge_paragraphs.py` | 通过 `markdown_code.py` 的围栏 span 与独立 `$$` 状态掩码，反引号 / 波浪号围栏及显示公式块（含内部空行）逐字节不动；公式标签 hard break 行（缩进+行尾两个空格）保留整行及其原始 CRLF/LF/CR，文件读写使用 `newline=''`，且绝不与下一段合并；嵌套子列表、Sphinx 定义列表（term+缩进定义段）、表格行（`\|` 开头）不合并；空行只在保护块外压缩且至少保留一个 |
| 表格后空行分隔 | `ensure_table_separators` | 表格块（连续 `\|` 开头行）后若非空行则补空行，避免表格与 `$$` 块/段落粘连（markdownify 表格后紧邻块级元素时不输出空行）；在 `html_to_markdown` 内无条件调用，不依赖 merge 开关 |
| 表格单元格显示公式行内化 | `convert_plain_tex_delimiters` | `table_formula_inline`（默认 true，config + CLI 覆盖）时，`<td>`/`<th>` 祖先内 `\[...\]` → `$`（行内），防 `$$` 块 + 空行撕裂表格；仅文本节点级配对替换，受保护子树不动 |
| 表格行内公式不升级 `$$` | `list_display_fixes` | 含 `\\begin{...}` 或 `\\` 行断的 `$...$` 若位于表格行内（去除空白后以 `\|` 开头且含第二个 `\|`）不自动升级 `$$`（会重新撕裂表格），列为「表格内（保持 $）」候选交 AI 复核 |
| 父页面导航块 | `append_nav_block` / `build_nav_block` | `page_nav`（默认 true）时抓取到子/孙页面后在父 md 末尾追加 Sub-pages 列表；顺序 = children_list / 导航收集顺序；`_fetch_child_tree` 返回实际标题与相对路径（孙页面嵌套缩进）；**链接路径含空格必须 `< >` 包裹**——final_verify 链接正则 `([^\s)\n]+)` 在空格处截断，不带 `< >` 误报「相对链接目标不存在」 |
| 表格 / 图片代码掩码与表格后空行兜底 | `final_verify.py` | 表格和图片结构检查统一读取保留换行的代码掩码，代码示例不误报；有分隔行的真表格，块结束后下一行非空即报「行 N 表格后缺空行」FAIL |
| 未配对 `$` 门禁 | `final_verify.py` | 顺序扫描未转义的 `$` / `$$`；悬空定界符报 FAIL，`\$` 与代码中的 `$` 不参与计数 |
| 清单解析容错 | `parse_children_list` | `--children-from` 清单：注释/空行/备注列忽略，深层级缩进、缺 URL、无父页面的孙页面行跳过并警告——单行格式错误不中断整批抓取 |
| `_clean_invisible_chars` 含 U+F0C1 | `extract_title` | Sphinx 标题锚点图标 ``（U+F0C1）与零宽/NBSP/BOM 一并清除，防止混入文件夹名与 md 标题 |
| Wikimedia 限流退避 | `download_images` | HTTP 429 时递增等待 2/4/6 秒，Wikimedia 图片间加 0.3s 间隔 |

## 明确不要做的事

- **不要把 `\{` `\}` 当 Markdown 转义修复**——它们是 `\left\{` `\right\}` 的合法 LaTeX 组件
- **不要在 math/code 子树内做链接、标题、占位符规范化**——公式载荷在 `process_math_formulas` 提取前必须逐字节不变
- **不要用全局 Markdown 正则包 `<...>` 占位符**——只在合格的 DOM 文本节点上操作，真实 HTML、代码、LaTeX 不受影响
- **不要自动发明表头或把引用块全量转代码**——那是需要通读全文的语义决策
- **不要用正则去区分 `**i**` 是公式还是粗体**——这是 AI 助手的工作，脚本做不到
- **不要对非 Wikipedia 页面做 Wikipedia 特有清洗**——`is_wiki` 兜底
- **即使用脚本执行替换，判断必须由 AI 助手做**——`**i**` → `$\mathbf{i}$` 这类转换，脚本只能做精确的 `str.replace`（AI 助手手写每一条 old→new 对），不能用正则或自动判断。区分「表格粗体」和「数学符号粗体」是上下文理解，脚本做不到
- **脚本只做机械操作，AI 助手审核全部**——脚本只在已配对公式内负责 `\_` → `_`、`\*` → `*` 等机械修改，散文合法转义与代码不动；`$$` 独占一行等结构问题由验证器拦截。但这些修改可能出错（修漏、修错、修坏）——AI 助手必须通读全文，逐一验证每个公式是否渲染正确，包括脚本改过的和没改过的。不以「脚本已处理过」为由跳过，质量优先，不省 token
