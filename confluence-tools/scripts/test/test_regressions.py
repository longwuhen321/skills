import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import collect_paginated_results
from config_parser import ConfigParseError, parse_config_text
from dependency_check import missing_dependencies
from md_export import ConfluenceExporter
from md_import import (LOOKUP_ERROR, LOOKUP_FOUND, LOOKUP_NOT_FOUND,
                       MarkdownImporter)
from math_upgrade import ConfluenceMathUpdater
from package_check import inspect_package


MOCK_CFG = {
    'common_config': {
        'confluence_url': 'http://test.invalid:8090',
        'confluence_token': 'fixture-token',
    },
    'import_config': {
        'space': 'TEST', 'math_align': 'left', 'tree_import': True,
        'fix_hierarchy': 'confirm', 'toc_enabled': True,
        'toc_min_headings': 4, 'preflight_review': False,
    },
    'upgrade_config': {
        'math_align': 'left', 'auto_update': True, 'ai_verify': False,
        'recursive': True, 'max_depth': 0,
    },
    'toc_upgrade_config': {
        'target_macro': 'easy_heading', 'default_page': '', 'space': '',
        'recursive': False, 'auto_update': True, 'ai_verify': False,
        'macro_parameters': {
            'titleExpandClickable': 'true',
            'hiddenEditedFlag': 'true',
            'navigationExpandOption': 'expand-all-by-default',
            'useNavigationHiddenMode': 'true',
        },
    },
    'export_config': {
        'output_dir': 'confluence_export', 'recursive': True, 'space': '',
    },
    'debug_config': {'max_size_mb': 50, 'keep_recent': 20},
}


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text='', headers=None,
                 chunks=None):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text
        self.headers = headers or {}
        self.ok = status_code < 400
        self._chunks = chunks or []

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f'HTTP {self.status_code}: {self.text}')
            err.response = self
            raise err

    def iter_content(self, chunk_size=8192):
        yield from self._chunks


