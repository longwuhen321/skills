---
name: confluence-tools
description: Confluence 工具集：Markdown 导入页面、数学公式升级等。仅在用户显式调用 $confluence-tools 时触发，不因一般 Confluence 讨论自动触发
---

# confluence-tools — Confluence 工具集

将 Markdown 文件导入 Confluence 页面、升级已有页面的数学公式格式，或将页面导出为 Markdown。

## 目标环境

- **Confluence 版本：9.2.1**（Data Center 系列，build 9109，实例实测版本；API 行为与 Cloud 有差异，调试时以此版本为准）
- **认证方式**：Personal Access Token (PAT)，Bearer 认证

## 触发

**仅显式调用**。用户使用 `$confluence-tools` 时才执行。

## 首次运行：配置向导

检查 `scripts/config.py` 是否存在。不存在时启动配置向导。

**脚本完整性检查（每次执行前）**：确认关键脚本存在（`scripts/md_import.py`、`scripts/math_upgrade.py`、`scripts/md_export.py`、`scripts/common.py`、`scripts/config_parser.py`、`scripts/debug_utils.py`、`scripts/dependency_check.py`、`scripts/check_config_sync.py`、`scripts/package_check.py`）。脚本缺失/损坏时**不要直接重写**——先按「容错与安全 → 脚本文件恢复」用 git 恢复（注意恢复的是最近提交版本），再继续。

**依赖预检（每次执行前）**：Python 路径确定后、执行任一页面脚本前运行：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/dependency_check.py"
```

预检会实际导入并一次报告完整依赖集 `requests`、`markdown2`、`beautifulsoup4`（导入名 `bs4`）、`markdownify`；包虽然可定位、但因缺少 DLL 或子依赖而无法导入时同样失败。退出码 1 表示存在导入失败项，应中断当前操作并完整报告；安装任何依赖前，AI 助手必须展示拟执行的安装命令并取得用户审批。检查脚本和页面脚本都不会自行安装或修改 Python 环境。

**配置同步门禁（每次执行前）**：`config.py` 存在时运行：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/check_config_sync.py"
```

门禁对比 `config.example.py` 的**全部五分组**（`common_config` / `import_config` / `upgrade_config` / `export_config` / `debug_config`）键集合与值类型，只比结构不比值（token / 路径等占位符 vs 真实值天然不同）。配置由共享的 AST + `ast.literal_eval` 解析器读取；函数调用、导入及其他带副作用的 Python 代码一律拒绝，不执行配置代码。不一致（退出码 1/2）→ **中断任务**，按输出报告补齐/修正后重跑；通过（退出码 0）→ 继续。

### 向导规则

**1. 配置来源唯一原则**

所有配置值**只来自用户输入**。禁止自动读取/预填历史配置（`settings.json`、`settings.local.json`、旧会话日志、旧 `config.py` 备份等）——旧值可能已失效（token 过期、URL 变更），且未经确认的凭据使用有安全风险。

**2. Python 环境路径：先问用户，用户不给再找**

1. **先直接询问用户**：Python 解释器路径？（用户给出 → 直接用）
2. 用户不提供（如回复"帮我找"）→ 才允许自动扫描 `where python`、Anaconda 目录、系统 PATH，优先选已安装 `requests`、`markdown2`、`beautifulsoup4`（导入名 `bs4`）、`markdownify` 的环境
3. 扫描到候选 → **展示候选给用户确认**（选哪个或拒绝）
4. 扫描无结果 → 该配置缺失，**中断任务**（没有 Python 无法执行脚本，属必需项）

**边界（必守）**：询问用户之前，不得进行任何自动探测/扫描（包括 PATH 扫描、`py --list` 等），即使扫描结果只作为候选展示。只有用户明确表示不提供路径之后，才允许扫描。

**3. 其他配置项：逐项询问，必需项无值即中断**

- **必需项**：Confluence 地址、PAT Token、默认空间 → 用户不提供，**直接中断任务**（不写 config.py、不继续）
- **选填项**（明确询问"要不要填"）：用户名（仅记录）、`upgrade_config.default_page`、`import_config.default_parent_id`、`import_config.default_page_name` 等 → 用户可明确选择留空
- 不存在"展示当前值，回车跳过"的默认值机制——向导阶段 config.py 不存在，没有任何当前值

**4. 中断语义**

- 任一必需项缺失 → 明确告知缺了哪几项 → 任务终止，提示用户可随时重新 `$confluence-tools` 补全
- 不创建半成品 config.py

