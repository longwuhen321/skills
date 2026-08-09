import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import web2md
from merge_paragraphs import merge_markdown_paragraphs


FIXER = SCRIPT_DIR / 'fix_escapes.py'
VERIFIER = SCRIPT_DIR / 'final_verify.py'


class ConfigRegressionTests(unittest.TestCase):
    def test_load_config_preserves_explicit_false_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.py'
            config.write_text(
                "web2md_config = {"
                "'page_nav': False, 'table_formula_inline': False, "
                "'collect_children': False, 'merge_paragraphs': False, "
                "'unknown_option': 'ignored'}\n",
                encoding='utf-8',
            )
            with patch.object(web2md, 'CONFIG_PATH', str(config)):
                loaded = web2md.load_config()
        self.assertIs(loaded['page_nav'], False)
        self.assertIs(loaded['table_formula_inline'], False)
        self.assertIs(loaded['collect_children'], False)
        self.assertIs(loaded['merge_paragraphs'], False)
        self.assertNotIn('unknown_option', loaded)


class MergeParagraphRegressionTests(unittest.TestCase):
    def test_fenced_code_and_display_math_are_byte_preserved(self):
        markdown = (
            'alpha\nbeta\n\n'
            '```python\nvalue = 1\nvalue += 2\n\nprint(value)\n```\n\n'
            '~~~text\nfirst\nsecond\n~~~\n\n'
            '$$\na &= 1\\\\\nb &= 2\n\n\\text{done}\n$$\n\n'
            'gamma\ndelta\n'
        )
        merged = merge_markdown_paragraphs(markdown)
        self.assertIn('alpha beta', merged)
        self.assertIn(
            '```python\nvalue = 1\nvalue += 2\n\nprint(value)\n```',
            merged,
        )
        self.assertIn('~~~text\nfirst\nsecond\n~~~', merged)
        self.assertIn(
            '$$\na &= 1\\\\\nb &= 2\n\n\\text{done}\n$$',
            merged,
        )
        self.assertIn('gamma delta', merged)


class ChildFailureRegressionTests(unittest.TestCase):
    def test_grandchild_failure_makes_batch_fail_but_keeps_successes(self):
        tree = [{
            'title': 'Child',
            'url': 'https://example.test/child',
            'children': [{
                'title': 'Grandchild',
                'url': 'https://example.test/grandchild',
                'children': [],
            }],
        }]

        def fake_fetch(url, session, timeout):
            if url.endswith('/grandchild'):
                raise RuntimeError('offline fixture failure')
            return url, url, '<html></html>'

        def fake_title(soup):
            return 'Root' if soup.endswith('/root') else 'Child'

        def fake_process(soup, final_url, raw_html, title, output_root, cfg, session):
            folder = title
            article_dir = Path(output_root) / folder
            article_dir.mkdir(parents=True, exist_ok=True)
            md_path = article_dir / f'{folder}.md'
            md_path.write_text(f'# {title}\n', encoding='utf-8')
            return folder, md_path

        cfg = {'timeout': 1, 'page_nav': False}
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with patch.object(web2md, 'fetch_page', side_effect=fake_fetch), \
                    patch.object(web2md, 'extract_title', side_effect=fake_title), \
                    patch.object(web2md, 'process_page', side_effect=fake_process), \
                    contextlib.redirect_stdout(output):
                ok = web2md.fetch_and_process(
                    'https://example.test/root', Path(tmp), cfg, object(),
                    children_mode=True, children_list=tree,
                )
            self.assertFalse(ok)
            self.assertTrue((Path(tmp) / 'Root' / 'Child' / 'Child.md').is_file())
            self.assertIn('https://example.test/grandchild', output.getvalue())


class FormulaAndVerifierRegressionTests(unittest.TestCase):
    def run_script(self, script, markdown):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.md'
            path.write_text(markdown, encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(script), str(path)],
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
            updated = path.read_text(encoding='utf-8')
        return result, updated

    def test_fixer_only_changes_math_not_prose_or_code(self):
        markdown = (
            r'Prose keeps literal\_underscore and literal\*star.' '\n'
            r'Inline `$code\_value$` stays.' '\n'
            '```text\nmath-looking $code\\_value$\n```\n'
            r'Formula $x\_{1}^{\*}$ changes.' '\n'
            '$$\ny\\_{2} + z\\*\n$$\n'
        )
        result, updated = self.run_script(FIXER, markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(r'literal\_underscore and literal\*star', updated)
        self.assertIn(r'`$code\_value$`', updated)
        self.assertIn(r'$code\_value$', updated)
        self.assertIn(r'$x_{1}^{*}$', updated)
        self.assertIn('$$\ny_{2} + z*\n$$', updated)

    def test_verifier_ignores_table_and_image_examples_in_code(self):
        markdown = (
            '```markdown\n'
            '| a | b |\n'
            '| --- | --- |\n'
            '| 1 | 2 |\n'
            'next-without-table-blank\n'
            '![example](missing.png)\n'
            '```\n'
            '`![inline](also-missing.png)`\n'
        )
        result, _ = self.run_script(VERIFIER, markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_verifier_rejects_fence_immediately_after_table(self):
        markdown = (
            '| a |\n'
            '| --- |\n'
            '```text\n'
            'code\n'
            '```\n'
        )
        result, _ = self.run_script(VERIFIER, markdown)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('表格后缺空行', result.stdout)

    def test_verifier_rejects_dangling_unescaped_dollar(self):
        result, _ = self.run_script(VERIFIER, 'Dangling $x has no close.\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未配对的 $ 定界符', result.stdout)

    def test_verifier_accepts_escaped_dollar(self):
        result, _ = self.run_script(VERIFIER, r'Literal \$ is not math.' + '\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
