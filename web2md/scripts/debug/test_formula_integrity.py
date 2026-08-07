import os
import subprocess
import sys
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT_DIR = TEST_DIR.parent
WORK_DIR = Path(os.environ.get('WEB2MD_TEST_WORKDIR', TEST_DIR))
FIXER = SCRIPT_DIR / 'fix_escapes.py'
PROMOTER = SCRIPT_DIR / 'list_display_fixes.py'
FINDER = SCRIPT_DIR / 'find_all_missed.py'
VERIFIER = SCRIPT_DIR / 'final_verify.py'


class FormulaIntegrityTests(unittest.TestCase):
    def run_script(self, script, markdown, *args):
        path = WORK_DIR / ('_sample_' + self._testMethodName + '.md')
        try:
            path.write_text(markdown, encoding='utf-8')
            result = subprocess.run(
                [sys.executable, str(script), str(path), *args],
                capture_output=True,
                text=True,
                encoding='utf-8',
            )
            return result, path.read_text(encoding='utf-8')
        finally:
            path.unlink(missing_ok=True)

    def test_apply_promotes_display_without_changing_payload(self):
        payload = (
            r'{\displaystyle {\begin{aligned}'
            r'\pi _{0}(O)&=\mathbf {Z} /2\mathbf {Z} \\'
            r'\pi _{1}(O)&=\mathbf {Z} /2\mathbf {Z} '
            r'\end{aligned}}}'
        )
        result, updated = self.run_script(
            PROMOTER,
            'Before $' + payload + '$ after\n',
            '--apply',
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('$$\n' + payload + '\n$$', updated)
        self.assertNotIn('$' + payload + '$', updated.replace('$$', ''))
        self.assertEqual(updated.count(payload), 1)

    def test_dry_run_does_not_modify_document(self):
        payload = r'{\begin{bmatrix}a&b\\c&d\end{bmatrix}}'
        original = '$' + payload + '$\n'
        result, updated = self.run_script(PROMOTER, original)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(updated, original)

    def test_promoter_ignores_code_and_promotes_latex(self):
        payload = r'\begin{aligned}a&=1\\b&=2\end{aligned}'
        markdown = (
            '`$\\begin{aligned}inline\\\\code\\end{aligned}$`\n'
            '> ```\n'
            '> $\\begin{aligned}fenced\\\\code\\end{aligned}$\n'
            '> ```\n'
            'Outside $' + payload + '$ after.\n'
        )
        result, updated = self.run_script(PROMOTER, markdown, '--apply')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('已自动转换且保持公式正文不变：1', result.stdout)
        self.assertIn(
            '`$\\begin{aligned}inline\\\\code\\end{aligned}$`', updated
        )
        self.assertIn(
            '> $\\begin{aligned}fenced\\\\code\\end{aligned}$', updated
        )
        self.assertIn('$$\n' + payload + '\n$$', updated)

    def test_fixer_ignores_code_and_fixes_outside_text(self):
        markdown = (
            'Inline `code\\_value and code\\*value`\n'
            '```sh\n'
            'code\\_value code\\*value $name\n'
            '```\n'
            'Outside $x\\_{1}^{\\*}$ and prose\\_value.\n'
        )
        result, updated = self.run_script(FIXER, markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('`code\\_value and code\\*value`', updated)
        self.assertIn('code\\_value code\\*value $name', updated)
        self.assertIn('Outside $x_{1}^{*}$ and prose_value.', updated)

    def test_finder_ignores_code_and_reports_outside_candidate(self):
        markdown = (
            'Inline `*x*2`\n'
            '```\n'
            '*i*2\n'
            '```\n'
            'Outside *a*1\n'
        )
        result, _ = self.run_script(FINDER, markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('行 5:', result.stdout)
        self.assertIn("斜体: ['*a*1']", result.stdout)
        self.assertNotIn('*x*2', result.stdout)
        self.assertNotIn('*i*2', result.stdout)

    def test_verifier_rejects_missing_close_brace(self):
        broken = (
            '$$\n'
            r'{\displaystyle {\begin{aligned}a&=1\\b&=2\end{aligned}}'
            '\n$$\n'
        )
        result, _ = self.run_script(VERIFIER, broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('LaTeX 花括号不平衡', result.stdout)

    def test_verifier_accepts_balanced_formula(self):
        valid = (
            '$$\n'
            r'{\displaystyle {\begin{aligned}a&=1\\b&=2\end{aligned}}}'
            '\n$$\n'
        )
        result, _ = self.run_script(VERIFIER, valid)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_verifier_accepts_literal_braces_in_aligned_formula(self):
        valid = (
            '$$\n'
            r'{\displaystyle {\begin{aligned}'
            r'f(t)&={\mathcal {L}}^{-1}\{F(s)\}\\'
            r'g(t)&={\mathcal {L}}^{-1}\{G(s)\}'
            r'\end{aligned}}}'
            '\n$$\n'
        )
        result, _ = self.run_script(VERIFIER, valid)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_verifier_ignores_latex_like_content_in_code(self):
        valid = (
            r'Inline `$x\_{1}^{\*} \left{ \begin{aligned}$`'
            '\n```text\n'
            '$$not a display formula$$\n'
            '$x\\_{1}$ \\left{ \\begin{aligned}\n'
            '```\n'
            r'Outside $\{x\}$ is valid.'
            '\n'
        )
        result, _ = self.run_script(VERIFIER, valid)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unclosed_inline_backtick_does_not_hide_latex(self):
        broken = 'Literal unclosed ` marker\nOutside $x\\_{1}$\n'
        result, _ = self.run_script(VERIFIER, broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('存在转义下划线', result.stdout)

    def test_verifier_rejects_missing_aligned_end(self):
        broken = (
            '$$\n'
            r'{\displaystyle {\begin{aligned}a&=1\\b&=2}}'
            '\n$$\n'
        )
        result, _ = self.run_script(VERIFIER, broken)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('aligned 公式包含损坏转义', result.stdout)

    def test_fixer_fixes_display_math_block(self):
        # $$ 块内的 \_ 转义也应修复（阶段 A 覆盖 display math）
        markdown = '$$\nx\\_{1}\n$$\n'
        result, updated = self.run_script(FIXER, markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('x_{1}', updated)

    def test_finder_skips_table_rows(self):
        # 表格行（| 开头）不当作伪公式候选
        markdown = '| *x*1 |\nOutside *a*1\n'
        result, _ = self.run_script(FINDER, markdown)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('行 2:', result.stdout)
        self.assertNotIn('行 1:', result.stdout)


if __name__ == '__main__':
    unittest.main()
