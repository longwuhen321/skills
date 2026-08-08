import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
CHECKER = SCRIPT_DIR / 'check_config_sync.py'
EXAMPLE = SCRIPT_DIR.parent / 'config.example.py'
REAL_CONFIG = SCRIPT_DIR / 'config.py'


def run_checker(args):
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
    )


class ConfigSyncTests(unittest.TestCase):
    def test_real_config_synced_passes(self):
        """现状：真实 config.py 与 example 键集一致（5 个键），检查必须通过（退出码 0）。"""
        result = run_checker([f'--example-file={EXAMPLE}', f'--config-file={REAL_CONFIG}'])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_synced_passes(self):
        """临时 example/config 键集一致 → 退出码 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("md2zh_config = {'python_path': 'x', 'max_block_chars': 16000}\n", encoding='utf-8')
            config.write_text("md2zh_config = {'python_path': 'D:/py/python.exe', 'max_block_chars': 20000}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_tmp_pair_missing_key_fails(self):
        """config.py 缺键 → 退出码 1，报 missing。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("md2zh_config = {'python_path': 'x', 'output_dir': ''}\n", encoding='utf-8')
            config.write_text("md2zh_config = {'python_path': 'D:/py/python.exe'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('missing', result.stdout)
            self.assertIn('output_dir', result.stdout)

    def test_tmp_pair_extra_key_fails(self):
        """config.py 多出 example 没有的键 → 退出码 1，报 extra（键名漂移）。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("md2zh_config = {'python_path': 'x'}\n", encoding='utf-8')
            config.write_text("md2zh_config = {'python_path': 'x', 'typo_opt': True}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('extra', result.stdout)
            self.assertIn('typo_opt', result.stdout)

    def test_tmp_pair_type_mismatch_fails(self):
        """同键类型不一致（max_block_chars 字符串 vs int）→ 退出码 1，报 type。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("md2zh_config = {'max_block_chars': 16000}\n", encoding='utf-8')
            config.write_text("md2zh_config = {'max_block_chars': '16000'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 1)
            self.assertIn('type', result.stdout)
            self.assertIn('max_block_chars', result.stdout)

    def test_tmp_pair_missing_config_file(self):
        """config.py 不存在 → 退出码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            example.write_text("md2zh_config = {'python_path': 'x'}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={Path(tmp) / "nope.py"}'])
            self.assertEqual(result.returncode, 2)

    def test_tmp_pair_broken_config_fails(self):
        """config.py 损坏（语法错误）→ 退出码 2。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("md2zh_config = {'python_path': 'x'}\n", encoding='utf-8')
            config.write_text("md2zh_config = {'python_path':\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 2)

    def test_config_text_stdin(self):
        """--config-text 从 stdin 读取真实配置：缺键判失败、补齐判通过。"""
        example_text = "md2zh_config = {'python_path': 'x', 'output_dir': ''}\n"
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            example.write_text(example_text, encoding='utf-8')
            fail = subprocess.run(
                [sys.executable, str(CHECKER), f'--example-file={example}', '--config-text'],
                input="md2zh_config = {'python_path': 'D:/py/python.exe'}\n",
                capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(fail.returncode, 1)
            self.assertIn('output_dir', fail.stdout)
            ok = subprocess.run(
                [sys.executable, str(CHECKER), f'--example-file={example}', '--config-text'],
                input="md2zh_config = {'python_path': 'D:/py/python.exe', 'output_dir': ''}\n",
                capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(ok.returncode, 0, ok.stdout)

    def test_group_custom(self):
        """--group 指定非默认分组名。"""
        with tempfile.TemporaryDirectory() as tmp:
            example = Path(tmp) / 'example.py'
            config = Path(tmp) / 'config.py'
            example.write_text("other_config = {'alpha': 1}\n", encoding='utf-8')
            config.write_text("other_config = {'alpha': 1}\n", encoding='utf-8')
            result = run_checker([f'--example-file={example}', f'--config-file={config}', '--group=other_config'])
            self.assertEqual(result.returncode, 0, result.stdout)
            # 未传 --group 时默认查 md2zh_config，其他分组视为缺失
            result2 = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result2.returncode, 2)


if __name__ == '__main__':
    unittest.main()
