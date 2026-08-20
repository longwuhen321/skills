# md2zh 脚本开发规则

## 强制读取条件

**修改或新增 `scripts/*.py` 前必须完整读取本文件**，并同时读取入口直接路由的
维护规则与对应历史记录。正常翻译流程不读取。修改后按实际实现同步本文件，
运行完整 `scripts/test/selftest.py`，全部通过才算完成。

## 防御性设计

| 机制 | 位置 | 必须保持的行为 |
|---|---|---|
| 字面量配置解析 | `config_literal.py` / `load_global_config` / `check_config_sync.py` | 只接受普通配置字典字面量；拒绝导入、调用、注解赋值、控制流和副作用，不重新引入 `exec` |
| 配置同步门禁 | `check_config_sync.py` | 比较模板与真实配置的键集合和值类型；不一致以 1/2 退出，禁止静默默认值继续 |
| 同一解释器 | `configure_project` / `ensure_state_runtime` | 配置、提取和后续阶段使用同一 Python；state 绑定解释器，运行时不匹配即拒绝 |
| 原子写入 | `write_bytes_atomic` / `write_json_atomic` | 配置、state、manifest、译文映射和完成标记不以半写状态替换目标 |
| 源哈希与分块指纹 | `extract` / `plan_blocks` / `state_block_surface` | state、manifest、输入块绑定源 SHA-256 与计划指纹；源或计划变化时拒绝复用旧结果 |
| SEG 表面契约 | `translation_block_surface` / `parse_block_surface` | SEG 行必须原样、顺序不变；每段译文非空，无空白段、错位标记或尾部额外内容 |
| PROTECT 完整性 | `validate_translated_template` | 每个保护标记恰好一次，成对标记顺序和嵌套不交叉，未知标记不得残留 |
| Markdown 语法防注入 | `validate_no_introduced_syntax` | 译文不得增加危险标记、模板语法或块级 Markdown；不要放宽为仅检查首行 |
| 单块失败隔离 | `validate_block` / manifest | 未接受块最多初始尝试加两轮修正；已接受块不重跑，显式 `--replace-accepted` 才能修订 |
| 完整合并 | `merge_blocks` | 所有块 accepted、unit ID 完整唯一；额外翻译与 accepted spans 键集合完全一致 |
| 确定性渲染 | `deterministic_render` / `verify_file` | 按源区间替换、保持 BOM 与行尾风格；候选必须逐字节等于重新渲染结果且无保护标记 |
| 输出防覆盖 | `render_file` / `copy_assets` | render 永不写源文件，覆盖候选需显式许可；目标 assets 已存在时拒绝合并或覆盖 |
| 四阶段完成门禁 | `completion.json` / `mark_reviewed` | merge、render、verify、review 依次绑定 state 与产物哈希；前序重跑使后续标记失效 |
| 安全归档 | `cleanup_run` | state/run 必须位于当前 task-id；全部块与四阶段有效、源未变后才归档；同名追加唯一后缀，不覆盖、不裁剪 |
| 术语表冲突保护 | `update_glossary` / `cleanup_run` | 术语冲突默认拒绝；共享术语表快照与任务内既有快照不同时拒绝覆盖 |
| 测试隔离 | `--config` / `--tools-root` | selftest 只使用临时配置与临时日志根，不读取或污染真实 `config.py` / `logs` |
| 发布敏感检查 | `package_check.py` | 路径优先拒绝真实配置、logs、缓存、链接和凭据；拒绝路径不读取内容 |
| 文档路由回归 | `test_documentation_routes.py` | 检查入口不超过 250 行、七份参考均由入口直接引用并声明完整读取、核心翻译红线与读取回执保留、上位标准可达且隐式调用仍关闭 |

## 明确不要做的事

- 不让 AI 或辅助脚本直接编辑完整 Markdown；翻译只通过块表面和 pipeline 重建。
- 不把 SEG/PROTECT 校验降级为计数近似、正则替换或“尽量保留”。
- 不在源哈希、计划指纹或完成哈希不匹配时自动刷新并继续。
- 不为了提高通过率放宽空译文、空行、块级标记、未知 ID 或额外翻译检查。
- 不用 shell 管道、here-string、`Add-Content` 传输译文；保持 UTF-8 直接文件写入。
- 不让 `--allow-overwrite` 覆盖源文件；它只用于 AI 复检后重写同一 candidate。
- 不合并已存在的目标 `.assets`，也不覆盖同名归档。
- 不让单块失败重启整篇或丢弃其他 accepted 块。
- 不把外部机器翻译、网络服务或嵌套模型会话加入默认 pipeline。
- 不在测试中使用真实配置或 skill 的真实日志目录。

## 修改与测试纪律

- 修改共享机制时同步所有调用方，避免复制相同解析、哈希或标记逻辑。
- 新增 CLI 子命令或参数时同步 `--help`、入口/参考、配置模板（若适用）及黑盒测试。
- 修复 bug 时先加入可失败的最小回归，再实现修复；测试覆盖正例和拒绝路径。
- 完整运行 `scripts/test/selftest.py`，不能只跑新增用例。
- 发布前在隔离暂存目录运行 `package_check.py`，确认运行源码和测试夹具均无敏感值。
