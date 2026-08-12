# Confluence 工具脚本开发规则

修改 `scripts/*.py` 时遵守以下约束；上位规则以相邻目录的
`SKILL_MODIFICATION_STANDARD.md` 和本 skill 的 `SKILL.md` 为准。

## 修改前

1. 先列出目标、影响文件和可验证的完成条件，再开始编辑。
2. 运行 `scripts/test/selftest.py` 建立基线；bug 修复先添加失败回归用例。
3. 优先复用 `scripts/common.py` 中的公共规则，避免导入、升级、导出各自实现不同语义。

## 转换安全

- Confluence storage 是 XHTML；正文、属性、宏参数和 CDATA 的转义层级不可混用。
- 转换前保护代码、宏和其他结构化区域，正则不得跨结构吞内容。
- 上传前预审默认开启：源 Markdown 保持不变，正文只从通过验证的审核副本转换；
  树导入必须先预审全部待写页面，任一失败时零远端写入。附件仍按源文件目录解析。
- 标题 `h1`～`h6` 中的行内公式由公共 `heading_math_mode` 决定：`literal` 保留字面 `$...$`（Confluence 9.2.1 目录宏默认），`mathinline` 使用原生宏；导入与升级必须读取同一值。
- `mathinline` 模式下标题公式始终保持行内宏，不能套用正文“复杂公式升级为 mathblock”的启发式规则。
- 转换必须幂等：内容已达目标状态时不改正文、不增加页面版本。
- 目录宏归一化只能替换或删除已识别宏的原始跨度，不能重序列化整个 storage；
  无源宏不注入，两类宏共存时保留目标宏原文，同类宏超过一个必须拒绝写入。
- Easy Heading 创建参数必须使用白名单和严格枚举；已有 Easy Heading 的参数不由配置覆盖，
  新建宏使用新 UUID，不复制参考页面的 `macro-id`。
- 查询歧义、并发版本冲突、附件或子任务失败必须显式失败，不得猜测或吞错。

## 修改后

1. 运行完整 `scripts/test/selftest.py`。
2. 运行配置同步、LF 换行和隔离候选目录的 `package_check.py`。
3. 同步 `SKILL.md`；bug 修复记入 `KNOWN_ISSUES.md`，非 bug 优化按约定记入 `OPTIMIZATION_SUMMARY.md`。
