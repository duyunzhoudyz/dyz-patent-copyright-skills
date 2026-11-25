"""Product bridge: real copied-file integration and prior-boundary regressions.

No model, account, network, browser, office application or persistent install.
"""
import ast
import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from tools.bundle import build_bundle, MANIFEST_NAME
from tools.host_bridge import HostToolBridge, BridgeError
from evals.test_fidelity import example

ROOT = Path(__file__).resolve().parents[1]
BASE_PYTHON = getattr(sys, '_base_executable', None) or sys.executable


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def png():
    def chunk(kind, raw):
        return struct.pack('>I', len(raw)) + kind + raw + struct.pack('>I', zlib.crc32(kind + raw) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b'')


class ProductBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.group = tempfile.TemporaryDirectory(prefix='dyz-product-bridge-')
        cls.base = Path(cls.group.name).resolve()
        cls.package = cls.base / 'package'
        build_bundle(cls.package, source_root=ROOT)
        cls.manifest = sha((cls.package / MANIFEST_NAME).read_bytes())

    @classmethod
    def tearDownClass(cls):
        assert cls.package.resolve().is_relative_to(cls.base)
        cls.group.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='case-', dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name).resolve()
        self.work, self.control = self.case / 'workspace', self.case / 'control'
        (self.work / 'input').mkdir(parents=True)
        self.control.mkdir()
        self.marker = 'SYNTHETIC-private-payload-仅供合成验证'
        self.raw = (self.marker + '\n正文\n内部备注\n').encode('utf-8')
        (self.work / 'input/source.md').write_bytes(self.raw)
        self.bridge = HostToolBridge(self.package, self.work, self.control, self.manifest)

    def spec(self, path='input/source.md', raw=None):
        return {'sensitivity': 'synthetic', 'document_id': 'ProductBridge', 'version': '1', 'business': 'patent',
                'sources': [{'id': 'Source', 'path': path, 'sha256': sha(self.raw if raw is None else raw)}],
                'blocks': [{'id': 'Body', 'kind': 'paragraph', 'audience': 'body', 'source_id': 'Source', 'start_line': 1, 'end_line': 2},
                           {'id': 'Note', 'kind': 'paragraph', 'audience': 'internal', 'source_id': 'Source', 'start_line': 3, 'end_line': 3}],
                'figures': []}

    def test_case_write_rejects_scripts_and_root_parent_segments(self):
        for ext in ('.sh', '.py', '.vbs', '.JS', '.ps1', '', '.docx'):
            path = 'work/unsafe' + ext
            result = self.bridge.call('case_write', {'path': path, 'text': 'synthetic text'})
            self.assertEqual('text_file_required', result['error'])
            self.assertFalse((self.work / path).exists())
        with self.assertRaisesRegex(BridgeError, 'unsafe_path'):
            HostToolBridge(self.package, self.work / 'input' / '..', self.control, self.manifest)

    def test_worker_output_is_rejected_at_stream_limit(self):
        self.put_spec(self.spec())
        with mock.patch('tools.host_bridge.MAX_WORKER_STREAM_BYTES', 8):
            answer = self.bridge.call('case_documents', {'input': 'input/spec.json', 'output': 'output/doc', 'mode': 'synthetic'})
        self.assertFalse(answer['success'])
        self.assertEqual('worker_output_limit_exceeded', answer['error'])

    def test_audit_write_is_blocked_during_tool_and_runtime_sibling_is_unreadable(self):
        runtime = self.case / 'synthetic-runtime'
        library = runtime / 'lib'
        library.mkdir(parents=True)
        (library / 'marker.txt').write_text('synthetic library fixture', encoding='utf-8')
        (runtime / 'outside.txt').write_text('synthetic non-library fixture', encoding='utf-8')
        job = self.control / 'direct-audit.job.json'
        audit = self.control / 'direct-audit.audit.json'
        job.write_text(json.dumps({'tool': 'case_fidelity', 'arguments': {}, 'package': str(self.package),
                                  'workspace': str(self.work), 'audit': str(audit),
                                  'expected_manifest_sha256': self.manifest}), encoding='utf-8')
        program = """
import importlib.util
from pathlib import Path
import sys

worker_path, job_path, root = sys.argv[1:]
spec = importlib.util.spec_from_file_location('isolated_test_worker', worker_path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
runtime = Path(root)
sys.base_prefix = sys.base_exec_prefix = root
worker.sysconfig.get_paths = lambda: dict(stdlib=runtime / 'lib', platstdlib=runtime / 'lib',
                                         purelib=runtime / 'lib' / 'site-packages', platlib=runtime / 'lib' / 'site-packages')

def observe_open_modes(job, _workspace):
    (runtime / 'lib' / 'marker.txt').read_bytes()
    for path, mode in [(Path(job['audit']), 'xb'), (runtime / 'outside.txt', 'rb')]:
        try:
            with path.open(mode):
                pass
        except PermissionError:
            continue
        raise AssertionError('worker accepted an unapproved path')
    return 0, None

worker._run_tool = observe_open_modes
sys.argv = [worker_path, job_path]
raise SystemExit(worker.main())
"""
        result = subprocess.run([BASE_PYTHON, '-I', '-S', '-B', '-X', 'utf8', '-c', program,
                                 str(self.package / 'tools/host_bridge_worker.py'), str(job), str(runtime)],
                                cwd=self.work, capture_output=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        proof = json.loads(audit.read_bytes())
        self.assertEqual({audit, runtime / 'outside.txt'}, {Path(row['path']) for row in proof['blocked']})
        self.assertTrue(any(row['location'] == 'python_runtime' for row in proof['file_open_events']))

    def test_docx_summary_crosses_worker_and_retains_hash_bound_full_report(self):
        from evals.test_document_review import fixture, edited, tag
        from tools.document_review import review_docx
        baseline = fixture()
        current = edited(baseline, lambda tree: setattr(tree.find('.//' + tag('t')), 'text', '条件由A改为B'))
        (self.work / 'input/current.docx').write_bytes(current)
        (self.work / 'input/baseline.docx').write_bytes(baseline)
        args = {'input': 'input/current.docx', 'baseline': 'input/baseline.docx',
                'output': 'output/review.json', 'mode': 'synthetic', 'summary': True}
        answer = self.bridge.call('case_docx_review', args)
        self.assertTrue(answer['success'], answer)
        wire = answer['result']['report_summary']
        self.assertEqual('', answer['result']['stdout'])
        self.assertEqual('parsed_into_report_summary', answer['result']['stdout_format'])
        full_raw = (self.work / args['output']).read_bytes()
        full = json.loads(full_raw)
        self.assertEqual(sha(full_raw), wire['sha256'])
        self.assertEqual(review_docx(current, baseline)['comparison'], full['comparison'])
        compact = wire['review_summary']
        self.assertEqual(sha(current), compact['current_sha256'])
        self.assertEqual(sha(baseline), compact['baseline_sha256'])
        self.assertTrue(any('literal_change' in item for item in compact['items']))
        self.assertEqual('not_performed', compact['professional_review'])
        self.assertNotIn('review_summary', full)
        self.assertFalse(self.bridge.calls[-1]['payloads_recorded'])
        with mock.patch('tools.host_bridge.subprocess.Popen', side_effect=AssertionError('invalid flag launched worker')):
            invalid = self.bridge.call('case_docx_review', {**args, 'output': 'output/invalid.json', 'summary': 'true'})
        self.assertFalse(invalid['success'])
        self.assertEqual('invalid_arguments', invalid['error'])
        self.assertFalse((self.work / 'output/invalid.json').exists())

    def test_wrong_docx_fields_rejected_before_worker_without_output(self):
        recipe = self.work / 'input/spec.json'
        recipe.write_text(json.dumps(self.spec()), encoding='utf-8')
        built = self.bridge.call('case_documents', {'input': 'input/spec.json', 'output': 'output/doc', 'mode': 'synthetic'})
        self.assertTrue(built['success'], built)
        current = 'output/doc/body/document.docx'
        current_hash = sha((self.work / current).read_bytes())
        jobs = {p.name for p in self.control.glob('*.job.json')}
        variants = [({'input': 'input/spec.json'}, 'current_docx_required'),
                    ({'input': current, 'baseline': 'input/spec.json'}, 'baseline_docx_required')]
        for n, (values, expected) in enumerate(variants):
            args = {'output': f'output/rejected-{n}.json', 'mode': 'synthetic', **values}
            with self.subTest(expected=expected), mock.patch('tools.host_bridge.subprocess.Popen',
                    side_effect=AssertionError('wrong file type must not start worker')) as launch:
                answer = self.bridge.call('case_docx_review', args)
                self.assertFalse(answer['success'])
                self.assertEqual(answer['error'], expected)
                launch.assert_not_called()
            self.assertFalse((self.work / args['output']).exists())
        self.assertEqual(jobs, {p.name for p in self.control.glob('*.job.json')})
        self.assertEqual(current_hash, sha((self.work / current).read_bytes()))
        self.assertEqual(len(self.bridge.calls), 3)

    def test_copied_product_projects_and_reverifies_reading_scope_without_development_module(self):
        resource=self.package/'skills/dyz-rendering/resources'
        spec=json.loads((resource/'reading-scope-example.json').read_bytes())
        for source in spec['sources']:
            origin=self.package/source['path'];target=self.work/'input'/origin.name
            target.write_bytes(origin.read_bytes());source['path']='input/'+origin.name
        (self.work/'input/reading-spec.json').write_bytes(json.dumps(spec,ensure_ascii=False).encode())
        args={'input':'input/reading-spec.json','output':'output/reading','mode':'synthetic'}
        answer=self.bridge.call('case_documents',args);self.assertTrue(answer['success'],answer)
        manifest=json.loads((self.work/'output/reading/manifest.json').read_bytes())
        self.assertEqual('checked',manifest['reading_scope']['status']);self.assertEqual('needs_review',manifest['status'])
        self.assertTrue(self.bridge.call('case_documents',{**args,'verify':True})['success'])
        answer=self.bridge.call('case_docx_review',{'input':'output/reading/body/document.docx','output':'output/reading-readback.json','mode':'synthetic'})
        self.assertTrue(answer['success'],answer)
        report=json.loads((self.work/'output/reading-readback.json').read_bytes())
        total=next(row['text'] for row in report['current']['bookmarks'] if row['name']=='Scope3')
        self.assertEqual((resource/'reading-scope-statements.md').read_text(encoding='utf-8').splitlines()[4],total)
        self.assertIn('示例文献甲（v1）',total);self.assertIn('示例文献乙（v2）',total)
        self.assertIn('合计覆盖31/51页',total)
        for ordinal in [1,2]:
            audit=json.loads((self.control/f'tool-{ordinal:04}.audit.json').read_bytes())
            self.assertEqual('manifest_hash_bound_source_only_no_bytecode',audit['source_loading'])
            self.assertEqual(self.package/'tools/fidelity.py',Path(audit['loaded_tools_modules']['tools.fidelity']))

    def test_optional_or_actual_docx_baseline_preserves_needs_review(self):
        (self.work / 'input/spec.json').write_text(json.dumps(self.spec()), encoding='utf-8')
        built = self.bridge.call('case_documents', {'input': 'input/spec.json', 'output': 'output/doc', 'mode': 'synthetic'})
        self.assertTrue(built['success'], built)
        current = 'output/doc/body/document.docx'
        raw = (self.work / current).read_bytes()
        (self.work / 'input/previous.DOCX').write_bytes(raw)
        for n, extra in enumerate([{}, {'baseline': 'input/previous.DOCX'}]):
            args = {'input': current, 'output': f'output/valid-{n}.json', 'mode': 'synthetic', **extra}
            answer = self.bridge.call('case_docx_review', args)
            self.assertTrue(answer['success'], answer)
            report = json.loads((self.work / args['output']).read_bytes())
            self.assertEqual(report['status'], 'needs_review')
            self.assertEqual(report['professional_review'], 'not_performed')
            if extra:
                self.assertEqual(report['baseline']['sha256'], sha(raw))
            else:
                self.assertEqual(report['comparison']['state'], 'not_requested')

    def test_next_chunk_reconstructs_unicode_json_without_copying_position_or_hash(self):
        value = {'status': 'blocked', 'unknown': None, 'text': '汉字🙂e\u0301"\\' * 7000, 'tail': 'end'}
        text = json.dumps(value, ensure_ascii=False)
        raw = (text + '\r\n').encode()
        (self.work / 'input/dense.json').write_bytes(raw)
        args = {'scope': 'workspace', 'path': 'input/dense.json'}
        parts, end = [], 0
        for _ in range(12):
            answer = self.bridge.call('case_read', args)
            self.assertTrue(answer['success'], answer)
            self.assertLessEqual(len(json.dumps(answer, ensure_ascii=False).encode()), 32000)
            result = answer['result']
            self.assertEqual(sha(raw), result['sha256'])
            self.assertEqual(end, result['start_column'])
            parts.extend(row['text'] for row in result['lines'])
            end = result['line_fragments'][-1]['to_column']
            if result['eof']:
                break
            args = {'scope': 'workspace', 'path': 'input/dense.json', 'next_chunk': True}
        else:
            self.fail('next_chunk did not reach EOF')
        self.assertEqual(text, ''.join(parts))
        self.assertEqual(value, json.loads(''.join(parts)))
        self.assertEqual('no_continuation_available', self.bridge.call('case_read', args)['error'])

    def test_next_chunk_does_not_correct_bad_explicit_hash_or_advance_on_error(self):
        (self.work / 'input/long.txt').write_bytes(b'x' * 48001)
        args = {'scope': 'workspace', 'path': 'input/long.txt'}
        first = self.bridge.call('case_read', args)['result']
        position = first['next_position']
        bad_hash = position['expected_sha256'][:33] + position['expected_sha256'][36:]
        self.assertEqual(61, len(bad_hash))
        rejected = self.bridge.call('case_read', {**args, **position, 'expected_sha256': bad_hash})
        self.assertEqual('invalid_expected_hash', rejected['error'])
        for mixed in [{'start_line': position['start_line']}, {'start_column': position['start_column']},
                      {'expected_sha256': bad_hash}, {'expected_sha256': position['expected_sha256']}]:
            answer = self.bridge.call('case_read', {**args, 'next_chunk': True, **mixed})
            self.assertEqual('continuation_position_conflict', answer['error'])
        second = self.bridge.call('case_read', {**args, 'next_chunk': True})
        self.assertTrue(second['success'], second)
        self.assertEqual(position['start_column'], second['result']['start_column'])
        self.assertEqual(sha(b'x' * 48001), second['result']['sha256'])

    def test_next_chunk_rejects_changed_source_and_unknown_or_finished_positions(self):
        args = {'scope': 'workspace', 'path': 'input/source.md', 'next_chunk': True, 'max_lines': 1}
        self.assertEqual('no_continuation_available', self.bridge.call('case_read', args)['error'])
        self.bridge.call('case_read', {key: value for key, value in args.items() if key != 'next_chunk'})
        (self.work / 'input/source.md').write_bytes(self.raw + b'changed')
        self.assertEqual('source_version_changed', self.bridge.call('case_read', args)['error'])
        self.assertNotIn('result', self.bridge.call('case_read', args))
        (self.work / 'input/source.md').write_bytes(self.raw)
        second = self.bridge.call('case_read', args)
        self.assertEqual(2, second['result']['start_line'])
        third = self.bridge.call('case_read', args)
        self.assertTrue(third['result']['eof'])
        self.assertEqual('no_continuation_available', self.bridge.call('case_read', args)['error'])

    def test_next_chunk_returned_metadata_mutation_cannot_change_server_pointer(self):
        raw = b'x' * 48001
        (self.work / 'input/long.txt').write_bytes(raw)
        args = {'scope': 'workspace', 'path': 'input/long.txt'}
        first = self.bridge.call('case_read', args)['result']
        start = first['next_position']['start_column']
        first['next_position'].update(start_column=0, expected_sha256='0' * 64)
        answer = self.bridge.call('case_read', {**args, 'next_chunk': True})
        self.assertTrue(answer['success'], answer)
        self.assertEqual(start, answer['result']['start_column'])
        self.assertEqual(sha(raw), answer['result']['sha256'])

    def test_next_chunk_is_scoped_to_path_and_validates_boolean(self):
        (self.work / 'input/other.md').write_bytes(b'a\nb\nc\n')
        a = {'scope': 'workspace', 'path': 'input/source.md', 'max_lines': 1}
        b = {'scope': 'workspace', 'path': 'input/other.md', 'max_lines': 1}
        self.bridge.call('case_read', a)
        self.assertEqual('no_continuation_available', self.bridge.call('case_read', {**b, 'next_chunk': True})['error'])
        self.bridge.call('case_read', b)
        self.assertEqual('正文', self.bridge.call('case_read', {**a, 'next_chunk': True})['result']['lines'][0]['text'])
        self.assertEqual('b', self.bridge.call('case_read', {**b, 'next_chunk': True})['result']['lines'][0]['text'])
        for value in [1, 'true', None]:
            self.assertEqual('invalid_next_chunk', self.bridge.call('case_read', {**a, 'next_chunk': value})['error'])

    def test_copied_ndjson_next_chunk_uses_same_instance_and_keeps_private_payloads_out(self):
        calls = [
            {'id': 'a', 'tool': 'case_read', 'arguments': {'scope': 'workspace', 'path': 'input/source.md', 'max_lines': 1}},
            {'id': 'b', 'tool': 'case_read', 'arguments': {'scope': 'workspace', 'path': 'input/source.md', 'max_lines': 1, 'next_chunk': True}},
        ]
        result = self.command('--package', str(self.package), '--workspace', str(self.work), '--control', str(self.control),
                              '--manifest-sha256', self.manifest,
                              input=b''.join((json.dumps(row) + '\n').encode() for row in calls))
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line)['answer'] for line in result.stdout.splitlines()]
        self.assertTrue(all(row['success'] for row in rows), rows)
        self.assertEqual([1, 2], [row['result']['start_line'] for row in rows])
        self.assertEqual([self.marker, '正文'], [row['result']['lines'][0]['text'] for row in rows])
        self.assertNotIn(self.marker.encode(), (self.control / 'call-0001.json').read_bytes())

    def put_spec(self, value):
        (self.work / 'input/spec.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def document(self):
        return self.bridge.call('case_documents', {'input': 'input/spec.json', 'output': 'output/doc', 'mode': 'synthetic'})

    def test_default_disk_and_memory_receipts_do_not_retain_payloads(self):
        read = self.bridge.call('case_read', {'scope': 'workspace', 'path': 'input/source.md'})
        written = self.bridge.call('case_write', {'path': 'work/draft.md', 'text': self.marker})
        (self.work / 'input/image.png').write_bytes(png())
        image = self.bridge.call('case_image', {'scope': 'workspace', 'path': 'input/image.png'})
        for number, answer in enumerate([read, written, image], 1):
            self.assertTrue(answer['success'], answer)
            raw = (self.control / f'call-{number:04}.json').read_bytes()
            row = json.loads(raw)
            self.assertEqual(row, self.bridge.calls[number - 1])
            self.assertNotIn(self.marker.encode(), raw)
            self.assertNotIn('arguments', row)
            self.assertNotIn('answer', row)
            self.assertFalse(row['payloads_recorded'])
            encoded = json.dumps(answer, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
            self.assertEqual(sha(encoded), row['answer_sha256'])
            self.assertNotIn(b'base64', raw)
        self.assertIn(self.marker, read['result']['lines'][0]['text'])
        self.assertIn('image_data_url', image['result'])

    def test_explicit_trace_opt_in_remains_available_for_authorized_evaluation(self):
        from evals.native_host_bridge import NativeHostBridge
        full = NativeHostBridge(self.package, self.work, self.control, self.manifest)
        answer = full.call('case_read', {'scope': 'workspace', 'path': 'input/source.md'})
        row = json.loads((self.control / 'call-0001.json').read_bytes())
        self.assertTrue(row['payloads_recorded'])
        self.assertEqual(answer, row['answer'])
        self.assertIn(self.marker, json.dumps(row, ensure_ascii=False))

    def test_root_recipe_bypass_is_rejected_by_worker_before_source_read(self):
        (self.work / 'controller.txt').write_bytes(self.raw)
        self.put_spec(self.spec(path='controller.txt'))
        answer = self.document()
        self.assertFalse(answer['success'], answer)
        self.assertEqual('worker_boundary_failure', answer['error'])
        self.assertFalse((self.work / 'output/doc').exists())
        audit = json.loads((self.control / 'tool-0001.audit.json').read_bytes())
        self.assertTrue(any(Path(row['path']) == self.work / 'controller.txt' for row in audit['blocked']))
        self.assertNotIn(self.marker.encode(), (self.control / 'tool-0001.audit.json').read_bytes())

    def test_valid_timestamp_unlisted_bytecode_cannot_replace_manifest_source(self):
        source = self.package / 'tools/core.py'
        cache = source.parent / '__pycache__'
        cache.mkdir(exist_ok=True)
        path = cache / ('core.' + sys.implementation.cache_tag + '.pyc')
        self.assertFalse(path.exists())
        raw = importlib.util.MAGIC_NUMBER + struct.pack('<III', 0, int(source.stat().st_mtime), source.stat().st_size)
        raw += marshal.dumps(compile('raise RuntimeError("SYNTHETIC-cache-must-not-run")', str(source), 'exec'))
        path.write_bytes(raw)
        try:
            self.put_spec(self.spec())
            answer = self.document()
            self.assertTrue(answer['success'], answer)
            audit = json.loads((self.control / 'tool-0001.audit.json').read_bytes())
            self.assertEqual('manifest_hash_bound_source_only_no_bytecode', audit['source_loading'])
            self.assertFalse(any(Path(row['path']) == path for row in audit['file_open_events']))
            self.assertEqual(raw, path.read_bytes())
        finally:
            path.unlink()  # Only this test-owned synthetic cache file.

    def test_worker_uses_base_interpreter_minimal_environment_and_actual_identity(self):
        self.put_spec(self.spec())
        real = subprocess.Popen
        observed = []
        def launch(command, **kwargs):
            process = real(command, **kwargs)
            observed.append((command, kwargs, process.pid))
            return process
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': 'SYNTHETIC-do-not-pass', 'HTTPS_PROXY': 'SYNTHETIC', 'PYTHONPATH': 'SYNTHETIC'}), \
                mock.patch('tools.host_bridge.subprocess.Popen', side_effect=launch):
            answer = self.document()
        self.assertTrue(answer['success'], answer)
        self.assertEqual(1, len(observed))
        command, options, pid = observed[0]
        self.assertEqual(BASE_PYTHON, command[0])
        self.assertEqual(['-I', '-S', '-B', '-X', 'utf8'], command[1:6])
        self.assertFalse({'OPENAI_API_KEY', 'HTTPS_PROXY', 'PYTHONPATH'} & set(options['env']))
        self.assertEqual('1', options['env']['PYTHONDONTWRITEBYTECODE'])
        audit = json.loads((self.control / 'tool-0001.audit.json').read_bytes())
        self.assertEqual(pid, audit['worker_pid'])
        self.assertEqual(sha((ROOT / 'tools/host_bridge_worker.py').read_bytes()), audit['worker_source_sha256'])
        self.assertFalse(list(self.control.glob('*.stdout')))
        self.assertFalse(list(self.control.glob('*.stderr')))

    def test_worker_cannot_write_into_input_even_with_bypassed_controller_job(self):
        value = example()
        source = self.work / 'input/fidelity.json'
        source.write_text(json.dumps(value), encoding='utf-8')
        before = source.read_bytes()
        audit = self.control / 'direct-worker.audit.json'
        job = self.control / 'direct-worker.job.json'
        job.write_text(json.dumps({'tool': 'case_fidelity', 'arguments': {'input': 'input/fidelity.json',
            'output': 'input/not-allowed.json', 'mode': 'synthetic'}, 'package': str(self.package),
            'workspace': str(self.work), 'audit': str(audit), 'expected_manifest_sha256': self.manifest}), encoding='utf-8')
        result = subprocess.run([BASE_PYTHON, '-I', '-S', '-B', '-X', 'utf8',
            str(self.package / 'tools/host_bridge_worker.py'), str(job)], cwd=self.work, capture_output=True, timeout=30)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.work / 'input/not-allowed.json').exists())
        self.assertEqual(before, source.read_bytes())
        proof = json.loads(audit.read_bytes())
        self.assertTrue(any(row.get('writing') and Path(row['path']) == self.work / 'input/not-allowed.json' for row in proof['blocked']))

    def test_reserved_control_artifacts_refuse_new_instance_before_directory_mutation(self):
        second = self.case / 'second'
        second.mkdir()
        (self.control / 'call-0001.json').write_bytes(b'SYNTHETIC-existing-receipt')
        with self.assertRaisesRegex(BridgeError, 'control_artifacts_exist'):
            HostToolBridge(self.package, second, self.control, self.manifest)
        self.assertEqual([], list(second.iterdir()))
        self.assertEqual(b'SYNTHETIC-existing-receipt', (self.control / 'call-0001.json').read_bytes())

    def test_late_control_collision_prevents_operation_without_overwrite(self):
        (self.control / 'call-0001.json').write_bytes(b'SYNTHETIC-other-owner')
        result = self.bridge.call('case_write', {'path': 'work/draft.md', 'text': self.marker})
        self.assertEqual('control_artifacts_exist', result['error'])
        self.assertEqual([], self.bridge.calls)
        self.assertFalse((self.work / 'work/draft.md').exists())
        self.assertEqual(b'SYNTHETIC-other-owner', (self.control / 'call-0001.json').read_bytes())

    def test_duplicate_native_callback_cannot_replay_mutation(self):
        params = {'callId': 'same-call', 'threadId': 't', 'turnId': 'u', 'tool': 'case_write',
                  'arguments': {'path': 'work/first.md', 'text': self.marker}}
        bad = self.bridge.native_tool_result(params, thread_id='other', turn_id='u')
        self.assertFalse(bad['success'])
        self.assertEqual([], self.bridge.calls)
        good = self.bridge.native_tool_result(params, thread_id='t', turn_id='u')
        self.assertTrue(good['success'])
        params['arguments']['path'] = 'work/replayed.md'
        twice = self.bridge.native_tool_result(params, thread_id='t', turn_id='u')
        self.assertEqual('duplicate_native_call', json.loads(twice['contentItems'][0]['text'])['error'])
        self.assertFalse((self.work / 'work/replayed.md').exists())
        self.assertEqual(1, len(self.bridge.calls))

    def command(self, *args, input=None):
        return subprocess.run([BASE_PYTHON, '-I', '-S', '-B', '-X', 'utf8', str(self.package / 'tools/host_bridge.py'), *args],
                              cwd=self.case, input=input, capture_output=True, timeout=30)

    def test_copied_entry_describes_eight_functions_from_foreign_cwd(self):
        result = self.command('--describe')
        self.assertEqual(0, result.returncode, result.stderr)
        tools = json.loads(result.stdout)['tools']
        self.assertEqual(10, len(tools))
        read = next(tool for tool in tools if tool['name'] == 'case_read')['inputSchema']
        self.assertEqual('boolean', read['properties']['next_chunk']['type'])
        self.assertEqual(['scope', 'path'], read['required'])
        self.assertFalse((self.package / 'evals').exists())
        for name in ['host_bridge.py', 'host_bridge_worker.py']:
            tree = ast.parse((self.package / 'tools' / name).read_text(encoding='utf-8'))
            imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(any(module and module.startswith('evals') for module in imports))

    def test_all_eight_real_tools_work_in_copied_ndjson_entry_and_keep_blocked_state(self):
        self.put_spec(self.spec())
        (self.work / 'input/image.png').write_bytes(png())
        fidelity = example()
        fidelity['assertions'][0]['formula'] = {'implies': ['permission', 'release']}
        (self.work / 'input/fidelity.json').write_text(json.dumps(fidelity), encoding='utf-8')
        calls = [
            ('case_read', {'scope': 'workspace', 'path': 'input/source.md'}),
            ('case_write', {'path': 'work/draft.md', 'text': self.marker}),
            ('case_info', {'scope': 'workspace', 'path': 'input/source.md'}),
            ('case_copy', {'scope': 'workspace', 'path': 'input/source.md', 'destination': 'output/copy.md', 'expected_sha256': sha(self.raw)}),
            ('case_image', {'scope': 'workspace', 'path': 'input/image.png'}),
            ('case_documents', {'input': 'input/spec.json', 'output': 'output/doc', 'mode': 'synthetic'}),
            ('case_docx_review', {'input': 'output/doc/body/document.docx', 'output': 'output/readback.json', 'mode': 'synthetic'}),
            ('case_fidelity', {'input': 'input/fidelity.json', 'output': 'output/fidelity.json', 'mode': 'synthetic'}),
        ]
        requests = [{'id': str(i), 'tool': tool, 'arguments': args} for i, (tool, args) in enumerate(calls)]
        requests += [{'id': '1', 'tool': 'case_write', 'arguments': {'path': 'work/replayed.md', 'text': self.marker}}]
        raw = b''.join((json.dumps(value, ensure_ascii=False) + '\n').encode() for value in requests)
        result = self.command('--package', str(self.package), '--workspace', str(self.work), '--control', str(self.control),
                              '--manifest-sha256', self.manifest, '--max-calls', '8', input=raw)
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(9, len(rows))
        self.assertTrue(all(row['answer']['success'] for row in rows[:8]), rows)
        self.assertFalse(rows[8]['answer']['success'])
        self.assertFalse((self.work / 'work/replayed.md').exists())
        self.assertEqual('blocked', rows[7]['answer']['result']['review_status'])
        self.assertEqual('needs_review', rows[6]['answer']['result']['review_status'])
        self.assertEqual('内部备注\n', (self.work / 'output/doc/internal/notes.txt').read_text(encoding='utf-8'))
        self.assertEqual(0, rows[7]['answer']['execution_budget']['tool_calls_remaining'])
        self.assertEqual(8, len(list(self.control.glob('call-*.json'))))
        for path in self.control.glob('call-*.json'):
            self.assertNotIn(self.marker.encode(), path.read_bytes())
        for path in self.control.glob('*.audit.json'):
            audit = json.loads(path.read_bytes())
            self.assertFalse(audit['blocked'])
            self.assertTrue(all(Path(value).is_relative_to(self.package) for value in audit['loaded_tools_modules'].values()))

    def test_invalid_transport_and_duplicate_json_keys_never_execute(self):
        raw = b'{"id":"x","id":"y","tool":"case_write","arguments":{"path":"work/bad.md","text":"bad"}}\n'
        result = self.command('--package', str(self.package), '--workspace', str(self.work), '--control', str(self.control),
                              '--manifest-sha256', self.manifest, input=raw)
        self.assertEqual(0, result.returncode)
        self.assertFalse(json.loads(result.stdout)['answer']['success'])
        self.assertFalse((self.work / 'work/bad.md').exists())
        self.assertFalse(list(self.control.glob('call-*.json')))

    def test_bad_manifest_binding_never_opens_tool_input(self):
        result = self.command('--package', str(self.package), '--workspace', str(self.work), '--control', str(self.control),
                              '--manifest-sha256', '0' * 64, input=b'')
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)['success'])
        self.assertEqual([], list(self.control.iterdir()))

    def test_default_update_preimage_is_explicit_private_artifact_not_receipt(self):
        first = self.bridge.call('case_write', {'path': 'work/draft.md', 'text': self.marker})
        second = self.bridge.call('case_write', {'path': 'work/draft.md', 'text': 'changed',
                                               'expected_sha256': first['result']['sha256']})
        self.assertTrue(second['success'], second)
        self.assertEqual(self.marker.encode(), (self.control / 'write-0002.before').read_bytes())
        self.assertNotIn(self.marker.encode(), (self.control / 'call-0002.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
