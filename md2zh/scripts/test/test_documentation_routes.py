import unittest
from pathlib import Path


class SkillDocumentationRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill_root = Path(__file__).resolve().parents[2]
        cls.skill_text = (cls.skill_root / 'SKILL.md').read_text(encoding='utf-8')

    def test_entry_stays_compact_and_routes_references_directly(self):
        self.assertLessEqual(len(self.skill_text.splitlines()), 250)
        references = (
            'translation-rules.md',
            'translation-quality.md',
            'configuration-guide.md',
            'ambiguous-content-workflow.md',
            'tree-translation-workflow.md',
            'maintenance-rules.md',
            'script-development-rules.md',
        )
        for name in references:
            with self.subTest(reference=name):
                self.assertTrue((self.skill_root / 'references' / name).is_file())
                self.assertIn(f'](references/{name})', self.skill_text)

        standard = self.skill_root.parent / 'SKILL_MODIFICATION_STANDARD.md'
        self.assertTrue(standard.is_file())
        self.assertIn('](../SKILL_MODIFICATION_STANDARD.md)', self.skill_text)
        self.assertIn('](KNOWN_ISSUES.md)', self.skill_text)
        self.assertIn('](OPTIMIZATION_SUMMARY.md)', self.skill_text)

        for route_label in ('| 排查或修复 bug |', '| 优化、重构或扩展 |'):
            route = next(
                (line for line in self.skill_text.splitlines() if line.startswith(route_label)),
                '',
            )
            with self.subTest(route=route_label):
                self.assertIn('](../SKILL_MODIFICATION_STANDARD.md)', route)
                self.assertIn('](references/maintenance-rules.md)', route)
                self.assertIn('](references/script-development-rules.md)', route)

    def test_routed_references_declare_complete_read_conditions(self):
        references = (
            'translation-rules.md',
            'translation-quality.md',
            'configuration-guide.md',
            'ambiguous-content-workflow.md',
            'tree-translation-workflow.md',
            'maintenance-rules.md',
            'script-development-rules.md',
        )
        for name in references:
            with self.subTest(reference=name):
                text = (self.skill_root / 'references' / name).read_text(encoding='utf-8')
                self.assertIn('## 强制读取条件', text)
                self.assertIn('必须', text)
                self.assertIn('完整读取', text)
                if len(text.splitlines()) > 100:
                    self.assertIn('## 目录', text)

    def test_entry_keeps_core_translation_redlines(self):
        required = (
            '仅显式调用',
            '配置同步失败必须停止',
            '源 Markdown 与源 `.assets` 始终只读',
            '不直接编辑完整 Markdown',
            'SEG 行原样且有序',
            'PROTECT 标记恰好一次',
            '译文只用 UTF-8 文件写入',
            '验证器不能代替语义审阅',
            '单块失败只修该块',
            '四阶段完成标记与产物哈希',
            '未经用户明确要求',
            '完整 `scripts/test/selftest.py`',
        )
        for redline in required:
            with self.subTest(redline=redline):
                self.assertIn(redline, self.skill_text)

    def test_read_receipt_fields_remain_visible(self):
        for field in ('任务类型：', '已完整读取：', '输入范围：', '输出边界：'):
            with self.subTest(field=field):
                self.assertIn(field, self.skill_text)

    def test_implicit_invocation_remains_disabled(self):
        openai_yaml = (self.skill_root / 'agents' / 'openai.yaml').read_text(encoding='utf-8')
        self.assertRegex(openai_yaml, r'(?m)^\s*allow_implicit_invocation:\s*false\s*$')


if __name__ == '__main__':
    unittest.main()
