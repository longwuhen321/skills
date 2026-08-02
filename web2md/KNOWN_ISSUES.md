# KNOWN_ISSUES — 已知问题与修复记录

> 排查需修改 `scripts/*.py` 的问题时读取本文件。
> 修复完成后按下方模板追加新条目（正序，新条目放最后），不删除旧条目。

条目模板：

```markdown
## [YYYY-MM-DD] 问题简述
- **现象**：...
- **根因**：...
- **修复**：`scripts/xxx.py` 何处、怎么改
- **排查方法**：下次如何快速定位/验证
```

---

## [2026-08-01] fix_escapes 全局兜底会替换散文中的合法字面转义

- **现象**：阶段 A 运行后，散文中表示字面量的 `\_` / `\*`（如 `foo\_bar` 想显示为 `foo_bar`）被替换成 `_` / `*`，可能意外变成强调或下划线语法。
- **根因**：`fix_escapes.py` 的 `fix_outside_code` 在完成公式块修复后，对**代码外全部文本**做全局 `\_`→`_`、`\*`→`*` 兜底——它分不清"公式内的转义"与"散文中刻意写的字面转义"（Markdown 里 `\_` 本来就是字面下划线的写法）。
- **修复**：保留兜底逻辑（上游 Codex 版同款行为，公式修复收益大于散文误改风险）；已在 SKILL.md 阶段 A 增加提示："代码外全局兜底也会把散文中合法表示字面量的 `\_` / `\*` 一并替换，复核时留意这类非公式转义。"
- **排查方法**：交付的 .md 中原本显示字面下划线/星号的散文被改成强调语法时，即为此类；在阶段 C 通读复核时留意。

## [2026-08-01] 抓取/转换失败无调试快照（已修复）

- **现象**：页面抓取成功但转换/下载/写出阶段抛异常时，进程只打印错误并退出，原始 HTML 不落盘——`final_verify` 报错后无法回溯转换前的页面结构，排查只能重新抓取。
- **根因**：`web2md.py` 的 `main()` 中 `fetch_page` 返回的原始 HTML 只用于转换，未在任何失败路径保存。
- **修复**：`scripts/web2md.py` 新增 `_save_debug_snapshot()`，`main()` 在转换/写出阶段捕获异常时，把原始 HTML 写入 `{项目根目录}/.web2md_tools/_archive/fetch_YYYYMMDD_HHMMSS.html`（成功路径不落盘）。
- **排查方法**：失败时看 `{项目根目录}/.web2md_tools/_archive/` 是否有 `fetch_*.html`；把快照喂给 `process_math_formulas` / `normalize_document_html` 可离线复现；selftest 有 `test_save_debug_snapshot` 覆盖。

## [2026-08-02] class="math" 纯字母公式被 \{}^_ 过滤漏转（已修复）

- **现象**：Sphinx 页面的纯字母内联公式（如 `\(L=W\)`、`\(AR\)`、`\(x, y, z\)`、`\(n=1.0\)`）在生成的 .md 中残留 `\(...\)` 语法，Typora 无法渲染。同页面还伴随三类 Sphinx 遗留：方程编号锚点混入公式块（`$$` 内 `(5)#\[...\]`）、裸 LaTeX 文本命令（`\textsl{...}`）、`aligned` 环境内的 `\label`。
- **根因**：`web2md.py` `process_math_formulas` 的 class="math" 分支用 `re.search(r'[\\{}^_]', text)` 决定是否转换——该检查在剥离 `\(` `\)` 定界符之后进行，纯字母公式正文不含 `\{}^_` 因而被漏掉。
- **修复**：`scripts/web2md.py` class="math" 分支引入 `delimited` 标志——凡被 `\(...\)` / `\[...\]` 定界符完整包裹的元素无条件转换（`if delimited or re.search(...)`），仅对无定界符包裹的文本保留原有过滤；新增回归测试 `test_math_plain_letter_delimited_formulas`（`scripts/tests/test_sphinx_conversion.py`）。
- **排查方法**：转换后 grep `\(` / `\)` 应无残留；同页面还需人工检查：`$$` 块内 `(N)#` 编号锚点、裸 `\textsl{...}` / 其他 LaTeX 命令、`aligned`/`split` 环境内 `\label`（MathJax 3 仅限编号环境，嵌套会报错导致公式渲染失败）。

## [2026-08-02] GitBook 导航 h1 与搜索模板混入正文（已修复）

