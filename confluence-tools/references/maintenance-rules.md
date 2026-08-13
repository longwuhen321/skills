# Confluence Skill 维护规则

## 强制读取条件

准备修改本 skill 的 `SKILL.md`、`references/*.md`、`scripts/*.py` 或
`config.example.py` 时，必须在任何编辑前完整读取本文件和相邻目录的
`SKILL_MODIFICATION_STANDARD.md`。读取后先向用户说明：
“已读取维护规则，将先提交方案审批，再修改和验证。”

若修改 `scripts/*.py`，还必须直接完整读取 `script-development-rules.md`；
若排查 bug，直接读取 `KNOWN_ISSUES.md`；若进行重构、扩展或新增能力，直接读取
`OPTIMIZATION_SUMMARY.md`。不要依赖参考文件的二级转述代替这些原文。

## 修改前

1. 检查工作树，保留用户已有改动，不清理无关文件。
2. 输出方案并取得用户批准，至少说明：
   - 是否有现有模式可复用；
   - 最小改动方案以及是否新增/删除文件；
   - 脚本、配置、文档、测试的影响范围；
   - 可机械验证的完成条件。
3. 修改脚本前运行 `scripts/test/selftest.py` 建立基线；bug 修复先增加能复现问题的测试。
4. 两个以上脚本共用的逻辑放入 `common.py` 或共享模块，不复制粘贴。

## 脚本恢复

- 发现关键脚本缺失或损坏时先报告，并在任何恢复前取得用户批准。
- 先检查 `git status`：已跟踪且显示删除的文件可从当前版本恢复；若只能从近期提交
  恢复，必须说明可能丢失未提交修改的风险。
- 未跟踪文件无法通过 git 恢复；被忽略的真实 `scripts/config.py` 也不视为可恢复文件，
  只能依据用户提供的信息或配置向导重新创建。
- 恢复时保留工作树内其他用户改动，不清理、不覆盖无关文件。

## 修改后门禁

按实际改动执行：

```bash
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/test/selftest.py"
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/check_config_sync.py"
"<python_path>" -X utf8 "<SKILL_DIR>/scripts/package_check.py" --root "<隔离候选目录>"
```

- `scripts/*.py`：完整 selftest 必须全绿；同步脚本开发规则中的实际防御机制。
- `config.example.py`：同步真实 `config.py` 和配置说明；配置门禁必须通过。
- `SKILL.md` / `references/*.md`：全文核对，无失效路径、二级路由或规则冲突。
- 全部文本保持 LF；执行 `git diff --check`。
- 四个页面入口执行 `python -X utf8 <script> --help` 并返回 0。
- 发布检查必须在隔离候选目录进行，候选不得包含真实 `config.py`、`logs/`、缓存、
  版本控制目录、链接或真实凭据。

## 文档路由约束

- `SKILL.md` 是唯一入口，保留全局红线和直接路由表。
- 每类任务只能有一个主要 workflow 文档；条件性附加文档必须在入口路由表直接列出。
- workflow 顶部必须包含“强制读取条件”和用户可见的读取回执文本。
- 不依赖 A → B → C 的多级引用；执行所需文件必须由 `SKILL.md` 直接路由。
- 核心安全约束允许在入口和 workflow 中有意重复；参数全集、示例和目录树只保留一个权威位置。
- 路由完整性测试必须检查所有引用存在、强制措辞存在、入口核心红线存在。

## 测试能力矩阵

| 能力 | 验收位置 |
|---|---|
| 配置无副作用解析、六组键和类型同步 | `test_config_sync.py`、`TestSafeConfigAndPackaging` |
| 导入页面消歧、409 和附件失败 | `TestImportLookupAndConflict` |
| 导入原件直传、完整修复副本、两级复审和哈希门禁 | `TestMdImport`、`TestMdPreflight` |
| 树计划唯一 ID 和断点恢复 | `TestTreePlanAndResume` |
| 数学零残留与过期确认 | `TestMathSafety` |
| 目录宏转换矩阵和参数校验 | `TestTocUpgrade` |
| 导出分页、附件与安全路径 | `TestExportSafety` |
| 四入口 UTF-8 help | `TestCliSurface` |
| 文档强制路由和引用完整性 | `TestSkillDocumentationRoutes` |

测试必须把 `SKILL_ROOT` 和日志目录指向临时目录，不读写真实 `logs/`。

## 真实环境验证清理

- 只创建用户授权范围内、唯一命名的测试页面和附件，并立即记录精确 ID。
- 删除前重新核对 ID、标题、空间和父子关系；只删除记录的测试 ID。
- 页面使用 `DELETE {confluence_url}/rest/api/content/{page_id}` 删除；附件随页删除。
- 删除一次性验证脚本，不留在 `scripts/`。
- 若账号只能移入回收站而无永久清除权限，如实报告 403 和回收站状态；不得扩大权限或
  操作其他页面。

## 日志与文件结构

```text
confluence-tools/
├── SKILL.md
├── KNOWN_ISSUES.md
├── OPTIMIZATION_SUMMARY.md
├── config.example.py
├── references/
│   ├── configuration-guide.md
│   ├── md-import-workflow.md
│   ├── md-import-preflight-rules.md
│   ├── math-upgrade-workflow.md
│   ├── toc-upgrade-workflow.md
│   ├── md-export-workflow.md
│   ├── maintenance-rules.md
│   └── script-development-rules.md
├── scripts/
│   ├── config.py
│   ├── common.py
│   ├── md_import.py
│   ├── md_preflight.py
│   ├── math_upgrade.py
│   ├── toc_upgrade.py
│   ├── md_export.py
│   └── test/
└── logs/
    ├── intermediate/
    ├── _archive/
    ├── import/
    ├── upgrade/
    ├── toc_upgrade/
    └── export/
```

日志清理由 `debug_utils.py` 统一控制；总大小超过 `max_size_mb` 或已识别的时间戳目录
超过 `keep_recent` 时，从最旧开始删除但至少保留最近 N 个。恢复树导入时跳过启动清理。
导入预审日志只允许报告与 manifest，不存放供 AI 修改的 Markdown 候选文件；修复副本必须
位于上传对象同级，不得放入 `logs/`。

## 记录与凭据

- bug 修复建议记录到 `KNOWN_ISSUES.md`；重构、扩展或新增能力建议记录到
  `OPTIMIZATION_SUMMARY.md`。是否记录由用户决定；确认后先读文档顶部模板，按时间倒序插入。
- 日期使用系统当前日期，不硬编码。
- 脚本必须从 `scripts/config.py` 独立运行，不依赖对话状态。
- 真实凭据只能存在于被忽略的 `scripts/config.py`；`config.example.py` 只放占位符。
