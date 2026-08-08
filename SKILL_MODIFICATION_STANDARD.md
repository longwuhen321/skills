# Skill 修改执行标准（项目级规范）

> 本文件是 `~/.claude/skills/` 下所有 skill（`web2md` / `md2zh` / `confluence-tools`）的**修改执行标准**。
> **何时读**：会话中准备修改任何 skill 文件（`SKILL.md`、`references/*.md`、`scripts/*.py`、`config.example.py`）之前，**先读本文件**。
> **何时不读**：仅正常使用 skill（执行抓取 / 翻译 / 导入等流程，不涉及修改）时，**不读本文件**——避免无谓加载。
> 本文件是执行标准，不是 skill 的一部分；`SKILL.md` 是每个 skill 的执行指令，本文件是「如何修改那些指令」的标准。

---

## 一、修改前的流程（必过）

任何对 skill 文件的修改，按以下顺序：

1. **读本执行标准**（本文件）
2. **读目标 skill 的 `OPTIMIZATION_SUMMARY.md`**（对齐上次优化：改动范围、修复过的 bug 序列、遗留事项——其中 P3 未做项可能是本次方向）
3. **按「实现前检查点」输出方案，让用户确认后再动手**：
   - **参考现有模式** — 项目中已有类似的东西吗？风格、格式、命名是否一致？
   - **最小改动原则** — 有没有更简单的方案？在现有文件上改还是新建？新建的话旧文件要不要删（避免残留）？
   - **影响范围** — 改动会影响哪些文件？脚本、配置、文档是否同步更新？
4. 修改完成后，按本文件「三、修改后的验证」逐项验证

---

## 二、SKILL.md 的书写规范

### 2.1 frontmatter（YAML）

| 字段 | 要求 | 来源 |
|---|---|---|
| `name` | 小写 kebab-case，**与所在目录名完全一致** | [官方仓库] agent-skills-spec.md |
| `description` | **第三人称**，同时说「做什么」+「何时用」，含触发关键词 | [官方仓库] plugin-dev skill-development |
| 其他字段 | 按需（`license` / `metadata` / `allowed-tools` 等） | [官方仓库] |

官方允许省略 `name`（用目录名）与 `description`（用正文首段），但本项目**明确要求写全**——触发准确率依赖 description。

### 2.2 正文书写原则（本项目实践沉淀 + 官方印证）

1. **自描述、自包含**
   - 规则写全本文件内，**不引用其他 skill 的规则细节**（如「与 xxx 同规则」）——执行时上下文只有本 SKILL.md，引用指向的内容不可见
   - 不用具体实例名（`Commands.md`、`NuttShell`、`settings.local.json` 这类真实项目/平台名）——用**占位符**（`<页面>`、`<标题>`）+ **示例图**（目录树缩进）说明结构
   - 复杂结构（目录格式、清单格式、输出结构）用「占位符 + 示例图」直接画出，不依赖外部参照
   - 唯一例外：**复述被删除的原文**（记录「改了什么」）可以在变更记录里出现，那是记录不是引用
2. **执行指令风格**：祈使句 / 不定式（动词开头），非第二人称 [官方仓库]
3. **聚焦单一能力**：一个 skill 一个能力 [官方仓库]
4. **渐进式披露**：SKILL.md 精简（官方 skill-development 指南：**1,500–2,000 词理想，<5k 上限**），长内容放 `references/`，SKILL.md 用链接引用 [官方原文]
5. **脚本组织**：可复用脚本放各 skill 的 `scripts/`，不复制进项目；两个及以上脚本共用逻辑抽共享模块，禁止复制粘贴
6. **无跨 skill 依赖**：每个 skill 独立成文件夹，不依赖其他 skill [官方仓库，经搜索快照]
7. **行尾强制 LF**（**强制性**）：仓库 `.gitattributes` 规定 `* text=auto eol=lf`，所有文本文件必须 LF 行尾。**修改/新建文件后必须保持 LF**——尤其避免用 Python 文本模式（`open(f, 'w')`）在 Windows 上写文件（`\n` 会自动转 `\r\n`），写入后检查 `file <路径>` 无 CRLF；如产生 CRLF，`sed -i 's/\r$//'` 修正后再提交

### 2.3 自描述规范的三条判定标准

| 类型 | 判定 | 处理 |
|---|---|---|
| 执行依赖的跨 skill 引用 | AI 需要对方规则细节才能执行（如「与 xxx 同规则」） | **删**，改自描述 |
| 对接/兼容说明 | 描述与其他 skill 的兼容性（「目录结构一致」「可直接反向导入」） | 自描述化（用示例图说自己的结构），不自行断言兼容性 |
| 真实默认值/命令值/禁止项清单 | `confluence_export`（默认目录）、`--confirm latest`（命令值）、`settings.json`（"禁止读取"对象） | **保留**（是真实值，不是示例） |

---

## 三、修改后的验证（必过）

按改动类型逐项验证：

