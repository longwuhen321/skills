---
name: web2md
description: 抓取网页内容，生成 Typora 兼容的 Markdown 文件（含本地图片、LaTeX 公式）。仅显式调用 /web2md 或 @web2md 时才触发，不因普通 URL 出现而触发
---

# web2md — 网页转 Markdown

输入 URL，自动生成 Typora 可打开的 `.md` 文件，图片下载到本地 `.assets` 文件夹，数学公式转为 LaTeX。

## 触发

**仅显式调用**。用户使用 `/web2md <URL>` 或 `@web2md <URL>` 时才执行。

用户随口发 URL 但没有用 `/web2md` 前缀的，不触发。

## 执行流程

### 第一步：Python 环境准备（config.py 记录）

**只执行一次**。后续直接使用 `scripts/config.py` 中记录的 `python_path`。

读取 `<skill-directory>/scripts/config.py`（本 skill 的共享配置）：

- `config.py` 存在且 `python_path` 有效 → 直接使用，不再询问。
- `config.py` 缺失 / 损坏 / 路径失效 → 走配置向导：
  1. **先问用户**：「有想用的 Python 环境路径吗？直接回车我自动搜索。」
  2. 用户指定 → 验证可用性 → 采用；用户跳过 → 自动扫描：`where python` / `where python3`、`~/python_env/*/python`、`E:/work/python_env/*/python`、系统 PATH
  3. 找到后列给用户确认。优先选已有 `requests`/`bs4`/`markdownify`/`lxml` 的
  4. 依赖缺失则：
     ```powershell
     & "<python路径>" -m pip install requests beautifulsoup4 markdownify lxml -q
     ```
     （不要因为缺依赖就换环境，安装失败或环境不可用才重新选择）
  5. 确认后把 `python_path` 写入 `scripts/config.py`（参考 `config.example.py` 模板，该文件已被 gitignore 排除）
  6. **python_path 是必需项**：用户不提供且自动扫描无结果 → **中断任务**（无 Python 无法执行脚本），不创建半成品 config.py；`timeout` 为选填，缺省用默认值 30
  7. **收集导航子页面** → `web2md_config.collect_children`（选填，默认 `false`）
     - `true`：抓取页面时解析侧边栏导航，**批量抓取当前页面在导航树下的直接子页面（含孙页面）**，按页面标题文件夹嵌套落盘
     - `false`（默认）：只抓当前页面，行为不变
     - 可被 CLI 参数 `--children` / `--no-children` 临时覆盖；`--children-from <file>` 以 AI 助手清单为准（见第三步）

> `scripts/config.py` 是 Python 路径的唯一配置源（全 skill 共享一份）。如需为脚本执行配置免确认白名单，请按当前 AI 助手平台的方式设置；**不要**通过平台环境变量存储 Python 路径——避免与 config.py 形成双配置源导致漂移。

### 第二步：确认共享脚本存在

本 skill 的所有脚本固定存放在 `<skill-directory>/scripts/`，**不复制到各项目**。执行前确认以下文件都在，缺失则停下报告缺失项：

| 文件 | 用途 | 阶段 |
|------|------|------|
| `web2md.py` | 主抓取脚本 | 第三步 |
| `markdown_code.py` | 代码 span/fence 掩码工具（被其他脚本共用） | 各阶段 |
| `fix_escapes.py` | `\_` `\*` → `_` `*`（忽略代码内） | 第四步-A |
| `list_display_fixes.py` | 自动升级确定性 `$`→`$$` 候选 + 列出其余候选（`--apply`） | 第四步-B |
| `find_all_missed.py` | 扫描伪公式模式（忽略代码内） | 第四步-C 辅助 |
| `merge_paragraphs.py` | 合并段落内的源码硬换行（通用能力，所有站点适用） | 第五步（可选） |
| `final_verify.py` | 公式 / 表格 / 图片 / 占位符全量验证 | 收尾 |

> **共享脚本规则**：以后新增的可复用脚本一律放 `<skill-directory>/scripts/`，不要往项目里复制。

### 第三步：执行抓取

```powershell
& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}"
```

`HTTP_PROXY` / `HTTPS_PROXY` 环境变量存在时自动使用。页面抓取与图片下载的超时均从 `scripts/config.py` 的 `timeout` 读取（默认 30 秒）。

