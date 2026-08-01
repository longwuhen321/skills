"""
离线自测脚本（不依赖 Confluence 服务器）

运行: python selftest.py

覆盖:
  - common:        429 限流重试、分页收集、token 环境变量覆盖
  - md_import:     占位符保护/还原、公式/代码转换、版本号流程、标题内存匹配
  - math_upgrade:  $/$$/```latex``` 转换、旧宏升级、原生 alignment、span 限制删除、verify

所有用例 mock 掉配置与网络，不触碰真实 config.py 和服务器。
"""

import os
import sys
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from common import (load_config, request_with_retry, collect_space_pages,
                    build_block_template)
from md_import import MarkdownImporter
from math_upgrade import ConfluenceMathUpdater

MOCK_CFG = {
    'common_config': {
        'confluence_url': 'http://test:8090',
        'confluence_token': 'test-token',
    },
    'import_config': {'space': 'TEST', 'math_align': 'left'},
    'upgrade_config': {'math_align': 'left', 'auto_update': True,
                       'claude_verify': False, 'recursive': True, 'max_depth': 0},
    'debug_config': {'max_size_mb': 50, 'keep_recent': 20},
}


class FakeResponse:
    """最小化 requests.Response 替身"""

    def __init__(self, status_code=200, json_data=None, text='', headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}: {self.text}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestCommon(unittest.TestCase):

    def test_retry_429_then_ok(self):
        session = mock.Mock()
        session.request.side_effect = [
            FakeResponse(429, text='rate limited', headers={'Retry-After': '0'}),
            FakeResponse(200, json_data={'ok': 1}),
        ]
        with patch('common.time.sleep') as fake_sleep:
            resp = request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(session.request.call_count, 2)
        fake_sleep.assert_called_once_with(0)  # 尊重 Retry-After

    def test_retry_exhausted_returns_last(self):
        session = mock.Mock()
        session.request.side_effect = [FakeResponse(429) for _ in range(3)]
        with patch('common.time.sleep'):
            resp = request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(session.request.call_count, 3)

    def test_retry_uses_backoff(self):
        session = mock.Mock()
        session.request.side_effect = [FakeResponse(429), FakeResponse(200)]
        with patch('common.time.sleep') as fake_sleep:
            request_with_retry(session, 'GET', 'http://x')
        self.assertEqual(fake_sleep.call_args[0][0], 1)  # 2**0 = 1s

    def test_collect_space_pages_pagination(self):
        session = mock.Mock()
        session.request.side_effect = [
            FakeResponse(200, json_data={'results': [
                {'id': '1', 'title': 'A', 'version': {'number': 1}},
                {'id': '2', 'title': 'B', 'version': {'number': 2}},
            ]}),
            FakeResponse(200, json_data={'results': [
                {'id': '3', 'title': 'C', 'version': {'number': 3}},
            ]}),
            FakeResponse(200, json_data={'results': []}),
        ]
        pages = collect_space_pages(session, 'http://x', 'SP', page_size=2)
        self.assertEqual(pages, [('1', 'A', 1), ('2', 'B', 2), ('3', 'C', 3)])
        # 分页参数正确传递
        params = [c.kwargs['params']['start'] for c in session.request.call_args_list]
        self.assertEqual(params, [0, 2, 4])

    def test_env_token_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, 'config.py')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                f.write("common_config = {'confluence_url': 'http://x',"
                        " 'confluence_token': 'file-token'}\n")
            with patch('common.CONFIG_PATH', cfg_path), \
                 patch.dict(os.environ, {'CONFLUENCE_TOKEN': 'env-token'}):
                cfg = load_config()
        self.assertEqual(cfg['common_config']['confluence_token'], 'env-token')

    def test_env_token_not_set_uses_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, 'config.py')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                f.write("common_config = {'confluence_url': 'http://x',"
                        " 'confluence_token': 'file-token'}\n")
            with patch('common.CONFIG_PATH', cfg_path), \
                 mock.patch.dict(os.environ, {'CONFLUENCE_TOKEN': ''}):
                cfg = load_config()
        self.assertEqual(cfg['common_config']['confluence_token'], 'file-token')


