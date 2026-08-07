---
name: confluence-tools
description: Confluence 工具集：Markdown 导入页面、数学公式升级等
---

# confluence-tools — Confluence 工具集

将 Markdown 文件导入 Confluence 页面，或升级已有页面的数学公式格式。

## 目标环境

- **Confluence 版本：9.2.1**（Data Center 系列，build 9109，实例实测版本；API 行为与 Cloud 有差异，调试时以此版本为准）
- **认证方式**：Personal Access Token (PAT)，Bearer 认证

## 触发

**仅显式调用**。用户使用 `/confluence-tools` 时才执行。

## 首次运行：配置向导

检查 `scripts/config.py` 是否存在。不存在时启动配置向导。

**脚本完整性检查（每次执行前）**：确认关键脚本存在（`scripts/md_import.py`、`scripts/math_upgrade.py`、`scripts/md_export.py`、`scripts/common.py`、`scripts/debug_utils.py`）。脚本缺失/损坏时**不要直接重写**——先按「容错与安全 → 脚本文件恢复」用 git 恢复（注意恢复的是最近提交版本），再继续。

### 向导规则

**1. 配置来源唯一原则**

所有配置值**只来自用户输入**。禁止自动读取/预填历史配置（`settings.json`、`settings.local.json`、旧会话日志、旧 `config.py` 备份等）——旧值可能已失效（token 过期、URL 变更），且未经确认的凭据使用有安全风险。

**2. Python 环境路径：先问用户，用户不给再找**

1. **先直接询问用户**：Python 解释器路径？（用户给出 → 直接用）
2. 用户不提供（如回复"帮我找"）→ 才允许自动扫描 `where python`、Anaconda 目录、系统 PATH，优先选已安装 `requests`/`markdown2` 的环境
3. 扫描到候选 → **展示候选给用户确认**（选哪个或拒绝）
4. 扫描无结果 → 该配置缺失，**中断任务**（没有 Python 无法执行脚本，属必需项）

**边界（必守）**：询问用户之前，不得进行任何自动探测/扫描（包括 PATH 扫描、`py --list` 等），即使扫描结果只作为候选展示。只有用户明确表示不提供路径之后，才允许扫描。

**3. 其他配置项：逐项询问，必需项无值即中断**

- **必需项**：Confluence 地址、PAT Token、默认空间 → 用户不提供，**直接中断任务**（不写 config.py、不继续）
- **选填项**（明确询问"要不要填"）：用户名（仅记录）、`upgrade_config.default_page`、`import_config.default_parent_id`、`import_config.default_page_name` 等 → 用户可明确选择留空
- 不存在"展示当前值，回车跳过"的默认值机制——向导阶段 config.py 不存在，没有任何当前值

**4. 中断语义**

- 任一必需项缺失 → 明确告知缺了哪几项 → 任务终止，提示用户可随时重新 `/confluence-tools` 补全
- 不创建半成品 config.py

**5. 交互形式：普通对话逐项询问**

- 配置向导使用普通文本对话，**逐项一问一答**，用户直接打字回答
- **禁止使用选项式提问工具**（如 AskUserQuestion / ask）：其选项形式适合选择，不适合 URL/Token/路径等开放输入，且会诱导把扫描结果硬塞进选项（违反规则 2 边界）

### 配置项

**── 通用 ──**

1. **Python 环境路径** → `common_config.python_path`
   - 先询问用户，用户不提供才自动扫描（见上方规则 2）
2. **Confluence 地址** → `common_config.confluence_url`（必需）
3. **用户名** → `common_config.confluence_user`（选填，仅记录，不参与认证）
4. **PAT Token** → `common_config.confluence_token`（必需）

**── md_import ──**

