"""Version-pinned operator evaluation transport; never persists authentication headers.

Local tests mock inference and use a synthetic child, not an account or model.
This module is outside the skill runtime bundle and is not an authorization gate.
"""
import argparse
import hashlib
import http.client
import http.server
import json
import os
import re
import socket
from pathlib import Path
import ssl
import subprocess
import threading
import time

CLI = Path('D:/npm-global/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe')
TRANSPORT_VERSION = '1.0'
LOCAL_PROVIDER_ID = 'dyz_official_eval'
DISABLED_FEATURES = ('shell_tool', 'unified_exec', 'apply_patch_freeform', 'code_mode', 'code_mode_host', 'code_mode_only', 'js_repl', 'js_repl_tools_only', 'multi_agent', 'multi_agent_v2', 'collab', 'agent_message_board', 'enable_fanout', 'apps', 'plugins', 'remote_plugin', 'plugin_discovery_prefetch', 'recommended_plugins', 'hooks', 'codex_hooks', 'plugin_hooks', 'memories', 'memory_tool', 'external_agent_memory_import', 'skill_search', 'skill_catalog_deltas', 'skill_mcp_dependency_install', 'skill_env_var_dependency_prompt', 'browser_use', 'browser_use_external', 'browser_use_full_cdp_access', 'in_app_browser', 'computer_use', 'image_generation', 'imagegenext', 'view_image', 'web_search', 'web_search_cached', 'web_search_request', 'standalone_web_search', 'search_tool', 'sleep_tool', 'goals', 'request_permissions', 'request_permissions_tool', 'request_rule', 'default_mode_request_user_input', 'send_async_message', 'send_message_to_user_async', 'workspace_dependencies', 'context_management', 'current_time_reminder', 'model_catalog_in_context', 'responses_websockets', 'responses_websockets_v2', 'remote_models', 'enable_request_compression', 'shell_snapshot', 'shell_snapshot_v2', 'personality', 'tool_suggest', 'tool_search', 'daemon_auto_start', 'worktrees')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def save(path, obj):
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')

def settings(port, protocol):
    PROTOCOL = Path(protocol)
    cfg = {f'features.{key}': False for key in DISABLED_FEATURES}
    cfg.update({
        'features.skip_host_skill_discovery': True,
        'model': 'gpt-6.1-sol', 'model_provider': LOCAL_PROVIDER_ID, 'model_reasoning_effort': 'high',
        'model_instructions_file': PROTOCOL.as_posix(),
        'developer_instructions': '', 'project_doc_max_bytes': 0,
        'include_environment_context': False, 'include_environment_context_time': False,
        'include_permissions_instructions': False, 'include_apps_instructions': False,
        'include_collaboration_mode_instructions': False,
        'skills.include_instructions': False, 'skills.bundled.enabled': False,
        'agents.enabled': False, 'apps._default.enabled': False,
        'plugins._default.enabled': False, 'mcp_servers': {},
        'tools.update_plan.enabled': False, 'tools.experimental_request_user_input.enabled': False,
        'web_search': 'disabled', 'history.persistence': 'none',
        'analytics.enabled': False, 'otel.exporter': 'none', 'otel.trace_exporter': 'none',
        'otel.metrics_exporter': 'none',
        'openai_base_url': f'http://127.0.0.1:{port}/backend-api/codex',
        f'model_providers.{LOCAL_PROVIDER_ID}.name': 'Official OpenAI via local evaluation relay',
        f'model_providers.{LOCAL_PROVIDER_ID}.base_url': f'http://127.0.0.1:{port}/backend-api/codex',
        f'model_providers.{LOCAL_PROVIDER_ID}.wire_api': 'responses',
        f'model_providers.{LOCAL_PROVIDER_ID}.requires_openai_auth': True,
        f'model_providers.{LOCAL_PROVIDER_ID}.supports_websockets': False,
        f'model_providers.{LOCAL_PROVIDER_ID}.stream_idle_timeout_ms': 660_000,
        f'model_providers.{LOCAL_PROVIDER_ID}.stream_max_retries': 0,
        f'model_providers.{LOCAL_PROVIDER_ID}.request_max_retries': 0,
    })
    return cfg

def toml_value(value):
    if isinstance(value, bool): return str(value).lower()
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict): return '{}'
    return str(value)