class TestMdImport(unittest.TestCase):

    def setUp(self):
        self.load_patcher = patch('md_import.load_config', return_value=MOCK_CFG)
        self.load_patcher.start()
        self.importer = MarkdownImporter(space_key='TEST')
        # 测试不写真实调试文件
        self.debug_patcher = patch.object(self.importer, '_save_debug_file')
        self.debug_patcher.start()

    def tearDown(self):
        self.debug_patcher.stop()
        self.load_patcher.stop()

    def test_code_protect_restore_roundtrip(self):
        md = '```python\nprint("hi")\n```\n\nand `code` here'
        protected, spans = self.importer._protect_code_spans(md)
        self.assertIn('CODE_FENCED_1_', protected)
        self.assertIn('CODE_INLINE_', protected)
        converted = self.importer._convert_protected_code_to_html(spans)
        restored = self.importer._restore_code_spans(protected, spans, converted)
        self.assertIn('<code', restored)
        # 无占位符残留
        self.assertNotIn(self.importer._token, restored)

    def test_math_protect_restore_roundtrip(self):
        md = '$$\nE=mc^2\n$$\n\ninline $x$ and block:\n```latex\ny=2\n```'
        protected, blocks = self.importer._protect_math_blocks(md)
        self.assertIn('MATH_BLOCK_', protected)
        self.assertIn('MATH_INLINE_', protected)
        self.assertIn('LATEX_BLOCK_', protected)
        restored = self.importer._restore_math_blocks(protected, blocks)
        self.assertEqual(restored, md)

    def test_placeholder_no_collision(self):
        # 原文恰好包含旧格式占位符注释文本，不应被误处理
        md = '<!-- CODE_FENCED_1 -->\n\n```python\nprint(1)\n```'
        protected, spans = self.importer._protect_code_spans(md)
        self.assertIn('<!-- CODE_FENCED_1 -->', protected)
        converted = self.importer._convert_protected_code_to_html(spans)
        restored = self.importer._restore_code_spans(protected, spans, converted)
        self.assertNotIn(self.importer._token, restored)  # 新占位符全部还原
        self.assertIn('<!-- CODE_FENCED_1 -->', restored)  # 原文注释保留

    def test_inline_math_no_cross_line(self):
        md = 'text $a\nb$ text'
        protected, blocks = self.importer._protect_math_blocks(md)
        self.assertEqual(protected, md)  # 跨行 $...$ 不当作行内公式
        self.assertEqual(len(blocks), 0)

    def test_shell_variables_not_math(self):
        # bash 变量 $PWD / $OLDPWD 不应被保护层识别为公式
        md = 'echo $PWD / $OLDPWD'
        protected, blocks = self.importer._protect_math_blocks(md)
        self.assertEqual(protected, md)
        self.assertEqual(len(blocks), 0)

    def test_convert_math_blocks(self):
        html = '<p>$$E=mc^2$$</p><p>$x$</p><pre><code>$$not math$$</code></pre>'
        result = self.importer._convert_math_blocks(html)
        self.assertIn('mathblock', result)
        self.assertIn('mathinline', result)
        self.assertIn('$$not math$$', result)  # code 内受保护

    def test_convert_math_blocks_left_alignment(self):
        # 默认 left：$$ 和 ```latex``` 块级公式都带 alignment=left
        html = '<p>$$E=mc^2$$</p><p>```latex\ny=3\n```</p>'
        result = self.importer._convert_math_blocks(html)
        self.assertEqual(result.count('ac:parameter ac:name="alignment">left<'), 2)

    def test_convert_math_blocks_center_no_alignment(self):
        center_importer = MarkdownImporter(space_key='TEST', math_align='center')
        html = '<p>$$E=mc^2$$</p>'
        result = center_importer._convert_math_blocks(html)
        self.assertIn('mathblock', result)
        self.assertNotIn('alignment', result)

    def test_undefined_control_seq_star_sanitized(self):
        # \* 未定义控制序列：inline body 与 block CDATA 都应归一化为 *
        html = '<p>$q^\\* = a-bi-cj-dk$</p><p>$$x^\\*$$</p>'
        result = self.importer._convert_math_blocks(html)
        self.assertNotIn('\\*', result)
        self.assertIn('q^* = a-bi-cj-dk', result)
        self.assertIn('x^*', result)

    def test_data_uri_image_skipped(self):
        # base64 内嵌图片：保留原始引用，不当作本地文件处理、不进失败报告
        html = '<p><img alt="x" src="data:image/png;base64,AAAA" /></p>'
        result = self.importer._convert_md_links(html, 'C:/fake/dir.md', '123')
        self.assertIn('data:image/png;base64,AAAA', result)
        self.assertEqual(self.importer.failed_images, [])
        self.assertEqual(self.importer.data_images_skipped, 1)

    def test_find_page_memory_match(self):
        with patch('md_import.collect_space_pages',
                   return_value=[('1', 'Foo Page', 3), ('2', 'foo page', 5)]):
            pid, ver = self.importer._find_page_by_title('Foo Page')
            self.assertEqual((pid, ver), ('1', 3))
            # 大小写不敏感兜底
            pid, ver = self.importer._find_page_by_title('FOO PAGE')
            self.assertEqual((pid, ver), ('1', 3))
            pid, ver = self.importer._find_page_by_title('Bar')
            self.assertEqual((pid, ver), (None, None))

    def test_update_page_409_retries_once(self):
        responses = [
            FakeResponse(409, text='version conflict'),
            FakeResponse(200, json_data={'id': '123', 'version': {'number': 8}}),
        ]
        with patch.object(self.importer.session, 'request', side_effect=responses) as req, \
             patch.object(self.importer, '_fetch_latest_version', return_value=7) as fv:
            pid, ver = self.importer._update_page('123', 'T', '<p>x</p>', 6)
        self.assertEqual((pid, ver), ('123', 8))
        self.assertEqual(req.call_count, 2)
        fv.assert_called_once_with('123')
        last_payload = req.call_args_list[1].kwargs['json']
        self.assertEqual(last_payload['version']['number'], 8)

    def test_import_markdown_version_flow(self):
        # 已有页面 v3 + 含图片 → 步骤6 更新 v4，步骤7 图片后更新 v5（不再硬编码 version=2）
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False,
                                         encoding='utf-8') as f:
            f.write('# Hello\n\nplain text')
            md_path = f.name
        try:
            importer = self.importer
            with patch.object(importer, '_find_page_by_title', return_value=('123', 3)):
                calls = []
                def fake_update(page_id, title, content, version):
                    calls.append(version)
                    return page_id, version + 1
                with patch.object(importer, '_update_page', side_effect=fake_update), \
                     patch.object(importer, '_convert_md_links',
                                  side_effect=lambda html, path, pid: html + '<ac:image/>'):
                    page_id = importer.import_markdown(md_path)
            self.assertEqual(page_id, '123')
            self.assertEqual(calls, [3, 4])
        finally:
            os.unlink(md_path)