class TestSafeConfigAndPackaging(unittest.TestCase):
    def test_config_parser_accepts_only_literal_group_dicts(self):
        parsed = parse_config_text(
            "common_config = {'url': 'x', 'enabled': False}\n"
            "import_config = {'count': 2}\n")
        self.assertEqual(parsed['common_config']['enabled'], False)
        self.assertEqual(parsed['import_config']['count'], 2)

    def test_config_parser_rejects_import_call_and_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'executed.txt'
            payload = (
                "import pathlib\n"
                f"pathlib.Path({str(marker)!r}).write_text('bad')\n"
                "common_config = {}\n"
            )
            with self.assertRaises(ConfigParseError):
                parse_config_text(payload)
            self.assertFalse(marker.exists())

    def test_package_check_rejects_banned_name_before_reading_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scripts').mkdir()
            (root / 'scripts' / 'config.py').write_text(
                "confluence_token = '" + 'must-not-be-read' + "'\n",
                encoding='utf-8')
            with patch.object(Path, 'read_text', side_effect=AssertionError('read')):
                forbidden, suspicious = inspect_package(root)
            self.assertTrue(any('scripts/config.py' in p for p in forbidden))
            self.assertEqual(suspicious, [])

    def test_package_check_rejects_banned_name_before_stat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            entry = mock.Mock()
            entry.path = str(root / 'config.py')
            entry.name = 'config.py'
            with patch('package_check.os.scandir', return_value=[entry]):
                forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, ['config.py'])
            self.assertEqual(suspicious, [])
            entry.stat.assert_not_called()
            entry.is_symlink.assert_not_called()

    def test_package_check_scans_allowed_text_for_suspected_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'SKILL.md').write_text(
                'Authorization: Bearer ' + ('a' * 32) + '\n',
                encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertTrue(any('SKILL.md' in p for p in suspicious))

    def test_package_check_detects_unquoted_token_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'settings.yaml').write_text(
                'tok' + 'en: ' + ('a' * 32) + '\n', encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertTrue(any('settings.yaml' in p for p in suspicious))

    def test_package_check_detects_token_inside_single_line_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'settings.py').write_text(
                'common_config = {"confluence_' + 'token": "'
                + ('a' * 32) + '"}\n',
                encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertTrue(any('settings.py' in p for p in suspicious))

    def test_package_check_rejects_reparse_point_without_entering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            entry = mock.Mock()
            entry.path = str(root / 'junction')
            entry.name = 'junction'
            entry.is_symlink.return_value = False
            entry.stat.return_value = mock.Mock(st_file_attributes=0x400)
            with patch('package_check.os.scandir', return_value=[entry]):
                forbidden, suspicious = inspect_package(root)
            self.assertTrue(any('reparse point/junction' in p for p in forbidden))
            self.assertEqual(suspicious, [])
            entry.is_dir.assert_not_called()

    def test_package_check_rejects_env_and_common_caches_before_reading_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.env').write_text('api_token=' + ('a' * 32), encoding='utf-8')
            (root / '.pytest_cache').mkdir()
            (root / 'README.md').write_text('safe', encoding='utf-8')
            with patch.object(Path, 'read_text', side_effect=AssertionError('read')):
                forbidden, suspicious = inspect_package(root)
            self.assertIn('.env', forbidden)
            self.assertIn('.pytest_cache/', forbidden)
            self.assertEqual(suspicious, [])

    def test_package_check_detects_common_token_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'settings.yaml').write_text(
                '\n'.join(
                    f'{key}: {key}-' + ('a' * 32)
                    for key in ('api_token', 'auth_token', 'access_token')),
                encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertEqual(len(suspicious), 3)

    def test_package_check_python_scanner_ignores_regex_and_built_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'scanner_test.py').write_text(
                "TOKEN_RE = re.compile(r'api_token\\s*=')\n"
                "FORMAT_RE = re.compile(r'sk-proj-[A-Za-z0-9_-]{20,}')\n"
                "fixture = 'api_token=' + ('a' * 32)\n"
                "token_fixture = 'sk-proj-' + ('a' * 32)\n",
                encoding='utf-8')
            self.assertEqual(inspect_package(root), ([], []))

    def test_package_check_ignores_atlassian_upload_control_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'client.py').write_text(
                "headers = {'X-Atlassian-Token': 'no-check'}\n",
                encoding='utf-8')
            self.assertEqual(inspect_package(root), ([], []))
            (root / 'client.py').write_text(
                "headers = {'X-Atlassian-Token': '" + ('a' * 32) + "'}\n",
                encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertEqual(len(suspicious), 1)

    def test_package_check_rejects_env_variants_cache_names_and_sensitive_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('.env.local', '.env.production',
                         'credentials.bin', 'api-token.txt'):
                (root / name).write_text('must-not-be-read', encoding='utf-8')
            (root / 'cache').mkdir()
            (root / 'foo_cache').mkdir()
            (root / 'README.md').write_text('safe', encoding='utf-8')
            with patch.object(Path, 'read_text', side_effect=AssertionError('read')):
                forbidden, suspicious = inspect_package(root)
            self.assertEqual(suspicious, [])
            for expected in (
                    '.env.local', '.env.production', 'cache/', 'foo_cache/',
                    'credentials.bin', 'api-token.txt'):
                self.assertIn(expected, forbidden)

    def test_package_check_shared_sensitive_keys_cover_yaml_and_python_dicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keys = ('jira_token', 'token_backup', 'my_api_key')
            (root / 'settings.yaml').write_text(
                '\n'.join(f'{key}: {key}-' + ('a' * 32) for key in keys),
                encoding='utf-8')
            (root / 'settings.py').write_text(
                'settings = {'
                + ', '.join(repr(key) + ': ' + repr(key + '-' + ('b' * 32))
                            for key in keys)
                + '}\n',
                encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertEqual(len(suspicious), 6)

    def test_package_check_detects_standalone_known_token_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jwt = ('eyJ' + ('a' * 20) + '.' + ('b' * 20)
                   + '.' + ('c' * 20))
            (root / 'README.md').write_text(
                'OpenAI: sk-proj-' + ('a' * 32) + '\n'
                'GitHub: ghp_' + ('b' * 36) + '\n'
                'JWT: ' + jwt + '\n',
                encoding='utf-8')
            forbidden, suspicious = inspect_package(root)
            self.assertEqual(forbidden, [])
            self.assertEqual(len(suspicious), 3)

    def test_dependency_check_reports_all_four_missing_in_stable_order(self):
        with patch('dependency_check.importlib.import_module',
                   side_effect=ImportError('missing')) as import_module:
            self.assertEqual(
                missing_dependencies(),
                ['requests', 'markdown2', 'beautifulsoup4', 'markdownify'])
        self.assertEqual(
            [call.args[0] for call in import_module.call_args_list],
            ['requests', 'markdown2', 'bs4', 'markdownify'])

    def test_dependency_check_treats_broken_import_as_missing(self):
        with patch('dependency_check.importlib.import_module', side_effect=[
                object(), ImportError('broken markdown2'), object(),
                OSError('broken extension')]):
            self.assertEqual(
                missing_dependencies(), ['markdown2', 'markdownify'])


class TestCommonPagination(unittest.TestCase):
    def test_public_paginator_follows_next_link(self):
        session = mock.Mock()
        session.request.side_effect = [
            FakeResponse(json_data={
                'results': [{'id': '1'}],
                '_links': {'next': '/rest/api/content?start=1&limit=1'},
            }),
            FakeResponse(json_data={'results': [{'id': '2'}], '_links': {}}),
        ]
        rows = collect_paginated_results(
            session, 'http://test.invalid/rest/api/content',
            base_url='http://test.invalid', params={'limit': 1})
        self.assertEqual([r['id'] for r in rows], ['1', '2'])
        self.assertEqual(session.request.call_count, 2)

    def test_public_paginator_propagates_http_error(self):
        session = mock.Mock()
        session.request.return_value = FakeResponse(503, text='offline')
        with patch('common.time.sleep'), self.assertRaises(requests.HTTPError):
            collect_paginated_results(
                session, 'http://test.invalid/rest/api/content',
                base_url='http://test.invalid', params={'limit': 1})


class ImporterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stack = [
            patch('md_import.SKILL_ROOT', self.tmp.name),
            patch('md_import.load_config', return_value=MOCK_CFG),
        ]
        for p in self.stack:
            p.start()
        self.importer = MarkdownImporter(space_key='TEST')
        self.importer.session = mock.Mock()
        p = patch.object(self.importer, '_save_debug_file')
        p.start()
        self.stack.append(p)

    def tearDown(self):
        for p in reversed(self.stack):
            p.stop()
        self.tmp.cleanup()


class TestImportLookupAndConflict(ImporterCase):
    def test_lookup_requires_disambiguation_for_duplicate_titles(self):
        self.importer._page_records = [
            {'id': '1', 'title': 'Same', 'version': 2, 'parent_id': '10'},
            {'id': '2', 'title': 'Same', 'version': 3, 'parent_id': '20'},
        ]
        self.assertEqual(self.importer._find_page_by_title('Same')[0], LOOKUP_ERROR)
        self.assertEqual(
            self.importer._find_page_by_title('Same', parent_id='20'),
            (LOOKUP_FOUND, '2', 3))
        self.assertEqual(
            self.importer._find_page_by_title('Other')[0], LOOKUP_NOT_FOUND)

    def test_lookup_page_id_is_exact_selector(self):
        self.importer._page_records = [
            {'id': '1', 'title': 'Same', 'version': 2, 'parent_id': '10'},
            {'id': '2', 'title': 'Same', 'version': 3, 'parent_id': '20'},
        ]
        self.assertEqual(
            self.importer._find_page_by_title('Ignored', page_id='2'),
            (LOOKUP_FOUND, '2', 3))

    def test_lookup_collection_failure_is_error_not_not_found(self):
        self.importer._page_records = None
        with patch('md_import.collect_space_page_records',
                   side_effect=requests.ConnectionError('offline')):
            self.assertEqual(
                self.importer._find_page_by_title('Anything')[0], LOOKUP_ERROR)

    def test_update_409_does_not_overwrite_without_force(self):
        self.importer.force = False
        self.importer.session.request.return_value = FakeResponse(409)
        with patch.object(self.importer, '_fetch_latest_version', return_value=9):
            result = self.importer._update_page('1', 'T', '<p>x</p>', 3)
        self.assertEqual(result, (None, None))
        self.assertEqual(self.importer.session.request.call_count, 1)

    def test_update_409_force_retries_from_latest_version(self):
        self.importer.force = True
        self.importer.session.request.side_effect = [
            FakeResponse(409), FakeResponse(200, {'id': '1'}),
        ]
        with patch.object(self.importer, '_fetch_latest_version', return_value=9):
            result = self.importer._update_page('1', 'T', '<p>x</p>', 3)
        self.assertEqual(result, ('1', 10))
        payload = self.importer.session.request.call_args_list[-1].kwargs['json']
        self.assertEqual(payload['version']['number'], 10)

    def test_toc_marker_round_trips_to_single_macro(self):
        storage = self.importer._convert_md_to_storage('[toc]\n\n## One\n')
        self.assertEqual(storage.count('ac:name="toc"'), 1)

    def test_single_import_attachment_failure_returns_false(self):
        with tempfile.NamedTemporaryFile(
                'w', suffix='.md', delete=False, encoding='utf-8') as handle:
            handle.write('![missing](missing.png)')
            md_path = handle.name
        try:
            def fail_image(content, _path, _page_id):
                self.importer.failed_images.append('missing.png')
                return content

            with patch.object(self.importer, '_convert_md_to_storage',
                              return_value='<p>image</p>'), \
                    patch.object(self.importer, '_find_page_by_title',
                                 return_value=(LOOKUP_NOT_FOUND, None, None)), \
                    patch.object(self.importer, '_create_page',
                                 return_value=('1', 1)), \
                    patch.object(self.importer, '_convert_md_links',
                                 side_effect=fail_image):
                self.assertFalse(self.importer.import_markdown(md_path))
        finally:
            os.unlink(md_path)


class TestTreePlanAndResume(ImporterCase):
    def test_tree_plan_uses_one_index_and_carries_id_version(self):
        node = {
            'name': 'Parent', 'md_path': 'parent.md',
            'children': [{'name': 'Child', 'md_path': 'child.md', 'children': []}],
        }
        records = [
            {'id': '1', 'title': 'Parent', 'version': 4, 'parent_id': None},
            {'id': '2', 'title': 'Child', 'version': 7, 'parent_id': '1'},
        ]
        self.importer._page_records = records
        plan = self.importer._build_plan(node)
        self.assertEqual((plan['page_id'], plan['version']), ('1', 4))
        self.assertEqual(
            (plan['children'][0]['page_id'], plan['children'][0]['version']),
            ('2', 7))

    def test_resume_skips_completed_parent_and_continues_child(self):
        with tempfile.TemporaryDirectory() as docs:
            child_md = Path(docs) / 'child.md'
            child_md.write_text('child', encoding='utf-8')
            plan = {
                'title': 'Parent', 'md_path': 'parent.md', 'status': 'update',
                'page_id': '1', 'version': 4, 'parent_title': None,
                'target_parent_id': None, 'depth': 0, 'completed': True,
                'children': [{
                    'title': 'Child', 'md_path': str(child_md), 'status': 'new',
                    'page_id': None, 'version': None, 'parent_title': 'Parent',
                    'target_parent_id': '1', 'depth': 1, 'completed': False,
                    'children': [],
                }],
            }
            with patch.object(self.importer, '_create_page', return_value=('2', 1)) as create, \
                    patch.object(self.importer, '_convert_md_to_storage', return_value='<p>x</p>'), \
                    patch.object(self.importer, '_convert_md_links', side_effect=lambda x, *_: x):
                result = self.importer._execute_plan(plan, checkpoint=lambda: None)
            create.assert_called_once()
            self.assertEqual(result['children'][0]['page_id'], '2')

    def test_tree_plan_never_assigns_one_page_id_to_two_nodes(self):
        self.importer._page_records = [
            {'id': '9', 'title': 'Shared', 'version': 2, 'parent_id': 'old'},
        ]
        tree = {
            'name': 'root', 'md_path': None,
            'children': [
                {'name': 'A', 'md_path': 'a.md', 'children': [
                    {'name': 'Shared', 'md_path': 'shared-a.md', 'children': []},
                ]},
                {'name': 'B', 'md_path': 'b.md', 'children': [
                    {'name': 'Shared', 'md_path': 'shared-b.md', 'children': []},
                ]},
            ],
        }
        plan = self.importer._build_plan(tree)
        first = plan['children'][0]['children'][0]
        second = plan['children'][1]['children'][0]
        self.assertEqual(first['page_id'], '9')
        self.assertEqual(second['status'], 'error')
        self.assertIsNone(second['page_id'])
        self.assertTrue(self.importer._plan_has_error(plan))

    def test_resume_rejects_checkpoint_with_duplicate_page_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / 'tree_plan.json'
            node = {
                'title': 'A', 'md_path': 'a.md', 'status': 'update',
                'page_id': '9', 'version': 2, 'parent_title': None,
                'target_parent_id': None, 'depth': 0, 'completed': False,
                'children': [{
                    'title': 'B', 'md_path': 'b.md', 'status': 'update',
                    'page_id': '9', 'version': 2, 'parent_title': 'A',
                    'target_parent_id': '9', 'depth': 1, 'completed': False,
                    'children': [],
                }],
            }
            checkpoint.write_text(json.dumps({
                'format_version': 1,
                'space_key': 'TEST',
                'root_dir': tmp,
                'plan': node,
            }), encoding='utf-8')
            with patch.object(self.importer, '_execute_plan') as execute:
                ok = self.importer.import_tree(resume_file=str(checkpoint), yes=True)
            self.assertFalse(ok)
            execute.assert_not_called()

    def test_tree_attachment_failure_keeps_node_resumable(self):
        with tempfile.TemporaryDirectory() as tmp:
            md_path = Path(tmp) / 'page.md'
            md_path.write_text('![missing](missing.png)', encoding='utf-8')
            plan = {
                'title': 'Page', 'md_path': str(md_path), 'status': 'new',
                'page_id': None, 'version': None, 'parent_title': None,
                'target_parent_id': None, 'depth': 0, 'completed': False,
                'children': [],
            }

            def fail_image(content, _path, _page_id):
                self.importer.failed_images.append('missing.png')
                return content + '<ac:image />'

            checkpoint = mock.Mock()
            with patch.object(self.importer, '_convert_md_to_storage',
                              return_value='<p>image</p>'), \
                    patch.object(self.importer, '_create_page',
                                 return_value=('7', 1)), \
                    patch.object(self.importer, '_update_page',
                                 return_value=('7', 2)), \
                    patch.object(self.importer, '_convert_md_links',
                                 side_effect=fail_image):
                result = self.importer._execute_plan(
                    plan, checkpoint=checkpoint)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(plan['page_id'], '7')
            self.assertEqual(plan['version'], 2)
            self.assertFalse(plan['completed'])
            self.assertEqual(checkpoint.call_count, 2)


class UpdaterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch('math_upgrade.SKILL_ROOT', self.tmp.name),
            patch('math_upgrade.load_config', return_value=MOCK_CFG),
        ]
        for p in self.patches:
            p.start()
        self.updater = ConfluenceMathUpdater(space_key='TEST')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class TestMathSafety(UpdaterCase):
    def test_center_removes_existing_alignment(self):
        self.updater.math_align = 'center'
        html = (
            '<ac:structured-macro ac:schema-version="1" ac:name="mathblock">'
            '<ac:parameter ac:name="alignment">left</ac:parameter>'
            '<ac:plain-text-body><![CDATA[x]]></ac:plain-text-body>'
            '</ac:structured-macro>')
        updated, count = self.updater._apply_alignment(html)
        self.assertEqual(count, 1)
        self.assertNotIn('ac:name="alignment"', updated)

    def test_verify_rejects_one_residual_and_reports_position(self):
        self.updater.allow_math_residuals = False
        passed, report = self.updater.verify(
            '<p>$x$</p>', '<p>line one</p>\n<p>$x$</p>',
            {'inline': 0, 'block': 0, 'latex': 0})
        self.assertFalse(passed)
        self.assertRegex(report, r'inline@2:\d+')

    def test_verify_allows_residual_only_when_explicit(self):
        self.updater.allow_math_residuals = True
        passed, _ = self.updater.verify(
            '<p>$x$</p>', '<p>$x$</p>',
            {'inline': 0, 'block': 0, 'latex': 0})
        self.assertTrue(passed)

    def test_confirm_rejects_stale_source_version(self):
        folder = Path(self.tmp.name) / 'confirm'
        folder.mkdir()
        after = '<p>converted</p>'
        source = '<p>source</p>'
        (folder / 'after.html').write_text(after, encoding='utf-8')
        (folder / 'info.txt').write_text(
            '页面 ID: 1\n版本: 3\n源内容 SHA256: '
            + hashlib.sha256(source.encode()).hexdigest() + '\n', encoding='utf-8')
        current = {'page_id': '1', 'title': 'T', 'version': 4,
                   'space_key': 'TEST', 'storage': source}
        with patch.object(self.updater, 'fetch_page', return_value=current), \
                patch.object(self.updater, 'update_page') as update:
            ok = self.updater.confirm_update(str(folder))
        self.assertFalse(ok)
        update.assert_not_called()

    def test_confirm_rejects_stale_source_content(self):
        folder = Path(self.tmp.name) / 'confirm-content-change'
        folder.mkdir()
        after = '<p>converted</p>'
        source = '<p>source</p>'
        (folder / 'after.html').write_text(after, encoding='utf-8')
        (folder / 'info.txt').write_text(
            '页面 ID: 1\n版本: 3\n源内容 SHA256: '
            + hashlib.sha256(source.encode()).hexdigest() + '\n', encoding='utf-8')
        current = {'page_id': '1', 'title': 'T', 'version': 3,
                   'space_key': 'TEST', 'storage': '<p>changed</p>'}
        with patch.object(self.updater, 'fetch_page', return_value=current) as fetch, \
                patch.object(self.updater, 'update_page') as update:
            ok = self.updater.confirm_update(str(folder))
        self.assertFalse(ok)
        fetch.assert_called_once_with('1')
        update.assert_not_called()

    def test_ai_verify_still_requires_mechanical_zero_residual_gate(self):
        self.updater.ai_verify = True
        page = {'page_id': '1', 'title': 'T', 'version': 3,
                'space_key': 'TEST', 'storage': '<p>$x$</p>'}
        stats = {'inline': 1, 'block': 0, 'latex': 0,
                 'old_macro_upgraded': 0}
        with patch.object(self.updater, 'fetch_page', return_value=page), \
                patch.object(self.updater, 'convert_math',
                             return_value=('<p>$x$</p>', stats)), \
                patch.object(self.updater, 'save_debug'), \
                patch.object(self.updater, 'update_page') as update:
            ok, message = self.updater.process_single('1')
        self.assertFalse(ok)
        self.assertIn('验证未通过', message)
        update.assert_not_called()

    def test_batch_failure_returns_false(self):
        with patch.object(self.updater, 'process_single',
                          side_effect=[(True, 'ok'), (False, 'bad')]):
            self.assertFalse(self.updater._run_batch([('1', 'A', 0), ('2', 'B', 0)]))


class ExporterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch('md_export.SKILL_ROOT', self.tmp.name),
            patch('md_export.load_config', return_value=MOCK_CFG),
        ]
        for p in self.patches:
            p.start()
        self.exporter = ConfluenceExporter(output_dir=self.tmp.name)
        self.exporter.session = mock.Mock()
        p = patch.object(self.exporter, 'fetch_attachments', return_value=[])
        p.start()
        self.patches.append(p)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class TestExportSafety(ExporterCase):
    def test_space_export_disables_recursive_reentry_and_aggregates_failure(self):
        with patch('md_export.collect_space_pages', return_value=[
                ('1', 'A', 1), ('2', 'B', 1)]), \
                patch.object(self.exporter, 'export_page',
                             side_effect=[Path('ok.md'), RuntimeError('bad')]) as export:
            ok = self.exporter.export_space('TEST')
        self.assertFalse(ok)
        self.assertEqual(export.call_args_list[0].kwargs['recursive'], False)
        self.assertEqual(export.call_args_list[1].kwargs['recursive'], False)

    def test_code_payload_blank_lines_survive_normalization(self):
        storage = (
            '<ac:structured-macro ac:name="code">'
            '<ac:parameter ac:name="language">python</ac:parameter>'
            '<ac:plain-text-body><![CDATA[first\n\n\nsecond]]></ac:plain-text-body>'
            '</ac:structured-macro>')
        text = self.exporter._convert_storage_to_markdown(
            storage, Path(self.tmp.name) / 'page', '1')
        self.assertIn('first\n\n\nsecond', text)

    def test_export_directory_contains_page_id(self):
        page = {'page_id': '42', 'title': 'Same', 'version': 1,
                'space_key': 'TEST', 'storage': '<p>x</p>', 'raw': {}}
        with patch.object(self.exporter, 'fetch_page', return_value=page), \
                patch.object(self.exporter, '_save_storage_debug'), \
                patch.object(self.exporter, '_convert_storage_to_markdown', return_value='x\n'):
            path = self.exporter.export_page('42', recursive=False)
        self.assertEqual(path.parent.name, '42_Same')
        self.assertEqual(path.name, 'Same.md')

    def test_windows_reserved_page_title_is_prefixed(self):
        page = {'page_id': '5', 'title': 'CON', 'version': 1,
                'space_key': 'TEST', 'storage': '<p>x</p>',
                'raw': {'version': {'when': ''}}}
        with patch.object(self.exporter, 'fetch_page', return_value=page), \
                patch.object(self.exporter, '_save_storage_debug'):
            path = self.exporter.export_page('5', recursive=False)
        self.assertEqual(path.name, '_CON.md')
        self.assertEqual(path.parent.name, '5__CON')

    def test_attachment_filename_is_basename_and_contained(self):
        assets = Path(self.tmp.name) / 'safe.assets'
        assets.mkdir()
        self.exporter.session.request.return_value = FakeResponse(chunks=[b'x'])
        saved = self.exporter._download_attachment({
            'id': '7', 'title': '../../outside.txt',
            '_links': {'download': '/download/7'},
        }, assets)
        self.assertEqual(saved, '7_outside.txt')
        self.assertTrue((assets / saved).is_file())
        self.assertFalse((Path(self.tmp.name) / 'outside.txt').exists())

    def test_unknown_macro_keeps_body_and_standalone_ri_url(self):
        storage = (
            '<ac:structured-macro ac:name="custom--macro">'
            '<ac:rich-text-body><p>Keep me</p>'
            '<ri:url ri:value="https://example.invalid/doc" />'
            '</ac:rich-text-body></ac:structured-macro>')
        text = self.exporter._convert_storage_to_markdown(
            storage, Path(self.tmp.name) / 'page', '1')
        self.assertIn('Keep me', text)
        self.assertIn('https://example.invalid/doc', text)
        self.assertIn('未处理的宏: custom-macro', text)
        self.assertIn('原始 Confluence XHTML', text)
        self.assertIn('&lt;ac:structured-macro', text)
        self.assertIn('custom&#45;&#45;macro', text)

    def test_external_image_url_is_preserved(self):
        storage = (
            '<ac:image><ac:parameter ac:name="alt">Remote</ac:parameter>'
            '<ri:url ri:value="https://example.invalid/image.png" />'
            '</ac:image>')
        text = self.exporter._convert_storage_to_markdown(
            storage, Path(self.tmp.name) / 'page', '1')
        self.assertIn('![Remote](https://example.invalid/image.png)', text)
        self.assertEqual(self.exporter.stats['failed_images'], 0)

    def test_attachment_download_failure_makes_space_export_fail(self):
        with patch('md_export.collect_space_pages',
                   return_value=[('1', 'A', 1)]), \
                patch.object(self.exporter, 'export_page',
                             return_value=Path('a.md')):
            self.exporter.stats['failed_images'] = 1
            self.assertFalse(self.exporter.export_space('TEST'))


