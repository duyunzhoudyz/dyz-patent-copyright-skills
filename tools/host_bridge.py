"""Bounded local case tools for controllers; no model, RPC or shell launcher.

Only the frozen package and explicit input/work/output roots are tool-readable.
The controller owns the roots and must prevent concurrent replacement. These
checks are not an OS sandbox or a claim about native-runtime internal I/O.
"""
from __future__ import annotations

import base64
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import subprocess
import sys
import tempfile
import threading

if __package__ in {None, ''}:
    # Explicit file entry point also works from a copied package/foreign cwd.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.bundle import BundleError, MANIFEST_NAME, _absolute, verify_bundle
from tools.core import is_macos_system_root_symlink

MAX_FILE = 5_000_000
MAX_WORKER_STREAM_BYTES = 8_000_000
TEXT_WRITE_SUFFIXES = frozenset({'.txt', '.md', '.json', '.jsonl', '.csv', '.tsv', '.xml', '.yaml', '.yml', '.toml', '.rst'})
MAX_SEGMENT = 48_000
READ_RESPONSE_BUDGET = 32_000
MAX_LINES = 120
WRITABLE = {'work', 'output'}
READABLE = WRITABLE | {'input'}
TOOL_NAMES = frozenset({'case_read', 'case_write', 'case_info', 'case_copy',
                        'case_image', 'case_documents', 'case_docx_review', 'case_fidelity',
                        'case_standard_package', 'case_software'})


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _worker_environment():
    # No provider keys, proxy, Python path, account/session or application env.
    keep = {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'SYSTEMDRIVE'}
    if os.name != 'nt':
        keep |= {'LANG', 'LC_ALL'}
    return {**{key: value for key, value in os.environ.items() if key.upper() in keep},
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}


class BridgeError(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, code):
    if not condition:
        raise BridgeError(code)


def _regular_chain(path, *, missing=False):
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            _require(missing, 'file_missing')
            continue
        is_link = item.is_symlink() or bool(
            getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
        if is_link:
            if item != path and is_macos_system_root_symlink(item):
                try:
                    info = item.stat()
                except OSError:
                    _require(False, 'reparse_path')
            else:
                _require(False, 'reparse_path')
        if item != path:
            _require(stat.S_ISDIR(info.st_mode), 'parent_not_directory')
        elif not stat.S_ISDIR(info.st_mode):
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'nonregular_or_aliased_file')

def _collect_worker_output(process, *, limit=MAX_WORKER_STREAM_BYTES, timeout=30):
    buffers = [bytearray(), bytearray()]
    errors = [None, None]

    def read_pipe(index, pipe):
        captured = buffers[index]
        try:
            while chunk := pipe.read(min(65536, limit + 1 - len(captured))):
                captured.extend(chunk)
                if len(captured) > limit:
                    errors[index] = 'worker_output_limit_exceeded'
                    process.kill()
                    break
        except OSError:
            if errors[index] is None:
                errors[index] = 'worker_output_read_failed'

    readers = [threading.Thread(target=read_pipe, args=(i, pipe), daemon=True)
               for i, pipe in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=2)
    _require(not any(reader.is_alive() for reader in readers), 'worker_output_read_failed')
    if timed_out:
        error = 'worker_timeout_partial_output_may_remain'
    elif 'worker_output_limit_exceeded' in errors:
        error = 'worker_output_limit_exceeded'
    else:
        error = next((error for error in errors if error), None)
    for buffer in buffers:
        del buffer[limit:]
    return buffers[0], buffers[1], error


