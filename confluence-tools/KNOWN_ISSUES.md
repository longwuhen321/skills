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
