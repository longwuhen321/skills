# Confluence 工具配置向导

## 强制读取条件

当 `scripts/config.py` 不存在、配置同步门禁失败，或用户要求查看、补齐、修改配置时，
必须在任何探测、写配置或页面操作前完整读取本文件。读取后先向用户说明：
“已读取 `references/configuration-guide.md`，将按配置来源和逐项询问规则执行。”

## 初始化门禁

1. 检查关键脚本是否存在：`md_import.py`、`md_preflight.py`、`math_upgrade.py`、
   `toc_upgrade.py`、`md_export.py`、`common.py`、`config_parser.py`、
   `debug_utils.py`、`dependency_check.py`、`check_config_sync.py`、`package_check.py`。
   缺失或损坏时不要直接重写；先向用户说明，并在用户确认后按 git 状态恢复跟踪文件。
2. Python 路径确定后运行：

   ```bash
   "<python_path>" -X utf8 "<SKILL_DIR>/scripts/dependency_check.py"
   ```

   必须能实际导入 `requests`、`markdown2`、`beautifulsoup4`（`bs4`）和
   `markdownify`。缺依赖时中断；安装前展示命令并取得用户批准。
3. `config.py` 已存在时运行：

   ```bash
   "<python_path>" -X utf8 "<SKILL_DIR>/scripts/check_config_sync.py"
   ```

   门禁比较六个配置分组的键集合和值类型，不比较值；退出码 1/2 时中断，
   按报告补齐后重新检查。配置使用 AST + `ast.literal_eval` 解析，拒绝函数调用、
   导入和其他副作用代码。

## 配置来源与交互规则

- 配置向导中所有值只来自用户本次输入；禁止读取或预填历史配置、旧会话日志、
  备份文件或其他 skill 副本。
- 先直接询问 Python 解释器路径。只有用户明确表示“不提供、请帮我找”后，才能扫描
  `where python`、Anaconda、PATH 等候选；找到后必须展示给用户选择，不能自动决定。
- Confluence 地址、PAT Token 和导入默认空间是必需项；缺一项即中断，且不创建半成品。
- 用户名、默认页面、默认父级等选填项必须明确询问是否留空。
- 使用普通文本逐项一问一答，不使用选项式提问工具承载 URL、Token、路径等开放输入。
- 配置确认后写入 `scripts/config.py`；真实凭据只能存在于该文件，不能写入模板、文档或日志。

## 六组配置项

### `common_config`

1. `python_path`：Python 解释器完整路径。
2. `confluence_url`：服务器基础 URL，必需，不以 `/` 结尾。
3. `confluence_user`：选填，仅记录，不参与认证。
4. `confluence_token`：PAT，必需；运行时可由 `CONFLUENCE_TOKEN` 环境变量覆盖。
5. `heading_math_mode`：`literal` 或 `mathinline`；默认 `literal`。
6. `toc_target_macro`：导入与目录升级共用的目标宏，`easy_heading` 或 `toc`；
   默认 `easy_heading`。`toc_upgrade.py --target` 可临时覆盖；旧配置中的
   `toc_upgrade_config.target_macro` 仅作为兼容回退读取。

### `import_config`

1. `space`：默认导入空间，必需。
2. `math_align`：`left` 或 `center`，默认 `left`。
3. `default_parent_id`：新建页面的默认父页面 ID；留空则建在空间根。
4. `default_page_name`：默认标题；留空取 Markdown 文件名。
5. `tree_import`：是否允许 `--dir` 树导入，默认 `false`。
6. `materialize_root_page`：是否把 `--dir` 传入的根文件夹实体化为根页面，默认 `false`。
   开启后优先使用同名 `.md`；缺少时创建空的 Confluence 页面而不补写本地文件，
   根目录内其他 `.md` 各自作为该根页面的直接子页面。
7. `fix_hierarchy`：`confirm`、`auto` 或 `off`，默认 `confirm`。
8. `toc_enabled`：是否按 `common_config.toc_target_macro` 自动插入目录宏，默认 `true`。
9. `toc_min_headings`：H2～H6 达到多少个时插入目录宏，默认 `4`。
10. `preflight_review`：上传前只读审核原件；有问题时创建并验证同级完整修复副本，默认 `true`。

### `upgrade_config`

1. `default_page`：数学升级默认页面 ID，可留空。
2. `space`：数学升级默认空间，可留空。
3. `math_align`：`left` 或 `center`，默认 `left`。
4. `auto_update`：验证后是否自动提交，默认 `true`。
5. `ai_verify`：是否等待人工确认，默认 `false`。
6. `recursive`：有页面 ID 时是否默认递归，默认 `true`。
7. `max_depth`：递归最大深度，`0` 表示不限。

### `toc_upgrade_config`

1. `default_page`：目录宏转换默认页面 ID，可留空。
2. `space`：空间范围默认值；建议留空，避免误触空间批量写入。
3. `recursive`：是否默认处理全部后代，默认 `false`；不设置深度上限。
4. `auto_update`：验证后是否自动提交，默认 `true`。
5. `ai_verify`：是否等待人工确认，默认 `false`。
6. `macro_parameters`：供导入或升级新建 Easy Heading 使用，不覆盖已有 Easy 宏参数：
   - `titleExpandClickable`：`true` / `false`，默认 `true`；
   - `hiddenEditedFlag`：插件内部标记，固定建议 `true`；
   - `navigationExpandOption`：展开策略，默认 `expand-all-by-default`；
   - `useNavigationHiddenMode`：悬停显示侧栏，默认 `true`；
   - 可选 `selector`、`wrapNavigationText`、`navigationTitle`。
   未知键、非法布尔值或非法枚举必须在远端写入前失败。

### `export_config`

1. `output_dir`：默认 `confluence_export`，支持相对或绝对路径。
2. `recursive`：页面导出是否默认包含后代，默认 `true`。
3. `space`：默认导出空间，可留空。

### `debug_config`

1. `max_size_mb`：日志总大小阈值，默认 `50`。
2. `keep_recent`：至少保留的最近时间戳目录数量，默认 `20`。

## 运行期规则

- 后续执行直接读取 `scripts/config.py`，不重复询问；只有用户主动要求时才用 CLI 覆盖。
- 取值优先级：用户显式 CLI 参数 > `config.py` > 代码默认值。
- 401、403、连接超时或配置门禁失败时，停止页面操作并引导重新配置。
- `config.py` 被 `.gitignore` 排除，git 无法恢复；丢失后必须重新运行配置向导。