**导航子页面收集**（`config.py` 的 `collect_children=true` 或 CLI `--children` 时按规则解析侧边栏导航；也可用 CLI `--children-from <file>` 按 AI 助手清单抓取，见下文「AI 助手判断通道」）：

1. 抓取父页面后，解析侧边栏导航（toctree），定位当前页面节点
2. 收集其**严格导航子页面**（直接子级），若子页面在导航中还有子页面（孙页面）也一并收集（深度最多 2 级）；子页面正文里引用的其他页面不处理
   - 单页文档（导航子项全部指向当前页面自身的锚点，如 `commands.html#xxx`）→ 自动视为无子页面，不重复抓取（`_strip_fragment` 去 fragment 后与当前页 URL 比较）；孙级锚点同理——孙页面指向其**直接父页面**自身的锚点（如 `customizing.html#xxx`）也跳过，不当作独立孙页面
3. 逐个抓取子/孙页面 → 转 Markdown → **按页面标题文件夹嵌套落盘**在父页面目录下：

```
{输出根}/父页面标题/
├── 父页面标题.md + .assets/
├── 子页面标题/          ← 子页面 1
│   ├── 子页面标题.md + .assets/
│   └── 孙页面标题/      ← 子页面 1 的孙页面
└── 子页面标题/          ← 子页面 2
```

> 文件夹名默认取页面标题（经文件系统命名规范化，非法字符如 `/` 替换）；AI 助手可酌情调整，但必须符合文件夹命名规范。

#### AI 助手判断通道（`--children-from <file>`）

规则解析（`collect_children`）只覆盖已知导航结构（Sphinx li/ul、VitePress div.item/section 等）。
遇到以下情况时，由 **AI 助手接管子/孙页面判断**（脚本退化为按清单抓取）：

1. 脚本输出"该页面无严格导航子页面"，但 AI 助手访问页面（web_fetch）时在侧边栏导航中
   明显看到子页面（新站点主题漏识别）
2. 规则收集的候选异常（数量过多、含外部站点/版本切换链接等，疑似整树误抓）

流程：

1. AI 助手 web_fetch 父页面 → 从页面导航文本识别子/孙页面（URL 核对：与父页面同域、
   同版本路径前缀；孙页面在导航中嵌套于子页面之下）
2. 写清单到 `{项目根目录}/.web2md_tools/intermediate/children_list.md`（格式见下）
3. 执行 `& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}" --children-from "{清单路径}"`
   → 脚本按清单逐个抓取子/孙页面落盘（文件夹名仍以页面实际标题为准）

清单格式（AI 助手生成，脚本只做机械解析；`--children-from` 优先于规则解析）：

```markdown
# 子页面清单 — 页面标题（`#` 开头为注释行，忽略）
- 子页面标题 | https://.../child.html
  - 孙页面标题 | https://.../grand.html    （2 空格缩进 = 孙页面，最多 2 级）
