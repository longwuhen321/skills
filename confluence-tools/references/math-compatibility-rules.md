# Confluence 数学公式兼容规则

## 强制读取条件

Markdown 单页、树导入、恢复上传、公式升级或 `--confirm` 前，以及维护公式兼容逻辑时，
必须按 `SKILL.md` 直接路由完整读取本文件，不受 `preflight_review` 开关影响。
读取后在公开回执中列出本文件，并说明：“仅按已知规则转换数学宏正文，特殊结构先复核，
源文件格式、目标公式兼容性和实际渲染分别记录。”

## 适用基线与职责

- 规则基于 Confluence 9.2.1 Data Center 的数学宏及 MathJax 2.7.9；合法 LaTeX 在目标
  环境中仍可能因扩展未加载而报 `Undefined control sequence`，不能据此认定源文档写错。
- `scripts/math_compat.py` 是唯一规则实现；`md_preflight.py` 分析并报告，`md_import.py`
  在生成 storage 时应用，`math_upgrade.py` 同时处理新转换的公式和已有原生数学宏。
- 不新增配置或 CLI 参数，不自动探测服务器、安装扩展或改服务器配置。`\require` 使用
  下表列出的固定扩展名；它是公式级依赖声明，仍以目标环境提供这些扩展为前提。
- 这是已知规则检查器，不是完整 TeX 解析器。未知命令保留，不猜测替换；静态通过不表示
  所有公式都已实际渲染成功。目标渲染器或扩展版本变化时须重新验证，再修订规则基线。

## 自动处理范围

| 原写法 | 转换与边界 |
|---|---|
| `\dfrac` | 读取两个 TeX 参数，转换为局部作用域的 `{\displaystyle\frac...}`；支持嵌套分式及合法的省略花括号参数，避免 displaystyle 泄漏到后续公式 |
| `\operatorname{rank}` | 简单字母数字名称改为 `\mathop{\mathrm{rank}}\nolimits `；末尾保留空格，避免后续字母拼成错误命令 |
| `\operatorname*{argmax}` | 简单名称改为 `\mathop{\mathrm{argmax}} `，保留算子的上下标行为；已验证的 `B\acute{e}zier`、`SB\acute{e}zier` 名称也可转换 |
| 其他 `\operatorname` 参数、显式 `\limits` / `\nolimits` | 保留原命令，显式加载 `AMSmath`，避免粗暴替换改变文字排版或上下标语义 |
| `\wideparen{AOB}` | 仅对大写字母圆弧标签使用 `\overset{\mmlToken{mo}[stretchy=true]{⏜}}{AOB}`；其他参数人工复核 |
| `\iddots` | 改为 `\mathinner{⋰}`，保留向右上方延伸的省略号方向 |

以下命令按需在当前公式前补唯一的 `\require{扩展名}`，已有声明保留，不重复添加：

| 扩展 | 已纳入的命令 |
|---|---|
| `AMSmath` | `lVert`、`rVert`、`lvert`、`rvert`、`boxed`、`substack`、`xrightarrow`、`mathring`、`dddot`、`ddddot`、`binom`，以及保留原写法的 `operatorname` |
| `AMSsymbols` | `leqslant`、`geqslant`、`triangleq`、`square`、`varnothing` |
| `mediawiki-texvc` | `oiint`、`vline`；`vline` 还需要 `AMSmath` |
| `cancel` | `cancel` |

命令识别遵守完整控制序列边界，跳过 TeX 注释和转义反斜杠；不能用全局字符串替换处理
公式。已有扩展声明不会被删除、去重或重排，也不把注释中的声明视为已加载。

## 人工复核与写入阻断

- `\multicolumn`、`\cline` 涉及矩阵跨列和分隔线，报告 `MATH_COMPAT_REVIEW_REQUIRED`。
  旧任务中某几个矩阵的修复方法不能推广为通用替换；必须逐项核对行列、元素和分隔关系。
- 上表之外的 `\wideparen` 参数、待转换命令缺参数，以及 `\def`、`\newcommand`、
  `\renewcommand`、`\let`、`\DeclareMathOperator` 等自定义宏进入人工复核，不假定原命令语义。
- 同一公式存在未解决问题时，保持该公式原文，不应用一部分改动后宣称修复。
- 预审开启时返回源文件路径、行列、规则 ID 和消息；格式本身仍可能是 `CLEAN`。
  修复只能进入已批准的修复副本，完成问题文件及最终对象复审后再上传。
- 预审关闭时，导入转换仍执行兼容检查。单页在页面写入前阻断；树导入实际执行前先转换
  全部待写文件，任一失败则不开始远端写入。关闭格式预审不能绕过兼容门禁。
- 升级及 `--confirm` 对未解决或尚未规范化的数学宏拒绝写入；允许美元符残留的开关
  不能绕过兼容检查。人工修复后重新生成候选并复核，不能只修改报告状态。

## 数据保护与审核记录

- 合法源 Markdown 无须为了 Confluence 改写，也不因纯兼容转换而新建 `__修复` 副本。
  原有格式修复、副本、容量拆分和哈希门禁规则继续生效。
- 导入先执行 `heading_math_mode`，再规范化原生数学宏；`literal` 标题保留字面公式，
  `mathinline` 标题与正文使用同一兼容规则，不调整现有标题展示政策。
- 只修改 `mathinline`、`mathblock` 的正文参数或纯文本正文；不重序列化整个页面。
  支持富文本宏内嵌数学宏；代码、注释、CDATA 中的伪标签不参与宏识别。参数按 XML
  文本解码一次，纯文本正文安全编码为 CDATA；宏 ID、非正文参数及其他正文保持原字节。
- 预审 `review.json` 单独保存 `format_status` 和 `math_compatibility`。后者含 profile、
  changes、issues、passed、renderer_validation；顶层 `status` 是综合门禁，兼容问题使其
  成为 `BLOCKED`。自动兼容转换只列入 changes，不列作源 Markdown 格式修复项。
- 升级 debug 保留原有 before/after/info，并增加 `math_compatibility.json`，记录公式序号、
  storage 正文偏移、公式内偏移、变更与问题。无变化不 PUT、不增加版本。

## 验证层次

1. **格式检查**：Markdown 定界符、花括号、环境及 XHTML 结构检查。
2. **已知兼容检查**：本模块的规则匹配、候选检查和幂等验证；默认
   `renderer_validation=not_run`，不能改称“全部公式渲染通过”。
3. **渲染器解析**：需要时使用与目标一致的 MathJax 版本和扩展条件，记录版本、公式数量、
   唯一公式数和错误数；环境不可用时如实说明未执行，不用 API 写入成功代替。
4. **页面效果与性能**：storage/view 回读和浏览器显示、加载性能分别记录；公网效果由实际
   公网环境确认。用户选择自行验收时，不擅自追加页面测试或宣称已完成。

回归用例位于 `scripts/test/selftest.py` 的 `TestMathCompatibilityRules` 和
`TestMathCompatibilityIntegration`，覆盖共享规则、三个入口、写入前阻断与幂等性。
