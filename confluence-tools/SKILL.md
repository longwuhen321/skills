---
name: confluence-tools
description: Confluence 工具集：导入 Markdown、升级数学公式、转换目录宏及导出页面。仅在用户显式调用 $confluence-tools 时触发，不因一般 Confluence 讨论自动触发
---

# confluence-tools — Confluence 工具集

面向 Confluence 9.2.1 Data Center（build 9109），使用 PAT Bearer 认证。支持：

- Markdown 单页或文件夹树导入；
- 页面数学公式升级；
- 原生目录宏与 Easy Heading Macro 双向转换；
- 页面或空间导出为 Typora 兼容 Markdown。

## 强制执行协议

1. 每次显式调用本 skill，先完整读取本 `SKILL.md`。
2. 根据下方路由表确定任务类型。
3. **在调用页面脚本、修改文件或连接服务器之前，完整读取路由表列出的全部文件。**
4. 读取后先向用户公开回执：说明本次任务类型、已读取的文件及将遵守的范围/安全规则。
5. 路由文件缺失、无法完整读取或规则冲突时停止操作并报告；不得凭记忆继续。
6. 不使用参考文件的二级转述代替入口列出的原文；条件性附加规则也由本表直接路由。

### 强制读取路由表

| 任务 | 操作前必须完整读取 |
|---|---|
| 首次配置、补齐或修改配置 | `references/configuration-guide.md` |
| Markdown 单页、树导入或 `--resume` | `references/md-import-workflow.md` |
| Markdown 导入且最终 `preflight_review=true` | `references/md-import-workflow.md` + `references/md-import-preflight-rules.md` |
| 数学公式升级或 `math_upgrade --confirm` | `references/math-upgrade-workflow.md` |
| 目录宏转换或 `toc_upgrade --confirm` | `references/toc-upgrade-workflow.md` |
| Markdown 导出 | `references/md-export-workflow.md` |
| 修改 `SKILL.md`、`references/`、`scripts/` 或配置模板 | `../SKILL_MODIFICATION_STANDARD.md` + `references/maintenance-rules.md` |
| 修改 `scripts/*.py` | 上一行全部 + `references/script-development-rules.md` |
| 排查并修复 bug | 维护规则 + `KNOWN_ISSUES.md`；涉及脚本时再读脚本开发规则 |
| 重构、扩展或新增能力 | 维护规则 + `OPTIMIZATION_SUMMARY.md`；涉及脚本时再读脚本开发规则 |

读取回执使用可核对的固定结构：

```text
任务类型：<配置/导入/数学升级/目录宏转换/导出/维护>
已完整读取：<路由表列出的文件>
本次范围：<页面、页面树、空间、目录或改动文件>
执行边界：<本任务最关键的写入与清理规则>
```

## 每次页面操作前的门禁

确认以下关键脚本存在：

```text
scripts/dependency_check.py   scripts/check_config_sync.py
scripts/md_import.py          scripts/md_preflight.py
scripts/math_upgrade.py       scripts/toc_upgrade.py
scripts/md_export.py          scripts/common.py
scripts/config_parser.py      scripts/debug_utils.py
```

缺失或损坏时不要直接重写；先报告，用户确认后才按 git 状态恢复跟踪版本。

读取 `common_config.python_path` 后运行：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/dependency_check.py"
```

必须能实际导入 `requests`、`markdown2`、`beautifulsoup4`（`bs4`）和
`markdownify`。缺依赖时中断；安装前展示命令并取得用户批准。

`scripts/config.py` 已存在时运行：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/check_config_sync.py"
```

门禁检查六个配置组的键集合和值类型；退出码 1/2 时中断，不能接受静默默认值降级。
`config.py` 不存在时按配置路由执行向导，不创建半成品。

## 功能路由

| 能力 | 范围 | 脚本 | 核心边界 |
|---|---|---|---|
| Markdown 导入 | 单页、文件夹树、恢复计划 | `md_import.py` | 原件只读预审；必要时完整修复副本；查询歧义不写 |
| 数学升级 | 单页、页面树、空间 | `math_upgrade.py` | 默认公式零残留；确认前复查源版本和哈希 |
| 目录宏转换 | 单页、完整页面树、空间 | `toc_upgrade.py` | 无源不注入；重复宏拒绝；已有目标宏保持原文 |
| Markdown 导出 | 单页、页面树、空间 | `md_export.py` | 全量分页；安全附件路径；空间每页一次 |

### Markdown 导入

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" "<md文件>" [--page-id ID] [--parent-id ID] [--page-name NAME] [--space KEY] [--force]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" --dir "<根文件夹>" [--plan-only] [--yes] [--force]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_import.py" --resume "<tree_plan.json>" [--yes] [--force]
```

核心红线：

- `--page-id` 精确定位；否则查询必须区分 `FOUND`、`NOT_FOUND`、`ERROR`。
- 只有 `NOT_FOUND` 可以新建；同名多候选、分页或 API 错误禁止猜测。
- 409 默认拒绝覆盖；只有用户明确要求并传 `--force` 才从最新版本重试一次。
- `preflight_review=true` 时先只读全量审核：全净直接上传原件；发现问题则在同级创建完整
  `<原名>__修复` 副本，只修改副本。问题文件全部通过后再全量审核副本。
- 修复副本重名必须询问覆盖、另起名称或取消；`__修复` 只作本地标识，不改变页面标题。
- `materialize_root_page=true` 时根文件夹必须成为页面；缺少同名 Markdown 时只创建空的
  Confluence 根页，不补写本地文件，根级其他 Markdown 作为其直接子页面。
- `[toc]` 与自动目录统一服从 `common_config.toc_target_macro`，已有原生或 Easy 目录时不重复插入。
- 最终审核对象与上传对象必须一致；远端写入前哈希变化时停止，日志只保存报告而不保存候选 Markdown。
- 导入后复盘审核项：通用修复按维护流程固化到脚本并补测试；个例先询问是否记入问题库。
- 页面、附件或树节点任一失败，整体命令返回非零。

### 数学公式升级

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --page-id <ID> [--recursive] [--max-depth N] [--align left|center]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --space <KEY>
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/math_upgrade.py" --confirm <debug目录|latest>
```

