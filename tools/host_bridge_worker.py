"""Private isolated-Python worker for bounded local case tools.

The controller owns and freezes the roots. Python audit events are a bounded
defence, not an OS sandbox; this worker never starts a model or external tool.
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import stat
import sys
import sysconfig


def _is_macos_system_root_symlink(entry):
    # Bootstrap and the audit hook must not import tools before the frozen loader can read them.
    if sys.platform != 'darwin' or entry not in (Path('/var'), Path('/tmp'), Path('/etc')):
        return False
    try:
        target = os.readlink(entry)
    except OSError:
        return False
    return target in (f'private/{entry.name}', f'/private/{entry.name}')


def _regular(path):
    for item in (path, *path.parents):
        info = item.lstat()
        is_link = item.is_symlink() or bool(
            getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))
        if is_link:
            if item != path and _is_macos_system_root_symlink(item):
                try:
                    info = item.stat()
                except OSError:
                    raise PermissionError('worker_reparse_path') from None
            else:
                raise PermissionError('worker_reparse_path')
        if item == path and not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise PermissionError('worker_nonregular_or_aliased_file')


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, fullname, path, row):
        super().__init__(fullname, str(path))
        self.row = row

    def get_code(self, fullname):
        path = Path(self.path)
        _regular(path)
        if path.stat().st_size != self.row['bytes']:
            raise ImportError('worker_source_changed')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.row['sha256']:
            raise ImportError('worker_source_changed')
        # Never call SourceFileLoader.get_code: -B prevents writing caches,
        # but the default loader still READS and executes valid unlisted pyc.
        return self.source_to_code(raw, self.path)


class _FrozenToolsFinder(importlib.abc.MetaPathFinder):
    def __init__(self, package, rows):
        self.package, self.rows = package, rows

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'tools' and not fullname.startswith('tools.'):
            return None
        relative = fullname.replace('.', '/')
        candidates = [(relative + '/__init__.py', True), (relative + '.py', False)]
        for name, is_package in candidates:
            if name in self.rows:
                source = self.package / name
                loader = _SourceOnlyLoader(fullname, source, self.rows[name])
                return importlib.util.spec_from_file_location(fullname, source, loader=loader,
                    submodule_search_locations=[str(source.parent)] if is_package else None)
        # Do not fall through to caches, workspace modules or another tools tree.
        raise ModuleNotFoundError('worker_module_not_in_manifest')


def _software_tool(a, workspace):
    from argparse import Namespace
    from tools import cli, core

    original_path, original_read = core.safe_path, cli._read_bound_json

    def case_path(root, relative, *, must_exist=True):
        # 软件授权只收窄当前案件；材料中嵌入的路径不能扩展宿主根。
        base = Path(root).resolve(strict=True)
        core.require(base.is_relative_to(workspace), 'software_case_root_required')
        core.require(isinstance(relative, str), 'relative_path_required')
        parts = relative.replace('\\', '/').split('/')
        core.require(all(part and not part.startswith('.') and ':' not in part
                     and '\x00' not in part for part in parts), 'unsafe_path')
        scoped = (*base.relative_to(workspace).parts, *parts)
        core.require(len(scoped) > 1 and scoped[0] in {'input', 'work', 'output'},
                     'workspace_path_not_allowed')
        return original_path(root, relative, must_exist=must_exist)

    def bound_json(root, relative, expected, limit):
        result = original_read(root, relative, expected, limit)
        if relative == a.get('authorization'):
            # 控制文件可以读；正文和源码仍由CLI在当前权限检查后读取。
            for entry in result.get('files', []):
                case_path(root, entry['path'], must_exist=False)
            request = result.get('request', {})
            if isinstance(request, dict) and 'path' in request:
                case_path(root, request['path'], must_exist=False)
            output = result.get('output')
            case_path(root, output, must_exist=False)
            core.require(output.replace('\\', '/').split('/')[0] == 'output', 'output_root_required')
        return result

    def index(relative):
        path = case_path(workspace, relative)
        paths = [path] if path.is_file() else sorted(path.rglob('*'))
        rows = []
        for item in paths:
            if item.is_file():
                name = item.relative_to(workspace).as_posix()
                checked = case_path(workspace, name)
                raw = checked.read_bytes()
                rows.append({'path': name, 'bytes': len(raw), 'sha256': core.sha256_bytes(raw)})
        return rows

    try:
        core.require(isinstance(a, dict), 'invalid_arguments')
        core.require(set(a) <= {'action', 'authorization', 'authorization_sha256', 'output', 'answers', 'root', 'candidates'}
                     and 'action' in a, 'invalid_arguments')
        core.require(isinstance(a['action'], str) and a['action'] in {'prepare', 'build', 'verify', 'intake'},
                     'software_action_invalid')
        core.require(a.get('root', '.') == '.', 'software_case_root_required')
        core.safe_path, cli._read_bound_json = case_path, bound_json
        if a['action'] == 'intake':
            from tools import software_intake
            core.require('candidates' not in a or type(a['candidates']) is bool, 'invalid_arguments')
            core.require('output' in a and not {'authorization', 'authorization_sha256'} & set(a),
                         'invalid_arguments')
            answers = a.get('answers', [])
            core.require(isinstance(answers, list) and len(answers) <= 1000
                         and all(isinstance(value, str) for value in answers), 'intake_answers_invalid')
            target = case_path(workspace, a['output'], must_exist=False)
            core.require(a['output'].replace('\\', '/').split('/')[0] == 'output', 'output_root_required')
            core.require(target.parent.is_dir() and not target.exists(), 'output_exists')
            position, pending = 0, None

            def ask(prompt):
                nonlocal position, pending
                if position == len(answers):
                    pending = prompt
                    raise EOFError
                value = answers[position]
                position += 1
                if '是否确认全部输入并允许现在逐文件读取' in prompt:
                    core.require(position == len(answers), 'intake_answers_unused')
                return value

            try:
                collector = (software_intake.collect_candidates if a.get('candidates', False)
                             else software_intake.collect)
                summary = collector(workspace, a['output'], ask=ask)
            except core.ContractError as error:
                if str(error) != 'intake_cancelled' or pending is None:
                    raise
                summary = {'status': 'awaiting_answers', 'next_question': pending,
                           'answers_consumed': position, 'files': []}
            else:
                summary['files'] = index(a['output'])
            code = 0
        else:
            core.require({'authorization', 'authorization_sha256'} <= set(a)
                         and not {'output', 'answers', 'candidates'} & set(a), 'invalid_arguments')
            authorization = case_path(workspace, a['authorization'])
            core.require(authorization.suffix.lower() == '.json', 'software_authorization_json_required')
            args = Namespace(root=str(workspace), authorization=a['authorization'],
                             authorization_sha256=a['authorization_sha256'],
                             verify=a['action'] == 'verify', pdf_tool=None, pdf_text_tool=None)
            report = cli._prepare_software(args, document_output=a['action'] != 'prepare')
            # 不把准备信封、源码、完整权限或私有审查正文放回宿主上下文。
            authorization = original_read(workspace, a['authorization'], a['authorization_sha256'], 1_000_000)
            summary = {'status': report['status'], 'action': a['action'],
                       'output_scope': 'internal_only_not_for_submission',
                       'professional_review': 'not_performed', 'external_action': 'not_performed',
                       'files': index(authorization['output'])}
            code = 4 if a['action'] != 'prepare' and report['status'] == 'partial' else 0
        print(json.dumps(summary, ensure_ascii=False))
        return code, None
    except core.ContractError as error:
        diagnostic = str(error)
        if not re.fullmatch('[a-z][a-z0-9_]{0,100}', diagnostic):
            diagnostic = 'software_contract_rejected'
        print('software_contract_rejected')
        return 2, diagnostic
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OverflowError):
        print('software_contract_rejected')
        return 2, 'preparation_boundary_invalid'
    except OSError:
        print('software_io_failed_partial_output_may_remain')
        return 3, None
    finally:
        core.safe_path, cli._read_bound_json = original_path, original_read


def _run_tool(job, workspace):
    code, contract_error = 1, None
    a = job['arguments']
    if job['tool'] == 'case_software':
        return _software_tool(a, workspace)
    if job['tool'] == 'case_standard_package':
        from tools import cli, core
        try:
            core.require(isinstance(a, dict) and {'input', 'output', 'mode'} <= set(a)
                         and set(a) <= {'input', 'output', 'mode', 'verify'}, 'invalid_arguments')
            core.require(a['mode'] == 'synthetic', 'standard_authorized_case_unsupported')
            core.require('verify' not in a or type(a['verify']) is bool, 'invalid_arguments')
            core.require(all(isinstance(a[key], str) for key in ('input', 'output')), 'invalid_arguments')
            for key in ('input', 'output'):
                parts = a[key].replace('\\', '/').split('/')
                core.require(len(parts) > 1 and all(part and not part.startswith('.') and
                             ':' not in part and '\x00' not in part for part in parts), 'unsafe_path')
            core.require(a['input'].replace('\\', '/').split('/')[0] in {'input', 'work', 'output'}
                         and a['output'].replace('\\', '/').split('/')[0] == 'output', 'workspace_path_not_allowed')
        except core.ContractError as error:
            print('standard_authorized_case_unsupported' if str(error) ==
                  'standard_authorized_case_unsupported' else 'standard_contract_rejected')
            return 2, None
        arguments = ['prepare-standard', '--synthetic', '--root', str(workspace),
                     '--input', a['input'], '--output', a['output']]
        if a.get('verify', False):
            arguments.append('--verify')
        return cli.main(arguments), None
    flag = '--synthetic' if a['mode'] == 'synthetic' else '--research-example'
    if job['tool'] == 'case_documents':
        if a.get('verify', False):
            # Reuse installed verification with the CLI's validation/status
            # contract. Only this known, path-free failure is typed; do not
            # infer a cause from the CLI's generic exit2 message.
            from tools import documents
            try:
                synthetic, research = a['mode'] == 'synthetic', a['mode'] == 'research_example'
                documents._mode(synthetic, research)
                path = documents.safe_path(workspace, a['input'])
                documents.require(path.stat().st_size <= documents.MAX_BYTES, 'document_input_size')
                spec = documents.strict_json_loads(path.read_text(encoding='utf-8'))
                documents.verify(workspace, spec, a['output'], synthetic=synthetic, research_example=research)
                print('document_verified_needs_review')
                code = 0
            except (documents.ContractError, ValueError, KeyError, TypeError, AttributeError, documents.zipfile.BadZipFile) as error:
                if isinstance(error, documents.ContractError) and str(error) == 'document_input_binding_changed':
                    contract_error = 'document_input_binding_changed'
                print('document_contract_rejected')
                code = 2
            except (OSError, documents.subprocess.TimeoutExpired):
                print('document_io_failed_partial_output_may_remain')
                code = 3
        else:
            sys.argv = ['tools.documents', flag, '--root', '.', '--input', a['input'], '--output', a['output']]
            runpy.run_module('tools.documents', run_name='__main__')
    elif job['tool'] == 'case_docx_review':
        sys.argv = ['tools.document_review', flag, '--root', '.', '--input', a['input'], '--output', a['output']]
        if 'baseline' in a:
            sys.argv += ['--baseline', a['baseline']]
        if a.get('summary') is True:
            sys.argv.append('--summary')
        runpy.run_module('tools.document_review', run_name='__main__')
    elif job['tool'] == 'case_fidelity':
        from tools.core import ContractError, safe_path, strict_json_loads, write_new_json
        from tools.fidelity import audit
        try:
            payload = strict_json_loads(safe_path(workspace, a['input']).read_text(encoding='utf-8'))
            report = audit(payload)
            write_new_json(workspace, a['output'], report)
            print(json.dumps({'status': report['status'], 'output': a['output'],
                              'sha256': hashlib.sha256(safe_path(workspace, a['output']).read_bytes()).hexdigest(),
                              'natural_language_verified': False, 'professional_review': 'not_performed'}))
            code = 0
        except (ContractError, ValueError, KeyError, TypeError):
            print('fidelity_contract_rejected')
            code = 2
    else:
        raise ValueError('unsupported_worker_tool')
    return code, contract_error


def main():
    if len(sys.argv) != 2 or not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
        return 2
    job_path = Path(sys.argv[1]).absolute()
    _regular(job_path)
    job = json.loads(job_path.read_bytes())
    if set(job) != {'tool', 'arguments', 'package', 'workspace', 'audit', 'expected_manifest_sha256'}:
        return 2
    package, workspace, audit_path = (Path(job[k]).absolute() for k in ('package', 'workspace', 'audit'))
    for root in (package, workspace, audit_path.parent):
        _regular(root)
    package = package.resolve()
    workspace = workspace.resolve()
    audit_path = audit_path.parent.resolve() / audit_path.name
    job_path = job_path.resolve()
    if Path.cwd().resolve() != workspace or audit_path.parent != job_path.parent or os.path.lexists(audit_path):
        return 2
    roots = [package, workspace, audit_path.parent]
    if len(set(roots)) != 3 or any(a.is_relative_to(b) for a in roots for b in roots if a != b):
        return 2
    manifest_path = package / 'bundle-manifest.json'
    _regular(manifest_path)
    expected = job['expected_manifest_sha256']
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected) or manifest_path.stat().st_size > 1_000_000:
        return 2
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        return 2
    manifest = json.loads(raw)
    rows = {row['path']: row for row in manifest['files']}
    # The parent already verified the fixed inventory against the external hash.
    allowed_package = set(rows) | {'bundle-manifest.json'}
    worker_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    runtime_paths = sysconfig.get_paths()
    runtime_roots = tuple({Path(runtime_paths[key]).resolve() for key in ('stdlib', 'platstdlib')})
    excluded_runtime_roots = tuple({Path(runtime_paths[key]).resolve() for key in ('purelib', 'platlib')})
    writing_audit = False
    events, blocked = [], []

    def observe(event, args):
        if event == 'open' and not isinstance(args[0], int):
            # Do NOT call os.path.abspath() before resolve(), as abspath() lexically collapses
            # symlink/.. segments on POSIX before lstat/resolve can detect workspace escapes.
            raw_path = Path(os.fsdecode(args[0]))
            path = raw_path.resolve()
            lexical = raw_path if raw_path.is_absolute() else (workspace / raw_path)
            mode, flags = args[1], args[2]
            writing = ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or
                       bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            location, allowed = 'other', False
            if path.is_relative_to(workspace):
                location = 'workspace'
                parts = path.relative_to(workspace).parts
                allowed = bool(parts) and parts[0] in ({'work', 'output'} if writing else {'input', 'work', 'output'})
                allowed = allowed and all(not part.startswith('.') and ':' not in part for part in parts)
            elif path.is_relative_to(package):
                location = 'installed_package'
                allowed = not writing and path.relative_to(package).as_posix() in allowed_package
            elif path == audit_path:
                location, allowed = 'audit', writing and writing_audit
            elif any(path.is_relative_to(r) for r in runtime_roots):
                location = 'python_runtime'
                allowed = not writing and not any(path.is_relative_to(r) for r in excluded_runtime_roots)
            if allowed and location != 'python_runtime':
                if '..' in raw_path.parts or Path.cwd().resolve() != workspace:
                    allowed = False
                else:
                    try:
                        # Check un-collapsed lexical path (handles dangling symlinks and reparse points!).
                        _regular(lexical if os.path.lexists(lexical) else lexical.parent)
                    except OSError:
                        allowed = False
            row = {'path': str(lexical), 'location': location, 'writing': writing}
            events.append(row)
            if not allowed:
                blocked.append(row)
                raise PermissionError('worker_file_boundary')
        if event.startswith('socket.') or event in {
            'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.spawn',
            'os.startfile', 'os.fork', 'os.forkpty', 'os.exec', 'webbrowser.open',
        }:
            blocked.append({'event': event})
            raise PermissionError('worker_network_or_subprocess_boundary')

    sys.meta_path.insert(0, _FrozenToolsFinder(package, rows))
    sys.addaudithook(observe)
    code, unexpected, contract_error = 1, None, None
    try:
        code, contract_error = _run_tool(job, workspace)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    except BaseException as error:
        unexpected = type(error).__name__
    finally:
        modules = {key: str(Path(value.__file__).resolve()) for key, value in sys.modules.items()
                   if (key == 'tools' or key.startswith('tools.')) and getattr(value, '__file__', None)}
        if not all(Path(value).is_relative_to(package) for value in modules.values()):
            unexpected, code = 'ModuleOriginMismatch', 1
        writing_audit = True
        try:
            with audit_path.open('x', encoding='utf-8') as stream:
                json.dump({'exit_code': code, 'unexpected_exception': unexpected, 'contract_error': contract_error,
                           'worker_pid': os.getpid(), 'worker_source_sha256': worker_hash,
                           'source_loading': 'manifest_hash_bound_source_only_no_bytecode',
                           'blocked': blocked, 'file_open_events': events, 'loaded_tools_modules': modules,
                           'scope': 'Python events only; not complete OS or native runtime isolation.'},
                          stream, ensure_ascii=False, indent=2)
        finally:
            writing_audit = False
    return code


if __name__ == '__main__':
    raise SystemExit(main())