- 另一个子页面 | https://.../other.html | 备注（`|` 后第一段为 URL，再后的备注忽略）
```

- 列表标记 `-` / `*` 均可；URL 可用 `<>` 包裹；缩进超过 2 级、缺 URL、无父页面的孙页面行跳过并警告
- 标题仅用于展示，落盘文件夹名以页面实际标题为准（与规则路径行为一致）

`web2md.py` 在提取公式前会做**窄范围的 DOM 规范化**（`normalize_document_html`）：

- 非数学的相对链接改为绝对链接；Sphinx 片段链接转为源页面链接
- 移除 Sphinx 标题锚点符号（``），同时把标题文本链接到源章节；`extract_title` 提取的文件夹/文件名标题同样清除 U+F0C1 与零宽字符
- 把转义后的散文占位符（如 `&lt;path&gt;`）包成 `<code>`
- 该过程**必须跳过** Wikipedia `.mwe-math-element`、MathJax `<script type="math/tex...">`、`<math>`、`class="math"` 以及所有 `<code>` / `<pre>` / `<script>` / `<style>` 子树；`process_math_formulas` 只在这些规范化完成之后运行。**绝不允许**为做链接/标题/占位符清理而事后改写公式载荷。

### 第四步：审核数学公式

脚本 `process_math_formulas` 只识别五种标签转为 `$...$` / `$$...$$`：Wikipedia `.mwe-math-element`、MathJax `<script>`、`<math>`（MathML）、`class="math"`、MathJax SVG `<mjx-container>`（含 MathML 递归转换与函数名还原，如 `sin` → `\sin `）。另有 `convert_plain_tex_delimiters` 兜底转换非平台结构页面的裸 `\(...\)` / `\[...\]` 定界符。

**非平台结构页面（自定义站点）**：抓取输出报告命中（「检测到裸 TeX 定界符」/「跨节点疑似」/「段落切碎检测」）时，先读取 `references/custom-site-rules.md` 按章执行（特征清单、转换规则、处理流程；规则不常驻上下文，仅命中时读取）。

生成 .md 后，完成以下阶段审核：

#### 阶段 A：脚本自动修复（`fix_escapes.py`）

修复 markdownify 造成的 `\_` `\*` 错误转义（下标 `x_{k}` → `x\_{k}`、上标 `q^{*}` → `q^{\*}`）。

```powershell
& "<python路径>" "<skill-directory>/scripts/fix_escapes.py" "{md文件路径}"
```

脚本会先掩码 Markdown 代码（围栏 / 行内），**只修复代码外的公式与散文**。内部逻辑：`$$` 和 `$` 块内（限长 2000 字符防孤立 `$`）`\_` → `_`、`\*` → `*`，再对代码外文本全局兜底。

> **不在此阶段修 `\{` `\}`**——它们是 `\left\{` `\right\}` 的合法 LaTeX 组件。
>
> 注意：代码外全局兜底也会把散文中合法表示字面量的 `\_` / `\*` 一并替换，复核时留意这类非公式转义。

#### 阶段 B：`$` vs `$$` 自动升级 + 复核（`list_display_fixes.py` + AI 助手判断）

```powershell
& "<python路径>" "<skill-directory>/scripts/list_display_fixes.py" "{md文件路径}" --apply
```

脚本自动把**确定性候选**从 `$...$` 升级为 `$$...$$`：只改定界符，公式正文逐字节不变。其余候选列出供 AI 助手逐条判断：

| 条件 | 判决 |
|------|------|
| `\begin{aligned/cases/array/bmatrix}` | 自动 → `$$` |
| 含 `\\` 行断（多行公式） | 自动 → `$$` |
| 长度 > 200 字符 | 列出仅复核（不自动升级） |
| 其余单行公式 | 保持 `$`（Typora 行内公式可正常渲染；需要块级独占行时才考虑 `$$`） |

> 脚本会掩码代码，代码内的公式绝不处理。不带 `--apply` 时只列出候选不修改。自动转换项也仍是机械操作——阶段 C 通读时必须逐一验证其渲染正确（含改过的和没改过的）。

#### 阶段 C：AI 助手通读循环（伪公式识别）

Wikipedia 用 `<b>` `<i>` `<sup>` 渲染的简单公式，markdownify 转成了 `**i**` `*i*`。脚本无法判断——**由 AI 助手读 .md 全文**，根据上下文识别。

1. **通读** .md → 识别遗漏的伪公式（`**w***k*`、`*x*2`、`*a*1 + *b*2**i**` 等）
2. **写清单**到 `{项目根目录}/.web2md_tools/intermediate/fix_list_roundN.md`，格式：`行号 + 原文片段 → 建议修复`
3. **逐条 Edit**，修一条划一条
4. **重读复核**
5. 有遗漏 → 回到步骤 2，**直到干净**


**常见遗漏模式 → 见 `references/formula-conversion-rules.md`**：涉及 LaTeX 语法转换时，按下方分类索引读取对应章节（低频符号表不常驻上下文）。

| 类别 | 识别什么 | 触发条件 | 参考 |
|---|---|---|---|
| A | 斜体+数字 → 下标/上标 | `*a*1`、`*x*2` | §1.1 |
| B | 斜体+运算符 → 行内公式 | `*x* = *y*` | §1.2 |
| C | 粗体+数字/运算符 → 向量公式 | `**i**2`、`**i** ⋅ **j**` | §1.3 |
| D | 粗体字母作为数学符号 | `**R**`、集合、散文符号 | §1.4 |
| E | 函数+斜体参数 | `cos(*φ*)` | §1.5 |
| F | 混合粗体+斜体表达式 | 四元数 `*a*+*b***i**` | §1.6 |
| G | 斜体含特殊符号（上标星号） | `*pq*∗` | §1.7 |
| H | 数学符号/记法 | `*d*g(*p*,*q*)` | §1.8 |
| I | Unicode 符号（粗体数域 / `±` `∈` `→` `≤` `∞` 等） | 页面出现对应 Unicode 字符时 | §2.1–2.9 |
| S | Sphinx 页面遗留公式模式 | Sphinx 页面（`\(...\)` 来源） | §3 |
| F2 | 碎片化行内公式序列 | `$x$-$y'$-$z''$` 等相邻片段 | §4 |