class TestMathUpgrade(unittest.TestCase):

    def setUp(self):
        self.load_patcher = patch('math_upgrade.load_config', return_value=MOCK_CFG)
        self.load_patcher.start()
        self.updater = ConfluenceMathUpdater(math_align='left')

    def tearDown(self):
        self.load_patcher.stop()

    def test_block_template_left_uses_native_alignment(self):
        left = build_block_template('left')
        self.assertIn('mathblock', left)
        self.assertIn('alignment">left<', left)
        self.assertNotIn('mathinline', left)
        center = build_block_template('center')
        self.assertIn('mathblock', center)
        self.assertNotIn('alignment', center)

    def test_convert_block_inline_latex(self):
        html = '$$E=mc^2$$\n$x^2$\n```latex\ny=3\n```'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['block'], 1)
        self.assertEqual(stats['latex'], 1)
        self.assertEqual(stats['inline'], 1)
        self.assertIn('mathblock', after)
        self.assertIn('mathinline', after)

    def test_convert_complex_inline_to_block(self):
        html = 'complex $a = b + c + d = e + f$'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['upgraded'], 1)
        self.assertIn('mathblock', after)

    def test_old_macro_upgrade(self):
        html = ('<ac:structured-macro ac:name="mathjax-inline-macro" ac:schema-version="1">'
                '<ac:parameter ac:name="equation">x^2</ac:parameter>'
                '</ac:structured-macro>')
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['old_macro_upgraded'], 1)
        self.assertIn('mathblock', after)
        self.assertIn('alignment">left<', after)

    def test_inline_math_no_cross_line(self):
        html = '<p>$a\nb$</p>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['inline'], 0)
        self.assertNotIn('mathinline', after)

    def test_shell_variables_not_math(self):
        # bash 变量 $PWD / $OLDPWD 不应被识别为公式
        html = '<p><span><span>$PWD</span><span> / </span><span>$OLDPWD</span></span></p>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['inline'], 0)
        self.assertNotIn('mathinline', after)
        # 纯文本场景（无 span 包装）
        html2 = '<p>$PWD / $OLDPWD</p>'
        after2, stats2 = self.updater.convert_math(html2)
        self.assertEqual(stats2['inline'], 0)
        self.assertNotIn('mathinline', after2)
        # 单个变量 $USER 也不转换
        html3 = '<p>echo $USER</p>'
        after3, stats3 = self.updater.convert_math(html3)
        self.assertEqual(stats3['inline'], 0)

    def test_inline_math_with_spaces_still_converts(self):
        html = '<p>$x + y = z$</p>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['inline'], 1)
        self.assertIn('mathinline', after)

    def test_currency_not_math(self):
        html = '<p>$5 and $10</p>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['inline'], 0)
        self.assertNotIn('mathinline', after)

    def test_undefined_control_seq_star_sanitized(self):
        # \* 是未定义控制序列（MathJax 报错），转换时应归一化为 *
        html = '<p>$q^\\* = a-bi-cj-dk$</p>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['inline'], 1)
        self.assertIn('q^* = a-bi-cj-dk', after)
        self.assertNotIn('\\*', after)
        # 块级公式同样清理
        html2 = '<p>$$a^\\* + b^\\*$$</p>'
        after2, stats2 = self.updater.convert_math(html2)
        self.assertNotIn('\\*', after2)
        self.assertIn('a^* + b^*', after2)

    def test_span_only_math_class_removed(self):
        html = '<span class="math-inline">$x$</span><span>keep me</span>'
        after, stats = self.updater.convert_math(html)
        self.assertNotIn('math-inline', after)
        self.assertIn('keep me', after)
        self.assertEqual(stats['span_removed'], 1)
        # 剥壳保留内容：$x$ 后续被转成宏，公式不丢
        self.assertIn('mathinline', after)
        # 转换后 XHTML 必须配对（防 PUT 400）
        balanced, _ = self.updater._check_xhtml_balance(after)
        self.assertTrue(balanced)

    def test_nested_math_span_kept_balanced(self):
        # 嵌套 math span：不剥壳（保结构完整），不产生孤立标签
        html = '<td><span class="math-inline"><span>$x$</span></span></td>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['span_removed'], 0)
        balanced, report = self.updater._check_xhtml_balance(after)
        self.assertTrue(balanced, report)
        self.assertIn('mathinline', after)

    def test_xhtml_balance_checker(self):
        ok, _ = self.updater._check_xhtml_balance('<p><b>x</b></p><ac:image><ri:attachment /></ac:image>')
        self.assertTrue(ok)
        ok, _ = self.updater._check_xhtml_balance('<p>a<br>b<img src="x" /></p>')
        self.assertTrue(ok)
        ok, report = self.updater._check_xhtml_balance('<p><span>x</span></span></p>')
        self.assertFalse(ok)
        ok, report = self.updater._check_xhtml_balance('<p><span>x</p>')
        self.assertFalse(ok)
        ok, report = self.updater._check_xhtml_balance('<p>a &lt; b &amp; c</p>')
        self.assertTrue(ok)

    def test_xhtml_balance_ignores_cdata_and_comments(self):
        # CDATA 内的 <mmc::Irlock> 类代码文本不是标签，不应污染配对检查（历史误报根因）
        html = ('<ac:structured-macro ac:name="code"><ac:plain-text-body>'
                '<![CDATA[uavcan::ReceivedDataStructure<mmc::Irlock> &msg)'
                'if (x < y && a > b) {}]]></ac:plain-text-body></ac:structured-macro>')
        ok, report = self.updater._check_xhtml_balance(html)
        self.assertTrue(ok, report)
        # 注释内含 <tag> 样文本同样忽略
        html2 = '<!-- if (a < b) --><p>x</p>'
        ok, report = self.updater._check_xhtml_balance(html2)
        self.assertTrue(ok, report)

    def test_apply_alignment_left(self):
        html = ('<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                '<ac:plain-text-body><![CDATA[x]]></ac:plain-text-body>'
                '</ac:structured-macro>')
        result, count = self.updater._apply_alignment(html)
        self.assertEqual(count, 1)
        self.assertIn('alignment">left<', result)

    def test_apply_alignment_idempotent_when_already_left(self):
        # 已是 alignment=left 的宏：跳过不重写（防版本号虚涨）
        html = ('<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                '<ac:parameter ac:name="alignment">left</ac:parameter>'
                '<ac:plain-text-body><![CDATA[x]]></ac:plain-text-body>'
                '</ac:structured-macro>')
        result, count = self.updater._apply_alignment(html)
        self.assertEqual(count, 0)
        self.assertEqual(result, html)  # 内容字节不变

    def test_apply_alignment_overrides_center(self):
        html = ('<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                '<ac:parameter ac:name="alignment">center</ac:parameter>'
                '<ac:plain-text-body><![CDATA[x]]></ac:plain-text-body>'
                '</ac:structured-macro>')
        result, count = self.updater._apply_alignment(html)
        self.assertEqual(count, 1)
        self.assertNotIn('center', result)
        self.assertIn('alignment">left<', result)

    def test_apply_alignment_center_mode_skips(self):
        center_updater = ConfluenceMathUpdater(math_align='center')
        html = ('<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                '<ac:plain-text-body><![CDATA[x]]></ac:plain-text-body>'
                '</ac:structured-macro>')
        result, count = center_updater._apply_alignment(html)
        self.assertEqual(count, 0)
        self.assertIn('mathblock', result)

    def test_verify_passes(self):
        before = '<p>$x^2$</p>'
        after, stats = self.updater.convert_math(before)
        passed, report = self.updater.verify(before, after, stats)
        self.assertTrue(passed)

    def test_run_batch_continues_on_error(self):
        with patch.object(self.updater, 'process_single',
                          side_effect=[(True, 'ok'), (False, 'fail'), (True, 'ok2')]) as ps, \
             patch('builtins.print'):
            self.updater._run_batch([(1, 'a', 0), (2, 'b', 0), (3, 'c', 0)])
        self.assertEqual(ps.call_count, 3)

    def test_run_batch_stop_on_error(self):
        with patch.object(self.updater, 'process_single',
                          side_effect=[(True, 'ok'), (False, 'fail'), (True, 'ok2')]) as ps, \
             patch('builtins.print'):
            self.updater._run_batch([(1, 'a', 0), (2, 'b', 0), (3, 'c', 0)],
                                    stop_on_error=True)
        self.assertEqual(ps.call_count, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
