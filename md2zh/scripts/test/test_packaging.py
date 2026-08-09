import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent.parent
CHECKER = SCRIPT_DIR / 'package_check.py'


def run_checker(root):
    return subprocess.run(
        [sys.executable, str(CHECKER), '--root', str(root)],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )


class PackagingCheckTests(unittest.TestCase):
    def test_clean_staging_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'SKILL.md').write_text('# test\n', encoding='utf-8')
            (root / 'config.example.py').write_text(
                "md2zh_config = {'python_path': '/path/to/python'}\n",
                encoding='utf-8',
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_forbidden_paths_are_rejected_without_reading_their_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'scripts' / 'config.py').write_bytes(b'\xff\xfeprivate')
            (root / '.env.local').write_bytes(b'\xff\xfeprivate')
            logs = root / 'logs'
            logs.mkdir()
            (logs / 'token.txt').write_bytes(b'\xff\xfeprivate')
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            paths = {item['path'] for item in payload['issues']}
            self.assertIn('scripts/config.py', paths)
            self.assertIn('.env.local', paths)
            self.assertIn('logs', paths)

    def test_sensitive_literal_in_allowed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'unsafe.py').write_text(
                "confluence_" + "token = 'sk-" + "live-abcdefghijklmnopqrstuvwxyz012345'\n",
                encoding='utf-8',
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertTrue(any(item['code'] == 'sensitive-value' for item in payload['issues']))

    def test_known_secret_in_markdown_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'README.md').write_text(
                'accidental credential: sk-proj-' + 'abcdefghijklmnopqrstuvwxyz012345\n',
                encoding='utf-8',
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertTrue(any(item['path'] == 'README.md' for item in payload['issues']))

    def test_unquoted_token_in_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes.txt').write_text(
                'access_token=anotherOpaqueValue0123456789\n',
                encoding='utf-8',
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertTrue(any(item['path'] == 'notes.txt' for item in payload['issues']))

    def test_placeholder_sensitive_literal_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config.example.py').write_text(
                "api_token = '<YOUR_TOKEN>'\n",
                encoding='utf-8',
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_python_token_processing_expression_is_not_a_secret_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'helper.py').write_text(
                'TOKEN_RE = re.compile(r"token[:=](.+)")\n',
                encoding='utf-8',
            )
            result = run_checker(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_allowed_text_read_error_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'broken.py').write_bytes(b'\xff\xfe')
            result = run_checker(root)
            self.assertEqual(result.returncode, 2)
            self.assertIn('error', result.stdout)


if __name__ == '__main__':
    unittest.main()
