# 配置与 Python 环境指南

## 强制读取条件

首次配置、`scripts/config.py` 缺失或损坏、`python_path` 无效、
`check_config_sync.py` 非零退出，或需要改动 `config.example.py` / 配置键时，
**必须在继续抓取前完整读取本文件**。配置已经有效且同步检查通过时不读取。

## 配置模型

- 模板：`<skill-directory>/config.example.py`，只放占位值与公开说明。
- 真实配置：`<skill-directory>/scripts/config.py`，由 `.gitignore` 排除，禁止发布。
- 唯一解释器来源：`web2md_config["python_path"]`。不要再用平台环境变量保存一份 Python 路径。
- 解析方式：`config_literal.py` 通过 AST 定位一项普通
  `web2md_config = {...}` 赋值，再用 `ast.literal_eval` 读取。导入、函数调用、
  带注解赋值、其他赋值及副作用语句均被拒绝。

当前配置键：

| 键 | 含义 | 默认或约束 |
|---|---|---|
| `python_path` | AI 助手执行脚本所用解释器 | 必填；必须指向可运行的 Python |
| `proxy` | requests 代理 | 空字符串表示自动读取环境变量；非空值优先；只支持 `http://` |
| `timeout` | 页面与图片请求超时秒数 | `30` |
| `collect_children` | 收集严格导航子/孙页面 | `false`；CLI 可覆盖 |
| `merge_paragraphs` | 合并段落源码硬换行 | `false`；CLI 可覆盖 |
| `table_formula_inline` | 表格内显示公式改为行内公式 | `true`；CLI 可覆盖 |
| `page_nav` | 为父页面追加本地 Sub-pages 导航 | `true`；CLI 可覆盖 |

## 每次执行的配置门禁

1. 读取 `scripts/config.py`，确认文件可解析且 `python_path` 指向可运行解释器。
2. 使用该解释器执行：

   ```powershell
   & "<python路径>" "<skill-directory>/scripts/check_config_sync.py"
   ```

3. 按退出码处理：

   - `0`：键集合和值类型全部同步，继续。
   - `1`：缺键、多余键或类型漂移，按输出修正真实配置后重跑。
   - `2`：文件缺失、语法损坏或无法安全解析，进入配置向导。

同步检查只比较键集合和值类型，不比较真实 `python_path` 与模板占位值。
任何非零结果都必须中断抓取；不得依赖 `load_config()` 的默认值降级继续执行。

## 首次配置或修复向导

1. 询问用户：“有想用的 Python 环境路径吗？直接回车我自动搜索。”
2. 用户指定路径时先验证；未指定时依次检查 `where python`、`where python3`、
   常见项目环境目录及系统 PATH。
3. 列出候选并让用户确认；优先选择已安装 `requests`、`bs4`、`markdownify`、
   `lxml` 的环境。
4. 解释器可用但缺依赖时，在获得所需权限后安装，不因缺依赖直接换环境：

   ```powershell
   & "<python路径>" -m pip install requests beautifulsoup4 markdownify lxml -q
   ```

5. 以 `config.example.py` 为结构模板创建或修复 `scripts/config.py`，填入真实
   `python_path` 及所有现有键。修改本 skill 文件必须使用安全的文件编辑工具；
   不把真实密钥或代理凭据写进模板。
6. 写入后立即重跑 `check_config_sync.py`；只有退出码为 `0` 才能继续。

若用户不提供解释器且自动搜索无结果，停止任务并报告原因；不要创建半成品配置。

## 配置变更纪律

- 新增、删除或改变配置键时，同步更新 `config.example.py`、本文件及相应测试。
- 不读取、提交或复制真实 `scripts/config.py` 到发布暂存目录。
- 需要超出沙箱权限时走 Codex 审批，不用配置文件绕过权限机制。
- 配置同步失败是硬门禁，不得解释为警告或静默使用默认值。
