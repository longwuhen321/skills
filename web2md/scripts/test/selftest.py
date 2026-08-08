"""web2md 离线测试入口：运行 tests/ 下全部测试模块。

用法：python selftest.py
修改 scripts/ 下的脚本后必须运行本入口，全部用例通过才算完成。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

loader = unittest.TestLoader()
suite = loader.discover(str(Path(__file__).resolve().parent), pattern='test_*.py')
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