**5. 交互形式：普通对话逐项询问**

- 配置向导使用普通文本对话，**逐项一问一答**，用户直接打字回答
- **禁止使用 AI 助手 的选项式提问工具**（如 `request_user_input`）：其选项形式适合选择，不适合 URL/Token/路径等开放输入，且会诱导把扫描结果硬塞进选项（违反规则 2 边界）

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

配置确认后，如执行该 Python 路径需要超出当前沙箱权限，必须先通过 AI 助手 的权限审批；如需免除后续重复确认，通过 AI 助手 的审批界面设置对应规则（避免后续执行每次确认）。

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

### 业务能力矩阵

| 能力 | 输入/范围 | 结果 | 关键安全边界 |
|---|---|---|---|
| 单页导入 | `.md`；空间 + 标题，可用 `--parent-id` / `--page-id` 消歧 | 新建或更新一个页面 | 查询严格区分 `FOUND` / `NOT_FOUND` / `ERROR`；只有 `NOT_FOUND` 才新建，歧义与查询失败均不写入 |
| 文件夹树导入 | `--dir` 或 `--resume tree_plan.json` | 按父子层级新建、更新或移动 | 整批只建一次页面索引；计划固化 page ID/version 且同一 ID 只能分配一次；逐节点写检查点，可断点续传 |
| 公式升级 | 单页、页面树或整个空间 | 更新 Confluence storage 正文 | 默认要求公式零残留；人工确认前复查源版本与内容哈希；批量失败返回非零 |
| Markdown 导出 | 单页、页面树或整个空间 | `<page_id>_<标题>/<标题>.md` + 可选 assets | 公共分页器拉全量；空间模式每页只导出一次；附件名和落盘路径受限于页面目录 |

---

### 一、导入 Markdown（md_import）

**读取 python_path 后执行：**

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" "<md文件路径>" [--page-id ID] [--parent-id ID] [--page-name NAME] [--space KEY] [--align left|center] [--force]
# --parent-id / --page-name 未传时回退到 config.py 的 import_config 对应配置项

"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" --dir "<根文件夹>" [--space KEY] [--align left|center] [--fix-hierarchy confirm|auto|off] [--plan-only] [--yes] [--force]
# --dir 批量树导入（需 import_config.tree_import 开启）；--space/--align/--fix-hierarchy 未传时默认从 config.py 读取

"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" --resume "<tree_plan.json>" [--yes] [--force]
```

**流程：**
1. 用户指定 md 文件（拖入或粘贴路径）
2. **直接读取** `scripts/config.py` 的 import_config 执行（`space` / `default_parent_id` / `default_page_name`），**不询问**（与"配置向导：后续调用不再询问"一致）
3. 仅当用户**主动提及**变更时，用 CLI 参数覆盖：`--space`（目标空间）、`--parent-id`（父页面）、`--page-id`（精确页面）、`--page-name`（标题）
4. 执行脚本 → 输出结果（page_id / 更新版本号）；任一必要步骤失败时进程返回非零

**取值优先级**：用户显式指定 > `config.py` 配置 > 代码默认值（父级留空不挂、标题取文件名）

**页面匹配与并发保护：**
- `--page-id` 精确选择页面；否则按空间 + 标题查找，`--parent-id` 同时用于同名页面消歧
- 查询结果必须是 `FOUND`、`NOT_FOUND`、`ERROR` 之一：仅 `NOT_FOUND` 新建；同名歧义、分页/API 错误均为 `ERROR` 并中断，禁止误建页面
- 更新使用查询时取得的源版本。遇到 409 默认拒绝覆盖；仅用户明确要求并传 `--force` 时，才拉取最新版本重试一次
- Markdown 中独占一行的 `[toc]` 转为目录宏；自动目录检测到已有 `[toc]` 时不重复插入

**批量导入文件夹树（--dir）：**
- 目录结构：每个含 .md 的文件夹 = 一个页面（标题=文件夹名，内容=同名 .md），子文件夹 = 子页面，`.assets/` 仅作图片源；中间文件夹无 .md 时跳级
- 流程：扫描建树 → 一次性拉取空间页面索引 → 只读生成计划（新建🆕 / 更新🔄 / 移动📦，固化 page ID/version；同一 page ID 被多个节点命中即整批拒绝）→ `fix_hierarchy=confirm` 时存在移动会暂停确认 → 深度优先执行（父先子后，子页面挂到父页面下）
- `--plan-only` 仅输出计划不执行；预览确认后加 `--yes` 执行可跳过再次确认
- 计划写入运行期日志目录下的 `tree_plan.json`；每个成功节点都会更新检查点。中途失败后用 `--resume <tree_plan.json>` 跳过已完成节点并继续，避免重复新建
- 优先级：用户显式指定 > config.py 配置 > 代码默认值

---

### 二、升级数学公式（math_upgrade）

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> [--align left|center] [--ai-verify]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> --recursive [--max-depth N]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --space <KEY>
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --confirm <debug目录|latest>
```

