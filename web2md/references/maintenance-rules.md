# web2md 维护与发布规则

## 强制读取条件

准备修改 `SKILL.md`、`references/*.md`、`scripts/*.py`、`config.example.py`、
测试或维护记录时，**必须在改动前完整读取本文件**。正常抓取与审核不读取。

同时直接读取项目级执行标准：
[`../../SKILL_MODIFICATION_STANDARD.md`](../../SKILL_MODIFICATION_STANDARD.md)。

## 维护路由

| 任务 | 改动前必须读取 |
|---|---|
| 文档结构、流程或配置模板优化 | 本文件、项目级执行标准、`../OPTIMIZATION_SUMMARY.md` |
| bug 排查或修复 | 本文件、项目级执行标准、`../KNOWN_ISSUES.md` |
| 修改或新增 `scripts/*.py` | 上述对应记录，以及 `script-development-rules.md` |
| 改动配置键 | 本文件、项目级执行标准、`configuration-guide.md` |

所有引用都从 `SKILL.md` 直接路由；不要要求执行者先打开一个参考文件，再由它发现
另一个执行所需参考文件。

## 修改前清单

1. 确认用户明确要求修改共享 skill；正常转换中不得自行修改。
2. 读取对应维护路由中的全部必读文件及其头部维护约定。
3. 检查 `git status` 与目标文件哈希，保留用户已有改动，不清理无关工作树。
4. 运行修改前基线：完整 `scripts/test/selftest.py`、`check_config_sync.py`，
   并记录用例数与退出状态。
5. 向用户列出目标、最小改动范围、文件清单、不会改动的边界与验收标准，获得确认。

## 实施约束

- 每一处改动都必须能追溯到已确认目标；不顺手重构相邻内容。
- `SKILL.md` 只保留触发、主流程、硬门禁与直接路由；低频细节放一级
  `references/`，避免正文与参考双重维护。
- 参考文件写明“强制读取条件”或“按索引读取条件”；超过 100 行时提供目录。
- 可复用脚本只放 `scripts/`；两个及以上脚本共享逻辑抽到共享模块。
- 修改脚本前完整读取 `script-development-rules.md`，修改后按实际机制同步它。
- 新增或改变配置键时同步 `config.example.py`、`configuration-guide.md`、入口摘要与测试。
- 全部文本保持 UTF-8 与 LF；不使用会在 Windows 上隐式写出 CRLF 的方式改文件。
- 不写入真实路径、Token、密码或私有代理值；不读取或发布真实 `scripts/config.py`。

## 修改后验证

按风险从内到外执行，任一失败都修复并从受影响层重新运行：

| 检查 | 要求 |
|---|---|
| `scripts/test/selftest.py` | 全部离线测试通过；修改脚本时是硬门禁，文档改动也应完整运行 |
| `scripts/check_config_sync.py` | 退出码 0，真实配置与模板键及类型同步 |
| skill 快速校验 | frontmatter、名称、描述和目录结构有效；Windows 必要时以 Python UTF-8 模式运行 |
| 文档路由测试 | 入口行数上限、直接引用、读取条件及核心红线均通过 |
| `git diff --check` | 无尾随空白、冲突标记或空白错误 |
| LF 检查 | 所有新增与修改文本不含 CRLF |
| 隔离发布检查 | 暂存包不含真实配置、logs、缓存、密钥或 reparse point；`package_check.py` 退出码 0 |

文档变更后全文通读一次，确认入口自包含、示例使用占位符、命令可执行，且没有
相互矛盾的重复规范。若只改文档，不应产生运行脚本或配置值差异。

## 记录规则

- bug 修复记录到 `KNOWN_ISSUES.md`：现象、根因、修复、测试与排查方法。
- 优化、重构、扩展记录到 `OPTIMIZATION_SUMMARY.md`：范围、决策、验证与遗留项。
- 修改记录前先读文档头部模板；日期必须用系统当前时间取得。
- 按文档约定把最新条目插在模板之后，保持时间倒序；不要在文件末尾盲目追加。
- 历史描述已过时时保留原条目，并新增“覆盖说明”，明确当前事实与被覆盖条目。

## 隔离发布

只把允许发布的文件复制到全新的临时目录，不复制 `scripts/config.py`、`logs/`、
缓存、环境文件或真实验证产物，然后运行：

```powershell
& "<python路径>" "<skill-directory>/scripts/package_check.py" --root "{待发布目录}"
```

退出码 `0` 才能交付；`1` 表示发现禁项，`2` 表示目录或文件无法完整读取。
检查完成后验证临时路径确实位于预期临时目录内，再安全清理。
