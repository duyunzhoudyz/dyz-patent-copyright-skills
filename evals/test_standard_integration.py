"""标准v2入口、离线白名单与独立包；全部材料为临时原创合成输入。"""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

from tools import bundle, cli, host_bridge, host_bridge_worker, standards_delivery

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = {'status': 'needs_evidence', 'professional_review': 'not_performed',
           'external_action': 'not_performed'}


class StandardCliBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyz-standard-cli-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'input').mkdir()
        (self.root / 'output').mkdir()
        self.input = self.root / 'input/task.json'
        self.payload = {'contract_version': 2, 'sensitivity': 'synthetic'}
        self.input.write_text(json.dumps(self.payload), encoding='utf-8')

    def arguments(self, *extra, synthetic=True, source='input/task.json', output='output/pack'):
        return ['prepare-standard', '--root', str(self.root), '--input', source,
                '--output', output, *(['--synthetic'] if synthetic else []), *extra]

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_prepare_and_verify_dispatch_preserve_actual_review_state(self):
        for verify in (False, True):
            if verify:
                (self.root / 'output/pack').mkdir()
            with self.subTest(verify=verify), mock.patch.object(
                    standards_delivery, 'prepare', return_value=SUMMARY) as prepare, \
                    mock.patch.object(standards_delivery, 'verify', return_value=SUMMARY) as check:
                code, out, err = self.invoke(self.arguments(*(['--verify'] if verify else [])))
            self.assertEqual((0, ''), (code, err))
            self.assertEqual(SUMMARY, json.loads(out))
            selected, other = (check, prepare) if verify else (prepare, check)
            selected.assert_called_once_with(self.root, self.payload, 'output/pack', synthetic=True)
            other.assert_not_called()

    def test_missing_synthetic_rejected_before_any_material_read(self):
        with mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                mock.patch.object(standards_delivery, 'prepare') as prepare:
            code, out, err = self.invoke(self.arguments(synthetic=False))
        self.assertEqual((2, '', 'standard_authorized_case_unsupported\n'), (code, out, err))
        prepare.assert_not_called()
        self.assertFalse((self.root / 'output/pack').exists())

    def test_paths_and_output_preconditions_rejected_before_input_read(self):
        (self.root / 'output/existing').mkdir()
        variants = [self.arguments(source='../outside.json'),
                    self.arguments(source=str(self.input)),
                    self.arguments(output='../outside'),
                    self.arguments(output='output/existing'),
                    self.arguments(output='missing/pack'),
                    self.arguments('--verify'),
                    self.arguments(output='input/task.json')]
        with mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                mock.patch.object(standards_delivery, 'prepare') as prepare:
            for args in variants:
                with self.subTest(args=args):
                    self.assertEqual(2, self.invoke(args)[0])
        prepare.assert_not_called()
        self.assertFalse((self.root / 'output/pack').exists())

    def test_unknown_cli_option_does_not_read_or_delegate(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                mock.patch.object(standards_delivery, 'prepare') as prepare:
            with self.assertRaises(SystemExit) as caught:
                cli.main(self.arguments('--admission', 'input/auth.json'))
        self.assertEqual(2, caught.exception.code)
        prepare.assert_not_called()

    def test_contract_version_classification_and_boundary_override_rejected(self):
        variants = [dict(self.payload, contract_version=value) for value in (1, 3, True, '2')]
        variants += [dict(self.payload, sensitivity=value) for value in ('restricted', 'public', None)]
        variants += [dict(self.payload, **{key: 'outside'})
                     for key in ('root', 'authorized_root', 'admission')]
        for payload in variants:
            self.input.write_text(json.dumps(payload), encoding='utf-8')
            with self.subTest(payload=payload), mock.patch.object(standards_delivery, 'prepare') as prepare:
                self.assertEqual(2, self.invoke(self.arguments())[0])
            prepare.assert_not_called()
            self.assertFalse((self.root / 'output/pack').exists())

    def test_duplicate_keys_and_oversized_input_rejected_before_delivery(self):
        for raw in (b'{"contract_version":2,"contract_version":2,"sensitivity":"synthetic"}',
                    b' ' * 5_000_001):
            self.input.write_bytes(raw)
            with self.subTest(size=len(raw)), mock.patch.object(standards_delivery, 'prepare') as prepare:
                self.assertEqual(2, self.invoke(self.arguments())[0])
            prepare.assert_not_called()
            self.assertFalse((self.root / 'output/pack').exists())

    def test_input_hardlink_rejected_before_read(self):
        import os
        os.link(self.input, self.root / 'input/alias.json')
        with mock.patch.object(Path, 'open', side_effect=AssertionError('material read')):
            self.assertEqual(2, self.invoke(self.arguments())[0])

    def test_existing_software_prepare_entry_keeps_its_authorization_arguments(self):
        with mock.patch.object(cli, '_prepare_software', return_value=None) as prepare:
            code, out, err = self.invoke(['prepare-software', '--root', str(self.root),
                                         '--authorization', 'input/auth.json',
                                         '--authorization-sha256', 'a' * 64])
        self.assertEqual((0, 'result_written\n', ''), (code, out, err))
        args = prepare.call_args.args[0]
        self.assertEqual(('input/auth.json', 'a' * 64),
                         (args.authorization, args.authorization_sha256))

    def test_errors_do_not_echo_private_payload_or_path(self):
        for error, code in ((ValueError('SYNTHETIC_PRIVATE'), 2), (OSError('SYNTHETIC_PRIVATE'), 3)):
            with self.subTest(error=type(error).__name__), mock.patch.object(
                    standards_delivery, 'prepare', side_effect=error):
                actual, out, err = self.invoke(self.arguments())
            self.assertEqual(code, actual)
            self.assertNotIn('SYNTHETIC_PRIVATE', out + err)
            self.assertNotIn(str(self.root), out + err)


def authorization(root, payload, *, output='output/pack'):
    """只用于合成安全替身，restricted标签用于验证拒绝与许可检查。"""
    now = datetime.now(timezone.utc)
    raw_hash = cli.core.sha256_bytes((root / 'input/task.json').read_bytes())
    return {'root': str(root), 'output': output, 'input_hash': raw_hash,
            'inputs': {'input/task.json': raw_hash}, 'payload_hash': cli.core.digest(payload),
            'sensitivity': payload['sensitivity'], 'purpose': 'synthetic-boundary-test',
            'permissions': [{'action': action, 'purpose': 'synthetic-boundary-test',
                             'recipient': 'local_tool', 'decision': 'allow',
                             'authority_evidence': 'synthetic-only-not-real-authorization',
                             'valid_from': (now - timedelta(days=1)).isoformat(),
                             'valid_until': (now + timedelta(days=1)).isoformat()}
                            for action in ('local_read', 'local_process', 'copy', 'local_write')],
            'environment': {'assessment_evidence': 'synthetic-only-not-host-certification',
                            'data_paths': [{'id': name, 'mode': 'local' if name == 'tools' else 'disabled',
                                            'verified': True, 'evidence': 'synthetic-only'}
                                           for name in ('host_model', 'index', 'telemetry',
                                                        'tools', 'logs', 'subprocess')]}}


class StandardAuthorizedCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyz-standard-admission-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'input').mkdir()
        (self.root / 'output').mkdir()
        self.payload = {'contract_version': 2, 'sensitivity': 'restricted'}
        self.input = self.root / 'input/task.json'
        self.input.write_text(json.dumps(self.payload), encoding='utf-8')
        self.auth = self.root / 'input/authorization.json'
        self.admission = authorization(self.root, self.payload)

    def args(self, admission=None):
        self.auth.write_text(json.dumps(self.admission if admission is None else admission), encoding='utf-8')
        return ['prepare-standard', '--root', str(self.root), '--input', 'input/task.json',
                '--output', 'output/pack', '--authorization', 'input/authorization.json',
                '--authorization-sha256', cli.core.sha256_bytes(self.auth.read_bytes())]

    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def assert_pre_read_rejection(self, args):
        original = Path.open
        opened = []

        def control_only(path, *values, **keywords):
            opened.append(path)
            self.assertEqual(self.auth, path, 'unauthorized payload must not be opened')
            return original(path, *values, **keywords)

        with mock.patch.object(Path, 'open', control_only), \
                mock.patch.object(standards_delivery, 'prepare') as prepare:
            code, out, err = self.invoke(args)
        self.assertEqual(2, code)
        self.assertEqual('', out)
        self.assertNotIn(str(self.root), err)
        prepare.assert_not_called()
        self.assertFalse((self.root / 'output/pack').exists())
        return opened

    def test_authorized_build_preserves_mode_and_full_bound_admission(self):
        with mock.patch.object(standards_delivery, 'prepare', return_value=SUMMARY) as prepare:
            code, out, err = self.invoke(self.args())
        self.assertEqual((0, ''), (code, err))
        self.assertEqual(SUMMARY, json.loads(out))
        prepare.assert_called_once_with(self.root, self.payload, 'output/pack',
                                        synthetic=False, admission=self.admission)

    def test_authorized_read_only_verify_does_not_require_write_permission(self):
        (self.root / 'output/pack').mkdir()
        self.admission['permissions'] = [entry for entry in self.admission['permissions']
                                         if entry['action'] != 'local_write']
        with mock.patch.object(standards_delivery, 'verify', return_value=SUMMARY) as verify:
            code, out, err = self.invoke(self.args() + ['--verify'])
        self.assertEqual((0, ''), (code, err))
        self.assertEqual(SUMMARY, json.loads(out))
        verify.assert_called_once_with(self.root, self.payload, 'output/pack',
                                       synthetic=False, admission=self.admission)

    def test_missing_expired_and_unverified_permissions_reject_before_payload(self):
        variants = []
        for action in ('local_read', 'local_process', 'copy', 'local_write'):
            value = copy.deepcopy(self.admission)
            value['permissions'] = [entry for entry in value['permissions'] if entry['action'] != action]
            variants.append(value)
        expired = copy.deepcopy(self.admission)
        for entry in expired['permissions']:
            entry['valid_until'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        variants.append(expired)
        for sensitivity in ('restricted', 'public'):
            missing_path = copy.deepcopy(self.admission)
            missing_path['sensitivity'] = sensitivity
            missing_path['environment']['data_paths'].pop()
            variants.append(missing_path)
        unknown_path = copy.deepcopy(self.admission)
        unknown_path['environment']['data_paths'][0]['verified'] = False
        variants.append(unknown_path)
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.assert_pre_read_rejection(self.args(value))

    def test_authorization_scope_and_shape_reject_before_payload(self):
        variants = [dict(self.admission, root=str(self.root.parent)),
                    dict(self.admission, output='output/other'),
                    dict(self.admission, inputs={'input/other.json': self.admission['input_hash']}),
                    dict(self.admission, input_hash='invalid'),
                    dict(self.admission, payload_hash='invalid'),
                    dict(self.admission, sensitivity='synthetic'),
                    dict(self.admission, now='2020-01-01T00:00:00Z')]
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.assert_pre_read_rejection(self.args(value))

    def test_authorization_descriptor_hash_and_ambiguous_modes_reject_before_payload(self):
        args = self.args()
        self.auth.write_bytes(self.auth.read_bytes() + b' ')
        self.assert_pre_read_rejection(args)
        args = self.args()
        self.assertEqual([], self.assert_pre_read_rejection(args + ['--synthetic']))
        self.assertEqual([], self.assert_pre_read_rejection(args[:-2]))

    def test_case_root_cannot_equal_contain_or_live_in_package_before_reads(self):
        args = self.args()
        for package in (self.root, self.root.parent, self.root / 'package'):
            with self.subTest(package=package), mock.patch.object(
                    cli, '__file__', str(package / 'tools/cli.py')):
                self.assertEqual([], self.assert_pre_read_rejection(args))

    def test_raw_input_hash_and_semantic_payload_hash_are_separate_bindings(self):
        args = self.args()
        self.input.write_bytes(self.input.read_bytes() + b' ')
        with mock.patch.object(standards_delivery, 'prepare') as prepare:
            self.assertEqual(2, self.invoke(args)[0])
        prepare.assert_not_called()
        self.admission = authorization(self.root, self.payload)
        self.admission['payload_hash'] = '0' * 64
        with mock.patch.object(standards_delivery, 'prepare') as prepare:
            self.assertEqual(2, self.invoke(self.args())[0])
        prepare.assert_not_called()
        self.assertFalse((self.root / 'output/pack').exists())

    def test_authorized_input_cannot_change_classification_after_admission(self):
        self.payload['sensitivity'] = 'synthetic'
        self.input.write_text(json.dumps(self.payload), encoding='utf-8')
        self.admission = authorization(self.root, self.payload)
        self.admission['sensitivity'] = 'restricted'
        with mock.patch.object(standards_delivery, 'prepare') as prepare:
            self.assertEqual(2, self.invoke(self.args())[0])
        prepare.assert_not_called()


class StandardMigrationCliTests(StandardAuthorizedCliTests):
    """沿用真实入口的全部读前反例，另核迁移不覆盖原表或伪造来源hash。"""

    def args(self, admission=None):
        args = super().args(admission)
        args[0] = 'migrate-standard-comments'
        return args[:1] + ['--direction', 'v1-to-v2'] + args[1:]

    # 成件专属成功路径不适用于迁移；对应迁移成功路径独立覆盖。
    def test_authorized_build_preserves_mode_and_full_bound_admission(self):
        from tools import standards_contract
        self.payload = {'sensitivity': 'restricted', 'document': {'header': {}, 'items': [], 'summary': {}}}
        self.input.write_text(json.dumps(self.payload), encoding='utf-8')
        self.admission = authorization(self.root, self.payload, output='output/migration.json')
        original = self.input.read_bytes()
        report = {'status': 'needs_evidence', 'issues': [{'code': 'synthetic_gap'}]}
        args = self.args()
        args[args.index('--output') + 1] = 'output/migration.json'
        with mock.patch.object(standards_contract, 'import_v1_disposition', return_value=report,
                               create=True) as convert:
            code, out, err = self.invoke(args)
        self.assertEqual((0, 'result_written\n', ''), (code, out, err))
        convert.assert_called_once_with(self.payload['document'], source_sha256=cli.core.sha256_bytes(original),
                                        source_locator='/document')
        saved = json.loads((self.root / 'output/migration.json').read_bytes())
        self.assertEqual(report, saved['conversion'])
        self.assertEqual('authorized_case', saved['mode'])
        self.assertEqual(cli.core.sha256_bytes(original), saved['input_binding']['sha256'])
        self.assertEqual(original, self.input.read_bytes())

    def test_authorized_read_only_verify_does_not_require_write_permission(self):
        args = self.args()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main(args + ['--verify'])
        self.assertFalse((self.root / 'output/pack').exists())

    def test_synthetic_reverse_export_binds_bytes_and_preserves_source(self):
        from tools import standards_contract
        self.payload = {'sensitivity': 'synthetic', 'document': {'contract_version': 2}}
        self.input.write_text(json.dumps(self.payload), encoding='utf-8')
        original = self.input.read_bytes()
        args = ['migrate-standard-comments', '--synthetic', '--root', str(self.root),
                '--input', 'input/task.json', '--output', 'output/export.json', '--direction', 'v2-to-v1']
        report = {'status': 'partial', 'losses': [{'path': '/synthetic_only'}]}
        with mock.patch.object(standards_contract, 'export_v1_disposition', return_value=report,
                               create=True) as convert:
            code, out, err = self.invoke(args)
        self.assertEqual((0, 'result_written\n', ''), (code, out, err))
        convert.assert_called_once_with(self.payload['document'])
        saved = json.loads((self.root / 'output/export.json').read_bytes())
        self.assertEqual(report, saved['conversion'])
        self.assertEqual(original, self.input.read_bytes())
        self.assertEqual(2, self.invoke(args)[0])

    def test_invalid_envelope_or_conflicting_classification_cannot_convert(self):
        from tools import standards_contract
        variants = [{'sensitivity': 'synthetic', 'document': {}, 'extra': True},
                    {'sensitivity': 'synthetic', 'document': []},
                    {'sensitivity': 'synthetic', 'document': {'sensitivity': 'restricted'}}]
        args = ['migrate-standard-comments', '--synthetic', '--root', str(self.root),
                '--input', 'input/task.json', '--output', 'output/export.json', '--direction', 'v1-to-v2']
        for payload in variants:
            self.input.write_text(json.dumps(payload), encoding='utf-8')
            with self.subTest(payload=payload), mock.patch.object(
                    standards_contract, 'import_v1_disposition', create=True) as convert:
                self.assertEqual(2, self.invoke(args)[0])
            convert.assert_not_called()
            self.assertFalse((self.root / 'output/export.json').exists())


class StandardHostBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dyz-standard-host-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / 'input').mkdir()
        (self.root / 'output').mkdir()
        (self.root / 'input/task.json').write_text('{}', encoding='utf-8')
        # 参数前置检查不依赖已冻结包，且不得触及包或创建worker任务。
        self.bridge = object.__new__(host_bridge.HostToolBridge)
        self.bridge.workspace = self.root
        self.args = {'input': 'input/task.json', 'output': 'output/pack', 'mode': 'synthetic'}

    def test_schema_registered_with_only_explicit_synthetic_and_known_fields(self):
        tools = host_bridge.dynamic_tools()
        self.assertEqual(host_bridge.TOOL_NAMES, {tool['name'] for tool in tools})
        self.assertEqual(10, len(tools))
        spec = next(tool['inputSchema'] for tool in tools if tool['name'] == 'case_standard_package')
        self.assertEqual({'input', 'output', 'mode', 'verify'}, set(spec['properties']))
        self.assertEqual(['input', 'output', 'mode'], spec['required'])
        self.assertEqual(['synthetic'], spec['properties']['mode']['enum'])
        self.assertEqual('boolean', spec['properties']['verify']['type'])
        self.assertFalse(spec['additionalProperties'])
        self.assertTrue({'case_documents', 'case_docx_review', 'case_fidelity'} <= host_bridge.TOOL_NAMES)

    def test_unknown_fields_missing_mode_and_unsupported_modes_reject_before_paths(self):
        variants = [{key: value for key, value in self.args.items() if key != 'mode'}]
        variants += [dict(self.args, **{key: 'ignored'}) for key in ('root', 'admission', 'command', 'shell')]
        variants += [dict(self.args, mode=value) for value in ('authorized_case', 'research_example', '', None)]
        variants += [dict(self.args, verify=value) for value in ('true', 1, None)]
        for args in variants:
            with self.subTest(args=args), mock.patch.object(self.bridge, '_path') as path, \
                    mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                    mock.patch.object(host_bridge.subprocess, 'Popen', side_effect=AssertionError('worker start')):
                with self.assertRaises(host_bridge.BridgeError):
                    self.bridge._file_tool('case_standard_package', args)
            path.assert_not_called()
        self.assertEqual([], list((self.root / 'output').iterdir()))

    def test_root_escape_and_existing_output_reject_before_reads_or_worker(self):
        (self.root / 'output/existing').mkdir()
        variants = [dict(self.args, input='../outside.json'), dict(self.args, output='../outside'),
                    dict(self.args, input='input/../task.json'), dict(self.args, output='input/new'),
                    dict(self.args, output='output/existing'), dict(self.args, verify=True)]
        for args in variants:
            with self.subTest(args=args), mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                    mock.patch.object(host_bridge.subprocess, 'Popen', side_effect=AssertionError('worker start')):
                with self.assertRaises(host_bridge.BridgeError):
                    self.bridge._file_tool('case_standard_package', args)
        self.assertFalse((self.root / 'output/pack').exists())

    def test_worker_revalidates_fields_mode_and_paths_before_cli(self):
        variants = [{key: value for key, value in self.args.items() if key != 'mode'},
                    dict(self.args, root='outside'), dict(self.args, admission={}),
                    dict(self.args, mode='authorized_case'), dict(self.args, mode='research_example'),
                    dict(self.args, verify='true'), dict(self.args, input='../outside.json'),
                    dict(self.args, input='input/../outside.json'), dict(self.args, input='input/.secret'),
                    dict(self.args, output='input/overwrite'), dict(self.args, output='output/../bad')]
        for args in variants:
            with self.subTest(args=args), contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.object(cli, 'main', side_effect=AssertionError('CLI delegated')), \
                    mock.patch.object(Path, 'open', side_effect=AssertionError('material read')):
                result = host_bridge_worker._run_tool(
                    {'tool': 'case_standard_package', 'arguments': args}, self.root)
            self.assertEqual((2, None), result)

    def test_worker_build_and_verify_delegate_only_declared_cli(self):
        for verify in (False, True):
            args = dict(self.args, verify=verify)
            with self.subTest(verify=verify), mock.patch.object(cli, 'main', return_value=0) as main:
                self.assertEqual((0, None), host_bridge_worker._run_tool(
                    {'tool': 'case_standard_package', 'arguments': args}, self.root))
            expected = ['prepare-standard', '--synthetic', '--root', str(self.root),
                        '--input', 'input/task.json', '--output', 'output/pack']
            main.assert_called_once_with(expected + (['--verify'] if verify else []))


