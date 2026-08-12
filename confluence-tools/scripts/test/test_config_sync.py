import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
CHECKER = SCRIPT_DIR / 'check_config_sync.py'

GROUPS = ('common_config,import_config,upgrade_config,toc_upgrade_config,'
          'export_config,debug_config')

EXAMPLE_TEXT = (
    "common_config = {'python_path': 'x', 'confluence_token': 'placeholder'}\n"
    "import_config = {'space': 'ALG', 'toc_enabled': True}\n"
    "upgrade_config = {'recursive': True}\n"
    "toc_upgrade_config = {'target_macro': 'easy_heading'}\n"
    "export_config = {'output_dir': 'out'}\n"
    "debug_config = {'max_size_mb': 50}\n"
)

CONFIG_TEXT = (
    "common_config = {'python_path': 'D:/py/python.exe', 'confluence_token': 'test-token'}\n"
    "import_config = {'space': 'ES', 'toc_enabled': False}\n"
    "upgrade_config = {'recursive': False}\n"
    "toc_upgrade_config = {'target_macro': 'toc'}\n"
    "export_config = {'output_dir': 'D:/out'}\n"
    "debug_config = {'max_size_mb': 20}\n"
)


def run_checker(args):
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )


class ConfigSyncTests(unittest.TestCase):
    def test_tmp_pair_synced_passes(self):
        """临时六分组 example/config 键集一致 → 退出码 0（值不同不误报）。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text(EXAMPLE_TEXT, encoding='utf-8')
            config.write_text(CONFIG_TEXT, encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', f'--groups={GROUPS}'])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_default_six_groups_passes(self):
        """不传 --groups 时也必须完整检查默认六分组。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text(EXAMPLE_TEXT, encoding='utf-8')
            config.write_text(CONFIG_TEXT, encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
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

    def test_tmp_pair_both_missing_requested_group_fails(self):
        """请求的分组在 example/config 双方都不存在，也必须显式失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            text = "common_config = {'python_path': 'x'}\n"
            example.write_text(text, encoding='utf-8')
            config.write_text(text, encoding='utf-8')
            result = run_checker([
                f'--example-file={example}',
                f'--config-file={config}',
                '--groups=common_config,import_config',
            ])
            self.assertEqual(result.returncode, 1)
            self.assertIn('import_config', result.stdout)

    def test_tmp_pair_both_missing_default_group_fails(self):
        """默认六分组中的任一组在双方都缺失，也必须显式失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            missing_debug_example = EXAMPLE_TEXT.replace(
                "debug_config = {'max_size_mb': 50}\n", '')
            missing_debug_config = CONFIG_TEXT.replace(
                "debug_config = {'max_size_mb': 20}\n", '')
            example.write_text(missing_debug_example, encoding='utf-8')
            config.write_text(missing_debug_config, encoding='utf-8')
            result = run_checker([
                f'--example-file={example}',
                f'--config-file={config}',
            ])
            self.assertEqual(result.returncode, 1)
            self.assertIn('debug_config', result.stdout)

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

    def test_tmp_pair_side_effect_is_rejected_without_execution(self):
        """配置含函数调用 → 退出码 2，且检查过程不执行副作用。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            marker = Path(tmp) / 'must-not-exist.txt'
            example.write_text(EXAMPLE_TEXT, encoding='utf-8')
            config.write_text(
                CONFIG_TEXT
                + f"__import__('pathlib').Path({str(marker)!r}).write_text('owned')\n",
                encoding='utf-8')
            result = run_checker([
                f'--example-file={example}',
                f'--config-file={config}',
            ])
            self.assertEqual(result.returncode, 2)
            self.assertFalse(marker.exists())

    def test_tmp_pair_non_utf8_config_is_unverifiable(self):
        """配置不是 UTF-8 → 退出码 2，不泄漏未捕获 traceback。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text(EXAMPLE_TEXT, encoding='utf-8')
            config.write_bytes(b'\xff')
            result = run_checker([
                f'--example-file={example}',
                f'--config-file={config}',
            ])
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)

    def test_config_text_stdin(self):
        """--config-text 从 stdin 读取配置文本：缺键判失败、补齐判通过。"""
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

    @unittest.skipUnless(sys.platform == 'win32', 'Windows console encoding only')
    def test_utf8_mode_overrides_gbk_console_for_validation_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / '不存在-example.py'
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'cp936'
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            result = subprocess.run(
                [sys.executable, '-X', 'utf8', str(CHECKER),
                 f'--example-file={missing}'],
                capture_output=True, text=True, encoding='utf-8', env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('example 配置文件缺失', result.stdout)
            self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