5. **导入默认空间** → `import_config.space`（必需）
6. **公式对齐方式** → `import_config.math_align`（`"left"` 左对齐 / `"center"` 居中，默认 `"left"`）
7. **默认父页面 ID** → `import_config.default_parent_id`（选填，留空不挂父级；仅新建页面生效，已存在页面按标题更新、位置不变）
8. **默认页面标题** → `import_config.default_page_name`（选填，留空取 md 文件名）
9. **树导入开关** → `import_config.tree_import`（默认 `false`，`true` 启用 `--dir` 批量文件夹树导入；首次运行配置向导时明确询问）
10. **树导入层级策略** → `import_config.fix_hierarchy`（`"confirm"` 默认，存在移动时预览确认 / `"auto"` 直接移动 / `"off"` 不移动）
11. **自动目录宏** → `import_config.toc_enabled`（默认 `true`，`false` 关闭）+ `import_config.toc_min_headings`（默认 `4`：子标题 H2~H6 达到该数量时自动在正文顶部插入 Confluence 目录宏）

**── math_upgrade ──**

12. **默认目标页面 ID** → `upgrade_config.default_page`（选填，设了之后不传 --page-id 也能跑）
13. **空间模式默认空间** → `upgrade_config.space`（选填，跑空间模式时需要）
14. **公式对齐方式** → `upgrade_config.math_align`（`"left"` 左对齐 / `"center"` 居中，默认 `"left"`）
15. **自动更新** → `upgrade_config.auto_update`（默认 `true`，`false` 则仅生成 debug）
16. **AI 验证** → `upgrade_config.ai_verify`（默认 `false`，`true` 则暂停等人工审核）
17. **默认递归** → `upgrade_config.recursive`（默认 `true`，有 page_id 时自动递归子页面）
18. **递归最大层级** → `upgrade_config.max_depth`（默认 `0` 不限）

**── md_export ──**

19. **默认输出目录** → `export_config.output_dir`（选填，默认 `confluence_export`，相对当前工作目录，也支持绝对路径如 `D:/out`；可被 `--output` 覆盖）
20. **默认递归导出** → `export_config.recursive`（默认 `true`，有 page_id 时自动递归子页面；可被 `--recursive` / `--no-recursive` 覆盖）
21. **空间模式默认空间** → `export_config.space`（选填，跑 `--space` 模式时需要）

**── Debug ──**

22. **Debug 阈值** → `debug_config.max_size_mb`（默认 50）
23. **Debug 保留数** → `debug_config.keep_recent`（默认 20）

配置确认后同时将 Python 路径写入 Bash allow 规则（Claude Code 为 `.claude/settings.local.json`，Reasonix 为 `reasonix.toml` 的 `[permissions].allow`），避免后续执行每次确认。

后续调用直接从 `scripts/config.py` 读取，不再询问。配置失效（401/403/连接超时）时提示用户重新走配置向导。

**运行期配置补齐**：运行期发现 config.py 缺 `export_config` 配置项时，咨询用户该参数的配置值，然后补齐到 config.py 中。

---

## 子命令

配置完成后询问用户：

> 要做什么？
> 1. **导入 Markdown** — 将 .md 文件上传为 Confluence 页面
> 2. **批量导入文件夹树** — `--dir` 模式，保留文件夹层级（需开启 tree_import）
> 3. **升级数学公式** — 升级已有页面的 $...$ / $$...$$ 为原生宏
> 4. **导出 Markdown** — 从 Confluence 拉取页面为 Typora 兼容 Markdown

---

### 一、导入 Markdown（md_import）

**读取 python_path 后执行：**

```bash
"<python_path>" "<SKILL_DIR>/scripts/md_import.py" "<md文件路径>" [--parent-id ID] [--page-name NAME] [--space KEY] [--align left|center]
# --parent-id / --page-name 未传时回退到 config.py 的 import_config 对应配置项

"<python_path>" "<SKILL_DIR>/scripts/md_import.py" --dir "<根文件夹>" [--space KEY] [--align left|center] [--fix-hierarchy confirm|auto|off] [--plan-only] [--yes]
# --dir 批量树导入（需 import_config.tree_import 开启）；--space/--align/--fix-hierarchy 未传时默认从 config.py 读取
```

