# Claude Code Skills

本仓库收录了一套面向 Claude Code 的实用 skills，每个 skill 封装了一个完整的自动化工作流。

---

## 目录

| Skill | 描述 |
|-------|------|
| [md2zh](#md2zh) | 将英文 Markdown 翻译为中文，保留格式与技术准确性 |
| [token-track](#token-track) | 自动追踪 Token 用量，生成会话消耗报告 |
| [web2md](#web2md) | 抓取网页内容，输出 Typora 兼容的 Markdown 文件 |

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

## token-track

**每次对话结束自动更新 Token 消耗报告。**

### 核心能力

- 记录每次提问的原文与时间戳
- 按 API 调用链拆分 token 明细（input / output / cached / cost / 耗时）
- 生成会话概览（总次数、总 token、总费用）
- 支持**自动模式**（Stop hook 触发）与**手动模式**（用户主动调用）

### 使用方式

```
/token-track
```

首次运行时选择自动/手动模式。自动模式下，每次对话结束自动更新项目根目录的 `token-usage.md`。

### 文件结构

```
<项目根目录>/
├── .claude/
│   ├── token-track-mode.txt    # 运行模式
│   └── settings.local.json     # Stop hook（自动模式）
└── token-usage.md              # 生成的报告
```

### 数据来源

- `~/.claude/telemetry/` — API 调用记录（`tengu_api_success` 事件）
- `~/.claude/history.jsonl` — 用户提问内容
- `~/.claude/sessions/` — 当前会话标识

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

## 安装

将本仓库 clone 到 `~/.claude/skills/` 目录，Claude Code 会自动发现并加载其中的 skills：

```bash
git clone <repo-url> ~/.claude/skills/
```

---

## 许可

MIT
