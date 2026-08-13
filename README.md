# AI Agent Skills 套件

![维护状态](https://img.shields.io/github/last-commit/longwuhen321/skills)

**网页 → 中文 → Confluence：一条命令式的知识流水线。**

三个相互对齐的 Agent Skills，把「抓取网页 → 翻译成中文 → 发布到 Confluence」整条链路做成自动化工作流——抓出来的 Markdown 直接能译，译完直接能导入，格式层层兼容，不需要任何手工修复。

## 这套技能能做什么

| 场景 | 怎么做 |
|---|---|
| 想把某个网页文档存成本地知识库 | `/web2md <URL>` → 图片本地化、公式转 LaTeX 的 Typora 兼容 Markdown |
| 英文文档要翻成中文，格式零损坏 | `/md2zh <file>` → 代码/公式/链接原样保留，术语全文一致 |
| 把 Markdown 发布到 Confluence | `/confluence-tools` → 导入页面、整树导入、公式升级、导出，一站式 |
| 把文档官网整体搬进公司知识库 | 三个 skill 串起来，一条命令接一条（见「组合流水线」） |

## 特点

这套技能按「抓取 → 翻译 → 发布」一条流水线设计，三个环节之间目录结构、命名、图片资源约定一致，无需手工转换：

- **格式互通** — web2md 抓出的目录直接是 md2zh 的输入；md2zh 译出的镜像树直接是 confluence-tools 树导入的输入；confluence-tools 导出的目录也可反向导回
- **公式处理** — 五路识别（Wikipedia / MathJax / MathML / Sphinx / MathJax-SVG）转 LaTeX；伪公式由 AI 逐条审核；交付前经 final_verify 全量验证，FAIL 项必须为零
- **确定性校验** — 译文与源文件逐字节比对；分块有契约闸门，空译文、编码错误直接拒绝；离线用例覆盖主要路径
- **真实环境容错** — 基于 Confluence Data Center 9.2.1 实例实测；429 限流指数退避重试、409 版本冲突自动拉取最新重试、批量操作遇错继续、结束汇总失败列表
- **经验沉淀** — 使用中遇到的问题，修复后经确认固化到 skill 自身：bug 记入 KNOWN_ISSUES.md（现象/根因/修复/排查方法），重大优化记入 OPTIMIZATION_SUMMARY.md 交接新会话。技能在使用中持续改进，而不是交付后停止

## 组合流水线

```
任意网页文档 ──web2md──▶ Typora Markdown ──md2zh──▶ 中文 Markdown ──confluence-tools──▶ Confluence 页面
（含数学公式）  图片本地化  ＋本地图片      格式零丢失  （_zh 镜像目录）  整树导入，保留层级  （含原生公式）
              公式 LaTeX
```

典型用法三步走：

```
/web2md https://docs.example.com/page
/md2zh ./page/
/confluence-tools → 选「批量导入文件夹树」
```

三个 skill 也可以独立使用——web2md 单独当网页抓取器，md2zh 单独当翻译器，confluence-tools 单独当 Confluence 客户端。

## 快速开始

```bash
git clone https://github.com/longwuhen321/skills.git ~/.claude/skills/
```

将仓库放入所用 Agent 的 skills 发现目录后即可加载；例如 Claude Code 使用 `~/.claude/skills/`，Codex 通常使用 `~/.codex/skills/`。首次调用时，每个 skill 会通过配置向导引导你完成 Python 环境与凭据设置。

## 运行环境参考

下面是 **2026-08-13 已验证环境的参考快照**，用于帮助迁移和排障，不是最低版本锁定。未列出的版本组合不代表一定不支持；在新环境中应先运行对应 skill 的配置检查、依赖检查和自测。

### 公共基础

| 项目 | 已验证参考 | 使用说明 |
|---|---|---|
| Agent 宿主 | 支持 `SKILL.md`，可读写本地文件并调用 Python 进程 | skills 发现目录由宿主决定，不应在脚本中写死某个用户目录 |
| 操作系统 / Shell | Windows + PowerShell 5.1 | Linux / macOS 尚未做同等强度的整套回归验证 |
| Python | CPython 3.11.9 | 项目尚未声明严格最低版本；新部署优先使用 Python 3.11，并在同一任务中保持解释器一致 |
| 文本与仓库格式 | UTF-8；仓库文本使用 LF | Markdown、JSON 和脚本均应显式按 UTF-8 处理 |
| 本地配置 | 各 skill 的 `scripts/config.py` | 真实配置不入库；从 `config.example.py` 创建，并避免公开本机路径、URL、Token、代理、Space Key、页面 ID 等环境信息 |

### 各 skill 的依赖与外部环境

| Skill | Python 依赖（已验证版本） | 外部环境 | 兼容边界与可选项 |
|---|---|---|---|
| `web2md` | `requests 2.32.3`、`beautifulsoup4 4.13.4`、`markdownify 1.2.3`、`lxml 5.3.1` | 可访问目标网页及图片资源的网络 | 普通抓取不依赖浏览器；JavaScript 渲染的导航可能需要浏览器渲染后再处理。HTTP 代理可选，SOCKS 需另装 PySocks。Typora 只是可选阅读器 |
| `md2zh` | 仅 Python 标准库 | 需要具备翻译与复核能力的 AI Agent；默认不依赖外部机器翻译服务 | 转换脚本负责字节保护、校验和断点状态；翻译与语义复核由 Agent 完成。全流程应使用同一 Python 解释器和 UTF-8 |
| `confluence-tools` | `requests 2.32.3`、`markdown2 2.5.3`、`beautifulsoup4 4.13.4`、`markdownify 1.2.3` | Confluence Data Center 9.2.1（build 9109）及 PAT Bearer 认证 | Easy Heading 模式已验证插件版本为 `3.6.3`，storage 宏名为 `easy-heading-free`、schema version 为 `1`；使用原生 `toc` 模式不需要该插件。Confluence Cloud 及其他 Server / DC 版本尚未完成同等验证 |

表中的第三方包版本是一次通过当前测试集的组合，不是 `requirements.txt` 式精确锁定。升级 Python、依赖、Confluence 或 Easy Heading 后，应重新运行三个 skill 的自测；分发仓库时不要附带真实 `config.py`、日志、缓存或本地修复副本。

---

## 技能一览

| Skill | 一句话定位 | 核心能力 |
|-------|-----------|---------|
| [web2md](#web2md) | 任意网页 → Typora 兼容 Markdown | 图片本地化、五路公式识别、导航子页面嵌套抓取 |
| [md2zh](#md2zh) | 英文 Markdown → 中文，格式零丢失 | 字节级保护、术语全文一致、断点续传、树形批量 |
| [confluence-tools](#confluence-tools) | Confluence 一站式工具集 | 导入 / 整树导入 / 公式升级 / 导出，含凭据安全管理 |

### web2md

**网页 → Typora 兼容的 Markdown，图片本地化，公式 LaTeX 化。**

- **正文提取与转换** — 任意网页 → 干净 Markdown，代码块、表格、链接完整保留
- **图片本地化** — 自动下载到 `.assets/` 文件夹（含 Wikimedia 限流退避），Typora 打开即所见即所得
- **数学公式 LaTeX 化** — 五路识别（Wikipedia / MathJax / MathML / Sphinx / MathJax-SVG），输出 `$...$` / `$$...$$`
- **导航子页面批量抓取** — 解析侧边栏导航，按标题文件夹嵌套落盘（深度最多 2 级），单页文档自动识别、不重复抓取
- **公式逐处人工级审核** — 脚本机械修复 + AI 助手通读复核，输出前经全量验证器把关

输出结构：

```
./{页面标题}/
├── {页面标题}.md
└── {页面标题}.assets/           # 本地图片
```

### md2zh

**英文 Markdown → 中文 Markdown，格式保留 + 术语一致。**

- **格式零丢失** — 代码、公式、链接、标识符原样保留，译文与源文件逐字节校验
- **术语全文一致** — 任务级术语表跨块生效，同一术语统一译法
- **长文档分块翻译** — 自动分块处理，单块失败不影响已完成的译文，支持断点续传
- **树形目录批量** — 一次翻译整棵文档树，输出 `_zh` 镜像目录，可直接对接 confluence-tools 的树导入

### confluence-tools

**Confluence 一站式工具集：Markdown 导入 + 数学公式升级 + Markdown 导出。**

- **Markdown 导入** — `.md` → Confluence 页面：图片自动上传、公式/代码/表格转换，同标题页面自动更新
- **文件夹树批量导入** — 把 web2md / md2zh 输出的目录结构整棵导入，保留页面层级
- **数学公式升级** — 已有页面 `$...$` / `$$...$$` 升级为原生宏，单页 / 递归子页 / 整空间批量
- **Markdown 导出** — Confluence 页面 → Typora 兼容 Markdown：公式还原、图片本地化，可反向导回
- **对真实服务器宽容** — 429 限流指数退避重试、409 版本冲突自动拉取最新重试、批量遇错继续并汇总失败列表

---

## 质量保障

这些技能是**在真实文档上打磨出来的**，不是示例代码：

- **离线自测** — 每个 skill 自带 `selftest.py`，改脚本必须全部用例通过才能交付
- **已知问题透明记录** — 每个 skill 都有 `KNOWN_ISSUES.md`，真实遇到过的坑、根因与修复方式全部公开，排查问题先查它
- **配置与凭据安全** — 真实 Token / 路径只存 gitignore 排除的 `config.py`，仓库内只有占位符模板；支持环境变量覆盖
- **脚本独立运行** — 所有脚本不依赖 AI 助手也能命令行独立执行，配置向导只是锦上添花

## 设计原则

- **共享脚本不复制** — 可复用脚本统一放在 skill 的 `scripts/` 目录，绝不复制进各项目
- **AI 助手判断，脚本只做机械操作** — 需要语义理解的地方（如区分粗体与数学符号）由 AI 判断，脚本只做精确替换，分工明确、可验证
- **配置向导只问一次** — Python 路径、Confluence 地址与 Token 配置一次后永久记住，之后零打扰

## 常见问题

**Q: 必须安装 Python 吗？**
三个 skill 都依赖 Python 执行脚本。首次调用时配置向导会先确认解释器；缺少依赖时会报告安装命令，并在获得用户确认后再安装。

**Q: 必须用 Confluence 吗？**
不是。web2md 和 md2zh 完全独立——一个把网页存成本地 Markdown 知识库，一个做文档翻译。只有想发布到 Confluence 时才需要 confluence-tools。

**Q: 三个 skill 可以只用其中一个吗？**
可以，互不依赖。组合使用只是为了流水线无缝衔接。

**Q: 这些 skill 支持哪些 AI 助手？**
按 SKILL.md 标准组织，Claude Code、Reasonix 等支持 agent skills 标准的助手均可直接使用。

## 许可

MIT
