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
    def test_example_derived_fixture_synced_passes(self):
        """由脱敏 example 构造临时 config；测试不读取本机真实 config.py。"""
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

    def test_unsafe_python_is_rejected_without_side_effects(self):
        """import/函数调用属于副作用代码；检查器拒绝且绝不执行。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = root / 'example.py'
            config = root / 'config.py'
            sentinel = root / 'must-not-exist.txt'
            example.write_text("md2zh_config = {'python_path': 'x'}\n", encoding='utf-8')
            config.write_text(
                "from pathlib import Path\n"
                f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
                "md2zh_config = {'python_path': 'x'}\n",
                encoding='utf-8',
            )
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 2)
            self.assertIn('不允许', result.stdout)
            self.assertFalse(sentinel.exists())

    def test_annotation_call_is_rejected_without_running(self):
        """类型注解中的函数调用也必须被语法门禁直接拒绝。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = root / 'example.py'
            config = root / 'config.py'
            sentinel = root / 'must-not-exist.txt'
            example.write_text("md2zh_config = {'python_path': 'x'}\n", encoding='utf-8')
            config.write_text(
                f"md2zh_config: open({str(sentinel)!r}, 'w').write('executed') = "
                "{'python_path': 'x'}\n",
                encoding='utf-8',
            )
            result = run_checker([f'--example-file={example}', f'--config-file={config}'])
            self.assertEqual(result.returncode, 2)
            self.assertFalse(sentinel.exists())

    def test_config_text_stdin(self):
        """--config-text 从 stdin 读取临时配置文本：缺键判失败、补齐判通过。"""
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