**核心纪律（必须遵守，非规则表）**：
- 判断必须由 AI 助手做；脚本只做精确 `str.replace`，绝不用正则/自动判断区分粗体 vs 公式
- 表格粗体 `| **i** |` 保留；维度 `2 × 2`、表格箭头保留 Unicode
- 每个候选与判断结论（含**决定不改**的）写进轮次清单
- 脚本只做机械操作，AI 助手审核全部（含脚本改过的和没改过的）——不以「脚本已处理过」为由跳过
- 辅助扫描（可选）：`& "<python路径>" "<skill-directory>/scripts/find_all_missed.py" "{md文件路径}"`

#### 阶段 D：Markdown 结构审核（与公式审核同步）

在通读全文时，除公式外一并检查 Markdown 结构：

1. 每个表格有合法的分隔行、列数一致、无 `:   ` 或四空格代码块缩进
2. 一个数学元组 / 序列 / 等式被拆进多个单元格时，按语义重建表格（不做页面特异的自动改写）
3. 每个本地图片引用目标真实存在；下载失败且未生成图片引用的视为无害，但**不留失效的本地引用**
4. 围栏代码块闭合；散文占位符（如 `<path>`）已 code 化——行内代码、围栏代码、LaTeX 内部的占位符形状文本忽略
5. Sphinx 页面：标题文本链接到精确源章节、无 `` 图标残留、相对非图片链接解析到源站点、无 `#cmdmount` 之类的旧本地命令锚点；公式类遗留（`\(...\)`、`(N)#\[` 锚点、裸 LaTeX 命令、`aligned` 内 `\label`）按 `references/formula-conversion-rules.md` §3 检查
6. GitBook 页面：无搜索模板残留（`results matching` / `No results`）、无导航栏 h1（`# [标题](站点根/)`）、正文完整——脚本 `remove_gitbook_chrome` 已自动清理，但需复核正文未被误删（正文容器 `.search-noresults` 嵌套在 `#book-search-results` 内，见 KNOWN_ISSUES.md 2026-08-02）
7. 被转成引用块的 **Command Syntax** 章节：仅当页面语义明确是命令语法时才转回代码，不做全局 blockquote→code 改写
8. 语义不明时**不要**自动发明表头或改写引用块；每个候选与判断结论写进轮次清单
9. 循环执行到无结构问题为止

#### 收尾验证（`final_verify.py`）

```powershell
& "<python路径>" "<skill-directory>/scripts/final_verify.py" "{md文件路径}"
```

**FAIL 项必须为零**。验证器先掩码代码，再检查：`\_` / `\*` 清零、`$$` 独占一行且成对、代码围栏闭合、LaTeX 花括号平衡、`aligned` 完整性、`\left\{` 未破坏、正文无未保护尖括号占位符（URL 除外）、无 Sphinx 图标残留、相对链接目标存在、无 `#cmd` 锚点、表格结构有效（分隔行 / 列数一致）、本地图片引用存在、AI 助手清单全部打勾。存在 REVIEW 项或 FAIL 项时退出码非零：FAIL 必须全部修掉；REVIEW 项需 AI 助手逐条复核后重跑，直到无 FAIL、无 REVIEW（退出码 0）为止。

### 第五步：段落合并（可选，通用能力）与输出

**段落源码硬换行合并**（`merge_paragraphs.py`，所有站点适用）：HTML 源码硬换行把自然段
切成 2-6 行短行时（抓取报告「段落切碎检测」命中，或用户偏好），启用合并：

