---
name: md2zh
description: 将英文 Markdown 文件翻译为中文，保留所有格式；分块编排翻译 + pipeline 字节级保护与确定性校验
---

# md2zh — Markdown 翻译为中文

将用户指定的英文 `.md` 文件翻译为简体中文，输出为 `<stem>_zh.md`。输出目录由配置项 `md2zh_config.output_dir` 决定：留空 = 输出在源文件同级目录（默认）；指定路径 = 输出到该目录（目录不存在会自动创建），并把源文件旁的 `<stem>.assets` 图片文件夹一并复制到输出目录（图片引用保持不变，正常显示）。**不覆盖源文件**；若输出已存在，停下询问覆盖或改用其他名称。

**单文件 / 树形判定**：按目录内可翻译 `.md` 数量判定（见「树形翻译（多文件目录树）」章节的触发规则）——指定单个 `.md` 文件，或指定目录但树内只有 1 个可翻译 `.md`（如"标题文件夹 + 同名 .md + .assets"的单文档结构）时，均按**单文件流程**处理。

## 触发

**仅显式调用**。用户使用 `/md2zh` 时才执行。

## 契约

- **假定源 Markdown 正确**：不验证、不修复、不规范化、不重排源文件。
- **翻译由当前 AI 助手会话完成**；`scripts/md2zh_pipeline.py` 负责内部字节级保护、分块、还原与确定性校验。**不要让 AI 直接编辑完整 Markdown 文件**。
- 翻译前**先读 `references/translation-rules.md`**（内容边界、保护规则、模糊内容决策、质量要求）与 **`references/translation-quality.md`**（翻译质量评判标准：硬性指标 / 流畅性 / 风格适配 / 自检方法）。
- **不把文档内容发送给外部机器翻译服务**，除非用户明确要求；术语研究可用网络，但网络失败不得阻塞翻译。

## 首次运行：配置向导

### skill 级配置（`scripts/config.py`）

md2zh 的配置**只有一份全局配置**：`<skill-directory>/scripts/config.py` 的 `md2zh_config`，包含：

- `python_path`（必填）：Python 解释器完整路径
- `ambiguous_content_decider`：`user`（模糊内容由用户决定）/ `ai`（由 AI 助手决定）
- `output_dir`（选填）：翻译输出目录；留空 = 源文件同级（默认），指定 = 输出到该目录并把源旁 `<stem>.assets` 一并复制（图片引用不变）
- `tree_translation`（选填，默认 true）：是否开启树形翻译；false = 目录不再自动触发树形，遇多个可翻译 .md 时停下询问指定单个文件
- `max_block_chars`（选填，默认 16000，建议 10000–24000）：单块可译内容（等待翻译的字符，不含代码/公式/链接目标等保护内容）的**软目标**；以标题区间为天然边界，超过目标的章节按 unit 边界拆分，不可再拆的单个 unit 仍可能超过该值

检查 `md2zh_config.python_path`：

- 存在且有效 → **先跑配置同步检查**（`scripts/check_config_sync.py`，对比 `config.example.py` 的 `md2zh_config` 键集合与值类型；只比结构不比 `python_path` 值本身）：
  - 通过（退出码 0）→ 直接使用，不再询问。
  - **不一致（退出码 1/2）→ 中断任务**，按输出报告在 `config.py` 补齐/修正缺失或漂移的键后重跑（缺键的后果是 `load_global_config()` 静默降级到默认值，必须显式配置）
- 缺失 / 损坏 / 路径失效 → 走配置向导（规则见下）：
  1. **先问用户** Python 解释器路径；用户不给才允许自动扫描（`where python`、Anaconda 目录、系统 PATH，优先选可用环境）
  2. 扫描候选 → 展示给用户确认；无结果 → **中断任务**（无 Python 无法执行 pipeline，必需项）
  3. 确认后由 pipeline `configure` 子命令写入 `scripts/config.py`（模板 `config.example.py`，gitignore 排除；`--python-path` 缺省时自动探测**当前解释器**），**写入后立即跑 `scripts/check_config_sync.py` 复核**——确认没有缺键（含向导未覆盖的新增键）才继续

配置读取只接受模块说明字符串和 `md2zh_config = {...}` 等**字面量赋值**：脚本用 AST 定位分组并通过 `ast.literal_eval` 解析，不导入配置模块。配置中出现 import、函数调用、属性写入、控制流或其他副作用语句时直接拒绝，且不会执行这些代码。

