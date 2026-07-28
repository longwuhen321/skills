import os
import subprocess
import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent
WORK_DIR = Path(os.environ.get('WEB2MD_TEST_WORKDIR', TEST_DIR))
sys.path.insert(0, str(SCRIPT_DIR))

from web2md import html_to_markdown, normalize_document_html, process_math_formulas


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


if __name__ == '__main__':
    unittest.main()