class TestCliSurface(unittest.TestCase):
    def test_all_page_entry_help_commands_use_utf8_and_exit_zero(self):
        scripts_dir = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        for script_name in ('md_import.py', 'md_export.py', 'math_upgrade.py',
                            'toc_upgrade.py'):
            result = subprocess.run(
                [sys.executable, '-X', 'utf8', str(scripts_dir / script_name),
                 '--help'],
                capture_output=True, text=True, encoding='utf-8', env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('usage:', result.stdout.lower())


class TestSkillDocumentationRoutes(unittest.TestCase):
    SKILL_ROOT = Path(__file__).resolve().parents[2]

    def test_skill_entry_is_compact_and_keeps_mandatory_route_gate(self):
        text = (self.SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
        line_count = len(text.splitlines())
        self.assertGreaterEqual(line_count, 180)
        self.assertLessEqual(line_count, 240)
        self.assertIn('在调用页面脚本、修改文件或连接服务器之前', text)
        self.assertIn('完整读取路由表列出的全部文件', text)
        self.assertIn('读取后先向用户公开回执', text)

    def test_every_direct_route_exists_and_requires_complete_read(self):
        expected = (
            'configuration-guide.md',
            'md-import-workflow.md',
            'md-import-preflight-rules.md',
            'math-upgrade-workflow.md',
            'toc-upgrade-workflow.md',
            'md-export-workflow.md',
            'maintenance-rules.md',
            'script-development-rules.md',
        )
        skill_text = (self.SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
        for name in expected:
            with self.subTest(name=name):
                reference = self.SKILL_ROOT / 'references' / name
                self.assertTrue(reference.is_file(), f'缺少路由文件: {name}')
                self.assertIn(name, skill_text, f'SKILL.md 未直接路由: {name}')
        for name in expected:
            with self.subTest(mandatory=name):
                text = (self.SKILL_ROOT / 'references' / name).read_text(
                    encoding='utf-8')
                self.assertIn('强制读取条件', text)
                self.assertIn('必须', text)
                self.assertIn('完整读取', text)

    def test_core_safety_redlines_remain_in_skill_entry(self):
        text = (self.SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
        for redline in (
                '范围不猜测', '写入前验证', '批量不误报', '并发不覆盖',
                '凭据不泄漏', 'XHTML 不破坏', '真实测试最小化',
                '权限不扩大', '临时产物清理'):
            with self.subTest(redline=redline):
                self.assertIn(redline, text)

    def test_parent_modification_standard_route_exists(self):
        standard = self.SKILL_ROOT.parent / 'SKILL_MODIFICATION_STANDARD.md'
        self.assertTrue(standard.is_file())
        skill_text = (self.SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('../SKILL_MODIFICATION_STANDARD.md', skill_text)


if __name__ == '__main__':
    unittest.main()