**关键参数：**
- `--align left`：左对齐（推荐默认）：为每个 `mathblock` 插入或替换唯一的 `alignment=left`；`--align center`：删除已有 alignment 参数，使用原生居中默认值
- `--ai-verify` / `--no-ai-verify`：覆盖是否在机械验证通过后暂停等人工审核；AI 审核不会绕过 XHTML、宏数量或默认零残留门禁
- `--confirm <debug目录>`：AI 助手验证 debug 文件后确认更新（配合 `ai_verify` 使用；`--confirm latest` 取最近一次 debug 目录）。确认时重新拉取远端页面并核对转换源版本与 SHA256；任一变化都拒绝提交旧 `after.html`，必须重新生成转换结果，不提供绕过参数
- `--recursive` / `--no-recursive`：覆盖是否递归子页面
- `--no-auto-update`：仅生成 debug 文件，不更新页面
- `--stop-on-error`：批量模式遇错即停（默认遇错继续，末尾汇总失败页面）
- `--allow-math-residuals`：显式容忍验证后仍存在的 `$...$`、`$$...$$` 或 latex 代码围栏；默认任何残留都失败，并报告 `类型@行:列`

---

### 三、导出 Markdown（md_export）

把 Confluence 页面（storage format）导出为 **Typora 兼容 Markdown**：

- 数学公式原生宏还原：`mathblock` → `$$...$$`、`mathinline` → `$...$`（旧 mathjax 宏兼容）
- 代码宏 → ```` ```语言 ```` 围栏；`toc` 宏 → `[toc]`；note/info/warning 等提示宏 → 引用块
- 图片附件下载到 `<标题>.assets/`，md 内引用改写为相对路径；附件文件名使用附件 ID + basename，且落盘前验证路径仍位于页面目录内
- 输出结构（页面目录 + 同名 md + 可选 assets）：

  ```
  <输出根>/
  ├── <页面ID>_<页面A>/           # 页面目录（ID + 标题，避免同名覆盖）
  │   ├── <页面A>.md              # 与该文件夹同名的 md
  │   └── <页面A>.assets/         # 该页面的图片（页面无图时不产生）
  └── <页面ID>_<页面B>/
      └── <页面B>.md
  ```

  子页面导出时 `<页面ID>_<页面A>` 内嵌套子页面目录（层级保留）。

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py" --page-id <ID> [--recursive|--no-recursive] [--output <目录>]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py" --space <KEY> [--output <目录>]
```

**关键参数：**
- `--page-id <ID>`：导出单页；`--recursive`（默认从 config 读）时递归导出子页面，子页面文件夹嵌套在父页面目录下
- `--space <KEY>`：批量导出整个空间（平铺，每页一个文件夹）；空间索引已包含全部页面，不再对每页递归，确保每个 page ID 只导出一次
- `--output <目录>`：输出根目录（默认 `export_config.output_dir`，相对当前工作目录，也支持绝对路径）
- 页面无图时不产生 `.assets/` 文件夹；图片下载失败在 md 中保留注释
- 页面标题和附件名会移除路径字符、尾随点/空格，并给 Windows 保留设备名（如 `CON`、`NUL`、`COM1`）加安全前缀
- 代码、公式、目录宏使用占位符跨越 Markdown 空行规范化，恢复后保留代码块内部空行；`[toc]` 独占一行，可被导入流程还原为目录宏
- 未知宏保留可读正文，并附带 HTML 转义后的原始 Confluence XHTML 注释；注释内的 `--` 转义为 `&#45;&#45;`，可还原且不会生成非法注释。`ri:url`（包括 `ac:image` 外链图片和未知宏正文中的独立 URL）保留为 Markdown 图片、链接或 URL
- 页面、子页面与附件列表都使用公共分页器拉取全量；分页 HTTP/JSON 错误直接传播并使进程返回非零，不把部分结果当成功

