# web2md 优化总结

> 本文档是优化交接文档：记录历次大优化"改了哪些文件、验证到什么程度、
> 踩过哪些坑、遗留了什么"，供后续做优化前对齐、避免重复踩坑。
> 优化前先读本文件，优化后追加记录，保持不过时。

## 一、优化范围

### 2026-08-02：导航子页面批量获取

| 类别 | 内容 |
|------|------|
| 新功能 | `collect_children`：解析侧边栏导航，收集严格导航子页面 + 孙页面（深度≤2）；`--children`/`--no-children` CLI 覆盖；`config.py` 的 `collect_children` 开关（默认 false） |
| 重构 | 抽出 `extract_title`（h1 优先、去站点后缀）、`process_page`（单页落盘）、`fetch_and_process` + `_fetch_child_tree`（递归批量抓取）；main 改 argparse |
| 输出 | 按页面标题文件夹嵌套落盘（父/子/孙），非法字符替换 |
| 测试 | 28 → 34 用例（导航解析 Sphinx+VitePress 双结构、标题命名、快照等） |

### 2026-08-01~02：脚本单份化 + 移植 Codex 增量

- 5 个内嵌脚本 → `scripts/` 独立文件；新增 `markdown_code.py`（掩码）
- 移植 Codex 版：DOM 规范化 8 函数、`list_display_fixes --apply`、`final_verify` 全量验证；保留 `mjx-container` 支持
- config.py 配置模式；平台通用化（"Claude"→"AI 助手"）
- 排障体系：新增 `KNOWN_ISSUES.md`、自进化章节、产物清理约定

## 二、验证结果

- PX4 `config_fw/` 端到端：父 + 4 子页面抓取、标题文件夹嵌套落盘正确
- Wikipedia 单页：58 公式、429 退避、13/13 图片
- selftest 34 用例全绿

## 三、过程中的 bug 序列

1. VitePress 侧边栏用 `div/section` 而非 `ul/li` → 标签无关算法（容器查找 + `ul`/`div.items` 层级计数）
2. `collect_children` 在 `process_page` 后调用：`html_to_markdown` 会删 `<nav>` → 先收集再处理
3. `<title>` 带站点后缀 → `extract_title` 优先 h1、去 ` | ` 后缀
4. 目录 URL 与 `index.html` 形式不匹配 → `_norm_nav_url` 双向归一化
5. 测试数据 href 与 base_url 版本号不一致 → 测试统一

## 四、协作风格

先方案后动手（用户确认才实施）／任务清单跟踪／测试先行（selftest 全绿才交付）／真实环境端到端验证／证据驱动排查（抓真实 HTML 分析，不猜）／文档同步／诚实报告／安全优先／一次性脚本即删。

## 五、遗留事项

- `collect_children` 只按导航树收集子+孙，不递归子页面正文引用（设计如此）
- 导航解析已验证 Sphinx li/ul 与 VitePress div/section；纯 JS 渲染导航的站点可能需要扩展
- 标题文件夹命名由 AI 助手酌情调整（须符合规范），脚本默认 `sanitize_filename`
- `config.py` 的 `collect_children` 默认 false，需用户开启
