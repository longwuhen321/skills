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
- 标题 `h1`～`h6` 中的行内公式必须保留为字面 `$...$`，供 Confluence 9.2.1 目录宏渲染；正文行内公式使用 `mathinline`。
- 转换必须幂等：内容已达目标状态时不改正文、不增加页面版本。
- 查询歧义、并发版本冲突、附件或子任务失败必须显式失败，不得猜测或吞错。

## 修改后

1. 运行完整 `scripts/test/selftest.py`。
2. 运行配置同步、LF 换行和隔离候选目录的 `package_check.py`。
3. 同步 `SKILL.md`；bug 修复记入 `KNOWN_ISSUES.md`，非 bug 优化按约定记入 `OPTIMIZATION_SUMMARY.md`。