| 改动 | 必须验证 |
|---|---|
| `scripts/*.py` | 跑该 skill 的 `scripts/test/selftest.py` **全绿**；改动前先读 `references/script-development-rules.md`（防御机制与红线），改动后同步该文件（防御性设计表按实际机制增删改） |
| `config.example.py` | 同步更新 SKILL.md 的配置说明；真实 `config.py` 缺新键会被门禁拦下（`check_config_sync.py`），属预期行为 |
| `SKILL.md` / `references/*.md` | 全文通读一次，确认符合本文件「二、书写规范」：无跨 skill 引用、无具体实例名、结构自描述 |
| 新增配置项 | 同步 `config.example.py` + SKILL.md 配置说明 |
| 真实环境验证产物 | 用后即清，不留残留 |

---

## 四、收尾自查（每次修改后必过）

修改完成后，**向用户提出记录建议**，**是否记录、记录到哪由用户决定**（我们出决策建议、由客户拍板，不自动强制补记）：

- 列出改动项，按类别给建议：**bug 修复 → `KNOWN_ISSUES.md`**；**优化/重构/扩展 → `OPTIMIZATION_SUMMARY.md`**
- 用户确认后按约定补记：
  - **写入前必须读该文档的头部说明（追加模板 / 维护约定），按约定插入**——追加模板在文档顶部、条目按时间倒序（最新在前）
  - **日期取系统当前时间**（`Get-Date -Format "yyyy-MM-dd"` / `date +%F`），禁止硬编码
- 用户选择不记录则跳过

---

## 五、官方参考（来源与置信度）

> 本节内容已通过**代理**直接抓取官方原文核实（先查询环境是否有代理——检查 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量、`git config --global http.proxy`，或探测常见本地代理端口；有则用代理抓取官方原文，无代理则降级用搜索快照转述并标注）：
> `agentskills.io/specification`（Agent Skills 开放标准，官方 spec 重定向地址）、`code.claude.com/docs/en/skills`（Claude Code 官方文档）、`raw.githubusercontent.com/anthropics/claude-code/.../skill-development/SKILL.md`（官方 skill 开发指南）。

### 5.1 官方文档结构（来源：官方原文，经代理核实）[官方原文]

- **SKILL.md frontmatter**：`name`（必填，≤64 字符，小写字母/数字/连字符，不得以连字符开头/结尾）、`description`（必填，≤1024 字符，非空，说「做什么」+「何时用」）、可选 `license` / `compatibility`（≤500）/ `metadata`（键值映射）/ `allowed-tools`（空格分隔工具列表，实验性）——来源：`agentskills.io/specification` 官方原文
- **Claude Code 扩展字段**：`argument-hint`（自动补全提示，计入 1536 字符上限）、`disable-model-invocation`（true = 仅手动触发，description 移出上下文）、`user-invocable`（false = 从 / 菜单隐藏）、`model` / `context`（含 `context: fork` 子代理）/ `agent` / `hooks`——来源：`code.claude.com/docs/en/skills` 官方原文
- **渐进式披露**：SKILL.md 精简（官方 skill-development 指南：**1,500–2,000 词理想，<5k 上限**），长内容放 `references/`，`scripts/` 放可执行代码，`assets/` 放模板/图标——来源：官方 skill-development 指南原文
- **无跨 skill 依赖**、**聚焦单一能力**、**一次改动只涉及一个 skill**——来源：anthropics/skills 仓库（CONTRIBUTING.md 已核实 main 分支 404，此条经搜索快照转述）[官方仓库转述]

### 5.2 与官方规范的偏差（本项目有意为之）

| 官方 | 本项目 |
|---|---|
| description 可省略（用正文首段） | 必须写全（触发准确率） |
| `name` 可省略（用目录名） | 必须写全（与目录名一致） |
| 修改既有 skill：先搜索防重复、重大变更先开 issue、单 PR 单 skill | 本项目无 issue/PR 机制，但保留「先查重、单次改单 skill」精神；重大变更先输出方案给用户确认 |

### 5.3 参考链接

- [agentskills.io/specification](https://agentskills.io/specification) — Agent Skills 开放标准官方原文（`anthropics/skills` 仓库 `agent-skills-spec.md` 的重定向地址）[官方原文]
- [Claude Code docs: skills](https://code.claude.com/docs/en/skills) — Claude Code 官方文档（frontmatter 参考、扩展字段）[官方原文]
- [anthropics/claude-code plugin-dev skill-development](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/skill-development/SKILL.md) — 官方 skill 开发指南（渐进式披露 1500-2000 词、第三人称描述）[官方原文]
- [anthropics/skills agent-skills-spec.md](https://github.com/anthropics/skills/blob/main/spec/agent-skills-spec.md) — 开放标准字段规范（内容已迁移至 agentskills.io）[官方仓库]
- [claude-skills/spec/SKILL_SPEC.md](https://github.com/inbharatai/claude-skills/blob/main/spec/SKILL_SPEC.md) — 社区规范 [第三方]

---

*本文件由 2026-08-08 会话确立，内容基于本次会话的实践沉淀（自描述规范、收尾自查、门禁机制）与官方规范检索结果。*
