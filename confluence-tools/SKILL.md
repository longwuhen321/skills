---
name: confluence-tools
description: Confluence 工具集：Markdown 导入页面、数学公式升级等
---

# confluence-tools — Confluence 工具集

将 Markdown 文件导入 Confluence 页面，或升级已有页面的数学公式格式。

## 触发

**仅显式调用**。用户使用 `/confluence-tools` 时才执行。

## 首次运行：配置向导

如果以下环境变量未设置，先走配置流程：

1. **Python 环境路径** → `CONFLUENCE_PYTHON`
   - 自动扫描常见路径，列出已有 `requests`/`markdown2` 的环境
   - 用户选一个或手动输入
2. **Confluence 地址** → `CONFLUENCE_URL`（如 `http://192.168.0.253:8090`）
3. **用户名** → `CONFLUENCE_USER`（用于显示，不参与认证）
4. **PAT Token** → `CONFLUENCE_TOKEN`
5. **默认空间 Key** → `CONFLUENCE_SPACE`
6. **Debug 日志设置**（可跳过，使用默认值）：
   - `CONFLUENCE_DEBUG_MAX_MB`（默认 50）
   - `CONFLUENCE_DEBUG_KEEP`（默认 20）

每项先展示当前值（如有），用户回车跳过沿用默认，输入新值则覆盖。

配置确认后写入 `C:/Users/<USER>/.claude/settings.local.json` 的 `env` 段，同时写入 Bash allow 规则避免后续执行确认：

```json
{
  "permissions": {
    "allow": [
      "Bash(<CONFLUENCE_PYTHON> *)"
    ]
  },
  "env": {
    "CONFLUENCE_URL": "...",
    "CONFLUENCE_TOKEN": "...",
    "CONFLUENCE_SPACE": "...",
    "CONFLUENCE_DEBUG_MAX_MB": "50",
    "CONFLUENCE_DEBUG_KEEP": "20"
  }
}
```

后续调用从 env 读取，不再询问。配置失效（401/403/连接超时）时提示用户重新配置。

## 子命令

配置完成后询问用户：

> 要做什么？
> 1. **导入 Markdown** — 将 .md 文件上传为 Confluence 页面
> 2. **升级数学公式** — 升级已有页面的 $...$ / $$...$$ 为原生宏

---

### 一、导入 Markdown（md_import）

**执行**：

```bash
"<CONFLUENCE_PYTHON>" "<SKILL_DIR>/scripts/md_import.py" "<md文件路径>" [--parent-id ID] [--page-name NAME] [--space KEY]
```

**流程**：
1. 用户指定 md 文件（可拖入或粘贴路径）
2. 询问：父页面 ID？（可选，回车跳过）
3. 询问：自定义页面标题？（可选，默认取文件名）
4. 询问：目标空间？（可选，回车用默认 `CONFLUENCE_SPACE`）
5. 执行脚本 → 输出结果（page_id / 更新版本号 / 错误信息）
6. 脚本自动处理：已存在→更新，不存在→新建

**脚本内部逻辑**：protect code → protect math → markdown2 → restore → convert macros → upload。
Step 5.5 自动清理 markdown2 包裹在块级元素外层的 `<p>` 标签。

---

### 二、升级数学公式（math_upgrade）

**单页模式**：
```bash
"<CONFLUENCE_PYTHON>" "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> [--align left|center] [--claude-verify]
```

**递归模式**（页面及其所有子页面）：
```bash
"<CONFLUENCE_PYTHON>" "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> --recursive [--max-depth N]
```

**空间模式**（整个空间所有页面）：
```bash
"<CONFLUENCE_PYTHON>" "<SKILL_DIR>/scripts/math_upgrade.py" --space <KEY>
```

**Claude 验证后确认更新**：
```bash
"<CONFLUENCE_PYTHON>" "<SKILL_DIR>/scripts/math_upgrade.py" --confirm latest
```

**关键参数说明**：
- `--align left`：左对齐（mathinline + \displaystyle），推荐默认值
- `--align center`：居中（mathblock 宏）
- `--claude-verify`：转换后暂停，等 Claude 读 debug 文件验证后再 `--confirm`
- `--no-auto-update`：只生成 debug 文件，不更新页面

**流程**：
1. 询问目标（页面 ID / 空间 Key / 递归）
2. 询问对齐方式（默认 left）
3. 执行脚本 → 输出统计（inline/block/latex 各转换多少处）
4. 若使用 `--claude-verify`：读 debug/before.html 和 after.html，逐项验证，确认后执行 `--confirm`

---

## 调试日志

所有 debug 文件统一存放在 skill 目录：

```
<SKILL_DIR>/debug/
├── import/              # md_import 的日志
│   └── YYYYMMDD_HHMMSS/
│       └── before_upload.html
└── upgrade/             # math_upgrade 的日志
    └── YYYYMMDD_HHMMSS/
        ├── before.html
        ├── after.html
        └── info.txt
```

超过阈值自动清理最旧的时间戳目录（阈值由 `CONFLUENCE_DEBUG_MAX_MB` / `CONFLUENCE_DEBUG_KEEP` 控制）。

---

## 脚本文件结构

```
<SKILL_DIR>/
├── SKILL.md
├── scripts/
│   ├── md_import.py      # Markdown → Confluence 导入
│   ├── math_upgrade.py   # 已有页面数学公式升级
│   └── debug_utils.py    # 调试日志清理（共用）
└── debug/
    ├── import/
    └── upgrade/
```

---

## 自进化：从错误中学习

每次执行过程中遇到 **非一次性错误**（脚本 bug、markdown2 行为变化、API 边界情况等），在修复并通过用户验证后，执行以下流程：

### 触发条件

满足以下任一条件时，向用户提出固化建议：

- 脚本执行报错，修改 `scripts/*.py` 后成功
- 上传后的页面渲染有问题，需调整脚本转换逻辑
- 发现新的边界情况并临时绕过
- Skill 的操作流程不够清晰导致用户困惑

### 执行步骤

1. **诊断** — 说明根本原因（如 "markdown2 的 codehilite 插件在 `<pre>` 和 `<code>` 之间插入了 `<span>`，导致正则失配"）
2. **修复** — 改脚本或调整执行方式，验证通过
3. **提出固化** — 向用户确认：

   > 问题已修复。需要我把这个修复固化到 skill 里吗？
   > - **修改脚本** — 更新 `scripts/*.py`，下次不会再踩这个坑
   > - **更新 SKILL.md** — 补充注意事项或调整操作流程
   > - **都改** — 两者都更新
   > - **不改** — 仅本次修复，不固化

4. **执行固化** — 按用户选择更新对应文件

### 什么不该固化

- 一次性环境问题（网络不通、磁盘满、Python 环境变动）
- 用户输入错误（路径写错、参数遗漏）
- 配置问题（token 过期、空间不存在）→ 应引导重新走配置向导
- 原 Markdown 文件自身的内容错误
