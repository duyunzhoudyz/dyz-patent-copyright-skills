"""完整正文、改稿绑定及AI未知贡献的合成回归。"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools import software
from tools.core import ContractError

FIXTURE = Path(__file__).parent / 'fixtures/software/synthetic.json'


class SoftwareAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'counter.py').write_text(self.fixture['source'], encoding='utf-8')
        self.payload = {'context': self.fixture['context'], 'authorized_root': str(self.root),
                        'scope_input': self.fixture['scope_input'], 'rights': self.fixture['rights'],
                        'files': [{'id': 'f1', 'path': 'counter.py', 'component_id': 'cli',
                                   'kind': 'source', 'include': True}],
                        'inventory_complete': True, 'pagination': self.fixture['pagination'],
                        'manual_input': self.fixture['manual_input'],
                        'form_rule_evidence': 'synthetic-rule'}

    def test_ai_contribution_unknown_and_partial_remain_needs_evidence(self):
        scope_input = copy.deepcopy(self.fixture['scope_input'])
        scope_input['components'][0]['origin'] = 'ai'
        scope = software._scope(scope_input)[0]
        for contribution in (None, {}, {'description': 'Synthetic human edits'},
                             {'evidence_ids': ['synthetic-contribution']}):
            with self.subTest(contribution=contribution):
                rights = copy.deepcopy(self.fixture['rights'])
                rights[0]['human_contribution'] = contribution
                result, issues, _ = software._rights({'scope': scope, 'rights': rights})
                self.assertEqual(result['decisions'][0]['decision'], 'needs_evidence')
                self.assertIn('human_contribution_unknown', {row['code'] for row in issues})

    def test_real_intake_blank_ai_contribution_remains_unknown(self):
        from tools.software_intake import _scope_and_rights
        answers = iter(['Synthetic AI tool', '1.0', 'CLI', 'yes', '', '', '',
                        'ai', 'synthetic-origin', 'Synthetic expression', 'Dependencies',
                        'Synthetic owner', 'Synthetic ownership', 'synthetic-owner', '',
                        'allow', 'allow', 'synthetic-permission'])
        scope_input, rights, _ = _scope_and_rights(lambda _: next(answers))
        self.assertIsNone(rights[0]['human_contribution'])
        scope = software._scope(scope_input)[0]
        result, issues, _ = software._rights({'scope': scope, 'rights': rights})
        self.assertEqual(result['decisions'][0]['decision'], 'needs_evidence')
        self.assertIn('human_contribution_unknown', {row['code'] for row in issues})

    def test_full_blocks_keep_order_and_unconfirmed_source_status(self):
        self.payload['manual_input']['blocks'] = [
            {'id': 'Overview', 'kind': 'heading1', 'text': 'Synthetic overview',
             'evidence_ids': ['synthetic-manual-source'], 'status': 'confirmed'},
            {'id': 'Detail', 'kind': 'paragraph', 'text': 'UNIQUE_COMPLETE_BODY_2317',
             'evidence_ids': [], 'status': 'confirmed'},
        ]
        result = software.prepare(self.payload)
        manual = result['artifacts']['manual']
        self.assertEqual([row['id'] for row in manual['blocks']], ['Overview', 'Detail'])
        self.assertEqual(manual['blocks'][1]['status'], 'needs_review')
        self.assertIn('UNIQUE_COMPLETE_BODY_2317', manual['markdown'])
        self.assertIn('manual_block_needs_review', {row['code'] for row in result['issues']})

    def test_body_change_creates_new_binding_preserving_source_and_original(self):
        self.payload['manual_input']['blocks'] = [
            {'id': 'Detail', 'kind': 'paragraph', 'text': 'First revision',
             'evidence_ids': ['synthetic-body'], 'status': 'confirmed'}]
        before = software.prepare(self.payload)['artifacts']
        old = copy.deepcopy(before)
        changed = copy.deepcopy(self.payload)
        changed['manual_input']['blocks'][0]['text'] = 'Second revision'
        changed['previous_preparation'] = before
        after = software.prepare(changed)['artifacts']
        self.assertEqual(before, old)
        self.assertEqual(after['source']['binding'], before['source']['binding'])
        self.assertNotEqual(after['manual']['binding'], before['manual']['binding'])
        self.assertEqual(after['supersedes'], before['binding'])
        self.assertIn('manual', {row['artifact'] for row in after['changes']})
        repeated = software.prepare({**changed, 'previous_preparation': after})['artifacts']
        self.assertEqual(repeated, after)

    def test_changed_blocks_and_source_require_current_confirmation(self):
        self.payload['manual_input']['blocks'] = [
            {'id': 'Detail', 'kind': 'paragraph', 'text': 'First revision',
             'evidence_ids': ['synthetic-body'], 'status': 'confirmed'},
            {'id': 'Stable', 'kind': 'paragraph', 'text': 'Unchanged explanation',
             'evidence_ids': ['synthetic-body'], 'status': 'confirmed'}]
        before = software.prepare(self.payload)['artifacts']
        changed = copy.deepcopy(self.payload)
        changed['previous_preparation'] = before
        changed['manual_input']['blocks'][0]['text'] = 'Changed expression'
        after = software.prepare(changed)['artifacts']
        self.assertEqual([b['status'] for b in after['manual']['blocks']],
                         ['needs_review', 'confirmed'])
        repeated = software.prepare({**changed, 'previous_preparation': after})['artifacts']
        self.assertEqual(repeated, after)
        reviewed = copy.deepcopy(changed)
        reviewed['previous_preparation'] = after
        reviewed['manual_input']['blocks'][0]['confirmation'] = {
            'input_binding': after['manual']['blocks'][0]['input_binding'],
            'actor': 'Synthetic reviewer', 'role': 'technical_owner',
            'evidence_id': 'synthetic-current-body-review'}
        confirmed = software.prepare(reviewed)['artifacts']
        self.assertEqual(confirmed['manual']['blocks'][0]['status'], 'confirmed')
        reviewed['manual_input']['blocks'][0]['text'] = 'Another change'
        reviewed['previous_preparation'] = confirmed
        stale = software.prepare(reviewed)['artifacts']
        self.assertEqual(stale['manual']['blocks'][0]['status'], 'needs_review')
        (self.root / 'counter.py').write_text(self.fixture['source'] + '\n# changed\n', encoding='utf-8')
        source_changed = software.prepare({**self.payload, 'previous_preparation': before})['artifacts']
        self.assertTrue(all(b['status'] == 'needs_review' for b in source_changed['manual']['blocks']))

    def test_duplicate_blocks_and_metadata_conflict_reject(self):
        block = {'id': 'Duplicate', 'kind': 'paragraph', 'text': 'Synthetic',
                 'evidence_ids': [], 'status': 'needs_review'}
        self.payload['manual_input']['blocks'] = [block, copy.deepcopy(block)]
        with self.assertRaisesRegex(ContractError, 'duplicate_id'):
            software.prepare(self.payload)
        self.payload['manual_input']['blocks'] = [block]
        self.payload['manual_input']['document_metadata'] = {'version': 'OTHER'}
        with self.assertRaisesRegex(ContractError, 'manual_metadata_conflict'):
            software.prepare(self.payload)

    def test_legacy_input_unchanged_and_explicit_empty_blocks_reject(self):
        result = software.prepare(self.payload)['artifacts']['manual']
        self.assertNotIn('blocks', result)
        self.assertIn('命令操作流程', result['markdown'])
        self.payload['manual_input']['blocks'] = []
        with self.assertRaisesRegex(ContractError, 'manual_blocks_required'):
            software.prepare(self.payload)


if __name__ == '__main__':
    unittest.main()