**流程：**
1. 用户指定 md 文件（拖入或粘贴路径）
2. **直接读取** `scripts/config.py` 的 import_config 执行（`space` / `default_parent_id` / `default_page_name`），**不询问**（与"配置向导：后续调用不再询问"一致）
3. 仅当用户**主动提及**变更时，用 CLI 参数覆盖：`--space`（目标空间）、`--parent-id`（父页面）、`--page-name`（标题）
4. 执行脚本 → 输出结果（page_id / 更新版本号）

**取值优先级**：用户显式指定 > `config.py` 配置 > 代码默认值（父级留空不挂、标题取文件名）

**批量导入文件夹树（--dir）：**
- 目录结构：每个含 .md 的文件夹 = 一个页面（标题=文件夹名，内容=同名 .md），子文件夹 = 子页面，`.assets/` 仅作图片源；中间文件夹无 .md 时跳级
- 流程：扫描建树 → 只读生成计划（新建🆕 / 更新🔄 / 移动📦）→ `fix_hierarchy=confirm` 时存在移动会暂停确认 → 深度优先执行（父先子后，子页面挂到父页面下）
- `--plan-only` 仅输出计划不执行；预览确认后加 `--yes` 执行可跳过再次确认
- 优先级：用户显式指定 > config.py 配置 > 代码默认值

---

### 二、升级数学公式（math_upgrade）

```bash
"<python_path>" "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> [--align left|center] [--ai-verify]
"<python_path>" "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> --recursive [--max-depth N]
"<python_path>" "<SKILL_DIR>/scripts/math_upgrade.py" --space <KEY>
```

**关键参数：**
- `--align left`：左对齐（推荐默认，原生 mathblock + alignment=left），`--align center`：居中
- `--ai-verify` / `--no-ai-verify`：覆盖是否暂停等人工审核
- `--confirm <debug目录>`：AI 助手验证 debug 文件后确认更新（配合 `ai_verify` 使用；`--confirm latest` 取最近一次 debug 目录）
- `--recursive` / `--no-recursive`：覆盖是否递归子页面
- `--no-auto-update`：仅生成 debug 文件，不更新页面
- `--stop-on-error`：批量模式遇错即停（默认遇错继续，末尾汇总失败页面）

---

### 三、导出 Markdown（md_export）

把 Confluence 页面（storage format）导出为 **Typora 兼容 Markdown**：