- **现象**：GitBook 3.x 页面转换后两类结构残留：① 顶部导航栏 `.book-header` 的 `<h1><a href="..">标题</a></h1>` 被转成 `# [标题](站点根URL)`——与脚本 title H1、正文标题三重重复，且链接指向站点根而非精确章节；② 隐藏搜索面板 `#book-search-results` 的模板（`results matching "..."` / `No results matching "..."`）被转进 .md 尾部。
- **根因**：`normalize_document_html` 只针对 Sphinx（`is_sphinx_document`）做标题/链接规范化，未识别 GitBook 的导航栏与搜索模板 DOM。
- **修复**：`scripts/web2md.py` 新增 `is_gitbook_document()`（`meta[generator]` 含 GitBook 或存在 `#book-search-results`）与 `remove_gitbook_chrome()`，在 `normalize_document_html` 中、`normalize_document_links` **之前**调用——先删 `.book-header` 与 `#book-search-results` 内的 `.has-results` / `.no-results` 模板 div，避免其 `<a href="..">` 被绝对化后残留。**关键陷阱**：GitBook 3.x 的正文容器 `.search-noresults` 嵌套在 `#book-search-results` 内部，只能删模板 div，绝不能整体删除容器（否则正文丢失）；模板 class 是 `no-results`（带 s）。新增回归测试 `test_gitbook_chrome_removed`（`scripts/tests/test_sphinx_conversion.py`）。
- **排查方法**：GitBook 页面转换后 grep `results matching` / `No results`（搜索模板）与 `# [标题](站点根/)`（导航 h1）；若正文整体消失，说明 `remove_gitbook_chrome` 误删了 `#book-search-results` 容器——检查选择器是否只命中 `.has-results` / `.no-results`。

## [2026-08-02] collect_children 把单页文档章节锚点误当子页面（已修复）

- **现象**：NuttX 等单页文档（侧边栏子项全部是 `当前页.html#xxx` 章节锚点）时，collect_children 把数十个锚点当子页面，逐个重新抓取同一页面并覆盖写入同一文件，最终只剩最后一次内容；子页面收集产物无效且耗时。
- **根因**：`_norm_nav_url` 不去锚点；子链接过滤只用 `href.startswith('#')` 拦相对锚点，`commands.html#xxx` 这类「完整 URL + 锚点」未被拦截。
- **修复**：`scripts/web2md.py` 新增 `_strip_fragment()`（urlsplit 去 fragment）；`collect_children` 中 current_a 定位与子链接过滤均改为「去 fragment 后的规范化 URL 与当前页面比较」，同页链接一律跳过；current 链接带锚点也能正常定位。新增回归测试 `test_collect_children_ignores_same_page_anchors` / `test_collect_children_current_link_with_anchor`。
- **排查方法**：转换日志出现「发现 N 个导航子页面」且子页面标题与父页相同、产物相互覆盖时，即为此类；用上述测试或核对 nav 子链接是否全部指向当前页锚点。

## [2026-08-02] extract_title 残留 Sphinx 锚点图标 U+F0C1（已修复）

- **现象**：文件夹名/文件名/md 首行标题带 `Commands`（Sphinx 锚点图标，U+F0C1），正文标题已被 normalize 清理但提取标题未覆盖。
- **根因**：`_INVISIBLE_CHARS` 正则缺 `\uf0c1`，只覆盖零宽/NBSP/BOM 等。
- **修复**：`scripts/web2md.py` `_INVISIBLE_CHARS` 追加 `\uf0c1`。新增回归测试 `test_extract_title_strips_sphinx_anchor_icon`（覆盖 h1 与 `<title>` 两条路径）。
- **排查方法**：转换后 grep `` 应无残留（含文件夹名）；若只有首行标题残留即为此类。

## [2026-08-02] collect_children 同页锚点变体仍被当子页面重复抓取（已修复）

- **现象**：多页文档中某页面在导航里自带章节锚点链接（如 `customizing.html#nsh-commands`）时，该锚点被收集为子/孙页面；递归抓取时与目标页面（customizing.html）同 URL、同标题，写入同一文件夹互相覆盖——内容无损但浪费请求、子页面收集数虚高。
- **根因**：`_strip_fragment` 过滤只与**根父页（base_url）** 比较；锚点变体去 fragment 后等于**另一个子页面**（嵌套为孙级，或平铺为兄弟子项）而非根页，绕过了过滤。
- **修复**：`scripts/web2md.py` `collect_children` 两层防护：① 收集循环维护 `accepted_stripped`（已接受链接去 fragment 后的 URL），任何链接与已接受页面同页即跳过——覆盖平铺兄弟与嵌套孙级两种形态；② 孙页面挂载循环再判「孙页面与直接父页面（u1）同页」跳过。新增回归测试 `test_collect_children_flat_anchor_sibling_skipped` / `test_collect_children_grandchild_anchor_to_parent_skipped`。
- **排查方法**：子页面收集日志出现「子页面标题与其他页面相同、产物互相覆盖」且非单页文档时，检查导航中是否有 `页.html#xxx` 形式的锚点链接（平铺或嵌套）；与单页文档过滤（`test_collect_children_ignores_same_page_anchors`）为同族场景。
