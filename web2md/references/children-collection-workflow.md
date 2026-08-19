# 导航子页面收集工作流

## 强制读取条件

启用 `collect_children`、`--children`、`--children-from`、`--rendered-html`，
或导航结果为空、异常、无法核实时，**必须在执行子页面流程前完整读取本文件**。
只抓当前单页时不读取。

## 目录

- [收集边界](#收集边界)
- [规则解析流程](#规则解析流程)
- [渲染后-DOM-降级](#渲染后-dom-降级)
- [AI-助手清单通道](#ai-助手清单通道)
- [输出与验收](#输出与验收)

## 收集边界

- 只收集当前页面在侧边栏导航树中的**严格直接子页面**，以及这些子页面的
  直接子页面；最大深度为两级。
- 正文中普通链接、外部站点、版本切换项及整棵导航树的其他分支不属于范围。
- 去除 fragment 后仍指向当前页的链接是章节锚点，不重复抓取；孙页面指向其
  直接父页面锚点时同样跳过。
- 无法核实导航结构不等于确认没有子页面。证据不足时必须报告并请求用户确认。

## 规则解析流程

使用配置 `collect_children=true` 或临时 CLI `--children`：

```powershell
& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}" --children
```

1. 先抓取父页面并在导航容器中定位当前节点。
2. 读取 `collect_children` 返回的 `structure`、`children` 与 `notes`。
3. 检查候选是否同域、位于稳定版本路径前缀内且深度不超过两级。
4. 逐个抓取子/孙页面；任何孙页面失败都会让批次失败，但已经成功的产物保留。
5. 按导航顺序生成目录，`page_nav=true` 时在父页面末尾追加本地 Sub-pages 列表。

规则结果需要人工判断的信号：

- `structure=unknown` / `generic` 且 `notes` 表示未定位当前页、容器未识别或原因不明；
- 结果为空，但父页面 Markdown、同站历史产物或导航文本明确存在子页；
- 候选数量异常、包含外域或版本切换项，疑似整树误抓；
- 脚本输出 `REVIEW` 或非零退出码。

## 渲染后 DOM 降级

仅当静态 HTML 导航为空且页面导航可能由 JavaScript 渲染时使用：

1. 用当前可用的浏览器能力打开**同一个父页面**，等待导航渲染完成。
2. 保存 UTF-8 DOM 快照，并记录地址栏最终 URL。
3. 执行：

   ```powershell
   & "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}" `
     --children --rendered-html "{DOM快照路径}" --rendered-url "{浏览器最终URL}"
   ```

4. 只在静态导航为空时采用快照。脚本必须用 `--rendered-url`，或快照中的
   canonical / `og:url` / `base href` 校验页面身份；query 是身份的一部分，
   不同 `?id=` 不得视为同页。
5. 再次限制同域、稳定版本路径前缀及两级深度。无法校验或仍无可靠结果时，
   保留非零 `REVIEW`，转入 AI 助手清单通道。
6. 使用后删除临时 DOM 快照，不放入 skill 或发布包。

已识别主题、已定位当前项且确认为真实叶子页时，可以确认无子页面，不触发该降级。

## AI 助手清单通道

优先按以下顺序取证：

1. 本次抓取保存的页面信息与导航诊断 `notes`；
2. `<skill-directory>/logs/intermediate/<项目根名>/children_list.md`、
   `_archive/<项目根名>/` 快照及项目目录中同站历史产物；
3. 可用的网页访问能力，仅用于补充核实同域、版本前缀与嵌套关系；
4. 仍不足时，用配置中的 Python 与代理写一次性核实脚本，放入
   `logs/_archive/<项目根名>/`，用后清理。

所有通道都无法确认时，向用户说明“无法核实子/孙页面”，附已有证据并请求清单。
禁止把不可核实静默记为无子页面。

确认后写入：

`<skill-directory>/logs/intermediate/<项目根名>/children_list.md`

```markdown
# 子页面清单 — <父页面标题>
- <子页面标题> | https://example.invalid/child.html
  - <孙页面标题> | https://example.invalid/grandchild.html
- <另一子页面标题> | <https://example.invalid/other.html> | <可选备注>
```

解析约束：

- `#` 开头行和空行忽略；列表标记 `-` / `*` 均可。
- 两个空格缩进表示孙页面；更深层级、缺 URL、无父项的孙页面跳过并警告。
- `|` 后第一段为 URL，之后为备注；URL 可用 `< >` 包裹。
- 清单标题仅供展示；实际目录名取页面真实标题并按安全命名规则处理。

执行：

```powershell
& "<python路径>" "<skill-directory>/scripts/web2md.py" "<URL>" "{项目根目录}" `
  --children-from "{清单路径}"
```

`--children-from` 优先于规则解析。

## 输出与验收

```text
{输出根}/<父页面标题>/
├── <父页面标题>.md
├── <父页面标题>.assets/
├── <子页面标题>/
│   ├── <子页面标题>.md
│   └── <孙页面标题>/
└── <另一子页面标题>/
```

- 处理 Windows 非法字符、保留名、尾随点/空格和路径预算。
- 不同来源清洗成同名时追加稳定 URL 哈希；不得覆盖既有不同来源目录。
- Sub-pages 链接使用本地相对路径；路径含空格时用 `< >` 包裹。
- 对父、子、孙页面分别完成公式与结构审核，并运行 `final_verify.py`，确保
  每个文件均无 FAIL、无 REVIEW。
- 批次非零退出、漏页、导航边界不明或任何失败项都必须在交付中明确列出。
