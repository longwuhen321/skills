import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
CHECKER = SCRIPT_DIR / 'check_config_sync.py'
EXAMPLE = SCRIPT_DIR.parent / 'config.example.py'


def run_checker(args):
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )


class ConfigSyncTests(unittest.TestCase):
    def test_example_derived_fixture_passes(self):
        """由公开 example 构造临时配置，不读取本机 scripts/config.py。"""
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config.py'
            config.write_text(EXAMPLE.read_text(encoding='utf-8'), encoding='utf-8')
            result = run_checker([f'--example-file={EXAMPLE}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_synced_passes(self):
        """临时 example/config 键集一致 → 退出码 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("web2md_config = {'python_path': 'x', 'timeout': 30}\n", encoding='utf-8')
            config.write_text("web2md_config = {'python_path': 'D:/py/python.exe', 'timeout': 30}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_missing_key_fails(self):
        """config.py 缺键 → 退出码 1，报 missing。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("web2md_config = {'python_path': 'x', 'timeout': 30}\n", encoding='utf-8')
            config.write_text("web2md_config = {'python_path': 'D:/py/python.exe'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('missing', result.stdout)
            self.assertIn('timeout', result.stdout)

    def test_tmp_pair_extra_key_fails(self):
        """config.py 多出 example 没有的键 → 退出码 1，报 extra（键名漂移）。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("web2md_config = {'timeout': 30}\n", encoding='utf-8')
            config.write_text("web2md_config = {'timeout': 30, 'typo_opt': True}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('extra', result.stdout)
            self.assertIn('typo_opt', result.stdout)

    def test_tmp_pair_type_mismatch_fails(self):
        """同键类型不一致（timeout 字符串 vs int）→ 退出码 1，报 type。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("web2md_config = {'timeout': 30}\n", encoding='utf-8')
            config.write_text("web2md_config = {'timeout': '30'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('type', result.stdout)
            self.assertIn('timeout', result.stdout)

    def test_tmp_pair_missing_config_file(self):
        """config.py 不存在 → 退出码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            example.write_text("web2md_config = {'timeout': 30}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={Path(tmp) / "nope.py"}'])
            self.assertEqual(result.returncode, 2)

    def test_tmp_pair_broken_config_fails(self):
        """config.py 损坏（语法错误）→ 退出码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("web2md_config = {'timeout': 30}\n", encoding='utf-8')
            config.write_text("web2md_config = {'timeout':\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 2)

    def test_config_text_stdin(self):
        """--config-text 从 stdin 读取临时配置文本：缺键判失败、补齐判通过。"""
        example_text = "web2md_config = {'timeout': 30, 'page_nav': True}\n"
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            example.write_text(example_text, encoding='utf-8')
            fail = subprocess.run(
                [sys.executable, str(CHECKER), f'--example-file={example}', '--config-text'],
                input="web2md_config = {'timeout': 30}\n", capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(fail.returncode, 1)
            self.assertIn('page_nav', fail.stdout)
            ok = subprocess.run(
                [sys.executable, str(CHECKER), f'--example-file={example}', '--config-text'],
                input="web2md_config = {'timeout': 30, 'page_nav': True}\n",
                capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(ok.returncode, 0, ok.stdout)


if __name__ == '__main__':
    unittest.main()
