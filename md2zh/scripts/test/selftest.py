"""
md2zh_pipeline 离线自测（不依赖网络/外部服务）

运行: python selftest.py

覆盖: 配置写入（全局 config.py：python_path / decider / output_dir / tree_translation /
      max_block_chars 写入与现值保留）、分块提取（标题区间优先 + PROTECT 保护）、
      段落级 unit（多行契约：合并/重排/空行拒绝）、summarize 摘要、逐块验证契约、
      合并、确定性渲染（字节级一致）、verify 通过/拒绝、copy-assets、cleanup 归档。

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_config_sync import ConfigSyncTests

SAMPLE = (
    '# Title\n\n'
    'Hello **world** with $x$ inline.\n\n'
    '```python\nprint("code")\n```\n\n'
    '| A | B |\n|---|---|\n| 1 | 2 |\n'
)

MULTILINE = (
    '# Title\n\n'
    'The first paragraph line one\n'
    'continues on line two.\n'
    'And line three here.\n\n'
    'Second paragraph after the blank line.\n'
)


def run_pipeline(*args):
    return subprocess.run([sys.executable, str(PIPELINE), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8')


class TestPipeline(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.cfg = self.root / 'md2zh_test_config.py'   # 隔离的全局配置（不碰真实 scripts/config.py）
        self.tools = self.root / 'tools'                # 隔离的日志根（不碰真实 <skill>/debug/）
        self.src = self.root / 'doc.md'
        self.src.write_text(SAMPLE, encoding='utf-8')
        self.task = self.tools / 'intermediate' / 'task-1'
        self.task.mkdir(parents=True)   # run 目录由 plan-blocks 创建（要求空/已有 manifest）

    def tearDown(self):
        self.td.cleanup()

    def _configure(self, decider='user', *extra):
        r = run_pipeline('configure', '--decider', decider,
                         '--python-path', sys.executable, '--config', self.cfg, *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def _load_cfg(self):
        namespace = {}
        exec(compile(self.cfg.read_text(encoding='utf-8'), str(self.cfg), 'exec'), namespace)
        return namespace['md2zh_config']

    def _extract(self):
        state = self.root / 'state.json'
        blocks = self.root / 'blocks.json'
        r = run_pipeline('extract', self.src, '--state', state, '--blocks', blocks,
                         '--project-root', self.root, '--config', self.cfg,
                         '--tools-root', self.tools)
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

    def test_configure_writes_global_config(self):
        self._configure()
        self.assertTrue(self.cfg.exists())
        config = self._load_cfg()
        self.assertEqual(config['ambiguous_content_decider'], 'user')
        self.assertEqual(config['python_path'], str(Path(sys.executable).resolve()))

    def test_configure_accepts_ai_decider(self):
        self._configure(decider='ai')
        config = self._load_cfg()
        self.assertEqual(config['ambiguous_content_decider'], 'ai')

    def test_configure_writes_output_dir(self):
        self._configure('user', '--output-dir', 'D:/out')
        config = self._load_cfg()
        self.assertEqual(config['output_dir'], 'D:/out')

    def test_configure_preserves_output_dir(self):
        self._configure('user', '--output-dir', 'D:/out')
        self._configure('ai')   # 不带 --output-dir → 保留现值
        config = self._load_cfg()
        self.assertEqual(config['ambiguous_content_decider'], 'ai')
        self.assertEqual(config['output_dir'], 'D:/out')

    def test_configure_writes_tree_translation(self):
        self._configure('user', '--tree-translation', 'false')
        config = self._load_cfg()
        self.assertIs(config['tree_translation'], False)

    def test_configure_preserves_tree_translation(self):
        self._configure('user', '--tree-translation', 'false')
        self._configure('ai')   # 不带 --tree-translation → 保留现值
        config = self._load_cfg()
        self.assertIs(config['tree_translation'], False)

    def test_configure_defaults_tree_translation_true(self):
        self._configure('user')
        config = self._load_cfg()
        self.assertIs(config['tree_translation'], True)

    def test_configure_writes_max_block_chars(self):
        self._configure('user', '--max-block-chars', '20000')
        config = self._load_cfg()
        self.assertEqual(config['max_block_chars'], 20000)

    def test_configure_preserves_max_block_chars(self):
        self._configure('user', '--max-block-chars', '20000')
        self._configure('ai')   # 不带 --max-block-chars → 保留现值
        config = self._load_cfg()
        self.assertEqual(config['max_block_chars'], 20000)

    def test_configure_defaults_max_block_chars(self):
        self._configure('user')
        config = self._load_cfg()
        self.assertEqual(config['max_block_chars'], 16000)

    def test_extract_splits_oversized_blocks(self):
        self._configure('user', '--max-block-chars', '20')
        _state, blocks = self._extract()
        data = json.loads(blocks.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(data['translation_blocks']), 2)   # SAMPLE 可译字符超 20 → 拆块

    def test_summarize_writes_structure_md(self):
        self._configure('user', '--max-block-chars', '60')
        state, _ = self._extract()
        summary = self.root / 'summary.md'
        r = run_pipeline('summarize', state, summary)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = summary.read_text(encoding='utf-8')
        self.assertIn('# 分块结构摘要', text)
        self.assertIn('## 章节统计', text)
        self.assertIn('## 默认分块方案', text)
        self.assertIn('Title', text)          # 标题树包含一级标题
        self.assertIn('max_block_chars', text)
        self.assertIn('block-0001', text)     # 默认方案表含块

    def _extract_multi(self):
        src = self.root / 'multi.md'
        src.write_text(MULTILINE, encoding='utf-8')
        state = self.root / 'state.json'
        blocks = self.root / 'blocks.json'
        r = run_pipeline('extract', src, '--state', state, '--blocks', blocks,
                         '--project-root', self.root, '--config', self.cfg,
                         '--tools-root', self.tools)
        self.assertEqual(r.returncode, 0, r.stderr)
        return src, state, blocks

    def test_paragraph_unit_merges_lines(self):
        self._configure()
        _src, _state, blocks = self._extract_multi()
        data = json.loads(blocks.read_text(encoding='utf-8'))
        surface = data['translation_blocks'][0]['surface'].replace('\r\n', '\n')
        self.assertIn('The first paragraph line one\ncontinues on line two.\nAnd line three here.', surface)
        self.assertIn('Second paragraph after the blank line.', surface)

    def test_roundtrip_multiline_paragraph(self):
        self._configure()
        src, state, _blocks = self._extract_multi()
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
        self.assertEqual(candidate.read_bytes(), src.read_bytes())   # 多行段落字节级一致

    def test_validate_accepts_rewrapped_translation(self):
        self._configure()
        _src, state, _blocks = self._extract_multi()
        self._plan(state)
        # 译文把原文 3 行重排为 2 行（物理行数自由）
        self._write_output(lambda t: t.replace(
            'The first paragraph line one\ncontinues on line two.\nAnd line three here.',
            '第一段第一行和第二行合并成一句，\n第三行单独成句。'))
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_validate_rejects_blank_line_translation(self):
        self._configure()
        _src, state, _blocks = self._extract_multi()
        self._plan(state)
        # 译文引入空行 = 拆段，段落边界被改变 → 拒绝
        self._write_output(lambda t: t.replace(
            'line two.\nAnd line three', 'line two.\n\nAnd line three'))
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertNotEqual(r.returncode, 0)

    def test_extract_accepts_marker_inside_inline_code(self):
        self._configure()
        src = self.root / 'markers.md'
        src.write_text(
            '# Markers\n\n'
            'The pipeline uses `@@MD2ZH:PROTECT:1:2@@` inside inline code.\n',
            encoding='utf-8')
        state = self.root / 'state.json'
        blocks = self.root / 'blocks.json'
        r = run_pipeline('extract', src, '--state', state, '--blocks', blocks,
                         '--project-root', self.root, '--config', self.cfg,
                         '--tools-root', self.tools)
        self.assertEqual(r.returncode, 0, r.stderr)   # 行内代码内的标记字样被保护，允许

    def test_extract_rejects_marker_in_plain_text(self):
        self._configure()
        src = self.root / 'markers.md'
        src.write_text(
            '# Markers\n\n'
            'Bare marker @@MD2ZH:PROTECT:1:2@@ in visible text.\n',
            encoding='utf-8')
        state = self.root / 'state.json'
        blocks = self.root / 'blocks.json'
        r = run_pipeline('extract', src, '--state', state, '--blocks', blocks,
                         '--project-root', self.root, '--config', self.cfg,
                         '--tools-root', self.tools)
        self.assertNotEqual(r.returncode, 0)          # 裸可见文本含标记，拒绝（防御保持）

    def test_cleanup_archives_task_dir(self):
        self._configure()
        state = self.task / 'state.json'          # state 必须在任务目录内（cleanup 契约）
        blocks = self.task / 'blocks.json'
        r = run_pipeline('extract', self.src, '--state', state, '--blocks', blocks,
                         '--project-root', self.root, '--config', self.cfg,
                         '--tools-root', self.tools)
        self.assertEqual(r.returncode, 0, r.stderr)
        self._plan(state)
        self._write_output()
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        manifest = self.task / 'run' / 'manifest.json'
        r = run_pipeline('cleanup-run', manifest)
        self.assertEqual(r.returncode, 0, r.stderr)
        archive = self.tools / '_archive' / 'task-1'
        self.assertTrue(archive.exists())          # 归档而非删除
        self.assertFalse(self.task.exists())

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

    def test_copy_assets_copies_sibling_folder(self):
        assets = self.root / 'doc.assets'
        assets.mkdir()
        (assets / 'img.png').write_bytes(b'fake-png')
        (assets / 'sub').mkdir()
        (assets / 'sub' / 'a.bin').write_bytes(b'x')
        out = self.root / 'out' / 'doc_zh.md'
        r = run_pipeline('copy-assets', self.src, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data['copied'])
        self.assertEqual(data['files'], 2)
        target = self.root / 'out' / 'doc.assets'   # 保持源 stem 命名，图片引用不变
        self.assertTrue((target / 'img.png').exists())
        self.assertTrue((target / 'sub' / 'a.bin').exists())

    def test_copy_assets_missing_folder(self):
        out = self.root / 'out' / 'doc_zh.md'
        r = run_pipeline('copy-assets', self.src, out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(json.loads(r.stdout)['copied'])
        self.assertFalse((self.root / 'out').exists())   # 无 assets 时不动输出目录


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

    def test_scan_visible_lists_multiline_segment(self):
        inp = self.dir / 'multi.input.txt'
        inp.write_text(
            '@@MD2ZH:SEG:block-0001:0001@@\n'
            'Line one\n'
            'line two\n'
            '@@MD2ZH:SEG:block-0001:0002@@\n'
            'Next segment.\n',
            encoding='utf-8')
        r = self._run('scan_visible.py', inp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('[0001] Line one\nline two', r.stdout)

    def test_apply_translations_replaces_multiline_segment(self):
        inp = self.dir / 'multi.input.txt'
        inp.write_text(
            '@@MD2ZH:SEG:block-0001:0001@@\n'
            'Line one\n'
            'line two\n'
            '@@MD2ZH:SEG:block-0001:0002@@\n'
            'Next segment.\n',
            encoding='utf-8')
        mapping = self.dir / 'map.json'
        mapping.write_text('{"0001": "第一行译文\\n第二行译文"}', encoding='utf-8')
        out = self.dir / 'multi.output.txt'
        r = self._run('apply_translations.py', inp, out, mapping)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding='utf-8')
        self.assertIn('第一行译文\n第二行译文', text)
        self.assertIn('Next segment.', text)   # 未映射段原样保留


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPipeline)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestHelpers))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(ConfigSyncTests))
    unittest.TextTestRunner(verbosity=2).run(suite)
