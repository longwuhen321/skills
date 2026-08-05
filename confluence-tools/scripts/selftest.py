"""
离线自测脚本（不依赖 Confluence 服务器）

运行: python selftest.py

覆盖:
  - common:        429 限流重试、分页收集、token 环境变量覆盖
  - md_import:     占位符保护/还原、公式/代码转换、版本号流程、标题内存匹配
  - math_upgrade:  $/$$/```latex``` 转换、旧宏升级、原生 alignment、span 限制删除、verify
  - md_export:     storage → Markdown（宏还原、图片引用改写、树导出结构）

所有用例 mock 掉配置与网络，不触碰真实 config.py 和服务器。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from common import (load_config, request_with_retry, collect_space_pages,
                    build_block_template)
from debug_utils import cleanup_debug
from md_import import MarkdownImporter
from math_upgrade import ConfluenceMathUpdater
from md_export import ConfluenceExporter

MOCK_CFG = {
    'common_config': {
        'confluence_url': 'http://test:8090',
        'confluence_token': 'test-token',
    },
    'import_config': {'space': 'TEST', 'math_align': 'left'},
    'upgrade_config': {'math_align': 'left', 'auto_update': True,
                       'ai_verify': False, 'recursive': True, 'max_depth': 0},
    'export_config': {'output_dir': 'confluence_export', 'recursive': True,
                      'space': ''},
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

    def test_get_timestamp_dirs_sorted_by_name_across_subdirs(self):
        # 跨功能子目录（import/upgrade/export）的时间戳目录必须按时间戳名排序，
        # 不能按完整路径（字母序 export < import < upgrade 会干扰"最旧优先"）
        from debug_utils import _get_timestamp_dirs
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'upgrade' / '20260801_000000').mkdir(parents=True)
            (root / 'export' / '20260804_000000').mkdir(parents=True)
            (root / 'import' / '20260802_000000').mkdir(parents=True)
            dirs = _get_timestamp_dirs(str(root))
            names = [os.path.basename(d) for d in dirs]
            self.assertEqual(names, ['20260801_000000', '20260802_000000',
                                     '20260804_000000'])

    def test_cleanup_debug_by_count_when_size_ok(self):
        # 数量超（>keep_recent）但大小未超阈值 → 也触发清理（二选一即清理）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(5):
                d = root / f'2026080{i}_000000'
                d.mkdir()
                (d / 'a.html').write_text('x' * 100, encoding='utf-8')
            cleanup_debug(str(root), max_size_mb=50, keep_recent=2)
            remaining = [p for p in root.iterdir() if p.is_dir()]
            self.assertEqual(len(remaining), 2)  # 保留最近 2 个

    def test_cleanup_debug_keeps_min_when_count_low(self):
        # 数量少于 keep_recent 时，即使大小超标也不删（保留下限）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / '20260801_000000'
            d.mkdir()
            (d / 'big.html').write_text('x' * 100, encoding='utf-8')
            cleanup_debug(str(root), max_size_mb=0, keep_recent=2)
            self.assertTrue(d.exists())  # 未删除

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

    def test_load_config_returns_export_config(self):
        # 回归：load_config 曾漏组装 export_config 分组，导致 md_export
        # 永远拿不到 config.py 中的导出配置（输出目录/递归/空间）
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, 'config.py')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                f.write("common_config = {'confluence_url': 'http://x',"
                        " 'confluence_token': 't'}\n")
                f.write("export_config = {'output_dir': 'E:/out',"
                        " 'recursive': False, 'space': 'ES'}\n")
            with patch('common.CONFIG_PATH', cfg_path):
                cfg = load_config()
        self.assertEqual(cfg['export_config']['output_dir'], 'E:/out')
        self.assertEqual(cfg['export_config']['space'], 'ES')


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

    def test_inline_math_inequality_protected(self):
        # LaTeX 不等式 $0<x<\pi$ 应被保护层识别（历史 bug：内容含 < > 被漏掉，
        # markdown2 转出裸 <x 导致 Confluence 400）
        md = '当 $0<x<\\pi$ 时'
        protected, blocks = self.importer._protect_math_blocks(md)
        self.assertEqual(len(blocks), 1)
        self.assertIn('MATH_INLINE_', protected)
        # HTML 阶段转换为 mathinline 宏，body 中 < 转义为 &lt;
        html = '<p>当 $0<x<\\pi$ 时</p>'
        result = self.importer._convert_math_blocks(html)
        self.assertIn('mathinline', result)
        self.assertIn('0&lt;x&lt;\\pi', result)
        self.assertNotIn('$0<x<\\pi$', result)

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
    def test_md_links_ignores_macro_cdata(self):
        # mathblock 宏 CDATA 内 LaTeX \right](0) 不应被图片正则误判（历史 bug：
        # <![CDATA[ 前缀含字面 ![，与 ]( 配对把 0 当图片路径）
        html = ('<p>text</p>'
                '<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                '<ac:parameter ac:name="alignment">left</ac:parameter>'
                '<ac:plain-text-body><![CDATA[{\\displaystyle \\mu _{n}=(-1)^{n}'
                '\\operatorname {E} \\left[e^{-sX}\\right](0).}]]></ac:plain-text-body>'
                '</ac:structured-macro>')
        result = self.importer._convert_md_links(html, 'dummy.md', '999')
        self.assertEqual(self.importer.failed_images, [])  # 不再误报
        self.assertIn('\\right](0).', result)            # CDATA 内容原样保留
        # 正常图片链接仍应被识别并记入失败报告
        html2 = '<p>![pic](missing.png)</p>'
        self.importer._convert_md_links(html2, 'dummy.md', '999')
        self.assertEqual(len(self.importer.failed_images), 1)

    def test_upload_attachment_updates_existing(self):
        # 同名附件已存在（页面更新场景）：POST 创建 400 → GET 查到 id → POST /data 更新
        from types import SimpleNamespace

        def make_resp(status, json_data=None, text=""):
            resp = SimpleNamespace(status_code=status, text=text)
            if json_data is not None:
                resp.json = lambda: json_data
            def _raise():
                if status >= 400:
                    raise Exception(f"HTTP {status}")
            resp.raise_for_status = _raise
            return resp

        page_id = '123'
        file_path = os.path.join(tempfile.gettempdir(), 'existing.png')
        with open(file_path, 'wb') as f:
            f.write(b'x')

        create_resp = make_resp(400, text='Cannot add a new attachment with same file name')
        lookup_resp = make_resp(200, json_data={'results': [{'id': '999'}]})
        update_resp = make_resp(200)

        # request_with_retry 内部走 session.request(method, url, ...)
        with mock.patch.object(self.importer.session, 'request',
                               side_effect=[create_resp, lookup_resp, update_resp]) as mreq:
            result = self.importer._upload_attachment(page_id, file_path)
        self.assertEqual(result, f'/download/attachments/{page_id}/existing.png')
        self.assertEqual(mreq.call_args_list[0][0][0], 'POST')
        self.assertIn('/child/attachment', mreq.call_args_list[0][0][1])          # 创建端点
        self.assertNotIn('/data', mreq.call_args_list[0][0][1])
        self.assertEqual(mreq.call_args_list[1][0][0], 'GET')                     # 查附件 id
        self.assertEqual(mreq.call_args_list[2][0][0], 'POST')
        self.assertIn('/child/attachment/999/data', mreq.call_args_list[2][0][1])  # 更新端点
        os.unlink(file_path)


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

    def test_default_parent_id_from_config(self):
        # 配置 default_parent_id：新建页面时挂到该父级下
        cfg = dict(MOCK_CFG)
        cfg['import_config'] = dict(MOCK_CFG['import_config'], default_parent_id='777')
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False,
                                         encoding='utf-8') as f:
            f.write('# Hello\n\nplain text')
            md_path = f.name
        try:
            with patch('md_import.load_config', return_value=cfg):
                importer = MarkdownImporter(space_key='TEST')
            self.assertEqual(importer.default_parent_id, '777')
            with patch.object(importer, '_find_page_by_title', return_value=(None, None)), \
                 patch.object(importer, '_create_page', return_value=('999', 1)) as cp:
                page_id = importer.import_markdown(md_path)
            self.assertEqual(page_id, '999')
            self.assertEqual(cp.call_args[0][2], '777')  # parent_id 传给 _create_page
        finally:
            os.unlink(md_path)

    def test_default_page_name_from_config(self):
        # 配置 default_page_name：标题用它，而非 md 文件名
        cfg = dict(MOCK_CFG)
        cfg['import_config'] = dict(MOCK_CFG['import_config'], default_page_name='Config Title')
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False,
                                         encoding='utf-8') as f:
            f.write('# Hello\n\nplain text')
            md_path = f.name
        try:
            with patch('md_import.load_config', return_value=cfg):
                importer = MarkdownImporter(space_key='TEST')
            self.assertEqual(importer.default_page_name, 'Config Title')
            with patch.object(importer, '_find_page_by_title', return_value=(None, None)), \
                 patch.object(importer, '_create_page', return_value=('999', 1)) as cp:
                importer.import_markdown(md_path)
            self.assertEqual(cp.call_args[0][0], 'Config Title')  # title 用配置值
        finally:
            os.unlink(md_path)

    def test_cli_args_override_config(self):
        # CLI 参数（--parent-id/--page-name）优先于配置默认值
        cfg = dict(MOCK_CFG)
        cfg['import_config'] = dict(MOCK_CFG['import_config'],
                                    default_parent_id='777', default_page_name='Config Title')
        with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False,
                                         encoding='utf-8') as f:
            f.write('# Hello\n\nplain text')
            md_path = f.name
        try:
            with patch('md_import.load_config', return_value=cfg):
                importer = MarkdownImporter(space_key='TEST')
            with patch.object(importer, '_find_page_by_title', return_value=(None, None)), \
                 patch.object(importer, '_create_page', return_value=('999', 1)) as cp:
                importer.import_markdown(md_path, parent_id='888', page_name='CLI Title')
            self.assertEqual(cp.call_args[0][0], 'CLI Title')  # 标题被 CLI 覆盖
            self.assertEqual(cp.call_args[0][2], '888')        # 父级被 CLI 覆盖
        finally:
            os.unlink(md_path)

    # ---- --dir 树导入 ----

    def _tree_cfg(self, **kw):
        cfg = dict(MOCK_CFG)
        ic = dict(MOCK_CFG['import_config'], tree_import=True, fix_hierarchy='confirm')
        ic.update(kw)
        cfg['import_config'] = ic
        return cfg

    def test_tree_import_disabled(self):
        # tree_import 未开启：--dir 直接报错
        importer = MarkdownImporter(space_key='TEST')  # MOCK_CFG 无 tree_import → False
        self.assertFalse(importer.tree_import)
        with self.assertRaises(SystemExit):
            importer.import_tree('C:/fake')

    def test_scan_tree_builds_hierarchy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Parent.md').write_text('# p', encoding='utf-8')
            child = root / 'Child'
            child.mkdir()
            (child / 'Child.md').write_text('# c', encoding='utf-8')
            (child / 'Child.assets').mkdir()
            importer = MarkdownImporter(space_key='TEST')
            tree = importer._scan_tree(td)
            self.assertIsNotNone(tree['md_path'])       # 根取同名 md
            self.assertEqual(len(tree['children']), 1)
            c = tree['children'][0]
            self.assertEqual(c['name'], 'Child')
            self.assertEqual(c['md_path'].name, 'Child.md')
            self.assertEqual(c['children'], [])          # .assets 不算节点

    def test_scan_tree_skips_multiple_md(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'A.md').write_text('a', encoding='utf-8')
            (root / 'B.md').write_text('b', encoding='utf-8')
            importer = MarkdownImporter(space_key='TEST')
            tree = importer._scan_tree(td)
            self.assertIsNone(tree['md_path'])           # 多个 md 无法确定内容
            self.assertEqual(tree['children'], [])

    def test_build_plan_statuses(self):
        importer = MarkdownImporter(space_key='TEST', fix_hierarchy='confirm')
        node = {'name': 'Parent', 'md_path': 'P.md',
                'children': [{'name': 'Child', 'md_path': 'C.md', 'children': []}]}
        with patch.object(importer, '_find_page_by_title',
                          side_effect=lambda t: ('11', 3) if t == 'Parent' else ('22', 3)), \
             patch.object(importer, '_get_page_parent',
                          side_effect=lambda pid: (None, None) if pid == '11' else ('99', 'Elsewhere')):
            plan = importer._build_plan(node)
        self.assertEqual(plan['status'], 'update')                    # Parent 命中且在根
        self.assertEqual(plan['children'][0]['status'], 'move')        # Child 命中但父级不符

    def test_execute_plan_new_passes_parent_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Parent.md').write_text('# p', encoding='utf-8')
            child = root / 'Child'
            child.mkdir()
            (child / 'Child.md').write_text('# c', encoding='utf-8')
            importer = None
            with patch('md_import.load_config', return_value=self._tree_cfg()):
                importer = MarkdownImporter(space_key='TEST', fix_hierarchy='confirm')
            with patch.object(importer, '_find_page_by_title', return_value=(None, None)), \
                 patch.object(importer, '_create_page',
                              side_effect=lambda t, c, pid: (str(len(importer._title_id_map) + 100), 1)) as cp, \
                 patch.object(importer, '_convert_md_links', side_effect=lambda h, p, pid: h):
                importer.import_tree(td, yes=True)
            # 父先建（parent_id=None），子后建（parent_id=父 id）
            self.assertEqual(cp.call_args_list[0][0][2], None)
            self.assertEqual(cp.call_args_list[1][0][2], '100')

    def test_fix_hierarchy_off_no_ancestors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Parent.md').write_text('# p', encoding='utf-8')
            with patch('md_import.load_config', return_value=self._tree_cfg()):
                importer = MarkdownImporter(space_key='TEST', fix_hierarchy='off')
            with patch.object(importer, '_find_page_by_title', return_value=('11', 3)), \
                 patch.object(importer, '_get_page_parent', return_value=('99', 'Elsewhere')), \
                 patch.object(importer, '_update_page', side_effect=lambda *a, **k: ('11', 4)) as up, \
                 patch.object(importer, '_convert_md_links', side_effect=lambda h, p, pid: h):
                importer.import_tree(td, yes=True)
            self.assertNotIn('ancestors', up.call_args.kwargs)   # off：不移动

    def test_execute_plan_move_applies_ancestors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            parent_dir = root / 'Parent'
            parent_dir.mkdir()
            (parent_dir / 'Parent.md').write_text('# p', encoding='utf-8')
            child = parent_dir / 'Child'
            child.mkdir()
            (child / 'Child.md').write_text('# c', encoding='utf-8')
            with patch('md_import.load_config', return_value=self._tree_cfg()):
                importer = MarkdownImporter(space_key='TEST', fix_hierarchy='confirm')
            with patch.object(importer, '_find_page_by_title',
                              side_effect=lambda t: ('111' if t == 'Parent' else '222', 3)), \
                 patch.object(importer, '_get_page_parent',
                              side_effect=lambda pid: (None, None) if pid == '111' else ('999', 'Elsewhere')), \
                 patch.object(importer, '_update_page',
                              side_effect=lambda *a, **k: (a[0], a[3] + 1)) as up, \
                 patch.object(importer, '_convert_md_links', side_effect=lambda h, p, pid: h):
                importer.import_tree(str(parent_dir), yes=True)
            move_call = up.call_args_list[1]                       # 子页面移动
            self.assertEqual(move_call.kwargs.get('ancestors'), '111')  # 用父页面 id

    def test_fix_hierarchy_confirm_prompts_and_cancel(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Parent.md').write_text('# p', encoding='utf-8')
            with patch('md_import.load_config', return_value=self._tree_cfg()):
                importer = MarkdownImporter(space_key='TEST', fix_hierarchy='confirm')
            with patch.object(importer, '_find_page_by_title', return_value=('11', 3)), \
                 patch.object(importer, '_get_page_parent', return_value=('99', 'Elsewhere')), \
                 patch.object(importer, '_update_page', side_effect=lambda *a, **k: ('11', 4)) as up, \
                 patch.object(importer, '_convert_md_links', side_effect=lambda h, p, pid: h):
                with patch('builtins.input', return_value='n') as inp:
                    importer.import_tree(td)
            inp.assert_called_once()     # confirm + move 触发确认
            up.assert_not_called()       # 取消后不执行写操作

    def test_plan_only_no_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'Parent.md').write_text('# p', encoding='utf-8')
            with patch('md_import.load_config', return_value=self._tree_cfg()):
                importer = MarkdownImporter(space_key='TEST')
            with patch.object(importer, '_find_page_by_title', return_value=(None, None)), \
                 patch.object(importer, '_create_page') as cp, \
                 patch.object(importer, '_update_page') as up:
                importer.import_tree(td, plan_only=True)
            cp.assert_not_called()
            up.assert_not_called()

    def test_toc_added_when_headings_meet_threshold(self):
        cfg = dict(MOCK_CFG)
        cfg['import_config'] = dict(MOCK_CFG['import_config'],
                                    toc_enabled=True, toc_min_headings=4)
        with patch('md_import.load_config', return_value=cfg):
            importer = MarkdownImporter(space_key='TEST')
        md = '# Title\n\n## A\n\n## B\n\n## C\n\n## D\n\n## E\n'
        html = importer._convert_md_to_storage(md)
        self.assertIn('<ac:structured-macro ac:name="toc"', html)
        self.assertTrue(html.startswith('<ac:structured-macro'))

    def test_toc_not_added_below_threshold(self):
        cfg = dict(MOCK_CFG)
        cfg['import_config'] = dict(MOCK_CFG['import_config'],
                                    toc_enabled=True, toc_min_headings=4)
        with patch('md_import.load_config', return_value=cfg):
            importer = MarkdownImporter(space_key='TEST')
        md = '# Title\n\n## A\n\n## B\n\n## C\n'
        html = importer._convert_md_to_storage(md)
        self.assertNotIn('ac:name="toc"', html)

    def test_toc_disabled(self):
        cfg = dict(MOCK_CFG)
        cfg['import_config'] = dict(MOCK_CFG['import_config'],
                                    toc_enabled=False, toc_min_headings=4)
        with patch('md_import.load_config', return_value=cfg):
            importer = MarkdownImporter(space_key='TEST')
        md = '# Title\n\n## A\n\n## B\n\n## C\n\n## D\n\n## E\n'
        html = importer._convert_md_to_storage(md)
        self.assertNotIn('ac:name="toc"', html)

    def test_self_closing_macro_does_not_swallow_images(self):
        # 自闭合宏（toc，无 </ac:structured-macro>）后紧跟图片：保护段不应把图片吞掉。
        # 历史 bug：旧正则 .*?</ac:structured-macro> 从自闭合宏开始跨段匹配到下一个
        # 成对宏的闭合标签，中间图片被跳过转换（TECS 页面 3 张图缺失即此因）。
        html = ('<ac:structured-macro ac:name="toc" ac:schema-version="1" data-layout="default"/>'
                '<p><img src="./a.png" alt="a" /></p>'
                '<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
                '<ac:parameter ac:name="body">$x$</ac:parameter></ac:structured-macro>')
        with tempfile.TemporaryDirectory() as td:
            md_dir = Path(td)
            (md_dir / 'a.png').write_bytes(b'x')
            md_file = md_dir / 'doc.md'
            md_file.write_text('# t', encoding='utf-8')
            with patch.object(self.importer, '_upload_attachment', return_value='http://fake'):
                final = self.importer._convert_md_links(html, str(md_file), '999')
        self.assertIn('ri:filename="a.png"', final)


    def test_highlight_marks_ignore_base64_padding(self):
        # base64 内嵌图片的 data URI 以 == 结尾（base64 padding），==高亮== 正则若
        # 跨图配对会把 <strong> 写进 src 属性值 → XHTML 非法 → 导入 400
        # （Altitude Mode (Fixed-Wing) 页面实测）。修复：转换前整体保护 <img> 标签。
        html = ('<p>==真高亮==</p>'
                '<p><img src="data:image/png;base64,AAAABBBB==" alt="" title="Easy to fly" />'
                '&#160;<img src="data:image/svg+xml;base64,CCCCDDDD==" alt="" title="Manual" /></p>')
        result = self.importer._convert_highlight_marks(html)
        # 两个 img 的 src 保持完整 base64（== padding 不被吞，也无 <strong> 混入属性）
        self.assertIn('src="data:image/png;base64,AAAABBBB=="', result)
        self.assertIn('src="data:image/svg+xml;base64,CCCCDDDD=="', result)
        # 真正的 ==高亮== 仍正常转换
        self.assertIn('<strong>真高亮</strong>', result)
        # 不产生畸形结构（base64 截断 + <strong> 混入 src 属性值）
        self.assertNotIn('BBB<strong>', result)

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

    def test_inline_math_inequality_converts(self):
        # storage 格式中 < 已转义为 &lt;：$0&lt;x&lt;\pi$ 应转换为 mathinline 宏。
        # body 中 & 再转义为 &amp;（XML 解析后还原为 &lt;，渲染为 <）
        html = '<p>$0&lt;x&lt;\\pi$</p>'
        after, stats = self.updater.convert_math(html)
        self.assertEqual(stats['inline'], 1)
        self.assertIn('mathinline', after)
        self.assertIn('0&amp;lt;x&amp;lt;\\pi', after)
        self.assertNotIn('$0&lt;x&lt;\\pi$', after)


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


class TestMdExport(unittest.TestCase):

    def setUp(self):
        self.load_patcher = patch('md_export.load_config', return_value=MOCK_CFG)
        self.load_patcher.start()
        self.tmp = tempfile.TemporaryDirectory()
        # 隔离 debug 目录：SKILL_ROOT 指向临时目录，避免测试写真实 skill 的 debug/
        self.skill_root_patcher = patch('md_export.SKILL_ROOT', self.tmp.name)
        self.skill_root_patcher.start()
        self.exporter = ConfluenceExporter(output_dir=self.tmp.name)
        self.att_patcher = patch.object(self.exporter, 'fetch_attachments',
                                        return_value=[])
        self.att_patcher.start()

    def tearDown(self):
        self.att_patcher.stop()
        self.skill_root_patcher.stop()
        self.load_patcher.stop()
        self.tmp.cleanup()

    def _convert(self, storage_html, page_name='测试页', page_id='1'):
        return self.exporter._convert_storage_to_markdown(
            storage_html, Path(self.tmp.name) / page_name, page_id)

    def _mathblock(self, content):
        return ('<ac:structured-macro ac:name="mathblock" ac:schema-version="1">'
                f'<ac:parameter ac:name="alignment">left</ac:parameter>'
                f'<ac:plain-text-body><![CDATA[{content}]]></ac:plain-text-body>'
                '</ac:structured-macro>')

    def test_mathblock_to_block_math(self):
        md = self._convert(self._mathblock('E=mc^2'))
        self.assertIn('$$E=mc^2$$', md)

    def test_mathblock_multiline_cdata_stripped(self):
        md = self._convert(self._mathblock('\nE = mc^2\n'))
        self.assertIn('$$E = mc^2$$', md)

    def test_mathinline_unescape_to_inline_math(self):
        html = ('<ac:structured-macro ac:name="mathinline" ac:schema-version="1">'
                '<ac:parameter ac:name="body">a &lt; b</ac:parameter>'
                '</ac:structured-macro>')
        md = self._convert(html)
        self.assertIn('$a < b$', md)

    def test_old_mathjax_macros_compat(self):
        html = ('<ac:structured-macro ac:name="mathjax-inline-macro" ac:schema-version="1">'
                '<ac:parameter ac:name="equation">x^2</ac:parameter>'
                '</ac:structured-macro>')
        md = self._convert(html)
        self.assertIn('$x^2$', md)

    def test_code_macro_to_fence(self):
        html = ('<ac:structured-macro ac:name="code" ac:schema-version="1">'
                '<ac:parameter ac:name="language">python</ac:parameter>'
                '<ac:plain-text-body><![CDATA[print("hi")]]></ac:plain-text-body>'
                '</ac:structured-macro>')
        md = self._convert(html)
        self.assertIn('```python', md)
        self.assertIn('print("hi")', md)

    def test_toc_macro_to_marker(self):
        html = '<ac:structured-macro ac:name="toc" ac:schema-version="1" data-layout="default"/>'
        md = self._convert(html)
        self.assertIn('[toc]', md)

    def test_toc_inside_h1_stays_on_own_line(self):
        # toc 宏嵌在 h1 内（<h1><ac:toc/><br/>标题</h1>）时，[toc] 必须独占一行，
        # 否则 Typora 不渲染目录（回归：曾导出为 "# [toc] 前提："）
        html = ('<h1><ac:structured-macro ac:name="toc" ac:schema-version="1"/>'
                '<br/>前提：</h1><p>正文</p>')
        md = self._convert(html)
        self.assertIn('[toc]\n\n# 前提：', md)

    def test_empty_pre_dropped_no_empty_fence(self):
        # 页面留白用的空 <pre><br/></pre> 不应导出为空代码围栏
        html = '<p>文字</p><pre><br/></pre><pre>   </pre><p>更多</p>'
        md = self._convert(html)
        self.assertNotIn('```', md)

    def test_ac_link_page_with_id_to_markdown_link(self):
        html = ('<p>查看：<ac:link><ri:page ri:content-id="12345" '
                'ri:content-title="rcS脚本解读"/></ac:link>。</p>')
        md = self._convert(html)
        self.assertIn('[rcS脚本解读](http://test:8090/pages/viewpage.action?pageId=12345)', md)

    def test_ac_link_page_without_id_keeps_title(self):
        # 无 content-id 的内链无法构造 URL：至少保留页面标题文本，不丢内容
        html = ('<p>参数详情可查看 <ac:link>'
                '<ri:page ri:content-title="控制分配(Control Allocation) 相关参数"/>'
                '</ac:link>，</p>')
        md = self._convert(html)
        self.assertIn('控制分配(Control Allocation) 相关参数', md)
        self.assertNotIn('ac:link', md)

    def test_ac_link_url_with_body_to_markdown_link(self):
        html = ('<p><ac:link><ri:url ri:value="https://example.com/a"/>'
                '<ac:link-body>示例</ac:link-body></ac:link></p>')
        md = self._convert(html)
        self.assertIn('[示例](https://example.com/a)', md)

    def test_note_macro_to_blockquote(self):
        html = ('<ac:structured-macro ac:name="note" ac:schema-version="1">'
                '<ac:rich-text-body><p>注意内容</p></ac:rich-text-body>'
                '</ac:structured-macro>')
        md = self._convert(html)
        self.assertIn('> 注意内容', md)

    def test_unknown_macro_to_comment(self):
        html = ('<ac:structured-macro ac:name="unknown-macro" ac:schema-version="1">'
                '<ac:parameter ac:name="x">1</ac:parameter>'
                '</ac:structured-macro>')
        md = self._convert(html)
        self.assertIn('<!-- 未处理的宏: unknown-macro -->', md)
        self.assertIn('unknown-macro', self.exporter.stats['skipped_macros'])

    def test_image_download_rewrites_reference(self):
        html = ('<ac:image><ri:attachment ri:filename="pic.png" '
                'ri:version-at-save="1"/></ac:image>')
        attachments = [{'id': '1', 'title': 'pic.png',
                        '_links': {'download': '/download/attachments/5/pic.png'}}]
        with patch.object(self.exporter, 'fetch_attachments',
                          return_value=attachments), \
             patch.object(self.exporter, '_download_attachment',
                          return_value='1_pic.png') as dl:
            md = self._convert(html, page_name='测试页', page_id='5')
        self.assertIn('![pic.png](./测试页.assets/1_pic.png)', md)
        dl.assert_called_once()

    def test_no_assets_dir_without_images(self):
        page_dir = Path(self.tmp.name) / '无图页'
        md = self._convert('<p>hello</p>', page_name='无图页')
        self.assertNotIn('![', md)
        self.assertFalse((page_dir / '无图页.assets').exists())

    def test_table_to_markdown_table(self):
        html = ('<table><tbody><tr><th>H1</th><th>H2</th></tr>'
                '<tr><td>a</td><td>b</td></tr></tbody></table>')
        md = self._convert(html)
        self.assertIn('| H1 | H2 |', md)
        self.assertIn('| --- | --- |', md)
        self.assertIn('| a | b |', md)

    def test_table_with_code_kept_as_html(self):
        # 表格单元格内含代码块 → 整体保留为原始 HTML（GFM 表格不能含多行围栏）
        html = ('<table><tbody><tr><th>代码</th><th>说明</th></tr>'
                '<tr><td><pre><code>if (a || b) {\n  x();\n}</code></pre></td>'
                '<td>条件判断</td></tr></tbody></table>')
        md = self._convert(html)
        self.assertIn('<table>', md)
        self.assertIn('if (a || b)', md)
        self.assertNotIn('| 代码 |', md)

    def test_table_html_code_placeholder_restored(self):
        # HTML 表格内的代码占位符必须被还原为原文，且无占位符残留
        html = ('<table><tbody><tr><td><pre><code>int x = 1;</code></pre></td>'
                '<td>说明</td></tr></tbody></table>')
        md = self._convert(html)
        self.assertIn('int x = 1;', md)
        self.assertNotIn('⟦', md)

    def test_table_pipe_escaped_in_gfm(self):
        # 纯文本表格单元格内的 | 需转义，防止被当成列分隔
        html = ('<table><tbody><tr><th>H</th></tr>'
                '<tr><td>a|b</td></tr></tbody></table>')
        md = self._convert(html)
        self.assertIn(r'a\|b', md)

    def test_heading_and_list_conversion(self):
        html = '<h1>标题</h1><ul><li>甲</li><li>乙</li></ul>'
        md = self._convert(html)
        self.assertIn('# 标题', md)
        self.assertIn('- 甲', md)
        self.assertIn('- 乙', md)

    def test_front_matter_title_escaped(self):
        page = {'title': 'A: B',
                'raw': {'version': {'when': '2026-01-01T00:00:00.000Z'}}}
        fm = self.exporter._front_matter(page)
        self.assertIn('title: "A: B"', fm)
        self.assertIn('date: 2026-01-01T00:00:00.000Z', fm)
        self.assertIn('math: true', fm)

    def test_export_page_creates_structure(self):
        page = {'page_id': '5', 'title': '测试页', 'version': 3, 'space_key': 'TEST',
                'storage': '<p>hello $x$</p>',
                'raw': {'version': {'when': '2026-01-01T00:00:00.000Z'}}}
        with patch.object(self.exporter, 'fetch_page', return_value=page), \
             patch.object(self.exporter, 'get_child_pages', return_value=[]):
            md_path = self.exporter.export_page('5')
        md_path = Path(self.tmp.name) / '测试页' / '测试页.md'
        self.assertTrue(md_path.exists())
        text = md_path.read_text(encoding='utf-8')
        self.assertIn('title: "测试页"', text)
        self.assertIn('math: true', text)
        self.assertIn('hello', text)

    def test_export_saves_storage_debug(self):
        # 导出时每页原始 storage 保存到 debug/export/<时间戳>/<page_id>_<标题>.html
        page = {'page_id': '5', 'title': '测试页', 'version': 3, 'space_key': 'TEST',
                'storage': '<p>原始内容</p>',
                'raw': {'version': {'when': '2026-01-01T00:00:00.000Z'}}}
        with patch.object(self.exporter, 'fetch_page', return_value=page), \
             patch.object(self.exporter, 'get_child_pages', return_value=[]):
            self.exporter.export_page('5')
        export_dir = Path(self.tmp.name) / 'debug' / 'export'
        self.assertTrue(export_dir.exists())
        files = list(export_dir.glob('*/*.html'))
        self.assertEqual(len(files), 1)
        self.assertIn('5_测试页.html', files[0].name)
        self.assertIn('原始内容', files[0].read_text(encoding='utf-8'))

    def test_recursive_off_skips_children(self):
        page = {'page_id': '5', 'title': '父页', 'version': 1, 'space_key': 'TEST',
                'storage': '<p>parent</p>', 'raw': {'version': {'when': ''}}}
        with patch.object(self.exporter, 'recursive', False), \
             patch.object(self.exporter, 'fetch_page', return_value=page), \
             patch.object(self.exporter, 'get_child_pages') as gc:
            self.exporter.export_page('5')
        gc.assert_not_called()

    def test_recursive_on_exports_children(self):
        page1 = {'page_id': '5', 'title': '父页', 'version': 1, 'space_key': 'TEST',
                 'storage': '<p>parent</p>', 'raw': {'version': {'when': ''}}}
        page2 = {'page_id': '6', 'title': '子页', 'version': 1, 'space_key': 'TEST',
                 'storage': '<p>child</p>', 'raw': {'version': {'when': ''}}}
        with patch.object(self.exporter, 'fetch_page', side_effect=[page1, page2]), \
             patch.object(self.exporter, 'get_child_pages',
                          side_effect=[[('6', '子页')], []]):
            self.exporter.export_page('5')
        root = Path(self.tmp.name)
        self.assertTrue((root / '父页' / '父页.md').exists())
        self.assertTrue((root / '父页' / '子页' / '子页.md').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