> **禁止预填**：向导阶段不自动读取历史配置/旧会话日志预填任何值。

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" configure --decider user --python-path "<python>"
```

> pipeline 会拒绝用不同解释器执行后续阶段——**全程使用同一个 Python**。

## 脚本完整性检查（每次执行前）

确认 `scripts/md2zh_pipeline.py` 存在。缺失 / 损坏时**不要直接重写**——先向用户报告并确认是否需要恢复，确认后按 git 恢复（注意恢复的是最近提交版本，之后未提交改动会丢失）。

另确认 `scripts/config_literal.py` 与 `scripts/check_config_sync.py` 存在（安全配置解析与第一步门禁依赖）。

## 执行流程

### 1. 提取与计划

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" extract "<源.md>" --state "<state.json>" --blocks "<blocks.json>" --project-root "<项目根>"
```

- 内部保护段是重建元数据，**不要暴露或翻译** state 文件。
- 单文件流程不传 `--glossary`：pipeline 在 `state.json` 同级创建或复用 `glossary.json`。树形流程传 `--glossary "<树级任务根>/glossary.json"`，令所有页面复用同一术语表；文件必须是 `{"schema_version": 1, "terms": {"源术语": "统一译法"}}`。
- 分块以**标题区间为天然边界**：章节（含无标题头部）不超 `max_block_chars` 就整块翻译（上下文完整）；超过软目标的章节在 unit 边界（段落/行）拆分，pipeline 不会切开不可分 unit，因此单块仍可能超过软目标。普通段落合并为多行 unit（段落内可自由断句），列表项、嵌套列表项与引用行保持逐行 unit。

**结构摘要（主流程，AI 分块依据）**——extract 后生成摘要 md，AI 通读并**确认采用 pipeline 的默认分块方案**后再进入分块：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" summarize "<state.json>" "<summary.md>"
```

- 摘要内容：标题树（到 3 级）+ 每章节可译字符数 + 代码/公式块行号范围（保护区间，不参与翻译）+ 默认分块方案表（✅ 目标内 / ⚠️ 超软目标）

### 2. 模糊内容决策

翻译前审查每个 `ambiguous_region`：

- `user`：把分组列表一次性展示，收集 translate/protect 决策
- `ai`：依据完整 region、章节与相邻可见上下文决定；只选 pipeline 建议的精确子串并给出简短理由

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" record-decisions "<state.json>" "<decisions.json>"
```

`decisions.json` 必须恰好覆盖 state 中的每个 region ID 一次（不得缺失、重复或出现未知 ID）：

```json
{
  "decisions": [
    {
      "region_id": "unknown-0001",
      "decision": "protect",
      "reason": "保留未知指令载荷",
      "selected_spans": []
    },
    {
      "region_id": "unknown-0002",
      "decision": "translate",
      "reason": "该载荷是读者可见文字",
      "selected_spans": [
        {"source_start": 120, "source_end": 138, "text": "Exact source text"}
      ]
    }
  ]
}
```

若存在 `translate` 决策，命令输出中的 `extra_translations_skeleton` 会列出 `unknown-xxxx:<span-index>` 键。把该对象保存为 UTF-8 `extra-translations.json`，将每个空字符串替换为对应中文译文；`protect` 决策不产生额外翻译键。

命令输出片段：

```json
{
  "passed": 2,
  "rejected": 0,
  "extra_translations_skeleton": {
    "translations": {
      "unknown-0002:0": ""
    }
  }
}
```

可直接复制其中的 `extra_translations_skeleton` 对象为文件并填写译文：

```json
{
  "translations": {
    "unknown-0002:0": "精确源文字的中文译文"
  }
}
```

### 3. 分块运行

AI 审阅摘要并确认采用默认方案后执行：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" plan-blocks "<state.json>" "<run-directory>"
```

`<run-directory>` 必须在 `<skill-directory>/logs/intermediate/<task-id>/run/` 下。manifest 记录每块的输入/输出/接受结果/源哈希/状态/尝试次数；重跑保留已接受块。

### 4. 逐块翻译（AI 助手）

1. 先读全部 `*.input.txt` 与 state 输出指向的 `glossary.json`，复用已确认术语；发现新术语时，把增量写成 `{"terms": {"源术语": "统一译法"}}`，再运行：

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" update-glossary "<state.json>" "<术语增量.json>"
   ```

   已有术语出现不同译法时命令默认拒绝；只有完成上下文复核并明确要替换时才追加 `--replace`。每个后续块和树内后续文件都重新读取同一 `glossary.json`。