- 数学公式原生宏还原：`mathblock` → `$$...$$`、`mathinline` → `$...$`（旧 mathjax 宏兼容）
- 代码宏 → ```` ```语言 ```` 围栏；`toc` 宏 → `[toc]`；note/info/warning 等提示宏 → 引用块
- 图片附件下载到 `<标题>.assets/`，md 内引用改写为相对路径
- 输出结构：`<标题>/<标题>.md + <标题>.assets/` —— 与 web2md 输出、`md_import --dir` 目录结构一致，**导出的目录树可直接用 `--dir` 反向导回 Confluence**

```bash
"<python_path>" "<SKILL_DIR>/scripts/md_export.py" --page-id <ID> [--recursive|--no-recursive] [--output <目录>]
"<python_path>" "<SKILL_DIR>/scripts/md_export.py" --space <KEY> [--output <目录>]
```

**关键参数：**
- `--page-id <ID>`：导出单页；`--recursive`（默认从 config 读）时递归导出子页面，子页面文件夹嵌套在父页面目录下
- `--space <KEY>`：批量导出整个空间（平铺，每页一个文件夹）
- `--output <目录>`：输出根目录（默认 `export_config.output_dir`，相对当前工作目录，也支持绝对路径）
- 页面无图时不产生 `.assets/` 文件夹；图片下载失败在 md 中保留注释
- 未知宏降级为 `<!-- 未处理的宏: xxx -->` 注释，结束时汇总提示

**依赖**：`beautifulsoup4` + `markdownify`（缺失时脚本启动会明确提示安装；配置向导阶段可确认环境已装）。

---

## 独立运行（不依赖 AI 助手）

脚本直接从 `scripts/config.py` 读取配置，无需任何环境变量或 AI 助手依赖：

```bash
python scripts/md_import.py my_doc.md --space ES
python scripts/math_upgrade.py --page-id 12345 --align left
python scripts/md_export.py --page-id 12345
```

首次使用：复制 `config.example.py` → `scripts/config.py`，填入真实值即可。

---

## 容错与安全

- **429 限流**：所有请求自动重试（指数退避，最多 3 次，尊重 `Retry-After`）。批量升级/大空间导入可能触发 429（Server/DC 官方未提供限流文档，重试为防御性措施）。
- **遇错继续**：批量升级默认跳过失败页面继续处理，结束时汇总失败列表；`--stop-on-error` 可立即停止。
- **版本冲突**：md_import 更新页面遇 409 时自动拉取最新版本重试一次（页面被他人并发修改时）。
- **凭据**：token 可用环境变量 `CONFLUENCE_TOKEN` 覆盖 config.py，共享机器/CI 上不必落盘。
- **图片上传失败**：md_import 结束时汇总报告未上传成功的图片，保留原始引用。
- **base64 内嵌图片**：`data:` URI 图片不当作本地文件处理，保留原始引用，结束时提示跳过数量。
- **脚本文件恢复**：脚本被删除/损坏时，**先向用户确认是否需要恢复，确认后才执行恢复（不替用户操作）**。确认后先 `git status` 判断：
  - 跟踪文件被删 → 显示 `D <file>`，可恢复：`git checkout -- <脚本路径>`
  - ⚠️ 恢复的是**最近一次提交**的版本，之后未提交的改动（新配置项、修复、重构）会丢失，需按 `OPTIMIZATION_SUMMARY.md` / `KNOWN_ISSUES.md` 的记录手动重做
  - 未跟踪文件 → git 无法恢复
  - `config.py`（真实凭据）被 `.gitignore` 排除，删除后 git 无法恢复，只能重跑配置向导
  - **预防**：重要改动及时 commit；执行前先做脚本完整性检查（见「首次运行」）

---

## 调试日志

```
<SKILL_DIR>/debug/
├── import/              # md_import
│   └── YYYYMMDD_HHMMSS/before_upload.html
├── upgrade/             # math_upgrade
│   └── YYYYMMDD_HHMMSS/{before,after}.html + info.txt
└── export/              # md_export
    └── YYYYMMDD_HHMMSS/{page_id}_<标题>.html（原始 storage 快照）
```

总大小超过 `max_size_mb` **或** 时间戳目录数超过 `keep_recent` 时自动清理（大小/数量**二选一即清理**），从最旧删起、至少保留最近 `keep_recent` 个（配置见 `debug_config`）。

---

## 文件结构

```
confluence-tools/
├── SKILL.md
├── KNOWN_ISSUES.md             # 已知问题与修复记录（排查改脚本时读取，按需追加）
├── OPTIMIZATION_SUMMARY.md     # 大优化交接总结（skill 自我优化前读取、优化后追加：改动范围、bug 序列、协作风格、遗留事项）
├── config.example.py           # 配置模板（提交 git，含占位符和注释）
├── scripts/
│   ├── config.py               # 真实配置（不提交，从 example 拷贝）
│   ├── common.py               # 公共：配置加载、HTTP 重试、页面收集
│   ├── debug_utils.py          # 公共：日志清理
│   ├── md_import.py            # Markdown → Confluence
│   ├── math_upgrade.py         # 数学公式升级
│   ├── md_export.py            # Confluence → Markdown 导出
│   └── debug/                  # 本地测试（git 不追踪）
│       └── selftest.py         # 离线自测（不依赖服务器，mock 配置运行）
└── debug/                      # 调试日志快照（gitignore 排除）
    ├── import/
    ├── upgrade/
    └── export/

