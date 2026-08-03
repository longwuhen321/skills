"""
md2zh_pipeline 离线自测（不依赖网络/外部服务）

运行: python selftest.py

覆盖: 配置写入、分块提取（PROTECT 保护）、逐块验证契约、合并、
      确定性渲染（字节级一致）、verify 通过/拒绝。

所有用例用 subprocess 黑盒跑 pipeline CLI，mock 掉网络与外部服务。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent   # md2zh/scripts
PIPELINE = HERE / 'md2zh_pipeline.py'

SAMPLE = (
    '# Title\n\n'
    'Hello **world** with $x$ inline.\n\n'
    '```python\nprint("code")\n```\n\n'
    '| A | B |\n|---|---|\n| 1 | 2 |\n'
)


def run_pipeline(*args):
    return subprocess.run([sys.executable, str(PIPELINE), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8')


class TestPipeline(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.src = self.root / 'doc.md'
        self.src.write_text(SAMPLE, encoding='utf-8')
        self.task = self.root / '.md2zh_tools' / 'intermediate' / 'task-1'
        self.task.mkdir(parents=True)   # run 目录由 plan-blocks 创建（要求空/已有 manifest）

    def tearDown(self):
        self.td.cleanup()

    def _configure(self, decider='user'):
        r = run_pipeline('configure', self.root, '--decider', decider,
                         '--python-mode', 'explicit', '--python-path', sys.executable)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def _extract(self):
        state = self.root / 'state.json'
        blocks = self.root / 'blocks.json'
        r = run_pipeline('extract', self.src, '--state', state, '--blocks', blocks,
                         '--project-root', self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        return state, blocks

    def _plan(self, state):
        r = run_pipeline('plan-blocks', state, self.task / 'run')
        self.assertEqual(r.returncode, 0, r.stderr)

    def _write_output(self, transform=None):
        inp = self.task / 'run' / 'blocks' / 'block-0001.input.txt'
        out = self.task / 'run' / 'blocks' / 'block-0001.output.txt'
        text = inp.read_text(encoding='utf-8')
        if transform:
            text = transform(text)
        out.write_text(text, encoding='utf-8')
        return out

    def test_help(self):
        r = run_pipeline('--help')
        self.assertEqual(r.returncode, 0)
        self.assertIn('usage', r.stdout.lower())

    def test_configure_writes_project_config(self):
        self._configure()
        cfg = self.root / '.md2zh_tools' / 'config.json'
        self.assertTrue(cfg.exists())
        data = json.loads(cfg.read_text(encoding='utf-8'))
        self.assertEqual(data['ambiguous_content_decider'], 'user')

    def test_configure_accepts_ai_decider(self):
        self._configure(decider='ai')
        cfg = self.root / '.md2zh_tools' / 'config.json'
        data = json.loads(cfg.read_text(encoding='utf-8'))
        self.assertEqual(data['ambiguous_content_decider'], 'ai')

    def test_extract_protects_code_and_math(self):
        self._configure()
        _state, blocks = self._extract()
        data = json.loads(blocks.read_text(encoding='utf-8'))
        unit_count = sum(b.get('unit_count', 0) for b in data['translation_blocks'])
        self.assertGreaterEqual(unit_count, 1)
        self.assertIn('PROTECT', json.dumps(data))       # 代码/粗体/公式被保护

    def test_full_pipeline_roundtrip(self):
        self._configure()
        state, _ = self._extract()
        self._plan(state)
        self._write_output()                              # 原样翻译
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        translations = self.task / 'translations.json'
        r = run_pipeline('merge-blocks', state, self.task / 'run' / 'manifest.json', translations)
        self.assertEqual(r.returncode, 0, r.stderr)
        candidate = self.task / 'candidate.md'
        r = run_pipeline('render', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_pipeline('verify', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"pass": true', r.stdout)
        # 原样翻译 → candidate 与源字节级一致（确定性渲染）
        self.assertEqual(candidate.read_bytes(), self.src.read_bytes())

    def test_validate_rejects_missing_segment(self):
        self._configure()
        state, _ = self._extract()
        self._plan(state)
        self._write_output(lambda t: '\n'.join(t.splitlines()[1:]) + '\n')  # 删首行 SEG
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertNotEqual(r.returncode, 0)              # 契约违规被拒

    def test_validate_rejects_extra_content(self):
        self._configure()
        state, _ = self._extract()
        self._plan(state)
        self._write_output(lambda t: t + '\nextra line not in contract\n')
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertNotEqual(r.returncode, 0)


class TestHelpers(unittest.TestCase):
    """scan_visible / apply_translations 辅助脚本测试"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.dir = Path(self.td.name)
        self.input = self.dir / 'block.input.txt'
        self.input.write_text(
            '@@MD2ZH:SEG:block-0001:0001@@\n'
            'Title text\n'
            '@@MD2ZH:SEG:block-0001:0002@@\n'
            '@@MD2ZH:PROTECT:0002:1@@Link@@MD2ZH:PROTECT:0002:2@@\n'
            '@@MD2ZH:SEG:block-0001:0003@@\n'
            'Visible paragraph.\n',
            encoding='utf-8')

    def tearDown(self):
        self.td.cleanup()

    def _run(self, script, *args):
        return subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8')

    def test_apply_translations_replaces_visible(self):
        mapping = self.dir / 'map.json'
        mapping.write_text('{"0001": "标题文本", "0003": "可见段落。"}', encoding='utf-8')
        out = self.dir / 'block.output.txt'
        r = self._run('apply_translations.py', self.input, out, mapping)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding='utf-8')
        self.assertIn('标题文本', text)
        self.assertIn('可见段落。', text)
        # PROTECT 行原样保留
        self.assertIn('@@MD2ZH:PROTECT:0002:1@@Link@@MD2ZH:PROTECT:0002:2@@', text)

    def test_apply_translations_keeps_unmapped(self):
        mapping = self.dir / 'map.json'
        mapping.write_text('{"0001": "标题文本"}', encoding='utf-8')
        out = self.dir / 'block.output.txt'
        r = self._run('apply_translations.py', self.input, out, mapping)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding='utf-8')
        self.assertIn('Visible paragraph.', text)   # 未映射行原样保留

    def test_scan_visible_lists_plain_text_only(self):
        r = self._run('scan_visible.py', self.input)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('[0001] Title text', r.stdout)
        self.assertIn('[0003] Visible paragraph.', r.stdout)
        self.assertNotIn('PROTECT', r.stdout)       # 不列 PROTECT 行


if __name__ == '__main__':
    unittest.main(verbosity=2)