2. **使用当前 AI 助手会话翻译**，不启动嵌套子代理/独立模型会话（丢失共享上下文、增加开销）。
3. 一次翻译一个完整块表面：
   - 每行 `@@MD2ZH:SEG:block-....:....@@` **原样保留且顺序不变**；SEG 行后的内容可占**多行**（段落级 unit）
   - 只翻译标记后的内容；段落内可**自由断句、换行、重排语序**（物理行数不受限）
   - **不得引入空行**（`\n\n` = 拆段，段落边界保持）；译文首尾不得有换行
   - 译文任何一行不得以 `#` `>` `-` `+` `*` 数字列表等**块级标记开头**（逐行校验）
   - 每个 `@@MD2ZH:PROTECT:...@@` 标记恰好保留一次
   - 不加注释、JSON 包装、代码围栏或多余行
4. **用 UTF-8 直接把译文写入块的 `*.output.txt`**——不要通过 PowerShell/Bash 管道、`Add-Content`、here-string 传输译文。若文件工具不可用（如沙箱限制无法直写目标盘），可用 `.NET WriteAllText`（UTF-8 无 BOM）直写，同样禁止管道/`Add-Content` 传输；编码正确性由 `validate-block` 闸门把关。

### 5. 逐块验证

先立即验证第一块，通过后再继续其余块：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" validate-block "<state.json>" "<manifest.json>" block-0001
```

- 这是编码与契约闸门。某块失败只改该块 manifest 条目；**初始尝试 + 最多 2 轮修正**，绝不因单块失败重启已接受块或重跑整篇。

### 6. 合并、渲染与校验

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" merge-blocks "<state.json>" "<manifest.json>" "<translations.json>"
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" render "<state.json>" "<translations.json>" "<candidate.md>"
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" verify "<state.json>" "<translations.json>" "<candidate.md>"
```

