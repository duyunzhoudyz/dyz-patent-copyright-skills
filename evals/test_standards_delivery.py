"""标准五文书实物闭环；只用临时原创合成材料，不等同专业验收。"""
import copy
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET
from pathlib import Path
import tempfile
import unittest

from tools.core import ContractError, VersionLedger, digest, sha256_bytes
from tools import standards_delivery as delivery


SECTION_IDS = [
    'note-01-work-overview', 'note-02-background-purpose',
    'note-03-principles-basis', 'note-04-technical-content-basis',
    'note-05-comparison', 'note-06-legal-standard-relation',
    'note-07-major-divergence', 'note-08-nature-and-implementation',
    'note-09-comment-disposition', 'note-10-verification', 'note-11-open-items',
]


def task():
    old = dict(id='CL1', text='合成设备应记录结果。', strength='requirement',
               kind='normative', source='S1', conditions=[], exceptions=[],
               method_ids=['V1'], references=[])
    current = dict(old, text='合成设备应记录结果及错误状态。')
    profile = dict(id='internal-example', version='1', scope='internal',
                   required_sections=SECTION_IDS)
    sections = [dict(id=sid, heading=f'说明 {index}', body='本节仅说明原创合成工程示例。',
                     state='explicit', owner='synthetic-author', source=['S1'])
                for index, sid in enumerate(SECTION_IDS, 1)]
    sections[-1]['open_items'] = []
    return dict(contract_version=2, project_id='SYNTHETIC', version='v2',
                sensitivity='synthetic', delivery_stage='draft',
                adaptation=dict(organization='internal', standard_type='technical',
                                domain='synthetic', stage='draft'),
                evidence_ids=['S1'], baseline_clauses=[old], clauses=[current],
                collection_status='complete',
                comments=[dict(id='C1', clause_id='CL1', text='请记录错误状态。',
                               source='S1', participant_id='P1', version='v1')],
                comment_outcomes=[dict(comment_id='C1', outcome='accepted',
                    classification='technical', reason='合成检查需可观察错误状态。',
                    reason_source='S1', decision_status='confirmed',
                    decision_by='synthetic-reviewer', decision_source='S1',
                    major_change='no', impact=[], changes=[dict(operation='replace',
                        clause_id='CL1', proposed_text=current['text'])])],
                profile=profile, compilation_note=dict(standard_name='合成标准',
                    version='v2', clause_digest=digest([current]), profile_id=profile['id'],
                    profile_hash=digest(profile), sections=sections),
                verification_matrix=[dict(id='V1', clause_id='CL1', method='inspection',
                                          status='planned', source='S1')])


def stress_task():
    """两条长意见的12语义字段和跨页附录；全部为原创合成待决材料。"""
    payload = task()
    payload['profile']['rendering'] = 'dyz-standard-internal-v1'
    payload['comments'] = []
    payload['comment_outcomes'] = []
    for index in (1, 2):
        payload['comments'].append(dict(
            id=f'LONG-{index}', seq=index, clause_id='CL1', version='v1',
            origin=dict(organization=f'合成提出单位{index}', representative_scope=f'合成代表范围{index}'),
            text=f'意见原文{index}：' + ('仅在启动状态记录合成故障，维护模式作为明确例外。' * 45),
            source=f'SYNTHETIC-SOURCE-{index}#page-{index}', participant_id=f'P{index}'))
        payload['comment_outcomes'].append(dict(
            comment_id=f'LONG-{index}', outcome='partially_accepted', classification='technical',
            reason=f'处理理由{index}：需责任人提供执行记录，不推定实际完成。',
            reason_source=f'SYNTHETIC-REASON-{index}', decision_status='proposed',
            accepted_part=f'拟采纳部分{index}：补入合成故障记录要求。',
            rejected_part=f'未采纳部分{index}：未核实的技术参数。',
            rejected_reason=f'未采纳理由{index}：没有获准来源，保留未决跟进。',
            major_change='undetermined', impact=dict(verification=True, references=True,
                compilation_note=True, downstream_products=True),
            changes=[dict(operation='replace', clause_id='CL1', proposed_text=f'拟改条款{index}：应保存合成故障记录。')],
            unresolved_item=dict(question=f'未决跟进{index}：核实组织与技术依据。',
                owner=f'合成责任人{index}', blocks='submission', recovery='补入获准依据后逐项复核。'),
            owner=f'合成责任人{index}'))
    appendix = dict(id='A.1', text='附录A.1原创合成记录规则：' + ('应逐项保存条件、例外和结果，不推断未取得的事实。' * 75),
                    strength='requirement', kind='normative', source='SYNTHETIC-APPENDIX',
                    conditions=['合成记录模式'], exceptions=['维护模式除外'], method_ids=[], references=[])
    payload['clauses'].append(appendix)
    payload['compilation_note']['clause_digest'] = digest(payload['clauses'])
    payload['compilation_note']['profile_hash'] = digest(payload['profile'])
    return payload


class StandardDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyz-standard-delivery-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = task()

    def build(self, output='pack'):
        return delivery.prepare(self.root, self.payload, output, synthetic=True)

    def test_five_actual_documents_and_external_manifest(self):
        manifest = self.build()
        self.assertEqual(len(list((self.root / 'pack/body').glob('*.docx'))), 5)
        self.assertEqual(manifest['professional_review'], 'not_performed')
        self.assertEqual(manifest['external_action'], 'not_performed')
        self.assertNotIn('manifest.json', [row['path'] for row in manifest['files']])
        result = delivery.verify(self.root, self.payload, 'pack', synthetic=True)
        self.assertTrue(result['file_hashes_equal'])
        self.assertEqual(result['input_hash'], digest(self.payload))

    def test_pending_reader_summary_preserves_reasons_and_locations_without_field_dump(self):
        from evals.test_standards_closed_loop import final_ready_payload
        from tools.document_review import review_docx
        self.payload = final_ready_payload()
        result = self.build()
        pending = result['pending_reviews']
        self.assertTrue(pending)
        checks = json.loads((self.root / 'pack/internal/checks.json').read_bytes())
        self.assertEqual(pending, checks['pending_reviews'])
        for role in ('compilation_note', 'comment_disposition', 'verification_matrix', 'review_report'):
            current = review_docx((self.root / f'pack/body/{role}.docx').read_bytes())['current']
            bookmarks = [row for row in current['bookmarks']
                         if row['name'] in {'FiniteSemanticPending', 'ReviewSemanticPending'}]
            self.assertEqual(1, len(bookmarks))
            text = bookmarks[0]['text']
            self.assertIn('共' + str(len(pending)) + '项', text)
            self.assertIn('internal/checks.json', text)
            for row in pending:
                self.assertIn(row['code'], text)
                self.assertIn(row['reason'], text)
                for key in ('target_id', 'record_id', 'binding_id'):
                    if row.get(key):
                        self.assertIn(row[key], text)
            for key in ('binding_id：', 'target_type：', 'limitation_type：'):
                self.assertNotIn(key, text)
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_reader_realization_keeps_state_and_change_without_technical_hashes(self):
        from tools.document_review import review_docx
        self.build()
        internal = json.loads((self.root / 'pack/internal/realizations.json').read_bytes())
        current = review_docx((self.root / 'pack/body/comment_disposition.docx').read_bytes())['current']
        text = next(row['text'] for row in current['bookmarks'] if row['name'] == 'CommentRealization1')
        for row in internal:
            self.assertIn(row['status'], text)
            for change in row['changes']:
                self.assertIn(change['clause_id'], text)
                self.assertIn(change['operation'], text)
            for key in ('decision_hash', 'baseline_clause_digest', 'target_clause_digest', 'body_sha256'):
                self.assertNotIn(row[key], text)
        self.assertIn('internal/realizations.json', text)
        self.assertIn(self.payload['comments'][0]['text'], '\n'.join(row['text'] for row in current['blocks']))
        self.assertIn(self.payload['comment_outcomes'][0]['reason'], '\n'.join(row['text'] for row in current['blocks']))

    def test_ordinary_unresolved_reference_is_visible_in_actual_review_report(self):
        from evals.test_standards_closed_loop import final_ready_payload
        from tools.document_review import review_docx
        self.payload = final_ready_payload()
        self.payload['clauses'][0]['references'] = ['MISSING']
        self.assertTrue(all(change['operation'] != 'delete'
                            for row in self.payload['comment_outcomes']
                            for change in row['changes']))
        result = self.build()
        self.assertIn('unresolved_clause_reference',
                      {row['code'] for row in result['issues']})
        self.assertEqual('internal_draft_needs_evidence', result['delivery_state'])
        current = review_docx((self.root / 'pack/body/review_report.docx').read_bytes())['current']
        text = '\n'.join(block['text'] for block in current['blocks'])
        self.assertIn('C-1', text)
        self.assertIn('MISSING', text)
        self.assertIn('unresolved_clause_reference', text)
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack',
                                       synthetic=True)['file_hashes_equal'])

    def test_issue_free_candidate_retains_actual_semantic_review_gaps(self):
        from evals.test_standards_closed_loop import final_ready_payload
        self.payload = final_ready_payload()
        result = self.build()
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['delivery_state'], 'internal_draft_needs_review')
        self.assertTrue(result['pending_reviews'])
        self.assertIn('source_evidence_not_verified', {row['code'] for row in result['pending_reviews']})
        checks = json.loads((self.root / 'pack/internal/checks.json').read_text(encoding='utf-8'))
        finite = checks['finite_review']
        self.assertEqual(1, finite['coverage']['actual_texts_checked'])
        self.assertEqual(sha256_bytes((self.root / 'pack/body/standard.docx').read_bytes()),
                         finite['actual_document']['sha256'])
        self.assertNotIn('actual_final_text_not_verified', {row['code'] for row in result['pending_reviews']})
        from tools.document_review import review_docx
        for role in ('compilation_note', 'comment_disposition', 'verification_matrix', 'review_report'):
            actual = review_docx((self.root / f'pack/body/{role}.docx').read_bytes())['current']
            text = '\n'.join(block['text'] for block in actual['blocks'])
            self.assertIn('有限核对待审', text)
            self.assertIn('source_evidence_not_verified', text)
            self.assertIn('专业', text)
        self.assertTrue(all(row.get('final_location', {}).get('bookmark')
                            for row in finite['limitation_checks']))
        self.assertEqual(result['professional_review'], 'not_performed')
        self.assertEqual(result['official_status'], 'not_asserted')
        self.assertEqual(result['external_action'], 'not_performed')
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_model_candidates_survive_actual_review_with_no_deterministic_findings(self):
        from evals.test_standards_closed_loop import final_ready_payload
        for blocks in ('none', 'submission'):
            with self.subTest(blocks=blocks):
                self.payload = final_ready_payload()
                candidate = dict(
                    id='SYNTHETIC-MODEL-CANDIDATE-1',
                    question='原创合成候选：校验失败时是否也需记录错误原因？',
                    owner='合成技术审阅人', blocks=blocks,
                    recovery='由技术审阅人核对原始需求并记录处置。',
                    source_refs=['synthetic:model-candidate-fixture#1'],
                    origin='model_candidate', state='needs_review',
                    locator=dict(clause_id='C-1', version='v2',
                                 quote=self.payload['clauses'][0]['text']))
                self.payload['open_items'] = [candidate]
                self.payload['compilation_note']['sections'][-1]['open_items'] = [copy.deepcopy(candidate)]
                before = copy.deepcopy(self.payload)
                assessment = delivery.standards.closed_loop(self.payload)
                expected_codes = set() if blocks == 'none' else {'open_item_stage_blocked'}
                self.assertEqual(expected_codes, {row['code'] for row in assessment['issues']})
                self.assertFalse(assessment['outcome_tally']['closed'])
                output = 'candidate-' + blocks
                result = self.build(output)
                self.assertEqual(before, self.payload)
                self.assertEqual(expected_codes, {row['code'] for row in result['issues']})
                self.assertEqual('needs_review' if blocks == 'none' else 'needs_evidence', result['status'])
                self.assertEqual('internal_draft_needs_review' if blocks == 'none'
                                 else 'internal_draft_needs_evidence', result['delivery_state'])
                self.assertTrue(result['pending_reviews'])
                self.assertEqual(len(result['pending_reviews']),
                                 result['machine_checks']['semantic_pending_count'])
                self.assertEqual('not_performed', result['professional_review'])
                self.assertEqual('not_performed', result['machine_checks']['natural_language_correctness'])
                self.assertEqual('not_performed', result['external_action'])
                with zipfile.ZipFile(self.root / output / 'body/review_report.docx') as package:
                    tree = ET.fromstring(package.read('word/document.xml'))
                text = ''.join(node.text or '' for node in tree.iter(
                    '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                for value in (candidate['id'], candidate['question'], candidate['owner'],
                              candidate['recovery'], candidate['source_refs'][0],
                              candidate['origin'], candidate['state'], candidate['blocks'],
                              *candidate['locator'].values()):
                    self.assertIn(value, text)
                self.assertIn('自然语言技术正确性和专业签核均未执行', text)
                self.assertTrue(delivery.verify(self.root, self.payload, output, synthetic=True)['file_hashes_equal'])

    def test_final_docx_original_clause_is_the_finite_review_consumer(self):
        cases = [
            ('设备周期应为10 ms。', '设备周期应为100 ms。',
             {'quantities': [dict(id='Q1', value=10, unit='ms', source='S1')]},
             'review_quantity_conflict'),
            ('仅在设备就绪时设备应启动。', '设备就绪时设备应启动。',
             {'conditions': ['设备就绪']}, 'review_condition_direction_conflict'),
            ('设备宜保持指示灯常亮；维护模式除外。', '设备应保持指示灯常亮。',
             {'strength': 'recommendation', 'exceptions': ['维护模式']}, 'review_exception_conflict'),
        ]
        original_outline = delivery._outline
        for index, (expected, actual, semantics, code) in enumerate(cases):
            with self.subTest(code=code):
                self.payload = task()
                self.payload['clauses'][0].update(text=expected, **semantics)
                self.payload['comments'] = []
                self.payload['comment_outcomes'] = []
                self.payload['compilation_note']['clause_digest'] = digest(self.payload['clauses'])
                before = copy.deepcopy(self.payload)
                def faulty_projection(payload, issues):
                    blocks, locations, default = original_outline(payload, issues)
                    for block in blocks:
                        if block.get('origin') == 'clauses/CL1':
                            block['text'] = actual
                    return blocks, locations, default
                output = 'actual-clause-' + str(index)
                with patch.object(delivery, '_outline', side_effect=faulty_projection):
                    manifest = self.build(output)
                self.assertEqual(before, self.payload)
                self.assertIn(code, {row['code'] for row in manifest['issues']})
                self.assertEqual('internal_draft_needs_evidence', manifest['delivery_state'])
                checks = json.loads((self.root / output / 'internal/checks.json').read_text(encoding='utf-8'))
                finite = checks['finite_review']
                self.assertEqual(1, finite['coverage']['actual_texts_checked'])
                conflict = next(row for row in finite['limitation_checks'] if row['judgment'] == 'conflicts')
                self.assertEqual(sha256_bytes(actual.encode('utf-8')), conflict['actual_sha256'])
                self.assertTrue(conflict['final_location']['bookmark'])
                self.assertEqual(sha256_bytes((self.root / output / 'body/standard.docx').read_bytes()),
                                 conflict['final_location']['document_sha256'])

    def test_decision_is_not_modified_by_realization(self):
        before = copy.deepcopy(self.payload)
        self.build()
        self.assertEqual(self.payload, before)
        report = json.loads((self.root / 'pack/internal/realizations.json').read_text(encoding='utf-8'))
        self.assertEqual(report[0]['decision_hash'], digest(self.payload['comment_outcomes'][0]))
        self.assertEqual(report[0]['target_clause_digest'], digest(self.payload['clauses']))
        self.assertEqual(report[0]['body_sha256'], sha256_bytes((self.root / 'pack/body/standard.docx').read_bytes()))

    def test_body_preserves_conditions_exceptions_and_quantities(self):
        clause = self.payload['clauses'][0]
        clause['conditions'] = ['仅在启动状态']
        clause['exceptions'] = ['维护状态除外']
        clause['quantities'] = [dict(id='Q1', value=12, unit='ms', tolerance=2, source='S1')]
        self.payload['compilation_note']['clause_digest'] = digest(self.payload['clauses'])
        self.build()
        with zipfile.ZipFile(self.root / 'pack/body/standard.docx') as package:
            tree = ET.fromstring(package.read('word/document.xml'))
        text = ''.join(n.text or '' for n in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        for expected in ('仅在启动状态', '维护状态除外', '12', 'ms', 'tolerance', '2'):
            self.assertIn(expected, text)

    def test_canonical_json_roundtrip_keeps_document_bytes(self):
        self.build()
        restored = json.loads((self.root / 'pack/internal/input.json').read_text(encoding='utf-8'))
        result = delivery.verify(self.root, restored, 'pack', synthetic=True)
        self.assertTrue(result['file_hashes_equal'])

    def test_no_overwrite_and_deterministic_documents(self):
        self.build('first')
        self.build('second')
        for path in (self.root / 'first').rglob('*'):
            if path.is_file():
                self.assertEqual(path.read_bytes(), (self.root / 'second' / path.relative_to(self.root / 'first')).read_bytes())
        with self.assertRaisesRegex(ContractError, 'output_exists'):
            self.build('first')

    def test_tampering_with_body_or_manifest_is_rejected(self):
        self.build()
        path = self.root / 'pack/body/standard.docx'
        raw = path.read_bytes()
        path.write_bytes(raw + b'changed')
        with self.assertRaises(ContractError):
            delivery.verify(self.root, self.payload, 'pack', synthetic=True)
        path.write_bytes(raw)
        path = self.root / 'pack/manifest.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['professional_review'] = 'approved'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaises(ContractError):
            delivery.verify(self.root, self.payload, 'pack', synthetic=True)

    def test_added_file_and_changed_payload_rejected(self):
        self.build()
        (self.root / 'pack/body/private.txt').write_text('synthetic private', encoding='utf-8')
        with self.assertRaises(ContractError):
            delivery.verify(self.root, self.payload, 'pack', synthetic=True)
        self.payload['version'] = 'v3'
        with self.assertRaises(ContractError):
            delivery.verify(self.root, self.payload, 'pack', synthetic=True)

    def test_mode_and_path_rejected_before_output(self):
        with self.assertRaises(ContractError):
            delivery.prepare(self.root, self.payload, 'pack')
        with self.assertRaises(ContractError):
            self.build('../escape')
        self.assertFalse((self.root / 'pack').exists())
        self.payload['sensitivity'] = 'restricted'
        with self.assertRaises(ContractError):
            self.build()

    def test_missing_note_can_be_rendered_as_incomplete_internal_draft(self):
        self.payload.pop('compilation_note')
        manifest = self.build()
        self.assertEqual(manifest['status'], 'needs_evidence')
        self.assertTrue(manifest['issues'])
        self.assertEqual(manifest['delivery_state'], 'internal_draft_needs_evidence')

    def test_unknown_contract_version_refused(self):
        self.payload['contract_version'] = 3
        with self.assertRaises(ContractError):
            self.build()

    def test_no_change_is_bound_without_claiming_a_rewrite(self):
        from evals.test_standards_closed_loop import final_ready_payload
        self.payload = final_ready_payload()
        self.payload['baseline_clauses'] = copy.deepcopy(self.payload['clauses'])
        outcome = self.payload['comment_outcomes'][0]
        outcome.pop('changes')
        outcome.update(no_change=True, reason_source='synthetic:already-satisfied')
        self.build()
        rows = json.loads((self.root / 'pack/internal/realizations.json').read_text(encoding='utf-8'))
        self.assertEqual(rows[0]['status'], 'unchanged_structure_bound')
        self.assertEqual(rows[0]['changes'], [])
        self.assertEqual(rows[0]['no_change_check']['clause_ids'], ['C-1'])

    def test_confirmation_is_not_professional_review_and_invalidates(self):
        self.build()
        ledger = VersionLedger()
        binding = delivery.register_package(ledger, self.root, self.payload, 'pack', synthetic=True)
        event = dict(id='confirm-1', actor_id='synthetic-human', actor_type='human',
                     authority_evidence='synthetic-fixture-only', stage='internal_review',
                     decision='accepted', manifest_sha256=binding['manifest_sha256'],
                     confirmed_at='2026-11-01T00:00:00Z')
        record_id = delivery.record_confirmation(ledger, binding, event)
        self.assertEqual(ledger.reviews, [])
        self.assertTrue(delivery.confirmation_current(ledger, record_id, self.root, self.payload, 'pack', synthetic=True))
        self.payload['version'] = 'v3'
        self.payload['compilation_note']['version'] = 'v3'
        self.build('next')
        delivery.register_package(ledger, self.root, self.payload, 'next', synthetic=True)
        self.assertFalse(ledger.is_current(record_id))

    def admission(self):
        self.payload['sensitivity'] = 'restricted'
        now = datetime.now(timezone.utc)
        return dict(root=str(self.root), output='pack', payload_hash=digest(self.payload),
                    sensitivity='restricted', purpose='synthetic-boundary-test',
                    permissions=[dict(action=action, purpose='synthetic-boundary-test',
                        recipient='local_tool', decision='allow', authority_evidence='synthetic-only',
                        valid_from=(now - timedelta(days=1)).isoformat(),
                        valid_until=(now + timedelta(days=1)).isoformat())
                        for action in ('local_read', 'local_process', 'copy', 'local_write')],
                    environment=dict(assessment_evidence='synthetic-only', data_paths=[
                        dict(id=key, mode='disabled' if key != 'tools' else 'local',
                             verified=True, evidence='synthetic-only')
                        for key in ('host_model', 'index', 'telemetry', 'tools', 'logs', 'subprocess')]))

    def test_permission_and_environment_checked_before_rendering(self):
        admission = self.admission()
        for action in ('local_read', 'local_process', 'copy', 'local_write'):
            denied = copy.deepcopy(admission)
            denied['permissions'] = [p for p in denied['permissions'] if p['action'] != action]
            with self.subTest(action=action), patch.object(delivery, '_project') as render:
                with self.assertRaises(ContractError):
                    delivery.prepare(self.root, self.payload, 'pack', admission=denied)
                render.assert_not_called()
        admission['environment']['data_paths'][0]['verified'] = False
        with self.assertRaises(ContractError):
            delivery.prepare(self.root, self.payload, 'pack', admission=admission)
        self.assertFalse((self.root / 'pack').exists())

    def test_public_materials_still_require_all_data_paths(self):
        admission = self.admission()
        self.payload['sensitivity'] = 'public'
        admission.update(sensitivity='public', payload_hash=digest(self.payload), environment={})
        with patch.object(delivery, '_project') as render:
            with self.assertRaises(ContractError):
                delivery.prepare(self.root, self.payload, 'pack', admission=admission)
            render.assert_not_called()

    def test_authorized_case_cannot_overlap_source_or_package(self):
        admission = self.admission()
        package = Path(delivery.__file__).resolve().parents[1]
        for root in (package, package.parent, package / 'tools'):
            with self.subTest(root=root):
                admission['root'] = str(root)
                with self.assertRaisesRegex(ContractError, 'standard_case_root_must_be_independent'):
                    delivery._admit(root, self.payload, 'not-created', synthetic=False, admission=admission)

    def test_each_document_displays_identity_and_internal_input_keeps_bindings(self):
        self.build()
        for role in delivery.ROLES:
            with zipfile.ZipFile(self.root / f'pack/body/{role}.docx') as package:
                tree = ET.fromstring(package.read('word/document.xml'))
            text = ''.join(n.text or '' for n in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
            for expected in (self.payload['project_id'], self.payload['version'], self.payload['compilation_note']['standard_name']):
                self.assertIn(expected, text)
        stored = json.loads((self.root / 'pack/internal/input.json').read_bytes())
        self.assertEqual(self.payload['compilation_note']['clause_digest'],
                         stored['compilation_note']['clause_digest'])
        self.assertEqual(self.payload['compilation_note']['profile_hash'],
                         stored['compilation_note']['profile_hash'])
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_expiry_rechecked_after_render_before_any_output(self):
        admission = self.admission()
        valid = datetime.now(timezone.utc).isoformat()
        expired = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        with patch.object(delivery, '_now', side_effect=[valid, expired]):
            with self.assertRaisesRegex(ContractError, 'permission_not_proven'):
                delivery.prepare(self.root, self.payload, 'pack', admission=admission)
        self.assertFalse((self.root / 'pack').exists())

    def test_authorization_changes_invalidate_without_reregistering(self):
        admission = self.admission()
        delivery.prepare(self.root, self.payload, 'pack', admission=admission)
        ledger = VersionLedger()
        binding = delivery.register_package(ledger, self.root, self.payload, 'pack', admission=admission)
        event = dict(id='auth-confirm', actor_id='synthetic-human', actor_type='human',
                     authority_evidence='synthetic-only', stage='internal_review', decision='accepted',
                     manifest_sha256=binding['manifest_sha256'], confirmed_at='2026-11-01T00:00:00Z')
        identity = delivery.record_confirmation(ledger, binding, event)
        self.assertTrue(delivery.confirmation_current(ledger, identity, self.root, self.payload, 'pack', admission=admission))
        changed = copy.deepcopy(admission)
        changed['permissions'][0]['authority_evidence'] = 'synthetic-renewed-grant'
        self.assertFalse(delivery.confirmation_current(ledger, identity, self.root, self.payload, 'pack', admission=changed))
        changed['permissions'][0]['revoked'] = True
        with self.assertRaises(ContractError):
            delivery.confirmation_current(ledger, identity, self.root, self.payload, 'pack', admission=changed)

    def test_confirmation_does_not_authorize_an_identical_copy(self):
        self.build('pack')
        self.build('copy')
        ledger = VersionLedger()
        binding = delivery.register_package(ledger, self.root, self.payload, 'pack', synthetic=True)
        event = dict(id='copy-confirm', actor_id='synthetic-human', actor_type='human',
                     authority_evidence='synthetic-only', stage='internal_review', decision='accepted',
                     manifest_sha256=binding['manifest_sha256'], confirmed_at='2026-11-01T00:00:00Z')
        identity = delivery.record_confirmation(ledger, binding, event)
        self.assertFalse(delivery.confirmation_current(ledger, identity, self.root, self.payload, 'copy', synthetic=True))

    def test_actual_tables_preserve_full_original_and_verification(self):
        self.build()
        checks = json.loads((self.root / 'pack/internal/checks.json').read_text(encoding='utf-8'))
        by_role = {row['role']: row for row in checks['documents']}
        self.assertEqual(by_role['comment_disposition']['checks']['tables'], 1)
        self.assertEqual(by_role['verification_matrix']['checks']['tables'], 1)
        with zipfile.ZipFile(self.root / 'pack/body/comment_disposition.docx') as package:
            tree = ET.fromstring(package.read('word/document.xml'))
        text = ''.join(n.text or '' for n in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        self.assertIn(self.payload['comments'][0]['text'], text)
        self.assertIn(self.payload['comment_outcomes'][0]['reason'], text)
        self.assertIn(self.payload['clauses'][0]['text'], text)

    def test_v2_ballot_unknown_version_reaches_actual_comment_document(self):
        self.payload['participants'] = [dict(id=f'P{i}', group='synthetic', eligible=True,
            authority_evidence=f'synthetic-authority-{i}') for i in (1, 2)]
        self.payload['votes'] = [dict(id=f'VOTE-{i}', participant_id=f'P{i}', choice='yes',
            evidence_id=f'synthetic-vote-{i}') for i in (1, 2)]
        self.payload['ballot_rule'] = dict(source='synthetic-rule', min_votes=2,
            min_yes_fraction=0.5, denominator='cast')
        result = self.build()
        self.assertTrue(any(row['code'] == 'vote_version_unproven' for row in result['issues']))
        self.assertFalse(any(row['code'] == 'standard_package_field_unprojected'
                             and row['field'] in {'votes', 'ballot_rule'} for row in result['issues']))
        with zipfile.ZipFile(self.root / 'pack/body/comment_disposition.docx') as package:
            tree = ET.fromstring(package.read('word/document.xml'))
        text = ''.join(node.text or '' for node in tree.iter(
            '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        for value in ('numeric_conditions_met', 'same_version_status', 'unknown', 'VOTE-1', 'VOTE-2'):
            self.assertIn(value, text)
        self.assertEqual('internal_draft_needs_evidence', result['delivery_state'])
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_internal_profile_emits_real_reference_and_directory_fields(self):
        self.payload['profile']['rendering'] = 'dyz-standard-internal-v1'
        self.payload['compilation_note']['profile_hash'] = digest(self.payload['profile'])
        self.build()
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        instructions = []
        for path in (self.root / 'pack/body').glob('*.docx'):
            with zipfile.ZipFile(path) as package:
                tree = ET.fromstring(package.read('word/document.xml'))
            instructions.extend((node.text or '').strip() for node in tree.iter(ns + 'instrText'))
        for kind in ('TOC', 'REF', 'SEQ', 'PAGEREF'):
            with self.subTest(kind=kind):
                self.assertTrue(any(value.split()[0] == kind for value in instructions if value), kind)
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_twelve_semantic_fields_and_long_appendix_survive_actual_docx(self):
        self.payload = stress_task()
        manifest = self.build()
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        with zipfile.ZipFile(self.root / 'pack/body/comment_disposition.docx') as package:
            tree = ET.fromstring(package.read('word/document.xml'))
        text = ''.join(node.text or '' for node in tree.iter(ns + 't'))
        for comment, outcome in zip(self.payload['comments'], self.payload['comment_outcomes']):
            values = [str(comment['seq']), comment['clause_id'], comment['origin']['organization'],
                      comment['origin']['representative_scope'], comment['text'], outcome['classification'],
                      outcome['outcome'], outcome['reason'], outcome['changes'][0]['proposed_text'],
                      'verification', 'references', 'compilation_note', 'downstream_products',
                      outcome['major_change'], outcome['unresolved_item']['question'],
                      outcome['unresolved_item']['recovery'], outcome['owner'], comment['source']]
            for value in values:
                with self.subTest(comment=comment['id'], value=value[:32]):
                    self.assertIn(value, text)
        self.assertIn('tally_balanced', text)
        with zipfile.ZipFile(self.root / 'pack/body/standard.docx') as package:
            body = ET.fromstring(package.read('word/document.xml'))
        self.assertIn(self.payload['clauses'][-1]['text'], ''.join(node.text or '' for node in body.iter(ns + 't')))
        self.assertEqual('internal_draft_needs_evidence', manifest['delivery_state'])
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_final_candidate_scans_placeholders_without_optional_fidelity(self):
        self.payload['delivery_stage'] = 'review_candidate'
        self.payload['clauses'][0]['text'] += '【待确认：真实阈值】'
        self.payload['comment_outcomes'][0]['changes'][0]['proposed_text'] = self.payload['clauses'][0]['text']
        self.payload['compilation_note']['clause_digest'] = digest(self.payload['clauses'])
        result = self.build()
        self.assertEqual(result['delivery_state'], 'internal_draft_needs_evidence')
        self.assertTrue(any(row['code'] == 'standard_document_quality' for row in result['issues']))
        checks = json.loads((self.root / 'pack/internal/checks.json').read_text(encoding='utf-8'))
        self.assertEqual(checks['documents'][0]['quality']['stage'], 'final')
        self.assertEqual(checks['documents'][0]['quality']['status'], 'blocked')

    def test_hardlink_alias_in_existing_package_rejected(self):
        self.build()
        original = self.root / 'pack/body/standard.docx'
        alias = self.root / 'alias.docx'
        os.link(original, alias)
        with self.assertRaisesRegex(ContractError, 'standard_file_alias_unsupported'):
            delivery.verify(self.root, self.payload, 'pack', synthetic=True)

    def test_confirmation_rechecks_actual_file(self):
        self.build()
        ledger = VersionLedger()
        binding = delivery.register_package(ledger, self.root, self.payload, 'pack', synthetic=True)
        event = dict(id='confirm-2', actor_id='synthetic-human', actor_type='human',
                     authority_evidence='synthetic-fixture-only', stage='internal_review',
                     decision='conditional', manifest_sha256=binding['manifest_sha256'],
                     confirmed_at='2026-11-01T00:00:00Z')
        record_id = delivery.record_confirmation(ledger, binding, event)
        (self.root / 'pack/body/standard.docx').write_bytes(b'changed')
        with self.assertRaises(ContractError):
            delivery.confirmation_current(ledger, record_id, self.root, self.payload, 'pack', synthetic=True)


class ReadingProjectionTests(unittest.TestCase):
    """SP-03：真实文书投影与完整记录保留是相互独立的要求。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyz-reading-projection-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = task()

    def body_text(self, role):
        with zipfile.ZipFile(self.root / f'pack/body/{role}.docx') as package:
            tree = ET.fromstring(package.read('word/document.xml'))
        return ''.join(node.text or '' for node in tree.iter(
            '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))

    def test_outline_renumbers_display_without_changing_stable_ids(self):
        original = self.payload['clauses'][0]['id']
        self.payload['presentation'] = {'outline': [
            {'id': 'chapter', 'kind': 'section', 'title': '记录要求'},
            {'id': 'record', 'parent_id': 'chapter', 'kind': 'clause',
             'title': '记录内容', 'clause_id': original}]}
        result = delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_bytes())
        self.assertEqual('1.1', mapping['clause_locations'][original]['display_number'])
        self.assertIn('1.1 记录内容', self.body_text('standard'))
        self.assertNotIn('strength：', self.body_text('standard'))
        self.assertEqual(original, self.payload['clauses'][0]['id'])
        self.assertEqual('1.7', result['generator_version'])
        self.assertEqual('standards-consistency/1', result['assessment_version'])

    def test_outline_insert_delete_and_annex_renumber_preserve_live_targets(self):
        original = self.payload['clauses'][0]['id']
        self.payload['presentation'] = {'outline': [
            {'id': 'section', 'kind': 'section', 'title': '正文'},
            {'id': 'item', 'parent_id': 'section', 'kind': 'clause',
             'clause_id': original, 'title': '记录要求'},
            {'id': 'annex-old', 'kind': 'annex', 'title': '保留附录'}]}
        delivery.prepare(self.root, self.payload, 'before', synthetic=True)
        before = json.loads((self.root / 'before/internal/source-map.json').read_bytes())
        outline = self.payload['presentation']['outline']
        inserted = dict(self.payload['clauses'][0], id='INSERTED', text='合成设备可记录启动状态。',
                        strength='permission', method_ids=[])
        self.payload['clauses'].append(inserted)
        outline[:0] = [dict(id='insert', kind='section', title='新增章节'),
                       dict(id='insert-clause', parent_id='insert', kind='clause',
                            clause_id='INSERTED', title='启动状态')]
        outline.insert(-1, dict(id='annex-new', kind='annex', title='新增附录'))
        self.payload['compilation_note']['clause_digest'] = digest(self.payload['clauses'])
        delivery.prepare(self.root, self.payload, 'inserted', synthetic=True)
        middle = json.loads((self.root / 'inserted/internal/source-map.json').read_bytes())
        self.assertEqual('1.1', before['clause_locations'][original]['display_number'])
        self.assertEqual('2.1', middle['clause_locations'][original]['display_number'])
        self.payload['clauses'] = [row for row in self.payload['clauses'] if row['id'] != 'INSERTED']
        self.payload['presentation']['outline'] = [row for row in outline
            if row['id'] not in {'insert', 'insert-clause', 'section'}]
        item = next(row for row in self.payload['presentation']['outline'] if row['id'] == 'item')
        item['parent_id'] = 'annex-old'
        self.payload['compilation_note']['clause_digest'] = digest(self.payload['clauses'])
        delivery.prepare(self.root, self.payload, 'deleted', synthetic=True)
        after = json.loads((self.root / 'deleted/internal/source-map.json').read_bytes())
        self.assertEqual('B.1', after['clause_locations'][original]['display_number'])
        self.assertEqual(before['clause_locations'][original]['bookmark'],
                         after['clause_locations'][original]['bookmark'])
        self.assertNotIn('INSERTED', after['clause_locations'])
        for role in ('standard', 'comment_disposition', 'verification_matrix'):
            with zipfile.ZipFile(self.root / f'deleted/body/{role}.docx') as archive:
                tree = ET.fromstring(archive.read('word/document.xml'))
            text = ''.join(node.text or '' for node in tree.iter(
                '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
            self.assertIn('B.1', text)
        self.assertTrue(delivery.verify(self.root, self.payload, 'deleted', synthetic=True)['file_hashes_equal'])
        with self.assertRaisesRegex(ContractError, 'standard_package_content_changed'):
            delivery.verify(self.root, self.payload, 'before', synthetic=True)

    def test_outline_rejects_cycles_duplicate_and_unknown_clause_before_output(self):
        variants = [
            [{'id': 'a', 'parent_id': 'b', 'kind': 'section', 'title': '甲'},
             {'id': 'b', 'parent_id': 'a', 'kind': 'section', 'title': '乙'}],
            [{'id': 'a', 'kind': 'section', 'title': '甲'},
             {'id': 'a', 'kind': 'section', 'title': '乙'}],
            [{'id': 'a', 'kind': 'clause', 'title': '甲', 'clause_id': 'missing'}],
            [{'id': 'a', 'kind': 'clause', 'title': '甲', 'clause_id': 'CL1'},
             {'id': 'b', 'kind': 'clause', 'title': '乙', 'clause_id': 'CL1'}]]
        for outline in variants:
            with self.subTest(outline=outline):
                self.payload['presentation'] = {'outline': outline}
                with self.assertRaises(ContractError):
                    delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
                self.assertFalse((self.root / 'pack').exists())

    def test_annex_and_clause_locations_are_shared_with_comments_and_matrix(self):
        self.payload['presentation'] = {'outline': [
            {'id': 'annex', 'kind': 'annex', 'title': '记录规则'},
            {'id': 'item', 'parent_id': 'annex', 'kind': 'clause',
             'clause_id': 'CL1', 'title': '结果记录'}]}
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_bytes())
        self.assertEqual('A.1', mapping['clause_locations']['CL1']['display_number'])
        for role in ('standard', 'comment_disposition', 'verification_matrix'):
            self.assertIn('A.1', self.body_text(role))

    def test_every_leaf_and_core_record_have_bound_projection(self):
        self.payload['comments'][0]['extension'] = {'nonstandard': '原创扩展内容不得丢失'}
        self.payload['comment_outcomes'][0]['extension'] = {'audit_note': '完整保留扩展决定'}
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        report = json.loads((self.root / 'pack/internal/projection-coverage.json').read_bytes())
        self.assertEqual('complete', report['status'])
        self.assertEqual([], report['unmapped_core_records'])
        self.assertEqual([], report['unpreserved_leaves'])
        for path in ('/clauses/0', '/comments/0', '/comment_outcomes/0', '/verification_matrix/0'):
            self.assertTrue(any(row['source_path'] == path and row['reader_blocks']
                                for row in report['core_records']))
        record = next(row for row in report['leaves']
                      if row['source_path'] == '/comments/0/extension/nonstandard')
        self.assertEqual('internal/input.json#/comments/0/extension/nonstandard', record['retained_at'])
        self.assertIn('原创扩展内容不得丢失', self.body_text('comment_disposition'))

    def test_missing_core_projection_is_detected_before_package_completion(self):
        original = delivery._block
        def drop_origin(identity, text, **options):
            block = original(identity, text, **options)
            if identity.startswith('Clause_'):
                block['origin'] = 'unbound'
            return block
        with patch.object(delivery, '_block', side_effect=drop_origin):
            with self.assertRaisesRegex(ContractError, 'standard_projection_core_missing'):
                delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        self.assertFalse((self.root / 'pack').exists())

    def test_fixed_original_and_report_reach_clause_reason_and_note_blocks(self):
        from evals.test_standard_sources import consumption_package
        source_payload, report = consumption_package(self.root)
        self.payload['source_reports'] = source_payload['source_reports']
        template = source_payload['source_bindings'][0]
        self.payload['source_bindings'] = [dict(template, binding_id='B-' + str(index),
            target_type=kind, target_id=identity) for index, (kind, identity) in enumerate([
                ('clause', 'CL1'), ('comment_reason', 'C1'),
                ('verification_basis', 'V1'), ('note_section', SECTION_IDS[0])])]
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        trace = json.loads((self.root / 'pack/internal/source-trace.json').read_bytes())
        self.assertEqual(4, len(trace))
        self.assertTrue(all(row['final_locations'] for row in trace))
        self.assertTrue(all(row['original_sha256'] == report['original_sha256'] for row in trace))
        self.assertTrue(all(row['proposition_support'] == 'not_verified' for row in trace))
        self.assertTrue(all(location['actual_text_state'] == 'literal_span_verified'
                            and location['actual_text_sha256']
                            and location['document_sha256']
                            for row in trace for location in row['final_locations']))
        checks = json.loads((self.root / 'pack/internal/checks.json').read_bytes())
        nonclauses = checks['finite_review']['nonclause_final_text_checks']
        self.assertEqual({'comment_reason', 'verification_basis', 'note_section'},
                         {row['target_type'] for row in nonclauses})
        self.assertTrue(all(row['status'] == 'needs_review'
                            and row['actual_blocks_checked'] > 0
                            and row['proposition_support'] == 'not_verified' for row in nonclauses))
        self.assertTrue(all(row.get('actual_evidence') == 'actual_final_bookmark_spans'
                            for row in checks['pending_reviews']
                            if row.get('binding_id') in {r['binding_id'] for r in nonclauses}))
        self.assertTrue(any(location['document_role'] == 'comment_disposition'
                            for row in trace if row['target_type'] == 'comment_reason'
                            for location in row['final_locations']))
        self.assertIn('来源追溯', self.body_text('review_report'))
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])
        before = (self.root / 'original.txt').read_bytes()
        (self.root / 'original.txt').write_bytes(before + b' changed')
        with self.assertRaisesRegex(ContractError, 'standard_package_content_changed'):
            delivery.verify(self.root, self.payload, 'pack', synthetic=True)

    def test_source_reader_preserves_ordered_quotes_context_and_half_open_ranges(self):
        from evals.test_standard_sources import consumption_package
        from tools.document_review import review_docx
        source_payload, _ = consumption_package(self.root)
        self.payload['source_reports'] = source_payload['source_reports']
        template = source_payload['source_bindings'][0]
        self.payload['source_bindings'] = [dict(template, binding_id='B-1', target_id='CL1')]
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        trace = json.loads((self.root / 'pack/internal/source-trace.json').read_bytes())
        current = review_docx((self.root / 'pack/body/review_report.docx').read_bytes())['current']
        text = next(row['text'] for row in current['bookmarks'] if row['name'] == 'SourceTrace1')
        self.assertIn('internal/source-trace.json', text)
        self.assertNotIn('quote：', text)
        self.assertNotIn('context：', text)
        positions = []
        for citation in trace[0]['citations']:
            self.assertIn('引文 ' + citation['id'], text)
            for segment in citation['segments']:
                location = ('第' + str(segment['page']) + '页，字符范围['
                            + str(segment['start']) + ',' + str(segment['end']) + ')')
                self.assertIn(location, text)
                self.assertIn('原文：\n' + segment['quote'], text)
                positions.append(text.index(location))
                if segment.get('context'):
                    self.assertIn(segment['context'], text)
        self.assertEqual(sorted(positions), positions)
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_source_reader_preserves_legacy_single_page_quote_and_context_in_actual_docx(self):
        from evals.test_standard_sources import consumption_package, identity
        from tools import standard_sources
        from tools.document_review import review_docx
        source_payload, _ = consumption_package(self.root, ['设备周期为10 ms。'])
        raw = (self.root / 'original.txt').read_bytes()
        report = standard_sources.import_local(self.root, 'original.txt', {
            'expected_sha256': sha256_bytes(raw), 'identity': identity(),
            'access_status': 'local_authorized', 'citations': [{
                'id': 'CITE-1', 'proposition': '设备周期为10 ms。', 'relation': 'supports',
                'page': 1, 'start': 5, 'end': 10, 'quote': '10 ms'}]}, synthetic=True)
        encoded = json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
        (self.root / 'report.json').write_bytes(encoded)
        self.payload['source_reports'] = source_payload['source_reports']
        self.payload['source_reports'][0]['sha256'] = sha256_bytes(encoded)
        self.payload['source_bindings'] = [dict(source_payload['source_bindings'][0], target_id='CL1')]
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        trace = json.loads((self.root / 'pack/internal/source-trace.json').read_bytes())
        citation = trace[0]['citations'][0]
        self.assertEqual('verified', trace[0]['state'])
        self.assertNotIn('segments', citation)
        self.assertEqual('10 ms', citation['quote'])
        current = review_docx((self.root / 'pack/body/review_report.docx').read_bytes())['current']
        text = next(row['text'] for row in current['bookmarks'] if row['name'] == 'SourceTrace1')
        for token in ('引文 CITE-1', '第1页，字符范围[5,10)', '原文：\n10 ms',
                      '上下文（字符范围[0,11)）：\n设备周期为10 ms。', 'internal/source-trace.json'):
            self.assertIn(token, text)
        self.assertEqual(raw, (self.root / 'original.txt').read_bytes())
        self.assertEqual(encoded, (self.root / 'report.json').read_bytes())
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_source_reader_keeps_distinct_context_without_rewriting_technical_spaces(self):
        citations = [{'id': 'C-1', 'segments': [
            {'page': 2, 'start': 3, 'end': 8, 'quote': '10 ms',
             'context_start': 0, 'context_end': 9, 'context': '周期为10 ms。'},
            {'page': 4, 'start': 1, 'end': 4, 'quote': 'A B',
             'context_start': 0, 'context_end': 5, 'context': '「A B」'}]}]
        text = delivery._source_citation_reader_text(citations)
        for token in ('引文 C-1', '第2页，字符范围[3,8)', '第4页，字符范围[1,4)',
                      '原文：\n10 ms', '原文：\nA B',
                      '上下文（字符范围[0,9)）：\n周期为10 ms。',
                      '上下文（字符范围[0,5)）：\n「A B」'):
            self.assertIn(token, text)
        self.assertNotIn('\u00a0', text)
        self.assertNotIn('\u200b', text)

    def test_reader_report_references_full_machine_evidence_without_duplicating_bookmark_text(self):
        payload = stress_task()
        payload['profile']['rendering'] = 'dyz-standard-internal-v2'
        payload['compilation_note']['profile_hash'] = digest(payload['profile'])
        delivery.prepare(self.root, payload, 'pack', synthetic=True)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_bytes())
        finite = json.loads((self.root / 'pack/internal/checks.json').read_bytes())['finite_review']
        summary = next(block['text'] for block in mapping['documents']['review_report']
                       if block['id'] == 'ReviewSemanticPending')
        self.assertTrue(finite['pending_reviews'])
        self.assertTrue(any(row.get('actual_range', {}).get('quote')
                            for row in finite['pending_reviews']))
        self.assertNotIn('actual_range', summary)
        self.assertNotIn('dependency_hash', summary)
        for row in finite['pending_reviews']:
            self.assertIn(row['code'], summary)
            if row.get('reason'):
                self.assertIn(row['reason'], summary)
        self.assertIn('internal/checks.json', self.body_text('review_report'))
        self.assertIn(payload['comments'][0]['text'], self.body_text('comment_disposition'))
        self.assertIn(payload['clauses'][-1]['text'], self.body_text('standard'))
        self.assertTrue(delivery.verify(self.root, payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_nonclause_final_business_fields_detect_source_literal_conflicts(self):
        from evals.test_standard_sources import consumption_package
        cases = [('仅在设备就绪时设备应启动。', '设备就绪时设备应启动。', 'condition_direction'),
                 ('设备周期应为10 ms。', '设备周期应为100 ms。', 'quantity_unit'),
                 ('设备宜保持指示灯常亮。', '设备应保持指示灯常亮。', 'strength'),
                 ('设备应记录结果；维护模式除外。', '设备应记录结果。', 'exception')]
        kinds = [('comment', 'C1'), ('comment_reason', 'C1'), ('verification', 'V1'),
                 ('verification_basis', 'V1'), ('compilation_note', SECTION_IDS[0]),
                 ('note_section', SECTION_IDS[0])]
        for case_index, (source, actual, dimension) in enumerate(cases):
            with tempfile.TemporaryDirectory(dir=self.root) as folder:
                base = Path(folder)
                source_payload, _ = consumption_package(base, [source])
                for kind, identity in kinds:
                    with self.subTest(kind=kind, dimension=dimension):
                        payload = task()
                        payload['source_reports'] = source_payload['source_reports']
                        payload['source_bindings'] = [dict(source_payload['source_bindings'][0],
                            target_type=kind, target_id=identity)]
                        if kind == 'comment':
                            payload['comments'][0]['text'] = actual
                        elif kind == 'comment_reason':
                            payload['comment_outcomes'][0]['reason'] = actual
                        elif kind == 'verification':
                            payload['verification_matrix'][0]['method'] = actual
                        elif kind == 'verification_basis':
                            payload['verification_matrix'][0]['reason'] = actual
                        else:
                            payload['compilation_note']['sections'][0]['body'] = actual
                        output = kind + '-' + str(case_index)
                        result = delivery.prepare(base, payload, output, synthetic=True)
                        finite = json.loads((base / output / 'internal/checks.json').read_bytes())['finite_review']
                        checks = [row for row in finite['limitation_checks']
                                  if row.get('binding_id') == 'B-1' and row['limitation_type'] == dimension]
                        self.assertEqual(1, len(checks))
                        check = checks[0]
                        self.assertEqual('conflicts', check['judgment'])
                        self.assertEqual(kind, check['target_type'])
                        location = check['actual_location']
                        raw = (base / output / ('body/' + location['document_role'] + '.docx')).read_bytes()
                        self.assertEqual(sha256_bytes(raw), location['document_sha256'])
                        from tools.document_review import review_docx
                        bookmark = next(row for row in review_docx(raw)['current']['bookmarks']
                                        if row['name'] == location['bookmark'])
                        self.assertEqual(actual, bookmark['text'][location['start']:location['end']])
                        expected_quote = '100 ms' if dimension == 'quantity_unit' else actual
                        self.assertEqual(expected_quote, bookmark['text'][check['actual_range']['start']:
                                                                         check['actual_range']['end']])
                        self.assertEqual(expected_quote, check['actual_range']['quote'])
                        self.assertEqual('conflicts', finite['nonclause_final_text_checks'][0]['finite_check_status'])
                        self.assertTrue(any(row['code'] == 'source_proposition_applicability_needs_review'
                                            for row in result['pending_reviews']))
                        self.assertIn('conflicts', '\n'.join(str(row) for row in result['issues']))
                        self.assertEqual('internal_draft_needs_evidence', result['delivery_state'])
                        self.assertTrue(delivery.verify(base, payload, output, synthetic=True)['file_hashes_equal'])

    def test_payload_passed_cannot_substitute_for_actual_source_verification(self):
        from evals.test_standard_sources import consumption_package
        source_payload, _ = consumption_package(self.root)
        self.payload['source_reports'] = source_payload['source_reports']
        self.payload['source_bindings'] = [dict(source_payload['source_bindings'][0], target_id='CL1')]
        with self.assertRaisesRegex(ContractError, 'standard_source_verification_not_current'):
            delivery._project(self.payload, source_verification={'passed': True})
        _, _, issues = delivery._project(self.payload)
        self.assertIn('source_reports_not_verified', {row['code'] for row in issues})

    def test_v2_nested_annex_uses_declared_four_level_styles(self):
        self.payload['profile']['rendering'] = 'dyz-standard-internal-v2'
        self.payload['compilation_note']['profile_hash'] = digest(self.payload['profile'])
        self.payload['presentation'] = {'outline': [
            {'id': 'a', 'kind': 'annex', 'title': '合成附录'},
            {'id': 'b', 'parent_id': 'a', 'kind': 'section', 'title': '记录'},
            {'id': 'c', 'parent_id': 'b', 'kind': 'section', 'title': '状态'},
            {'id': 'd', 'parent_id': 'c', 'kind': 'clause', 'clause_id': 'CL1', 'title': '结果'}]}
        manifest = delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_bytes())
        self.assertEqual('A.1.1.1', mapping['clause_locations']['CL1']['display_number'])
        self.assertTrue(any(block['kind'] == 'heading4' and block['annex']
                            for block in mapping['documents']['standard']))
        with zipfile.ZipFile(self.root / 'pack/body/standard.docx') as archive:
            self.assertIn(b'AnnexHeading4', archive.read('word/document.xml'))
            self.assertIn(b'PAGE', archive.read('word/footer1.xml'))
        self.assertEqual(delivery.documents.document_profile('dyz-standard-internal-v2')['hash'],
                         manifest['rendering_profile_hash'])
        self.assertTrue(delivery.verify(self.root, self.payload, 'pack', synthetic=True)['file_hashes_equal'])

    def test_original_table_profiles_reach_real_five_document_projection(self):
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        mapping = json.loads((self.root / 'pack/internal/source-map.json').read_bytes())
        for role, profile, width in (('comment_disposition', 'dyz-comment-six-column-v1', 6),
                                     ('review_report', 'dyz-comment-three-column-v1', 3)):
            table = next(block for block in mapping['documents'][role]
                         if block.get('table_profile') == profile)
            expected = delivery.documents.table_template_profile(profile)
            self.assertEqual([column['header'] for column in expected['columns']], table['cells'][0])
            self.assertTrue(all(len(row) == width for row in table['cells']))
            with zipfile.ZipFile(self.root / f'pack/body/{role}.docx') as archive:
                self.assertIn(b'tblHeader', archive.read('word/document.xml'))

    def test_incomplete_outline_preserves_missing_clause_but_blocks_readiness(self):
        self.payload['presentation'] = {'outline': [{'id': 'section', 'kind': 'section', 'title': ''}]}
        result = delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        self.assertTrue({'standard_outline_clause_missing', 'standard_outline_title_missing'}
                        <= {row['code'] for row in result['issues']})
        self.assertEqual('internal_draft_needs_evidence', result['delivery_state'])
        self.assertIn(self.payload['clauses'][0]['text'], self.body_text('standard'))

    def test_organization_note_uses_declared_order_and_semantics(self):
        for ids in (('overview', 'evidence', 'pending'), ('scope', 'basis', 'followup')):
            with self.subTest(ids=ids):
                payload = task()
                semantics = dict(zip(ids, (SECTION_IDS[0], SECTION_IDS[3], SECTION_IDS[-1])))
                payload['profile'] = dict(id='original-organization-example', version='1',
                    scope='organization', source='original:test-authorized-profile',
                    required_sections=list(ids), section_semantics=semantics)
                note = payload['compilation_note']
                note.update(profile_id=payload['profile']['id'], profile_hash=digest(payload['profile']))
                note['sections'] = [dict(id=key, heading='组织明确章节 ' + key,
                    body='本章完整内容 ' + key, state='explicit', owner='synthetic-author', source=['S1'])
                    for key in reversed(ids)]
                output = 'profile-' + ids[0]
                delivery.prepare(self.root, payload, output, synthetic=True)
                with zipfile.ZipFile(self.root / output / 'body/compilation_note.docx') as archive:
                    tree = ET.fromstring(archive.read('word/document.xml'))
                text = ''.join(n.text or '' for n in tree.iter(
                    '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
                positions = [text.index('组织明确章节 ' + key) for key in ids]
                self.assertEqual(sorted(positions), positions)
                self.assertNotIn('clause_digest', text)
                self.assertNotIn('profile_hash', text)
                coverage = json.loads((self.root / output / 'internal/projection-coverage.json').read_bytes())
                self.assertEqual(3, sum(row['source_path'].startswith('/compilation_note/sections/')
                                        for row in coverage['core_records']))
                self.assertTrue(delivery.verify(self.root, payload, output, synthetic=True)['file_hashes_equal'])

    def test_old_generator_has_explicit_recovery_diagnostic(self):
        delivery.prepare(self.root, self.payload, 'pack', synthetic=True)
        path = self.root / 'pack/manifest.json'
        manifest = json.loads(path.read_bytes())
        for version in ('1.1', '1.2', '1.3', '1.4', '1.5', '1.6'):
            with self.subTest(version=version):
                manifest['generator_version'] = version
                path.write_bytes(delivery.canonical_bytes(manifest))
                with self.assertRaisesRegex(ContractError, 'standard_generator_version_unsupported'):
                    delivery.verify(self.root, self.payload, 'pack', synthetic=True)


if __name__ == '__main__':
    unittest.main()
