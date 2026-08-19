---
name: web2md
description: 将网页抓取为 Typora 兼容 Markdown，并本地化图片、转换 LaTeX 公式；仅在用户显式调用 $web2md 时使用
---

# web2md — 网页转 Markdown

输入 URL，生成 Typora 可打开的 `.md`；图片保存到同名 `.assets` 目录，数学公式转换为 LaTeX。

## 触发与范围

- **仅显式调用**：只有用户使用 `$web2md <URL>` 时执行；普通 URL 不触发。
- 默认只抓当前页；子/孙页面、段落合并均需配置或 CLI 明确启用。
- 正常转换不得修改共享 skill；只有用户明确要求维护时才能改动其文件。

## 强制协议与直接路由

先判断本次命中的情形，直接读取下表文件；不要通过一个参考文件再寻找另一个必读文件。
开始实质操作前，简短说明已命中的路由及读取结果。

| 情形 | 继续前必须读取 |
|---|---|
| 首次配置、配置缺失/损坏、解释器无效、同步失败、改配置键 | [configuration-guide.md](references/configuration-guide.md)（完整） |
| `collect_children`、`--children`、`--children-from`、`--rendered-html` 或导航异常 | [children-collection-workflow.md](references/children-collection-workflow.md)（完整） |
| 裸 TeX、跨节点 `REVIEW`、段落切碎 | [custom-site-rules.md](references/custom-site-rules.md)（完整） |
| 阶段 C 命中 A–I、S、F2 公式候选 | [formula-conversion-rules.md](references/formula-conversion-rules.md)（按分类索引） |
| 修改任何 skill 文件 | [../SKILL_MODIFICATION_STANDARD.md](../SKILL_MODIFICATION_STANDARD.md) 与 [maintenance-rules.md](references/maintenance-rules.md)（完整） |
| 修改或新增 `scripts/*.py` | 上一行两份文件及 [script-development-rules.md](references/script-development-rules.md)（完整） |
| 排查或修复 bug | 维护路由及 [KNOWN_ISSUES.md](KNOWN_ISSUES.md) |
| 优化、重构或扩展 | 维护路由及 [OPTIMIZATION_SUMMARY.md](OPTIMIZATION_SUMMARY.md) |

未命中的参考不预读。公式参考是索引式例外，只读取命中章节；其余标注“完整”的文件必须全文读取。

## 1. 准备环境

读取 `scripts/config.py` 中的 `python_path`，用它先执行配置同步门禁：

```powershell
& "<python路径>" "<skill-directory>/scripts/check_config_sync.py"
```

- 退出码 `0`：继续。
- 退出码 `1/2`、文件缺失、无法安全解析或解释器无效：立即停止抓取，完整读取配置指南后修复并重跑。
- `scripts/config.py` 是唯一 Python 路径来源；不要用环境变量维护第二份路径。

确认共享脚本完整：

| 阶段 | 必需文件 |
|---|---|
| 配置 | `config_literal.py`、`check_config_sync.py` |
| 抓取 | `web2md.py`、`nav_children.py`、`markdown_code.py` |
| 审核 | `fix_escapes.py`、`list_display_fixes.py`、`find_all_missed.py`、`final_verify.py` |
| 可选与发布 | `merge_paragraphs.py`、`package_check.py` |

缺失任何一项都停止并报告；共享脚本只保留在 `<skill-directory>/scripts/`，不要复制到项目目录。

## 2. 抓取页面

基础命令：

```powershell
& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}"
```

请求与图片超时读取配置；显式代理配置优先，否则自动使用 `HTTP_PROXY` / `HTTPS_PROXY`。
输出名取页面标题并安全规范化；不同来源发生清洗冲突时追加稳定 URL 哈希，禁止覆盖既有不同来源目录。

单页输出结构：

```text
{项目根目录}/<页面标题>/
├── <页面标题>.md
└── <页面标题>.assets/
```

只下载 Markdown 实际引用的图片；每个本地图片引用必须解析到该页面目录中的真实文件。

若启用任何子页面参数，先完整读取子页面工作流。收集范围只包括严格导航子页面及其
直接子页面，最大两级；**无法核实导航不等于确认没有子页面**，证据不足时必须询问用户。

抓取时允许在公式提取前做窄范围 DOM 清理，包括链接绝对化、Sphinx 标题锚点清理、
重复 H1 处理及散文占位符 code 化；必须跳过 math、code、pre、script、style 等保护子树。
绝不允许为了清理标题、链接或占位符而改写公式或代码载荷。

## 3. 公式与 Markdown 审核

脚本可识别 Wikipedia、MathJax、MathML、`class="math"`、MathJax SVG 及可靠的裸
`\(...\)` / `\[...\]`。跨块、保护子树、格式标签、非正文节点或歧义候选保持原文并报 `REVIEW`；不得猜测转换。

脚本报告裸 TeX、`REVIEW` 或段落切碎时，先完整读取自定义站点规则，再进入下列循环。

### A. 修复公式内转义

```powershell
& "<python路径>" "<skill-directory>/scripts/fix_escapes.py" "{md文件路径}"
```

只在已配对公式内把 `\_` / `\*` 修成 `_` / `*`；散文、代码及未配对 `$` 不动。
不要修改 `\{` / `\}`，它们可能属于合法的 `\left\{` / `\right\}`。

