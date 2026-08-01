# confluence-tools 优化总结（2026-08-01）

> 本文档是本次大优化的工作交接摘要：记录做了什么、当前状态、以及协作风格，
> 供后续会话快速对齐，避免重复探索。

## 一、本次优化范围

### 代码层（5 个脚本 + 39 个测试用例）

| 文件 | 核心改动 |
|------|---------|
| `common.py` | `build_block_template`（left/center 宏模板）、`request_with_retry`（429/5xx 指数退避重试 + timeout）、`collect_space_pages`（分页收集）、`load_config`（CONFLUENCE_TOKEN 环境变量覆盖） |
| `md_import.py` | 公式对齐配置（`import_config.math_align` + `--align`）、标题内存匹配（绕开 CQL title bug）、版本号流程修复（原硬编码 version=2 必 409）、409 自动重试、占位符随机 token、base64 图片跳过、`\*` 控制序列归一化、图片失败汇总报告 |
| `math_upgrade.py` | 原生 `mathblock + alignment=left`（替代 mathinline+`\displaystyle` hack）、`_apply_alignment` 幂等（防版本虚涨）、span 剥壳保留内容（防 XHTML 400）、`_check_xhtml_balance` 标签配对校验（剔除 CDATA/注释防误报）、`_sanitize_latex`（`\*`→`*`）、批量遇错继续 + `--stop-on-error`、拉取失败兜底重试 |
| `debug_utils.py` | 未改动 |
| `selftest.py` | 39 个离线用例（mock 配置与网络），修改脚本后必须全绿 |

### 文档层（四方同步）

SKILL.md（配置向导规则收紧、对齐配置、容错与安全、自进化流程）／ KNOWN_ISSUES.md（8 条问题记录）／ README.md（confluence-tools 章节）／ config.example.py（math_align）／ 根目录 .gitignore（迁移 + `/config.py` 防误提交）。

## 二、真实环境验证结果

- ES 空间 204/204、ALG 空间 50/50、新空间 111/111 全量升级通过
- mathblock `alignment=left` 在 Confluence 9.2.1 服务器实测支持
- 多轮真实页面导入/升级/修复验证，全部闭环

## 三、过程中修复的 bug 序列（按时间）

1. **硬编码 version=2** → 更新已有页面必 409 → 返回真实版本号
2. **全局删 `<span>`** → 破坏编辑器格式 → 只删 math class
3. **stdout 双重 wrap** → 多模块 import 时 print 崩溃 → 幂等化
4. **`$PWD / $OLDPWD` 误识别为公式** → 正则三规则（开头 $ 后禁空白、闭合 $ 前禁空白、内容禁 `<>`）
5. **`\*` 未定义控制序列** → `_sanitize_latex` 归一化
6. **span 嵌套删除 → XHTML 400** → 剥壳保留内容 + 禁嵌套匹配
7. **XHTML 检查器 CDATA 误报**（`<mmc::Irlock>` 当标签）→ 剔除 CDATA/注释
8. **`_apply_alignment` 非幂等 → 版本虚涨**（TECS v2→v6 内容不变）→ 已 left 跳过

## 四、协作风格（本会话遵循的工作方式）

1. **先方案后动手**：写代码前输出方案（含默认值/影响范围），用户确认后才实施；方案被否就重出
2. **任务清单跟踪**：多步任务用 TaskCreate 列清单，逐步推进，不半途遗忘
3. **测试先行**：所有代码改动必须 selftest 全绿才交付；测试也随功能同步补
4. **真实环境验证**：代码改完在真实服务器验证（建测试页/跑批量），**验证产物（测试页、临时脚本）用后即清**，不留残留
5. **证据驱动排查**：遇到问题先拉数据/日志定位根因（如 debug 目录判断失败阶段），不猜
6. **文档同步**：代码、配置模板、SKILL.md、KNOWN_ISSUES、README 保持一致；发现的问题记录到 KNOWN_ISSUES（现象/根因/修复/排查方法）
7. **诚实报告**：做过什么、没做什么、验证到什么程度，如实说明；修复后明确告诉用户需要验证的部分
8. **安全优先**：token 不落盘不打印；含真实凭据的文件不读全文；删除/批量操作被安全机制拦截时停下向用户解释，等明确授权
9. **一次性脚本即用即删**：临时验证脚本跑完删除，不留在 scripts/
10. **配置驱动设计**：脚本从 config.py 自给自足，无参执行；配置项改文件即生效

## 五、遗留事项

- **草稿清理**：Confluence 9.2.1 REST API 无法删除页面草稿（尝试 5 种方式均失败，草稿是编辑器私有机制）。"未发布更改"标记的草稿无害，关闭浏览器标签页随会话清理；顽固残留需管理员后台处理
- **P3 未做**（有意不做的）：atlassian-python-api 依赖、批量并发处理
- **配置向导**：SKILL.md 已收紧规则（必需项缺失即中断、禁止预填历史配置、先问后找），新会话跑 `/confluence-tools` 时应遵守

## 六、当前环境速查

- Confluence：9.2.1（http://192.168.0.253:8090），PAT Bearer 认证
- Python：`D:/path/to/python/python.exe`（有 requests/markdown2）
- 空间：ES（204 页）、ALG（50 页）、数学知识空间（111 页）
- 测试命令：`"<python>" scripts/selftest.py` → 39 用例全绿
