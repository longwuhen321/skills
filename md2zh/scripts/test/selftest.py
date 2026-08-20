"""
md2zh_pipeline 离线自测（不依赖网络/外部服务）

运行: python selftest.py

覆盖: 配置安全解析与写入（全局 config.py：python_path / decider / output_dir / tree_translation /
      max_block_chars 写入与现值保留）、只读发布检查、分块提取（标题区间优先 + PROTECT 保护）、
      段落级 unit（多行契约：合并/重排/空行拒绝）、summarize 摘要、逐块验证契约、
      glossary 跨文件复用、合并、确定性渲染（字节级一致）、verify/review 完成标记、
      copy-assets、无覆盖归档、skill 文档直接路由与核心红线。

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
from test_documentation_routes import SkillDocumentationRoutesTests
from test_packaging import PackagingCheckTests

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
        self.tools = self.root / 'tools'                # 隔离的日志根（不碰真实 <skill>/logs/）
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
        sys.path.insert(0, str(HERE))
        try:
            from config_literal import load_config_group
            return load_config_group(self.cfg, 'md2zh_config')
        finally:
            sys.path.pop(0)

    def _extract(self, state=None, blocks=None, glossary=None, source=None):
        state = Path(state) if state else self.root / 'state.json'
        blocks = Path(blocks) if blocks else self.root / 'blocks.json'
        args = [
            'extract', source or self.src, '--state', state, '--blocks', blocks,
            '--project-root', self.root, '--config', self.cfg,
            '--tools-root', self.tools,
        ]
        if glossary:
            args.extend(['--glossary', glossary])
        r = run_pipeline(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return state, blocks

    def _complete_task(self, glossary=None):
        self._configure()
        state, blocks = self._extract(
            self.task / 'state.json', self.task / 'blocks.json', glossary=glossary
        )
        self._plan(state)
        self._write_output()
        manifest = self.task / 'run' / 'manifest.json'
        r = run_pipeline('validate-block', state, manifest, 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        translations = self.task / 'translations.json'
        r = run_pipeline('merge-blocks', state, manifest, translations)
        self.assertEqual(r.returncode, 0, r.stderr)
        candidate = self.task / 'candidate.md'
        r = run_pipeline('render', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_pipeline('verify', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        review = self.task / 'review.md'
        review.write_text('# AI 终检\n\n已通读，未发现问题。\n', encoding='utf-8')
        r = run_pipeline('mark-reviewed', state, translations, candidate, review)
        self.assertEqual(r.returncode, 0, r.stderr)
        return state, manifest, translations, candidate, review

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

    def test_configure_rejects_side_effect_config_without_executing(self):
        sentinel = self.root / 'must-not-exist.txt'
        self.cfg.write_text(
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
            "md2zh_config = {'python_path': 'x'}\n",
            encoding='utf-8',
        )
        original = self.cfg.read_bytes()
        r = run_pipeline(
            'configure', '--decider', 'user', '--python-path', sys.executable,
            '--config', self.cfg,
        )
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(sentinel.exists())
        self.assertEqual(self.cfg.read_bytes(), original)

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

    def test_configure_rejects_nonpositive_max_block_chars(self):
        for value in ('0', '-1'):
            with self.subTest(value=value):
                r = run_pipeline(
                    'configure', '--decider', 'user', '--python-path', sys.executable,
                    '--config', self.cfg, '--max-block-chars', value,
                )
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('positive integer', r.stderr)

    def test_extract_rejects_invalid_configured_max_block_chars(self):
        for value in ('0', '-1', 'True', "'16000'"):
            with self.subTest(value=value):
                cfg = self.root / ('invalid-' + str(len(value)) + '.py')
                cfg.write_text(
                    "md2zh_config = {\n"
                    f"    'python_path': {str(Path(sys.executable).resolve())!r},\n"
                    "    'ambiguous_content_decider': 'user',\n"
                    "    'output_dir': '',\n"
                    "    'tree_translation': True,\n"
                    f"    'max_block_chars': {value},\n"
                    "}\n",
                    encoding='utf-8',
                )
                r = run_pipeline(
                    'extract', self.src, '--state', self.root / 'invalid-state.json',
                    '--blocks', self.root / 'invalid-blocks.json', '--project-root', self.root,
                    '--config', cfg, '--tools-root', self.tools,
                )
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('max_block_chars', r.stderr)

    def test_extract_splits_oversized_blocks(self):
        self._configure('user', '--max-block-chars', '20')
        _state, blocks = self._extract()
        data = json.loads(blocks.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(data['translation_blocks']), 2)   # SAMPLE 可译字符超 20 → 拆块

    def test_summarize_writes_structure_md(self):
        self.src.write_text(SAMPLE + '\n$$\nx + y\n$$\n', encoding='utf-8')
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
        self.assertRegex(text, r'代码块 1：第 \d+–\d+ 行')
        self.assertRegex(text, r'公式块 1：第 \d+–\d+ 行')

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

    def test_list_and_quote_lines_are_independent_units_and_roundtrip(self):
        source_text = (
            '# Lists\n\n'
            '- First item\n'
            '  - Nested item\n'
            '> Quote line one\n'
            '> Quote line two\n'
            '>   > Nested quote\n'
        )
        self.src.write_text(source_text, encoding='utf-8')
        self._configure()
        state, _blocks = self._extract()
        data = json.loads(state.read_text(encoding='utf-8'))
        structural_units = [
            unit for unit in data['units']
            if unit['source_text'] in {
                'First item', 'Nested item', 'Quote line one', 'Quote line two',
                'Nested quote'
            }
        ]
        self.assertEqual(len(structural_units), 5)
        self.assertTrue(all(unit['line_start'] == unit['line_end'] for unit in structural_units))

        self._plan(state)
        self._write_output()
        manifest = self.task / 'run' / 'manifest.json'
        r = run_pipeline('validate-block', state, manifest, 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        translations = self.task / 'translations.json'
        r = run_pipeline('merge-blocks', state, manifest, translations)
        self.assertEqual(r.returncode, 0, r.stderr)
        candidate = self.task / 'candidate.md'
        r = run_pipeline('render', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(candidate.read_bytes(), self.src.read_bytes())

    def test_line_level_units_do_not_change_setext_heading_detection(self):
        self.src.write_text(
            'Setext Title\n============\n\n- List item\n', encoding='utf-8'
        )
        self._configure()
        state, _blocks = self._extract()
        data = json.loads(state.read_text(encoding='utf-8'))
        setext_units = [
            unit for unit in data['units'] if unit['source_text'] == 'Setext Title'
        ]
        self.assertEqual(len(setext_units), 1)
        self.assertEqual(setext_units[0]['kind'], 'heading')
        list_units = [unit for unit in data['units'] if unit['source_text'] == 'List item']
        self.assertEqual(len(list_units), 1)
        self.assertEqual(list_units[0]['line_start'], list_units[0]['line_end'])

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

    def test_validate_rejects_whitespace_only_line_translation(self):
        self._configure()
        _src, state, _blocks = self._extract_multi()
        self._plan(state)
        self._write_output(lambda t: t.replace(
            'line two.\nAnd line three', 'line two.\n \t \nAnd line three'))
        r = run_pipeline('validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('whitespace-only', r.stderr)

    def _validate_first_paragraph_line(self, replacement):
        self._configure()
        _src, state, _blocks = self._extract_multi()
        self._plan(state)
        self._write_output(lambda text: text.replace(
            'The first paragraph line one', replacement, 1))
        return run_pipeline(
            'validate-block', state, self.task / 'run' / 'manifest.json', 'block-0001'
        )

    def test_validate_rejects_indented_heading_marker(self):
        r = self._validate_first_paragraph_line('   # 新标题')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_indented_star_list_marker(self):
        r = self._validate_first_paragraph_line('  * 新列表项')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_indented_quote_marker(self):
        r = self._validate_first_paragraph_line('   > 新引用')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_four_space_indented_code(self):
        r = self._validate_first_paragraph_line('    print value')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_tab_indented_code(self):
        r = self._validate_first_paragraph_line('\t print value')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_space_tab_indented_code(self):
        r = self._validate_first_paragraph_line('   \tprint value')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_thematic_break_marker(self):
        r = self._validate_first_paragraph_line('---')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_rejects_setext_marker(self):
        r = self._validate_first_paragraph_line('===')
        self.assertNotEqual(r.returncode, 0)

    def test_validate_allows_three_space_plain_text(self):
        r = self._validate_first_paragraph_line('   普通缩进文本')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_extract_protects_space_tab_indented_code(self):
        self.src.write_text(
            '# Code\n\n   \tprint("protected")\n\nVisible paragraph.\n',
            encoding='utf-8'
        )
        self._configure()
        state, _blocks = self._extract()
        data = json.loads(state.read_text(encoding='utf-8'))
        source_texts = [unit['source_text'] for unit in data['units']]
        self.assertNotIn('print("protected")', source_texts)
        self.assertIn('Visible paragraph.', source_texts)

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

    def _extract_ambiguous(self):
        self.src.write_text('# Title\n\n:::note Translate this text\n', encoding='utf-8')
        self._configure('ai')
        state, blocks = self._extract()
        data = json.loads(state.read_text(encoding='utf-8'))
        self.assertEqual(len(data['ambiguous_regions']), 1)
        return state, blocks, data['ambiguous_regions'][0]

    def _write_decisions(self, region, decision, path=None):
        selected_spans = region['suggested_spans'] if decision == 'translate' else []
        payload = {
            'decisions': [{
                'region_id': region['id'],
                'decision': decision,
                'reason': 'offline test',
                'selected_spans': selected_spans,
            }]
        }
        path = path or (self.root / 'decisions.json')
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return path, payload

    def test_record_decisions_requires_complete_unique_known_region_ids(self):
        state, _blocks, region = self._extract_ambiguous()
        decisions_path = self.root / 'decisions.json'
        cases = {
            'missing': {'decisions': []},
            'duplicate': {
                'decisions': [
                    {
                        'region_id': region['id'], 'decision': 'protect',
                        'reason': '', 'selected_spans': [],
                    },
                    {
                        'region_id': region['id'], 'decision': 'protect',
                        'reason': '', 'selected_spans': [],
                    },
                ]
            },
            'unknown': {
                'decisions': [
                    {
                        'region_id': region['id'], 'decision': 'protect',
                        'reason': '', 'selected_spans': [],
                    },
                    {
                        'region_id': 'unknown-9999', 'decision': 'protect',
                        'reason': '', 'selected_spans': [],
                    },
                ]
            },
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                decisions_path.write_text(
                    json.dumps(payload, ensure_ascii=False), encoding='utf-8'
                )
                r = run_pipeline('record-decisions', state, decisions_path)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(label, r.stderr)

    def test_protect_decision_end_to_end_needs_no_extra_translations(self):
        state, _blocks, region = self._extract_ambiguous()
        decisions_path, _payload = self._write_decisions(region, 'protect')
        r = run_pipeline('record-decisions', state, decisions_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            json.loads(r.stdout)['extra_translations_skeleton'], {'translations': {}}
        )

        self._plan(state)
        self._write_output()
        manifest = self.task / 'run' / 'manifest.json'
        r = run_pipeline('validate-block', state, manifest, 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        translations = self.task / 'translations.json'
        r = run_pipeline('merge-blocks', state, manifest, translations)
        self.assertEqual(r.returncode, 0, r.stderr)
        candidate = self.task / 'candidate.md'
        r = run_pipeline('render', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(candidate.read_bytes(), self.src.read_bytes())

    def test_translate_decision_skeleton_closes_merge_and_render(self):
        state, _blocks, region = self._extract_ambiguous()
        decisions_path, _payload = self._write_decisions(region, 'translate')
        r = run_pipeline('record-decisions', state, decisions_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        expected_id = region['id'] + ':0'
        skeleton = result['extra_translations_skeleton']
        self.assertEqual(skeleton, {'translations': {expected_id: ''}})

        self._plan(state)
        self._write_output()
        manifest = self.task / 'run' / 'manifest.json'
        r = run_pipeline('validate-block', state, manifest, 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        translations = self.task / 'translations.json'
        r = run_pipeline('merge-blocks', state, manifest, translations)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--extra-translations', r.stderr)

        skeleton['translations'][expected_id] = '翻译此文本'
        extras = self.task / 'extra-translations.json'
        extras.write_text(json.dumps(skeleton, ensure_ascii=False), encoding='utf-8')
        r = run_pipeline(
            'merge-blocks', state, manifest, translations,
            '--extra-translations', extras,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        candidate = self.task / 'candidate.md'
        r = run_pipeline('render', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(':::note 翻译此文本', candidate.read_text(encoding='utf-8'))
        r = run_pipeline('verify', state, translations, candidate)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_cleanup_requires_merge_render_verify_and_review(self):
        self._configure()
        state, _blocks = self._extract(self.task / 'state.json', self.task / 'blocks.json')
        self._plan(state)
        self._write_output()
        manifest = self.task / 'run' / 'manifest.json'
        r = run_pipeline('validate-block', state, manifest, 'block-0001')
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run_pipeline('cleanup-run', manifest)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('merge', r.stderr)

    def test_cleanup_archives_without_overwriting_or_pruning_existing_archives(self):
        _state, manifest, _translations, _candidate, _review = self._complete_task()
        archive_root = self.tools / '_archive'
        collision = archive_root / 'task-1'
        collision.mkdir(parents=True)
        sentinel = collision / 'keep.txt'
        sentinel.write_text('keep', encoding='utf-8')
        old_entries = []
        for index in range(21):
            item = archive_root / f'old-{index:02d}'
            item.mkdir()
            old_entries.append(item)

        r = run_pipeline('cleanup-run', manifest)
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        archived = Path(result['archived'])
        self.assertNotEqual(archived, collision)
        self.assertTrue(archived.exists())
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'keep')
        self.assertTrue(all(item.exists() for item in old_entries))
        self.assertTrue((archived / 'glossary.json').exists())
        self.assertFalse(self.task.exists())

    def test_mark_reviewed_requires_verify_and_cleanup_rejects_stale_review(self):
        self._configure()
        state, _blocks = self._extract(self.task / 'state.json', self.task / 'blocks.json')
        self._plan(state)
        self._write_output()
        manifest = self.task / 'run' / 'manifest.json'
        self.assertEqual(run_pipeline('validate-block', state, manifest, 'block-0001').returncode, 0)
        translations = self.task / 'translations.json'
        self.assertEqual(run_pipeline('merge-blocks', state, manifest, translations).returncode, 0)
        candidate = self.task / 'candidate.md'
        self.assertEqual(run_pipeline('render', state, translations, candidate).returncode, 0)
        review = self.task / 'review.md'
        review.write_text('已通读，未发现问题。\n', encoding='utf-8')
        early = run_pipeline('mark-reviewed', state, translations, candidate, review)
        self.assertNotEqual(early.returncode, 0)
        self.assertEqual(run_pipeline('verify', state, translations, candidate).returncode, 0)
        marked = run_pipeline('mark-reviewed', state, translations, candidate, review)
        self.assertEqual(marked.returncode, 0, marked.stderr)
        completion = json.loads((self.task / 'completion.json').read_text(encoding='utf-8'))
        self.assertEqual(set(completion['stages']), {'merge', 'render', 'verify', 'review'})
        review.write_text('标记后被修改。\n', encoding='utf-8')
        stale = run_pipeline('cleanup-run', manifest)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('review', stale.stderr)

    def test_cleanup_rejects_review_stage_without_review_artifact(self):
        _state, manifest, _translations, _candidate, _review = self._complete_task()
        completion_path = self.task / 'completion.json'
        completion = json.loads(completion_path.read_text(encoding='utf-8'))
        del completion['stages']['review']['review']
        completion_path.write_text(
            json.dumps(completion, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )

        result = run_pipeline('cleanup-run', manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('review.review', result.stderr)

    def test_glossary_reuses_terms_across_files_and_rejects_silent_conflicts(self):
        self._configure()
        shared = self.root / 'tree-run' / 'glossary.json'
        task_one = self.tools / 'intermediate' / 'tree-1'
        task_one.mkdir(parents=True)
        state_one, _ = self._extract(
            task_one / 'state.json', task_one / 'blocks.json', glossary=shared
        )
        updates = self.root / 'glossary-updates.json'
        updates.write_text(
            json.dumps({'terms': {'controller': '控制器'}}, ensure_ascii=False),
            encoding='utf-8',
        )
        r = run_pipeline('update-glossary', state_one, updates)
        self.assertEqual(r.returncode, 0, r.stderr)

        second_source = self.root / 'second.md'
        second_source.write_text('# Second\n\nController details.\n', encoding='utf-8')
        task_two = self.tools / 'intermediate' / 'tree-2'
        task_two.mkdir(parents=True)
        state_two, _ = self._extract(
            task_two / 'state.json', task_two / 'blocks.json', glossary=shared,
            source=second_source,
        )
        state_data = json.loads(state_two.read_text(encoding='utf-8'))
        self.assertEqual(Path(state_data['glossary_path']), shared.resolve())
        glossary = json.loads(shared.read_text(encoding='utf-8'))
        self.assertEqual(glossary['terms']['controller'], '控制器')

        updates.write_text(
            json.dumps({'terms': {'controller': '控制器装置'}}, ensure_ascii=False),
            encoding='utf-8',
        )
        conflict = run_pipeline('update-glossary', state_two, updates)
        self.assertNotEqual(conflict.returncode, 0)
        self.assertEqual(
            json.loads(shared.read_text(encoding='utf-8'))['terms']['controller'], '控制器'
        )

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

    def test_copy_assets_same_directory_is_safe_noop(self):
        assets = self.root / 'doc.assets'
        assets.mkdir()
        image = assets / 'img.png'
        image.write_bytes(b'original')
        output = self.root / 'doc_zh.md'
        r = run_pipeline('copy-assets', self.src, output)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertFalse(data['copied'])
        self.assertTrue(data['already_in_place'])
        self.assertEqual(data['files'], 1)
        self.assertEqual(image.read_bytes(), b'original')

    def test_copy_assets_existing_different_target_is_rejected(self):
        assets = self.root / 'doc.assets'
        assets.mkdir()
        (assets / 'new.png').write_bytes(b'new')
        target = self.root / 'out' / 'doc.assets'
        target.mkdir(parents=True)
        sentinel = target / 'keep.png'
        sentinel.write_bytes(b'keep')
        output = self.root / 'out' / 'doc_zh.md'
        r = run_pipeline('copy-assets', self.src, output)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('refusing to merge or overwrite', r.stderr)
        self.assertEqual(sentinel.read_bytes(), b'keep')
        self.assertFalse((target / 'new.png').exists())


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
            '@@MD2ZH:PROTECT:0002:1@@Bold text@@MD2ZH:PROTECT:0002:2@@\n'
            '@@MD2ZH:SEG:block-0001:0003@@\n'
            'Visible paragraph.\n'
            '@@MD2ZH:SEG:block-0001:0004@@\n'
            '@@MD2ZH:PROTECT:0004:1@@\n'
            '@@MD2ZH:SEG:block-0001:0005@@\n'
            '@@MD2ZH:PROTECT:0005:1@@\n'
            '@@MD2ZH:SEG:block-0001:0006@@\n'
            '@@MD2ZH:PROTECT:0006:1@@Link label@@MD2ZH:PROTECT:0006:2@@\n',
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
        self.assertIn('@@MD2ZH:PROTECT:0002:1@@Bold text@@MD2ZH:PROTECT:0002:2@@', text)

    def test_apply_translations_keeps_unmapped(self):
        mapping = self.dir / 'map.json'
        mapping.write_text('{"0001": "标题文本"}', encoding='utf-8')
        out = self.dir / 'block.output.txt'
        r = self._run('apply_translations.py', self.input, out, mapping)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = out.read_text(encoding='utf-8')
        self.assertIn('Visible paragraph.', text)   # 未映射行原样保留

    def test_scan_visible_keeps_markers_for_mixed_visible_segments(self):
        r = self._run('scan_visible.py', self.input)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('[0001] Title text', r.stdout)
        self.assertIn('[0003] Visible paragraph.', r.stdout)
        self.assertIn(
            '[0002] @@MD2ZH:PROTECT:0002:1@@Bold text@@MD2ZH:PROTECT:0002:2@@',
            r.stdout,
        )
        self.assertIn(
            '[0006] @@MD2ZH:PROTECT:0006:1@@Link label@@MD2ZH:PROTECT:0006:2@@',
            r.stdout,
        )

    def test_scan_visible_skips_formula_and_inline_code_only_segments(self):
        r = self._run('scan_visible.py', self.input)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('[0004]', r.stdout)       # 纯公式 PROTECT 段
        self.assertNotIn('[0005]', r.stdout)       # 纯行内代码 PROTECT 段

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
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(PackagingCheckTests))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(SkillDocumentationRoutesTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
