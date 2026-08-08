import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
CHECKER = SCRIPT_DIR / 'check_config_sync.py'
EXAMPLE = SCRIPT_DIR.parent / 'config.example.py'
REAL_CONFIG = SCRIPT_DIR / 'config.py'

GROUPS = 'common_config,import_config,upgrade_config,export_config,debug_config'


def run_checker(args):
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )


class ConfigSyncTests(unittest.TestCase):
    def test_real_config_synced_passes(self):
        """现状：真实 config.py 五分组键与 example 一致，检查必须通过（退出码 0）。"""
        result = run_checker([f'--example-file={EXAMPLE}', f'--config-file={REAL_CONFIG}'])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_synced_passes(self):
        """临时 example/config 键集一致 → 退出码 0（值不同不误报）。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text(
                "common_config = {'python_path': 'x', 'confluence_token': 'placeholder'}\n"
                "import_config = {'space': 'ALG', 'toc_enabled': True}\n", encoding='utf-8')
            config.write_text(
                "common_config = {'python_path': 'D:/py/python.exe', 'confluence_token': 'real-token'}\n"
                "import_config = {'space': 'ES', 'toc_enabled': False}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', f'--groups={GROUPS}'])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_missing_group_fails(self):
        """config.py 缺整个分组 → 退出码 1，报 missing。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text(
                "common_config = {'python_path': 'x'}\n"
                "import_config = {'space': 'ALG'}\n", encoding='utf-8')
            config.write_text("common_config = {'python_path': 'D:/py/python.exe'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', '--groups=common_config,import_config'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('import_config', result.stdout)

    def test_tmp_pair_missing_key_fails(self):
        """config.py 分组内缺键 → 退出码 1，报 missing。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text(
                "common_config = {'python_path': 'x', 'confluence_url': 'http://x'}\n", encoding='utf-8')
            config.write_text("common_config = {'python_path': 'D:/py/python.exe'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', '--groups=common_config'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('confluence_url', result.stdout)

    def test_tmp_pair_extra_key_fails(self):
        """config.py 多出 example 没有的键 → 退出码 1，报 extra（键名漂移）。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("debug_config = {'max_size_mb': 50}\n", encoding='utf-8')
            config.write_text("debug_config = {'max_size_mb': 50, 'typo_opt': True}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', '--groups=debug_config'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('typo_opt', result.stdout)

    def test_tmp_pair_type_mismatch_fails(self):
        """同键类型不一致（max_size_mb 字符串 vs int）→ 退出码 1，报 type。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("debug_config = {'max_size_mb': 50}\n", encoding='utf-8')
            config.write_text("debug_config = {'max_size_mb': '50'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', '--groups=debug_config'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('type', result.stdout)
            self.assertIn('max_size_mb', result.stdout)

    def test_tmp_pair_missing_config_file(self):
        """config.py 不存在 → 退出码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            example.write_text("debug_config = {'max_size_mb': 50}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={Path(tmp) / "nope.py"}'])
            self.assertEqual(result.returncode, 2)

    def test_tmp_pair_broken_config_fails(self):
        """config.py 损坏（语法错误）→ 退出码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("debug_config = {'max_size_mb': 50}\n", encoding='utf-8')
            config.write_text("debug_config = {'max_size_mb':\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 2)

    def test_config_text_stdin(self):
        """--config-text 从 stdin 读取真实配置：缺键判失败、补齐判通过。"""
        example_text = "common_config = {'python_path': 'x', 'confluence_url': 'http://x'}\n"
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            example.write_text(example_text, encoding='utf-8')
            fail = subprocess.run(
                [sys.executable, str(CHECKER), f'--example-file={example}', '--config-text', '--groups=common_config'],
                input="common_config = {'python_path': 'D:/py/python.exe'}\n",
                capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(fail.returncode, 1)
            self.assertIn('confluence_url', fail.stdout)
            ok = subprocess.run(
                [sys.executable, str(CHECKER), f'--example-file={example}', '--config-text', '--groups=common_config'],
                input="common_config = {'python_path': 'D:/py/python.exe', 'confluence_url': 'http://real'}\n",
                capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(ok.returncode, 0, ok.stdout)


if __name__ == '__main__':
    unittest.main()
