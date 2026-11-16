"""Isolated Python worker for the three explicitly allowed installed file tools."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys

job = json.loads(Path(sys.argv[1]).read_bytes())
package, workspace, audit_path = (Path(job[k]).resolve() for k in ('package', 'workspace', 'audit'))
assert Path.cwd().resolve() == workspace
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
sys.path.insert(0, str(package))
runtime = Path(sys.base_prefix).resolve()
events, blocked = [], []


def observe(event, args):
    if event == 'open' and not isinstance(args[0], int):
        path = Path(os.fsdecode(args[0])).resolve()
        mode, flags = args[1], args[2]
        writing = ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or
                   bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        location = ('workspace' if path.is_relative_to(workspace) else 'installed_package' if path.is_relative_to(package)
                    else 'python_runtime' if path.is_relative_to(runtime) else 'audit' if path == audit_path else 'other')
        row = {'path': str(path), 'location': location, 'writing': writing}
        events.append(row)
        if location == 'other' or (writing and location not in {'workspace', 'audit'}):
            blocked.append(row)
            raise PermissionError('worker_file_boundary')
    if event in {'socket.connect', 'socket.bind', 'subprocess.Popen', 'os.system'}:
        blocked.append({'event': event})
        raise PermissionError('worker_network_or_subprocess_boundary')


sys.addaudithook(observe)
code, unexpected, contract_error = 1, None, None
try:
    a = job['arguments']
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
except SystemExit as error:
    code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
except BaseException as error:
    unexpected = type(error).__name__
finally:
    modules = {k: str(Path(v.__file__).resolve()) for k, v in sys.modules.items()
               if k.startswith('tools') and getattr(v, '__file__', None)}
    assert all(Path(v).is_relative_to(package) for v in modules.values())
    with audit_path.open('x', encoding='utf-8') as file:
        json.dump({'exit_code': code, 'unexpected_exception': unexpected, 'contract_error': contract_error, 'blocked': blocked,
                   'file_open_events': events, 'loaded_tools_modules': modules,
                   'scope': 'Python events only; not complete OS or native runtime isolation.'}, file, ensure_ascii=False, indent=2)
sys.exit(code)
