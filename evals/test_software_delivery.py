"""软件成品链的合成边界测试；不是权利、官方规则或真实截图验收。"""
import copy
import io
import json
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from tools import core, software
from tools import software_delivery as delivery

ROOT = Path(__file__).resolve().parents[1]


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00' + b'\xff\x00\x00' * 2 + b'\x00' + b'\x00\xff\x00' * 2))
            + chunk(b'IEND', b''))


class SoftwareDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyz-delivery-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = json.loads((ROOT / 'evals/fixtures/software/synthetic.json').read_text(encoding='utf-8'))
        self.context = copy.deepcopy(self.fixture['context'])
        self.context['permissions'].append({**self.context['permissions'][0], 'action': 'local_write'})
        self.source = self.fixture['source']
        self.options = {'selection': 'all', 'screenshots': [], 'sensitive_literals': []}
        self.refresh()

    def refresh(self):
        (self.root / 'counter.py').write_text(self.source, encoding='utf-8')
        self.payload = {'context': self.context, 'authorized_root': str(self.root),
                        'scope_input': self.fixture['scope_input'], 'rights': self.fixture['rights'],
                        'files': [{'id': 'f1', 'path': 'counter.py', 'component_id': 'cli',
                                   'kind': 'source', 'include': True}],
                        'inventory_complete': True,
                        'pagination': {'lines_per_page': 50, 'wrap_columns': 78,
                                       'selection': 'all', 'basis': 'synthetic-internal-layout'},
                        'manual_input': self.fixture['manual_input']}
        self.preparation = software.prepare(self.payload)['artifacts']

    def build(self, **kwargs):
        return delivery.build(self.root, self.preparation, self.options, 'pack',
                              context=self.context, **kwargs)

    def test_local_pack_contains_three_editable_documents_and_internal_mapping(self):
        result = self.build()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pdf'], 'not_generated')
        self.assertEqual(result['professional_review'], 'not_performed')
        for name in ('source', 'manual', 'worksheet'):
            self.assertTrue((self.root / f'pack/body/{name}.docx').is_file())
            self.assertTrue((self.root / f'pack/body/{name}.txt').is_file())
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_text(encoding='utf-8'))
        self.assertEqual(mapping['source']['source_lines'], 3)
        self.assertEqual((self.root / 'counter.py').read_text(encoding='utf-8'), self.source)
        verified = delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)
        self.assertTrue(verified['file_hashes_equal'])

    def test_source_wrap_preserves_all_characters_and_maps_columns(self):
        rows = [{'file_id': 'f', 'source_line': 1, 'text': '\t中文<&>https://x//path' * 10}]
        pages, mapping = delivery.source_pages(rows)
        self.assertEqual(''.join(b['text'] for page in pages for b in page), rows[0]['text'])
        self.assertEqual(mapping['rows'][0]['column_start'], 1)
        self.assertEqual(mapping['rows'][-1]['column_end'], len(rows[0]['text']))
        self.assertTrue(all(r['display_width'] <= 78 for r in mapping['rows']))

    def test_page_thresholds_and_tail_preserve_original_page_members(self):
        for count in (0, 49, 50, 51, 1499, 1500, 2999, 3000, 3001, 3050):
            with self.subTest(count=count):
                rows = [{'file_id': 'f', 'source_line': n + 1, 'text': f'line_{n + 1}'} for n in range(count)]
                pages, mapping = delivery.source_pages(rows)
                self.assertEqual(sum(map(len, pages)), count)
                self.assertEqual(mapping['source_lines'], count)
                selected = delivery.select_pages(pages, 'head_tail')
                indexes = list(range(len(pages))) if len(pages) <= 60 else list(range(30)) + list(range(len(pages) - 30, len(pages)))
                self.assertEqual(selected, indexes)
                self.assertEqual(len(indexes), len(set(indexes)))
                if count:
                    self.assertEqual(pages[indexes[-1]][-1]['text'], f'line_{count}')

    def test_secrets_in_source_metadata_or_caption_block_before_output(self):
        for location in ('source', 'metadata', 'manual'):
            with self.subTest(location=location):
                preparation = copy.deepcopy(self.preparation)
                if location == 'source':
                    preparation['source']['selected_lines'][0]['text'] = 'SYNTHETIC_SECRET'
                    preparation['source'] = software._seal({k: v for k, v in preparation['source'].items() if k != 'binding'})
                elif location == 'metadata':
                    preparation['scope']['metadata']['name'] = 'SYNTHETIC_SECRET'
                    preparation['scope'] = software._seal({k: v for k, v in preparation['scope'].items() if k != 'binding'})
                else:
                    preparation['manual']['facts'][0]['text'] = 'SYNTHETIC_SECRET'
                    preparation['manual'] = software._seal({k: v for k, v in preparation['manual'].items() if k != 'binding'})
                preparation = software._seal({k: v for k, v in preparation.items() if k != 'binding'})
                with self.assertRaises(core.ContractError):
                    delivery.build(self.root, preparation, {**self.options, 'sensitive_literals': ['SYNTHETIC_SECRET']},
                                   'pack', context=self.context)
                self.assertFalse((self.root / 'pack').exists())

    def test_no_write_permission_blocks_before_image_read_or_output(self):
        self.context['permissions'] = [p for p in self.context['permissions'] if p['action'] != 'local_write']
        with self.assertRaises(core.ContractError):
            self.build()
        self.assertFalse((self.root / 'pack').exists())

    def test_incomplete_or_preselected_source_cannot_be_claimed_as_full_mother(self):
        self.payload['pagination'].update(selection='head_tail', pages_each_end=1)
        prepared = software.prepare(self.payload)['artifacts']
        with self.assertRaisesRegex(core.ContractError, 'delivery_full_source_required'):
            delivery.build(self.root, prepared, self.options, 'pack', context=self.context)

    def test_missing_manual_keeps_source_and_worksheet_but_records_gap(self):
        del self.payload['manual_input']
        prepared = software.prepare(self.payload)['artifacts']
        manifest = delivery.build(self.root, prepared, self.options, 'pack', context=self.context)
        self.assertIn('manual_missing', manifest['issues'])
        self.assertFalse((self.root / 'pack/body/manual.docx').exists())
        self.assertTrue((self.root / 'pack/body/source.docx').exists())

    def test_no_overwrite_and_extra_member_rejected(self):
        self.build()
        with self.assertRaisesRegex(core.ContractError, 'output_exists'):
            self.build()
        (self.root / 'pack/body/unexpected.txt').write_text('synthetic', encoding='utf-8')
        with self.assertRaisesRegex(core.ContractError, 'delivery_members_changed'):
            delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)

    def test_modified_docx_is_rejected_even_if_manifest_hash_is_reforged(self):
        self.build()
        path = self.root / 'pack/body/source.docx'
        data = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts['word/extra.xml'] = b'<synthetic/>'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, raw in parts.items():
                archive.writestr(name, raw)
        manifest_path = self.root / 'pack/manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for row in manifest['files']:
            if row['path'] == 'body/source.docx':
                row.update(bytes=path.stat().st_size, sha256=core.sha256_bytes(path.read_bytes()))
        manifest_path.write_bytes(core.canonical_bytes(manifest))
        with self.assertRaises(core.ContractError):
            delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)

    def test_converter_failure_is_recorded_without_success_pdf(self):
        tool = self.root / 'soffice.exe'
        tool.write_bytes(b'synthetic-test-executable')
        with patch('tools.software_delivery.subprocess.run', side_effect=OSError('SYNTHETIC_PRIVATE_PATH')):
            manifest = self.build(pdf_tool=str(tool))
        self.assertEqual(manifest['status'], 'partial')
        self.assertIn('pdf_conversion_failed', manifest['issues'])
        self.assertNotIn('SYNTHETIC_PRIVATE_PATH', json.dumps(manifest))
        self.assertTrue((self.root / 'pack/manifest.json').exists())
        self.assertEqual(manifest['pdf'], 'failed')

    def gui(self):
        self.fixture['manual_input']['mode'] = 'GUI'
        self.fixture['manual_input']['runtime_evidence'] = [
            {'id': 'shot1', 'version': '1.0', 'evidence_id': 'synthetic-capture', 'kind': 'screenshot'}]
        self.refresh()
        raw = png()
        (self.root / 'screen.png').write_bytes(raw)
        self.options['screenshots'] = [{'id': 'shot1', 'path': 'screen.png', 'sha256': core.sha256_bytes(raw),
            'version': '1.0', 'operation_id': 'count', 'build_binding': delivery.build_binding(self.preparation),
            'capture_evidence': 'synthetic-not-real-screenshot', 'local_use_evidence': 'synthetic-use',
            'visible_state': 'Synthetic two-color test image'}]
        return raw

    def test_screenshot_embeds_original_bytes_at_its_operation(self):
        raw = self.gui()
        manifest = self.build()
        self.assertIn('screenshot_visual_review_missing', manifest['issues'])
        with zipfile.ZipFile(self.root / 'pack/body/manual.docx') as archive:
            images = [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]
            self.assertEqual(images, [raw])
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_text(encoding='utf-8'))
        self.assertEqual(mapping['screenshots'][0]['operation_id'], 'count')

    def test_same_filename_changed_bytes_version_operation_and_build_reject(self):
        self.gui()
        original = copy.deepcopy(self.options)
        for field, value in (('sha256', '0' * 64), ('version', '2.0'), ('operation_id', 'missing'), ('build_binding', '0' * 64)):
            with self.subTest(field=field):
                self.options = copy.deepcopy(original)
                self.options['screenshots'][0][field] = value
                with self.assertRaises(core.ContractError):
                    self.build()
                self.assertFalse((self.root / 'pack').exists())

    def test_worksheet_contains_unapplied_candidate_sources_and_locator(self):
        candidate = {
            'field': 'name', 'value': 'Synthetic candidate name', 'status': 'inferred',
            'sources': [{'path': 'counter.py',
                         'sha256': core.sha256_bytes((self.root / 'counter.py').read_bytes()),
                         'locator': 'line 1; synthetic source location'}],
        }
        self.payload['field_candidates'] = [candidate]
        self.preparation = software.prepare(self.payload)['artifacts']
        self.build()
        text = (self.root / 'pack/body/worksheet.txt').read_text(encoding='utf-8')
        compact = text.replace('\n', '')
        for value in (candidate['value'], 'counter.py', candidate['sources'][0]['sha256'],
                      candidate['sources'][0]['locator'], 'inferred', 'field_confirmation_required'):
            self.assertIn(value, compact)
        self.assertIn('独立确认：未提供', compact)
        self.assertNotEqual(self.preparation['form']['name'], candidate['value'])
        verified = delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)
        self.assertTrue(verified['generated_docx_equal'])

    def test_worksheet_contains_confirmation_actor_role_evidence_and_binding(self):
        candidate = {
            'field': 'name', 'value': 'Synthetic confirmed name', 'status': 'candidate',
            'sources': [{'path': 'counter.py',
                         'sha256': core.sha256_bytes((self.root / 'counter.py').read_bytes()),
                         'locator': 'line 1; confirmed synthetic location'}],
        }
        self.payload['field_candidates'] = [candidate]
        draft = software.prepare(self.payload)['artifacts']
        confirmation = {
            'candidate_digest': core.digest(candidate),
            'input_binding': draft['worksheet']['input_binding'], 'status': 'confirmed',
            'actor': 'Synthetic Reviewer', 'role': 'technical-owner',
            'evidence_id': 'synthetic-confirmation-record',
        }
        self.payload['confirmations'] = [confirmation]
        self.preparation = software.prepare(self.payload)['artifacts']
        self.build()
        compact = (self.root / 'pack/body/worksheet.txt').read_text(encoding='utf-8').replace('\n', '')
        for value in confirmation.values():
            self.assertIn(value, compact)
        self.assertIn(candidate['value'], compact)
        self.assertIn('已采纳到表单', compact)
        self.assertEqual(self.preparation['form']['name'], candidate['value'])

    def test_head_tail_never_slices_before_full_pdf_validation(self):
        self.options['selection'] = 'head_tail'
        manifest = self.build()
        self.assertEqual(manifest['selection_applied'], 'all_pending_physical_validation')
        self.assertIn('physical_selection_not_verified', manifest['issues'])


