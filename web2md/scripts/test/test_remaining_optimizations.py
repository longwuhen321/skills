import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup, Comment

import web2md
import package_check
import merge_paragraphs as merge_module
from package_check import main as package_main, scan_package
from config_literal import ConfigLiteralError, parse_literal_dict
from merge_paragraphs import merge_markdown_paragraphs


class LiteralConfigTests(unittest.TestCase):
    def test_literal_dict_is_accepted(self):
        cfg = parse_literal_dict(
            "web2md_config = {'timeout': 30, 'page_nav': False}\n",
            'web2md_config',
        )
        self.assertEqual(cfg, {'timeout': 30, 'page_nav': False})

    def test_import_is_rejected(self):
        with self.assertRaises(ConfigLiteralError):
            parse_literal_dict(
                "import os\nweb2md_config = {'timeout': 30}\n",
                'web2md_config',
            )

    def test_annotated_assignment_is_rejected_without_evaluating_annotation(self):
        with self.assertRaises(ConfigLiteralError):
            parse_literal_dict(
                "web2md_config: dangerous() = {'timeout': 30}\n",
                'web2md_config',
            )

    def test_function_call_is_rejected(self):
        with self.assertRaises(ConfigLiteralError):
            parse_literal_dict(
                "web2md_config = {'timeout': int('30')}\n",
                'web2md_config',
            )

    def test_side_effect_statement_is_rejected_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'marker.txt'
            text = (
                "web2md_config = {'timeout': 30}\n"
                f"open({str(marker)!r}, 'w').write('unsafe')\n"
            )
            with self.assertRaises(ConfigLiteralError):
                parse_literal_dict(text, 'web2md_config')
            self.assertFalse(marker.exists())

    def test_runtime_loader_rejects_side_effect_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'marker.txt'
            config = Path(tmp) / 'config.py'
            config.write_text(
                "web2md_config = {'timeout': 9}\n"
                f"open({str(marker)!r}, 'w').write('unsafe')\n",
                encoding='utf-8',
            )
            with patch.object(web2md, 'CONFIG_PATH', str(config)), \
                    contextlib.redirect_stdout(io.StringIO()):
                loaded = web2md.load_config()
            self.assertEqual(loaded['timeout'], 30)
            self.assertFalse(marker.exists())


