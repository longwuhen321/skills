# 配置与 Python 环境指南

## 强制读取条件

首次配置、`scripts/config.py` 缺失或损坏、`python_path` 无效、
`check_config_sync.py` 非零退出，或需要改变配置键时，
**必须在继续翻译前完整读取本文件**。配置有效且同步检查通过时不读取。

## 配置模型

- 模板：`<skill-directory>/config.example.py`，只保存占位值和公开说明。
- 真实配置：`<skill-directory>/scripts/config.py`，由 `.gitignore` 排除，禁止发布。
- 唯一配置组：`md2zh_config`。配置只接受模块说明字符串及普通字面量赋值；
  `config_literal.py` 通过 AST 与 `ast.literal_eval` 读取，不执行配置代码。

| 键 | 含义 | 默认或约束 |
|---|---|---|
| `python_path` | 执行 pipeline 的解释器 | 必填；全任务必须使用同一解释器 |
| `ambiguous_content_decider` | 模糊内容由谁判定 | `user` 或 `ai` |
| `output_dir` | 最终输出目录 | `""` 表示源文件同级 |
| `tree_translation` | 多文件目录是否启用树形翻译 | `true` |
| `max_block_chars` | 每块可译字符软目标 | `16000`；正整数，建议 10000–24000 |

## 每次执行的配置门禁

1. 读取 `scripts/config.py`，确认文件可安全解析且 `python_path` 指向可运行解释器。
2. 使用该解释器执行：

   ```powershell
   & "<python>" "<skill-directory>/scripts/check_config_sync.py"
   ```

3. 按退出码处理：

   - `0`：键集合和值类型同步，继续。
   - `1`：存在缺键、多余键或类型漂移，按输出修正真实配置后重跑。
   - `2`：配置缺失、损坏或无法安全解析，进入配置向导。

同步检查只比较键集合和值类型，不比较模板占位路径与真实 `python_path`。
任何非零结果都是硬门禁；不得依赖 `load_global_config()` 的默认值降级继续翻译。

## 首次配置或修复向导

1. 先询问用户希望使用的 Python 解释器；用户未指定时才扫描 `where python`、
   Anaconda 环境与系统 PATH。
2. 展示候选并由用户确认。没有可用解释器时停止，不创建半成品配置。
3. 明确模糊内容判定方式，以及是否需要非默认输出目录、树形开关或分块软目标。
4. 使用用户确认的解释器执行；不要从旧会话、历史配置或日志预填任何值：

   ```powershell
   & "<python>" "<skill-directory>/scripts/md2zh_pipeline.py" configure `
     --decider user --python-path "<python>"
   ```

   需要覆盖默认值时追加 `--output-dir`、`--tree-translation true|false` 或
   `--max-block-chars <N>`。未提供的选项保留现值。
5. pipeline 会拒绝由不同解释器配置任务；配置完成后全程继续使用同一个 Python。
6. 写入后立即重跑 `check_config_sync.py`，仅退出码为 `0` 时继续。

## 配置边界

- `output_dir` 只决定最终文件放置位置；pipeline 的 `render` 仍先写任务候选文件。
- 最终输出已存在时必须停下询问，不因配置了目录就获得覆盖许可。
- `configure` / `extract --config` 与 `extract --tools-root` 只用于测试隔离或明确的
  临时覆盖；正常流程使用 skill 内真实配置和默认日志根。
- 新增、删除或改变配置键时，同步更新 `config.example.py`、本文件、入口摘要与测试。
- 不把真实路径、凭据或文档内容写进模板、发布包或维护记录。
