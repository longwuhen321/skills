# 脚本开发规则（脚本关键技术要点）

> 按需读取：**修改或新增 `scripts/*.py` 之前必读本文件**（对齐既有防御机制与红线，
> 避免破坏设计）；正常转换流程不读。
> 更新约束：改动脚本后须同步本文件（防御性设计表按实际机制增删改）；
> 修改 `scripts/*.py` 后必须跑 `scripts/debug/selftest.py` 全绿才算完成。

## 防御性设计

| 机制 | 位置 | 说明 |
|------|------|------|
| `unquote()` 图片文件名 | `download_images` | Wikipedia URL 含 `%28` `%29` `%3D` 等编码，需解码后再做文件名 |
| `wikipedia_latex` 择优 | `process_math_formulas` #1 | annotation 文本可能被截断，选花括号平衡且更完整的 img alt TeX 源 |
| 受保护子树 DOM 规范化 | `normalize_document_html` | 链接/标题/占位符清理在公式提取前完成，math/code 子树不动 |
| 文本节点占位符保护 | `protect_angle_placeholders` | 把转义占位符包成 `<code>`，不碰真实 HTML 标签与 math/code 内容 |
| 代码掩码 | `markdown_code.py` | fix_escapes / list_display_fixes / find_all_missed / final_verify 全部忽略围栏与行内代码 |
| `is_wiki` 域名判断 | `html_to_markdown` | 语言栏/编辑链接清理、`[[edit]]` 移除仅对 `wikipedia.org` / `wikimedia.org` 生效 |
| 定义列表表格去缩进 | `normalize_definition_list_tables` | 去掉 markdownify 的 `:   ` 与四空格嵌套，让 Typora 能解析表格 |
| `$$` 独占一行 | `html_to_markdown` | `([^\n])\$\$` → 前插 `\n\n`，`\$\$([^\n])` → 后插 `\n\n`，确保 Typora 识别 |
| 图片名截断 `max_len=60` | `sanitize_filename` | 避免超长文件名 |
| 同页锚点过滤 | `collect_children` | 单页文档章节锚点（`commands.html#xxx`）与孙级锚点（`父页.html#xxx`）经 `_strip_fragment` 去 fragment 后与当前页/直接父页 URL 相同 → 跳过，避免重复抓取同一页面互相覆盖 |
| 裸定界符配对保护 | `convert_plain_tex_delimiters` | 文本节点级配对 `\(...\)`/`\[...\]`；跳过 `\\[` 行距（开定界符前字符是反斜杠）、`\left(` `\left[` 天然不匹配、math/code 子树；跨节点配对不替换，计数输出交 AI 复核 |
| 段落合并结构保护 | `merge_paragraphs.py` | `$$` 块内逐字节、公式标签行（缩进+行尾两空格）、嵌套子列表、Sphinx 定义列表（term+缩进定义段）不合并；空行压缩条件 `skip >= 1`（误写 `>= 2` 会删光段落间空行） |
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
- **脚本只做机械操作，AI 助手审核全部**——脚本负责 `\_` → `_`、`\*` → `*`、`$$` 独占一行等机械修改。但这些修改可能出错（修漏、修错、修坏）——AI 助手必须通读全文，逐一验证每个公式是否渲染正确，包括脚本改过的和没改过的。不以「脚本已处理过」为由跳过，质量优先，不省 token