class StandardPdfCliTests(unittest.TestCase):
    def arguments(self):
        return ['standard-pdf', '--synthetic', '--root', 'SYNTHETIC_ROOT',
                '--input', 'output/pack', '--output', 'output/pdf',
                '--soffice', 'C:/approved/soffice.exe', '--pdfinfo', 'C:/approved/pdfinfo.exe',
                '--pdftotext', 'C:/approved/pdftotext.exe', '--pdftoppm', 'C:/approved/pdftoppm.exe']

    def test_explicit_local_tools_and_unperformed_visual_review_preserved(self):
        from tools import standard_pdf
        report = dict(SUMMARY, status='structure_checked_needs_visual_review',
                      total_documents=5, total_pages=10, visual_review='not_performed')
        out = io.StringIO()
        with mock.patch.object(standard_pdf, 'convert', return_value=report) as convert, \
                contextlib.redirect_stdout(out):
            self.assertEqual(0, cli.main(self.arguments()))
        self.assertEqual(report, json.loads(out.getvalue()))
        convert.assert_called_once_with('SYNTHETIC_ROOT', 'output/pack', 'output/pdf', synthetic=True,
            tool_paths={name: 'C:/approved/' + name + '.exe'
                        for name in ('soffice', 'pdfinfo', 'pdftotext', 'pdftoppm')})

    def test_explicit_bundled_python_and_refresh_state_reach_conversion(self):
        from tools import standard_pdf
        report = dict(SUMMARY, status='needs_review', total_documents=5, total_pages=10,
                      visual_review='not_performed', field_refresh='needs_review')
        out = io.StringIO()
        with mock.patch.object(standard_pdf, 'convert', return_value=report) as convert, \
                contextlib.redirect_stdout(out):
            self.assertEqual(0, cli.main(self.arguments() + ['--office-python', 'C:/approved/python.exe']))
        self.assertEqual(report, json.loads(out.getvalue()))
        self.assertEqual('C:/approved/python.exe', convert.call_args.kwargs['tool_paths']['office_python'])

    def test_authorized_directory_uses_pdf_admission_without_json_material_loader(self):
        from tools import standard_pdf
        with tempfile.TemporaryDirectory(prefix='dyz-pdf-cli-control-') as directory:
            root = Path(directory).resolve()
            control = root / 'authorization.json'
            admission = {'control': 'SYNTHETIC_BOUND_DESCRIPTOR'}
            control.write_text(json.dumps(admission), encoding='utf-8')
            args = self.arguments()
            args.remove('--synthetic')
            args[args.index('--root') + 1] = str(root)
            args += ['--authorization', 'authorization.json', '--authorization-sha256',
                     cli.core.sha256_bytes(control.read_bytes())]
            report = dict(SUMMARY, total_documents=5, total_pages=9, visual_review='not_performed')
            with mock.patch.object(standard_pdf, 'convert', return_value=report) as convert, \
                    mock.patch.object(cli, '_read_standard_input', side_effect=AssertionError('directory is not JSON')), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, cli.main(args))
            self.assertEqual(root, convert.call_args.args[0])
            self.assertEqual(admission, convert.call_args.kwargs['admission'])
            self.assertFalse(convert.call_args.kwargs['synthetic'])

    def test_changed_pdf_control_hash_is_rejected_before_conversion(self):
        from tools import standard_pdf
        with tempfile.TemporaryDirectory(prefix='dyz-pdf-cli-control-') as directory:
            root = Path(directory).resolve()
            (root / 'authorization.json').write_text('{}', encoding='utf-8')
            args = self.arguments()
            args.remove('--synthetic')
            args[args.index('--root') + 1] = str(root)
            args += ['--authorization', 'authorization.json', '--authorization-sha256', '0' * 64]
            with mock.patch.object(standard_pdf, 'convert') as convert, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(2, cli.main(args))
            convert.assert_not_called()

    def test_intake_dispatch_preserves_actual_result_without_business_confirmation(self):
        from tools import standard_intake
        result = {'status': 'needs_evidence', 'input': 'intake/task.json',
                  'professional_review': 'not_performed', 'external_action': 'not_performed'}
        output = io.StringIO()
        with mock.patch.object(standard_intake, 'collect', return_value=result) as collect, \
                contextlib.redirect_stdout(output):
            self.assertEqual(0, cli.main(['standard-intake', '--root', 'ROOT', '--output', 'intake', '--synthetic']))
        collect.assert_called_once_with('ROOT', 'intake', synthetic=True)
        self.assertEqual(result, json.loads(output.getvalue()))

    def test_real_pdf_mode_cannot_read_or_start_conversion(self):
        from tools import standard_pdf
        args = self.arguments()
        args.remove('--synthetic')
        with mock.patch.object(standard_pdf, 'convert') as convert, \
                mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, cli.main(args))
        convert.assert_not_called()
        self.assertNotIn('case_standard_pdf', host_bridge.TOOL_NAMES)


class StandardPackageIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='dyz-standard-installed-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name).resolve()
        cls.package = cls.base / 'package'
        bundle.build_bundle(cls.package, source_root=ROOT)
        cls.manifest_hash = host_bridge._sha((cls.package / bundle.MANIFEST_NAME).read_bytes())

    def setUp(self):
        from evals.test_standards_delivery import task
        self.case_temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.base)
        self.addCleanup(self.case_temp.cleanup)
        self.case = Path(self.case_temp.name).resolve()
        self.work, self.control = self.case / 'workspace', self.case / 'control'
        (self.work / 'input').mkdir(parents=True)
        self.control.mkdir()
        self.payload = task()
        (self.work / 'input/task.json').write_text(json.dumps(self.payload, ensure_ascii=False), encoding='utf-8')
        self.bridge = host_bridge.HostToolBridge(self.package, self.work, self.control, self.manifest_hash)
        self.args = {'input': 'input/task.json', 'output': 'output/pack', 'mode': 'synthetic'}

    def _complete_package_consumer(self, *, tamper=False):
        # 父进程仅传原创载荷和源文字；包内进程不得借用开发评测实现或夹具。
        script = r'''
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import traceback
from unittest import mock
import zipfile
from xml.etree import ElementTree as ET

import tools
from tools import bundle, cli, core, document_review, host_bridge, host_bridge_worker
from tools import standard_intake, standard_review, standard_sources, standards_delivery

request = json.load(sys.stdin)
package = Path.cwd().resolve()
root = Path(request['root']).resolve()
result = {'material_origin': request['material_origin'], 'isolated_flags': {
    'ignore_environment': sys.flags.ignore_environment,
    'no_user_site': sys.flags.no_user_site, 'no_site': sys.flags.no_site,
    'dont_write_bytecode': sys.dont_write_bytecode}}
failed = False
try:
    assert request['material_origin'] == 'original_synthetic_only'
    payload = copy.deepcopy(request['payload'])
    assert payload['sensitivity'] == 'synthetic'
    pin_path = Path(request['pin_path']).resolve()
    assert not pin_path.is_relative_to(package)
    pin_hash = pin_path.read_text(encoding='ascii').strip()
    assert pin_hash == request['manifest_hash']
    package_manifest_raw = (package / bundle.MANIFEST_NAME).read_bytes()
    assert pin_hash == core.sha256_bytes(package_manifest_raw)
    package_manifest = core.strict_json_loads(package_manifest_raw.decode('utf-8'))
    pinned = bundle.verify_bundle(package, expected_manifest_sha256=pin_hash)
    assert pinned['inventory_layout'] == 'current'
    assert pinned['binding'] == 'expected_manifest_hash_matched'
    result['external_pin'] = {'sha256': pin_hash, 'outside_package': True,
        'verification': pinned, 'manifest': package_manifest,
        'manifest_raw_utf8': package_manifest_raw.decode('utf-8')}
    source_path, report_path, recipe_path = (
        'input/original.txt', 'input/source-report.json', 'input/consumer-v2.json')
    raw = '\f'.join(request['source_pages']).encode('utf-8')
    (root / source_path).write_bytes(raw)
    citation = {'id': 'CITE-PACKAGE-1', 'proposition': ''.join(request['source_pages']),
        'relation': 'supports', 'segments': [
            {'page': index, 'start': 0, 'end': len(text), 'quote': text}
            for index, text in enumerate(request['source_pages'], 1)]}
    imported = standard_sources.import_local(root, source_path, {
        'expected_sha256': core.sha256_bytes(raw), 'identity': request['source_identity'],
        'access_status': 'local_authorized', 'citations': [citation]}, synthetic=True)
    standard_sources.write_report(root, report_path, imported, synthetic=True)
    # 保留实际写入报告的字节，不能把内存对象digest代替文件sha256。
    report_raw = (root / report_path).read_bytes()
    payload['source_reports'] = [{'report_id': 'R-PACKAGE-1', 'path': report_path,
        'sha256': core.sha256_bytes(report_raw), 'source': request['source_identity']}]
    targets = [('clause', 'CL1'), ('comment_reason', 'C1'), ('verification_basis', 'V1'),
               ('note_section', payload['compilation_note']['sections'][0]['id'])]
    payload['source_bindings'] = [{'binding_id': 'B-PACKAGE-' + str(index),
        'target_type': kind, 'target_id': identity, 'report_id': 'R-PACKAGE-1',
        'citation_ids': [citation['id']], 'proposition': citation['proposition'],
        'version': payload['version']} for index, (kind, identity) in enumerate(targets, 1)]
    payload['profile']['rendering'] = 'dyz-standard-internal-v2'
    payload['compilation_note']['profile_hash'] = core.digest(payload['profile'])
    payload['presentation'] = {'outline': [
        {'id': 'annex', 'kind': 'annex', 'title': '原创合成附录'},
        {'id': 'section', 'parent_id': 'annex', 'kind': 'section', 'title': '设备记录'},
        {'id': 'subsection', 'parent_id': 'section', 'kind': 'section', 'title': '记录条件'},
        {'id': 'clause', 'parent_id': 'subsection', 'kind': 'clause',
         'clause_id': 'CL1', 'title': '结果要求'}]}
    recipe_raw = core.canonical_bytes(payload) + b'\n'
    (root / recipe_path).write_bytes(recipe_raw)
    values = ['v2',
        '\t'.join(['P-PACKAGE', recipe_path, core.sha256_bytes(recipe_raw), 'payload',
                   'original-synthetic-v2']),
        '\t'.join(['S-PACKAGE', source_path, core.sha256_bytes(raw), 'source',
                   'original-synthetic-text']),
        '\t'.join(['R-PACKAGE', report_path, core.sha256_bytes(report_raw), 'report',
                   'actual-original-synthetic-import-report']), '', 'yes']
    prompts, position = [], 0
    def input_fn(prompt):
        global position
        prompts.append(prompt)
        assert position < len(values), 'unexpected extra intake question'
        answer = values[position]
        position += 1
        return answer
    (root / 'output').mkdir(exist_ok=True)
    intake = standard_intake.collect(root, 'output/consumer-intake', input_fn=input_fn, synthetic=True)
    assert position == len(values), 'not all declared intake answers were consumed'
    collected = core.strict_json_loads((root / intake['input']).read_text(encoding='utf-8'))
    assert collected == payload
    originals = {name: (root / name).read_bytes()
                 for name in (source_path, report_path, recipe_path, intake['input'])}
    bridge = host_bridge.HostToolBridge(package, root, Path(request['control']), request['manifest_hash'])
    arguments = {'input': intake['input'], 'output': intake['output'], 'mode': 'synthetic'}
    built = bridge.call('case_standard_package', arguments)
    assert built['success'], built
    checked = bridge.call('case_standard_package', dict(arguments, verify=True))
    assert checked['success'], checked
    output = root / intake['output']
    manifest = core.strict_json_loads((output / 'manifest.json').read_text(encoding='utf-8'))
    checks = core.strict_json_loads((output / 'internal/checks.json').read_text(encoding='utf-8'))
    trace = core.strict_json_loads((output / 'internal/source-trace.json').read_text(encoding='utf-8'))
    inspections = {}
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    for path in sorted((output / 'body').glob('*.docx')):
        document_raw = path.read_bytes()
        current = document_review.review_docx(document_raw)['current']
        with zipfile.ZipFile(io.BytesIO(document_raw)) as archive:
            body = ET.fromstring(archive.read('word/document.xml'))
            fields = [node.text or '' for name in archive.namelist()
                if name.startswith('word/footer') and name.endswith('.xml')
                for node in ET.fromstring(archive.read(name)).iter(ns + 'instrText')]
        locations = [location['bookmark'] for row in trace for location in row['final_locations']
                     if location['document_role'] == path.stem]
        inspections[path.stem] = {'sha256': core.sha256_bytes(document_raw),
            'page_fields': fields,
            'heading_styles': [node.get(ns + 'val') for node in body.iter(ns + 'pStyle')],
            'bookmarks': [row for row in current['bookmarks'] if row['name'] in locations]}
    # 同一原创合成输入仅试真实worker模式的读前拒绝，绝不处理真实材料。
    real_arguments = dict(arguments, mode='authorized_case')
    with mock.patch.object(Path, 'open', side_effect=AssertionError('real-mode material read')), \
         mock.patch.object(cli, 'main', side_effect=AssertionError('real-mode CLI')), \
         contextlib.redirect_stdout(io.StringIO()):
        real_worker = host_bridge_worker._run_tool(
            {'tool': 'case_standard_package', 'arguments': real_arguments}, root)
        try:
            bridge._file_tool('case_standard_package', real_arguments)
        except host_bridge.BridgeError as error:
            real_bridge_error = str(error)
        else:
            raise AssertionError('real-mode bridge accepted')
    assert real_worker == (2, None)
    assert all((root / name).read_bytes() == expected for name, expected in originals.items())
    result.update(intake=intake, intake_answers_consumed=position,
        intake_confirmation_count=sum('集中确认' in prompt for prompt in prompts),
        intake_reasked_metadata=any(prompt.startswith('标准名称') for prompt in prompts),
        imported=imported, source_sha256=core.sha256_bytes(raw),
        report_sha256=core.sha256_bytes(report_raw), manifest=manifest,
        finite_review=checks['finite_review'], source_trace=trace, documents=inspections,
        real_worker={'code': real_worker[0], 'result': real_worker[1], 'mode': 'authorized_case',
                     'bridge_error': real_bridge_error, 'material_read': 'not_performed'},
        built=built, verified=checked, originals_protected=True)
    if request['tamper']:
        before = {path.relative_to(output).as_posix(): path.read_bytes()
                  for path in output.rglob('*') if path.is_file()}
        word_path = output / 'body/standard.docx'
        word_raw = word_path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(word_raw)) as archive:
            xml = archive.read('word/document.xml')
            original_text = payload['clauses'][0]['text'].encode('utf-8')
            assert original_text in xml
            changed_xml = xml.replace(original_text, original_text.replace(b'10 ms', b'20 ms'), 1)
            assert changed_xml != xml
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as changed:
                for member in archive.infolist():
                    changed.writestr(member, changed_xml if member.filename == 'word/document.xml'
                                    else archive.read(member.filename))
            changed_word = buffer.getvalue()
        changed_report = copy.deepcopy(imported)
        changed_report['citations'][0]['segments'][0]['quote'] += 'original-synthetic-change'
        variants = [('original', root / source_path, raw.replace(b'10 ms', b'20 ms')),
                    ('report', root / report_path, core.canonical_bytes(changed_report) + b'\n'),
                    ('actual_word', word_path, changed_word)]
        rejected = []
        for surface, path, altered in variants:
            retained = path.read_bytes()
            assert altered != retained
            try:
                path.write_bytes(altered)
                inputs_before = {name: (root / name).read_bytes() for name in originals}
                package_before = {item.relative_to(output).as_posix(): item.read_bytes()
                                  for item in output.rglob('*') if item.is_file()}
                rejection = bridge.call('case_standard_package', dict(arguments, verify=True))
                assert not rejection['success'], (surface, rejection)
                assert path.read_bytes() == altered
                assert all((root / name).read_bytes() == value
                           for name, value in inputs_before.items())
                assert {item.relative_to(output).as_posix(): item.read_bytes()
                        for item in output.rglob('*') if item.is_file()} == package_before
                rejected.append({'surface': surface, 'call': rejection,
                    'altered_sha256': core.sha256_bytes(altered),
                    'originals_protected': True, 'verification_wrote_nothing': True})
            finally:
                path.write_bytes(retained)
        assert all((root / name).read_bytes() == expected for name, expected in originals.items())
        assert {path.relative_to(output).as_posix(): path.read_bytes()
                for path in output.rglob('*') if path.is_file()} == before
        restored = bridge.call('case_standard_package', dict(arguments, verify=True))
        assert restored['success'], restored
        package_source = package / 'tools/standard_intake.py'
        source_before = package_source.read_bytes()
        audit_before = sorted(path.name for path in Path(request['control']).glob('*.audit.json'))
        try:
            package_source.write_bytes(source_before + b'\n# ORIGINAL_SYNTHETIC_PIN_TAMPER\n')
            try:
                bundle.verify_bundle(package, expected_manifest_sha256=pin_hash)
            except bundle.BundleError as error:
                pin_error = str(error)
            else:
                raise AssertionError('externally pinned package source change accepted')
            assert pin_error == 'bundle_source_changed', pin_error
            assert {path.relative_to(output).as_posix(): path.read_bytes()
                    for path in output.rglob('*') if path.is_file()} == before
            assert all((root / name).read_bytes() == value for name, value in originals.items())
            assert sorted(path.name for path in Path(request['control']).glob('*.audit.json')) == audit_before
        finally:
            package_source.write_bytes(source_before)
        repinned = bundle.verify_bundle(package, expected_manifest_sha256=pin_hash)
        result.update(tamper_rejections=rejected, restored_verify=restored,
            package_source_rejection={'code': pin_error, 'originals_protected': True,
                'old_package_output_preserved': True, 'worker_started': False,
                'restored_pin': repinned})
    result['worker_audits'] = [core.strict_json_loads(path.read_text(encoding='utf-8'))
                              for path in sorted(Path(request['control']).glob('*.audit.json'))]
except Exception as error:
    failed = True
    result['failure'] = {'type': type(error).__name__, 'message': str(error)}
    traceback.print_exc(file=sys.stderr)
finally:
    result['tools_file'] = str(Path(tools.__file__).resolve())
    result['module_paths'] = {name: str(Path(module.__file__).resolve())
        for name, module in sorted(sys.modules.items())
        if name.startswith('tools.') and getattr(module, '__file__', None)}
    result['eval_modules'] = [name for name in sys.modules if name == 'evals' or name.startswith('evals.')]
    result['sys_path'] = [str(Path(value or '.').resolve()) for value in sys.path]
    print(json.dumps(result, ensure_ascii=True))
if failed:
    sys.exit(1)
'''
        payload = copy.deepcopy(self.payload)
        text = '设备应每10 ms记录结果及错误状态。'
        payload['clauses'][0]['text'] = text
        payload['comment_outcomes'][0]['changes'][0]['proposed_text'] = text
        payload['compilation_note']['clause_digest'] = cli.core.digest(payload['clauses'])
        request = {'root': str(self.work), 'control': str(self.control), 'payload': payload,
                   'manifest_hash': self.manifest_hash, 'material_origin': 'original_synthetic_only',
                   'source_pages': ['设备应每10 ms记录结果', '及错误状态。'],
                   'source_identity': {'number': 'SYN-PACKAGE 25', 'edition': '2026',
                                       'publisher': '原创合成包消费者', 'title': '设备记录要求'},
                   'tamper': tamper, 'pin_path': str(self.case / 'package-manifest.sha256')}
        Path(request['pin_path']).write_text(self.manifest_hash + '\n', encoding='ascii')
        base_python = getattr(sys, '_base_executable', None) or sys.executable
        process = subprocess.run([base_python, '-E', '-s', '-S', '-B', '-c', script],
            input=json.dumps(request, ensure_ascii=True).encode('utf-8'), cwd=self.package,
            capture_output=True, timeout=90)
        observation = {'test': self.id(), 'returncode': process.returncode,
                       'stdout': process.stdout.decode('utf-8'),
                       'stderr': process.stderr.decode('utf-8', errors='replace'),
                       'package_manifest_sha256': self.manifest_hash,
                       'python_flags': ['-E', '-s', '-S', '-B']}
        if not hasattr(type(self), 'consumer_observations'):
            type(self).consumer_observations = []
        type(self).consumer_observations.append(observation)
        self.assertEqual(0, process.returncode, observation['stderr'] + observation['stdout'])
        result = json.loads(process.stdout)
        self.assertEqual(self.package / 'tools/__init__.py', Path(result['tools_file']))
        self.assertEqual([], result['eval_modules'])
        self.assertNotIn(str(ROOT), result['sys_path'])
        self.assertEqual({'ignore_environment': 1, 'no_user_site': 1, 'no_site': 1,
                          'dont_write_bytecode': True}, result['isolated_flags'])
        self.assertTrue({'tools.standard_intake', 'tools.standard_sources', 'tools.standard_review',
                         'tools.standards_delivery', 'tools.documents', 'tools.host_bridge'}
                        <= set(result['module_paths']))
        for module, filename in result['module_paths'].items():
            with self.subTest(module=module):
                path = Path(filename)
                self.assertTrue(path.is_relative_to(self.package / 'tools'), path)
                self.assertIn(path.relative_to(self.package).as_posix(), bundle.BUNDLE_FILES)
        for audit in result['worker_audits']:
            self.assertEqual([], audit['blocked'])
            self.assertEqual('manifest_hash_bound_source_only_no_bytecode', audit['source_loading'])
            for filename in audit['loaded_tools_modules'].values():
                self.assertTrue(Path(filename).is_relative_to(self.package / 'tools'), filename)
        forbidden_parts = {'evals', 'docs', '竞品对比', '真实案例'}
        for filename in result['module_paths'].values():
            self.assertTrue(forbidden_parts.isdisjoint(Path(filename).relative_to(self.package).parts))
        self.assertFalse((self.package / 'evals').exists())
        self.assertTrue(result['external_pin']['outside_package'])
        self.assertEqual(self.manifest_hash, result['external_pin']['sha256'])
        self.assertEqual('current', result['external_pin']['verification']['inventory_layout'])
        pin = result['external_pin']
        self.assertEqual(self.manifest_hash, host_bridge._sha(pin['manifest_raw_utf8'].encode('utf-8')))
        self.assertEqual(pin['manifest'], json.loads(pin['manifest_raw_utf8']))
        self.assertEqual(set(bundle.BUNDLE_FILES), {row['path'] for row in pin['manifest']['files']})
        for row in pin['manifest']['files']:
            with self.subTest(distributed_source=row['path']):
                raw = (self.package / row['path']).read_bytes()
                self.assertEqual(row['bytes'], len(raw))
                self.assertEqual(row['sha256'], host_bridge._sha(raw))
        forbidden_paths = [str(ROOT).encode('utf-8'), ROOT.as_posix().encode('utf-8')]
        product_files = [self.package / bundle.MANIFEST_NAME]
        product_files.extend(path for path in (self.work / result['intake']['output']).rglob('*')
                             if path.is_file())
        for path in product_files:
            with self.subTest(no_development_absolute_path=path.name):
                raw = path.read_bytes()
                if path.suffix == '.docx':
                    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                        raw = b'\n'.join(archive.read(name) for name in archive.namelist())
                self.assertTrue(all(value not in raw for value in forbidden_paths))
        return result

    def test_original_synthetic_intake_sources_rules_and_v2_delivery_use_complete_package(self):
        result = self._complete_package_consumer()
        self.assertEqual('original_synthetic_only', result['material_origin'])
        self.assertEqual('synthetic', result['intake']['mode'])
        self.assertIsNone(result['intake']['authorization'])
        self.assertEqual(6, result['intake_answers_consumed'])
        self.assertEqual(1, result['intake_confirmation_count'])
        self.assertFalse(result['intake_reasked_metadata'])
        self.assertTrue(result['originals_protected'])
        self.assertEqual('complete', result['imported']['extraction']['coverage'])
        self.assertEqual(2, result['imported']['extraction']['total_pages'])
        self.assertEqual('not_verified', result['imported']['citations'][0]['proposition_support'])
        manifest, finite = result['manifest'], result['finite_review']
        self.assertEqual('not_performed', manifest['professional_review'])
        self.assertEqual('not_performed', manifest['external_action'])
        self.assertEqual('dyz-standard-internal-v2', manifest['rendering_profile'])
        resource_root = self.package / 'skills/dyz-standards/resources/lifecycle'
        layout = json.loads((resource_root / 'rendering-profile.v2.json').read_bytes())
        self.assertEqual(cli.core.digest(layout), manifest['rendering_profile_hash'])
        rules_raw = (resource_root / 'review-rules.v1.json').read_bytes()
        rules = json.loads(rules_raw)
        self.assertEqual(host_bridge._sha(rules_raw), finite['rules_hash'])
        self.assertEqual({row['id'] for row in rules['rules']}, set(finite['coverage']['rule_ids']))
        self.assertEqual('actual_reports_checked', finite['coverage']['source_verification'])
        self.assertEqual(1, finite['coverage']['actual_texts_checked'])
        self.assertTrue(any(row['rule_id'] == 'SR-STR-01'
                            and row['actual_evidence'] == 'actual_final_text'
                            for row in finite['limitation_checks']))
        self.assertEqual(result['documents']['standard']['sha256'], finite['actual_document']['sha256'])
        self.assertEqual(5, len(result['documents']))
        self.assertIn('AnnexHeading4', result['documents']['standard']['heading_styles'])
        for role, document in result['documents'].items():
            with self.subTest(role=role):
                self.assertTrue(any(field.strip() == 'PAGE' for field in document['page_fields']))
                member = next(row for row in manifest['files'] if row['path'] == f'body/{role}.docx')
                self.assertEqual(member['sha256'], document['sha256'])
        trace = result['source_trace']
        self.assertEqual({'clause', 'comment_reason', 'verification_basis', 'note_section'},
                         {row['target_type'] for row in trace})
        for row in trace:
            with self.subTest(binding=row['binding_id']):
                self.assertEqual('verified', row['state'])
                self.assertEqual(result['source_sha256'], row['original_sha256'])
                self.assertEqual(result['report_sha256'], row['report_sha256'])
                self.assertEqual('not_verified', row['proposition_support'])
                self.assertTrue(row['final_locations'])
                for location in row['final_locations']:
                    document = result['documents'][location['document_role']]
                    bookmarks = [record for record in document['bookmarks']
                                 if record['name'] == location['bookmark']]
                    self.assertEqual(1, len(bookmarks))
                    self.assertEqual('paired_unique_name', bookmarks[0]['identity_state'])
                    self.assertEqual('literal_span', bookmarks[0]['text_state'])
                    self.assertEqual(bookmarks[0]['text'], location['actual_text'])
                    self.assertEqual(cli.core.sha256_bytes(bookmarks[0]['text'].encode('utf-8')),
                                     location['actual_text_sha256'])
                    self.assertEqual(document['sha256'], location['document_sha256'])
                    self.assertEqual('literal_span_verified', location['actual_text_state'])
                    self.assertEqual('not_generated', location['page_status'])
        self.assertEqual(2, result['real_worker']['code'])
        self.assertEqual('not_performed', result['real_worker']['material_read'])
        self.assertEqual('standard_authorized_case_unsupported', result['real_worker']['bridge_error'])
        self.assertEqual(2, len(result['worker_audits']))

    def test_package_consumer_rejects_changed_original_report_and_actual_word(self):
        result = self._complete_package_consumer(tamper=True)
        rejected = result['tamper_rejections']
        self.assertEqual(['original', 'report', 'actual_word'], [row['surface'] for row in rejected])
        for row in rejected:
            with self.subTest(surface=row['surface']):
                self.assertFalse(row['call']['success'])
                self.assertTrue(row['originals_protected'])
                self.assertTrue(row['verification_wrote_nothing'])
        self.assertTrue(result['restored_verify']['success'])
        pin_rejection = result['package_source_rejection']
        self.assertEqual('bundle_source_changed', pin_rejection['code'])
        self.assertTrue(pin_rejection['originals_protected'])
        self.assertTrue(pin_rejection['old_package_output_preserved'])
        self.assertFalse(pin_rejection['worker_started'])
        self.assertEqual('expected_manifest_hash_matched', pin_rejection['restored_pin']['binding'])
        self.assertEqual(6, len(result['worker_audits']))

    def test_complete_bundle_contains_required_modules_and_both_schema_versions(self):
        required = {'tools/standards_delivery.py', 'tools/standards_contract.py',
                    'tools/standard_sources.py', 'tools/document_edit.py', 'tools/standard_pdf.py',
                    'tools/standard_review.py', 'tools/standard_intake.py',
                    'skills/dyz-standards/resources/lifecycle/review-rules.v1.json',
                    'skills/dyz-standards/resources/lifecycle/rendering-profile.v2.json',
                    'skills/dyz-standards/resources/lifecycle/table-template-profiles.v1.json'}
        required.update('skills/dyz-standards/resources/lifecycle/' + name + version + '.schema.json'
                        for name in ('compilation-note', 'comment-disposition') for version in ('', '.v2'))
        self.assertTrue(required <= set(bundle.BUNDLE_FILES))
        self.assertTrue(all((self.package / name).is_file() for name in required))
        self.assertFalse((self.package / 'evals').exists())
        for name in ('compilation-note', 'comment-disposition'):
            old = json.loads((self.package / f'skills/dyz-standards/resources/lifecycle/{name}.schema.json').read_bytes())
            new = json.loads((self.package / f'skills/dyz-standards/resources/lifecycle/{name}.v2.schema.json').read_bytes())
            self.assertNotEqual(old['$id'], new['$id'])

    def test_source_edit_and_pdf_entrypoints_load_only_complete_package(self):
        base_python = getattr(sys, '_base_executable', None) or sys.executable
        for module, command in (('tools.standard_sources', []), ('tools.document_edit', []),
                                ('tools', ['standard-pdf'])):
            with self.subTest(module=module):
                # -E使环境中的PYTHONUTF8失效；显式-X utf8与文档命令一致，
                # 否则非中文代码页（如cp1252）输出中文帮助时编码失败。
                process = subprocess.run([base_python, '-E', '-s', '-S', '-B', '-X', 'utf8',
                                          '-m', module, *command, '--help'], cwd=self.package,
                                         capture_output=True, timeout=15)
                self.assertEqual(0, process.returncode, process.stderr)
                self.assertIn(b'--root', process.stdout)
                self.assertIn(b'--synthetic', process.stdout)
        self.assertFalse((self.package / 'evals').exists())

    def test_five_documents_build_verify_and_status_cross_frozen_worker(self):
        built = self.bridge.call('case_standard_package', self.args)
        self.assertTrue(built['success'], built)
        manifest = json.loads((self.work / 'output/pack/manifest.json').read_bytes())
        self.assertEqual(5, len(list((self.work / 'output/pack/body').glob('*.docx'))))
        self.assertEqual(manifest['status'], built['result']['review_status'])
        self.assertEqual('not_performed', built['result']['report_summary']['professional_review'])
        before = {path: path.read_bytes() for path in (self.work / 'output/pack').rglob('*') if path.is_file()}
        checked = self.bridge.call('case_standard_package', dict(self.args, verify=True))
        self.assertTrue(checked['success'], checked)
        self.assertEqual(manifest['status'], checked['result']['review_status'])
        self.assertTrue(all(path.read_bytes() == raw for path, raw in before.items()))
        for number in (1, 2):
            audit = json.loads((self.control / f'tool-{number:04}.audit.json').read_bytes())
            self.assertEqual([], audit['blocked'])
            self.assertEqual('manifest_hash_bound_source_only_no_bytecode', audit['source_loading'])
            self.assertEqual(self.package / 'tools/standards_delivery.py',
                             Path(audit['loaded_tools_modules']['tools.standards_delivery']))
        self.assertTrue(all(call['tool'] == 'case_standard_package' and not call['payloads_recorded']
                            for call in self.bridge.calls))

    def test_real_mode_is_not_laundered_into_synthetic_before_worker(self):
        with mock.patch.object(Path, 'open', side_effect=AssertionError('material read')), \
                mock.patch.object(host_bridge.subprocess, 'Popen', side_effect=AssertionError('worker start')):
            with self.assertRaisesRegex(host_bridge.BridgeError, 'standard_authorized_case_unsupported'):
                self.bridge._file_tool('case_standard_package', dict(self.args, mode='authorized_case'))
        self.assertFalse((self.work / 'output/pack').exists())
        self.assertEqual([], list(self.control.iterdir()))

    def test_authorized_cli_build_and_verify_use_safe_restricted_substitute(self):
        self.payload['sensitivity'] = 'restricted'
        source = self.work / 'input/task.json'
        source.write_text(json.dumps(self.payload), encoding='utf-8')
        admission = authorization(self.work, self.payload)
        path = self.work / 'input/authorization.json'
        path.write_text(json.dumps(admission), encoding='utf-8')
        args = ['prepare-standard', '--root', str(self.work), '--input', 'input/task.json',
                '--output', 'output/pack', '--authorization', 'input/authorization.json',
                '--authorization-sha256', cli.core.sha256_bytes(path.read_bytes())]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(0, cli.main(args))
            self.assertEqual(0, cli.main(args + ['--verify']))
        manifest = json.loads((self.work / 'output/pack/manifest.json').read_bytes())
        self.assertEqual('authorized_case', manifest['mode'])
        self.assertEqual('not_performed', manifest['professional_review'])
        self.assertEqual('not_performed', manifest['external_action'])
        self.assertEqual('restricted', self.payload['sensitivity'])

    def test_changed_recipe_and_changed_actual_document_cannot_verify(self):
        self.assertTrue(self.bridge.call('case_standard_package', self.args)['success'])
        source = self.work / 'input/task.json'
        original = source.read_bytes()
        altered = dict(self.payload, version='another-version')
        source.write_text(json.dumps(altered), encoding='utf-8')
        self.assertFalse(self.bridge.call('case_standard_package', dict(self.args, verify=True))['success'])
        source.write_bytes(original)
        path = self.work / 'output/pack/body/standard.docx'
        path.write_bytes(path.read_bytes() + b'SYNTHETIC_CHANGED_BYTES')
        self.assertFalse(self.bridge.call('case_standard_package', dict(self.args, verify=True))['success'])


if __name__ == '__main__':
    unittest.main()