核心红线：

- 默认任何 `$...$`、`$$...$$` 或 latex 围栏残留均失败；容忍必须显式启用并报告位置。
- 转换幂等；无变化不 PUT、不增加版本。
- `--confirm` 重新拉取页面，源版本或正文 SHA256 变化时拒绝提交旧结果，不提供强制绕过。
- `left` 插入或替换唯一 alignment；`center` 删除已有 alignment。

### 目录宏双向转换

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --page-id <ID> --no-recursive [--target easy_heading|toc]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --page-id <ID> --recursive [--target easy_heading|toc]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --space <KEY> [--target easy_heading|toc]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/toc_upgrade.py" --confirm <debug目录|latest>
```

核心红线：

- 只有源宏时原位替换；两类宏各一个时删除非目标宏、保留目标宏原文。
- 两类宏都没有时跳过；任一类型超过一个时拒绝修改该页面。
- 已有 Easy Heading 参数不覆盖；新宏生成独立 UUID。
- `--recursive` 处理根页面及全部后代，不限制层级；空间范围每个 page ID 一次。
- 确认前复查源版本、源/结果哈希、XHTML 和目标宏数量。

### Markdown 导出

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py"
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py" --page-id <ID> [--recursive|--no-recursive] [--output <目录>]
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/md_export.py" --space <KEY> [--output <目录>]
```

核心红线：

- 无参数运行从 `export_config.default_page` 或 `export_config.space` 取默认范围；两者不能同时设置。
- 导出时省略 Confluence 原生 `toc` 和 Easy Heading 目录宏，不生成 Markdown 目录标记或宏注释。
- 含代码表格不得保留为会破坏 Markdown 渲染的 HTML：单列纯代码表拆成围栏，多列或混合表按行列标签纵向展开；纯文本表格继续使用 Markdown 表格。
- 页面、子页面和附件列表必须全量分页；请求错误不能返回截断结果。
- 空间模式每个页面导出一次，不对空间索引中的页面重复递归。
- 页面目录默认只用标题；同一导出层级标题冲突时，冲突组全部改用 `page ID_标题`，即时提示并在结束时汇总。附件只取 basename 并验证路径仍位于页面 assets 目录内。
- 附件下载失败必须保留说明、累计失败并令命令返回非零。

## 全局安全红线

- **范围不猜测**：用户指定页面、父级、空间或目录时按原范围执行；存在多种解释时先确认。
- **写入前验证**：配置、依赖、页面身份、版本和转换结果必须先通过对应门禁。
- **批量不误报**：允许保留部分成功结果，但任一未处理失败都使整体命令返回非零。
- **并发不覆盖**：除导入的显式 `--force` 单次重试外，不用旧内容覆盖新页面。
- **凭据不泄漏**：真实 Token 只存在于被忽略的 `scripts/config.py` 或环境变量；不打印、不复制到模板或日志。
- **XHTML 不破坏**：代码、宏、CDATA、属性和正文按各自转义层处理；转换不得跨结构吞内容。
- **真实测试最小化**：只创建唯一命名且明确授权的测试页，立即记录 ID；删除前核对 ID、标题、空间和父级，只删除测试 ID。
- **权限不扩大**：删除或 purge 被 403 拒绝时如实报告，不换账号、不扩大范围、不触碰其他页面。
- **临时产物清理**：一次性验证脚本用后删除；测试日志定向到临时目录。
- **网络失败可见**：429 遵从 `Retry-After` 并指数退避，最多重试 3 次；瞬时 GET 5xx
  可重试，写请求不因 5xx 自动重复；分页、响应或 JSON 错误必须失败。

## 配置与独立运行

脚本直接读取 `scripts/config.py`，不依赖 AI 对话状态。取值优先级：

```text
用户显式 CLI 参数 > scripts/config.py > 代码默认值
```

独立运行示例：

```bash
python -X utf8 scripts/dependency_check.py
python -X utf8 scripts/md_import.py my_doc.md --space ES
python -X utf8 scripts/math_upgrade.py --page-id 12345
python -X utf8 scripts/toc_upgrade.py --page-id 12345 --target easy_heading
python -X utf8 scripts/md_export.py --page-id 12345
```

## 日志

运行期产物统一位于 `<SKILL_DIR>/logs/`：

```text
intermediate/  _archive/  import/  upgrade/  toc_upgrade/  export/
```

`debug_config.max_size_mb` 默认 50，`keep_recent` 默认 20。脚本启动时调用统一清理器；
树导入 `--resume` 跳过启动清理，避免检查点被提前删除。

当前已知缺口：`toc_upgrade` 使用带微秒的时间戳目录，现有清理器尚未识别该格式；
该目录暂不受自动删除控制，修复时按 bug 维护流程处理。

## Skill 维护摘要

- 修改任何 skill 文件前，按路由读取维护标准并先提交方案给用户审批。
- 修改脚本前建立 selftest 基线；修改后完整 selftest、配置同步、LF、CLI 和隔离发布检查必须通过。
- bug 建议记录到 `KNOWN_ISSUES.md`；重构、扩展和新增能力建议记录到
  `OPTIMIZATION_SUMMARY.md`。是否记录由用户决定。
- 详细文件结构、测试矩阵、发布检查和真实验证清理流程见强制路由的
  `references/maintenance-rules.md`，不能跳过。