- `merge-blocks` 由 pipeline 重建内部 ID 映射，AI 不产生大 JSON 映射。仅存在 `translate` 模糊决策时，在上面的 merge 命令末尾追加 `--extra-translations "<extra-translations.json>"`；没有时保持原命令。pipeline 要求额外翻译键与已接受的 translate spans 完全一致且译文非空。
- `merge-blocks`、`render`、成功的 `verify` 会把各自产物路径与 SHA-256 写入任务根 `completion.json`；重跑前序阶段会自动撤销过期的后续阶段标记。
- render 把渲染结果写入传入的 `<candidate.md>`（中间产物）；**最终文件位置由 AI 读 `md2zh_config.output_dir` 放置**——留空 = `<stem>_zh.md` 与源文件同级；指定 = `<目录>/<stem>_zh.md`（目录不存在自动创建）。
- 源旁存在 `<stem>.assets` 时，render 后用 `copy-assets` 复制到输出目录（保持源 stem 命名，md 内图片引用不变；不复制会导致图片无法显示）。源和目标 assets 是同一路径时安全 no-op；不同路径的目标 assets 已存在时拒绝静默合并或覆盖，先由用户处理目标冲突：

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" copy-assets "<源.md>" "<输出.md>"
```

- 按 `references/translation-quality.md` 的评判标准复核完整译文（硬性错误 / 流畅性 / 风格适配 / 自检）；只改受影响的块输出，重新 `validate-block ... --replace-accepted` 后重合并/重渲染/重校验。

### 7. AI 终检（翻译完成后的质量闸门）

render 输出后、清理前，**AI 通读完整译文**（含长文档每个一级标题下至少完整读一遍），对照 `references/translation-quality.md` 四章逐项检查：硬性错误（数字/术语/漏译增译）、流畅性（翻译腔/“的的的/被被被”）、风格适配、自检（屏蔽原文测试——仅凭中文能否完整理解）。

- 检查结果写入 `<skill-directory>/logs/intermediate/<task-id>/review.md`（问题清单：位置 + 类型 + 处理；无问题也记录已通读达标）
- 发现问题 → 定位受影响块 → 改 `output.txt` → `validate-block ... --replace-accepted` → 重 merge → `render ... --allow-overwrite` → verify → 重读复查，**循环到干净**。`--allow-overwrite` 只允许覆盖既有 candidate；pipeline 仍拒绝把源文件作为 render 输出。
- 复查干净后显式写入 AI 终检完成标记；该命令要求 `verify` 已成功，且把 `review.md`、译文映射和候选文件哈希绑定：

  ```powershell
  & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" mark-reviewed "<state.json>" "<translations.json>" "<candidate.md>" "<review.md>"
  ```

### 8. 收尾

```powershell
& "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" cleanup-run "<manifest.json>"
```

- `cleanup-run` 必须同时确认所有块 accepted，以及 `merge`、`render`、`verify`、`review` 四个完成标记仍与当前文件哈希一致；缺失或标记后被修改均拒绝归档。
- 任务目录（`<task-id>/`）**归档移入 `<skill-directory>/logs/_archive/`** 而非删除（便于排查）。同名 task-id 已存在时追加唯一时间后缀，绝不覆盖或删除既有归档；共享树级术语表的当前快照作为归档内 `glossary.json` 保存。
- 保留决策日志、源文件、最终输出。

## 树形翻译（多文件目录树）

**触发（单文件 / 树形判定）**：按**可翻译 `.md` 任务数**判定，不只看"是否目录"——任何 AI 数一下即可，判定确定、可复现：

| 用户指定 | 判定 | 流程 | 输出 |
|---|---|---|---|
| 单个 `.md` 文件 | 单文件 | 单文件流程（上文） | `<stem>_zh.md`，与源 .md 平级 |
| **目录**，树内可翻译 `.md` **只有 1 个**（忽略 `.assets/`） | **单文件**（退化为单文件流程） | 同上 | `<stem>_zh.md`，与源 .md 平级（`.assets/` 仅作图片源） |
| **目录**，树内可翻译 `.md` **≥ 2 个** | 树形 | 本树形流程 | `<根名>_zh/` 镜像树 |

> 表格的"输出"列是**默认位置**；`md2zh_config.output_dir` 指定时，单文件输出到该目录、树形镜像树根建在该目录下（见「首次运行：配置向导」）。`md2zh_config.tree_translation=false` 时目录不再自动触发树形（≥2 个可翻译 .md 停下询问指定单个文件）。

- 任务数口径与「流程 1 扫描」同规则：扫描目录树（含子目录，忽略 `.assets/`），每个含 .md 的文件夹 = 1 个任务（同名 md 优先、无同名取唯一、多个 md 跳过并提示）。
- 指定目录时，若树内只有 1 个可翻译 `.md`，且目录结构是"标题文件夹 + 同名 .md + .assets"（如单个文档抓取的输出结构）→ 按**单文件模式**处理（任务数 = 1，退化为单文件流程）；只有多页面收集结构（任务数 ≥ 2）才走树形镜像输出。单文件场景目录结构示例：

  ```
  <输出根>/
  ├── <标题>.md                # 与该文件夹同名的 md（待翻译内容）
  └── <标题>.assets/           # 该页面的图片文件夹（仅作图片源，不参与任务数统计）
  ```

**流程**：

1. **扫描目录树**：每个含 .md 的文件夹 = 一个翻译任务（源 = 与文件夹**同名**的 .md；无同名取唯一 .md；多个 .md 时跳过并提示；`.assets/` 忽略）。
2. **树级术语表**：在本次树形翻译的任务根创建一份共享 `glossary.json`；先扫全树所有页面建立初始术语表，随后每个页面的 `extract` 都追加 `--glossary "<同一 glossary.json>"`，并通过 `update-glossary` 持续复用和补充。
3. **逐文件夹执行完整 pipeline 流程**：对每个任务跑 extract → summarize（AI 审阅摘要并确认默认分块）→（模糊决策）→ plan-blocks → 逐块翻译 → validate-block → merge-blocks → render → verify → AI 终检（review.md）→ mark-reviewed → cleanup-run（每文件独立 task-id、独立状态与产物，共享树级 glossary；归档保存当时快照）。
4. **输出镜像树**：默认在源目录旁新建 `<根名>_zh/`；`md2zh_config.output_dir` 指定时镜像树根建在该目录下。保持原层级结构，每文件夹内生成**与源同名的 `.md`**，并把该文件夹的 `.assets` 一并复制到镜像对应位置（`copy-assets` 逐文件执行，图片引用不变）；`_zh` 后缀命名仅用于单文件模式。**不修改源文件**。输出示例：

   ```
   <输出根>/<根名>_zh/
   ├── 页面A.md                # 与文件夹同名的 md（页面内容）
   ├── 页面A.assets/           # 该页面的图片文件夹（一并复制，引用不变）
   ├── 子文件夹/               # 子页面层级
   │   ├── 子文件夹.md
   │   └── 子文件夹.assets/
   └── 页面B.md
   ```
5. **失败隔离**：单文件失败不影响其他；结束汇总成功 / 失败 / 跳过列表。

**规则**：树形翻译 = 单文件流程的循环编排，pipeline 脚本无特殊模式；每个文件独立遵守单文件契约（UTF-8 直写、契约保留、产物清理）。

**翻译执行注意事项（实战沉淀）**：
- 每个 SEG 内容段**必须有译文**（空译文会被 validate-block 拒绝）；无可见文本的块（全 PROTECT）直接复制 input 为 output
- 译文**避免引入 Markdown 语法字符**（`\`、`*`、`[` `]` 等，会被判为 introduced syntax）；引号用中文引号直接书写，不要经 shell 转义
- 段落内可自由断句换行，但**不得引入空行**（拆段被拒）、任何一行不得以块级标记（`#` `>` `-` 等）开头
- 可见文本提取用 `scan_visible.py`，译文写回用 `apply_translations.py`（不要手写临时脚本）
- state/blocks 等中间产物放**任务目录内**（`<skill-directory>/logs/intermediate/<task>/`），否则 `cleanup-run` 会因 state 不在任务目录而拒绝清理
- 含弯引号（`“”`）的目录名在 PowerShell 双引号字符串中会被误解析，路径拼接用单引号

