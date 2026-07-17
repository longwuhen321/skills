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

- 抓取任意网页，提取正文内容并转换为 Markdown
- 图片自动下载到本地 `.assets` 文件夹
- 数学公式智能识别与转换（Wikipedia `.mwe-math-element`、MathJax、MathML、Sphinx `class="math"`）
- 防御性设计：限流退避、文件名截断、URL 解码、Wikipedia 专有清洗
- 生成后审核：Claude 会逐项检查 `\_`/`\*` 反转义、伪公式修复、孤 `$` 污染等

### 使用方式

```
/web2md <URL>
```

首次使用时会引导配置 Python 环境（自动搜索或手动指定），之后记住路径不再询问。

### 输出结构

```
./{页面标题}/
├── {页面标题}.md
└── {页面标题}.assets/
    ├── image1.png
    ├── image2.jpg
    └── ...
```

用 Typora 打开 `.md` 文件即可获得完整阅读体验。

---

## 安装

将本仓库 clone 到 `~/.claude/skills/` 目录，Claude Code 会自动发现并加载其中的 skills：

```bash
git clone <repo-url> ~/.claude/skills/
```

---

## 许可

MIT