```powershell
& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}" --merge-paragraphs
```

或对已生成的 md 直接执行：

```powershell
& "<python路径>" "<skill-directory>/scripts/merge_paragraphs.py" "{md文件路径}"
```

规则：普通段落合并为一行（空格连接、保留首行缩进）；列表项 + 2 空格缩进文字续行并入
首行（去尾部 hard-break 空格）；`$$` 公式块内部、公式标签行（缩进 + 行尾两空格）、
嵌套子列表、Sphinx 定义列表（term + 缩进定义段）逐字节保护；双空行压缩为单个（块外）。
合并后需重跑 final_verify 确认结构未破坏（`merge_paragraphs` 默认关闭，见「配置」）。

告知用户文件路径，用 Typora 打开即可。

如果本次抓取/转换/审核发现了**新的失败模式**（当前脚本与说明未覆盖的），在交付时附加一小节：

1. 总结现象、可能原因、人工修复方法
2. 写明 `推荐更新 web2md Skill：是 / 否`，为"是"时指出应修改的具体文件（SKILL.md 或哪个脚本）

> 仅当失败模式是新的才写；转换过程中**不直接修改**共享 skill（除非用户明确要求更新）。

---

## 各项目工作文件

- `{项目根目录}/.web2md_tools/intermediate/` — AI 助手清单 `fix_list_roundN.md`（公式/结构审核轮次）、`children_list.md`（子页面清单，`--children-from` 读取）
- `{项目根目录}/.web2md_tools/_archive/` — 一次性调试/诊断文件（含抓取失败快照 `fetch_*.html`）

### 产物清理约定

- `intermediate/`：每轮转换的清单按 `fix_list_roundN.md` 追加，**只保留最近 5 轮**，更早的移入 `_archive/` 或删除；`children_list.md` 为固定名覆盖式（每次 AI 生成新清单直接覆盖），不参与轮次清理
- `_archive/`：**最多保留最近 20 个文件/目录**，超出后删除最旧的（调试快照排查用完后可手动删除）

### 目录结构规范

```
<skill-directory>/                  # 本 skill 目录（脚本唯一来源）
├── SKILL.md
├── KNOWN_ISSUES.md                 # 已知问题与修复记录（排查/优化时读，正常转换不预读）
├── OPTIMIZATION_SUMMARY.md         # 工作交接摘要（大优化后更新，新会话先读）
├── config.example.py               # 配置模板（占位符）
├── references/
│   ├── formula-conversion-rules.md   # 公式转换规则（阶段 C 按需读取：伪公式 A–I / Sphinx 遗留 / 碎片化序列）
│   ├── custom-site-rules.md          # 非平台结构页面规则（自定义站点，检测命中时读取）
│   └── script-development-rules.md   # 脚本技术要点（防御性设计 + 红线，改动 scripts/*.py 前必读）
└── scripts/
    ├── config.py                   # 真实配置（gitignore 排除）
    ├── web2md.py                   ← 主抓取
    ├── markdown_code.py            ← 代码掩码工具
    ├── fix_escapes.py              ← 阶段 A：\_ \* 修复
    ├── list_display_fixes.py       ← 阶段 B：$→$$ 自动升级 + 候选列表
    ├── find_all_missed.py          ← 阶段 C：伪公式扫描
    ├── merge_paragraphs.py         ← 第五步（可选）：段落源码硬换行合并
    ├── final_verify.py             ← 收尾验证
    └── debug/                      ← 本地测试（git 不追踪）
        ├── selftest.py             ← 测试入口
        ├── test_formula_integrity.py
        ├── test_sphinx_conversion.py
        └── test_custom_site.py     ← 自定义站点/段落合并测试
```

- 可复用脚本一律放 `<skill-directory>/scripts/`，**不复制进项目**
- 项目根目录禁止散放 `.py` / `.txt` / `.json`（除平台配置目录外）
- AI 助手生成的中间清单 → `intermediate/`
- 非复用的一次性脚本 → `_archive/`

---

## 配置（config.py）

仿照 confluence-tools 的配置模式：

