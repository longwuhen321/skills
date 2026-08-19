import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent
WORK_DIR = Path(os.environ.get('WEB2MD_TEST_WORKDIR', TEST_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from web2md import (
    _mathml_to_latex,
    _save_debug_snapshot,
    download_images,
    html_to_markdown,
    normalize_definition_list_tables,
    normalize_document_html,
    process_math_formulas,
)
import web2md as web2md_module


VERIFIER = SCRIPT_DIR / 'final_verify.py'
BASE_URL = 'https://example.com/docs/topic/page.html'


class SphinxConversionTests(unittest.TestCase):
    def run_verifier(self, markdown):
        path = WORK_DIR / ('_sample_' + self._testMethodName + '.md')
        try:
            path.write_text(markdown, encoding='utf-8')
            return subprocess.run(
                [sys.executable, str(VERIFIER), str(path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
        finally:
            path.unlink(missing_ok=True)

    def test_dom_normalization_preserves_math_payloads(self):
        html = r'''
        <html>
          <head><meta name="generator" content="Sphinx 8.2"></head>
          <body><main>
            <h2 id="solve"><code>solve</code> Formula
              <span class="math notranslate nohighlight">\(x_{k}^{*}+\text{&lt;path&gt;}\)</span>
              <a class="headerlink" href="#solve"></a>
            </h2>
            <p>Use &lt;path&gt; with
              <span class="math">\(F(s)=\int_0^\infty f(t)e^{-st}\,dt\)</span>.
            </p>
            <p><a href="../guide.html">Guide</a> <a href="#legacy">Legacy</a></p>
            <pre>tool &lt;raw&gt;</pre>
          </main></body>
        </html>
        '''
        soup = BeautifulSoup(html, 'lxml')
        before = [node.get_text().strip() for node in soup.select('.math')]

        stats = normalize_document_html(soup, BASE_URL)
        after = [node.get_text().strip() for node in soup.select('.math')]

        self.assertEqual(after, before)
        self.assertEqual(stats['sphinx_headings'], 1)
        self.assertEqual(stats['links'], 2)
        self.assertEqual(stats['placeholders'], 1)
        self.assertEqual(soup.select_one('h2 > a')['href'], BASE_URL + '#solve')
        self.assertEqual(
            soup.find('a', string='Guide')['href'],
            'https://example.com/docs/guide.html',
        )
        self.assertEqual(soup.find('a', string='Legacy')['href'], BASE_URL + '#legacy')
        self.assertEqual(soup.pre.get_text(), 'tool <raw>')

        math_count = process_math_formulas(soup)
        self.assertEqual(math_count, 2)
        normalized_text = soup.get_text()
        for payload in (
            r'$x_{k}^{*}+\text{<path>}$',
            r'$F(s)=\int_0^\infty f(t)e^{-st}\,dt$',
        ):
            self.assertIn(payload, normalized_text)

        markdown = html_to_markdown(soup, {}, BASE_URL, 'unused.assets')
        self.assertIn('`<path>`', markdown)
        self.assertIn('https://example.com/docs/topic/page.html#solve', markdown)
        self.assertNotIn('', markdown)

    def test_verifier_accepts_math_and_code_placeholders(self):
        valid = 'HTML <br> code `<path>` and math $\\text{<path>}$.\n'
        result = self.run_verifier(valid)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_math_plain_letter_delimited_formulas(self):
        # 纯字母 Sphinx 公式（不含 \{}^_ 字符）也必须转换，不能残留 \(...\)
        # 回归：\(L=W\)、\(AR\)、\(x, y, z\) 此前被 [\\{}^_] 过滤漏掉
        html = (
            '<p>therefore <span class="math notranslate nohighlight">\\(L=W\\)</span>, '
            'and <span class="math">\\(AR\\)</span> is the ratio, '
            'translational (<span class="math">\\(x, y, z\\)</span>)</p>'
        )
        soup = BeautifulSoup(html, 'lxml')
        count = process_math_formulas(soup)
        self.assertEqual(count, 3)
        normalized = soup.get_text()
        for payload in (r'$L=W$', r'$AR$', r'($x, y, z$)'):
            self.assertIn(payload, normalized)
        self.assertNotIn('\\(', normalized)

    def test_gitbook_chrome_removed(self):
        # GitBook 3.x：导航 h1 与搜索模板不应进入 Markdown；正文必须保留
        # （正文容器 .search-noresults 嵌套在 #book-search-results 内部，只删模板 div）
        html = r'''
        <html>
          <head><meta name="generator" content="GitBook 3.2.3"></head>
          <body>
            <div class="book-header">
              <h1><a href="..">1.3 ROS2快速体验</a></h1>
            </div>
            <div class="page-inner">
              <div id="book-search-results">
                <div class="search-noresults">
                  <section class="normal markdown-section">
                    <h2>1.3 ROS2快速体验</h2>
                    <p>正文内容</p>
                  </section>
                </div>
                <div class="has-results">
                  <h1 class="search-results-title"><span class="search-results-count"></span> results matching "<span class="search-query"></span>"</h1>
                  <ul class="search-results-list"></ul>
                </div>
                <div class="no-results">
                  <h1>No results matching "<span class="search-query"></span>"</h1>
                </div>
              </div>
            </div>
          </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'lxml')
        normalize_document_html(soup, 'https://rzl6.github.io/ROS2_Tuition/chapter1/13-ros2kuai-su-ti-yan.html')
        text = soup.get_text()
        self.assertNotIn('results matching', text)
        self.assertNotIn('No results', text)
        # 导航 h1 已删；正文 h2 与段落必须保留
        self.assertIn('正文内容', text)
        headings = soup.find_all(re.compile(r'^h[1-6]$'))
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0].name, 'h2')
        # .book-header 内的 <a href=".."> 不应被链接规范化成站点根绝对链接
        self.assertNotIn('ROS2_Tuition/', text)

    def test_verifier_rejects_bare_placeholder(self):
        result = self.run_verifier('Use <path> here.\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('正文中存在未保护的尖括号占位符', result.stdout)

    def test_verifier_rejects_missing_relative_link(self):
        result = self.run_verifier('[Guide](../missing.html)\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('相对链接目标不存在', result.stdout)

    def test_verifier_rejects_legacy_sphinx_anchor(self):
        result = self.run_verifier('[mount](#cmdmount)\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('存在未保留的 Sphinx #cmd 锚点', result.stdout)

    def test_verifier_rejects_sphinx_glyph(self):
        result = self.run_verifier('# Heading \n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('存在残留的 Sphinx 标题永久链接图标', result.stdout)

    def test_verifier_rejects_unclosed_fence(self):
        result = self.run_verifier('```sh\necho hello\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('代码围栏未闭合', result.stdout)

    def test_verifier_reviews_blockquoted_command_syntax(self):
        result = self.run_verifier('**Command Syntax**:\n\n> command <arg>\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('命令语法疑似被转换为引用块', result.stdout)

    # ── 以下为 2026-08-01 新增：MathML / mjx / 快照 / 定义列表表格 / data: URI ──

    def test_mathml_matrix_to_latex(self):
        # mtable → bmatrix（多行多列）
        html = ('<math><mtable><mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr>'
                '<mtr><mtd><mi>c</mi></mtd><mtd><mi>d</mi></mtd></mtr></mtable></math>')
        latex = _mathml_to_latex(BeautifulSoup(html, 'lxml').find('math'))
        self.assertIn('\\begin{bmatrix}', latex)
        self.assertIn('a & b', latex)
        self.assertIn('c & d', latex)

    def test_mathml_column_vector_notation(self):
        # 单列 ≤4 行的 mtable → 逗号分隔行内记法（不加方括号）
        html = ('<math><mtable><mtr><mtd><mi>x</mi></mtd></mtr>'
                '<mtr><mtd><mi>y</mi></mtd></mtr></mtable></math>')
        latex = _mathml_to_latex(BeautifulSoup(html, 'lxml').find('math'))
        self.assertIn('x, y', latex)
        self.assertNotIn('bmatrix', latex)

    def test_mathml_accent_mover(self):
        # mover 重音：→ 变 \vec，^ 变 \hat
        vec_html = '<math><mover><mi>v</mi><mo>→</mo></mover></math>'
        latex = _mathml_to_latex(BeautifulSoup(vec_html, 'lxml').find('math'))
        self.assertIn('\\vec{v}', latex)
        hat_html = '<math><mover><mi>x</mi><mo>^</mo></mover></math>'
        latex = _mathml_to_latex(BeautifulSoup(hat_html, 'lxml').find('math'))
        self.assertIn('\\hat{x}', latex)

    def test_mjx_function_name_restore(self):
        # MathJax SVG 把 sin 拆成 s/i/n 三个 <mi>，转换后应还原为 \sin
        html = ('<mjx-container display="false"><mjx-assistive-mml><math>'
                '<mi>s</mi><mi>i</mi><mi>n</mi><mo>(</mo><mi>x</mi><mo>)</mo>'
                '</math></mjx-assistive-mml></mjx-container>')
        soup = BeautifulSoup(html, 'lxml')
        count = process_math_formulas(soup)
        self.assertEqual(count, 1)
        self.assertIn(r'$\sin (x)$', str(soup))

    def test_normalize_definition_list_tables(self):
        md = 'term\n:   | a | b |\n    | 1 | 2 |\nnext'
        self.assertEqual(
            normalize_definition_list_tables(md),
            'term\n| a | b |\n| 1 | 2 |\nnext',
        )

    def test_image_data_uri_skipped_in_download(self):
        # data: URI 不触发网络下载（session 传 None 也不应被调用）
        html = '<img src="data:image/png;base64,AAAA" alt="x">'
        soup = BeautifulSoup(html, 'lxml')
        with tempfile.TemporaryDirectory() as tmp:
            mapping = download_images(soup, Path(tmp), 'https://example.com', None)
        self.assertEqual(mapping, {})

    def test_wikipedia_layout_tables_flatten_but_semantic_table_stays(self):
        html = r'''
        <main>
          <dl><dt>Formula</dt><dd><table id="formula-layout"><tbody>
            <tr>
              <td>${\displaystyle y(t)=(x*h)(t)}$</td>
              <td>${\displaystyle =\int x(t-\tau)h(\tau)\,d\tau}$</td>
            </tr>
            <tr>
              <td></td>
              <td>${\displaystyle =\int x(\tau)h(t-\tau)\,d\tau}$
                (using <a href="https://en.wikipedia.org/wiki/Convolution">commutativity</a>)
              </td>
            </tr>
            <tr>
              <td></td>
              <td>${\displaystyle =\int h(\tau)x(t-\tau)\,d\tau}$
                (<a href="https://en.wikipedia.org/wiki/Convolution">commutativity</a>)
              </td>
            </tr>
          </tbody></table></dd></dl>
          <p>After layout.</p>
          <table class="numblk" role="presentation"><tbody><tr>
            <td>${\displaystyle O_t\{x\}=y(t)}$</td><td></td><td>Eq.2</td>
          </tr></tbody></table>
          <table><caption>Measurements</caption>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>gain</td><td>${\displaystyle H(s)}$</td></tr>
          </table>
        </main>
        '''
        markdown = html_to_markdown(
            BeautifulSoup(html, 'lxml'), {},
            'https://en.wikipedia.org/wiki/Example', 'unused.assets',
        )
        before_semantic = markdown.split('Measurements', 1)[0]
        self.assertNotIn('|', before_semantic)
        self.assertNotIn(':   ', before_semantic)
        self.assertNotIn('intentionally blank header', markdown)
        self.assertIn('$$\n\\begin{aligned}', markdown)
        self.assertIn('[commutativity](https://en.wikipedia.org/wiki/Convolution)', markdown)
        self.assertIn('commutativity](https://en.wikipedia.org/wiki/Convolution))\n\nAfter layout.', markdown)
        self.assertIn('Eq.2', markdown)
        self.assertIn('| Name | Value |', markdown)
        self.assertIn('| gain | ${\\displaystyle H(s)}$ |', markdown)

    def test_wikipedia_message_box_becomes_blockquote(self):
        html = r'''
        <main><table class="ambox ambox-style"><tr>
          <td><img src="icon.png" alt="notice"></td>
          <td>This article needs <a href="https://example.com/citations">more citations</a>.</td>
        </tr></table></main>
        '''
        markdown = html_to_markdown(
            BeautifulSoup(html, 'lxml'), {},
            'https://en.wikipedia.org/wiki/Example', 'unused.assets',
        )
        self.assertIn('> This article needs [more citations](https://example.com/citations).', markdown)
        self.assertNotIn('|', markdown)

    def test_non_wikipedia_formula_layout_remains_table(self):
        html = r'''
        <main><table><tr><td>${\displaystyle x}$</td><td>${\displaystyle y}$</td></tr>
        <tr><td></td><td>${\displaystyle z}$</td></tr></table></main>
        '''
        markdown = html_to_markdown(
            BeautifulSoup(html, 'lxml'), {}, BASE_URL, 'unused.assets',
        )
        self.assertIn('|', markdown)

    def test_save_debug_snapshot(self):
        # 用临时 skill 根验证路径规则，绝不写入真实 <skill>/logs。
        with tempfile.TemporaryDirectory() as tmp:
            fake_script = Path(tmp) / 'skill' / 'scripts' / 'web2md.py'
            fake_script.parent.mkdir(parents=True)
            output_root = Path(tmp) / 'project'
            output_root.mkdir()
            with patch.object(web2md_module, '__file__', str(fake_script)):
                path = _save_debug_snapshot(output_root, '<html>raw</html>')
            self.assertTrue(path.exists())
            self.assertTrue(path.is_relative_to(Path(tmp)))
            self.assertEqual(path.parent, Path(tmp) / 'skill' / 'logs' / '_archive' / 'project')
            self.assertTrue(path.name.startswith('fetch_'))
            self.assertEqual(path.read_text(encoding='utf-8'), '<html>raw</html>')

    # ── 2026-08-01 新增：导航子页面收集（collect_children）──

    NAV_HTML = """
    <nav><ul>
    <li><a href="/v1.15/en/frames_plane/index.html">Planes</a>
      <ul>
        <li><a href="/v1.15/en/config_fw/index.html" class="active">Config/Tuning</a>
          <ul>
            <li><a href="/v1.15/en/config_fw/pid_tuning_guide_fixedwing.html">Rate/Attitude Controller Tuning Guide</a></li>
            <li><a href="/v1.15/en/config_fw/position_tuning_guide_fixedwing.html">Altitude/Position Controller Tuning Guide</a></li>
            <li><a href="/v1.15/en/config_fw/weight_and_altitude_tuning.html">Weight &amp; Altitude Tuning</a></li>
            <li><a href="/v1.15/en/config_fw/trimming_guide_fixedwing.html">Trimming Guide</a>
              <ul>
                <li><a href="/v1.15/en/config_fw/trimming_guide_fixedwing_a.html">Trimming Sub A</a></li>
                <li><a href="/v1.15/en/config_fw/trimming_guide_fixedwing_b.html">Trimming Sub B</a></li>
              </ul>
            </li>
          </ul>
        </li>
      </ul>
    </li>
    </ul></nav>
    """

    def test_collect_children_strict_navigation(self):
        # 严格导航子页面：目录形式 URL → 4 个子页面，Trimming Guide 下 2 个孙页面
        from nav_children import collect_children
        soup = BeautifulSoup(self.NAV_HTML, 'lxml')
        children = collect_children(soup, 'https://docs.px4.io/v1.15/en/config_fw/')['children']
        self.assertEqual(len(children), 4)
        self.assertEqual(children[0]['title'], 'Rate/Attitude Controller Tuning Guide')
        self.assertEqual(
            children[0]['url'],
            'https://docs.px4.io/v1.15/en/config_fw/pid_tuning_guide_fixedwing.html',
        )
        trimming = children[3]
        self.assertEqual(trimming['title'], 'Trimming Guide')
        self.assertEqual(len(trimming['children']), 2)
        self.assertEqual(trimming['children'][0]['title'], 'Trimming Sub A')

    def test_collect_children_index_html_url(self):
        # index.html 形式的 base_url 也能匹配当前导航节点
        from nav_children import collect_children
        soup = BeautifulSoup(self.NAV_HTML, 'lxml')
        children = collect_children(soup, 'https://docs.px4.io/v1.15/en/config_fw/index.html')['children']
        self.assertEqual(len(children), 4)

    def test_collect_children_leaf_returns_empty(self):
        # 叶子节点（导航中无子页面）→ 空列表，不报错
        from nav_children import collect_children
        leaf = BeautifulSoup(
            '<nav><ul><li><a href="/a/index.html">A</a></li></ul></nav>', 'lxml')
        self.assertEqual(collect_children(leaf, 'https://x.com/a/')['children'], [])

    def test_children_folder_name_sanitized(self):
        # 标题文件夹名：非法字符（/ 等）被替换，符合文件系统命名规范
        from web2md import sanitize_filename
        self.assertNotIn('/', sanitize_filename('Rate/Attitude Controller Tuning Guide'))
        self.assertNotIn(':', sanitize_filename('a:b*c?d'))
        self.assertTrue(sanitize_filename('Trimming Guide'))

    def test_collect_children_vitepress_structure(self):
        # VitePress 侧边栏用 div/section 而非 ul/li：子页面平铺在 div.items 下
        from nav_children import collect_children
        html = """
        <aside class="VPSidebar"><nav class="nav"><div class="group">
        <section class="VPSidebarItem level-0">
          <div class="item"><a href="/v1.15/en/frames_plane/index.html">Planes</a></div>
          <div class="items">
            <section class="VPSidebarItem level-1">
              <div class="item"><a href="/v1.15/en/config_fw/index.html" class="VPLink link link">Config/Tuning</a></div>
              <div class="items">
                <div class="item"><a href="/v1.15/en/config_fw/pid_tuning_guide_fixedwing.html">Rate/Attitude Controller Tuning Guide</a></div>
                <div class="item"><a href="/v1.15/en/config_fw/trimming_guide_fixedwing.html">Trimming Guide</a></div>
              </div>
            </section>
          </div>
        </section>
        </div></nav></aside>
        """
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(soup, 'https://docs.px4.io/v1.15/en/config_fw/')['children']
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0]['title'], 'Rate/Attitude Controller Tuning Guide')
        self.assertEqual(
            children[0]['url'],
            'https://docs.px4.io/v1.15/en/config_fw/pid_tuning_guide_fixedwing.html',
        )
        self.assertEqual(children[1]['title'], 'Trimming Guide')

    def test_extract_title_strips_zero_width(self):
        # h1 自带的零宽字符（U+200B 等）必须清除，避免混入文件夹名
        from web2md import extract_title
        html = '<html><head><title>P</title></head><body><h1>Fixed-wing Vehicle Configuration\u200b</h1></body></html>'
        soup = BeautifulSoup(html, 'lxml')
        self.assertEqual(extract_title(soup), 'Fixed-wing Vehicle Configuration')
        # 不可见字符全面清理：NBSP、零宽连字、BOM 等（真实空格保留）
        html2 = '<html><body><h1>a\u00a0b\u200d c\ufeffd</h1></body></html>'
        soup2 = BeautifulSoup(html2, 'lxml')
        self.assertEqual(extract_title(soup2), 'ab cd')

    def test_extract_title_strips_sphinx_anchor_icon(self):
        # Sphinx 锚点图标 U+F0C1（\uF0C1 即 \uF0C1）必须清除，避免混入文件夹名/文件名/md 标题
        from web2md import extract_title
        html = '<html><head><title>Commands</title></head><body><h1>Commands\uf0c1</h1></body></html>'
        soup = BeautifulSoup(html, 'lxml')
        self.assertEqual(extract_title(soup), 'Commands')
        # <title> 标签路径同样覆盖（无 h1 时）
        html2 = '<html><head><title>Commands\uf0c1 | NuttX</title></head><body></body></html>'
        soup2 = BeautifulSoup(html2, 'lxml')
        self.assertEqual(extract_title(soup2), 'Commands')

    def test_collect_children_ignores_same_page_anchors(self):
        # 单页文档：导航子项全部是当前页锚点（commands.html#xxx）→ 无子页面，不重复抓取
        from nav_children import collect_children
        html = """
        <nav><ul>
        <li><a href="/docs/latest/applications/nsh/commands.html">Commands</a>
          <ul>
            <li><a href="/docs/latest/applications/nsh/commands.html#test-evaluate-expression">test</a></li>
            <li><a href="/docs/latest/applications/nsh/commands.html#cat-concatenate-files">cat</a></li>
            <li><a href="/docs/latest/applications/nsh/commands.html#built-in-commands">Built-In Commands</a></li>
          </ul>
        </li>
        </ul></nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(soup, 'https://nuttx.apache.org/docs/latest/applications/nsh/commands.html')['children']
        self.assertEqual(children, [])

    def test_collect_children_current_link_with_anchor(self):
        # 当前导航链接带锚点（commands.html#commands）也能定位节点；本页锚点子项被过滤，真子页面保留
        from nav_children import collect_children
        html = """
        <nav><ul>
        <li><a href="/docs/latest/applications/nsh/commands.html#commands">Commands</a>
          <ul>
            <li><a href="/docs/latest/applications/nsh/commands.html#test-evaluate-expression">test</a></li>
            <li><a href="/docs/latest/applications/nsh/other.html">Other Page</a></li>
          </ul>
        </li>
        </ul></nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(soup, 'https://nuttx.apache.org/docs/latest/applications/nsh/commands.html')['children']
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]['title'], 'Other Page')
        self.assertEqual(
            children[0]['url'],
            'https://nuttx.apache.org/docs/latest/applications/nsh/other.html',
        )


    def test_collect_children_grandchild_anchor_to_parent_skipped(self):
        # 孙页面锚点指向其直接父页面自身（customizing.html#nsh-commands）→ 跳过，避免重复抓取同一页面互相覆盖
        from nav_children import collect_children
        html = '''
        <nav><ul>
        <li><a href="/docs/latest/applications/nsh/index.html" class="active">NuttShell (NSH)</a>
          <ul>
            <li><a href="/docs/latest/applications/nsh/customizing.html">The NSH Library</a>
              <ul>
                <li><a href="/docs/latest/applications/nsh/customizing.html#nsh-commands">NSH Commands</a></li>
                <li><a href="/docs/latest/applications/nsh/customizing.html#adding-new-nsh-commands">Adding New NSH Commands</a></li>
              </ul>
            </li>
          </ul>
        </li>
        </ul></nav>
        '''
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(
            soup, 'https://nuttx.apache.org/docs/latest/applications/nsh/index.html')['children']
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]['title'], 'The NSH Library')
        self.assertEqual(children[0]['children'], [])


    def test_collect_children_flat_anchor_sibling_skipped(self):
        # 平铺导航：customizing.html#nsh-commands 与 customizing.html 同级（同为子页面），
        # 锚点变体去 fragment 后与已接受的子页面相同 → 跳过，不重复抓取
        from nav_children import collect_children
        html = '''
        <nav><ul>
        <li><a href="/docs/latest/applications/nsh/index.html" class="active">NuttShell (NSH)</a>
          <ul>
            <li><a href="/docs/latest/applications/nsh/customizing.html">The NSH Library</a></li>
            <li><a href="/docs/latest/applications/nsh/customizing.html#nsh-commands">NSH Commands</a>
              <ul>
                <li><a href="/docs/latest/applications/nsh/customizing.html#adding-new-nsh-commands">Adding New NSH Commands</a></li>
              </ul>
            </li>
          </ul>
        </li>
        </ul></nav>
        '''
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(
            soup, 'https://nuttx.apache.org/docs/latest/applications/nsh/index.html')['children']
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]['title'], 'The NSH Library')
        self.assertEqual(children[0]['children'], [])

    # ── 2026-08-04 补：AI 判断通道（--children-from 清单解析）──

    def _write_children_list(self, tmpdir, content):
        from web2md import parse_children_list
        path = Path(tmpdir) / 'children_list.md'
        path.write_text(content, encoding='utf-8')
        return parse_children_list(str(path))

    def test_parse_children_list_basic_nesting(self):
        # 子页面 + 2 空格缩进孙页面：嵌套结构、标题/URL 提取正确
        with tempfile.TemporaryDirectory() as tmp:
            items = self._write_children_list(tmp, (
                '- 子页面一 | https://x.com/a.html\n'
                '  - 孙页面一 | https://x.com/a1.html\n'
                '  - 孙页面二 | https://x.com/a2.html\n'
                '- 子页面二 | https://x.com/b.html\n'
            ))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['title'], '子页面一')
        self.assertEqual(items[0]['url'], 'https://x.com/a.html')
        self.assertEqual(len(items[0]['children']), 2)
        self.assertEqual(items[0]['children'][1]['title'], '孙页面二')
        self.assertEqual(items[1]['children'], [])

    def test_parse_children_list_ignores_comments_and_notes(self):
        # # 注释行、空行、`|` 后的备注列全部忽略；标题缺失时回退用 URL 展示
        with tempfile.TemporaryDirectory() as tmp:
            items = self._write_children_list(tmp, (
                '# 子页面清单 — 注释行\n'
                '\n'
                '- 子页面 | https://x.com/a.html | 备注文字忽略\n'
                '  - 孙页面 | https://x.com/a1.html\n'
                '- | https://x.com/b.html\n'
            ))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['title'], '子页面')
        self.assertEqual(items[0]['url'], 'https://x.com/a.html')
        self.assertEqual(items[0]['children'][0]['title'], '孙页面')
        self.assertEqual(items[1]['title'], 'https://x.com/b.html')

    def test_parse_children_list_deep_indent_skipped(self):
        # 4 空格缩进（超过孙页面层级）→ 跳过并警告，不中断其余行的解析
        with tempfile.TemporaryDirectory() as tmp:
            items = self._write_children_list(tmp, (
                '- 子页面 | https://x.com/a.html\n'
                '  - 孙页面 | https://x.com/a1.html\n'
                '    - 曾孙页面 | https://x.com/a1a.html\n'
                '- 子页面二 | https://x.com/b.html\n'
            ))
        self.assertEqual(len(items), 2)
        self.assertEqual(len(items[0]['children']), 1)
        self.assertEqual(items[1]['title'], '子页面二')

    def test_parse_children_list_missing_url_or_parent_skipped(self):
        # 缺 URL 的行跳过；首行即缩进（无父页面的孙页面）跳过
        with tempfile.TemporaryDirectory() as tmp:
            items = self._write_children_list(tmp, (
                '  - 无父孙页面 | https://x.com/orphan.html\n'
                '- 子页面 | https://x.com/a.html\n'
                '  - 孙页面 |\n'
            ))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], '子页面')
        self.assertEqual(items[0]['children'], [])

    def test_parse_children_list_star_angle_and_errors(self):
        # * 列表标记与 <> 包裹 URL 可解析；文件缺失抛 ValueError；空清单返回 []
        from web2md import parse_children_list
        with tempfile.TemporaryDirectory() as tmp:
            items = self._write_children_list(tmp, (
                '* 子页面 | <https://x.com/a.html>\n'
                '  * 孙页面 | <https://x.com/a1.html>\n'
            ))
            self.assertEqual(items[0]['url'], 'https://x.com/a.html')
            self.assertEqual(items[0]['children'][0]['url'], 'https://x.com/a1.html')
            empty = Path(tmp) / 'empty.md'
            empty.write_text('', encoding='utf-8')
            self.assertEqual(parse_children_list(str(empty)), [])
            with self.assertRaises(ValueError):
                parse_children_list(str(Path(tmp) / 'missing.md'))

    # ── 2026-08-04 补：collect_children 回归（纯锚点 / .html 重定向 / collapsible 分组）──

    def test_collect_children_layout_anchor_not_interfering(self):
        # VitePress 布局锚点 #VPContent / 正文标题锚点先于导航出现时，不得把 current_a
        # 误定位到锚点（去 fragment 后与当前页 URL 相同）→ 子页面仍正常收集
        from nav_children import collect_children
        html = """
        <div class="Layout"><a href="#VPContent">Skip to content</a></div>
        <nav><ul>
        <li><a href="/docs/topic/index.html" class="active">Topic</a>
          <ul>
            <li><a href="/docs/topic/child1.html">Child 1</a></li>
            <li><a href="/docs/topic/child2.html">Child 2</a></li>
          </ul>
        </li>
        </ul></nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(soup, 'https://docs.example.com/docs/topic/index.html')['children']
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0]['title'], 'Child 1')
        self.assertEqual(
            children[1]['url'],
            'https://docs.example.com/docs/topic/child2.html',
        )

    def test_collect_children_plain_page_html_redirect(self):
        # 普通页面（非 index）被服务器重定向为去 .html 形式：导航链接 modules_main
        # （无后缀）与 base_url modules_main.html 归一化后必须匹配，否则误报"无导航子页面"
        from nav_children import collect_children
        html = """
        <nav><ul>
        <li><a href="/modules/modules_main" class="active">Modules Main</a>
          <ul>
            <li><a href="/modules/sub/a.html">Sub A</a></li>
            <li><a href="/modules/sub/b.html">Sub B</a></li>
          </ul>
        </li>
        </ul></nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(soup, 'https://docs.example.com/modules/modules_main.html')['children']
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0]['title'], 'Sub A')
        self.assertEqual(
            children[0]['url'],
            'https://docs.example.com/modules/sub/a.html',
        )

    def test_collect_children_collapsible_group_grandchild(self):
        # VitePress 可展开分组（section.VPSidebarItem level-2 collapsible，非 div.level-2）：
        # 分组下的孙页面必须正确挂载到分组子页面（Drivers）下，而非漏挂
        from nav_children import collect_children
        html = """
        <aside class="VPSidebar"><nav class="nav"><div class="group">
        <section class="VPSidebarItem level-1">
          <div class="item"><a href="/modules/index.html" class="active">Modules</a></div>
          <div class="items">
            <section class="VPSidebarItem level-2 collapsible">
              <div class="item"><a href="/modules/drivers/index.html">Drivers</a></div>
              <div class="items">
                <div class="item"><a href="/modules/drivers/uart.html">UART</a></div>
                <div class="item"><a href="/modules/drivers/gpio.html">GPIO</a></div>
              </div>
            </section>
            <div class="item"><a href="/modules/sched.html">Scheduler</a></div>
          </div>
        </section>
        </div></nav></aside>
        """
        soup = BeautifulSoup(html, 'lxml')
        children = collect_children(soup, 'https://docs.example.com/modules/index.html')['children']
        self.assertEqual(len(children), 2)
        drivers = children[0]
        self.assertEqual(drivers['title'], 'Drivers')
        self.assertEqual(len(drivers['children']), 2)
        self.assertEqual(drivers['children'][0]['title'], 'UART')
        self.assertEqual(
            drivers['children'][1]['url'],
            'https://docs.example.com/modules/drivers/gpio.html',
        )
        self.assertEqual(children[1]['title'], 'Scheduler')
        self.assertEqual(children[1]['children'], [])

    # ── 2026-08-08 补：Sphinx RTD 主题当前项 href="#" 回归 ──

    def test_collect_children_rtd_current_anchor(self):
        # Sphinx RTD 主题（Read the Docs）：当前项导航链接是 href="#" 占位（靠 li.current
        # class 标记当前页），而非页面完整 URL。若按「跳过 # 开头链接」一刀切，current_a
        # 定位失败 → 误报「无导航子页面」（2026-08-08 实测回归：nuttx NSH 页 8 子页面全漏）。
        # 修复：href_raw == '#' 且 urljoin 后 == 当前页 → 参与定位；真实锚点（#VPContent）
        # 仍跳过（test_collect_children_layout_anchor_not_interfering 保证）。
        from nav_children import collect_children
        html = """
        <nav class="wy-nav-side">
        <ul class="current">
        <li class="toctree-l2 current"><a href="#">NuttShell (NSH)</a>
          <ul>
            <li class="toctree-l3"><a href="nsh.html">Overview</a></li>
            <li class="toctree-l3"><a href="commands.html">Commands</a></li>
            <li class="toctree-l3"><a href="config.html">Configuration Settings</a></li>
          </ul>
        </li>
        </ul>
        </nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = collect_children(soup, 'https://nuttx.apache.org/docs/latest/applications/nsh/index.html')
        self.assertEqual(result['structure'], 'sphinx')
        self.assertEqual(len(result['children']), 3)
        self.assertEqual(result['children'][0]['title'], 'Overview')
        self.assertEqual(
            result['children'][1]['url'],
            'https://nuttx.apache.org/docs/latest/applications/nsh/commands.html',
        )
        # notes 应说明定位成功（诊断供 AI 判断，不静默空结果）
        self.assertTrue(any('定位成功' in n for n in result['notes']))

    def test_collect_children_rtd_no_children_notes(self):
        # RTD 叶子页：当前项 href="#" 但无嵌套子页面容器 → children 空，notes 说明原因
        # （AI 据此判断「真没有」而非「漏识别」，不需要再访问页面）
        from nav_children import collect_children
        html = """
        <nav class="wy-nav-side">
        <ul class="current">
        <li class="toctree-l1 current"><a href="#">Leaf Page</a></li>
        </ul>
        </nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = collect_children(soup, 'https://nuttx.apache.org/docs/latest/applications/leaf.html')
        self.assertEqual(result['structure'], 'sphinx')
        self.assertEqual(result['children'], [])
        self.assertTrue(any('叶子页' in n or '无嵌套' in n or '定位成功' in n for n in result['notes']))

    def test_collect_children_layout_anchor_still_skipped(self):
        # 回归防护：VitePress 布局锚点 #VPContent 等真实锚点仍必须跳过——即使 urljoin 后
        # 去 fragment 与当前页相同，也不能参与 current_a 定位（会误定位到布局元素）。
        # 与 test_collect_children_layout_anchor_not_interfering 呼应，此处验证 unknown
        # 结构时 notes 给出未命中原因。
        from nav_children import collect_children
        html = """
        <div class="Layout"><a href="#VPContent">Skip to content</a></div>
        <nav><ul>
        <li><a href="/docs/topic/index.html" class="active">Topic</a>
          <ul>
            <li><a href="/docs/topic/child1.html">Child 1</a></li>
          </ul>
        </li>
        </ul></nav>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = collect_children(soup, 'https://docs.example.com/docs/topic/index.html')
        self.assertEqual(result['structure'], 'generic')
        self.assertEqual(len(result['children']), 1)
        self.assertEqual(result['children'][0]['title'], 'Child 1')


if __name__ == '__main__':
    unittest.main()