class PackagingCheckTests(unittest.TestCase):
    def test_clean_literal_package_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'SKILL.md').write_text('---\nname: sample\ndescription: sample\n---\n', encoding='utf-8')
            (root / 'config.example.py').write_text(
                "sample_config = {'token': '', 'server': 'https://example.invalid'}\n",
                encoding='utf-8',
            )
            (root / 'settings.example.yaml').write_text(
                'api_' + 'token: ${API_TOKEN}\n'
                'confluence_' + 'token: <YOUR_TOKEN>\n'
                'auth_' + 'token: your_token_here\n',
                encoding='utf-8',
            )
            self.assertEqual(scan_package(root), [])

    def test_denied_paths_are_reported_without_opening_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blocked_config = root / 'config.py'
            blocked_config.write_text('must-not-be-read', encoding='utf-8')
            blocked_env = root / '.env'
            blocked_env.write_text('must-not-be-read', encoding='utf-8')
            blocked_token = root / 'access-token.txt'
            blocked_token.write_text('must-not-be-read', encoding='utf-8')
            blocked_log = root / 'logs'
            blocked_log.mkdir()
            (blocked_log / 'trace.txt').write_text('must-not-be-read', encoding='utf-8')
            original_open = Path.open
            original_scandir = package_check.os.scandir

            def guarded_open(path_obj, *args, **kwargs):
                if (path_obj in (blocked_config, blocked_env, blocked_token)
                        or blocked_log in path_obj.parents):
                    raise AssertionError(f'blocked content was opened: {path_obj}')
                return original_open(path_obj, *args, **kwargs)

            def guarded_scandir(path):
                if Path(path) == blocked_log:
                    raise AssertionError(f'blocked directory was entered: {path}')
                return original_scandir(path)

            with (patch.object(Path, 'open', guarded_open),
                  patch.object(package_check.os, 'scandir', guarded_scandir)):
                issues = scan_package(root)
            joined = '\n'.join(issues)
            self.assertIn('config.py', joined)
            self.assertIn('.env', joined)
            self.assertIn('access-token.txt', joined)
            self.assertIn('logs', joined)

    def test_token_filename_and_real_secret_assignment_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'access-token.txt').write_text('must-not-be-read', encoding='utf-8')
            sensitive_line = 'api' + "_key = 'live-value-not-a-placeholder'\n"
            (root / 'settings.py').write_text(sensitive_line, encoding='utf-8')
            bare_sensitive_line = 'to' + 'ken: live-value-not-a-placeholder\n'
            (root / 'settings.yaml').write_text(bare_sensitive_line, encoding='utf-8')
            issues = '\n'.join(scan_package(root))
            self.assertIn('access-token.txt', issues)
            self.assertEqual(issues.count('疑似敏感值'), 2)

    def test_prefixed_token_keys_and_known_token_literals_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assignments = '\n'.join((
                'api_' + 'token: opaque-api-value',
                'auth_' + 'token=opaque-auth-value',
                'confluence_' + 'token = opaque-confluence-value',
                'token_suffix = opaque-suffix-value',
            ))
            (root / 'settings.yaml').write_text(assignments, encoding='utf-8')
            known = 'sk-' + ('A' * 24)
            (root / 'README.md').write_text(
                'accidental credential: ' + known + '\n', encoding='utf-8')
            issues = '\n'.join(scan_package(root))
            self.assertGreaterEqual(issues.count('疑似敏感值'), 5)

    def test_reparse_point_is_rejected_before_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            class FakeEntry:
                name = 'linked-directory'
                path = str(root / name)

                @staticmethod
                def is_symlink():
                    return False

                @staticmethod
                def stat(follow_symlinks=False):
                    del follow_symlinks
                    return type('FakeStat', (), {
                        'st_file_attributes': package_check.REPARSE_ATTRIBUTE,
                    })()

                @staticmethod
                def is_dir(follow_symlinks=False):
                    del follow_symlinks
                    return False

                @staticmethod
                def is_file(follow_symlinks=False):
                    del follow_symlinks
                    return False

            with patch.object(package_check.os, 'scandir', return_value=[FakeEntry()]):
                issues = '\n'.join(scan_package(root))
            self.assertIn('reparse point', issues)

    def test_cli_exit_codes_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'SKILL.md').write_text('safe\n', encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(package_main(['--root', str(root)]), 0)
            (root / 'config.py').write_text('must-not-be-read', encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(package_main(['--root', str(root)]), 1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(package_main(['--root', str(root / 'missing')]), 2)


class MergeHardBreakTests(unittest.TestCase):
    def test_indented_formula_tag_hard_break_is_byte_preserved(self):
        source = '前段\n\n    \\tag{1}  \n后续段落\n'
        merged = merge_markdown_paragraphs(source)
        self.assertIn('    \\tag{1}  \n', merged)
        self.assertNotIn('    \\tag{1} 后续段落', merged)

    def test_formula_hard_break_preserves_crlf_and_mixed_eol_exactly(self):
        samples = (
            '前段\r\n\r\n    \\tag{1}  \r\n后续段落\r\n',
            '前段\n\n    \\tag{2}  \r\n后续段落\r\n',
        )
        for source in samples:
            with self.subTest(source=repr(source)):
                self.assertEqual(merge_markdown_paragraphs(source), source)

    def test_formula_hard_break_cli_preserves_utf8_file_bytes(self):
        source = '前段\r\n\r\n    \\tag{3}  \r\n后续段落\r\n'.encode('utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'formula.md'
            path.write_bytes(source)
            with (patch.object(merge_module.sys, 'argv', ['merge_paragraphs.py', str(path)]),
                  contextlib.redirect_stdout(io.StringIO())):
                merge_module.main()
            self.assertEqual(path.read_bytes(), source)


class OutputNameTests(unittest.TestCase):
    def test_windows_reserved_name_is_never_returned(self):
        names = (
            'CON', 'con', 'CON.txt', 'CON .txt', 'NUL .log',
            'COM1 .txt', 'COM9.', 'LPT1', 'LPT9 .md', 'aux.',
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, name in enumerate(names):
                with self.subTest(name=name):
                    cleaned = web2md.sanitize_filename(name)
                    self.assertNotRegex(
                        cleaned.upper(),
                        r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',
                    )
                    parent = root / str(index)
                    parent.mkdir()
                    (parent / cleaned).mkdir()

    def test_collision_uses_stable_url_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / 'Topic'
            existing.mkdir()
            (existing / 'Topic.md').write_text(
                '> 原文链接: [https://example.test/old](https://example.test/old)\n',
                encoding='utf-8',
            )
            first = web2md.resolve_output_name(root, 'Topic', 'https://example.test/new')
            second = web2md.resolve_output_name(root, 'Topic', 'https://example.test/new')
            self.assertEqual(first, second)
            self.assertRegex(first, r'^Topic-[0-9a-f]{8}$')

    def test_existing_output_for_same_url_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / 'Topic'
            existing.mkdir()
            source = 'https://example.test/topic'
            (existing / 'Topic.md').write_text(
                f'# Topic\n\n> 原文链接: [{source}]({source})\n',
                encoding='utf-8',
            )
            self.assertEqual(web2md.resolve_output_name(root, 'Topic', source), 'Topic')

    def test_output_name_respects_path_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ('nested-' + 'x' * 90)
            name = web2md.resolve_output_name(
                root,
                'Very long title ' * 30,
                'https://example.test/docs/long',
                path_limit=240,
            )
            longest = root / name / f'{name}.assets' / ('x' * 75 + '.jpeg')
            self.assertLessEqual(len(str(longest.resolve())), 240)


class RenderedNavigationTests(unittest.TestCase):
    def test_snapshot_identity_preserves_query(self):
        rendered = BeautifulSoup('<html><body>snapshot</body></html>', 'html.parser')
        valid, reason = web2md._snapshot_matches_page(
            rendered,
            'https://docs.test/page?id=one',
            'https://docs.test/page?id=two',
        )
        self.assertFalse(valid)
        self.assertIn('不一致', reason)

    def test_navigation_scope_keeps_stable_version_prefix(self):
        cases = (
            'https://docs.test/v1',
            'https://docs.test/v1/',
            'https://docs.test/v1/index.html',
            'https://docs.test/v1/topic.html',
            'https://docs.test/docs/v1/topic',
        )
        for page_url in cases:
            with self.subTest(page_url=page_url):
                self.assertTrue(web2md._navigation_scope(
                    'https://docs.test/v1/child.html'
                    if '/docs/' not in page_url else
                    'https://docs.test/docs/v1/child.html',
                    page_url,
                ))
                self.assertFalse(web2md._navigation_scope(
                    'https://docs.test/v2/child.html'
                    if '/docs/' not in page_url else
                    'https://docs.test/docs/v2/child.html',
                    page_url,
                ))

    def test_missing_static_navigation_without_snapshot_requires_review(self):
        static = BeautifulSoup('<html><body><h1>Parent</h1></body></html>', 'html.parser')
        result = web2md.collect_navigation(
            static,
            'https://docs.test/v1/parent.html',
        )
        self.assertEqual(result['source'], 'static')
        self.assertEqual(result['children'], [])
        self.assertTrue(result['review_required'])

    def test_recognized_leaf_without_snapshot_does_not_require_review(self):
        static = BeautifulSoup(
            '<meta name="generator" content="Sphinx 8.0">'
            '<nav><ul class="current"><li class="toctree-l1 current">'
            '<a href="#">Leaf Page</a></li></ul></nav>',
            'html.parser',
        )
        result = web2md.collect_navigation(
            static,
            'https://docs.test/v1/leaf.html',
        )
        self.assertEqual(result['structure'], 'sphinx')
        self.assertEqual(result['children'], [])
        self.assertFalse(result['review_required'])

    def test_rendered_dom_is_used_only_when_static_navigation_is_empty(self):
        static = BeautifulSoup('<html><body><h1>Parent</h1></body></html>', 'html.parser')
        rendered = '''
        <ul><li><a href="/v1/parent.html">Parent</a><ul>
          <li><a href="/v1/child.html">Child</a><ul>
            <li><a href="/v1/grand.html">Grand</a><ul>
              <li><a href="/v1/too-deep.html">Too deep</a></li>
            </ul></li>
          </ul></li>
          <li><a href="https://outside.test/v1/out.html">Outside</a></li>
          <li><a href="/v2/switch.html">Other version</a></li>
        </ul></li></ul>
        '''
        result = web2md.collect_navigation(
            static,
            'https://docs.test/v1/parent.html',
            rendered_html=rendered,
            rendered_url='https://docs.test/v1/parent.html',
        )
        self.assertEqual(result['source'], 'rendered')
        self.assertEqual([item['title'] for item in result['children']], ['Child'])
        self.assertEqual(
            [item['title'] for item in result['children'][0]['children']],
            ['Grand'],
        )

    def test_static_navigation_wins_over_rendered_dom(self):
        static = BeautifulSoup(
            '<ul><li><a href="/v1/parent.html">Parent</a><ul>'
            '<li><a href="/v1/static.html">Static</a></li>'
            '</ul></li></ul>',
            'html.parser',
        )
        rendered = (
            '<ul><li><a href="/v1/parent.html">Parent</a><ul>'
            '<li><a href="/v1/rendered.html">Rendered</a></li>'
            '</ul></li></ul>'
        )
        result = web2md.collect_navigation(
            static,
            'https://docs.test/v1/parent.html',
            rendered_html=rendered,
            rendered_url='https://docs.test/v1/parent.html',
        )
        self.assertEqual(result['source'], 'static')
        self.assertEqual([item['title'] for item in result['children']], ['Static'])

    def test_unverified_snapshot_is_not_used(self):
        static = BeautifulSoup('<html><body><h1>Parent</h1></body></html>', 'html.parser')
        rendered = (
            '<ul><li><a href="/v1/parent.html">Parent</a><ul>'
            '<li><a href="/v1/rendered.html">Rendered</a></li>'
            '</ul></li></ul>'
        )
        result = web2md.collect_navigation(
            static,
            'https://docs.test/v1/parent.html',
            rendered_html=rendered,
            rendered_url='https://docs.test/v2/other.html',
        )
        self.assertEqual(result['source'], 'static')
        self.assertEqual(result['children'], [])
        self.assertTrue(result['review_required'])
        self.assertIn('REVIEW', '\n'.join(result['notes']))


class CrossNodeTexTests(unittest.TestCase):
    def test_comment_crossing_is_left_unchanged_for_review(self):
        soup = BeautifulSoup(
            r'<p>Before \(<span>x</span><!--keep-me--><span>+ y\)</span> after</p>',
            'html.parser',
        )
        before = str(soup)
        inline, display, review = web2md.convert_plain_tex_delimiters(soup)
        self.assertEqual((inline, display, review), (0, 0, 1))
        self.assertEqual(str(soup), before)
        self.assertEqual(soup.find(string=lambda value: isinstance(value, Comment)), 'keep-me')

    def test_formula_like_comment_is_not_converted(self):
        soup = BeautifulSoup(r'<p>safe</p><!-- \(not-body\) -->', 'html.parser')
        before = str(soup)
        self.assertEqual(web2md.convert_plain_tex_delimiters(soup), (0, 0, 0))
        self.assertEqual(str(soup), before)

    def test_safe_cross_span_pair_is_converted(self):
        soup = BeautifulSoup(
            r'<p>Before \(<span>x + </span><span>y</span>\) after</p>',
            'html.parser',
        )
        inline, display, review = web2md.convert_plain_tex_delimiters(soup)
        self.assertEqual((inline, display, review), (1, 0, 0))
        self.assertIn('$x + y$', soup.get_text())

    def test_protected_subtree_keeps_cross_pair_for_review(self):
        soup = BeautifulSoup(
            r'<p>\(<span>x</span><code>do-not-touch</code><span>y</span>\)</p>',
            'html.parser',
        )
        inline, display, review = web2md.convert_plain_tex_delimiters(soup)
        self.assertEqual((inline, display), (0, 0))
        self.assertGreaterEqual(review, 1)
        self.assertIn(r'\(', soup.get_text())
        self.assertEqual(soup.code.get_text(), 'do-not-touch')

    def test_block_boundary_is_not_crossed(self):
        soup = BeautifulSoup(r'<p>\(x</p><p>y\)</p>', 'html.parser')
        inline, display, review = web2md.convert_plain_tex_delimiters(soup)
        self.assertEqual((inline, display), (0, 0))
        self.assertEqual(review, 1)
        self.assertIn(r'\(x', soup.get_text())

    def test_formatting_subtree_is_not_flattened(self):
        soup = BeautifulSoup(r'<p>\(<em>x</em> + y\)</p>', 'html.parser')
        inline, display, review = web2md.convert_plain_tex_delimiters(soup)
        self.assertEqual((inline, display), (0, 0))
        self.assertEqual(review, 1)
        self.assertEqual(soup.em.get_text(), 'x')


if __name__ == '__main__':
    unittest.main()