class SoftwareDeliveryCliTests(unittest.TestCase):
    def setUp(self):
        from evals.test_software_prepare import SoftwarePrepareCliTests
        self.case = SoftwarePrepareCliTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.authorization['output'] = 'materials'
        self.case.request['delivery'] = {'selection': 'all', 'screenshots': [], 'sensitive_literals': []}
        self.case.save_request()

    def test_actual_cli_builds_and_verifies_internal_documents(self):
        import subprocess
        import sys
        args = self.case.args()
        args[0] = 'build-software'
        process = subprocess.run([sys.executable, '-B', '-m', 'tools', *args], cwd=ROOT,
                                 capture_output=True, text=True, encoding='utf-8')
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (4, 'software_documents_partial\n', ''))
        self.assertTrue((self.case.root / 'materials/body/source.docx').is_file())
        code, out, err = self.case.invoke(args + ['--verify'])
        self.assertEqual(code, 4)
        self.assertEqual(err, '')

    def test_unauthorized_image_rejected_before_read(self):
        self.case.request['delivery']['screenshots'] = [{'path': 'PRIVATE.png', 'sha256': '0' * 64}]
        self.case.save_request()
        args = self.case.args()
        args[0] = 'build-software'
        original = Path.open
        def guarded(path, *values, **kwargs):
            self.assertNotEqual(path.name, 'PRIVATE.png')
            return original(path, *values, **kwargs)
        with patch.object(Path, 'open', guarded):
            code, out, err = self.case.invoke(args)
        self.assertEqual((code, out, err), (2, '', 'contract_rejected\n'))
        self.assertFalse((self.case.root / 'materials').exists())

    def test_internal_delivery_manifest_is_not_exportable(self):
        from tools.disclosure import inspect_bytes
        args = self.case.args()
        args[0] = 'build-software'
        self.case.invoke(args)
        raw = (self.case.root / 'materials/manifest.json').read_bytes()
        self.assertIn('internal_artifact_not_exportable', inspect_bytes('manifest.json', raw)['issues'])


if __name__ == '__main__':
    unittest.main()

