"""Native evaluation RPC/HTTP plumbing, outside the shipped runtime package.

The installed CLI owns authentication. The relay never logs headers, never
follows redirects, and forwards only to the fixed official Responses endpoint.
Native configuration/background I/O is not an OS isolation boundary.
"""
from __future__ import annotations

import hashlib
import http.client
import http.server
import json
import os
from pathlib import Path
import queue
import select
import socket
import ssl
import tempfile
import threading
import time

from tools.codex_host import native_process_counters

DEFAULT_REQUEST_BODY_BYTES = 2_000_000
MAX_REQUEST_BODY_BYTES = 8_000_000
REQUEST_BODY_READ_SECONDS = 30


def read_request_body(connection, stream, length, *, timeout, stopped, audit):
    """Keep buffered header-tail bytes, with a total deadline and cooperative stop."""
    received = bytearray()
    previous_timeout = connection.gettimeout()
    started = time.perf_counter()
    audit['body_read_started_monotonic'] = time.monotonic()
    audit['body_read_started_perf_counter'] = started
    audit['body_read_clock'] = 'perf_counter'
    connection.setblocking(False)
    try:
        while len(received) < length:
            require(not stopped.is_set(), 'relay_stopped_during_body_read')
            remaining = timeout - (time.perf_counter() - started)
            require(remaining > 0, 'request_body_timeout')
            try:
                chunk = stream.read1(min(65536, length - len(received)))
            except BlockingIOError:
                chunk = None
            if chunk:
                received.extend(chunk)
                continue
            # BufferedReader.read1 can return empty for a nonblocking would-read.
            # Peeking the socket distinguishes that state from an actual EOF.
            try:
                pending = connection.recv(1, socket.MSG_PEEK)
            except BlockingIOError:
                select.select([connection], [], [], min(0.1, remaining))
                continue
            if not pending:
                break
        require(not stopped.is_set(), 'relay_stopped_during_body_read')
        require(time.perf_counter() - started <= timeout, 'request_body_timeout')
        return bytes(received)
    except (OSError, ValueError) as error:
        if stopped.is_set():
            raise SessionError('relay_stopped_during_body_read') from error
        raise
    finally:
        audit['body_read_elapsed_seconds'] = round(time.perf_counter() - started, 6)
        audit['received_request_body_bytes'] = len(received)
        audit['received_request_body_sha256'] = sha(received)
        try:
            connection.settimeout(previous_timeout)
        except OSError:
            if not stopped.is_set():
                raise


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save_new(path, data):
    with Path(path).open('x', encoding='utf-8', newline='\n') as file:
        file.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


class SessionError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise SessionError(code)


def await_input_review(marker,deadline,stopped):
    """Read a complete review without an exists/stat then open race.

    Only a missing file means no review yet. Other I/O failures remain fatal;
    they are never silently converted to absence or retried as approvals.
    """
    while True:
        require(not stopped.is_set() and time.monotonic()<deadline,'input_review_deadline')
        try:raw=Path(marker).read_bytes()
        except FileNotFoundError:
            time.sleep(0.1);continue
        require(len(raw)<=4_000_000,'input_review_size')
        def unique(pairs):
            value={}
            for key,item in pairs:
                require(key not in value,'input_review_duplicate_key');value[key]=item
            return value
        review=json.loads(raw,object_pairs_hook=unique,
            parse_constant=lambda _:(_ for _ in ()).throw(SessionError('input_review_nonfinite_json')))
        require(isinstance(review,dict),'input_review_object_required')
        return review