def run(name, *, base, protocol, prepared, cli=CLI, forward=False):
    BASE, PROTOCOL, CLI = Path(base).resolve(), Path(protocol).resolve(), Path(cli).resolve()
    prepared = str(Path(prepared).resolve())
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name):
        raise ValueError('invalid run name')
    if not BASE.is_dir() or not CLI.is_file():
        raise ValueError('existing base and CLI required')
    protocol = PROTOCOL.read_text(encoding='utf-8')
    packet = json.loads(Path(prepared).read_text(encoding='utf-8'))
    if not isinstance(packet, dict):
        raise ValueError('prepared object required')
    messages = packet.get('messages')
    if (not isinstance(messages, list) or len(messages) != 2 or
            not all(isinstance(message, dict) for message in messages) or
            messages[0].get('role') != 'developer' or messages[0].get('content') != protocol or
            messages[1].get('role') != 'user' or not isinstance(messages[1].get('content'), str) or
            not messages[1]['content'].strip()):
        raise ValueError('prepared protocol and two-message packet required')
    user = messages[1]['content']
    folder = BASE / 'channel' / name
    folder.mkdir(parents=True, exist_ok=False)
    workdir = folder / 'empty-workdir'
    workdir.mkdir()
    requests = []
    state_lock = threading.RLock()
    stopping = threading.Event()
    active_upstreams = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_): pass
        def do_GET(self):
            self.send_error(404)
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            with state_lock:
                ordinal = len(requests) + 1
                audit = {'ordinal': ordinal, 'path': self.path, 'time': time.time(), 'sha256': sha(body),
                         'bytes': len(body), 'stream_outcome': 'not_forwarded'}
                requests.append(audit)
            upstream = response = None
            try:
                data = json.loads(body)
                texts = []
                for item in data.get('input', []):
                    texts.append({'type': item.get('type'), 'role': item.get('role'), 'content': item.get('content')})
                expected_input = len(texts) == 1 and texts[0]['role'] == 'user' and texts[0]['content'] == [{'type': 'input_text', 'text': user}]
                instructions_match = data.get('instructions', '').replace('\r\n','\n').rstrip() == protocol.replace('\r\n','\n').rstrip()
                audit.update({'model': data.get('model'), 'reasoning': data.get('reasoning'), 'tools': [t.get('name', t.get('type')) for t in data.get('tools', [])],
                    'input_summary': [{'type': t['type'], 'role': t['role'], 'bytes': len(json.dumps(t['content'], ensure_ascii=False).encode('utf-8')), 'sha256': sha(json.dumps(t['content'], ensure_ascii=False).encode('utf-8'))} for t in texts],
                    'keys': sorted(data), 'instructions_match': instructions_match, 'input_match': expected_input,
                    'has_parent': bool(data.get('previous_response_id') or data.get('conversation')),
                    'request_token_cap': data.get('max_output_tokens', data.get('max_tokens'))})
                audit['input_structure'] = []
                for item in data.get('input', []):
                    item_text = json.dumps(item, ensure_ascii=False)
                    audit['input_structure'].append({'keys': list(item), 'role': item.get('role'), 'type': item.get('type'),
                        'protocol_contained': protocol.strip() in item_text or protocol in item_text,
                        'text_matches': [c.get('text', '').replace('\r\n','\n').rstrip() == protocol.replace('\r\n','\n').rstrip() for c in (item.get('content') or []) if isinstance(c,dict)],
                        'known_tags': re.findall(r'<[/]?([a-zA-Z_][a-zA-Z_ -]*)>', item_text),
                        'known_markers': [m for m in ['AGENTS.md','environment_context','skills_instructions','D:\\dyz-patent-skills','D:/dyz-patent-skills','Windows','sandbox','orchestrator','multi_agent','Codex','current_date'] if m in item_text],
                        'tool_names': [t.get('name',t.get('type')) for t in item.get('tools', [])]})
                # Normalize the final outbound request from frozen caller inputs.
                # Never carry client-discovered instructions, tools, metadata, a cache
                # key, or conversation links across this boundary. The CLI remains
                # the authenticated client and consumes the official raw response.
                final = {
                    'model': 'gpt-6.1-sol',
                    'input': [
                        {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': protocol}]},
                        {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': user}]},
                    ],
                    'tools': [], 'tool_choice': 'none', 'parallel_tool_calls': False,
                    'store': False, 'stream': True, 'reasoning': {'effort': 'high', 'context': 'all_turns'},
                }
                valid = (data.get('model') == 'gpt-6.1-sol' and data.get('reasoning', {}).get('effort') == 'high'
                         and audit['request_token_cap'] is None and ordinal == 1 and not stopping.is_set())
                body = json.dumps(final, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                audit['normalization'] = 'frozen_protocol_and_user_only_v2'
                audit['outbound_sha256'] = sha(body)
                audit['outbound_tools'] = []
                audit['outbound_parent_links'] = []
                audit['allowlisted_request'] = valid
                if valid:
                    (folder / f'request-{ordinal}.json').write_bytes(body)
                if not (valid and forward):
                    payload = json.dumps({'error': {'message': 'Local evaluation request not forwarded.', 'type': 'local_inspection'}}).encode()
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                # Exact endpoint allowlist. Authentication lives only in memory and is
                # forwarded to the official service; headers are never written to disk.
                if self.path != '/backend-api/codex/responses':
                    raise ValueError('unexpected inference path')
                headers = {k: v for k,v in self.headers.items() if k.lower() not in {'host','connection','accept-encoding','content-length'}}
                headers['Accept-Encoding'] = 'identity'
                upstream = http.client.HTTPSConnection('chatgpt.com', timeout=30, context=ssl.create_default_context())
                entry = {'connection': upstream, 'socket': None}
                with state_lock:
                    if stopping.is_set():
                        raise ConnectionAbortedError('caller exited before forwarding')
                    active_upstreams[ordinal] = entry
                audit['forward_attempted'] = True
                audit['forward_started_at'] = time.time()
                upstream.request('POST', self.path, body=body, headers=headers)
                audit['request_sent'] = True
                audit['request_sent_at'] = time.time()
                audit['forwarded_body_sha256'] = sha(body)
                # Retain this owned socket object before getresponse can detach it
                # for a Connection: close response. Never reconstruct a reused fd.
                entry['socket'] = upstream.sock
                if entry['socket'] is not None:
                    entry['socket'].settimeout(600)
                if stopping.is_set():
                    raise ConnectionAbortedError('caller exited while forwarding')
                response = upstream.getresponse()
                audit['upstream_status'] = response.status
                audit['upstream_response_started_at'] = time.time()
                audit['upstream_request_id'] = response.getheader('x-request-id')
                audit['stream_outcome'] = 'streaming' if response.status == 200 else 'upstream_http_error'
                self.send_response(response.status)
                self.send_header('Content-Type', response.getheader('Content-Type', 'application/octet-stream'))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                with (folder / f'response-{ordinal}.sse').open('xb') as f:
                    while True:
                        if stopping.is_set():
                            audit['stream_outcome'] = 'cancelled_after_cli_exit'
                            break
                        chunk = response.readline()
                        if not chunk:
                            if response.status == 200:
                                audit['stream_outcome'] = 'eof_without_terminal'
                            break
                        f.write(chunk)
                        f.flush()
                        audit['last_raw_activity_at'] = time.time()
                        terminal_event = False
                        if chunk.startswith(b'data: '):
                            try:
                                event = json.loads(chunk[6:])
                                terminal_event = event.get('type') in {'response.completed', 'response.failed', 'response.incomplete'}
                                if terminal_event:
                                    audit['terminal_event_observed'] = event['type']
                                item = event.get('item', {})
                                if item.get('type') not in {None, 'message', 'reasoning'}:
                                    audit['unexpected_output_item_type'] = item.get('type')
                                    audit['stream_outcome'] = 'unexpected_output_item'
                                    break
                            except json.JSONDecodeError:
                                pass
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        if terminal_event:
                            # SSE event is dispatched only after its blank delimiter.
                            separator = response.readline()
                            if separator not in {b'\n', b'\r\n'}:
                                audit['stream_outcome'] = 'terminal_delimiter_missing'
                                raise ValueError('terminal SSE delimiter missing')
                            f.write(separator)
                            f.flush()
                            self.wfile.write(separator)
                            self.wfile.flush()
                            audit['terminal_delimiter_observed'] = True
                            audit['stream_outcome'] = audit['terminal_event_observed'].removeprefix('response.')
                            break
            except Exception as exc:
                audit['exception_type'] = type(exc).__name__
                if audit['stream_outcome'] in {'not_forwarded', 'streaming'}:
                    audit['stream_outcome'] = ('cancelled_after_cli_exit' if stopping.is_set()
                                               else 'upstream_or_downstream_error')
                # Do not include exception text that might contain header values.
            finally:
                # Only this request owns these resources; cleanup also covers
                # header errors, peer disconnects and incomplete streams.
                for resource in (response, upstream):
                    if resource is not None:
                        try:
                            resource.close()
                        except Exception as close_error:
                            audit.setdefault('cleanup_exception_types', []).append(type(close_error).__name__)
                with state_lock:
                    active_upstreams.pop(ordinal, None)
                audit['usage_status'] = ('not_extracted_from_completed_response' if audit['stream_outcome'] == 'completed'
                                         else 'unknown_not_zero' if audit.get('forward_attempted') else 'not_forwarded')
                audit['finalized_at'] = time.time()
                try:
                    raw = folder / f'response-{ordinal}.sse'
                    if raw.exists():
                        audit['response_sha256'] = sha(raw.read_bytes())
                        audit['response_bytes'] = raw.stat().st_size
                    audit['archive_saved'] = True
                    save(folder / f'request-{ordinal}-audit.json', audit)
                except Exception as archive_error:
                    audit['archive_saved'] = False
                    audit['archive_exception_type'] = type(archive_error).__name__

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    proc = None
    cleanup_errors = []
    try:
        server_thread.start()
        cfg = settings(server.server_port, PROTOCOL)
        args = [str(CLI), 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--json', '-s', 'read-only', '-C', str(workdir), '-o', str(folder / 'last-message.txt')]
        for k,v in cfg.items(): args.extend(['-c', f'{k}={toml_value(v)}'])
        args.append('-')
        allowed_env = {'systemroot','windir','comspec','temp','tmp','userprofile','appdata','localappdata','path','pathext','homedrive','homepath','programdata','os'}
        env = {k:v for k,v in os.environ.items() if k.lower() in allowed_env}
        save(folder / 'launch.json', {'transport_version': TRANSPORT_VERSION, 'cli': str(CLI), 'args': args[1:], 'config': cfg, 'environment_keys': sorted(env), 'forward': forward, 'official_upstream': 'https://chatgpt.com/backend-api/codex/responses', 'user_text_sha256': sha(user.encode('utf-8')), 'prepared': prepared, 'header_logging': False, 'authentication_config_read_by_coordinator': False})
        (folder / 'user-input.txt').write_text(user, encoding='utf-8', newline='')
        with (folder / 'stdout.jsonl').open('xb') as out, (folder / 'stderr.txt').open('xb') as err:
            proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=out, stderr=err, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            print(json.dumps({'name': name, 'pid': proc.pid, 'forward': forward}), flush=True)
            proc.communicate(user.encode('utf-8'))
    finally:
        stopping.set()
        with state_lock:
            owned = list(active_upstreams.values())
        for entry in owned:
            owned_socket = entry['socket'] or entry['connection'].sock
            if owned_socket is not None:
                try:
                    owned_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            try:
                entry['connection'].close()
            except Exception as close_error:
                cleanup_errors.append(type(close_error).__name__)
        if server_thread.is_alive():
            server.shutdown()
        server.server_close()
        if server_thread.ident is not None:
            server_thread.join()
    # Finalize only after all handlers have archived their actual outcome.
    sent = sum(bool(r.get('request_sent')) for r in requests)
    complete = (forward and proc.returncode == 0 and len(requests) == 1 and sent == 1
                and requests[0]['stream_outcome'] == 'completed'
                and requests[0].get('archive_saved') is True
                and not requests[0].get('cleanup_exception_types') and not cleanup_errors)
    code = (0 if complete else 1) if forward else proc.returncode
    summary = {'transport_version': TRANSPORT_VERSION, 'mode': 'forward' if forward else 'inspection_only',
               'exit_code': proc.returncode, 'effective_exit_code': code,
               'requests': requests, 'transport_complete': bool(complete),
               'forward_attempts': sum(bool(r.get('forward_attempted')) for r in requests),
               'model_requests_forwarded': sent,
               'upstream_responses_started': sum('upstream_status' in r for r in requests),
               'token_cap': None,
               'cleanup': {'active_upstreams_after_join': len(active_upstreams),
                           'cancelled_owned_streams': len(owned),
                           'exception_types': cleanup_errors,
                           'listener_closed': server.socket.fileno() == -1}}
    save(folder / 'summary.json', summary)
    print(json.dumps({'name': name, 'exit_code': proc.returncode, 'effective_exit_code': code,
                      'request_count': len(requests), 'model_requests_forwarded': sent}), flush=True)
    return code

if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Operator-only evaluation; forwarding requires authorization and admission.')
    p.add_argument('name')
    p.add_argument('--base', required=True)
    p.add_argument('--protocol', required=True)
    p.add_argument('--prepared', required=True)
    p.add_argument('--cli', default=str(CLI))
    p.add_argument('--forward', action='store_true')
    args = p.parse_args()
    raise SystemExit(run(args.name, base=args.base, protocol=args.protocol, prepared=args.prepared,
                         cli=args.cli, forward=args.forward))