**完整依赖**：`requests` + `markdown2` + `beautifulsoup4`（导入名 `bs4`）+ `markdownify`。导出功能使用后两项；配置向导选择 Python 环境时须确认四项均已安装。

---

## 独立运行（不依赖 AI 助手）

脚本直接从 `scripts/config.py` 读取配置，无需任何环境变量或 AI 助手依赖：

```bash
python -X utf8 scripts/dependency_check.py
python -X utf8 scripts/md_import.py my_doc.md --space ES
python -X utf8 scripts/math_upgrade.py --page-id 12345 --align left
python -X utf8 scripts/md_export.py --page-id 12345
```

首次使用：复制 `config.example.py` → `scripts/config.py`，填入真实值即可。

---

## 容错与安全

- **429 限流**：所有请求自动重试（指数退避，最多 3 次，尊重 `Retry-After`）。批量升级/大空间导入可能触发 429（Server/DC 官方未提供限流文档，重试为防御性措施）。
- **遇错继续但不误报成功**：批量升级、树导入、空间导出默认汇总全部失败；页面、附件上传、附件下载或附件后二次更新任一失败，最终退出码即非零。`--stop-on-error` 可让批量升级立即停止。
- **版本冲突**：md_import 更新页面遇 409 默认安全失败；仅用户明确要求并传 `--force` 时才拉取最新版本重试一次。
- **分页完整性**：空间页面、子页面及附件均通过公共分页器拉取；分页请求或响应结构错误会中断/记为失败，不返回静默截断的部分数据。
- **凭据**：token 可用环境变量 `CONFLUENCE_TOKEN` 覆盖 config.py，共享机器/CI 上不必落盘。
- **图片上传失败**：md_import 汇总未上传成功的图片并保留原始引用，同时把当前页面/树节点标为失败；树计划保留 page ID/version 供 `--resume` 重试。
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
<SKILL_DIR>/logs/
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
│   ├── check_config_sync.py    # 配置同步强制门禁（每次执行前）
│   ├── config_parser.py        # 配置 AST + literal_eval 安全解析（load/check 同源）
│   ├── common.py               # 公共：配置加载、HTTP 重试、页面收集
│   ├── debug_utils.py          # 公共：日志清理
│   ├── dependency_check.py     # 四项 Python 依赖统一预检（只报告，不安装）
│   ├── package_check.py        # 待发布目录只读路径/敏感项检查
│   ├── md_import.py            # Markdown → Confluence
│   ├── math_upgrade.py         # 数学公式升级
│   ├── md_export.py            # Confluence → Markdown 导出
│   └── test/                    # 本地测试（git 追踪）
│       ├── selftest.py           # 离线自测（不依赖服务器，mock 配置运行）
│       ├── test_config_sync.py   # 配置结构门禁的隔离回归测试
│       └── test_regressions.py   # 工程安全与页面业务回归测试
└── logs/                        # 调试日志快照（gitignore 排除）
    ├── import/
    ├── upgrade/
    └── export/

