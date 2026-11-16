"""固定授权修订稿经真实CLI导入，合成文件只留临时目录。"""
import copy
import io
import contextlib
import unittest
import zipfile
from unittest.mock import patch

from tools import core, documents
from tools.cli import main
from evals import test_software_prepare as prepare_tests


class SoftwareImportTests(prepare_tests.SoftwarePrepareCliTests):
    def revision_args(self, text='First complete manual revision', suffix='md'):
        if suffix == 'md':
            raw = ('# Synthetic manual\n\n' + text + '\n').encode('utf-8')
        else:
            raw = documents.make_software_docx([[{'id': 'Detail', 'kind': 'paragraph', 'text': text}]],
                title='合成计数器', version='1.0', kind='manual')
        name = 'manual.' + suffix
        (self.root / name).write_bytes(raw)
        sha = core.sha256_bytes(raw)
        self.request['manual_revision'] = {'path': name, 'sha256': sha,
                                          'format': 'markdown' if suffix == 'md' else 'docx'}
        self.authorization['files'].append({'path': name, 'sha256': sha})
        self.save_request()
        args = self.args()
        args[0] = 'import-software-manual'
        return args

    def test_markdown_cli_new_binding_and_source_unchanged(self):
        args = self.revision_args()
        self.assertEqual(self.invoke(args)[0], 0)
        before = self.result()['artifacts']
        before_bytes = (self.root / 'prepared.json').read_bytes()
        self.request['previous_preparation'] = before
        self.authorization['output'] = 'revision-two.json'
        self.authorization['files'].pop()
        args = self.revision_args('Second complete manual revision')
        self.assertEqual(self.invoke(args)[0], 0)
        after = core.strict_json_loads((self.root / 'revision-two.json').read_text(encoding='utf-8'))['artifacts']
        self.assertEqual((self.root / 'prepared.json').read_bytes(), before_bytes)
        self.assertEqual(before['source']['binding'], after['source']['binding'])
        self.assertNotEqual(before['manual']['binding'], after['manual']['binding'])
        self.assertEqual(after['supersedes'], before['binding'])
        self.assertTrue(after['manual']['revision']['difference']['changed'])
        self.assertTrue(all(row['status'] == 'needs_review' for row in after['manual']['blocks']))

    def test_repeated_same_revision_reuses_snapshot(self):
        self.assertEqual(self.invoke(self.revision_args())[0], 0)
        before = self.result()['artifacts']
        self.request['previous_preparation'] = before
        self.authorization['output'] = 'repeat.json'
        self.save_request()
        args = self.args()
        args[0] = 'import-software-manual'
        self.assertEqual(self.invoke(args)[0], 0)
        after = core.strict_json_loads((self.root / 'repeat.json').read_text(encoding='utf-8'))['artifacts']
        self.assertEqual(before, after)

    def test_supported_docx_revision_and_strict_old_document_review(self):
        args = self.revision_args('Edited Word paragraph', 'docx')
        self.assertEqual(self.invoke(args)[0], 0)
        manual = self.result()['artifacts']['manual']
        self.assertIn('Edited Word paragraph', manual['markdown'])
        self.assertEqual(manual['revision']['parser_metadata']['format'], 'docx')
        old = [[{'id': 'Detail', 'kind': 'paragraph', 'text': 'Original Word paragraph'}]]
        with self.assertRaises(core.ContractError):
            documents.inspect_software_docx((self.root / 'manual.docx').read_bytes(), old,
                title='合成计数器', version='1.0', kind='manual')

    def test_denied_preflight_reads_only_control(self):
        self.authorization['context']['permissions'][0]['decision'] = 'deny'
        args = self.revision_args()
        from pathlib import Path
        original, opened = Path.open, []
        def track(path, *a, **kw):
            opened.append(path.name)
            return original(path, *a, **kw)
        with patch.object(Path, 'open', track):
            self.assert_rejected(args)
        self.assertEqual(opened, ['authorization.json'])

    def test_sensitive_full_revision_refuses_without_output(self):
        args = self.revision_args('Synthetic forbidden sentinel 4821')
        self.request['delivery'] = {'sensitive_literals': ['Synthetic forbidden sentinel 4821']}
        self.save_request()
        args = self.args()
        args[0] = 'import-software-manual'
        self.assert_rejected(args)

    def test_unapproved_image_or_unsupported_docx_preserves_input(self):
        args = self.revision_args('![Synthetic](unapproved.png)')
        raw = (self.root / 'manual.md').read_bytes()
        self.assert_rejected(args)
        self.assertEqual((self.root / 'manual.md').read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
