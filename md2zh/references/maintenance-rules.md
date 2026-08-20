# md2zh 维护与发布规则

## 强制读取条件

准备修改 `SKILL.md`、`references/*.md`、`scripts/*.py`、`config.example.py`、
测试或维护记录时，**必须在改动前完整读取本文件**。正常翻译流程不读取。

同时由入口直接读取项目级执行标准：
[`../../SKILL_MODIFICATION_STANDARD.md`](../../SKILL_MODIFICATION_STANDARD.md)。

## 维护路由

| 任务 | 改动前必须读取 |
|---|---|
| 文档结构、流程或配置模板优化 | 本文件、项目级执行标准、`../OPTIMIZATION_SUMMARY.md` |
| bug 排查或修复 | 本文件、项目级执行标准、`../KNOWN_ISSUES.md` |
| 修改或新增 `scripts/*.py` | 上述对应记录，以及 `script-development-rules.md` |
| 改动配置键 | 本文件、项目级执行标准、`configuration-guide.md` |

所有必读文件都必须由 `SKILL.md` 直接路由；不得依赖参考文件之间的二级发现。

## 修改前清单

1. 确认用户明确要求修改共享 skill；正常翻译中不得自行修改。
2. 读取路由命中的全部文件及记录文档头部维护约定。
3. 检查目标 `git status` 与关键文件哈希；保留用户已有改动，不清理无关工作树。
4. 运行修改前完整 `scripts/test/selftest.py`、`check_config_sync.py` 与 skill 校验，
   记录用例数和退出状态。
5. 列出目标、最小文件范围、不变边界和验收标准，取得用户确认后实施。

## 实施约束

- 每一处改动都必须追溯到已确认目标；不顺手重构相邻代码或文档。
- `SKILL.md` 只保留触发、主 pipeline、硬门禁和直接路由；条件性细节放一级参考。
- 参考文件声明“强制读取条件”；超过 100 行时在顶部提供目录。
- 修改脚本前完整读取 `script-development-rules.md`，修改后按实际机制同步该文件。
- 新增或改变配置键时同步 `config.example.py`、配置指南、入口摘要与测试。
- 不改变 SEG/PROTECT、字节级渲染、完成哈希、源文件只读及无覆盖归档红线。
- 文本保持 UTF-8 与 LF；真实路径、凭据、文档正文和真实配置不得进入发布文件。

## 修改后验证

| 检查 | 要求 |
|---|---|
| `scripts/test/selftest.py` | 完整离线套件全绿；测试脚本或运行脚本改动均重新运行 |
| `scripts/check_config_sync.py` | 退出码 0，真实配置与模板 5 个键及类型同步 |
| skill 快速校验 | frontmatter、名称、描述与目录结构有效；Windows 使用 UTF-8 模式 |
| 文档路由测试 | 行数上限、直接引用、读取条件、核心红线与显式调用开关通过 |
| `git diff --check` | 无空白错误或冲突标记 |
| LF 与本地链接 | 所有变更文本无 CRLF，Markdown 本地目标均存在 |
| 隔离发布检查 | 不含真实配置、logs、缓存、凭据或 reparse point；`package_check.py` 返回 0 |

文档变更后全文通读一次，确认入口自包含、示例使用占位符、命令顺序正确且没有
相互矛盾的重复规范。仅文档架构变更时，运行脚本、配置模板与真实配置应保持不变。

## 记录与产物

- bug 修复记录到 `KNOWN_ISSUES.md`；优化、重构或扩展记录到 `OPTIMIZATION_SUMMARY.md`。
- 写记录前读取头部模板；日期通过系统当前时间取得，最新条目插在模板后方。
- 历史条目只记录当时事实，不因现状改变而重写；需要纠正时新增覆盖说明。
- 测试使用临时 `--config` 与 `--tools-root` 隔离真实配置和 logs。
- 真实验证的 task-id 目录必须完成 `cleanup-run` 归档；其他临时文件用后清理。

## 隔离发布

只复制允许发布的文件到全新临时目录，不复制 `scripts/config.py`、`logs/`、缓存、
环境文件或真实验证产物，然后执行：

```powershell
& "<python>" "<skill-directory>/scripts/package_check.py" --root "<待发布目录>"
```

退出码 `0` 才能交付；`1` 表示发现禁项，`2` 表示用法或读取错误。
清理暂存目录前必须确认解析后的绝对路径位于预期临时根内。
