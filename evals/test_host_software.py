"""软件宿主schema/NDJSON/隔离worker合成验证；无网络、模型或Office。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tools import cli, core
from tools.bundle import MANIFEST_NAME, build_bundle
from tools.host_bridge import HostToolBridge, dynamic_tools
from evals import test_software_intake as intake_fixtures

ROOT = Path(__file__).resolve().parents[1]
BASE_PYTHON = getattr(sys, '_base_executable', None) or sys.executable


class HostSoftwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='dyz-host-software-')
        cls.base = Path(cls.temporary.name).resolve()
        cls.package = cls.base / 'package'
        build_bundle(cls.package, source_root=ROOT)
        cls.manifest = core.sha256_bytes((cls.package / MANIFEST_NAME).read_bytes())

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.temporary_case = tempfile.TemporaryDirectory(prefix='case-', dir=self.base)
        self.addCleanup(self.temporary_case.cleanup)
        self.case = Path(self.temporary_case.name)
        self.workspace, self.control = self.case / 'workspace', self.case / 'control'
        (self.workspace / 'input').mkdir(parents=True)
        self.control.mkdir()
        self.bridge = HostToolBridge(self.package, self.workspace, self.control, self.manifest)
        fixture = json.loads((ROOT / 'evals/fixtures/software/synthetic.json').read_bytes())
        self.marker = 'SYNTHETIC_SOURCE_SECRET_NOT_FOR_TOOL_REPLY'
        self.source = (fixture['source'] + '# ' + self.marker + '\n').encode()
        (self.workspace / 'input/counter.py').write_bytes(self.source)
        self.request = {key: copy.deepcopy(fixture[key]) for key in
                        ('scope_input', 'rights', 'pagination', 'manual_input')}
        self.request.update(files=[{'id': 'f1', 'path': 'input/counter.py', 'component_id': 'cli',
                                  'kind': 'source', 'include': True}], inventory_complete=True,
                            form_rule_evidence='synthetic-rule')
        now = datetime.now(timezone.utc)
        permission = {'purpose': 'software_internal_preparation', 'recipient': 'local_tool',
                      'decision': 'allow', 'authority_evidence': 'synthetic-private-authority',
                      'valid_from': (now - timedelta(days=1)).isoformat(),
                      'valid_until': (now + timedelta(days=1)).isoformat()}
        self.authorization = {
            'kind': 'software_local_authorization', 'authorized_root': str(self.workspace),
            'context': {'sensitivity': 'synthetic', 'purpose': permission['purpose'],
                        'environment': {}, 'permissions': [{**permission, 'action': action}
                            for action in ('local_read', 'local_write')]},
            'request': {'path': 'input/request.json', 'sha256': ''},
            'files': [{'path': 'input/counter.py', 'sha256': core.sha256_bytes(self.source)}],
            'output': 'output/prepared.json'}

    def arguments(self, action='prepare'):
        request = core.canonical_bytes(self.request)
        (self.workspace / 'input/request.json').write_bytes(request)
        self.authorization['request']['sha256'] = core.sha256_bytes(request)
        authorization = core.canonical_bytes(self.authorization)
        (self.workspace / 'input/authorization.json').write_bytes(authorization)
        return {'action': action, 'authorization': 'input/authorization.json',
                'authorization_sha256': core.sha256_bytes(authorization)}

    def audit(self):
        ordinal = len(self.bridge.calls)
        return json.loads((self.control / f'tool-{ordinal:04}.audit.json').read_bytes())

    def invoke_cli(self, arguments):
        argv = ['prepare-software' if arguments['action'] == 'prepare' else 'build-software',
                '--root', str(self.workspace), '--authorization', arguments['authorization'],
                '--authorization-sha256', arguments['authorization_sha256']]
        if arguments['action'] == 'verify':
            argv.append('--verify')
        return subprocess.run([BASE_PYTHON, '-B', '-m', 'tools', *argv], cwd=self.package,
                              capture_output=True, timeout=30)

    def assert_no_material_reads(self):
        material = self.workspace / 'input/counter.py'
        proof = self.audit()
        self.assertEqual([], proof['blocked'])
        self.assertFalse(any(Path(row['path']) == material for row in proof['file_open_events']))
        self.assertNotIn(self.marker, json.dumps(proof))

    def test_schema_and_copied_ndjson_prepare_are_real(self):
        schemas = dynamic_tools()
        spec = next(item for item in schemas if item['name'] == 'case_software')
        self.assertEqual(['action'], spec['inputSchema']['required'])
        self.assertEqual(['prepare', 'build', 'verify', 'intake'],
                         spec['inputSchema']['properties']['action']['enum'])
        self.assertFalse(spec['inputSchema']['additionalProperties'])
        args = self.arguments()
        process = subprocess.run([BASE_PYTHON, '-I', '-S', '-B', '-X', 'utf8',
            str(self.package / 'tools/host_bridge.py'), '--package', str(self.package),
            '--workspace', str(self.workspace), '--control', str(self.control),
            '--manifest-sha256', self.manifest], cwd=self.case,
            input=(json.dumps({'id': '1', 'tool': 'case_software', 'arguments': args}) + '\n').encode(),
            capture_output=True, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        answer = json.loads(process.stdout)['answer']
        self.assertTrue(answer['success'], answer)
        self.assertNotIn(self.marker.encode(), process.stdout)
        self.assertEqual('output/prepared.json', answer['result']['report_summary']['files'][0]['path'])
        proof = json.loads((self.control / 'tool-0001.audit.json').read_bytes())
        self.assertEqual([], proof['blocked'])
        self.assertEqual(str(self.package / 'tools/software.py'), proof['loaded_tools_modules']['tools.software'])

    def test_prepare_matches_actual_copied_cli_bytes_and_hides_material(self):
        args = self.arguments()
        answer = self.bridge.call('case_software', args)
        self.assertTrue(answer['success'], answer)
        output = self.workspace / self.authorization['output']
        first = output.read_bytes()
        self.assertIn(self.marker.encode(), first)
        output.unlink()
        process = self.invoke_cli(args)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual(first, output.read_bytes())
        wire = json.dumps(answer)
        self.assertNotIn(self.marker, wire)
        self.assertNotIn('synthetic-private-authority', wire)
        self.assertNotIn('permissions', wire)
        self.assertEqual('', answer['result']['stdout'])
        row = answer['result']['report_summary']['files'][0]
        self.assertEqual(core.sha256_bytes(first), row['sha256'])
        for receipt in self.control.glob('call-*.json'):
            self.assertNotIn(self.marker.encode(), receipt.read_bytes())

    def test_build_verify_match_cli_partial_and_do_not_mutate_on_verify(self):
        full_body = 'SYNTHETIC_FULL_MANUAL_BODY_内容顺序不得丢失'
        self.request['manual_input']['blocks'] = [
            {'id': 'Overview', 'kind': 'heading1', 'text': '完整正文标题',
             'evidence_ids': ['synthetic-manual'], 'status': 'confirmed'},
            {'id': 'Detail', 'kind': 'paragraph', 'text': full_body,
             'evidence_ids': ['synthetic-manual'], 'status': 'needs_review'},
        ]
        self.request['delivery'] = {'selection': 'all', 'screenshots': [], 'sensitive_literals': []}
        self.authorization['output'] = 'output/documents'
        args = self.arguments('build')
        answer = self.bridge.call('case_software', args)
        self.assertFalse(answer['success'], answer)
        self.assertEqual(4, answer['result']['exit_code'])
        self.assertEqual('partial', answer['result']['review_status'])
        target = self.workspace / self.authorization['output']
        before = {path.relative_to(target).as_posix(): path.read_bytes()
                  for path in target.rglob('*') if path.is_file()}
        self.assertIn('body/source.docx', before)
        self.assertIn('body/manual.docx', before)
        self.assertIn(full_body, before['body/manual.txt'].decode())
        self.assertNotIn(full_body, json.dumps(answer))
        self.assertFalse(any(name.endswith('.pdf') for name in before))
        verified = self.bridge.call('case_software', {**args, 'action': 'verify'})
        self.assertEqual(4, verified['result']['exit_code'], verified)
        self.assertEqual('partial', verified['result']['report_summary']['status'])
        cli_verify = self.invoke_cli({**args, 'action': 'verify'})
        self.assertEqual(4, cli_verify.returncode, cli_verify.stderr)
        self.assertEqual(before, {path.relative_to(target).as_posix(): path.read_bytes()
                         for path in target.rglob('*') if path.is_file()})
        # 同一输入另一个新目录：授权仅换输出，不改变业务准备及成品内容。
        self.authorization['output'] = 'output/cli-documents'
        cli_build = self.invoke_cli(self.arguments('build'))
        self.assertEqual(4, cli_build.returncode, cli_build.stderr)
        other = self.workspace / self.authorization['output']
        self.assertEqual(before, {path.relative_to(other).as_posix(): path.read_bytes()
                         for path in other.rglob('*') if path.is_file()})
        self.assertNotIn(self.marker, json.dumps(answer))

    def test_local_permission_rejections_precede_request_and_material_and_match_lower_layer(self):
        original = copy.deepcopy(self.authorization)
        for value in ('deny', 'unknown', 'no_evidence', 'expired'):
            with self.subTest(value=value):
                self.authorization = copy.deepcopy(original)
                permission = self.authorization['context']['permissions'][0]
                if value == 'no_evidence':
                    permission['authority_evidence'] = ''
                elif value == 'expired':
                    permission['valid_until'] = '2000-01-01T00:00:00Z'
                else:
                    permission['decision'] = value
                args = self.arguments()
                answer = self.bridge.call('case_software', args)
                self.assertEqual('permission_not_proven', answer['error'], answer)
                self.assert_no_material_reads()
                self.assertFalse(any(Path(row['path']).name == 'request.json'
                                     for row in self.audit()['file_open_events']))
                namespace = type('Args', (), {'root': str(self.workspace),
                    'authorization': args['authorization'],
                    'authorization_sha256': args['authorization_sha256']})()
                with self.assertRaises(core.ContractError) as caught:
                    cli._prepare_software(namespace)
                self.assertEqual(answer['error'], str(caught.exception))
                self.assertEqual(2, self.invoke_cli(args).returncode)

    def test_component_material_denied_unknown_or_without_evidence_never_reads_source(self):
        original = copy.deepcopy(self.request['rights'])
        for value in ('deny', 'unknown', 'no_evidence'):
            with self.subTest(value=value):
                self.request['rights'] = copy.deepcopy(original)
                if value == 'no_evidence':
                    self.request['rights'][0]['evidence_ids'] = []
                else:
                    self.request['rights'][0]['permissions']['local_process'] = value
                args = self.arguments()
                answer = self.bridge.call('case_software', args)
                self.assert_no_material_reads()
                self.assertEqual('partial', answer['result']['review_status'], answer)
                output = self.workspace / self.authorization['output']
                before = output.read_bytes()
                self.assertNotIn(self.marker.encode(), before)
                output.unlink()
                process = self.invoke_cli(args)
                self.assertEqual(0, process.returncode, process.stderr)
                self.assertEqual(before, output.read_bytes())
                output.unlink()

    def test_confidential_unknown_paths_reject_before_request_and_source(self):
        self.authorization['context'].update(sensitivity='confidential', environment={
            'assessment_evidence': 'synthetic-assessment', 'data_paths': [
                {'id': name, 'verified': True, 'mode': 'unknown', 'evidence': 'synthetic'}
                for name in ('host_model', 'index', 'telemetry', 'tools', 'logs', 'subprocess')]})
        answer = self.bridge.call('case_software', self.arguments())
        self.assertEqual('data_path_mode_unknown', answer['error'], answer)
        self.assert_no_material_reads()

    def test_hash_and_material_scope_rejections_use_fixed_diagnostics(self):
        args = self.arguments()
        answer = self.bridge.call('case_software', {**args, 'authorization_sha256': '0' * 64})
        self.assertEqual('input_snapshot_mismatch', answer['error'])
        self.assert_no_material_reads()
        self.authorization['files'][0]['path'] = '../outside.py'
        answer = self.bridge.call('case_software', self.arguments())
        self.assertEqual('unsafe_path', answer['error'], answer)
        self.assert_no_material_reads()

    def test_embedded_output_and_request_cannot_escape_case_or_write_input(self):
        for field, value, code in [('output', 'input/bad.json', 'output_root_required'),
                                  ('output', '../bad.json', 'unsafe_path'),
                                  ('request', '../request.json', 'unsafe_path')]:
            with self.subTest(field=field, value=value):
                old = copy.deepcopy(self.authorization)
                if field == 'request':
                    self.authorization['request']['path'] = value
                else:
                    self.authorization['output'] = value
                answer = self.bridge.call('case_software', self.arguments())
                self.assertEqual(code, answer['error'], answer)
                self.assert_no_material_reads()
                self.authorization = old

    def test_bad_arguments_reject_before_worker_and_formal_permission_cannot_be_injected(self):
        for extra, expected in [({'root': '..'}, 'software_case_root_required'),
                                ({'pdf_tool': 'soffice'}, 'invalid_arguments'),
                                ({'context': {'permissions': ['allow']}}, 'invalid_arguments'),
                                ({'action': 'submit'}, 'software_action_invalid')]:
            with self.subTest(extra=extra), mock.patch('tools.host_bridge.subprocess.Popen') as launch:
                answer = self.bridge.call('case_software', {**self.arguments(), **extra})
                self.assertEqual(expected, answer['error'], answer)
                launch.assert_not_called()

    def intake_answers(self, **kwargs):
        helper = intake_fixtures.SoftwareIntakeTests()
        helper.now = datetime.now(timezone.utc)
        return helper.answers(files=['input/counter.py'], **kwargs).values

    def test_candidate_intake_real_prefix_returns_next_question_without_material_reads(self):
        schema = next(item for item in dynamic_tools() if item['name'] == 'case_software')
        self.assertEqual('boolean', schema['inputSchema']['properties']['candidates']['type'])
        args = {'action': 'intake', 'output': 'output/candidates', 'candidates': True}
        first = self.bridge.call('case_software', args)
        self.assertTrue(first['success'], first)
        summary = first['result']['report_summary']
        self.assertEqual('awaiting_answers', summary['status'])
        self.assertIn('材料敏感等级', summary['next_question'])
        self.assertEqual(0, summary['answers_consumed'])
        self.assert_no_material_reads()
        helper = intake_fixtures.SoftwareIntakeTests()
        helper.now = datetime.now(timezone.utc)
        prefix = helper.context_answers()
        next_answer = self.bridge.call('case_software', {**args, 'answers': prefix})
        self.assertTrue(next_answer['success'], next_answer)
        summary = next_answer['result']['report_summary']
        self.assertEqual('awaiting_answers', summary['status'])
        self.assertIn('明确授权读取的根内文件路径', summary['next_question'])
        self.assertEqual(len(prefix), summary['answers_consumed'])
        self.assert_no_material_reads()
        self.assertFalse((self.workspace / 'output/candidates').exists())
        for invalid in ({'action': 'prepare', 'candidates': True},
                        {'action': 'intake', 'output': 'output/candidates', 'candidates': 'true'}):
            with mock.patch('tools.host_bridge.subprocess.Popen') as launch:
                answer = self.bridge.call('case_software', invalid)
                self.assertEqual('invalid_arguments', answer['error'], answer)
                launch.assert_not_called()

    def test_intake_discovers_actual_question_and_collects_real_answers(self):
        initial = self.bridge.call('case_software', {'action': 'intake', 'output': 'output/intake'})
        self.assertTrue(initial['success'], initial)
        self.assertEqual('awaiting_answers', initial['result']['report_summary']['status'])
        self.assertIn('材料敏感等级', initial['result']['report_summary']['next_question'])
        self.assertFalse((self.workspace / 'output/intake').exists())
        self.assert_no_material_reads()
        answers = self.intake_answers()
        partial = self.bridge.call('case_software', {'action': 'intake', 'output': 'output/intake',
                                                   'answers': answers[:-1]})
        self.assertEqual('awaiting_answers', partial['result']['report_summary']['status'], partial)
        self.assertIn('是否确认全部输入', partial['result']['report_summary']['next_question'])
        self.assert_no_material_reads()
        complete = self.bridge.call('case_software', {'action': 'intake', 'output': 'output/intake',
                                                    'answers': answers})
        self.assertTrue(complete['success'], complete)
        summary = complete['result']['report_summary']
        self.assertEqual('collected', summary['status'])
        self.assertEqual(2, len(summary['files']))
        self.assertNotIn('synthetic-local-authority', json.dumps(complete))
        self.assertNotIn(self.marker, json.dumps(complete))
        auth = json.loads((self.workspace / summary['authorization']).read_bytes())
        self.assertNotIn('confirmations', json.loads((self.workspace / auth['request']['path']).read_bytes()))
        built = self.bridge.call('case_software', {'action': 'build',
            'authorization': summary['authorization'], 'authorization_sha256': summary['authorization_sha256']})
        self.assertEqual(4, built['result']['exit_code'], built)

    def test_intake_refusal_unknown_missing_evidence_and_unused_answers_read_nothing(self):
        for options in ({'local_process': 'deny'}, {'local_process': 'unknown'}, {'evidence': ''}):
            answer = self.bridge.call('case_software', {'action': 'intake', 'output': 'output/intake',
                                                       'answers': self.intake_answers(**options)})
            self.assertEqual('material_permission_not_proven', answer['error'], answer)
            self.assert_no_material_reads()
        answer = self.bridge.call('case_software', {'action': 'intake', 'output': 'output/intake',
            'answers': self.intake_answers() + ['extra']})
        self.assertEqual('intake_answers_unused', answer['error'], answer)
        self.assert_no_material_reads()
        self.assertFalse((self.workspace / 'output/intake').exists())

    def test_bypassed_controller_worker_checks_paths_before_any_material_open(self):
        args = self.arguments()
        args['root'] = '..'
        job, audit = self.control / 'direct.job.json', self.control / 'direct.audit.json'
        job.write_bytes(core.canonical_bytes({'tool': 'case_software', 'arguments': args,
            'package': str(self.package), 'workspace': str(self.workspace), 'audit': str(audit),
            'expected_manifest_sha256': self.manifest}))
        process = subprocess.run([BASE_PYTHON, '-I', '-S', '-B', '-X', 'utf8',
            str(self.package / 'tools/host_bridge_worker.py'), str(job)], cwd=self.workspace,
            capture_output=True, timeout=30)
        self.assertEqual(2, process.returncode, process.stderr)
        proof = json.loads(audit.read_bytes())
        self.assertEqual('software_case_root_required', proof['contract_error'])
        self.assertEqual([], proof['blocked'])
        self.assertFalse(any(Path(row['path']).name in {'counter.py', 'request.json', 'authorization.json'}
                             for row in proof['file_open_events']))


if __name__ == '__main__':
    unittest.main()