## 配置（config.py）

- 模板：`<skill-directory>/config.example.py`（占位符 + 中文注释）
- 真实配置：`<skill-directory>/scripts/config.py`（gitignore 排除，禁止提交）
- 分组：`md2zh_config` — `python_path`（必填）+ `ambiguous_content_decider`（user / ai）+ `output_dir`（选填，留空 = 源文件同级）+ `tree_translation`（选填，默认 true）+ `max_block_chars`（选填，默认 16000，正整数软目标，建议 10000–24000）
- 全局 `scripts/config.py` 由 pipeline `configure` 子命令管理（首次配置向导写入）
- 同步强制：首次运行时先跑 `scripts/check_config_sync.py`——`config.py` 与 `config.example.py` 的 `md2zh_config` **键集合与值类型**不一致（缺键 / 多余键 / 类型不符）即**中断任务**，补齐后再继续（只比结构，不比 `python_path` 占位符 vs 真实路径等值）
- `configure` 支持 `--output-dir <目录>` / `--tree-translation true|false` / `--max-block-chars <N>` 临时覆盖（缺省保留现值，不会清空已配置值）
- `configure` / `extract` 支持 `--config <path>` 临时指定配置文件（默认 `<skill>/scripts/config.py`；selftest 用其隔离真实配置，正常流程不使用）
- `extract` 支持 `--tools-root <path>` 临时指定日志根目录（默认 `<skill>/logs`；仅 selftest 隔离用，正常流程不使用）
- `extract` 支持 `--glossary <path>` 指定树级共享术语表；不传则使用 `state.json` 同级的任务术语表

## 测试（本地）

`scripts/test/selftest.py` 离线黑盒测试 pipeline（配置写入、分块保护、端到端 roundtrip、契约违规拒绝）：

```powershell
& "<python>" "<skill-directory>/scripts/test/selftest.py"
```

**修改 `scripts/*.py` 后必须运行并全绿。**

发布前对**待发布暂存目录**运行只读检查（不要把安装态含真实 `config.py` / `logs` 的目录直接当作发布包）：

```powershell
& "<python>" "<skill-directory>/scripts/package_check.py" --root "<待发布目录>"
```

退出码 0 = 通过，1 = 发现禁项，2 = 用法或读取错误。检查器先按路径拒绝并跳过 `config.py`、`logs`、缓存和禁用目录，不读取其内容；随后只扫描允许的文本配置文件，拒绝非占位 Token 或其他敏感赋值。

