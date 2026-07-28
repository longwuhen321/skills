# Codex Skills

本目录存放 Codex Skills。每个 Skill 通过独立目录中的 `SKILL.md` 定义适用场景、执行流程和约束。

## 自定义 Skills

### `md2zh`

将英文 Markdown 文档翻译为自然、准确的简体中文，同时保留原有 Markdown 结构、代码、LaTeX、链接、图片路径和引用。

- 调用方式：`$md2zh <Markdown 文件路径>`，或明确要求使用 `md2zh` Skill。
- 输出文件：默认在源文件旁生成 `<原文件名>_zh.md`，不会覆盖源文件。
- 主要特点：统一技术术语，并校验标题、代码块、表格、图片、链接和公式结构。

### `web2md`

将网页转换为可在 Typora 中打开的 Markdown 文档，下载网页图片到本地 `.assets` 目录，并将数学公式转换为 LaTeX。

- 调用方式：`$web2md <URL>`、`/web2md <URL>` 或 `@web2md <URL>`。
- 仅在显式调用时触发；普通消息中出现 URL 不会自动执行。
- 主要特点：复用项目 Python 环境、调用共享转换脚本，并对公式、表格和本地图片引用进行检查。

## 目录结构

```text
skills/
├── md2zh/
│   └── SKILL.md
├── web2md/
│   ├── SKILL.md
│   └── scripts/
├── .gitignore
└── README.md
```

## Skill 定义

每个 `SKILL.md` 的 YAML 头部至少包含名称和用途说明：

```yaml
---
name: example-skill
description: 说明该 Skill 的能力以及应在何时使用。
---
```

正文用于描述具体工作流、输入输出、验证步骤和必须遵守的限制。
