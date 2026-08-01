# Claude Code Skills

本仓库收录了一套面向 Claude Code 的实用 skills，每个 skill 封装了一个完整的自动化工作流。

---

## 目录

| Skill | 描述 |
|-------|------|
| [md2zh](#md2zh) | 将英文 Markdown 翻译为中文，保留格式与技术准确性 |
| [web2md](#web2md) | 抓取网页内容，输出 Typora 兼容的 Markdown 文件 |
| [confluence-tools](#confluence-tools) | Confluence 工具集：Markdown 导入页面、数学公式升级 |

---

## md2zh

**英文 Markdown → 中文 Markdown，格式零损失。**

### 核心能力

- 保留所有 Markdown 格式（代码块、表格、链接、列表、引用块等）
- 智能处理不应翻译的内容：代码、LaTeX 公式、URL、专有名词/品牌名
- 翻译代码块内注释、图片 alt 文本、链接显示文本
- 术语一致性保障：翻译前扫描高频术语并建立映射表
- 翻译后自动校验：结构对比（标题/表格/代码块/图片/链接数量） + 随机段落抽查

### 使用方式

```
/md2zh
```

然后指定要翻译的 `.md` 文件路径。输出文件为 `原文件名_zh.md`，放在同目录下。

### 技术参考

翻译技术术语时优先参考全国科学技术名词审定委员会 (cnterm.cn) 的审定名词与相关国标（GB/T 2900.56-2008 等）。

---

## web2md

**网页 → Typora 兼容的 Markdown，图片本地化，公式 LaTeX 化。**

### 核心能力

- 抓取任意网页，提取正文并转为 Markdown（`markdownify` + `BeautifulSoup`）
- 图片自动下载到本地 `.assets` 文件夹，支持 Wikimedia 限流退避
- 数学公式四路识别：Wikipedia `.mwe-math-element`、MathJax `<script>`、`<math>` MathML、Sphinx `class="math"`
- **三阶段公式审核流水线**：脚本机械修复 + Claude 上下文判断，确保每个公式正确渲染

### 使用方式

```
/web2md <URL>
```

首次使用时会引导配置 Python 环境（自动搜索或手动指定），同时写入 Bash allow 规则避免后续重复确认。之后记住路径不再询问。

### 输出结构

```
./{页面标题}/
├── {页面标题}.md
└── {页面标题}.assets/
    ├── image1.png
    ├── image2.jpg
    └── ...
```

### 公式审核流水线（第四步）

脚本 `process_math_formulas` 只能做标签级转换。生成 `.md` 后，分三个阶段完成审核：

| 阶段 | 工具 | 做什么 | 谁判断 |
|------|------|--------|--------|
| **A** | `fix_escapes.py` | `$...$` / `$$...$$` 内 `\_`→`_`、`\*`→`*`（不碰 `\{` `\}`） | 脚本机械执行 |
| **B** | `list_display_fixes.py` | 列出含 `\begin{aligned}` 或 `\\` 行断但仍被 `$` 包裹的公式 | **Claude** 逐条判 `$`→`$$` |
| **C** | `find_all_missed.py`（辅助扫描）+ **LLM 通读循环** | Wikipedia 伪公式识别：`**i**`、`*x*2`、`*a*1 + *b*2**i**` 等 | **Claude** 读全文 → 写清单 → Edit → 复核，循环至干净 |

#### 阶段 C 伪公式分类（LLM 逐条判断）

脚本无法区分表格粗体和数学符号——由 Claude 通读全文，根据上下文识别以下类别：

- **斜体+数字** → 下标/上标：`*a*1` → `$a_{1}$`、`*x*2` → `$x^{2}$`
- **斜体+运算符** → 行内公式：`*x* = *y*` → `$x=y$`
- **粗体+数字/运算符** → 向量公式：`**i** ⋅ **j** = **k**` → `$\mathbf{i}\cdot\mathbf{j}=\mathbf{k}$`
- **粗体数域记号**：`**R**` → `$\mathbf{R}$`、`**C**` → `$\mathbf{C}$` 等
- **Unicode 运算符**（±, ⋅, ×, ∗, −）→ LaTeX
- **Unicode 不等号/集合/箭头**（≤, ∈, →, ⇒, …）→ LaTeX
- **混合粗体+斜体**：`*a* + *b* **i** + *c* **j**` → `$a+b\mathbf{i}+c\mathbf{j}$`
- **函数+斜体参数**：`cos(*φ*)` → `$\cos(\varphi)$`

> 判断边界：表格 `| **i** | **j** | **k** |` 保留 bold；维度 `2 × 2` 保留 Unicode。

#### 收尾验证

`final_verify.py` 最终确认：`\_` 清零、`\*` 清零、`\\` 行断完整、`\left\{` 未破坏、`$$` 独占一行、LLM 清单全部打勾。

### 项目文件结构

```
<项目根目录>/
├── .web2md_tools/
│   ├── web2md.py              # 主抓取脚本
│   ├── fix_escapes.py          # 阶段 A：\_ \* 修复
│   ├── list_display_fixes.py   # 阶段 B：$→$$ 候选列表
│   ├── find_all_missed.py      # 阶段 C：伪公式扫描辅助
│   ├── final_verify.py         # 收尾验证
│   ├── intermediate/           # LLM 清单 fix_list_roundN.md
│   └── _archive/               # 调试脚本等一次性文件
└── .claude/
    └── settings.local.json     # Python 路径 + Bash allow 规则
```

### 设计原则

- **Claude 做判断，脚本做执行**——`**i**` → `$\mathbf{i}$` 这类转换，脚本只能做 Claude 手写的精确 `str.replace`，不能自动判断上下文
- **不碰 `\{` `\}`**——它们是 `\left\{` `\right\}` 的合法 LaTeX 组件
- **Wikipedia 特化清洗**仅对 `wikipedia.org` / `wikimedia.org` 生效，`is_wiki` 兜底

---

## confluence-tools

**Confluence 一站式工具集：Markdown 导入 + 数学公式升级。**

### 核心能力

- **Markdown 导入** — `.md` → Confluence 页面：代码块、表格、图片附件（上传失败 / 本地缺失 / base64 内嵌均有明确报告）、`==高亮==`、数学公式
- **数学公式升级** — 已有页面的 `$...$` / `$$...$$` / `\`\`\`latex` 升级为原生 `mathinline` / `mathblock` 宏，支持单页、递归子页、整空间批量
- **公式对齐可配置** — 导入与升级统一支持左对齐 / 居中（原生 `mathblock + alignment` 参数，已在 Confluence 9.2.1 实测），`--align` 可临时覆盖
- **自动查重更新** — 空间内标题内存匹配（大小写不敏感），同标题自动更新为新版本，409 版本冲突自动重试
- **容错机制** — 429 限流指数退避重试（尊重 `Retry-After`）、批量遇错继续 + 末尾失败汇总（`--stop-on-error` 可停）、全请求超时保护
- **首次配置向导** — 必需项（地址 / Token / 空间）缺失即中断、禁止预填历史配置、Python 路径先问后找
- **凭据安全** — Token 只存 `config.py`（gitignore 排除），支持 `CONFLUENCE_TOKEN` 环境变量覆盖

### 使用方式

```
/confluence-tools
```

首次运行走配置向导，之后选择：导入 Markdown 或升级数学公式。两个脚本也支持独立命令行运行。

### 技术要点

- Confluence 9.x REST API，Bearer Token (PAT) 认证
- 公式宏统一由 `common.build_block_template` 生成（left = `mathblock + alignment=left`，center = 默认居中）
- 导入流水线：protect code/math → markdown2 → restore → convert 宏 → 上传附件 → 更新
- 公共层 `common.py` 集中处理：配置加载、HTTP 重试、分页收集、宏模板

### 质量保障

- `scripts/selftest.py`：39 个离线用例（转换管线、版本号流程、限流重试、对齐、base64 图片等），mock 配置与网络，**修改脚本后必须全绿**
- `KNOWN_ISSUES.md`：已知问题与修复记录（现象 / 根因 / 修复 / 排查方法），排查前先读
- 真实环境验证产物（测试页 / 临时脚本）用后即清

### 文件结构

```
confluence-tools/
├── SKILL.md
├── KNOWN_ISSUES.md           # 已知问题与修复记录
├── config.example.py         # 配置模板（占位符）
├── scripts/
│   ├── config.py             # 真实配置（gitignore 排除）
│   ├── common.py             # 公共：配置加载、HTTP 重试、页面收集、宏模板
│   ├── debug_utils.py        # 调试日志清理
│   ├── md_import.py          # Markdown → Confluence
│   ├── math_upgrade.py       # 数学公式升级
│   └── selftest.py           # 离线自测（39 用例）
└── debug/                    # 导入/升级调试快照（自动清理）
```

### 自进化机制

每次执行遇到非一次性错误（脚本 bug、渲染异常、边界情况），修复并通过验证后询问是否固化：

- **修改脚本** — 更新 `scripts/*.py`
- **记录到 KNOWN_ISSUES.md** — 追加现象 / 根因 / 修复 / 排查方法
- **更新 SKILL.md** — 补充注意事项或调整流程

---

## 安装

将本仓库 clone 到 `~/.claude/skills/` 目录，Claude Code 会自动发现并加载其中的 skills：

```bash
git clone <repo-url> ~/.claude/skills/
```

---

## 许可

MIT