## 容错与安全

- **失败隔离**：单块翻译/验证失败只改该块 manifest 条目，初始尝试 + 最多 2 轮修正；已接受块不重启，绝不因单块失败重跑整篇。
- **断点续传**：`plan-blocks` 重跑保留已接受块（提取计划不变时）；中断后可恢复。
- **结构摘要**：`summarize` 输出标题树/章节字符统计/默认分块方案，AI 审阅并确认采用默认方案。
- **决策日志**：所有 accepted / rejected / retried 决策持久化在 `<skill-directory>/logs/decision_logs/*.jsonl`，任务完成后保留（诊断与规则改进用）。
- **编码安全**：译文必须 UTF-8 直接写入 `*.output.txt`，禁止经 shell 管道/heredoc 传输（防编码错乱）；`validate-block` 是编码与契约闸门。
- **凭据安全**：真实配置只存在于 `scripts/config.py`（gitignore 排除）；`config.example.py` 用占位符，禁止出现真实路径/密钥。不把文档内容发送给外部机器翻译服务。
- **安全解析与发布**：配置只按 AST 字面量解析，不执行 Python 配置代码；发布暂存目录必须通过 `package_check.py`，禁项只按路径报告且不读取内容。

## 任务产物与清理

```
<skill-directory>/logs/
├── decision_logs/           # 决策日志 *.jsonl（完成后保留）
├── intermediate/
│   └── <task-id>/           # 单次任务目录（含 state/blocks、run/、summary.md、review.md、translations.json、candidate.md）
│       ├── glossary.json    # 单任务术语表，或共享树级术语表的归档快照
│       └── completion.json  # merge/render/verify/review 哈希绑定完成标记
└── _archive/                # 已完成任务的只增归档；同名追加唯一后缀
```

- `cleanup-run` 把**本任务目录** `<task-id>/` 移入 `_archive/`，要求所有块 accepted、四阶段完成标记有效，且传入精确的 `<task-id>/run/manifest.json`。
- **残留任务清理**：`intermediate/` 中**非本次任务**或**已确认弃用**的任务目录，任务结束后人工清理（删除，或移入 `_archive/` 便于排查）；`cleanup-run` 拒收的 unfinished 任务（未完成块）需先处理未完成块，或确认弃用后人工删除——不留残留，避免 `intermediate/` 日积月累堆积。
- **保留**：全部决策日志、源文件、非本任务数据、最终输出。
- **历史遗留**：旧版项目级 `{项目根}/.md2zh_tools/config.json` 不再读取，可直接删除。
- 真实环境验证产物（临时文件）用后即清。

## 文件结构

```
md2zh/
├── SKILL.md
├── KNOWN_ISSUES.md             # 已知问题与修复记录（排查改脚本时读取，按需追加）
├── OPTIMIZATION_SUMMARY.md     # 优化交接总结（skill 自我优化前读取、优化后追加）
├── config.example.py           # 配置模板（提交 git，占位符）
├── logs/                        # 日志产物根（gitignore 排除）：decision_logs/ + intermediate/ + _archive/
├── references/
│   ├── translation-rules.md    # 翻译规则（内容边界/保护/模糊内容/质量）
│   └── translation-quality.md  # 翻译质量评判标准（翻译前必读：硬性/流畅性/风格/自检）
└── scripts/
    ├── config.py               # 真实配置（不提交，从 example 拷贝）
    ├── config_literal.py       # AST + literal_eval 安全配置解析（不执行配置代码）
    ├── check_config_sync.py    # 配置同步强制检查（首次运行时门禁）
    ├── package_check.py        # 待发布目录只读敏感文件/值检查
    ├── md2zh_pipeline.py       # 分块/保护/校验 pipeline（纯标准库 Python）
    ├── scan_visible.py         # 扫描块 input.txt 列出可见文本段（供翻译）
    ├── apply_translations.py   # 按 SEG 映射生成 output.txt（译文写回，支持多行段）
    └── test/
        ├── selftest.py         # 离线黑盒测试（改脚本后必须全绿）
        ├── test_config_sync.py # 配置结构检查测试（只用临时 fixture）
        └── test_packaging.py   # 发布检查测试（只用临时 fixture）
忽略规则（.gitignore）位于仓库根目录：`md2zh/scripts/config.py` 与 `md2zh/logs/` 被排除。
```