class HostToolBridge:
    def __init__(self, package, workspace, control, expected_manifest_sha256, *, max_calls=120,
                 image_views=(), record_payloads=False):
        try:
            self.package, self.workspace, self.control = map(_absolute, (package, workspace, control))
        except BundleError:
            raise BridgeError('unsafe_path') from None
        for path in (self.package, self.workspace, self.control):
            _regular_chain(path)
            _require(path.is_dir(), 'root_not_directory')
        roots = [self.package.resolve(), self.workspace.resolve(), self.control.resolve()]
        _require(all(not a.is_relative_to(b) for a in roots for b in roots if a != b)
                 and len(set(roots)) == 3, 'roots_overlap')
        _require(type(record_payloads) is bool, 'invalid_recording_policy')
        _require(not any(re.fullmatch(r'(?:call-\d+\.json|write-\d+\.before|tool-\d+\..+)', item.name)
                         for item in self.control.iterdir()), 'control_artifacts_exist')
        self.record_payloads = record_payloads
        self.expected = expected_manifest_sha256
        verify_bundle(self.package, expected_manifest_sha256=self.expected)
        manifest = json.loads((self.package / MANIFEST_NAME).read_bytes())
        self.package_files = {row['path'] for row in manifest['files']} | {MANIFEST_NAME}
        self.package_hashes = {row['path']: row['sha256'] for row in manifest['files']}
        self.package_hashes[MANIFEST_NAME] = expected_manifest_sha256
        _require(type(max_calls) is int and max_calls > 0, 'invalid_call_limit')
        self.max_calls = max_calls
        self.calls = []
        self.lock = threading.RLock()
        self.native_calls = set()
        self._read_positions = {}
        for name in ('work', 'output'):
            path = self.workspace / name
            if not path.exists():
                path.mkdir()
            _regular_chain(path)
        self.image_views = {}
        view_keys = {'source_sha256','source_width','source_height','view_sha256','view_width','view_height','view_path','provenance'}
        for view in image_views:
            _require(isinstance(view,dict) and set(view)==view_keys, 'image_view_fields')
            _require(all(isinstance(view[k],str) and re.fullmatch('[0-9a-f]{64}',view[k]) for k in ('source_sha256','view_sha256')),
                     'image_view_hash')
            _require(all(type(view[k]) is int and 0 < view[k] <= 20000 for k in ('source_width','source_height','view_width','view_height')),
                     'image_view_dimensions')
            _require(max(view['view_width'],view['view_height']) <= 2048
                     and ((view['view_width']+31)//32)*((view['view_height']+31)//32) <= 2500,
                     'image_view_exceeds_native_high_detail')
            _require(view['provenance']=='codex-0.160.1-high-detail-prepared_observed', 'image_view_provenance')
            path=Path(view['view_path']);_regular_chain(path)
            _require(path.is_absolute() and (path.resolve().is_relative_to(self.control.resolve())
                     or path.resolve().is_relative_to((self.control.parent/'image-views').resolve())), 'image_view_outside_control')
            raw=path.read_bytes()
            _require(_sha(raw)==view['view_sha256'] and raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24
                     and raw[12:16]==b'IHDR' and len(raw)<=2_000_000, 'image_view_file_changed')
            _require((int.from_bytes(raw[16:20],'big'),int.from_bytes(raw[20:24],'big'))==(view['view_width'],view['view_height']),
                     'image_view_header_mismatch')
            _require(view['source_sha256'] not in self.image_views, 'duplicate_image_view_source')
            self.image_views[view['source_sha256']] = (dict(view),raw)

    def _path(self, scope, relative, *, writing=False, missing=False):
        _require(isinstance(relative, str) and relative, 'relative_path_required')
        _require(not PureWindowsPath(relative).drive and not relative.startswith(('/', '\\'))
                 and ':' not in relative and '\x00' not in relative, 'unsafe_path')
        pieces = relative.replace('\\', '/').split('/')
        _require(all(p and p not in {'.', '..'} and not p.startswith('.') for p in pieces), 'unsafe_path')
        relative = '/'.join(pieces)
        if scope == 'package':
            _require(not writing and relative in self.package_files, 'package_path_not_allowed')
            base = self.package
        else:
            _require(scope == 'workspace', 'unknown_scope')
            _require(pieces[0] in (WRITABLE if writing else READABLE), 'workspace_path_not_allowed')
            base = self.workspace
        path = base.joinpath(*pieces)
        _regular_chain(path, missing=missing)
        _require(path.resolve(strict=not missing).is_relative_to(base.resolve()), 'path_outside_root')
        return path

    def _bytes(self, scope, relative):
        path = self._path(scope, relative)
        _require(path.is_file() and path.stat().st_size <= MAX_FILE, 'file_size_or_kind')
        with path.open('rb') as file:
            raw = file.read(MAX_FILE + 1)
        _require(len(raw) <= MAX_FILE, 'file_size_or_kind')
        if scope == 'package':
            _require(_sha(raw) == self.package_hashes[relative.replace('\\', '/')], 'package_file_changed')
        return raw

    @staticmethod
    def _keys(args, required, optional=()):
        _require(isinstance(args, dict) and set(required) <= set(args)
                 and set(args) <= set(required) | set(optional), 'invalid_arguments')

    def _execution_budget(self, used):
        # Per-process admitted calls, including registered failures. No caller input.
        return {'max_tool_calls': self.max_calls, 'tool_calls_used': used,
                'tool_calls_remaining': max(0, self.max_calls - used)}

    def _read(self, a):
        self._keys(a, {'scope', 'path'}, {'start_line', 'max_lines', 'start_column', 'expected_sha256', 'next_chunk'})
        next_chunk = a.get('next_chunk', False)
        _require(type(next_chunk) is bool, 'invalid_next_chunk')
        if next_chunk:
            _require(not {'start_line', 'start_column', 'expected_sha256'} & set(a), 'continuation_position_conflict')
        raw = self._bytes(a['scope'], a['path'])
        source_hash = _sha(raw)
        key = (a['scope'], a['path'].replace('\\', '/'))
        if next_chunk:
            position = self._read_positions.get(key)
            _require(position is not None, 'no_continuation_available')
            _require(position['expected_sha256'] == source_hash, 'source_version_changed')
            start, column = position['start_line'], position['start_column']
        else:
            start, column = a.get('start_line', 1), a.get('start_column', 0)
        lines = raw.decode('utf-8').splitlines()
        count = a.get('max_lines', 80)
        _require(type(start) is int and 1 <= start <= max(1, len(lines))
                 and type(count) is int and 1 <= count <= MAX_LINES, 'invalid_line_range')
        _require(type(column) is int and column >= 0 and (column==0 or lines and column<len(lines[start-1])), 'invalid_column_range')
        if column > 0 and not next_chunk:
            _require('expected_sha256' in a, 'fragment_source_hash_required')
        if 'expected_sha256' in a:
            expected=a['expected_sha256']
            _require(isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected), 'invalid_expected_hash')
            _require(expected==source_hash,'source_version_changed')

        def payload(rows,fragments):
            if fragments:
                last=fragments[-1]
                line_done=last['to_column']==last['total_columns']
                next_line=last['line']+1 if line_done else last['line']
                next_column=0 if line_done else last['to_column']
            else:next_line,next_column=1,0
            eof=not lines or next_line>len(lines)
            limited=bool(fragments and (fragments[-1]['to_column']<fragments[-1]['total_columns']
                         or len(fragments)<min(count,len(lines)-start+1)))
            return {'sha256':source_hash,'total_lines':len(lines),'start_line':start,'start_column':column,
                'end_line':fragments[-1]['line'] if fragments else start-1,'eof':eof,'budget_limited':limited,
                'response_budget_utf8_bytes':READ_RESPONSE_BUDGET,
                'next_position':None if eof else {'start_line':next_line,'start_column':next_column,'expected_sha256':source_hash},
                'column_unit':'zero_based_unicode_codepoints_end_exclusive','line_fragments':fragments,'lines':rows}

        def fits(value):
            # Bound the real tool text, including JSON escapes and metadata.
            return len(json.dumps({'success':True,'result':value,
                'execution_budget':self._execution_budget(len(self.calls)+1)},ensure_ascii=False).encode('utf-8'))<=READ_RESPONSE_BUDGET

        rows,fragments=[],[]
        for index in range(start-1,min(len(lines),start-1+count)):
            text=lines[index];begin=column if index==start-1 else 0
            def candidate(length):
                row={'number':index+1,'text':text[begin:begin+length]}
                fragment={'line':index+1,'from_column':begin,'to_column':begin+length,'total_columns':len(text)}
                return row,fragment,payload(rows+[row],fragments+[fragment])
            remaining=len(text)-begin
            row,fragment,value=candidate(min(remaining,READ_RESPONSE_BUDGET))
            if remaining<=READ_RESPONSE_BUDGET and fits(value):
                rows.append(row);fragments.append(fragment);continue
            low,high,best=1,min(remaining,READ_RESPONSE_BUDGET),None
            while low<=high:
                length=(low+high)//2
                row,fragment,value=candidate(length)
                if fits(value):best=(row,fragment);low=length+1
                else:high=length-1
            if best is not None:
                rows.append(best[0]);fragments.append(best[1])
            _require(bool(rows),'read_metadata_exceeds_budget')
            break
        result=payload(rows,fragments)
        _require(fits(result) and len(json.dumps({'success':True,'result':result,
                 'execution_budget':self._execution_budget(len(self.calls)+1)},ensure_ascii=False).encode('utf-8'))<=MAX_SEGMENT,
                 'read_response_exceeds_budget')
        # The returned dictionary belongs to the caller; keep a separate binding.
        position = result['next_position']
        self._read_positions[key] = dict(position) if position is not None else None
        return result

    def _write(self, a):
        self._keys(a, {'path', 'text'}, {'expected_sha256'})
        _require(isinstance(a['text'], str), 'text_required')
        raw = a['text'].encode('utf-8')
        _require(len(raw) <= MAX_FILE, 'file_size_or_kind')
        path = self._path('workspace', a['path'], writing=True, missing=True)
        _require(path.suffix.lower() in TEXT_WRITE_SUFFIXES, 'text_file_required')
        expected = a.get('expected_sha256')
        if expected is None:
            _require(not path.exists(), 'destination_exists')
            path.parent.mkdir(parents=True, exist_ok=True)
            _regular_chain(path.parent)
            with path.open('xb') as file:
                file.write(raw)
        else:
            _require(isinstance(expected, str) and len(expected) == 64, 'invalid_expected_hash')
            previous = self._bytes('workspace', a['path'])
            _require(_sha(previous) == expected, 'source_version_changed')
            backup = self.control / f'write-{len(self.calls) + 1:04}.before'
            with backup.open('xb') as file:
                file.write(previous)
            handle, temporary = tempfile.mkstemp(prefix='.bridge-write-', dir=path.parent)
            staging = Path(temporary)
            try:
                with os.fdopen(handle, 'wb') as file:
                    file.write(raw)
                _regular_chain(path)
                _require(_sha(path.read_bytes()) == expected, 'source_version_changed')
                os.replace(staging, path)
            finally:
                staging.unlink(missing_ok=True)
        return {'path': a['path'], 'sha256': _sha(raw), 'bytes': len(raw),
                'previous_sha256': expected, 'status': 'local_text_written'}

    def _info(self, a):
        self._keys(a, {'scope', 'path'})
        raw = self._bytes(a['scope'], a['path'])
        return {'path': a['path'], 'sha256': _sha(raw), 'bytes': len(raw)}

    def _copy(self, a):
        self._keys(a, {'scope', 'path', 'destination', 'expected_sha256'})
        raw = self._bytes(a['scope'], a['path'])
        _require(_sha(raw) == a['expected_sha256'], 'source_version_changed')
        target = self._path('workspace', a['destination'], writing=True, missing=True)
        _require(not target.exists(), 'destination_exists')
        target.parent.mkdir(parents=True, exist_ok=True)
        _regular_chain(target.parent)
        with target.open('xb') as file:
            file.write(raw)
        return {'path': a['destination'], 'sha256': _sha(raw), 'bytes': len(raw)}

    def _image(self, a):
        self._keys(a, {'scope', 'path'})
        raw = self._bytes(a['scope'], a['path'])
        _require(raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw) >= 24
                 and raw[12:16] == b'IHDR' and len(raw) <= 2_000_000, 'bounded_png_required')
        width, height = int.from_bytes(raw[16:20], 'big'), int.from_bytes(raw[20:24], 'big')
        _require(0 < width <= 20000 and 0 < height <= 20000, 'bounded_png_required')
        view = self.image_views.get(_sha(raw))
        view_raw, view_metadata = raw, None
        if view is not None:
            policy,view_raw=view
            _require((width,height)==(policy['source_width'],policy['source_height']), 'image_view_source_dimensions')
            view_metadata={'sha256':policy['view_sha256'],'bytes':len(view_raw),'width':policy['view_width'],'height':policy['view_height'],
                           'kind':'frozen_reviewed_native_prepared_view','provenance':policy['provenance'],
                           'original_resolution_bytes_in_image_content':False}
        return {'path': a['path'], 'sha256': _sha(raw), 'bytes': len(raw),
                'width': width, 'height': height,
                'dimension_scope': 'original_source_png',
                **({'image_view':view_metadata} if view_metadata is not None else {}),
                'validation': 'signature_and_dimensions_only_not_full_image_or_provenance_validation',
                'image_data_url': 'data:image/png;base64,' + base64.b64encode(view_raw).decode('ascii')}

    def _software_tool(self, a):
        self._keys(a, {'action'}, {'authorization', 'authorization_sha256', 'output', 'answers', 'root', 'candidates'})
        _require(isinstance(a['action'], str) and a['action'] in {'prepare', 'build', 'verify', 'intake'},
                 'software_action_invalid')
        _require(a.get('root', '.') == '.', 'software_case_root_required')
        if a['action'] == 'intake':
            _require('candidates' not in a or type(a['candidates']) is bool, 'invalid_arguments')
            _require(not {'authorization', 'authorization_sha256'} & set(a) and 'output' in a,
                     'invalid_arguments')
            answers = a.get('answers', [])
            _require(isinstance(answers, list) and len(answers) <= 1000
                     and all(isinstance(value, str) for value in answers), 'intake_answers_invalid')
            target = self._path('workspace', a['output'], writing=True, missing=True)
            _require(a['output'].replace('\\', '/').split('/')[0] == 'output', 'output_root_required')
            _require(target.parent.is_dir(), 'output_parent_missing')
            _require(not target.exists(), 'output_exists')
        else:
            _require({'authorization', 'authorization_sha256'} <= set(a)
                     and not {'answers', 'output', 'candidates'} & set(a), 'invalid_arguments')
            expected = a['authorization_sha256']
            _require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
                     'invalid_expected_sha256')
            source = self._path('workspace', a['authorization'])
            _require(source.is_file() and source.suffix.lower() == '.json'
                     and source.stat().st_size <= 1_000_000, 'software_authorization_json_required')
        return self._worker_tool('case_software', a)

    def _file_tool(self, tool, a):
        optional = {'verify'} if tool in {'case_documents', 'case_standard_package'} else ({'baseline', 'summary'} if tool == 'case_docx_review' else set())
        self._keys(a, {'input', 'output', 'mode'}, optional)
        if tool == 'case_standard_package':
            _require(a['mode'] == 'synthetic', 'standard_authorized_case_unsupported')
            _require('verify' not in a or type(a['verify']) is bool, 'invalid_arguments')
        _require(a['mode'] in {'synthetic', 'research_example'}, 'unsupported_mode')
        source = self._path('workspace', a['input'])
        if tool == 'case_standard_package':
            _require(source.is_file() and source.suffix.lower() == '.json'
                     and source.stat().st_size <= MAX_FILE, 'standard_json_input_required')
        if tool == 'case_docx_review':
            _require(source.is_file() and source.suffix.lower() == '.docx', 'current_docx_required')
        output = self._path('workspace', a['output'], writing=True, missing=True)
        _require(a['output'].replace('\\', '/').split('/')[0] == 'output', 'output_root_required')
        if 'verify' in a:
            _require(type(a['verify']) is bool, 'invalid_arguments')
        if 'summary' in a:
            _require(type(a['summary']) is bool, 'invalid_arguments')
        if 'baseline' in a:
            baseline = self._path('workspace', a['baseline'])
            _require(baseline.is_file() and baseline.suffix.lower() == '.docx', 'baseline_docx_required')
        if tool == 'case_fidelity':
            _require(a['mode'] == 'synthetic', 'synthetic_only')
        _require(output.parent.is_dir(), 'output_parent_missing')
        if tool == 'case_standard_package':
            _require(source != output and not source.is_relative_to(output), 'standard_source_output_collision')
            _require(output.is_dir() if a.get('verify', False) else not output.exists(),
                     'standard_output_missing' if a.get('verify', False) else 'output_exists')
        return self._worker_tool(tool, a)

    def _worker_tool(self, tool, a):
        verify_bundle(self.package, expected_manifest_sha256=self.expected)
        number = len(self.calls) + 1
        job = self.control / f'tool-{number:04}.job.json'
        audit = self.control / f'tool-{number:04}.audit.json'
        request = {'tool': tool, 'arguments': a, 'package': str(self.package),
                   'workspace': str(self.workspace), 'audit': str(audit),
                   'expected_manifest_sha256': self.expected}
        with job.open('x', encoding='utf-8') as file:
            json.dump(request, file, ensure_ascii=False)
        worker = Path(__file__).with_name('host_bridge_worker.py')
        _regular_chain(worker)
        worker_hash = _sha(worker.read_bytes())
        # A venv launcher can outlive/lose its child on timeout. Own the base
        # interpreter directly, and bind the audit to this actual Popen PID.
        command = [getattr(sys, '_base_executable', None) or sys.executable,
                   '-I', '-S', '-B', '-X', 'utf8', str(worker), str(job)]
        with subprocess.Popen(command, cwd=self.workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=_worker_environment(), bufsize=0,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
            stdout, stderr, output_error = _collect_worker_output(process, limit=MAX_WORKER_STREAM_BYTES)
            returncode, worker_pid = process.returncode, process.pid
        if self.record_payloads:
            (self.control / f'tool-{number:04}.stdout').write_bytes(stdout)
            (self.control / f'tool-{number:04}.stderr').write_bytes(stderr)
        _require(output_error is None, output_error)
        _require(_sha(worker.read_bytes()) == worker_hash, 'worker_source_changed')
        _require(audit.is_file(), 'worker_audit_missing')
        proof = json.loads(audit.read_bytes())
        _require(not proof['blocked'] and proof['unexpected_exception'] is None, 'worker_boundary_failure')
        _require(proof['worker_pid'] == worker_pid and proof['worker_source_sha256'] == worker_hash,
                 'worker_identity_mismatch')
        _require(proof['exit_code'] == returncode, 'worker_exit_code_mismatch')
        answer = {'exit_code': returncode, 'stdout': stdout.decode('utf-8'),
                  'stderr': stderr.decode('utf-8'), 'worker_audit_sha256': _sha(audit.read_bytes()),
                  'status': 'tool_completed_needs_review' if returncode == 0 else 'tool_rejected_or_io_failure'}
        if tool == 'case_software':
            if proof.get('contract_error') is not None:
                diagnostic = proof['contract_error']
                _require(returncode == 2 and answer['stdout'].strip() == 'software_contract_rejected'
                         and not answer['stderr'] and isinstance(diagnostic, str)
                         and re.fullmatch('[a-z][a-z0-9_]{0,100}', diagnostic),
                         'worker_contract_diagnostic_invalid')
                answer['contract_error'] = diagnostic
            elif returncode in {0, 4}:
                summary = json.loads(answer['stdout'])
                answer.update(report_summary=summary, review_status=summary['status'],
                              stdout='', stdout_format='parsed_into_report_summary')
                answer['status'] = summary['status']
            return answer
        if proof.get('contract_error') is not None:
            _require(tool == 'case_documents' and a.get('verify') is True and returncode == 2
                     and answer['stdout'].strip() == 'document_contract_rejected' and not answer['stderr']
                     and proof['contract_error'] == 'document_input_binding_changed', 'worker_contract_diagnostic_invalid')
            answer['contract_error'] = proof['contract_error']
        if returncode == 0:
            if tool in {'case_fidelity', 'case_docx_review', 'case_standard_package'}:
                summary = json.loads(answer['stdout'])
                answer['report_summary'] = summary
                answer['review_status'] = summary['status']
                if tool == 'case_docx_review' and a.get('summary') is True:
                    # Keep the bounded excerpts once; raw stdout repeats the same JSON.
                    answer['stdout'] = ''
                    answer['stdout_format'] = 'parsed_into_report_summary'
            else:
                answer['review_status'] = 'needs_review'
        return answer

    def call(self, name, arguments):
        with self.lock:
            if len(self.calls) >= self.max_calls:
                return {'success': False, 'error': 'tool_call_limit',
                        'execution_budget': self._execution_budget(len(self.calls))}
            number = len(self.calls) + 1
            if any((self.control / suffix).exists() for suffix in (
                    f'call-{number:04}.json', f'write-{number:04}.before',
                    f'tool-{number:04}.job.json', f'tool-{number:04}.audit.json',
                    f'tool-{number:04}.stdout', f'tool-{number:04}.stderr')):
                return {'success': False, 'error': 'control_artifacts_exist',
                        'execution_budget': self._execution_budget(len(self.calls))}
            handlers = {'case_read': self._read, 'case_write': self._write, 'case_info': self._info,
                        'case_copy': self._copy, 'case_image': self._image,
                        'case_software': self._software_tool}
            request_hash = None
            try:
                request_hash = _sha(_json_bytes({'tool': name, 'arguments': arguments}))
                _require(isinstance(name, str), 'unknown_tool')
                if name in handlers:
                    payload = handlers[name](arguments)
                else:
                    _require(name in {'case_documents', 'case_docx_review', 'case_fidelity',
                                      'case_standard_package'}, 'unknown_tool')
                    payload = self._file_tool(name, arguments)
                answer = {'success': payload.get('exit_code', 0) == 0, 'result': payload}
                if not answer['success'] and 'contract_error' in payload:
                    answer['error'] = payload['contract_error']
            except BridgeError as error:
                answer = {'success': False, 'error': str(error)}
            except (OSError, UnicodeError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
                answer = {'success': False, 'error': 'io_encoding_or_contract_error', 'exception_type': type(error).__name__}
            answer['execution_budget'] = self._execution_budget(len(self.calls) + 1)
            record = {'ordinal': len(self.calls) + 1, 'tool': name if isinstance(name, str) and name in TOOL_NAMES else None,
                      'request_sha256': request_hash, 'answer_sha256': _sha(_json_bytes(answer)),
                      'success': answer['success'], 'error': answer.get('error'),
                      'execution_budget': answer['execution_budget'], 'payloads_recorded': self.record_payloads}
            if self.record_payloads:
                record.update(arguments=arguments, answer=answer)
            with (self.control / f'call-{record["ordinal"]:04}.json').open('x', encoding='utf-8') as file:
                json.dump(record, file, ensure_ascii=False, indent=2)
            self.calls.append(record)
            return answer

    def native_tool_result(self, params, *, thread_id, turn_id):
        """Return the actual native ToolCallResponse shape, bound to one session.

        The RPC controller must retain every inbound/outbound frame, including
        rejections before call(). No cross-thread execution or implicit RPC is
        performed here. Operational success preserves the report's own status.
        """
        try:
            self._keys(params, {'arguments', 'callId', 'threadId', 'tool', 'turnId'}, {'namespace'})
            _require(all(isinstance(params[k], str) and params[k] for k in ('callId', 'threadId', 'turnId', 'tool')),
                     'invalid_native_call_identity')
            _require(isinstance(thread_id, str) and thread_id and isinstance(turn_id, str) and turn_id,
                     'native_session_not_bound')
            _require(params['threadId'] == thread_id and params['turnId'] == turn_id,
                     'native_session_mismatch')
            _require(params.get('namespace') is None or isinstance(params['namespace'], str),
                     'invalid_native_namespace')
            with self.lock:
                identity = (thread_id, turn_id, params['callId'])
                _require(identity not in self.native_calls, 'duplicate_native_call')
                self.native_calls.add(identity)
                answer = self.call(params['tool'], params['arguments'])
        except BridgeError as error:
            answer = {'success': False, 'error': str(error)}
        image_url = None
        if answer['success'] and isinstance(answer.get('result'), dict):
            result = dict(answer['result'])
            image_url = result.pop('image_data_url', None)
            answer = {**answer, 'result': result}
        items = [{'type': 'inputText', 'text': json.dumps(answer, ensure_ascii=False)}]
        if image_url is not None:
            items.append({'type': 'inputImage', 'imageUrl': image_url})
        return {'success': answer['success'], 'contentItems': items}


def dynamic_tools():
    """Use the actual native DynamicToolSpec function variant; no freeform shell."""
    scope = {'type': 'string', 'enum': ['package', 'workspace']}
    text = {'type': 'string'}
    mode = {'type': 'string', 'enum': ['synthetic', 'research_example']}
    specs = [
        ('case_read', 'Read UTF-8 with exact source hash and explicit numbered line/column coverage. start_line>=1; max_lines=1..120 (default80). Tool text is bounded to32000 UTF-8 bytes within the48000 hard limit; a long line may return only a declared fragment. When next_position is not null, prefer next_chunk:true with the same scope/path and optional max_lines, omitting start_line/start_column/expected_sha256. The same bridge remembers the exact next position and rechecks its source hash; changed bytes are rejected. Alternatively copy every next_position field exactly; supplied malformed hashes are never corrected. Columns count Unicode codepoints, zero-based with exclusive end, not UTF-8 bytes. Metadata/hash/one fragment does not mean full reading. Paths are relative: package is frozen installed tree; workspace permits input/, work/, output/ only.',
         {'scope': scope, 'path': text,
          'next_chunk': {'type': 'boolean', 'description': 'Continue the same scope/path from its last successful next_position in this bridge. Omit all explicit position/hash fields; no prior read, EOF or changed source is rejected.'},
          'start_line': {'type': 'integer', 'minimum': 1, 'description': 'First physical line, integer at least1; default1.'},
          'start_column': {'type':'integer','minimum':0,'description':'Zero-based Unicode codepoint column of first line; default0. For a returned same-line continuation use next_position.start_column plus its expected_sha256.'},
          'expected_sha256': {'type':'string','pattern':'^[0-9a-f]{64}$','description':'Exact current source SHA-256,64 lowercase hexadecimal characters. Required for start_column>0; copy it from next_position to prevent mixing source versions.'},
          'max_lines': {'type': 'integer', 'minimum': 1, 'maximum': MAX_LINES,
                        'description': 'Integer from1 through120 inclusive; default80. Larger values are rejected.'}}, ['scope', 'path']),
        ('case_write', 'Create local UTF-8 text in work/ or output/. Updating an existing text file requires its current expected_sha256 and preserves a controller preimage. Input and installed files cannot be changed. This does not generate binary Word/PDF/image files.',
         {'path': text, 'text': text, 'expected_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$',
            'description': 'For updates only, the exact current64 lowercase hexadecimal SHA-256 characters. Omit when creating a new file.'}}, ['path', 'text']),
        ('case_info', 'Return size and exact SHA-256 of one permitted file; no directory enumeration or implicit version approval.',
         {'scope': scope, 'path': text}, ['scope', 'path']),
        ('case_copy', 'Copy one approved file into a new work/ or output/ path, requiring the exact source SHA-256. It preserves bytes and refuses overwrite.',
         {'scope': scope, 'path': text, 'destination': text, 'expected_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$',
            'description': 'The exact current source SHA-256:64 lowercase hexadecimal characters.'}}, ['scope', 'path', 'destination', 'expected_sha256']),
        ('case_image', 'Read one approved bounded PNG as image content with its path/hash. Signature/dimension checks do not authenticate its source or completeness.',
         {'scope': scope, 'path': text}, ['scope', 'path']),
        ('case_documents', 'Run the frozen installed document tool on a local JSON recipe, preserving its synthetic/research_example classification. Build requires a new output/ directory. verify=true checks a bundle against its generating recipe, not a different version. Compare versions with case_docx_review on actual DOCX files. No PDF conversion or arbitrary program execution.',
         {'input': {'type': 'string', 'description': 'Workspace JSON recipe for this bundle. With verify=true use its generating recipe/version, whose canonical input hash is bound in the output manifest; another version is not a comparison baseline.'},
          'output': {'type': 'string', 'description': 'Workspace bundle directory under output/. New for build; with verify=true use the directory generated from the supplied input. Check an old version against its own directory.'},
          'mode': mode,
          'verify': {'type': 'boolean', 'description': 'True: read-only check of this recipe/output pair. False or omitted: build. For version differences use case_docx_review with the actual current and previous DOCX files.'}}, ['input', 'output', 'mode']),
        ('case_standard_package', 'Build or read-only verify an internal five-document standard package from a contract_version=2 synthetic JSON recipe. Explicit synthetic mode only; real-material admission is unsupported and never relabeled. Frozen local modules only; no network, Office, PDF conversion, professional approval or external action.',
         {'input': {'type': 'string', 'description': 'Existing workspace .json recipe under input/, work/ or output/. The recipe must explicitly declare contract_version=2 and sensitivity=synthetic.'},
          'output': {'type': 'string', 'description': 'Package directory under output/. New for build; existing with the same generating recipe for verify.'},
          'mode': {'type': 'string', 'enum': ['synthetic']},
          'verify': {'type': 'boolean', 'description': 'True: read-only check of the original recipe and actual package. False or omitted: create a new package.'}}, ['input', 'output', 'mode']),
        ('case_docx_review', 'Read an existing current DOCX literal text/bookmark structure, optionally compare a previous DOCX, and write a new output/ JSON report. JSON assembly recipes belong to case_documents. Preserve partial/unknown states; not visual, semantic or professional approval.',
         {'input': {'type': 'string', 'description': 'Workspace path to the existing current .docx file to read back; not a JSON assembly recipe or Markdown source.'},
          'baseline': {'type': 'string', 'description': 'Optional workspace path to an existing previous .docx file for comparison. Omit when no previous Word file is available; never supply a JSON recipe or Markdown source.'},
          'output': {'type': 'string', 'description': 'New workspace path under output/ for the complete JSON readback report.'},
          'summary': {'type': 'boolean', 'description': 'Optional true adds bounded changed-text and anomaly excerpts with exact JSON report pointers, counts and omitted-item totals. Complete evidence remains in output with its SHA-256; omitted items are not reviewed. Default false preserves the metadata-only reply.'},
          'mode': mode}, ['input', 'output', 'mode']),
        ('case_software', 'Prepare, build or read-only verify internal software materials using the same hash-bound authorization and implementation as the CLI. Root is this case workspace only. No network, source execution, PDF tools, formal approval or submission. Only metadata/file hashes are returned. Intake replays genuine operator answers to software_intake.collect; omit answers to discover the first question, then replay the previous answers plus the next real answer. Never invent consent, evidence or authority. An incomplete list returns the next actual question before material reads; completion writes a new request/authorization pair. DOCX-only build/verify may return exit_code=4 and partial; this is not a physical-page or professional pass.',
         {'action': {'type': 'string', 'enum': ['prepare', 'build', 'verify', 'intake']},
          'root': {'type': 'string', 'enum': ['.'], 'description': 'Optional literal dot; case workspace is fixed by the controller.'},
          'authorization': {'type': 'string', 'description': 'Prepare/build/verify: existing hash-bound software_local_authorization JSON under input/, work/ or output/. Bound request and every material must also remain in this case; its output must be under output/.'},
          'authorization_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
          'output': {'type': 'string', 'description': 'Intake only: new collection directory under output/; parent must already exist. Other actions take output solely from the authorization.'},
          'candidates': {'type': 'boolean', 'description': 'Intake only: true uses the real candidate-discovery collector questions; false or omitted preserves the original single-component collector. No implicit consent or material reads.'},
          'answers': {'type': 'array', 'maxItems': 1000, 'items': {'type': 'string'}, 'description': 'Intake only: ordered real answers to the actual collector questions. Omit or supply a prefix to receive the next question. No automatic consent or permissions.'}}, ['action']),
        ('case_fidelity', 'Run the frozen finite fidelity auditor from a local synthetic JSON payload into a new output/ report. Operational success may still contain status blocked; caller-formalized relations do not prove natural language or legal support.',
         {'input': text, 'output': text, 'mode': {'type': 'string', 'enum': ['synthetic']}}, ['input', 'output', 'mode']),
    ]
    return [{'type': 'function', 'name': name, 'description': description,
             'inputSchema': {'type': 'object', 'properties': properties, 'required': required,
                             'additionalProperties': False}}
            for name, description, properties, required in specs]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bounded local case tools; NDJSON stdin/stdout, no model or network.')
    parser.add_argument('--describe', action='store_true', help='Print the function schemas without opening roots.')
    parser.add_argument('--package')
    parser.add_argument('--workspace')
    parser.add_argument('--control')
    parser.add_argument('--manifest-sha256')
    parser.add_argument('--max-calls', type=int, default=120)
    args = parser.parse_args(argv)
    if args.describe:
        print(json.dumps({'transport': 'local_ndjson_v1', 'tools': dynamic_tools(),
                          'default_receipts': 'hashes_status_budget_without_payloads',
                          'scope': 'Python file boundaries; not OS isolation or a model host'}, ensure_ascii=False))
        return 0
    if not all((args.package, args.workspace, args.control, args.manifest_sha256)):
        parser.error('--package, --workspace, --control and --manifest-sha256 are required')
    try:
        bridge = HostToolBridge(args.package, args.workspace, args.control, args.manifest_sha256, max_calls=args.max_calls)
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'success': False, 'error': 'bridge_roots_or_manifest_rejected'}))
        return 2
    seen = set()
    # Bound a physical input frame before JSON parsing; do not accumulate an
    # unbounded malformed stream. Binary reads also have explicit UTF-8 semantics.
    while True:
        raw = sys.stdin.buffer.readline(32_000_001)
        if not raw:
            return 0
        if len(raw) > 32_000_000:
            print(json.dumps({'id': None, 'answer': {'success': False, 'error': 'frame_too_large'}}), flush=True)
            return 2
        identity = None
        try:
            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise BridgeError('duplicate_json_key')
                    value[key] = item
                return value
            request = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                                 parse_constant=lambda value: (_ for _ in ()).throw(BridgeError('invalid_json_constant')))
            bridge._keys(request, {'id', 'tool', 'arguments'})
            _require(isinstance(request['id'], str) and 0 < len(request['id']) <= 200, 'invalid_request_id')
            identity = request['id']
            _require(identity not in seen, 'duplicate_request_id')
            seen.add(identity)
            answer = bridge.call(request['tool'], request['arguments'])
        except (ValueError, UnicodeError, TypeError, KeyError):
            answer = {'success': False, 'error': 'invalid_or_duplicate_request'}
        print(json.dumps({'id': identity, 'answer': answer}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
