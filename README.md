# AI Agent Skills

本仓库收录了一套面向 AI 助手（Claude Code、Reasonix 等）的实用 skills，每个 skill 封装了一个完整的自动化工作流。

---

## 目录

| Skill | 描述 |
|-------|------|
| [md2zh](#md2zh) | 将英文 Markdown 翻译为中文，保留格式与技术准确性 |
| [web2md](#web2md) | 抓取网页内容，输出 Typora 兼容的 Markdown 文件 |
| [confluence-tools](#confluence-tools) | Confluence 工具集：Markdown 导入页面、数学公式升级 |

---

## md2zh

**英文 Markdown → 中文 Markdown，字节级保护 + 确定性校验。**

### 核心能力

- **分块编排翻译**：pipeline 把长文档分为约 10–20 个 heading-aware 块，AI 助手逐块翻译，字节级 `PROTECT` 标记保护代码/公式/链接/标识符
- **确定性渲染**：merge → render → verify 全流程校验，源文件 source hash 比对，译文与源字节级一致
- **失败隔离**：单块失败只改该块（最多 2 轮修正），已接受块保留，支持断点续传
- **模糊内容决策**：user / ai 两种决策者模式，全部决策记录到 `decision_logs/*.jsonl`
- **术语一致性**：任务级术语表跨块保留；树形翻译时树级共享术语表（跨子页面一致）
- **树形目录批量翻译**：指定目录且树内可翻译 `.md` ≥ 2 个（多页面收集结构，忽略 `.assets/`）时按树逐文件翻译，镜像输出 `<根名>_zh/`，可直接对接 confluence-tools `--dir` 导入（流水线：web2md 抓取 → md2zh 翻译 → Confluence 页面树）；目录内仅 1 个 `.md`（如抓取单页的"标题文件夹 + 同名 .md + .assets"）按**单文件流程**输出 `<stem>_zh.md` 平级文件

### 使用方式

```
/md2zh
```

首次运行走配置向导（skill 级 `scripts/config.py` 的 Python 路径 + 项目级 `.md2zh_tools/config.json` 的决策者/解释器模式）。之后指定要翻译的 `.md` 文件路径，输出 `<stem>_zh.md` 放在源文件旁。

### 技术参考

翻译技术术语时优先参考全国科学技术名词审定委员会 (cnterm.cn) 的审定名词与相关国标（GB/T 2900.56-2008 等），具体规则见 `md2zh/references/translation-rules.md`。

### 质量保障

- `scripts/tests/selftest.py`：离线黑盒测试（配置写入、分块保护、端到端 roundtrip、契约违规拒绝），修改脚本后必须全绿
- 决策日志、任务产物清理（`cleanup-run`）、脚本完整性检查 + git 恢复（先确认再恢复）

---

## web2md

**网页 → Typora 兼容的 Markdown，图片本地化，公式 LaTeX 化。**

### 核心能力

- 抓取任意网页，提取正文并转为 Markdown（`markdownify` + `BeautifulSoup`）
- 图片自动下载到本地 `.assets` 文件夹，支持 Wikimedia 限流退避
- 数学公式五路识别：Wikipedia `.mwe-math-element`、MathJax `<script>`、`<math>` MathML、Sphinx `class="math"`、MathJax SVG `<mjx-container>`
- **三阶段公式审核流水线**：脚本机械修复 + AI 助手上下文判断，确保每个公式正确渲染
- **导航子页面批量获取**：规则解析侧边栏导航（Sphinx li/ul、VitePress div.item/section）批量抓取子/孙页面并按标题文件夹嵌套落盘；规则失效时由 AI 助手判断兜底（`--children-from` 清单）

### 使用方式

```
/web2md <URL>
```

首次使用时会引导配置 Python 环境（自动搜索或手动指定），同时写入 Bash allow 规则避免后续重复确认。之后记住路径不再询问。

导航子页面批量获取（可选）：`config.py` 的 `collect_children` 开关或 CLI `--children` 按规则解析侧边栏导航抓取子/孙页面；`--children-from <file>` 则按 AI 助手写的清单抓取（规则解析对新站点主题失效时的兜底通道）。

### 输出结构

```
./{页面标题}/
├── {页面标题}.md
├── {页面标题}.assets/
│   ├── image1.png
│   └── ...
├── {子页面标题}/              ← 子页面（--children / --children-from 时）
│   ├── {子页面标题}.md + .assets/
│   └── {孙页面标题}/          ← 孙页面（深度最多 2 级）
└── ...
```

### 公式审核流水线（第四步）

脚本 `process_math_formulas` 只能做标签级转换（识别 Wikipedia `.mwe-math-element`、MathJax `<script>`、`<math>`、`class="math"`、`<mjx-container>` 五种标签）。生成 `.md` 后，完成以下阶段审核：

| 阶段 | 工具 | 做什么 | 谁判断 |
|------|------|--------|--------|
| **A** | `fix_escapes.py` | `$...$` / `$$...$$` 内 `\_`→`_`、`\*`→`*`（不碰 `\{` `\}`，掩码忽略代码） | 脚本机械执行 |
| **B** | `list_display_fixes.py --apply` | 自动升级确定性候选（`\begin{aligned/cases/array/bmatrix}` 或 `\\` 行断）`$`→`$$`，正文逐字节不变；其余列出 | 脚本自动 + **AI 助手**复核其余 |
| **C** | `find_all_missed.py`（辅助扫描）+ **AI 助手通读循环** | Wikipedia 伪公式识别：`**i**`、`*x*2`、`*a*1 + *b*2**i**` 等 | **AI 助手**读全文 → 写清单 → Edit → 复核，循环至干净 |
| **D** | 通读时同步检查 | Markdown 结构：表格分隔行/列数、图片引用存在性、围栏闭合、Sphinx 标题链接、占位符 code 化等 | **AI 助手**逐条判断 |

#### 阶段 C 伪公式分类（AI 助手逐条判断）

脚本无法区分表格粗体和数学符号——由 AI 助手通读全文，按分类索引识别（**完整转换规则见 `web2md/references/formula-conversion-rules.md`**，涉及 LaTeX 语法转换时读取对应章节）：

- **斜体+数字** → 下标/上标（`*a*1` → `$a_{1}$`）、**斜体+运算符** → 行内公式（`*x* = *y*` → `$x=y$`）
- **粗体+数字/运算符** → 向量公式（`**i** ⋅ **j** = **k**`）、**粗体数域记号**（`**R**` → `$\mathbf{R}$`）
- **Unicode 运算符/不等号/集合/箭头**（±, ⋅, ≤, ∈, →, …）→ LaTeX、**混合粗体+斜体**（四元数）、**函数+斜体参数**（`cos(*φ*)`）

> 判断边界：表格 `| **i** | **j** | **k** |` 保留 bold；维度 `2 × 2` 保留 Unicode；分类索引与全部规则表见参考文件 §1–§4。

#### 收尾验证

`final_verify.py` 最终确认：`\_` 清零、`\*` 清零、`\\` 行断完整、`\left\{` 未破坏、`$$` 独占一行且成对、围栏闭合、LaTeX 花括号平衡、表格结构有效（分隔行 / 列数一致）、本地图片引用存在、正文无未保护占位符、LLM 清单全部打勾（先掩码代码再检查）。

### 项目文件结构（脚本单份化）

所有脚本固定存放在 skill 目录 `web2md/scripts/`，**不复制进项目**；项目只保留工作数据：

```
web2md/                            # skill 目录（本仓库）
├── SKILL.md
├── KNOWN_ISSUES.md                # 已知问题与修复记录（排查时读）
├── OPTIMIZATION_SUMMARY.md        # 优化交接摘要（优化前读）
├── config.example.py              # 配置模板（占位符）
├── references/
│   └── formula-conversion-rules.md  # 公式转换规则（阶段 C 按需读取）
└── scripts/
    ├── config.py                  # 真实配置（gitignore 排除）：python_path、timeout、collect_children
    ├── web2md.py                  # 主抓取脚本（DOM 规范化、导航收集、--children-from）
    ├── markdown_code.py           # 代码掩码工具（各脚本共用）
    ├── fix_escapes.py             # 阶段 A：\_ \* 修复
    ├── list_display_fixes.py      # 阶段 B：$→$$ 自动升级 + 候选列表
    ├── find_all_missed.py         # 阶段 C：伪公式扫描辅助
    ├── final_verify.py            # 收尾验证
    └── tests/                     # 本地测试（git 不追踪）
        ├── selftest.py            # 测试入口（41 用例）
        ├── test_formula_integrity.py
        └── test_sphinx_conversion.py

<项目根目录>/
└── .web2md_tools/
    ├── intermediate/              # AI 助手清单 fix_list_roundN.md、children_list.md（--children-from 读取）
    └── _archive/                  # 调试脚本等一次性文件
```

### 设计原则

- **AI 助手做判断，脚本做执行**——`**i**` → `$\mathbf{i}$` 这类转换，脚本只能做 AI 助手手写的精确 `str.replace`，不能自动判断上下文
- **导航收集双通道**——规则解析（`collect_children`）覆盖已知导航主题，新主题漏识别或规则异常时，AI 助手 web_fetch 页面读导航、写清单（`--children-from`）接管子/孙页面判断，脚本退化为按清单抓取
- **脚本单份化**——可复用脚本只存在 `scripts/`，不复制进项目，避免版本漂移；各脚本通过 `markdown_code.py` 掩码忽略代码内容
- **配置用 config.py**——仿 confluence-tools：`config.example.py` 模板 → `scripts/config.py` 真实值（gitignore 排除），`load_config()` 读取
- **不碰 `\{` `\}`**——它们是 `\left\{` `\right\}` 的合法 LaTeX 组件
- **Wikipedia 特化清洗**仅对 `wikipedia.org` / `wikimedia.org` 生效，`is_wiki` 兜底
- **质量保障**——修改脚本后必须跑 `scripts/tests/selftest.py` 全绿（本地测试，不随仓库分发）

---

## confluence-tools

**Confluence 一站式工具集：Markdown 导入 + 数学公式升级。**

### 核心能力

- **Markdown 导入** — `.md` → Confluence 页面：代码块、表格、图片附件（上传失败 / 本地缺失 / base64 内嵌均有明确报告）、`==高亮==`、数学公式
- **数学公式升级** — 已有页面的 `$...$` / `$$...$$` / `\`\`\`latex` 升级为原生 `mathinline` / `mathblock` 宏，支持单页、递归子页、整空间批量
- **公式对齐可配置** — 导入与升级统一支持左对齐 / 居中（原生 `mathblock + alignment` 参数，已在 Confluence 9.2.1 实测），`--align` 可临时覆盖
- **自动查重更新** — 空间内标题内存匹配（大小写不敏感），同标题自动更新为新版本，409 版本冲突自动重试
- **文件夹树批量导入** — `--dir` 模式把 web2md/md2zh 输出的目录结构整棵导入，保留层级（子文件夹 = 子页面，任意深度）；命中已有页面按 `fix_hierarchy` 策略处理（confirm 预览确认 / auto 移动 / off 不移动）
- **自动目录宏** — 页面子标题（H2~H6）达阈值时自动在正文顶部插入 Confluence 目录宏（`toc_enabled` / `toc_min_headings` 可配）
- **容错机制** — 429 限流指数退避重试（尊重 `Retry-After`）、批量遇错继续 + 末尾失败汇总（`--stop-on-error` 可停）、全请求超时保护
- **首次配置向导** — 必需项（地址 / Token / 空间）缺失即中断、禁止预填历史配置、Python 路径先问后找
- **凭据安全** — Token 只存 `config.py`（gitignore 排除），支持 `CONFLUENCE_TOKEN` 环境变量覆盖

### 使用方式

```
/confluence-tools
```

首次运行走配置向导，之后选择：导入 Markdown、批量导入文件夹树（`--dir`，需开启 tree_import）或升级数学公式。两个脚本也支持独立命令行运行。

### 技术要点

- Confluence 9.x REST API，Bearer Token (PAT) 认证
- 公式宏统一由 `common.build_block_template` 生成（left = `mathblock + alignment=left`，center = 默认居中）
- 导入流水线：protect code/math → markdown2 → restore → convert 宏 → 上传附件 → 更新
- 公共层 `common.py` 集中处理：配置加载、HTTP 重试、分页收集、宏模板

### 质量保障

- `scripts/selftest.py`：58 个离线用例（转换管线、版本号流程、限流重试、对齐、base64 图片、树导入、toc 等），mock 配置与网络，**修改脚本后必须全绿**
- `KNOWN_ISSUES.md`：已知问题与修复记录（现象 / 根因 / 修复 / 排查方法），排查前先读
- 真实环境验证产物（测试页 / 临时脚本）用后即清

### 文件结构

```
confluence-tools/
├── SKILL.md
├── KNOWN_ISSUES.md           # 已知问题与修复记录
├── OPTIMIZATION_SUMMARY.md   # 优化交接总结（优化前读、优化后追加）
├── config.example.py         # 配置模板（占位符）
├── scripts/
│   ├── config.py             # 真实配置（gitignore 排除）
│   ├── common.py             # 公共：配置加载、HTTP 重试、页面收集、宏模板
│   ├── debug_utils.py        # 调试日志清理
│   ├── md_import.py          # Markdown → Confluence
│   ├── math_upgrade.py       # 数学公式升级
│   └── selftest.py           # 离线自测（58 用例）
└── debug/                    # 导入/升级调试快照（自动清理）
```

### 自进化机制

每次执行遇到非一次性错误（脚本 bug、渲染异常、边界情况），修复并通过验证后询问是否固化：

- **修改脚本** — 更新 `scripts/*.py`
- **记录到 KNOWN_ISSUES.md** — 追加现象 / 根因 / 修复 / 排查方法
- **更新 SKILL.md** — 补充注意事项或调整流程

---

## 安装

将本仓库 clone 到 `~/.claude/skills/` 目录，AI 助手（Claude Code / Reasonix 等）会自动发现并加载其中的 skills：

```bash
git clone <repo-url> ~/.claude/skills/
```

---

## 许可

MIT