## 自进化：从错误中学习

**修改本 skill 任何文件（`SKILL.md` / `references/*.md` / `scripts/*.py` / `config.example.py`）之前，先读 `<skill-directory>/../SKILL_MODIFICATION_STANDARD.md`**（skill 修改执行标准：书写规范、修改前流程、验证与收尾自查）。仅正常使用本 skill（不涉及修改）时不读。

**仅在排查问题（可能修改 `scripts/*.py`）或需要优化时才读 `KNOWN_ISSUES.md`**；正常翻译流程不预读。

**分工**：
- **bug 修复** → 记录到 `KNOWN_ISSUES.md`（现象 / 根因 / 修复 / 排查方法）
- **优化 / 重构 / 扩展** → 记录到 `OPTIMIZATION_SUMMARY.md`

**skill 自我优化时**：
- **优化前**：先读 `OPTIMIZATION_SUMMARY.md` 对齐历史改动与遗留事项
- **优化后**：将本次优化**追加记录**（含日期，取系统当前时间 `Get-Date -Format "yyyy-MM-dd"`，禁止硬编码）
- **⚠️ 写入 `OPTIMIZATION_SUMMARY.md` / `KNOWN_ISSUES.md` 前必须读该文档的头部说明（追加模板 / 维护约定），按文档约定插入**——例如 `OPTIMIZATION_SUMMARY.md` 的约定是「追加操作、插入位置在顶部（最新条目紧随模板之后、时间倒序）」，**禁止直接 `cat >>` 追加到文件末尾或只模仿尾部格式**

每次修复非一次性错误后向用户提出固化方案（改脚本 / 记 KNOWN_ISSUES / 更新 SKILL.md / 都改 / 不改）。

**收尾自查**：本次会话是否改动了 `scripts/*.py`、`SKILL.md`、`config.example.py`、`references/*.md`？
- 有 → **向用户提出记录建议**：列出改动项，按类别给出建议（bug 修复 → `KNOWN_ISSUES.md`；优化/重构/扩展 → `OPTIMIZATION_SUMMARY.md`），**是否记录、记录到哪由用户决定**——确认后按约定补记（日期取系统时间、按文档头部约定插入），用户选择不记录则跳过
- 无 → 跳过

### 实现前检查点（必过）

**在写任何代码之前，必须输出方案并让用户确认。** 方案至少覆盖以下三点：

1. **参考现有模式** — 项目中已有类似的东西吗？风格、格式、命名是怎样的？新方案是否与之一致？不一致的话，有什么充分理由？
2. **最小改动原则** — 有没有更简单的方案？在现有文件上改还是新建？新建的话，已有相关文件要不要删除（避免残留）？
3. **影响范围** — 改动会影响哪些文件？脚本、配置、文档是否同步更新？

检查通过后才能开始实现。

### 回归测试（必过）

**修改 `scripts/*.py` 后，必须运行 `scripts/test/selftest.py` 且全部用例通过**，才能算修改完成：

- 全绿 = 分块/保护/校验逻辑未破坏，改动可固化
- 有红 = 修改引入回归，先修复再继续

### 真实环境验证的清理（必过）

**使用真实文档做验证时（实际翻译一篇 md 走完整流程），验证完成后必须清理产物**：

- 临时任务目录（`<skill-directory>/logs/intermediate/<task-id>/`）→ 用 `cleanup-run` 归档（移入 `_archive/`）
- 验证用的临时文件 → 删除，不留在 scripts/ 目录

不留任何验证残留，向用户报告验证结果时说明已清理。

### 固化的核心约束

- **修改 `scripts/*.py` 后必须跑 selftest 全绿**
- **公共代码必须抽取**：两个及以上脚本共用的逻辑放入共享模块，禁止复制粘贴
- **新增/改动配置项时同步更新** `config.example.py` 与本文档的配置说明（旧 `config.py` 缺新键会被首次运行的 `check_config_sync.py` 门禁拦下，属预期行为）
- **脚本保持独立运行能力**：pipeline 从自身参数/配置自给自足，不依赖 AI 注入环境变量或上下文；CLI 参数只用于临时覆盖
- **向导禁止预填**：配置向导阶段禁止自动读取历史配置/旧会话日志预填任何值
- **恢复被删脚本前先征得用户确认**（见"脚本完整性检查"）
