# 多文件目录树翻译工作流

## 强制读取条件

用户指定目录且扫描得到至少两个可翻译 Markdown 任务，并且
`md2zh_config.tree_translation=true` 时，**必须在创建任务前完整读取本文件**。
单文件或仅含一个可翻译 Markdown 的目录不读取。

## 模式判定

| 输入 | 判定 | 默认输出 |
|---|---|---|
| 单个 `.md` | 单文件流程 | 源文件同级 `<stem>_zh.md` |
| 目录内只有一个可翻译 `.md` | 退化为单文件流程 | 该文件同级 `<stem>_zh.md` |
| 目录内至少两个可翻译任务 | 树形流程 | 源目录旁 `<根名>_zh/` 镜像树 |

`output_dir` 非空时，单文件输出到该目录，树形镜像根建在该目录下。
`tree_translation=false` 且目录含多个任务时，停止并请用户指定单个文件，不自行翻译整树。

## 扫描规则

递归扫描目录并忽略 `.assets/`：

- 每个含 Markdown 的文件夹最多形成一个任务。
- 有与文件夹同名的 `.md` 时优先选它。
- 没有同名文件但只有一个 `.md` 时选择该文件。
- 同一文件夹有多个候选且无唯一同名文件时跳过并报告，不猜测。
- 扫描结果先列出源文件、相对路径和跳过原因，再开始翻译。

## 树级术语表

在树形任务根创建一份共享 `glossary.json`，格式固定为：

```json
{"schema_version": 1, "terms": {"Source term": "统一译法"}}
```

先扫描全树建立初始术语表。每个文件执行 `extract` 时都传入同一路径：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" extract "<源.md>" `
  --state "<state.json>" --blocks "<blocks.json>" --project-root "<树根>" `
  --glossary "<树级任务根>/glossary.json"
```

每个新块和新文件开始前重新读取术语表；新术语通过 `update-glossary` 合并。
冲突译法默认拒绝，只有完成上下文复核后才使用 `--replace`。

## 逐文件执行

按稳定的扫描顺序，对每个任务独立执行完整单文件流程：

```text
extract → summarize → 模糊决策（若有）→ plan-blocks
→ 翻译/validate-block → merge-blocks → render → verify
→ AI 终检/mark-reviewed → copy-assets → cleanup-run
```

- 每个文件使用独立 task-id、state、manifest、candidate 和 review；只共享术语表。
- 单文件失败不回滚其他文件，也不跳过其自身未完成门禁。
- 每个文件完成后记录成功、失败或跳过，整树结束时统一汇总。

## 镜像输出

```text
<输出根>/<根名>_zh/
├── <页面A>.md
├── <页面A>.assets/
├── <子目录>/
│   ├── <子目录>.md
│   └── <子目录>.assets/
└── <页面B>.md
```

- 保持源目录层级；树形输出中的 Markdown 与源文件同名，`_zh` 只用于镜像根。
- 每个源旁 `.assets` 用 `copy-assets` 复制到对应镜像目录，保持源 stem 名称。
- 目标 Markdown、镜像根或 assets 已存在且内容边界不明确时停止；禁止静默覆盖或合并。
- 源文件和源 assets 始终只读。

## 执行注意事项

- state、blocks、run、summary、review 与 candidate 都放在各自 task-id 目录内。
- 含弯引号的 Windows 路径用 PowerShell 单引号与变量拼接，避免双引号解析错误。
- 只使用 `scan_visible.py` 与 `apply_translations.py` 处理块表面，不为每个文件编写临时脚本。
- 最终汇总必须列出全部任务及未解决失败；部分成功不得描述为整树完成。