- 模板：`<skill-directory>/config.example.py`（占位符 + 中文注释）
- 真实配置：`<skill-directory>/scripts/config.py`（**gitignore 排除**，禁止提交）
- 分组：`web2md_config` dict — `python_path`（必填，AI 助手执行脚本的解释器）、`timeout`（请求超时秒数，默认 30）、`collect_children`（是否收集导航子页面，默认 false，可被 CLI 覆盖）、`merge_paragraphs`（是否合并段落内源码硬换行，默认 false，可被 CLI `--merge-paragraphs` 覆盖）
- 加载：`web2md.py` 内 `load_config()`（exec 读取；缺失/损坏时降级默认值并提示首次配置，不退出——脚本仍可独立命令行运行）
- 首次配置：由第一步的配置向导写入，或手动复制 `config.example.py` → `scripts/config.py` 后填真实值

## 测试（本地，git 不追踪）

`scripts/debug/` 存放离线测试（掩码行为、`--apply` 升级、验证器各检查项、DOM 规范化、导航解析 collect_children、`--children-from` 清单解析、裸定界符转换、段落合并），**不随仓库分发**：

```powershell
& "<python路径>" "<skill-directory>/scripts/debug/selftest.py"
```

**修改 scripts/ 下任何脚本后必须运行并全绿。**

---

## 自进化：从错误中学习

**仅在碰到问题需要排查（可能涉及修改 `scripts/*.py`）或需要优化 skill 时才读取 `KNOWN_ISSUES.md`**，查是否已知问题及修复方案；正常转换流程**不预读**——不要出于「流程性保守」提前读，历史条目只在真正排查/优化时才有用。

**分工**：
- **bug 修复** → 记录到 `KNOWN_ISSUES.md`（现象 / 根因 / 修复 / 排查方法）
- **优化 / 重构 / 扩展 / 新增能力** → 记录到 `OPTIMIZATION_SUMMARY.md`

**skill 自我优化（非 bug 修复：重构 / 扩展 / 新增能力）时**：
- **优化前**：先读取 `OPTIMIZATION_SUMMARY.md`——对齐上次大优化的改动范围、修复过的 bug 序列（避免重复踩坑）、协作风格与遗留事项（其中未做的 P3 项可能是本次优化方向）
- **优化后**：将本次优化**追加记录**到 `OPTIMIZATION_SUMMARY.md`（新增 / 改动内容、过程中遇到的问题与解法、遗留事项更新），保持交接文档不过时

每次执行遇到非一次性错误（脚本 bug、转换异常、边界情况），修复并通过验证后，向用户提出固化方案：

> 问题已修复。需要固化到 skill 吗？
> - **修改脚本** — 更新 `scripts/*.py`
> - **记录到 KNOWN_ISSUES.md** — 追加条目（现象/根因/修复/排查方法）
> - **更新 SKILL.md** — 补充注意事项或调整流程
> - **都改 / 不改**

### 固化的核心约束

- **修改 `scripts/*.py` 后必须跑 selftest 全绿**才算完成；改动脚本前先读 `references/script-development-rules.md`（防御机制与红线），改动后同步该文件（防御性设计表按实际机制增删改）
- **写入 KNOWN_ISSUES.md / OPTIMIZATION_SUMMARY.md 的条目日期必须取系统当前时间**：写入前执行 `Get-Date -Format "yyyy-MM-dd"`（Windows）或 `date +%F`（Linux/macOS）获取，禁止硬编码或凭印象写日期（历史教训：曾把 8-02 晚间的条目误标为 8-03）
- **新增/改动配置项时同步更新** `config.example.py` 与本文档的配置说明
- **公共代码必须抽取**：两个及以上脚本共用的逻辑放入 `scripts/` 下共享模块（如 `markdown_code.py`），禁止复制粘贴
- **真实环境验证产物用后即清**：验证用的临时页面/文件不残留
- **失败快照**：处理失败时 `web2md.py` 会把原始 HTML 存入 `{项目根目录}/.web2md_tools/_archive/fetch_*.html`，排查用

---

---

## 脚本技术要点（外置）

脚本的防御性设计机制与「明确不要做的事」红线 → **`references/script-development-rules.md`**（**修改或新增 `scripts/*.py` 之前必读**，正常转换流程不读）。