def publish_input_review(marker,review):
    """Publish complete bytes exclusively; caller owns this local directory.

    An exclusive hard link makes the closed, flushed sibling file visible in
    one step on the tested local filesystem. Never replace an old approval.
    This publishes an operator review; it does not create or infer approval.
    """
    marker=Path(marker);require(isinstance(review,dict),'input_review_object_required')
    raw=json.dumps(review,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')+b'\n'
    require(len(raw)<=4_000_000,'input_review_size')
    descriptor,name=tempfile.mkstemp(dir=marker.parent,prefix='input-review-',suffix='.json.tmp')
    staged=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.link(staged,marker)
    finally:staged.unlink()


def visible_functions(data):
    """Native Codex can put tools in input.additional_tools, not just top level."""
    roots = list(data.get('tools', []))
    for item in data.get('input', []):
        if item.get('type') == 'additional_tools':
            roots.extend(item.get('tools', []))
    result = {}

    def walk(rows, prefix=''):
        for item in rows:
            kind, name = item.get('type'), item.get('name')
            require(isinstance(name, str) and name, 'tool_name_missing')
            if kind == 'namespace':
                require(name == 'functions' and not prefix, 'unexpected_namespace')
                walk(item.get('tools', []), name + '.')
            else:
                require(kind == 'function', 'unexpected_tool_type')
                leaf = name.removeprefix('functions.')
                require('.' not in leaf and leaf not in result, 'duplicate_or_foreign_tool')
                result[leaf] = {'qualified_name': prefix + name,
                                'parameters': item.get('parameters', item.get('inputSchema'))}
    walk(roots)
    return result


def native_wire_schema(schema):
    """Observed0.160.1 conversion omits numeric bounds/regex, not client checks.

    Preserve all other schema fields exactly. This declares the expected wire
    representation; it never edits a request or relaxes the execution bridge.
    """
    result = {}
    for key, value in schema.items():
        if key in {'minimum', 'maximum', 'pattern'}:
            continue
        if key == 'properties':
            value = {name: native_wire_schema(child) for name, child in value.items()}
        result[key] = value
    return result


def validate_native_request(data, *, specs, prompt, thread_id, initial, response_ids, call_ids):
    require(isinstance(data, dict) and isinstance(data.get('input'), list), 'native_input_required')
    require(data.get('model') == 'gpt-6.1-sol', 'model_mismatch')
    require(isinstance(data.get('reasoning'), dict) and data['reasoning'].get('effort') == 'high', 'reasoning_mismatch')
    require(data.get('store') is False and data.get('stream') is True, 'storage_or_stream_mismatch')
    require(not any(k in data for k in ('max_tokens', 'max_output_tokens')), 'token_cap_present')
    require(not data.get('conversation'), 'external_conversation')
    previous = data.get('previous_response_id')
    require(previous is None or previous in response_ids, 'unknown_previous_response')
    if initial:
        require(previous is None, 'initial_continuation')
        require(all(x.get('type') in {'message', 'additional_tools'} for x in data['input']), 'initial_history_item')
        require(not any(x.get('role') == 'assistant' for x in data['input']), 'initial_assistant_history')
    texts = [c.get('text', '') for item in data['input'] if item.get('role') == 'user'
             for c in item.get('content', []) if isinstance(c, dict)]
    require(previous is not None or sum(prompt in x for x in texts) == 1, 'task_prompt_not_bound')
    metadata = data.get('client_metadata', {})
    if 'thread_id' in metadata:
        require(metadata['thread_id'] == thread_id, 'native_thread_mismatch')
    for item in data['input']:
        if item.get('type') == 'function_call_output':
            require(item.get('call_id') in call_ids, 'unknown_tool_output')
    actual = visible_functions(data)
    expected = {x['name']: native_wire_schema(x['inputSchema']) for x in specs}
    if actual:
        require(set(actual) == set(expected), 'visible_tool_set_mismatch')
        require(all(actual[k]['parameters'] == expected[k] for k in expected), 'visible_tool_schema_mismatch')
    else:
        require(not initial and previous in response_ids, 'visible_tools_missing')
    return {'model': data['model'], 'reasoning_effort': data['reasoning']['effort'],
            'visible_tools': sorted(actual), 'schemas_match_native_projection': bool(actual),
            'bridge_source_schema_constraints_retained': True,
            'native_schema_omits': ['minimum', 'maximum', 'pattern'],
            'tools_inherited_from_known_response': not bool(actual), 'previous_response_id': previous,
            'initial_no_assistant_or_tool_history': initial,
            'native_thread_bound': metadata.get('thread_id') == thread_id}


def exception_sites(error):
    """Code locations only: no exception text, locals, headers or full paths."""
    sites = []
    trace = error.__traceback__
    while trace is not None:
        sites.append({'file': Path(trace.tb_frame.f_code.co_filename).name,
                      'function': trace.tb_frame.f_code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    return sites[-8:]


def relay_sse(response, sink, record, *, completed, stopped, observed=None, progress=None, clock=time.monotonic):
    """Keep the genuine terminal event and its genuine delimiter; invent nothing."""
    def read_line():
        started = clock()
        try:
            raw = response.readline()
            return raw, started, clock()
        except (OSError, ValueError, AttributeError) as error:
            if stopped.is_set():
                raise SessionError('relay_stopped_during_read') from error
            raise

    def report_read(raw, started, finished, kind):
        if progress is not None:
            progress({'bytes_read': len(raw), 'read_started_monotonic': started,
                      'read_finished_monotonic': finished, 'kind': kind})

    while True:
        require(not stopped.is_set(), 'relay_stopped')
        raw, started, finished = read_line()
        if not raw:
            report_read(raw, started, finished, 'eof')
        require(bool(raw), 'sse_eof_without_terminal')
        record.write(raw)
        record.flush()
        event = None
        if raw.startswith(b'data: '):
            try:
                event = json.loads(raw[6:])
            except json.JSONDecodeError:
                pass
        kinds = {'response.created': 'created', 'response.in_progress': 'in_progress',
                 'response.output_item.added': 'item_added', 'response.output_item.done': 'item_done',
                 'response.function_call_arguments.delta': 'argument_delta',
                 'response.output_text.delta': 'output_delta',
                 'response.reasoning_summary_text.delta': 'reasoning_delta',
                 'response.completed': 'terminal', 'response.failed': 'terminal', 'response.incomplete': 'terminal'}
        kind = kinds.get(event.get('type'), 'other_json') if isinstance(event, dict) else 'non_json'
        report_read(raw, started, finished, kind)
        if isinstance(event, dict) and observed is not None:
            observed(event)
        sink.write(raw)
        sink.flush()
        if isinstance(event, dict) and event.get('type') in {'response.completed', 'response.failed', 'response.incomplete'}:
            separator, started, finished = read_line()
            report_read(separator, started, finished, 'terminal_separator' if separator else 'eof')
            require(separator in {b'\n', b'\r\n'}, 'sse_terminal_delimiter_missing')
            record.write(separator)
            record.flush()
            # Bind returned call IDs before the native client can consume the
            # terminal delimiter and submit the next request.
            completed(event)
            sink.write(separator)
            sink.flush()
            return event['type']


class NativeRelay:
    def __init__(self, folder, metadata, specs, prompt, *, max_requests=6, review_seconds=300,
                 review_authorization='existing_official_cli_casefree_scope', request_guard=None,
                 max_request_body_bytes=DEFAULT_REQUEST_BODY_BYTES,
                 body_read_timeout_seconds=REQUEST_BODY_READ_SECONDS):
        require(review_authorization in {'existing_official_cli_casefree_scope',
                'existing_official_cli_synthetic_skill_evaluation'}, 'review_authorization_scope')
        require(type(max_request_body_bytes) is int and 0 < max_request_body_bytes <= MAX_REQUEST_BODY_BYTES,
                'request_body_budget')
        require(type(body_read_timeout_seconds) in {int, float} and 0 < body_read_timeout_seconds <= REQUEST_BODY_READ_SECONDS,
                'request_body_timeout_budget')
        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=False)
        self.metadata = metadata
        self.specs, self.prompt = specs, prompt
        self.max_requests, self.review_seconds = max_requests, review_seconds
        self.review_authorization, self.request_guard = review_authorization, request_guard
        self.request_limits = {'max_request_body_bytes': max_request_body_bytes,
                               'body_read_timeout_seconds': body_read_timeout_seconds}
        self.thread_id = None
        self.armed = False
        self.requests, self.metadata_gets = [], []
        self.negotiations = []
        self.response_ids, self.call_ids = set(), set()
        self.calls = {}
        self.output_items = {}
        self.failed = None
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.active = {}
        self.incoming = {}
        self.handlers = []
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == '/backend-api/codex/responses' and self.headers.get('Upgrade', '').lower() == 'websocket':
                    # Native0.160.1 explicitly recognizes426 as an immediate
                    # HTTP negotiation, avoiding failed reconnect loops.
                    relay.negotiations.append({'path': self.path, 'status': 426, 'external_forward': False})
                    if len(relay.negotiations) > 2:
                        relay.failed = 'unexpected_repeated_transport_negotiation'
                    self.send_response(426)
                    self.send_header('Content-Length', '0')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    return
                audit = {'path': self.path, 'external_forward': False}
                relay.metadata_gets.append(audit)
                valid = self.path == '/backend-api/codex/models?client_version=0.160.1'
                if not valid:
                    relay.failed = 'unexpected_get_endpoint'
                raw = relay.metadata if valid else b''
                try:
                    self.send_response(200 if valid else 404)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    if raw:
                        self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    audit['client_disconnected'] = True
                self.close_connection = True

            def do_POST(self):
                relay.handlers.append(threading.current_thread())
                with relay.lock:
                    ordinal = len(relay.requests) + 1
                    audit = {'ordinal': ordinal, 'forwarded': False, 'request_limits': dict(relay.request_limits)}
                    relay.requests.append(audit)
                    relay.incoming[ordinal] = self.connection
                connection = None
                sent_headers = False
                try:
                    require(self.path == '/backend-api/codex/responses', 'endpoint_mismatch')
                    require(relay.armed and relay.thread_id is not None, 'inference_not_armed')
                    require(relay.failed is None and not relay.stopped.is_set(), 'prior_failure_stopped')
                    require(ordinal <= relay.max_requests, 'request_budget_reached')
                    lengths = self.headers.get_all('Content-Length', [])
                    audit['content_length_header_count'] = len(lengths)
                    require(not self.headers.get_all('Transfer-Encoding', []), 'request_transfer_encoding_unsupported')
                    length_text = lengths[0].strip(' \t') if len(lengths) == 1 else ''
                    require(len(lengths) == 1 and len(length_text) <= 16 and length_text.isascii()
                            and length_text.isdigit(), 'request_length_invalid')
                    length = int(length_text)
                    audit['declared_request_body_bytes'] = length
                    require(0 < length <= relay.request_limits['max_request_body_bytes'], 'request_size')
                    raw = read_request_body(self.connection, self.rfile, length,
                        timeout=relay.request_limits['body_read_timeout_seconds'], stopped=relay.stopped, audit=audit)
                    require(len(raw) == length, 'request_incomplete')
                    data = json.loads(raw)
                    (relay.folder / f'request-{ordinal}.json').write_bytes(raw)
                    audit['body_sha256'] = sha(raw)
                    # Retain even a rejected visible declaration for operator diagnosis.
                    audit['visible_declarations'] = visible_functions(data)
                    audit['validation'] = validate_native_request(data, specs=relay.specs, prompt=relay.prompt,
                        thread_id=relay.thread_id, initial=ordinal == 1,
                        response_ids=relay.response_ids, call_ids=relay.call_ids)
                    if relay.request_guard is not None:
                        audit['runner_guard'] = relay.request_guard(data, ordinal == 1)
                    if ordinal == 1:
                        audit['stage']='waiting_for_local_input_review'
                        save_new(relay.folder / 'first-request-review.json', audit)
                        print(json.dumps({'stage': 'first_native_request_waiting_local_input_review',
                                          'body_sha256': audit['body_sha256'],
                                          'visible_tools': sorted(audit['visible_declarations'])}), flush=True)
                        deadline = time.monotonic() + relay.review_seconds
                        marker = relay.folder / 'input-reviewed.json'
                        review = await_input_review(marker,deadline,relay.stopped)
                        require(review.get('request_body_sha256') == audit['body_sha256']
                                and review.get('authorization') == relay.review_authorization
                                and review.get('visible_input_reviewed') is True, 'input_review_not_bound')
                        audit['stage']='local_input_review_complete'
                    headers = {k: v for k, v in self.headers.items()
                               if k.lower() not in {'host', 'connection', 'accept-encoding', 'content-length'}}
                    headers['Accept-Encoding'] = 'identity'
                    connection = http.client.HTTPSConnection('chatgpt.com', timeout=600, context=ssl.create_default_context())
                    with relay.lock:
                        relay.active[ordinal] = {'connection': connection, 'socket': None}
                    connection.request('POST', '/backend-api/codex/responses', body=raw, headers=headers)
                    audit['forwarded'] = True
                    audit['forwarded_body_sha256'] = sha(raw)
                    with relay.lock:
                        relay.active[ordinal]['socket'] = connection.sock
                    response = connection.getresponse()
                    audit['upstream_status'] = response.status
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.getheader('Content-Type', 'application/octet-stream'))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    sent_headers = True
                    require(response.status == 200, 'upstream_http_error')

                    def observe(event):
                        if event.get('type') == 'response.output_item.done':
                            item = event.get('item', {})
                            if item.get('id'):
                                relay.output_items[item['id']] = item
                            relay.bind_actual_function_item(item)

                    def completed(event):
                        audit['terminal_type'] = event['type']
                        audit['actual_terminal_delimiter'] = True
                        payload = event.get('response', {})
                        audit['usage'] = payload.get('usage')
                        audit['response_id'] = payload.get('id')
                        audit['response_model'] = payload.get('model')
                        if payload.get('id'):
                            relay.response_ids.add(payload['id'])
                        for item in payload.get('output', []):
                            if item.get('id'):
                                relay.output_items[item['id']] = item
                            relay.bind_actual_function_item(item)
                        require(event['type'] == 'response.completed', 'upstream_not_completed')

                    progress = {'read_calls': 0, 'bytes_read': 0, 'empty_reads': 0, 'kind_counts': {},
                        'first_byte_monotonic': None, 'last_byte_monotonic': None,
                        'last_read_finished_monotonic': None, 'max_read_wait_seconds': 0.0,
                        'clock': 'time.monotonic in the coordinator process',
                        'scope': 'Prospective HTTPResponse.readline completion times only; not packets or server generation. No earlier timing reconstruction.'}
                    audit['stream_progress'] = progress

                    def stream_read(meta):
                        progress['read_calls'] += 1
                        progress['last_read_finished_monotonic'] = meta['read_finished_monotonic']
                        progress['max_read_wait_seconds'] = max(progress['max_read_wait_seconds'],
                            meta['read_finished_monotonic'] - meta['read_started_monotonic'])
                        counts = progress['kind_counts']
                        counts[meta['kind']] = counts.get(meta['kind'], 0) + 1
                        if meta['bytes_read']:
                            progress['bytes_read'] += meta['bytes_read']
                            if progress['first_byte_monotonic'] is None:
                                progress['first_byte_monotonic'] = meta['read_finished_monotonic']
                            progress['last_byte_monotonic'] = meta['read_finished_monotonic']
                        else:
                            progress['empty_reads'] += 1

                    with (relay.folder / f'response-{ordinal}.sse').open('xb') as record:
                        relay_sse(response, self.wfile, record, completed=completed,
                                  stopped=relay.stopped, observed=observe, progress=stream_read)
                    audit['outcome'] = 'completed_with_genuine_delimiter'
                except Exception as error:
                    audit['failure_type'] = type(error).__name__
                    audit['failure_category'] = str(error) if isinstance(error, SessionError) else 'transport_or_parse_error'
                    if isinstance(error,OSError):
                        audit['os_error']={'errno':error.errno,'winerror':getattr(error,'winerror',None)}
                        if audit.get('stage')=='waiting_for_local_input_review':audit['failure_category']='local_input_review_io_error'
                    audit['failure_sites'] = exception_sites(error)
                    audit['failure_context'] = ('observed_during_requested_relay_shutdown' if relay.stopped.is_set()
                                                else 'active_request_failure')
                    audit['failure_observed_monotonic'] = time.monotonic()
                    if relay.failed is None:
                        relay.failed = audit['failure_category']
                    else:
                        audit['primary_stop_cause'] = relay.failed
                    if not sent_headers:
                        try:
                            self.send_response(400)
                            self.send_header('Content-Length', '0')
                            self.send_header('Connection', 'close')
                            self.end_headers()
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            pass
                    self.close_connection = True
                finally:
                    if connection is not None:
                        connection.close()
                    with relay.lock:
                        relay.active.pop(ordinal, None)
                        relay.incoming.pop(ordinal, None)
                    save_new(relay.folder / f'audit-{ordinal}.json', audit)
                    print(json.dumps({'stage': 'native_request_finished', 'ordinal': ordinal,
                                      'forwarded': audit['forwarded'], 'outcome': audit.get('outcome'),
                                      'failure': audit.get('failure_category')}), flush=True)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_port

    def bind_actual_function_item(self, item):
        if item.get('type') != 'function_call':
            return
        require(item.get('status') in {None, 'completed'}, 'function_item_not_completed')
        identity, name, arguments = item.get('call_id'), item.get('name'), item.get('arguments')
        require(isinstance(identity, str) and identity and name in {s['name'] for s in self.specs},
                'actual_function_item_identity')
        require(isinstance(arguments, str), 'actual_function_arguments')
        binding = {'name': name, 'arguments': json.loads(arguments), 'namespace': item.get('namespace')}
        require(isinstance(binding['arguments'], dict), 'actual_function_arguments_not_object')
        with self.lock:
            require(identity not in self.calls or self.calls[identity] == binding,
                    'actual_call_id_rebound')
            self.calls[identity] = binding
            self.call_ids.add(identity)

    def close(self):
        self.stopped.set()
        with self.lock:
            active = list(self.active.values())
            incoming = list(self.incoming.values())
        for item in active:
            sock = item['socket']
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
            item['connection'].close()
        for sock in incoming:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        deadline = time.monotonic() + 10
        for thread in list(self.handlers):
            thread.join(timeout=max(0, deadline - time.monotonic()))
        return {'listener_thread_finished': not self.thread.is_alive(),
                'request_threads_finished': all(not t.is_alive() for t in self.handlers),
                'active_upstreams': len(self.active)}


class NativeRpc:
    def __init__(self, process, log, outbound_log=None, diagnostic_log=None):
        self.process, self.log = process, log
        self.outbound_log = outbound_log
        self.diagnostic_log = diagnostic_log
        self.lifecycle = []
        self.progress_lock = threading.Lock()
        self.reader_progress = {'started_monotonic': None, 'stdout_bytes_read': 0,
                                'frames_queued': 0, 'pending_frame_bytes': 0, 'eof': False}
        self.queue = queue.Queue()
        self.pending_tools = []
        self.frames = []
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.record_lifecycle('rpc_created')

    def record_lifecycle(self, stage, *, method=None, identity=None, error=None):
        """Only owned-handle counters, protocol stages and bounded progress; no payloads."""
        with self.progress_lock:
            progress = dict(self.reader_progress)
        row = {'stage': stage, 'monotonic': time.monotonic(), 'wall_time_unix': time.time(),
               'native_process': native_process_counters(self.process),
               'returncode': self.process.poll(), 'reader_alive': self.reader.is_alive(),
               'reader_progress': progress, 'queued_frames': self.queue.qsize()}
        if method is not None:
            allowed = {'initialize', 'skills/list', 'model/list', 'thread/start', 'turn/start',
                       'turn/interrupt', 'thread/unsubscribe', 'mcpServerStatus/list'}
            row['method'] = method if method in allowed else 'other'
        if type(identity) is int:
            row['request_id'] = identity
        if error is not None:
            row['error_type'] = type(error).__name__
        self.lifecycle.append(row)
        if self.diagnostic_log is not None:
            self.diagnostic_log.write(json.dumps(row, ensure_ascii=False).encode('utf-8') + b'\n')
            self.diagnostic_log.flush()
        return row

    def _read(self):
        pending = bytearray()
        try:
            with self.progress_lock:
                self.reader_progress['started_monotonic'] = time.monotonic()
            read_chunk = getattr(self.process.stdout, 'read1', None) or self.process.stdout.read
            while True:
                raw = read_chunk(65536)
                with self.progress_lock:
                    self.reader_progress['stdout_bytes_read'] += len(raw)
                    self.reader_progress['last_read_monotonic'] = time.monotonic()
                    if not raw:
                        self.reader_progress['eof'] = True
                if not raw:
                    require(not pending, 'rpc_incomplete_frame')
                    self.queue.put(('eof', None))
                    return
                self.log.write(raw)
                self.log.flush()
                pending.extend(raw)
                while b'\n' in pending:
                    end = pending.index(b'\n') + 1
                    require(end <= 4_000_000, 'rpc_frame_limit')
                    frame = bytes(pending[:end])
                    del pending[:end]
                    self.queue.put(('message', json.loads(frame)))
                    with self.progress_lock:
                        self.reader_progress['frames_queued'] += 1
                with self.progress_lock:
                    self.reader_progress['pending_frame_bytes'] = len(pending)
                require(len(pending) <= 4_000_000, 'rpc_frame_limit')
        except Exception as error:
            with self.progress_lock:
                self.reader_progress['error_type'] = type(error).__name__
                self.reader_progress['pending_frame_bytes'] = len(pending)
                if isinstance(error, SessionError):
                    self.reader_progress['error_code'] = str(error)
            self.queue.put(('reader_error', type(error).__name__))

    def send(self, message):
        raw = json.dumps(message, ensure_ascii=False).encode('utf-8') + b'\n'
        if self.outbound_log is not None:
            self.outbound_log.write(raw)
            self.outbound_log.flush()
        self.process.stdin.write(raw)
        self.process.stdin.flush()

    def receive(self, timeout):
        kind, value = self.queue.get(timeout=timeout)
        require(kind == 'message', 'rpc_' + kind)
        self.frames.append(value)
        return value

    def request(self, method, params, identity, *, timeout=30):
        self.record_lifecycle('rpc_request_started', method=method, identity=identity)
        try:
            self.send({'method': method, 'params': params, 'id': identity})
            deadline = time.perf_counter() + timeout
            self.record_lifecycle('rpc_request_flushed', method=method, identity=identity)
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise queue.Empty
                message = self.receive(remaining)
                if time.perf_counter() > deadline:
                    raise queue.Empty
                if 'method' in message:
                    if 'id' in message:
                        require(message['method'] == 'item/tool/call', 'unexpected_server_request')
                        self.pending_tools.append(message)
                    continue
                require(message.get('id') == identity, 'unexpected_response_id')
                require('error' not in message, 'native_rpc_rejected')
                self.record_lifecycle('rpc_response_received', method=method, identity=identity)
                return message['result']
        except queue.Empty as error:
            self.record_lifecycle('rpc_response_timeout', method=method, identity=identity, error=error)
            raise SessionError('rpc_response_timeout') from error
        except Exception as error:
            self.record_lifecycle('rpc_request_failed', method=method, identity=identity, error=error)
            raise


def close_native_process(process, *, observe=None):
    """Use absolute5s/15s limits, including observations before each decision."""
    import subprocess
    events = []
    def sample(stage):
        row = observe(stage) if observe is not None else {
            'stage': stage, 'monotonic': time.monotonic(),
            'native_process': native_process_counters(process), 'returncode': process.poll()}
        events.append(row)
    assessed = process.poll() is None
    sample('stdin_close_started')
    started = time.perf_counter()
    process.stdin.close()
    sample('stdin_closed')
    timing = {'clock': 'perf_counter', 'primary_limit_seconds': 5, 'late_total_limit_seconds': 15,
              'observations_before_decisions_count_toward_limits': True}
    result = {'five_second_exit_assessed': assessed, 'observations': events, 'timing': timing}
    def decision(phase):
        timing[phase + '_decision_elapsed_seconds'] = round(time.perf_counter() - started, 6)
        timing[phase + '_decision_exit_code'] = process.poll()
    def wait_until(deadline, limit):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('owned_native_process', limit)
        process.wait(timeout=remaining)
        if time.perf_counter() > deadline:
            raise subprocess.TimeoutExpired('owned_native_process', limit)
    if not assessed:
        result['five_second_exit'] = None
        decision('primary')
        sample('process_already_ended')
    else:
        try:
            wait_until(started + 5, 5)
            result['five_second_exit'] = True
            decision('primary')
            sample('process_exited_within5s')
        except subprocess.TimeoutExpired:
            result['five_second_exit'] = False
            decision('primary')
            late_deadline = min(started + 15, time.perf_counter() + 10)
            timing['late_deadline_elapsed_seconds'] = round(late_deadline - started, 6)
            sample('process_wait5_timeout')
            try:
                wait_until(late_deadline, 10)
                result['diagnostic_late_exit'] = True
                decision('late')
                sample('process_exited_during_late_observation')
            except subprocess.TimeoutExpired:
                result['cleanup_incomplete'] = True
                decision('late')
                sample('process_late_wait_timeout')
    result['exit_seconds'] = round(time.perf_counter() - started, 6)
    result['exit_code'] = process.poll()
    return result


def read_native_metadata(process, workspace, inbound, outbound, diagnostic_log):
    """Only initialize/skills-list; caller owns verified CLI/config and output streams."""
    rpc = NativeRpc(process, inbound, outbound, diagnostic_log)
    result = {'pid': process.pid, 'turn_requested': False}
    try:
        identity = rpc.lifecycle[0]['native_process']
        require(identity.get('status') == 'observed_owned_handle' and identity.get('pid') == process.pid
                and type(identity.get('creation_filetime_100ns')) is int, 'native_process_identity_unverified')
        rpc.request('initialize', {'clientInfo': {'name': 'dyz_candidate_metadata_feasibility',
            'title': 'DYZ current package metadata', 'version': '0.1'},
            'capabilities': {'experimentalApi': True, 'explicitGatewayOauth': True}}, 1)
        rpc.send({'method': 'initialized', 'params': {}})
        reply = rpc.request('skills/list', {'cwds': [str(workspace)], 'forceReload': True}, 2)
        require(isinstance(reply.get('data'), list) and len(reply['data']) == 1, 'metadata_root_count')
        result.update(status='metadata_received', inventory=reply['data'][0]['skills'],
                      reported_errors=reply['data'][0].get('errors', []))
    except Exception as error:
        result.update(status='metadata_failed', error_type=type(error).__name__,
                      failure_category=str(error) if isinstance(error, SessionError) else 'metadata_protocol_error')
    finally:
        result.update(close_native_process(process, observe=rpc.record_lifecycle))
        rpc.reader.join(timeout=1)
        result['rpc_reader_finished'] = not rpc.reader.is_alive()
        result['post_close_observation'] = rpc.record_lifecycle('rpc_reader_joined')
        result['lifecycle'] = rpc.lifecycle
    return result
