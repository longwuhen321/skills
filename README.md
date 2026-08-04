# AI Agent Skills

本仓库收录了一套面向 AI 助手（Claude Code、Reasonix 等）的实用 skills，每个 skill 封装了一个完整的自动化工作流。

---

## 目录

| Skill | 描述 |
|-------|------|
| [web2md](#web2md) | 抓取网页（含公式与子页面）为 Typora 兼容 Markdown |
| [md2zh](#md2zh) | 英文 Markdown → 中文，格式与术语零丢失 |
| [confluence-tools](#confluence-tools) | Confluence 一站式：Markdown 导入 / 导出 / 公式升级 |

三个 skill 可串成一条完整流水线：**网页 → 中文 Markdown → Confluence**（见「组合流水线」）。

---

## 组合流水线

网页内容转中文知识库：

1. **web2md** — 抓取网页（含数学公式、子页面导航），输出本地 Markdown
2. **md2zh** — 翻译为中文，输出 `_zh` 镜像目录
3. **confluence-tools** — 整棵导入 Confluence，保留页面层级

典型用法：`/web2md <URL>` → `/md2zh <file>` → `/confluence-tools` 选「批量导入文件夹树」。

---

## web2md

**网页 → Typora 兼容的 Markdown，图片本地化，公式 LaTeX 化。**

### 核心能力

- **正文提取与转换** — 任意网页 → 干净 Markdown，代码块、表格、链接完整保留
- **图片本地化** — 自动下载到 `.assets/` 文件夹（含 Wikimedia 限流退避），Typora 打开即所见即所得
- **数学公式 LaTeX 化** — 五路识别（Wikipedia / MathJax / MathML / Sphinx / MathJax-SVG），输出 `$...$` / `$$...$$`
- **公式逐处人工级审核** — 脚本机械修复 + AI 助手通读复核，确保每个公式正确渲染
- **导航子页面批量抓取** — 解析侧边栏导航按标题文件夹嵌套落盘；新站点主题识别失效时由 AI 助手清单兜底

### 使用方式

```
/web2md <URL>
```

首次使用会引导配置 Python 环境；之后记住路径不再询问。输出结构：

```
./{页面标题}/
├── {页面标题}.md
└── {页面标题}.assets/           # 本地图片
```

### 质量保障

修改脚本后必须跑 `scripts/tests/selftest.py` 全绿（离线用例，不依赖网络）。

---

## md2zh

**英文 Markdown → 中文 Markdown，格式保留 + 术语一致。**

### 核心能力

- **格式零丢失** — 代码、公式、链接、标识符原样保留，译文与源文件逐字节校验
- **术语全文一致** — 任务级术语表跨块生效，同一术语统一译法
- **长文档分块翻译** — 自动分块处理，单块失败不影响已完成的译文，支持断点续传
- **树形目录批量** — 一次翻译整棵文档树，输出 `_zh` 镜像目录，可直接对接 confluence-tools `--dir` 导入

### 使用方式

```
/md2zh
```

指定要翻译的 `.md` 文件（首次运行会引导配置 Python 路径与决策模式），输出 `<stem>_zh.md` 放在源文件旁。

### 质量保障

`scripts/tests/selftest.py` 离线用例（配置写入、分块保护、端到端 roundtrip），修改后必须全绿。

---

## confluence-tools

**Confluence 一站式工具集：Markdown 导入 + 数学公式升级 + Markdown 导出。**

### 核心能力

- **Markdown 导入** — `.md` → Confluence 页面：图片自动上传、公式/代码/表格转换，同标题页面自动更新
- **文件夹树批量导入** — 把 web2md / md2zh 输出的目录结构整棵导入，保留页面层级（`--dir`）
- **数学公式升级** — 已有页面 `$...$` / `$$...$$` 升级为原生宏，单页 / 递归子页 / 整空间批量
- **Markdown 导出** — Confluence 页面 → Typora 兼容 Markdown：公式还原、图片本地化、表格/代码完整保留，可反向导回
- **配置向导 + 凭据安全** — 首次运行引导配置；Token 仅存 gitignore 排除的 config.py，支持环境变量覆盖

### 使用方式

```
/confluence-tools
```

配置完成后选择：导入 Markdown、批量导入文件夹树、升级数学公式或导出 Markdown。三个脚本也支持独立命令行运行。

### 质量保障

- `scripts/selftest.py`：83 个离线用例，修改脚本后必须全绿
- `KNOWN_ISSUES.md`：已知问题与修复记录（排查前先读）

---

## 安装

将本仓库 clone 到 `~/.claude/skills/` 目录，AI 助手（Claude Code / Reasonix 等）会自动发现并加载其中的 skills：

```bash
git clone <repo-url> ~/.claude/skills/
```

---

## 许可

MIT
