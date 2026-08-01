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
- **选填项**（明确询问"要不要填"）：用户名（仅记录）、`upgrade_config.default_page` 等 → 用户可明确选择留空
- 不存在"展示当前值，回车跳过"的默认值机制——向导阶段 config.py 不存在，没有任何当前值

**4. 中断语义**

- 任一必需项缺失 → 明确告知缺了哪几项 → 任务终止，提示用户可随时重新 `/confluence-tools` 补全
- 不创建半成品 config.py

**5. 交互形式：普通对话逐项询问**

- 配置向导使用普通文本对话，**逐项一问一答**，用户直接打字回答
- **禁止使用 AskUserQuestion**：其选项形式适合选择，不适合 URL/Token/路径等开放输入，且会诱导把扫描结果硬塞进选项（违反规则 2 边界）

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

**── math_upgrade ──**

7. **默认目标页面 ID** → `upgrade_config.default_page`（选填，设了之后不传 --page-id 也能跑）
8. **空间模式默认空间** → `upgrade_config.space`（选填，跑空间模式时需要）
9. **公式对齐方式** → `upgrade_config.math_align`（`"left"` 左对齐 / `"center"` 居中，默认 `"left"`）
10. **自动更新** → `upgrade_config.auto_update`（默认 `true`，`false` 则仅生成 debug）
11. **Claude 验证** → `upgrade_config.claude_verify`（默认 `false`，`true` 则暂停等人工审核）
12. **默认递归** → `upgrade_config.recursive`（默认 `true`，有 page_id 时自动递归子页面）
13. **递归最大层级** → `upgrade_config.max_depth`（默认 `0` 不限）

**── Debug ──**

14. **Debug 阈值** → `debug_config.max_size_mb`（默认 50）
15. **Debug 保留数** → `debug_config.keep_recent`（默认 20）

配置确认后同时将 Python 路径写入 Bash allow 规则（`settings.local.json`），避免后续执行每次确认。

后续调用直接从 `scripts/config.py` 读取，不再询问。配置失效（401/403/连接超时）时提示用户重新走配置向导。

---

## 子命令

配置完成后询问用户：

> 要做什么？
> 1. **导入 Markdown** — 将 .md 文件上传为 Confluence 页面
> 2. **升级数学公式** — 升级已有页面的 $...$ / $$...$$ 为原生宏

---

### 一、导入 Markdown（md_import）

**读取 python_path 后执行：**

```bash
"<python_path>" "<SKILL_DIR>/scripts/md_import.py" "<md文件路径>" [--parent-id ID] [--page-name NAME] [--space KEY] [--align left|center]
```

**流程：**
1. 用户指定 md 文件（拖入或粘贴路径）
2. 询问：父页面 ID？（可选，回车跳过）
3. 询问：自定义页面标题？（可选，默认取文件名）
4. 询问：目标空间？（可选，回车用 `scripts/config.py` 的 `import_config.space`）
5. 执行脚本 → 输出结果（page_id / 更新版本号）
6. 脚本自动：已存在→更新，不存在→新建

---

### 二、升级数学公式（math_upgrade）

```bash
"<python_path>" "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> [--align left|center] [--claude-verify]
"<python_path>" "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> --recursive [--max-depth N]
"<python_path>" "<SKILL_DIR>/scripts/math_upgrade.py" --space <KEY>
```

**关键参数：**
- `--align left`：左对齐（推荐默认，原生 mathblock + alignment=left），`--align center`：居中
- `--claude-verify` / `--no-claude-verify`：覆盖是否暂停等人工审核
- `--recursive` / `--no-recursive`：覆盖是否递归子页面
- `--no-auto-update`：仅生成 debug 文件，不更新页面
- `--stop-on-error`：批量模式遇错即停（默认遇错继续，末尾汇总失败页面）

---

## 独立运行（不用 Claude）

脚本直接从 `scripts/config.py` 读取配置，无需任何环境变量或 Claude 依赖：

```bash
python scripts/md_import.py my_doc.md --space ES
python scripts/math_upgrade.py --page-id 12345 --align left
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

---

## 调试日志

```
<SKILL_DIR>/debug/
├── import/              # md_import
│   └── YYYYMMDD_HHMMSS/before_upload.html
└── upgrade/             # math_upgrade
    └── YYYYMMDD_HHMMSS/{before,after}.html + info.txt
```

超过 `max_size_mb` 阈值自动清理最旧的时间戳目录。

---

## 文件结构

```
confluence-tools/
├── SKILL.md
├── KNOWN_ISSUES.md             # 已知问题与修复记录（排查改脚本时读取，按需追加）
├── config.example.py           # 配置模板（提交 git，含占位符和注释）
├── scripts/
│   ├── config.py               # 真实配置（不提交，从 example 拷贝）
│   ├── common.py               # 公共：配置加载、HTTP 重试、页面收集
│   ├── debug_utils.py          # 公共：日志清理
│   ├── md_import.py            # Markdown → Confluence
│   ├── math_upgrade.py         # 数学公式升级
│   └── selftest.py             # 离线自测（不依赖服务器，mock 配置运行）
└── debug/
    ├── import/
    └── upgrade/

忽略规则（.gitignore）位于仓库根目录，见 `skills/.gitignore`
```

---

## 自进化：从错误中学习

排查需修改 `scripts/*.py` 的问题时，**先读取 `KNOWN_ISSUES.md`** 查是否已知问题及修复方案。

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

**修改 `scripts/*.py` 后，必须运行 `selftest.py` 且全部用例通过**，才能算修改完成：

```bash
"<python_path>" "<SKILL_DIR>/scripts/selftest.py"
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

- 脚本启动时从 `scripts/config.py` 自给自足，不依赖 Claude 注入任何环境变量或上下文
- 不能引入只在 Claude 对话中才有的状态（如"上次用户说的那个值"）
- CLI 参数只用于临时覆盖，不能把一个原本可选的参数变成必须由 Claude 传的
- 新增依赖的 Python 包必须在配置向导中检测，或脚本启动时明确提示缺失
- **向导禁止预填**：配置向导阶段禁止自动读取历史配置文件（settings.json、settings.local.json、旧会话日志等）预填任何参数，所有值只来自用户输入（Python 路径按"先问后找"规则执行）
- **公共代码必须抽取**：两个及以上脚本共用的逻辑放入 `common.py` 或新建共用模块，禁止复制粘贴
- **配置模板必须同步**：新增配置项时，同时更新 `config.example.py` 和 SKILL.md 的配置向导

### 凭据安全

**真实凭据只能存在于 `scripts/config.py`。** 该文件已通过 `.gitignore` 排除提交。

`config.example.py`（提交 git）使用占位符示例，**禁止**出现真实 Token、密码、内网地址。

不固化的一次性问题：网络不通、磁盘满、Token 过期、Markdown 内容自身错误。