忽略规则（.gitignore）位于仓库根目录（见根目录 `.gitignore`）
```

---

## 自进化：从错误中学习

排查需修改 `scripts/*.py` 的问题时，**先读取 `KNOWN_ISSUES.md`** 查是否已知问题及修复方案。

**skill 自我优化（非 bug 修复：重构/扩展/新增能力）时：**

- **优化前**：先读取 `OPTIMIZATION_SUMMARY.md`——对齐上次大优化的改动范围、修复过的 bug 序列（避免重复踩坑）、协作风格与遗留事项（其中 P3 未做项可能是本次优化方向）。
- **优化后**：将本次优化追加记录到 `OPTIMIZATION_SUMMARY.md`（新增/改动内容、过程中遇到的问题与解法、遗留事项更新），保持交接文档不过时。
- **分工**：bug 修复 → 记 `KNOWN_ISSUES.md`；优化/重构/扩展 → 记 `OPTIMIZATION_SUMMARY.md`。

每次执行遇到非一次性错误（脚本 bug、渲染异常、边界情况），修复并通过验证后，向用户提出：

> 问题已修复。需要固化到 skill 吗？
> - **修改脚本** — 更新 `scripts/*.py`
> - **记录到 KNOWN_ISSUES.md** — 追加修复条目（含现象/根因/修复/排查方法）
> - **都改 / 不改**

### 实现前检查点（必过）

**在写任何代码之前，必须输出方案并让用户确认。** 方案至少覆盖以下三点：

1. **参考现有模式** — 项目中已有类似的东西吗？风格、格式、命名是怎样的？我的新方案是否和它一致？不一致的话，有什么充分的理由？
2. **最小改动原则** — 有没有更简单的方案？是在现有文件上改还是新建文件？新建的话，已有的相关文件要不要删除（避免残留）？
3. **影响范围** — 这个改动会影响哪些文件？脚本、配置、文档是否都会同步更新？

检查通过后才能开始实现。

### 回归测试（必过）

**修改 `scripts/*.py` 后，必须运行 `scripts/debug/selftest.py` 且全部用例通过**，才能算修改完成：

```bash
"<python_path>" "<SKILL_DIR>/scripts/debug/selftest.py"
```

- 全绿 = 转换逻辑未破坏，改动可固化
- 有红 = 修改引入回归，先修复再继续

### 真实环境验证的清理（必过）

**使用真实服务器做验证时（建测试页、传测试附件、跑导入/升级），验证完成后必须清理产物**：

- 创建的测试页面 → 用 REST API 删除：
  `DELETE {confluence_url}/rest/api/content/{page_id}`
- 上传的测试附件 → 随页面删除，无需单独处理
- 验证脚本（临时写的一次性 .py）→ 删除，不留在 scripts/ 目录

不留任何验证残留，向用户报告验证结果时说明已清理。

### 固化的核心约束

**脚本必须保持独立运行能力。** 任何修改都不能破坏以下原则：

- 脚本启动时从 `scripts/config.py` 自给自足，不依赖 AI 助手注入任何环境变量或上下文
- 不能引入只在 AI 对话中才有的状态（如"上次用户说的那个值"）
- CLI 参数只用于临时覆盖，不能把一个原本可选的参数变成必须由 AI 助手传的
- 新增依赖的 Python 包必须在配置向导中检测，或脚本启动时明确提示缺失
- **向导禁止预填**：配置向导阶段禁止自动读取历史配置文件（settings.json、settings.local.json、旧会话日志等）预填任何参数，所有值只来自用户输入（Python 路径按"先问后找"规则执行）
- **公共代码必须抽取**：两个及以上脚本共用的逻辑放入 `common.py` 或新建共用模块，禁止复制粘贴
- **配置模板必须同步**：新增配置项时，同时更新 `config.example.py` 和 SKILL.md 的配置向导

### 凭据安全

**真实凭据只能存在于 `scripts/config.py`。** 该文件已通过 `.gitignore` 排除提交。

`config.example.py`（提交 git）使用占位符示例，**禁止**出现真实 Token、密码、内网地址。

不固化的一次性问题：网络不通、磁盘满、Token 过期、Markdown 内容自身错误。