### B. 显示公式候选

```powershell
& "<python路径>" "<skill-directory>/scripts/list_display_fixes.py" "{md文件路径}" --apply
```

- `aligned` / `cases` / `array` / `bmatrix` 或多行公式可机械升级为 `$$`；只改定界符。
- 长公式只列出复核；普通单行公式保持 `$`。
- 表格内公式保持 `$`，多行内容由 AI 按语义重建为单物理行 `aligned`，不得用 `$$` 撕裂表格。
- 自动改过与未改过的候选都必须在通读中复核。

### C. AI 全文通读循环

1. 通读完整 `.md`，识别遗漏伪公式、错误公式、表格与结构问题。
2. 把每个候选写入
   `<skill-directory>/logs/intermediate/<项目根名>/fix_list_roundN.md`，格式为
   `行号 + 原文片段 → 判决/建议修复`。
3. **决定不改的候选也必须记录判决与理由**。
4. 逐条用 `apply_patch` 修改并勾选；重读全文，有遗漏则进入下一轮，直到清单全部关闭。
5. 可用 `find_all_missed.py` 辅助扫描，但扫描结果不能代替 AI 判断。

命中下列类型时，按索引读取公式参考的对应章节：

| 类别 | 候选 | 章节 |
|---|---|---|
| A–H | 斜体/粗体、上下标、函数、混合数学表达式 | §1.1–§1.8 |
| I | Unicode 数域、单位、运算符、关系、集合、箭头 | §2.1–§2.9 |
| S | Sphinx 裸命令、锚点或 `aligned` 遗留 | §3 |
| F2 | `$x$-$y'$` 等碎片化行内公式序列 | §4 |

判断必须由 AI 助手完成。脚本只做机械操作；不得用正则自动区分数学粗体与排版粗体。

### D. 同步审核 Markdown 结构

- 表格必须有合法分隔行、列数一致，块后留空行；不得发明空表头或全局改写引用块。
- 区分布局表格与语义表格；数学元组、序列或等式被拆进多个单元格时按语义人工重建。
- 每个本地图片目标必须存在；不保留失效的本地引用。
- 围栏代码块必须闭合；散文 `<占位符>` 应 code 化，代码与 LaTeX 内相似文本忽略。
- Sphinx 产物不得残留标题锚点图标、错误本地锚点或未转换公式；GitBook 产物不得残留搜索模板与导航栏标题。
- Command Syntax 仅在页面语义明确时转代码；语义不明时记录候选，不猜测。

### E. 收尾门禁

先确认阶段 C/D 的人工清单全部关闭，再执行：

```powershell
& "<python路径>" "<skill-directory>/scripts/final_verify.py" "{md文件路径}"
```

`final_verify.py` 检查公式定界符与花括号、`aligned`、代码围栏、占位符、Sphinx
残留、相对链接、表格及本地图片。**FAIL 必须为零，REVIEW 也必须为零，退出码必须为 0**；
否则逐项复核、修复并重跑。验证器不能代替全文通读和人工清单。

## 4. 可选段落合并与交付

脚本报告段落切碎或用户明确偏好时，可在抓取时加 `--merge-paragraphs`，或执行：

```powershell
& "<python路径>" "<skill-directory>/scripts/merge_paragraphs.py" "{md文件路径}"
```

合并器只合并普通段落硬换行，保护代码围栏、显示公式、公式标签、嵌套列表与定义列表。
合并后必须重新运行 `final_verify.py`，仍需无 FAIL、无 REVIEW。

工作清单写入 `<skill-directory>/logs/intermediate/<项目根名>/`；一次性诊断文件写入
`logs/_archive/<项目根名>/`。轮次清单只保留最近 5 轮，固定名 `children_list.md`
可覆盖；归档最多保留最近 20 项。真实验证快照用后清理，不得混入项目产物或发布包。

交付时列出 Markdown、`.assets` 及未解决事项的完整路径；告知可用 Typora 打开。
若发现现有说明未覆盖的新失败模式，报告现象、可能原因、人工方案，并说明是否建议更新 skill；
没有用户明确要求时只提出建议，不直接修改共享 skill。

## 全局红线

- 配置同步失败必须停止；不得静默依赖默认值。
- 无法核实子页面不等于没有子页面。
- 公式与代码保护载荷不得因清理、合并或修复而被意外改写。
- 脚本只执行机械转换，AI 助手审核全部结果。
- 每个候选都要有判决，包括决定不修改的项。
- `final_verify.py` 必须达到零 FAIL、零 REVIEW。
- 输出名保持稳定，禁止覆盖不同来源的既有产物。
- 未经用户明确要求，不得修改共享 skill。
- 修改 `scripts/*.py` 后，必须运行完整 `scripts/test/selftest.py` 并全部通过。

## 维护收尾

维护任务遵循直接路由与维护规则。bug 记录到 `KNOWN_ISSUES.md`；优化、重构、扩展记录到
`OPTIMIZATION_SUMMARY.md`。写记录前读取文档头部约定，并用系统当前日期插入最新条目。

任何 skill 文件变更后都要完整运行自测、配置同步、skill 校验、文档路由测试、
`git diff --check`、LF 检查和隔离暂存目录的 `package_check.py`。只有全部通过才算完成。
