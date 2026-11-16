"""Real file boundaries and installed-tool integration, with no model/network."""
import concurrent.futures
import copy
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import struct
import subprocess
import sys
import unittest
from unittest import mock
import zlib

from evals.native_host_bridge import BridgeError, NativeHostBridge, MAX_SEGMENT, READ_RESPONSE_BUDGET
from evals.test_fidelity import example as fidelity_fixture
from tools.bundle import build_bundle, MANIFEST_NAME

ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeHostBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.group = tempfile.TemporaryDirectory(prefix='dyz-native-bridge-tests-')
        cls.base = Path(cls.group.name).resolve()
        cls.package = cls.base / 'package'
        build_bundle(cls.package, source_root=ROOT)
        cls.manifest_sha = sha((cls.package / MANIFEST_NAME).read_bytes())

    @classmethod
    def tearDownClass(cls):
        assert cls.package.resolve().is_relative_to(cls.base)
        cls.group.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name).resolve()
        self.work = self.case / 'workspace'
        self.control = self.case / 'control'
        (self.work / 'input').mkdir(parents=True)
        self.control.mkdir()
        self.source = '合成文件工具检查\n实际正文\n仅供内部的备注\n'
        (self.work / 'input/source.md').write_bytes(self.source.encode('utf-8'))
        self.bridge = NativeHostBridge(self.package, self.work, self.control, self.manifest_sha)

    def call(self, tool, **args):
        return self.bridge.call(tool, args)

    def write_json(self, value, path='work/spec.json'):
        answer = self.call('case_write', path=path, text=json.dumps(value, ensure_ascii=False))
        self.assertTrue(answer['success'], answer)
        return path

    def document_spec(self):
        return {'sensitivity': 'synthetic', 'document_id': 'BridgeProbe', 'version': '1', 'business': 'patent',
                'sources': [{'id': 'Source', 'path': 'input/source.md', 'sha256': sha(self.source.encode('utf-8'))}],
                'blocks': [{'id': 'Title', 'kind': 'heading1', 'audience': 'body', 'source_id': 'Source', 'start_line': 1, 'end_line': 1},
                           {'id': 'Body', 'kind': 'paragraph', 'audience': 'body', 'source_id': 'Source', 'start_line': 2, 'end_line': 2},
                           {'id': 'Note', 'kind': 'paragraph', 'audience': 'internal', 'source_id': 'Source', 'start_line': 3, 'end_line': 3}],
                'figures': []}

    def test_paged_utf8_reads_explicit_coverage_and_hash(self):
        first = self.call('case_read', scope='workspace', path='input/source.md', start_line=1, max_lines=2)
        self.assertTrue(first['success'])
        self.assertFalse(first['result']['eof'])
        self.assertEqual([1, 2], [x['number'] for x in first['result']['lines']])
        second = self.call('case_read', scope='workspace', path='input/source.md', start_line=3, max_lines=2)
        self.assertTrue(second['result']['eof'])
        self.assertEqual(sha(self.source.encode()), second['result']['sha256'])

    def test_invalid_ranges_do_not_become_empty_success(self):
        for extra in [{'start_line': 0}, {'start_line': True}, {'start_line': 20}, {'max_lines': 121}, {'max_lines': 0}]:
            with self.subTest(extra=extra):
                self.assertFalse(self.call('case_read', scope='workspace', path='input/source.md', **extra)['success'])

    def test_adapter_next_chunk_returns_exact_coverage_and_budget_without_long_hash_argument(self):
        first = self.call('case_read', scope='workspace', path='input/source.md', max_lines=1)
        second = self.call('case_read', scope='workspace', path='input/source.md', max_lines=1, next_chunk=True)
        self.assertTrue(first['success'], first)
        self.assertTrue(second['success'], second)
        self.assertEqual(2, second['result']['start_line'])
        self.assertEqual(first['result']['sha256'], second['result']['sha256'])
        self.assertEqual('实际正文', second['result']['lines'][0]['text'])
        self.assertEqual(2, second['execution_budget']['tool_calls_used'])
        self.assertNotIn('expected_sha256', self.bridge.calls[1]['arguments'])
        self.assertEqual(second, self.bridge.calls[1]['answer'])

    def test_crlf_source_hash_remains_byte_exact(self):
        raw = self.source.replace('\n', '\r\n').encode('utf-8')
        (self.work / 'input/crlf.md').write_bytes(raw)
        answer = self.call('case_read', scope='workspace', path='input/crlf.md')
        self.assertTrue(answer['success'], answer)
        self.assertEqual(sha(raw), answer['result']['sha256'])
        self.assertNotEqual(sha(self.source.encode('utf-8')), answer['result']['sha256'])
        self.assertEqual(self.source.splitlines(), [r['text'] for r in answer['result']['lines']])

    def test_large_single_line_has_explicit_bounded_fragments_and_exact_reconstruction(self):
        # Keep the former48001-character case, now readable without raising its cap.
        text='a'*48001
        (self.work/'input/long.txt').write_bytes(text.encode())
        args={'scope':'workspace','path':'input/long.txt'};parts=[];positions=[]
        for _ in range(8):
            answer=self.call('case_read',**args);self.assertTrue(answer['success'],answer)
            self.assertLessEqual(len(json.dumps(answer,ensure_ascii=False).encode()),READ_RESPONSE_BUDGET)
            self.assertLessEqual(READ_RESPONSE_BUDGET,MAX_SEGMENT)
            data=answer['result'];parts.extend(x['text'] for x in data['lines']);positions.extend(data['line_fragments'])
            self.assertEqual(data['sha256'],sha(text.encode()))
            if data['eof']:break
            self.assertTrue(data['budget_limited']);self.assertIsNotNone(data['next_position'])
            args={**args,**data['next_position']}
        else:self.fail('bounded reading did not reach EOF')
        self.assertGreater(len(parts),1);self.assertEqual(''.join(parts),text)
        self.assertEqual(positions[0]['from_column'],0);self.assertEqual(positions[-1]['to_column'],len(text))
        self.assertTrue(all(a['to_column']==b['from_column'] for a,b in zip(positions,positions[1:])))

    def test_unicode_json_fragments_preserve_quotes_combining_characters_and_original_crlf_hash(self):
        value={'status':'blocked','text':'汉字🙂e\u0301"\\'*6500,'unknown':None,'tail':'真实尾标'}
        text=json.dumps(value,ensure_ascii=False);raw=(text+'\r\n').encode()
        (self.work/'input/dense.json').write_bytes(raw);args={'scope':'workspace','path':'input/dense.json','max_lines':60};parts=[]
        for _ in range(12):
            answer=self.call('case_read',**args);self.assertTrue(answer['success'],answer)
            self.assertLessEqual(len(json.dumps(answer,ensure_ascii=False).encode()),READ_RESPONSE_BUDGET)
            data=answer['result'];self.assertEqual(data['sha256'],sha(raw));parts.extend(x['text'] for x in data['lines'])
            if data['eof']:break
            args={**args,**data['next_position']}
        else:self.fail('Unicode JSON did not reach EOF')
        self.assertEqual(''.join(parts),text);self.assertEqual(json.loads(''.join(parts)),value)

    def test_fragment_continuation_requires_current_hash_and_valid_codepoint_column(self):
        (self.work/'input/long.txt').write_bytes(b'x'*48001)
        first=self.call('case_read',scope='workspace',path='input/long.txt')['result'];position=first['next_position']
        missing={k:v for k,v in position.items() if k!='expected_sha256'}
        self.assertEqual(self.call('case_read',scope='workspace',path='input/long.txt',**missing)['error'],'fragment_source_hash_required')
        self.assertEqual(self.call('case_read',scope='workspace',path='input/long.txt',**{**position,'expected_sha256':'0'*64})['error'],'source_version_changed')
        for column in [-1,True,48001]:
            self.assertEqual(self.call('case_read',scope='workspace',path='input/long.txt',start_column=column)['error'],'invalid_column_range')
        (self.work/'input/empty.txt').write_bytes(b'')
        empty=self.call('case_read',scope='workspace',path='input/empty.txt')['result']
        self.assertTrue(empty['eof']);self.assertEqual(empty['total_lines'],0);self.assertEqual(empty['line_fragments'],[])

    def test_traversal_absolute_ads_and_alias_segments_are_rejected(self):
        for path in ['../control/log.json', 'C:/Windows/win.ini', '/etc/passwd', 'input/source.md:secret', 'input/../source.md', 'input//source.md', 'input/./source.md', 'input/.hidden', 'input/']:
            with self.subTest(path=path):
                self.assertFalse(self.call('case_read', scope='workspace', path=path)['success'])

    def test_frozen_package_read_and_hash(self):
        answer = self.call('case_read', scope='package', path='skills/dyz-patent/SKILL.md', max_lines=8)
        self.assertTrue(answer['success'], answer)
        self.assertEqual(sha((self.package / 'skills/dyz-patent/SKILL.md').read_bytes()), answer['result']['sha256'])

    def test_unlisted_package_file_is_not_read(self):
        path = self.package / 'not-listed.txt'
        path.write_text('not allowed', encoding='utf-8')
        try:
            answer = self.call('case_read', scope='package', path=path.name)
            self.assertEqual('package_path_not_allowed', answer['error'])
            self.assertNotIn('result', answer)
        finally:
            path.unlink()

    def test_changed_package_bytes_are_not_returned(self):
        path = self.package / 'README.md'
        old = path.read_bytes()
        try:
            path.write_bytes(b'!' + old[1:])
            answer = self.call('case_read', scope='package', path='README.md')
            self.assertEqual('package_file_changed', answer['error'])
        finally:
            path.write_bytes(old)

    def test_control_and_workspace_root_files_are_not_visible(self):
        (self.work / 'controller.txt').write_text('synthetic controller marker', encoding='utf-8')
        answer = self.call('case_read', scope='workspace', path='controller.txt')
        self.assertEqual('workspace_path_not_allowed', answer['error'])

    def test_create_refuses_overwrite(self):
        self.assertTrue(self.call('case_write', path='work/draft.md', text='first')['success'])
        answer = self.call('case_write', path='work/draft.md', text='second')
        self.assertEqual('destination_exists', answer['error'])
        self.assertEqual('first', (self.work / 'work/draft.md').read_text())

    def test_hash_bound_update_keeps_preimage(self):
        self.call('case_write', path='work/draft.md', text='first')
        answer = self.call('case_write', path='work/draft.md', text='second', expected_sha256=sha(b'first'))
        self.assertTrue(answer['success'], answer)
        self.assertEqual(b'first', (self.control / 'write-0002.before').read_bytes())
        self.assertEqual('second', (self.work / 'work/draft.md').read_text())

    def test_stale_update_preserves_current_file(self):
        self.call('case_write', path='work/draft.md', text='first')
        answer = self.call('case_write', path='work/draft.md', text='second', expected_sha256='0' * 64)
        self.assertEqual('source_version_changed', answer['error'])
        self.assertEqual(b'first', (self.work / 'work/draft.md').read_bytes())
        self.assertEqual([], list(self.control.glob('*.before')))

    def test_input_and_package_cannot_be_written(self):
        self.assertFalse(self.call('case_write', path='input/source.md', text='changed')['success'])
        self.assertFalse(self.call('case_write', path='../package/README.md', text='changed')['success'])
        self.assertEqual(self.source, (self.work / 'input/source.md').read_text(encoding='utf-8'))

    def test_hardlinked_input_is_rejected_without_content(self):
        alias = self.work / 'input/alias.md'
        os.link(self.work / 'input/source.md', alias)
        answer = self.call('case_read', scope='workspace', path='input/alias.md')
        self.assertEqual('nonregular_or_aliased_file', answer['error'])
        self.assertNotIn('result', answer)

    def test_call_limit_is_enforced(self):
        self.bridge.max_calls = 1
        self.assertTrue(self.call('case_info', scope='workspace', path='input/source.md')['success'])
        self.assertEqual('tool_call_limit', self.call('case_info', scope='workspace', path='input/source.md')['error'])
        self.assertEqual(1, len(self.bridge.calls))

    def test_budget_counts_success_and_registered_failure_without_reset(self):
        self.bridge.max_calls = 3
        first = self.call('case_info', scope='workspace', path='input/source.md')
        failed = self.call('case_read', scope='workspace', path='input/source.md', start_line=0)
        last = self.call('case_write', path='work/handoff.md', text='actual local handoff')
        self.assertTrue(first['success'])
        self.assertFalse(failed['success'])
        self.assertEqual('invalid_line_range', failed['error'])
        self.assertTrue(last['success'])
        for used, answer in enumerate([first, failed, last], 1):
            self.assertEqual({'max_tool_calls': 3, 'tool_calls_used': used,
                              'tool_calls_remaining': 3 - used}, answer['execution_budget'])
            saved = json.loads((self.control / f'call-{used:04}.json').read_text(encoding='utf-8'))
            self.assertEqual(answer, saved['answer'])

    def test_last_budget_slot_writes_handoff_and_exhaustion_cannot_mutate(self):
        self.bridge.max_calls = 2
        self.call('case_info', scope='workspace', path='input/source.md')
        last = self.call('case_write', path='work/handoff.md', text='keep this handoff')
        self.assertTrue(last['success'])
        self.assertEqual(0, last['execution_budget']['tool_calls_remaining'])
        denied = self.call('case_write', path='work/after-limit.md', text='must not be written')
        self.assertFalse(denied['success'])
        self.assertEqual('tool_call_limit', denied['error'])
        self.assertEqual(last['execution_budget'], denied['execution_budget'])
        self.assertFalse((self.work / 'work/after-limit.md').exists())
        self.assertEqual('keep this handoff', (self.work / 'work/handoff.md').read_text())
        self.assertEqual(2, len(self.bridge.calls))
        self.assertEqual(2, len(list(self.control.glob('call-*.json'))))

    def test_native_budget_is_persisted_and_cannot_be_supplied_as_an_argument(self):
        self.bridge.max_calls = 2
        params = {'arguments': {'scope': 'workspace', 'path': 'input/source.md'},
                  'callId': 'budget-one', 'threadId': 'thread-one', 'tool': 'case_info', 'turnId': 'turn-one'}
        native = self.bridge.native_tool_result(params, thread_id='thread-one', turn_id='turn-one')
        payload = json.loads(native['contentItems'][0]['text'])
        saved = json.loads((self.control / 'call-0001.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['answer'], payload)
        self.assertEqual(1, payload['execution_budget']['tool_calls_remaining'])
        denied = self.call('case_info', scope='workspace', path='input/source.md',
                           execution_budget={'max_tool_calls': 10000, 'tool_calls_remaining': 9999})
        self.assertFalse(denied['success'])
        self.assertEqual('invalid_arguments', denied['error'])
        self.assertEqual({'max_tool_calls': 2, 'tool_calls_used': 2,
                          'tool_calls_remaining': 0}, denied['execution_budget'])
        self.assertEqual(2, self.bridge.max_calls)

    def test_concurrent_budget_is_monotonic_and_exhausted_calls_do_not_create_files(self):
        self.bridge.max_calls = 3
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(lambda n: self.call('case_write', path=f'work/budget-{n}.md', text=str(n)), range(8)))
        successful = [answer for answer in answers if answer['success']]
        denied = [answer for answer in answers if not answer['success']]
        self.assertEqual(3, len(successful))
        self.assertEqual([1, 2, 3], sorted(a['execution_budget']['tool_calls_used'] for a in successful))
        self.assertEqual([0, 1, 2], sorted(a['execution_budget']['tool_calls_remaining'] for a in successful))
        self.assertTrue(all(a['error'] == 'tool_call_limit' and a['execution_budget']['tool_calls_used'] == 3
                            and a['execution_budget']['tool_calls_remaining'] == 0 for a in denied))
        self.assertEqual(3, len(list((self.work / 'work').glob('budget-*.md'))))
        self.assertEqual(3, len(self.bridge.calls))

    def test_concurrent_create_has_one_winner(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(lambda text: self.call('case_write', path='work/concurrent.md', text=text), ['a', 'b']))
        self.assertEqual(1, sum(x['success'] for x in answers))
        self.assertIn((self.work / 'work/concurrent.md').read_text(), ['a', 'b'])

    def test_copy_is_hash_bound_and_exclusive(self):
        info = self.call('case_info', scope='workspace', path='input/source.md')['result']
        self.assertTrue(self.call('case_copy', scope='workspace', path='input/source.md', destination='work/copy.md', expected_sha256=info['sha256'])['success'])
        self.assertEqual((self.work / 'input/source.md').read_bytes(), (self.work / 'work/copy.md').read_bytes())
        answer = self.call('case_copy', scope='workspace', path='input/source.md', destination='work/copy2.md', expected_sha256='0' * 64)
        self.assertFalse(answer['success'])
        self.assertFalse((self.work / 'work/copy2.md').exists())

    def test_binary_files_cannot_be_created_as_text(self):
        for suffix in ['.docx', '.png', '.pdf', '.exe', '.ps1']:
            self.assertFalse(self.call('case_write', path='output/fake' + suffix, text='fake')['success'])

    def test_non_png_is_not_returned_as_an_image(self):
        self.assertEqual('bounded_png_required', self.call('case_image', scope='workspace', path='input/source.md')['error'])

    def test_installed_document_generation_verification_and_readback(self):
        source = self.write_json(self.document_spec())
        built = self.call('case_documents', input=source, output='output/doc-package', mode='synthetic')
        self.assertTrue(built['success'], built)
        self.assertTrue(self.call('case_documents', input=source, output='output/doc-package', mode='synthetic', verify=True)['success'])
        answer = self.call('case_docx_review', input='output/doc-package/body/document.docx', output='output/readback.json', mode='synthetic')
        self.assertTrue(answer['success'], answer)
        report = json.loads((self.work / 'output/readback.json').read_bytes())
        self.assertEqual('needs_review', report['status'])
        self.assertEqual('complete_supported_subset', report['current']['readback_state'])
        self.assertEqual('not_performed', report['professional_review'])
        for path in self.control.glob('*.audit.json'):
            audit = json.loads(path.read_bytes())
            self.assertFalse(audit['blocked'])
            self.assertTrue(all(Path(p).is_relative_to(self.package) for p in audit['loaded_tools_modules'].values()))
        self.assertEqual('仅供内部的备注\n', (self.work / 'output/doc-package/internal/notes.txt').read_text(encoding='utf-8'))

    def test_recipe_json_is_not_an_optional_docx_baseline(self):
        source = self.write_json(self.document_spec())
        built = self.call('case_documents', input=source, output='output/doc-package', mode='synthetic')
        self.assertTrue(built['success'], built)
        jobs = {p.name for p in self.control.glob('*.job.json')}
        with mock.patch('tools.host_bridge.subprocess.Popen', side_effect=AssertionError('invalid baseline must not launch worker')) as launch:
            answer = self.call('case_docx_review', input='output/doc-package/body/document.docx',
                output='output/rejected-readback.json', baseline=source, mode='synthetic')
            self.assertFalse(answer['success'])
            self.assertEqual(answer['error'], 'baseline_docx_required')
            launch.assert_not_called()
        self.assertEqual(jobs, {p.name for p in self.control.glob('*.job.json')})
        self.assertFalse((self.work / 'output/rejected-readback.json').exists())

    def test_invalid_recipe_is_a_tool_rejection_not_a_boundary_failure(self):
        source = self.write_json({})
        answer = self.call('case_documents', input=source, output='output/rejected', mode='synthetic')
        self.assertFalse(answer['success'])
        self.assertEqual(2, answer['result']['exit_code'])
        self.assertFalse((self.work / 'output/rejected').exists())

    def test_old_recipe_binding_is_typed_false_and_matches_actual_installed_cli(self):
        old = self.write_json(self.document_spec(), 'work/old.json')
        changed = self.document_spec()
        changed['version'] = '2'
        current = self.write_json(changed, 'work/current.json')
        target = 'output/versioned'
        self.assertTrue(self.call('case_documents', input=current, output=target, mode='synthetic')['success'])
        before = {p.relative_to(self.work).as_posix():sha(p.read_bytes()) for p in self.work.rglob('*') if p.is_file()}
        for source, expected_success in [(current, True), (old, False)]:
            with self.subTest(source=source):
                answer = self.call('case_documents', input=source, output=target, mode='synthetic', verify=True)
                self.assertEqual(expected_success, answer['success'])
                cli = subprocess.run([sys.executable, '-I', '-S', '-B', '-X', 'utf8', '-c',
                    'import sys;sys.path.insert(0,sys.argv[1]);from tools.documents import main;sys.exit(main(sys.argv[2:]))',
                    str(self.package), '--synthetic', '--root', str(self.work), '--input', source,
                    '--output', target, '--verify'], capture_output=True, timeout=30)
                self.assertEqual(cli.returncode, answer['result']['exit_code'])
                self.assertEqual(cli.stdout.decode('utf-8'), answer['result']['stdout'])
                self.assertEqual(cli.stderr.decode('utf-8'), answer['result']['stderr'])
                if expected_success:
                    self.assertEqual('needs_review', answer['result']['review_status'])
                    self.assertNotIn('error', answer)
                else:
                    self.assertEqual('document_input_binding_changed', answer['error'])
                    self.assertEqual(answer['error'], answer['result']['contract_error'])
                    audit = json.loads(max(self.control.glob('*.audit.json')).read_bytes())
                    self.assertEqual(answer['error'], audit['contract_error'])
                    self.assertIsNone(audit['unexpected_exception'])
                    self.assertFalse(audit['blocked'])
                    self.assertEqual(self.package / 'tools/documents.py', Path(audit['loaded_tools_modules']['tools.documents']))
        after = {p.relative_to(self.work).as_posix():sha(p.read_bytes()) for p in self.work.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_corruption_malformed_input_and_io_do_not_inherit_binding_error(self):
        source = self.write_json(self.document_spec())
        target = 'output/damaged'
        self.assertTrue(self.call('case_documents', input=source, output=target, mode='synthetic')['success'])
        body = self.work / target / 'body/source.txt'
        body.write_text('changed', encoding='utf-8')
        damaged = self.call('case_documents', input=source, output=target, mode='synthetic', verify=True)
        self.assertFalse(damaged['success'])
        self.assertEqual(2, damaged['result']['exit_code'])
        self.assertNotIn('error', damaged)
        malformed = self.write_json({}, 'work/malformed.json')
        rejected = self.call('case_documents', input=malformed, output=target, mode='synthetic', verify=True)
        self.assertFalse(rejected['success'])
        self.assertEqual(2, rejected['result']['exit_code'])
        self.assertNotIn('error', rejected)
        (self.work / target / 'manifest.json').unlink()
        missing = self.call('case_documents', input=source, output=target, mode='synthetic', verify=True)
        self.assertFalse(missing['success'])
        self.assertEqual(3, missing['result']['exit_code'])
        self.assertNotIn('error', missing)
        self.assertNotIn('contract_error', missing['result'])

    def test_fidelity_status_does_not_become_a_professional_pass(self):
        value = fidelity_fixture()
        source = self.write_json(value, 'work/fidelity.json')
        answer = self.call('case_fidelity', input=source, output='output/fidelity.json', mode='synthetic')
        self.assertTrue(answer['success'], answer)
        report = json.loads((self.work / 'output/fidelity.json').read_bytes())
        self.assertEqual('checked', report['status'])
        self.assertFalse(report['natural_language_verified'])
        changed = copy.deepcopy(value)
        changed['assertions'][0]['formula'] = {'implies': ['permission', 'release']}
        source = self.write_json(changed, 'work/reverse.json')
        answer = self.call('case_fidelity', input=source, output='output/reverse.json', mode='synthetic')
        self.assertTrue(answer['success'], answer)
        self.assertEqual('blocked', json.loads((self.work / 'output/reverse.json').read_bytes())['status'])

    def test_unsupported_research_fidelity_has_no_worker_job(self):
        source = self.write_json(fidelity_fixture())
        answer = self.call('case_fidelity', input=source, output='output/rejected.json', mode='research_example')
        self.assertEqual('synthetic_only', answer['error'])
        self.assertEqual([], list(self.control.glob('*.job.json')))

    def test_output_root_and_freeform_flags_are_rejected(self):
        source = self.write_json(self.document_spec())
        answer = self.call('case_documents', input=source, output='work/out', mode='synthetic')
        self.assertEqual('output_root_required', answer['error'])
        answer = self.call('case_documents', input=source, output='output/out', mode='synthetic', pdf_tool='unapproved')
        self.assertEqual('invalid_arguments', answer['error'])
        self.assertEqual('unknown_tool', self.call('exec_command', cmd='whoami')['error'])

    def test_control_root_cannot_overlap_case_root(self):
        nested = self.work / 'nested-control'
        nested.mkdir()
        with self.assertRaises(BridgeError):
            NativeHostBridge(self.package, self.work, nested, self.manifest_sha)

    def native_params(self, tool, arguments, **overrides):
        return {'arguments': arguments, 'callId': 'call-one', 'threadId': 'thread-one',
                'turnId': 'turn-one', 'tool': tool, **overrides}

    def test_native_result_matches_current_schema_and_actual_read(self):
        params = self.native_params('case_read', {'scope': 'workspace', 'path': 'input/source.md'})
        result = self.bridge.native_tool_result(params, thread_id='thread-one', turn_id='turn-one')
        self.assertEqual({'success', 'contentItems'}, set(result))
        self.assertTrue(result['success'])
        self.assertEqual('inputText', result['contentItems'][0]['type'])
        payload = json.loads(result['contentItems'][0]['text'])
        self.assertEqual(sha(self.source.encode()), payload['result']['sha256'])

    def test_native_wrong_session_cannot_read_or_write(self):
        for overrides in [{'threadId': 'other-thread'}, {'turnId': 'other-turn'}]:
            params = self.native_params('case_write', {'path': 'work/not-written.md', 'text': 'unexpected'}, **overrides)
            result = self.bridge.native_tool_result(params, thread_id='thread-one', turn_id='turn-one')
            self.assertFalse(result['success'])
            self.assertEqual('native_session_mismatch', json.loads(result['contentItems'][0]['text'])['error'])
        self.assertFalse((self.work / 'work/not-written.md').exists())
        self.assertEqual([], self.bridge.calls)

    def test_native_image_is_separate_content_not_duplicate_text(self):
        image = next(self.package.rglob('*.png'))
        params = self.native_params('case_image', {'scope': 'package', 'path': image.relative_to(self.package).as_posix()})
        result = self.bridge.native_tool_result(params, thread_id='thread-one', turn_id='turn-one')
        self.assertTrue(result['success'], result)
        self.assertEqual(['inputText', 'inputImage'], [x['type'] for x in result['contentItems']])
        self.assertTrue(result['contentItems'][1]['imageUrl'].startswith('data:image/png;base64,'))
        self.assertNotIn('image_data_url', result['contentItems'][0]['text'])
        metadata=json.loads(result['contentItems'][0]['text'])['result']
        actual=image.read_bytes()
        self.assertEqual(metadata['width'],int.from_bytes(actual[16:20],'big'))
        self.assertEqual(metadata['height'],int.from_bytes(actual[20:24],'big'))

    def prepared_view_fixture(self):
        def png(width,height):
            def chunk(kind,raw):return struct.pack('>I',len(raw))+kind+raw+struct.pack('>I',zlib.crc32(kind+raw)&0xffffffff)
            scan=b''.join(b'\x00'+b'\xff\x00\x00'*width for _ in range(height))
            return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b'')
        source,view=png(32,64),png(16,32)
        (self.work/'input/original.png').write_bytes(source)
        path=self.control/'approved-view.png';path.write_bytes(view)
        policy={'source_sha256':sha(source),'source_width':32,'source_height':64,'view_sha256':sha(view),'view_width':16,'view_height':32,
                'view_path':str(path),'provenance':'codex-0.160.1-high-detail-prepared_observed'}
        return source,view,policy

    def test_explicit_frozen_view_retains_original_identity_and_exact_view_content(self):
        source,view,policy=self.prepared_view_fixture()
        bridge=NativeHostBridge(self.package,self.work,self.control,self.manifest_sha,image_views=[policy])
        params=self.native_params('case_image',{'scope':'workspace','path':'input/original.png'})
        result=bridge.native_tool_result(params,thread_id='thread-one',turn_id='turn-one')
        self.assertTrue(result['success'],result)
        metadata=json.loads(result['contentItems'][0]['text'])['result']
        self.assertEqual((metadata['sha256'],metadata['width'],metadata['height']),(sha(source),32,64))
        self.assertEqual(metadata['image_view']['sha256'],sha(view))
        self.assertFalse(metadata['image_view']['original_resolution_bytes_in_image_content'])
        actual=base64.b64decode(result['contentItems'][1]['imageUrl'].split(',',1)[1])
        self.assertEqual(actual,view);self.assertNotEqual(actual,source)
        self.assertEqual((self.work/'input/original.png').read_bytes(),source)

    def test_changed_unreviewed_or_outside_control_view_is_rejected(self):
        _,_,policy=self.prepared_view_fixture()
        for changed in [{**policy,'view_sha256':'0'*64},{**policy,'view_width':20000},
                        {**policy,'source_sha256':'invalid'},{**policy,'provenance':'guessed'},
                        {**policy,'view_path':str(self.work/'input/original.png')},
                        {**policy,'view_height':True}]:
            with self.subTest(changed=changed),self.assertRaises(BridgeError):
                NativeHostBridge(self.package,self.work,self.control,self.manifest_sha,image_views=[changed])
        with self.assertRaisesRegex(BridgeError,'duplicate_image_view_source'):
            NativeHostBridge(self.package,self.work,self.control,self.manifest_sha,image_views=[policy,policy])

    def test_native_fidelity_blocked_status_is_explicit(self):
        value = fidelity_fixture()
        value['assertions'][0]['formula'] = {'implies': ['permission', 'release']}
        path = self.write_json(value)
        params = self.native_params('case_fidelity', {'input': path, 'output': 'output/blocked.json', 'mode': 'synthetic'})
        result = self.bridge.native_tool_result(params, thread_id='thread-one', turn_id='turn-one')
        self.assertTrue(result['success'])  # The operation ran; its formal audit is blocked.
        payload = json.loads(result['contentItems'][0]['text'])['result']
        self.assertEqual('blocked', payload['review_status'])
        self.assertFalse(payload['report_summary']['natural_language_verified'])


if __name__ == '__main__':
    unittest.main()
