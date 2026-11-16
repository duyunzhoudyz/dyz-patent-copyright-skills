"""正文块、真实报告来源和本地外发候选的合成回归，不执行转换或发送。"""
import copy
import json
import unittest
from unittest.mock import patch

from evals import test_software_delivery as existing
from tools import core, software
from tools import software_delivery as delivery


class SoftwareDeliveryUpgradeTests(unittest.TestCase):
    setUp = existing.SoftwareDeliveryTests.setUp
    refresh = existing.SoftwareDeliveryTests.refresh
    build = existing.SoftwareDeliveryTests.build
    gui = existing.SoftwareDeliveryTests.gui
    def authored(self, blocks):
        manual = {key: value for key, value in self.preparation['manual'].items() if key != 'binding'}
        manual['blocks'] = blocks
        self.preparation = software._seal({key: value for key, value in self.preparation.items()
                                          if key != 'binding'} | {'manual': software._seal(manual)})

    def block(self, identity='intro', **values):
        return {'id': identity, 'kind': 'paragraph', 'text': 'Unique authored material.',
                'evidence_ids': ['synthetic-source'], 'status': 'confirmed', **values}

    def approval(self, names=('body/source.docx',)):
        template = self.context['permissions'][0]
        context = copy.deepcopy(self.context)
        context['purpose'] = 'deposit'
        context['permissions'] = [{**template, 'action': action, 'purpose': 'deposit',
                                    'recipient': recipient}
                                   for action, recipient in [('local_read', 'local_tool'),
                                                             ('local_write', 'local_tool'),
                                                             ('copy', 'synthetic-reviewer')]]
        files = []
        for name in names:
            raw = (core.canonical_bytes(delivery._export_fields(self.preparation)) + b'\n'
                   if name == 'application-fields.json' else (self.root / 'pack' / name).read_bytes())
            files.append({'path': name, 'sha256': core.sha256_bytes(raw)})
        return context, {'files': files, 'recipient': 'synthetic-reviewer', 'purpose': 'deposit',
                         'channel': 'local_handoff', 'evidence_id': 'synthetic-file-approval'}

    def export(self, names=('body/source.docx',), **changes):
        context, approval = self.approval(names)
        approval.update(changes)
        return delivery.export_package(self.root, self.preparation, self.options, 'pack', 'export',
                                       context=context, approval=approval)

    def test_authored_blocks_order_text_and_stable_source_map(self):
        self.authored([self.block('中文正文', text='Distinct authored text not present in facts.'),
                       self.block('steps', kind='list', text='One\nTwo', operation_id='count'),
                       self.block('table', kind='table', text='A | B')])
        self.build()
        text = (self.root / 'pack/body/manual.txt').read_text(encoding='utf-8')
        self.assertIn('Distinct authored text not present in facts.', text)
        self.assertNotIn(self.fixture['manual_input']['facts'][0]['text'], text)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_text(encoding='utf-8'))
        rows = mapping['manual']['blocks']
        self.assertEqual([row['source_block_id'] for row in rows], ['中文正文', 'steps', 'steps', 'table'])
        self.assertEqual(rows[1]['source_kind'], 'list')
        self.assertEqual(rows[1]['evidence_ids'], ['synthetic-source'])
        self.assertTrue(delivery.verify(self.root, self.preparation, self.options, 'pack',
                                       context=self.context)['generated_docx_equal'])

    def test_real_prepare_consumes_blocks_without_legacy_fact_reconstruction(self):
        self.payload['manual_input'] = {**self.fixture['manual_input'], 'blocks': [
            self.block('intro', text='Original authored paragraph through prepare.')],
            'document_metadata': {'name': self.fixture['scope_input']['metadata']['name'], 'version': '1.0'}}
        self.preparation = software.prepare(self.payload)['artifacts']
        self.build()
        self.assertIn('Original authored paragraph through prepare.',
                      (self.root / 'pack/body/manual.txt').read_text(encoding='utf-8'))

    def test_operation_images_are_inserted_once_and_explicit_slot_selects_id(self):
        raw = self.gui()
        self.authored([self.block('step1', operation_id='count'),
                       self.block('step2', operation_id='count'),
                       self.block('figure', kind='image', image_id='shot1', operation_id='count')])
        plans, _, _ = delivery._plan(self.root, self.preparation, self.options, self.context)
        figures = [block for page in plans['manual'] for block in page if block['kind'] == 'image']
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0]['png'], raw)
        self.assertEqual(figures[0]['source_block_id'], 'figure')

    def test_short_authored_text_and_image_fit_same_planned_page(self):
        self.gui()
        self.authored([self.block(f'line_{index}', text=f'Synthetic line {index}')
                       for index in range(9)] + [
            self.block('figure', kind='image', image_id='shot1', operation_id='count')])
        plans, _, _ = delivery._plan(self.root, self.preparation, self.options, self.context)
        self.assertEqual(len(plans['manual']), 1)
        self.assertEqual(len(plans['manual'][0]), 10)
        self.assertEqual(plans['manual'][0][-1]['kind'], 'image')

    def test_implicit_operation_image_and_unmatched_image(self):
        self.gui()
        self.authored([self.block('step1', operation_id='count'), self.block('step2', operation_id='count')])
        pages = delivery._manual_pages(self.preparation, delivery._screenshots(
            self.root, self.preparation, self.options, self.context)[0])
        self.assertEqual(sum(block['kind'] == 'image' for page in pages for block in page), 1)
        self.authored([self.block()])
        with self.assertRaisesRegex(core.ContractError, 'manual_screenshot_unmatched'):
            self.build()
        self.assertFalse((self.root / 'pack').exists())

    def test_authored_placeholder_and_import_provenance_scanned(self):
        self.authored([self.block(text='[待确认：PRIVATE_QUESTION]')])
        report = self.build()['text_review']
        self.assertEqual(report['status'], 'needs_review')
        self.assertNotIn('PRIVATE_QUESTION', json.dumps(report))
        self.assertTrue(any(location[:2] == ['manual', 'blocks'] for location in report['locations'].values()))
        preparation = copy.deepcopy(self.preparation)
        preparation['manual']['revision'] = {'provenance': '[TO CONFIRM: imported evidence]'}
        self.assertTrue(delivery._text_review(preparation, self.options)['issues'])

    def test_secret_inside_authored_body_rejected_before_output(self):
        self.authored([self.block(text='AUTHORED_SECRET')])
        self.options['sensitive_literals'] = ['AUTHORED_SECRET']
        with self.assertRaisesRegex(core.ContractError, 'delivery_sensitive_literal_found'):
            self.build()
        self.assertFalse((self.root / 'pack').exists())

    def test_code_snapshot_is_real_and_shared_code_change_invalidates(self):
        result = self.build()
        snapshot = {row['file']: row['sha256'] for row in result['code_snapshot']}
        self.assertEqual(snapshot['software_delivery.py'], core.sha256_bytes(
            delivery.Path(delivery.__file__).read_bytes()))
        self.assertEqual(result['page_sources']['manual']['basis'], 'estimated')
        changed = copy.deepcopy(result['code_snapshot'])
        changed[0]['sha256'] = '0' * 64
        with patch.object(delivery, '_code_snapshot', return_value=changed):
            with self.assertRaisesRegex(core.ContractError, 'delivery_code_changed'):
                delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)

    def test_snapshot_and_page_source_forgery_rejected(self):
        manifest = self.build()
        manifest['page_sources']['source']['basis'] = 'human_confirmed'
        (self.root / 'pack/manifest.json').write_bytes(core.canonical_bytes(manifest))
        with self.assertRaisesRegex(core.ContractError, 'delivery_page_sources_changed'):
            delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)

    def test_legacy_v11_report_read_without_invented_code_attestation(self):
        manifest = self.build()
        manifest['generator_version'] = '1.1'
        for key in ('code_snapshot', 'input_snapshot', 'page_sources', 'tool_versions'):
            manifest.pop(key)
        (self.root / 'pack/manifest.json').write_bytes(core.canonical_bytes(manifest))
        result = delivery.verify(self.root, self.preparation, self.options, 'pack', context=self.context)
        self.assertEqual(result['provenance'], 'legacy_report_without_code_snapshot')
        self.assertNotIn('code_snapshot', result)

    def test_export_allows_internal_partial_without_claiming_professional_pass(self):
        self.build()
        report = self.export(('body/source.docx', 'body/manual.txt', 'application-fields.json'))
        names = {path.relative_to(self.root / 'export').as_posix()
                 for path in (self.root / 'export').rglob('*') if path.is_file()}
        self.assertEqual(names, {'body/source.docx', 'body/manual.txt', 'application-fields.json'})
        fields = (self.root / 'export/application-fields.json').read_text(encoding='utf-8')
        for forbidden in ('evidence_id', 'actor', 'sha256', 'counter.py', 'synthetic-source'):
            self.assertNotIn(forbidden, fields)
        self.assertEqual(report['professional_review'], 'not_performed')
        self.assertEqual(report['external_action'], 'not_performed')
        self.assertEqual(report['page_sources']['source']['basis'], 'estimated')

    def test_export_blocks_internal_members_even_with_exact_approval(self):
        self.build()
        for name in ('body/worksheet.txt', 'internal/preparation.json', 'manifest.json'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(core.ContractError, 'export_file_not_whitelisted'):
                    self.export((name,))
                self.assertFalse((self.root / 'export').exists())

    def test_export_blocks_stale_approval_and_missing_copy_permission(self):
        self.build()
        context, approval = self.approval()
        approval['files'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(core.ContractError, 'export_file_approval_changed'):
            delivery.export_package(self.root, self.preparation, self.options, 'pack', 'export',
                                    context=context, approval=approval)
        context['permissions'] = [row for row in context['permissions'] if row['action'] != 'copy']
        with self.assertRaisesRegex(core.ContractError, 'permission_not_proven'):
            delivery.export_package(self.root, self.preparation, self.options, 'pack', 'export',
                                    context=context, approval=approval)
        self.assertFalse((self.root / 'export').exists())

    def test_export_blocks_unconfirmed_body_placeholder_and_unknown_rights(self):
        self.authored([self.block(status='needs_review')])
        self.build()
        with self.assertRaisesRegex(core.ContractError, 'export_manual_confirmation_pending'):
            self.export(('body/manual.txt',))

    def test_prepare_changed_body_keeps_old_confirmation_out_of_export(self):
        self.payload['manual_input']['blocks'] = [self.block('intro', text='Approved original')]
        before = software.prepare(self.payload)['artifacts']
        self.payload['previous_preparation'] = before
        self.payload['manual_input']['blocks'][0]['text'] = 'Unreviewed replacement'
        self.preparation = software.prepare(self.payload)['artifacts']
        self.build()
        self.assertEqual(self.preparation['manual']['blocks'][0]['status'], 'needs_review')
        with self.assertRaisesRegex(core.ContractError, 'export_manual_confirmation_pending'):
            self.export(('body/manual.txt',))
        self.assertFalse((self.root / 'export').exists())

    def test_export_placeholder_and_missing_body_evidence_block_before_copy(self):
        self.authored([self.block(text='[TO CONFIRM: missing evidence]')])
        self.build()
        with self.assertRaisesRegex(core.ContractError, 'export_text_review_unresolved'):
            self.export(('body/manual.txt',))
        self.assertFalse((self.root / 'export').exists())

    def test_source_export_does_not_require_unrelated_manual_confirmation(self):
        self.authored([self.block(status='needs_review')])
        self.build()
        result = self.export()
        self.assertEqual(result['status'], 'needs_review')
        self.assertTrue((self.root / 'export/body/source.docx').is_file())

    def test_export_first_verifies_old_package_members(self):
        self.build()
        (self.root / 'pack/internal/extra.txt').write_text('unapproved internal', encoding='utf-8')
        with self.assertRaisesRegex(core.ContractError, 'delivery_members_changed'):
            self.export()
        self.assertFalse((self.root / 'export').exists())

    def test_export_clean_fields_excludes_pending_candidate_and_all_provenance(self):
        self.payload['field_candidates'] = [{'field': 'name', 'value': 'UNCONFIRMED CANDIDATE',
            'status': 'inferred', 'sources': [{'path': 'counter.py',
                'sha256': core.sha256_bytes((self.root / 'counter.py').read_bytes()), 'locator': 'line 1'}]}]
        self.preparation = software.prepare(self.payload)['artifacts']
        fields = delivery._export_fields(self.preparation)
        self.assertNotIn('name', fields)
        self.assertNotIn('sources', fields)
        for value in ('actor', 'sha256', 'evidence_id', 'UNCONFIRMED CANDIDATE'):
            self.assertNotIn(value, json.dumps(fields))

    def test_tool_version_probe_is_local_version_only(self):
        tool = self.root / 'pdftotext.exe'
        tool.write_bytes(b'synthetic')
        with patch.object(delivery.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'Synthetic PDF tool 1.0'
            run.return_value.stderr = b''
            report = delivery._tool_version(tool)
        self.assertEqual(run.call_args.args[0], [str(tool), '--version'])
        self.assertEqual(report['status'], 'recorded')

    def test_export_public_purpose_cannot_borrow_deposit_permission(self):
        self.build()
        context, approval = self.approval()
        context['purpose'] = approval['purpose'] = 'public'
        for row in context['permissions']:
            row['purpose'] = 'public'
        with self.assertRaisesRegex(core.ContractError, 'export_rights_not_authorized'):
            delivery.export_package(self.root, self.preparation, self.options, 'pack', 'export',
                                    context=context, approval=approval)
        self.assertFalse((self.root / 'export').exists())


if __name__ == '__main__':
    unittest.main()
