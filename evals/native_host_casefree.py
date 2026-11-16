"""One explicitly armed native case-free probe; never runs on unittest import.

Run only after the recorded authorization/profile review. First outgoing input
also waits for the controller's body-bound review marker before forwarding.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import queue
import secrets
import subprocess
import tempfile
import threading
import time

from evals.native_host_bridge import NativeHostBridge, dynamic_tools
from evals.native_host_session import NativeRelay, NativeRpc, SessionError, native_wire_schema, require, save_new, sha
from tools.bundle import verify_bundle

ROOT = Path('D:/dyz-patent-skills')
OUT = ROOT / 'outputs/maturity-i05-native-g6-r21'
PACKAGE = Path('D:/skills/codex/dyz-patent-skills')
CLI = Path('D:/npm-global/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe')
MANIFEST_SHA = '5074f7446cf2b246269e80d22a3b7589d25e69850f30c263753cfb184af17708'
CLI_SHA = '9e7c59c05cc1ce5677b1f94e835b2ac038ca3be14504e78d558eacdb0ea3f55d'
AUTH_SHA = '43ad750fc3215fc0e25f147662a715264d7d0a6991c77ed2196d2f94f65ca734'
CATALOG_SHA = '5994afab545e7f9e7b260d93fcb53230efba30170c14faf74340f756ef063b52'
PROMPT = ('这是一次无案件的宿主工具核验。请完成三个动作：用提供的工具读取 '
          'input/channel-check.txt；把该文件的完整文本原样写入 work/channel-check.txt，'
          '不增加换行；读取安装包 README.md 第1至8行。最后简短报告核验串、写入路径和'
          'README实际读取行范围。只操作上述文件，不运行业务案件，不使用其他工具。')
DEVELOPER = ('本次客户端仅提供固定安装包和当前input/work/output目录内的受限动态工具。'
             '仅完成用户明确的无案件读写核验，不读取其他文件，不使用Shell、网络、子代理、'
             '外部账号或其他目录。不得把本次核验升级为专业或完整稳定性验收。')


def casefree_call_allowed(params):
    name, args = params.get('tool'), params.get('arguments')
    require(isinstance(args, dict), 'callback_arguments_not_object')
    if name in {'case_read', 'case_info'}:
        require((args.get('scope'), args.get('path')) in {
            ('workspace', 'input/channel-check.txt'), ('workspace', 'work/channel-check.txt'),
            ('package', 'README.md')}, 'casefree_read_scope')
        if name == 'case_read' and args.get('scope') == 'package':
            start, count = args.get('start_line', 1), args.get('max_lines', 80)
            require(type(start) is int and type(count) is int
                    and start >= 1 and count >= 1 and start + count - 1 <= 8, 'casefree_read_range')
    elif name == 'case_write':
        require(args.get('path') == 'work/channel-check.txt' and 'expected_sha256' not in args,
                'casefree_write_scope')
    else:
        raise SessionError('casefree_tool_scope')


def main():
    require(OUT.is_dir(), 'missing_preflight_directory')
    run = OUT / 'run-06'
    run.mkdir(exist_ok=False)
    require(sha(CLI.read_bytes()) == CLI_SHA, 'cli_changed')
    require(sha((ROOT / 'evals/workflows/alignment-d12-channel-authorization.json').read_bytes()) == AUTH_SHA,
            'authorization_changed')
    tests = json.loads((OUT / 'combined-tests-r6.json').read_bytes())
    require(tests['exit_code'] == 0, 'session_tests_not_passed')
    for rel, digest in tests['source_hashes'].items():
        require(sha((ROOT / rel).read_bytes()) == digest, 'session_test_source_changed')
    bridge_tests = tests
    require(bridge_tests['exit_code'] == 0, 'bridge_tests_not_passed')
    for rel, digest in bridge_tests['source_hashes'].items():
        require(sha((ROOT / rel).read_bytes()) == digest, 'bridge_test_source_changed')
    verify_bundle(PACKAGE, expected_manifest_sha256=MANIFEST_SHA)
    metadata = (ROOT / 'outputs/maturity-i05-native-r21/protocol-r3-official-model-metadata.json').read_bytes()
    require(sha(metadata) == CATALOG_SHA, 'catalog_changed')
    derived = json.loads(metadata)
    selected_metadata = [m for m in derived['models'] if m.get('slug') == 'gpt-6.1-sol']
    require(len(selected_metadata) == 1 and selected_metadata[0]['tool_mode'] == 'code_mode_only',
            'original_catalog_tool_mode_changed')
    require(selected_metadata[0]['apply_patch_tool_type'] == 'freeform'
            and selected_metadata[0]['experimental_supported_tools'] == ['send_user_message_async','clock'],
            'original_catalog_builtin_selection_changed')
    selected_metadata[0]['tool_mode'] = 'direct'
    selected_metadata[0]['apply_patch_tool_type'] = None
    selected_metadata[0]['experimental_supported_tools'] = []
    catalog_path = run / 'derived-direct-tool-catalog.json'
    save_new(catalog_path, derived)
    work = Path(tempfile.mkdtemp(prefix='dyz-r21-native-g6-')).resolve()
    require(not work.is_relative_to(ROOT) and not work.is_relative_to(PACKAGE), 'workspace_overlap')
    (work / 'input').mkdir()
    nonce = ('DYZ-NATIVE-G6-' + secrets.token_hex(18) + '-核验').encode('utf-8')
    (work / 'input/channel-check.txt').write_bytes(nonce)
    control = run / 'bridge'
    control.mkdir()
    bridge = NativeHostBridge(PACKAGE, work, control, MANIFEST_SHA, max_calls=12)
    specs = dynamic_tools()
    prior_posts = sum(sum(bool(r.get('forwarded')) for r in json.loads((p/'result.json').read_bytes())['requests'])
                      for p in OUT.glob('run-0[1-5]'))
    require(prior_posts == 2, 'prior_post_budget_changed')
    relay = NativeRelay(run / 'relay', metadata, specs, PROMPT, max_requests=4, review_seconds=300)
    profile = json.loads((ROOT / 'outputs/maturity-i05-native-r21/protocol-trace-intent.json').read_bytes())
    cfg = dict(profile['per_process_config'])
    cfg['openai_base_url'] = f'http://127.0.0.1:{relay.port}/backend-api/codex'
    cfg['sandbox_mode'] = 'workspace-write'
    cfg['sandbox_workspace_write.network_access'] = False
    cfg['model_catalog_json'] = str(catalog_path.resolve())
    command = [str(CLI), 'app-server', '--listen', 'stdio://']
    for key, value in cfg.items():
        command += ['-c', key + '=' + json.dumps(value, ensure_ascii=False)]
    allowed_env = {k.lower() for k in profile['environment_keys']} - {'rust_log'}
    environment = {k: v for k, v in os.environ.items() if k.lower() in allowed_env}
    environment['RUST_LOG'] = 'off,codex_app_server::request_processors::thread_processor=warn,codex_app_server::message_processor=warn'
    intent = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'kind': 'one_fresh_native_casefree_G6',
        'authority': {'path': 'evals/workflows/alignment-d12-channel-authorization.json', 'sha256': AUTH_SHA},
        'installation_approval_not_model_authority': True,
        'components': {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in [Path(__file__),
            ROOT / 'evals/native_host_session.py', ROOT / 'evals/native_host_bridge.py',
            ROOT / 'tools/host_bridge.py', ROOT / 'tools/host_bridge_worker.py', ROOT / 'tools/bundle.py']},
        'cli_sha256': CLI_SHA, 'model': 'gpt-6.1-sol', 'effort': 'high', 'token_cap': None,
        'workspace': str(work), 'control': str(control), 'loopback_port': relay.port,
        'installed_manifest_sha256': MANIFEST_SHA, 'official_cached_catalog_sha256': CATALOG_SHA,
        'derived_catalog': {'path': str(catalog_path), 'sha256': sha(catalog_path.read_bytes()),
            'only_semantic_changes': {'models[slug=gpt-6.1-sol].tool_mode': ['code_mode_only','direct'],
                'models[slug=gpt-6.1-sol].apply_patch_tool_type': ['freeform',None],
                'models[slug=gpt-6.1-sol].experimental_supported_tools': [['send_user_message_async','clock'],[]]},
            'official_catalog_not_modified': True, 'not_an_official_catalog_claim': True},
        'prompt': PROMPT, 'prompt_sha256': sha(PROMPT.encode('utf-8')), 'developer': DEVELOPER,
        'nonce_input_sha256': sha(nonce), 'nonce_input_bytes': len(nonce), 'nonce_not_in_prompt': True,
        'command': command, 'config': cfg, 'environment_keys': sorted(environment), 'dynamic_tools': specs,
        'expected_wire_parameters': {s['name']:native_wire_schema(s['inputSchema']) for s in specs},
        'wire_projection_limit': 'Observed native SDK drops minimum/maximum/pattern. Original declaration and execution checks remain; other schema changes are rejected. No outgoing request rewrite.',
        'budget': {'max_official_posts': 4, 'prior_official_posts_this_goal_turn': prior_posts,
                   'max_cumulative_official_posts_this_goal_turn': 6,
                   'max_tool_calls': 12, 'max_task_seconds': 600,
                   'first_input_review_seconds': 300, 'stdin_close_exit_seconds': 5,
                   'late_exit_diagnostic_extra_seconds': 10, 'token_cap': None,
                   'automatic_content_redraws': 0, 'money': 'unknown_not_zero_existing_authorized_account'},
        'expected_local_transport_negotiation': 'At most2 exact native WebSocket upgrade GETs receive426 locally, which the pinned native source handles by selecting HTTP immediately. No external WS and no failed-response retry allowed.',
        'stop': 'First unexpected request/tool/input/session/content/transport/lifecycle failure stops this probe. No case auto-admission.',
        'gates_expected': ['actual native model/high/no cap and exact8 declarations',
            'no old conversation or answer history', 'genuine complete SSE and native callbacks bound to actual thread/turn',
            'input exact copy without newline and README1-8 actually read',
            'actual final answer reports nonce', 'owned thread closed and process exits within original5s',
            'listener/threads stop and installation/prior files unchanged'],
        'limitations': 'Native runtime can internally read existing configuration. Workspace-write and client path checks are not an OS or vendor isolation claim. No business cases or professional acceptance.'}
    save_new(run / 'intent.json', intent)
    stdout = (run / 'rpc-inbound.jsonl').open('xb')
    outbound = (run / 'rpc-outbound.jsonl').open('xb')
    child = None
    result = {'status': 'prepared', 'workspace': str(work), 'intent_sha256': sha((run / 'intent.json').read_bytes()),
              'case_tasks': 0, 'whole_goal': 'not_complete', 'closed_thread_ids': []}
    start = time.monotonic()
    stderr_hash, stderr_info = hashlib.sha256(), {'bytes': 0, 'eof': False}
    stderr_thread, rpc = None, None

    def stderr_reader():
        while True:
            raw = child.stderr.read(4096)
            if not raw:
                stderr_info['eof'] = True
                return
            stderr_hash.update(raw)
            stderr_info['bytes'] += len(raw)

    def observe(message):
        if message.get('method') == 'thread/closed':
            result['closed_thread_ids'].append(message['params']['threadId'])

    def handle_tool(message):
        require(message.get('method') == 'item/tool/call' and 'id' in message, 'unexpected_server_request')
        params = message['params']
        require(params['callId'] in relay.call_ids, 'callback_call_not_in_actual_response')
        binding = relay.calls[params['callId']]
        require(params.get('tool') == binding['name'] and params.get('arguments') == binding['arguments']
                and params.get('namespace') == binding['namespace'], 'callback_differs_from_actual_function_item')
        require(params['callId'] not in result.setdefault('executed_call_ids', []), 'duplicate_callback')
        casefree_call_allowed(params)
        answer = bridge.native_tool_result(params, thread_id=result['thread_id'], turn_id=result['turn_id'])
        result['executed_call_ids'].append(params['callId'])
        rpc.send({'id': message['id'], 'result': answer})
        require(answer['success'], 'bridge_tool_failed')
        if params['tool'] == 'case_write':
            require((work / 'work/channel-check.txt').read_bytes() == nonce, 'nonce_write_content_mismatch')
        print(json.dumps({'stage': 'native_tool_returned', 'tool': params['tool'],
                          'ordinal': len(result['executed_call_ids']), 'success': answer['success']}), flush=True)

    try:
        child = subprocess.Popen(command, cwd=work, env=environment, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        result['pid'] = child.pid
        save_new(run / 'live-ownership.json', {'pid': child.pid, 'port': relay.port, 'workspace': str(work),
                                              'cli_sha256': CLI_SHA, 'driver_pid': os.getpid()})
        stderr_thread = threading.Thread(target=stderr_reader, daemon=True)
        stderr_thread.start()
        rpc = NativeRpc(child, stdout, outbound)
        rpc.request('initialize', {'clientInfo': {'name': 'dyz_native_casefree', 'title': 'DYZ case-free native read/write',
                                                'version': '0.1.0'},
                                 'capabilities': {'experimentalApi': True, 'explicitGatewayOauth': True}}, 1)
        rpc.send({'method': 'initialized', 'params': {}})
        skills = rpc.request('skills/list', {'cwds': [str(work)], 'forceReload': True}, 2)
        require(len(skills['data']) == 1, 'skill_roots_mismatch')
        matches = [s for s in skills['data'][0]['skills'] if Path(s['path']).resolve().is_relative_to(PACKAGE.resolve())]
        require(len(matches) == 6 and all(s['enabled'] for s in matches), 'installed_skill_discovery_mismatch')
        result['installed_default_entries'] = [{k: s.get(k) for k in ['name','description','path','enabled','scope']} for s in matches]
        models = rpc.request('model/list', {'includeHidden': True, 'limit': 100}, 3)
        selected = [m for m in models['data'] if m.get('model') == 'gpt-6.1-sol']
        require(len(selected) == 1 and any(e['reasoningEffort'] == 'high' for e in selected[0]['supportedReasoningEfforts']),
                'native_model_high_not_listed')
        reply = rpc.request('thread/start', {'model': 'gpt-6.1-sol', 'modelProvider': 'openai', 'cwd': str(work),
            'ephemeral': True, 'approvalPolicy': 'never', 'sandbox': 'workspace-write',
            'dynamicTools': specs, 'developerInstructions': DEVELOPER}, 4)
        result['thread_id'] = reply['thread']['id']
        result['thread_start'] = {k: reply.get(k) for k in ['model','modelProvider','cwd','approvalPolicy','sandbox',
                                                                         'reasoningEffort','activePermissionProfile']}
        save_new(run / 'thread-start.json', reply)
        require(reply['model'] == 'gpt-6.1-sol' and reply['modelProvider'] == 'openai'
                and reply['approvalPolicy'] == 'never' and reply.get('reasoningEffort') == 'high', 'thread_profile_mismatch')
        require(reply['sandbox']['type'] == 'workspaceWrite' and reply['sandbox']['networkAccess'] is False,
                'thread_permission_mismatch')
        status = rpc.request('mcpServerStatus/list', {'threadId': result['thread_id'], 'detail': 'toolsAndAuthOnly', 'limit': 100}, 5)
        result['mcp_status'] = [{'name': x['name'], 'runtime_status': x.get('runtimeStatus'),
                                'tool_count': len(x.get('tools', {}))} for x in status['data']]
        require(not status.get('nextCursor') and all((x['runtime_status'].get('status') if isinstance(x['runtime_status'],dict)
                else x['runtime_status']) == 'disabled' and x['tool_count'] == 0 for x in result['mcp_status']), 'mcp_not_disabled')
        relay.thread_id, relay.armed = result['thread_id'], True
        turn = rpc.request('turn/start', {'threadId': result['thread_id'],
            'input': [{'type': 'text', 'text': PROMPT}], 'effort': 'high', 'model': 'gpt-6.1-sol'}, 6)
        result['turn_id'] = turn['turn']['id']
        save_new(run / 'turn-start.json', turn)
        while True:
            require(time.monotonic() - start < 600, 'casefree_time_budget')
            require(relay.failed is None, 'relay_failed')
            if rpc.pending_tools:
                message = rpc.pending_tools.pop(0)
            else:
                try:
                    message = rpc.receive(min(1, max(0.01, 600 - (time.monotonic() - start))))
                except queue.Empty:
                    continue
            observe(message)
            require(message.get('method') != 'error', 'unexpected_native_error')
            if 'method' in message and 'id' in message:
                handle_tool(message)
            elif message.get('method') == 'turn/completed':
                require(message['params']['threadId'] == result['thread_id']
                        and message['params']['turn']['id'] == result['turn_id'], 'turn_completion_mismatch')
                result['completed_turn'] = message['params']['turn']
                require(result['completed_turn']['status'] == 'completed'
                        and result['completed_turn'].get('error') is None, 'native_turn_not_completed')
                break
        require((work / 'input/channel-check.txt').read_bytes() == nonce, 'input_changed')
        require((work / 'work/channel-check.txt').read_bytes() == nonce, 'nonce_file_mismatch')
        require(any(c['tool'] == 'case_read' and c['arguments'].get('scope') == 'package'
                    and c['arguments'].get('path') == 'README.md' and c['answer']['result']['start_line'] == 1
                    and c['answer']['result']['end_line'] == 8 for c in bridge.calls), 'readme_not_read_1_8')
        actual_files = sorted(p.relative_to(work).as_posix() for p in work.rglob('*') if p.is_file())
        require(actual_files == ['input/channel-check.txt', 'work/channel-check.txt'], 'unexpected_workspace_files')
        result['functional_checks'] = {'exact_nonce_copy_no_newline': True, 'input_unchanged': True,
                                       'readme_actual_lines': [1,8], 'files': actual_files}
        result['status'] = 'native_function_loop_completed_pending_full_review'
    except Exception as error:
        result['status'] = 'native_casefree_failed'
        result['failure_type'] = type(error).__name__
        result['failure_category'] = str(error) if isinstance(error, SessionError) else 'operator_or_transport_error'
        print(json.dumps({'stage': 'probe_stopped', 'failure': result['failure_category'],
                          'relay_failure': relay.failed}), flush=True)
    finally:
        relay.armed = False
        if child is not None and child.poll() is None:
            if result.get('turn_id') and not result.get('completed_turn'):
                try:
                    result['interrupt'] = rpc.request('turn/interrupt',
                        {'threadId': result['thread_id'], 'turnId': result['turn_id']}, 90, timeout=10)
                except Exception as error:
                    result['interrupt_error'] = type(error).__name__
            if result.get('thread_id'):
                try:
                    result['unsubscribe'] = rpc.request('thread/unsubscribe', {'threadId': result['thread_id']}, 91, timeout=10)
                    for message in rpc.frames:
                        observe(message)
                    deadline = time.monotonic() + 10
                    while result['thread_id'] not in result['closed_thread_ids']:
                        message = rpc.receive(max(0.01, deadline - time.monotonic()))
                        observe(message)
                        require(time.monotonic() < deadline, 'thread_close_deadline')
                    result['owned_thread_closed_before_stdin_close'] = True
                except Exception as error:
                    result['thread_close_error'] = type(error).__name__
            closed = time.monotonic()
            child.stdin.close()
            try:
                child.wait(timeout=5)
                result['five_second_exit'] = 'met_this_run'
            except subprocess.TimeoutExpired:
                result['five_second_exit'] = 'failed_this_run'
                try:
                    child.wait(timeout=10)
                    result['diagnostic_late_exit'] = True
                except subprocess.TimeoutExpired:
                    result['cleanup_incomplete'] = True
            result['exit_seconds_after_stdin_close'] = round(time.monotonic() - closed, 6)
        if child is not None:
            result['exit_code'] = child.poll()
        if rpc is not None:
            rpc.reader.join(timeout=1)
            result['rpc_reader_finished'] = not rpc.reader.is_alive()
        if stderr_thread is not None:
            stderr_thread.join(timeout=1)
        result['relay_cleanup'] = relay.close()
        result['relay_failure'] = relay.failed
        result['requests'] = relay.requests
        result['metadata_gets'] = relay.metadata_gets
        result['local_http_negotiations'] = relay.negotiations
        result['tool_calls'] = len(bridge.calls)
        result['stderr'] = {**stderr_info, 'sha256': stderr_hash.hexdigest(), 'body_not_recorded': True}
        result['elapsed_seconds'] = round(time.monotonic() - start, 6)
        result['workspace_files'] = [{'path': p.relative_to(work).as_posix(), 'sha256': sha(p.read_bytes()),
                                      'bytes': p.stat().st_size} for p in work.rglob('*') if p.is_file()]
        result['external_workspace_retained'] = True
        stdout.close()
        outbound.close()
        save_new(run / 'result.json', result)
        print(json.dumps({k: result.get(k) for k in ['status','pid','failure_category','relay_failure','tool_calls',
            'five_second_exit','exit_code','elapsed_seconds','cleanup_incomplete']},ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