忽略规则（.gitignore）位于仓库根目录（见根目录 `.gitignore`）
```

---

## 自进化：从错误中学习

**修改本 skill 任何文件（`SKILL.md` / `references/*.md` / `scripts/*.py` / `config.example.py`）之前，先读 `<skill-directory>/../SKILL_MODIFICATION_STANDARD.md`**（skill 修改执行标准：书写规范、修改前流程、验证与收尾自查）。仅正常使用本 skill（不涉及修改）时不读。

排查需修改 `scripts/*.py` 的问题时，**先读取 `KNOWN_ISSUES.md`** 查是否已知问题及修复方案。

**skill 自我优化（非 bug 修复：重构/扩展/新增能力）时：**

- **优化前**：先读取 `OPTIMIZATION_SUMMARY.md`——对齐上次大优化的改动范围、修复过的 bug 序列（避免重复踩坑）、协作风格与遗留事项（其中 P3 未做项可能是本次优化方向）。
- **优化后**：将本次优化追加记录到 `OPTIMIZATION_SUMMARY.md`（新增/改动内容、过程中遇到的问题与解法、遗留事项更新），保持交接文档不过时。
- **⚠️ 写入 `OPTIMIZATION_SUMMARY.md` / `KNOWN_ISSUES.md` 前必须读该文档的头部说明（追加模板 / 维护约定），按文档约定插入**——例如 `OPTIMIZATION_SUMMARY.md` 的约定是「追加操作、插入位置在顶部（最新条目紧随模板之后、时间倒序）」，**禁止直接 `cat >>` 追加到文件末尾或只模仿尾部格式**。
- **分工**：bug 修复 → 记 `KNOWN_ISSUES.md`；优化/重构/扩展 → 记 `OPTIMIZATION_SUMMARY.md`。

每次执行遇到非一次性错误（脚本 bug、渲染异常、边界情况），修复并通过验证后，向用户提出：

> 问题已修复。需要固化到 skill 吗？
> - **修改脚本** — 更新 `scripts/*.py`
> - **记录到 KNOWN_ISSUES.md** — 追加修复条目（含现象/根因/修复/排查方法）
> - **都改 / 不改**

**收尾自查**：本次会话是否改动了 `scripts/*.py`、`SKILL.md`、`config.example.py`、`references/*.md`？
- 有 → **向用户提出记录建议**：列出改动项，按类别给出建议（bug 修复 → `KNOWN_ISSUES.md`；优化/重构/扩展 → `OPTIMIZATION_SUMMARY.md`），**是否记录、记录到哪由用户决定**——确认后按约定补记（日期取系统时间、按文档头部约定插入），用户选择不记录则跳过
- 无 → 跳过

### 实现前检查点（必过）

**在写任何代码之前，必须输出方案并让用户确认。** 方案至少覆盖以下三点：

1. **参考现有模式** — 项目中已有类似的东西吗？风格、格式、命名是怎样的？我的新方案是否和它一致？不一致的话，有什么充分的理由？
2. **最小改动原则** — 有没有更简单的方案？是在现有文件上改还是新建文件？新建的话，已有的相关文件要不要删除（避免残留）？
3. **影响范围** — 这个改动会影响哪些文件？脚本、配置、文档是否都会同步更新？

检查通过后才能开始实现。

### 回归测试（必过）

**修改 `scripts/*.py` 后，必须运行 `scripts/test/selftest.py` 且全部用例通过**，才能算修改完成：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/test/selftest.py"
```

- 全绿 = 转换逻辑未破坏，改动可固化
- 有红 = 修改引入回归，先修复再继续

#### 测试能力矩阵

| 能力 | 离线验收 | 主要覆盖位置 |
|---|---|---|
| 配置 | 只接受无副作用字面量；五分组键和类型漂移返回 1/2 | `scripts/test/test_config_sync.py`、`TestSafeConfigAndPackaging` |
| 退出码 | 页面、树节点、批量与附件失败均汇总为失败，入口最终返回非零 | `TestImportLookupAndConflict`、`TestTreePlanAndResume`、`TestMathSafety`、`TestExportSafety` |
| 日志隔离 | 测试把 `SKILL_ROOT` / debug 目录定向到临时目录，不读写真实 `logs/` | `scripts/test/selftest.py` 各工具 `setUp`、`ImporterCase` / `UpdaterCase` / `ExporterCase` |
| CLI | 三个页面入口用 `python -X utf8 ... --help` 均为退出码 0 | `TestCliSurface` |
| 依赖缺失 | 实际导入四个模块；缺包、坏安装或缺 DLL 均一次报告完整失败集 | `TestSafeConfigAndPackaging` |
| Windows 编码 | GBK 控制台环境下用 `python -X utf8` 执行验证，中文输出可按 UTF-8 解码 | `ConfigSyncTests.test_utf8_mode_overrides_gbk_console_for_validation_output` |

### 发布前只读检查（必过）

先把待发布文件复制到**隔离的候选目录**，不带真实 `scripts/config.py`、`logs/`、缓存或版本控制目录；不要直接把含本机配置的工作目录当发布包。然后运行：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/package_check.py" --root "<待发布目录>"
```

检查按两阶段执行：先只看路径和名称，发现 `config.py`、`.env`、`logs/`、`__pycache__/`、常见工具缓存/虚拟环境、`node_modules/`、`.git/`、`.claude/`、`.reasonix/`、`.vscode/`、字节码、符号链接、junction/reparse point 或解析后越界路径时立即失败，且不读取任何文本；路径门禁通过后，才扫描允许的文本文件是否含疑似真实 `token` / `confluence_token` / `api_token` / `auth_token` / `access_token` / Bearer 值（含单行字典赋值）。退出码：0 通过，1 发现禁项，2 用法、目录列举或允许文本读取错误。

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
