"""Local transport contracts only; never connects to the official service."""
import copy
import io
import http.client
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from evals.native_host_bridge import dynamic_tools
from evals.native_host_session import NativeRelay, SessionError, native_wire_schema, relay_sse, sha, validate_native_request, visible_functions
from evals.native_host_session import NativeRpc, close_native_process, read_native_metadata, MAX_REQUEST_BODY_BYTES


class InputReviewFileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.marker=Path(self.temp.name)/'input-reviewed.json'

    def test_readable_marker_does_not_require_a_successful_stat_probe(self):
        from evals.native_host_session import await_input_review
        self.marker.write_bytes(b'{"approved":true}')
        with mock.patch.object(Path,'exists',side_effect=OSError(13,'unavailable stat probe')):
            self.assertEqual({'approved':True},await_input_review(self.marker,time.monotonic()+1,threading.Event()))

    def test_missing_marker_waits_but_io_error_is_not_changed_to_absence(self):
        from evals.native_host_session import await_input_review
        with mock.patch.object(Path,'read_bytes',side_effect=[FileNotFoundError(),b'{"approved":true}']), \
             mock.patch('evals.native_host_session.time.sleep') as pause:
            self.assertEqual({'approved':True},await_input_review(self.marker,time.monotonic()+1,threading.Event()))
            pause.assert_called_once()
        error=PermissionError(13,'private message is not approval')
        with mock.patch.object(Path,'read_bytes',side_effect=error):
            with self.assertRaises(PermissionError) as caught:await_input_review(self.marker,time.monotonic()+1,threading.Event())
        self.assertIs(error,caught.exception)

    def test_stop_and_deadline_do_not_read_or_accept_a_marker(self):
        from evals.native_host_session import await_input_review
        stopped=threading.Event();stopped.set()
        with mock.patch.object(Path,'read_bytes',side_effect=AssertionError('must not read')):
            for deadline,flag in [(time.monotonic()+1,stopped),(0,threading.Event())]:
                with self.assertRaisesRegex(SessionError,'input_review_deadline'):await_input_review(self.marker,deadline,flag)

    def test_duplicate_or_nonfinite_review_json_is_rejected(self):
        from evals.native_host_session import await_input_review
        for raw in [b'{"approved":false,"approved":true}',b'{"value":NaN}']:
            self.marker.write_bytes(raw)
            with self.assertRaises((SessionError,ValueError)):await_input_review(self.marker,time.monotonic()+1,threading.Event())

    def test_publication_is_complete_before_visibility_and_preserves_existing_marker(self):
        import os
        from evals.native_host_session import publish_input_review,await_input_review
        real_link=os.link;value={'approved':True,'nested':{'text':'合成核验'*5000}}
        def observe(source,target):
            self.assertFalse(self.marker.exists());self.assertEqual(value,json.loads(Path(source).read_bytes()))
            return real_link(source,target)
        with mock.patch('evals.native_host_session.os.link',side_effect=observe):publish_input_review(self.marker,value)
        self.assertEqual(value,await_input_review(self.marker,time.monotonic()+1,threading.Event()))
        raw=self.marker.read_bytes()
        with self.assertRaises(FileExistsError):publish_input_review(self.marker,{'approved':False})
        self.assertEqual(raw,self.marker.read_bytes());self.assertEqual([self.marker],list(self.marker.parent.iterdir()))


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.specs = dynamic_tools()
        self.tools = [{'type': 'namespace', 'name': 'functions', 'tools': [
            {'type': 'function', 'name': s['name'], 'parameters': native_wire_schema(s['inputSchema'])}
            for s in self.specs]}]
        self.request = {'model': 'gpt-6.1-sol', 'reasoning': {'effort': 'high'},
                        'store': False, 'stream': True, 'client_metadata': {'thread_id': 'own-thread'},
                        'input': [{'type': 'additional_tools', 'tools': self.tools},
                                  {'type': 'message', 'role': 'user',
                                   'content': [{'type': 'input_text', 'text': 'case-free task'}]}]}

    def validate(self, data=None, **overrides):
        kwargs = dict(specs=self.specs, prompt='case-free task', thread_id='own-thread',
                      initial=True, response_ids=set(), call_ids=set())
        kwargs.update(overrides)
        return validate_native_request(data or self.request, **kwargs)

    def test_native_additional_tools_are_not_missed(self):
        result = self.validate()
        self.assertEqual(len(result['visible_tools']), 10)
        self.assertIn('case_standard_package', result['visible_tools'])
        self.assertTrue(result['schemas_match_native_projection'])
        self.assertTrue(result['native_thread_bound'])

    def test_top_level_tools_supported(self):
        data = copy.deepcopy(self.request)
        data['tools'] = data['input'].pop(0)['tools']
        result = self.validate(data)
        self.assertEqual(len(result['visible_tools']), 10)
        self.assertIn('case_standard_package', result['visible_tools'])

    def test_native_projection_does_not_remove_argument_contract(self):
        source = copy.deepcopy(self.specs[0]['inputSchema'])
        wire = native_wire_schema(source)
        self.assertEqual(source['properties']['max_lines']['maximum'], 120)
        self.assertNotIn('maximum', wire['properties']['max_lines'])
        self.assertEqual(wire['properties']['scope']['enum'], ['package','workspace'])
        self.assertFalse(wire['additionalProperties'])
        for field in ['enum','type']:
            data = copy.deepcopy(self.request)
            data['input'][0]['tools'][0]['tools'][0]['parameters']['properties']['scope'].pop(field)
            with self.subTest(field=field):
                with self.assertRaisesRegex(SessionError, 'visible_tool_schema_mismatch'):
                    self.validate(data)

    def test_extra_builtin_rejected(self):
        data = copy.deepcopy(self.request)
        data['input'][0]['tools'][0]['tools'].append(
            {'type': 'function', 'name': 'exec_command', 'parameters': {}})
        with self.assertRaisesRegex(SessionError, 'visible_tool_set_mismatch'):
            self.validate(data)

    def test_custom_shell_and_foreign_namespace_rejected(self):
        for kind, name in [('custom', 'exec'), ('namespace', 'other')]:
            with self.subTest(kind=kind):
                with self.assertRaises(SessionError):
                    visible_functions({'tools': [{'type': kind, 'name': name}]})

    def test_duplicate_and_schema_changes_rejected(self):
        data = copy.deepcopy(self.request)
        data['tools'] = self.tools
        with self.assertRaisesRegex(SessionError, 'duplicate_or_foreign_tool'):
            self.validate(data)
        data = copy.deepcopy(self.request)
        data['input'][0]['tools'][0]['tools'][0]['parameters'] = {}
        with self.assertRaisesRegex(SessionError, 'visible_tool_schema_mismatch'):
            self.validate(data)

    def test_model_effort_storage_token_caps_checked(self):
        for key, value in [('model', 'other'), ('reasoning', {'effort': 'low'}),
                           ('store', True), ('stream', False), ('max_tokens', 100),
                           ('max_output_tokens', 100), ('conversation', 'foreign')]:
            with self.subTest(key=key):
                data = copy.deepcopy(self.request)
                data[key] = value
                with self.assertRaises(SessionError):
                    self.validate(data)

    def test_fresh_prompt_thread_and_history_checked(self):
        for key in ['prompt', 'thread', 'assistant', 'tool_history', 'previous']:
            with self.subTest(key=key):
                data = copy.deepcopy(self.request)
                if key == 'prompt':
                    data['input'][1]['content'][0]['text'] = 'different'
                elif key == 'thread':
                    data['client_metadata']['thread_id'] = 'foreign'
                elif key == 'assistant':
                    data['input'].append({'type': 'message', 'role': 'assistant'})
                elif key == 'tool_history':
                    data['input'].append({'type': 'function_call_output', 'call_id': 'foreign'})
                else:
                    data['previous_response_id'] = 'foreign'
                with self.assertRaises(SessionError):
                    self.validate(data)

    def test_only_known_continuations_and_call_ids(self):
        data = copy.deepcopy(self.request)
        data['previous_response_id'] = 'own-response'
        data['input'] = [{'type': 'function_call_output', 'call_id': 'own-call', 'output': 'ok'}]
        result = self.validate(data, initial=False, response_ids={'own-response'}, call_ids={'own-call'})
        self.assertTrue(result['tools_inherited_from_known_response'])
        with self.assertRaisesRegex(SessionError, 'unknown_tool_output'):
            self.validate(data, initial=False, response_ids={'own-response'}, call_ids=set())
        data.pop('previous_response_id')
        with self.assertRaises(SessionError):
            self.validate(data, initial=False, call_ids={'own-call'})

    def test_actual_terminal_delimiter_and_bytes_preserved(self):
        raw = b'event: response.completed\r\ndata: {"type":"response.completed","response":{"id":"r"}}\r\n\r\n'
        sink, record, events = io.BytesIO(), io.BytesIO(), []
        kind = relay_sse(io.BytesIO(raw), sink, record, completed=events.append,
                         stopped=threading.Event())
        self.assertEqual(kind, 'response.completed')
        self.assertEqual(sink.getvalue(), raw)
        self.assertEqual(record.getvalue(), raw)
        self.assertEqual(events[0]['response']['id'], 'r')

    def test_eof_or_missing_delimiter_never_fabricates_completion(self):
        for raw in [b'data: {"type":"response.created"}\n\n',
                    b'data: {"type":"response.completed"}\n']:
            with self.subTest(raw=raw):
                events, sink = [], io.BytesIO()
                with self.assertRaises(SessionError):
                    relay_sse(io.BytesIO(raw), sink, io.BytesIO(), completed=events.append,
                              stopped=threading.Event())
                self.assertEqual(events, [])
                self.assertEqual(sink.getvalue(), raw)

    def test_callback_precedes_delimiter_delivery(self):
        events = []
        class Sink(io.BytesIO):
            def write(self, raw):
                if raw == b'\n':
                    self_outer.assertTrue(events)
                return super().write(raw)
        self_outer = self
        relay_sse(io.BytesIO(b'data: {"type":"response.completed"}\n\n'), Sink(), io.BytesIO(),
                  completed=events.append, stopped=threading.Event())

    def test_stop_before_read(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaisesRegex(SessionError, 'relay_stopped'):
            relay_sse(io.BytesIO(b''), io.BytesIO(), io.BytesIO(), completed=lambda _: None, stopped=stop)

    def test_loopback_websocket_negotiates_http_without_external_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            relay = NativeRelay(Path(temporary) / 'relay', b'{}', self.specs, 'case-free task')
            connection = http.client.HTTPConnection('127.0.0.1', relay.port, timeout=3)
            try:
                connection.request('GET', '/backend-api/codex/responses', headers={'Upgrade':'websocket'})
                response = connection.getresponse()
                self.assertEqual(response.status, 426)
                self.assertEqual(response.read(), b'')
                self.assertEqual(relay.requests, [])
                self.assertEqual(len(relay.negotiations), 1)
                self.assertFalse(relay.negotiations[0]['external_forward'])
                self.assertIsNone(relay.failed)
            finally:
                connection.close()
                result = relay.close()
            self.assertTrue(result['listener_thread_finished'])

    def test_actual_function_item_bound_before_native_receives_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            relay = NativeRelay(Path(temporary) / 'relay', b'{}', self.specs, 'case-free task')
            item = {'type':'function_call','status':'completed','call_id':'own-call',
                    'name':'case_read','arguments':'{"scope":"workspace","path":"input/channel-check.txt"}'}
            event = {'type':'response.output_item.done','item':item}
            raw = b'data: ' + json.dumps(event).encode() + b'\n\n'
            self_outer = self
            class NativeSink(io.BytesIO):
                def write(self, data):
                    if b'response.output_item.done' in data:
                        self_outer.assertIn('own-call', relay.call_ids)
                    return super().write(data)
            try:
                with self.assertRaisesRegex(SessionError,'sse_eof_without_terminal'):
                    relay_sse(io.BytesIO(raw),NativeSink(),io.BytesIO(),completed=lambda _:None,
                        stopped=threading.Event(),observed=lambda e:relay.bind_actual_function_item(e['item']))
                self.assertEqual(relay.calls['own-call']['arguments']['path'],'input/channel-check.txt')
                self.assertEqual(relay.response_ids,set())
                relay.bind_actual_function_item(item)
                with self.assertRaisesRegex(SessionError,'actual_call_id_rebound'):
                    relay.bind_actual_function_item({**item,'arguments':'{"scope":"package","path":"README.md"}'})
            finally:
                relay.close()

    def test_review_scope_is_explicit_and_invalid_scope_never_binds(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'invalid'
            with self.assertRaisesRegex(SessionError,'review_authorization_scope'):
                NativeRelay(folder,b'{}',self.specs,'case-free task',review_authorization='unbounded')
            self.assertFalse(folder.exists())
            relay=NativeRelay(Path(temporary)/'default',b'{}',self.specs,'case-free task')
            try:self.assertEqual(relay.review_authorization,'existing_official_cli_casefree_scope')
            finally:relay.close()

    def test_request_guard_rejects_before_review_or_official_connection(self):
        with tempfile.TemporaryDirectory() as temporary:
            def reject(data,initial):
                self.assertTrue(initial)
                self.assertEqual(data['input'],self.request['input'])
                raise SessionError('fixture_guard_rejection')
            folder=Path(temporary)/'relay'
            relay=NativeRelay(folder,b'{}',self.specs,'case-free task',request_guard=reject)
            relay.thread_id='own-thread';relay.armed=True
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                try:
                    connection.request('POST','/backend-api/codex/responses',json.dumps(self.request),{'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,400);response.read()
                finally:connection.close();cleanup=relay.close()
                upstream.assert_not_called()
            audit=json.loads((folder/'audit-1.json').read_bytes())
            self.assertFalse(audit['forwarded']);self.assertEqual(audit['failure_category'],'fixture_guard_rejection')
            self.assertFalse((folder/'first-request-review.json').exists())
            self.assertTrue(cleanup['request_threads_finished'])

    def test_marker_io_failure_is_local_and_records_only_os_codes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'relay';relay=NativeRelay(folder,b'{}',self.specs,'case-free task')
            relay.thread_id='own-thread';relay.armed=True;raw=json.dumps(self.request).encode()
            (folder/'input-reviewed.json').write_text(json.dumps({'request_body_sha256':sha(raw),'authorization':relay.review_authorization,
                'visible_input_reviewed':True}),encoding='utf-8')
            error=OSError(13,'sensitive path or header must not be logged');error.winerror=32
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.await_input_review',side_effect=error,create=True), \
                 mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                try:
                    connection.request('POST','/backend-api/codex/responses',raw,{'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(400,response.status);response.read()
                finally:connection.close();cleanup=relay.close()
                upstream.assert_not_called()
            audit=json.loads((folder/'audit-1.json').read_bytes())
            self.assertFalse(audit['forwarded']);self.assertEqual('local_input_review_io_error',audit['failure_category'])
            self.assertEqual({'errno':13,'winerror':32},audit['os_error'])
            self.assertNotIn('sensitive path',json.dumps(audit));self.assertTrue(cleanup['request_threads_finished'])

    def test_scope_mismatch_marker_never_forwards(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'relay'
            relay=NativeRelay(folder,b'{}',self.specs,'case-free task',
                review_authorization='existing_official_cli_synthetic_skill_evaluation')
            relay.thread_id='own-thread';relay.armed=True
            raw=json.dumps(self.request).encode()
            (folder/'input-reviewed.json').write_text(json.dumps({'request_body_sha256':sha(raw),
                'authorization':'existing_official_cli_casefree_scope','visible_input_reviewed':True}))
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                try:
                    connection.request('POST','/backend-api/codex/responses',raw,{'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,400);response.read()
                finally:connection.close();relay.close()
                upstream.assert_not_called()
            self.assertEqual(relay.requests[0]['failure_category'],'input_review_not_bound')

    def test_prior_stop_cause_survives_a_rejected_followup(self):
        with tempfile.TemporaryDirectory() as temporary:
            relay=NativeRelay(Path(temporary)/'relay',b'{}',self.specs,'case-free task')
            relay.thread_id='own-thread';relay.armed=True;relay.failed='unexpected_tool_failure'
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                try:
                    connection.request('POST','/backend-api/codex/responses',json.dumps(self.request),{'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,400);response.read()
                finally:connection.close();relay.close()
                upstream.assert_not_called()
            self.assertEqual(relay.failed,'unexpected_tool_failure')
            self.assertEqual(relay.requests[0]['failure_category'],'prior_failure_stopped')
            self.assertEqual(relay.requests[0]['primary_stop_cause'],'unexpected_tool_failure')

    def test_midstream_abort_preserves_primary_tool_failure_without_fabricated_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'relay';relay=NativeRelay(folder,b'{}',self.specs,'case-free task')
            relay.thread_id='own-thread';relay.armed=True;raw=json.dumps(self.request).encode()
            (folder/'input-reviewed.json').write_text(json.dumps({'request_body_sha256':sha(raw),
                'authorization':'existing_official_cli_casefree_scope','visible_input_reviewed':True}))
            prefix=b'data: {"type":"response.created","response":{"id":"fixture-response"}}\n\n'
            class AbortedStream(io.BytesIO):
                status=200
                def getheader(self,key,default=None):return 'text/event-stream' if key=='Content-Type' else default
                def readline(self,*args):
                    value=super().readline(*args)
                    if value:return value
                    relay.failed='unexpected_tool_failure'
                    raise ConnectionAbortedError('fixture cancellation after primary tool failure')
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                upstream.return_value.sock=None;upstream.return_value.getresponse.return_value=AbortedStream(prefix)
                try:
                    connection.request('POST','/backend-api/codex/responses',raw,{'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.read(),prefix)
                finally:connection.close();relay.close()
            audit=json.loads((folder/'audit-1.json').read_bytes())
            self.assertEqual(audit['failure_category'],'transport_or_parse_error')
            self.assertEqual(audit['primary_stop_cause'],'unexpected_tool_failure')
            self.assertEqual(relay.failed,'unexpected_tool_failure')
            self.assertNotIn('actual_terminal_delimiter',audit)
            self.assertEqual((folder/'response-1.sse').read_bytes(),prefix)

    def test_real_delimited_stream_registers_actual_history_and_guard_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'relay'
            guard=mock.Mock(return_value={'verified_call_ids':[],'fixture':True})
            relay=NativeRelay(folder,b'{}',self.specs,'case-free task',request_guard=guard,
                review_authorization='existing_official_cli_synthetic_skill_evaluation')
            relay.thread_id='own-thread';relay.armed=True
            raw=json.dumps(self.request).encode()
            (folder/'input-reviewed.json').write_text(json.dumps({'request_body_sha256':sha(raw),
                'authorization':'existing_official_cli_synthetic_skill_evaluation','visible_input_reviewed':True}))
            item={'id':'function-item','type':'function_call','status':'completed','call_id':'actual-call',
                  'name':'case_read','arguments':'{"scope":"workspace","path":"input/channel-check.txt"}'}
            final={'id':'actual-final','type':'message','role':'assistant',
                   'content':[{'type':'output_text','text':'actual final','annotations':[]}]}
            events=[{'type':'response.output_item.done','item':item},
                    {'type':'response.completed','response':{'id':'actual-response','output':[item,final]}}]
            stream=b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events)
            class Response(io.BytesIO):
                status=200
                def getheader(self,key,default=None):return 'text/event-stream' if key=='Content-Type' else default
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                upstream.return_value.sock=None
                upstream.return_value.getresponse.return_value=Response(stream)
                try:
                    connection.request('POST','/backend-api/codex/responses',raw,{'Content-Type':'application/json'})
                    response=connection.getresponse();self.assertEqual(response.status,200);self.assertEqual(response.read(),stream)
                finally:connection.close();relay.close()
                self.assertEqual(upstream.call_args.args,('chatgpt.com',))
                forwarded=upstream.return_value.request.call_args
                self.assertEqual(forwarded.args,('POST','/backend-api/codex/responses'))
                self.assertEqual(forwarded.kwargs['body'],raw)
            guard.assert_called_once_with(self.request,True)
            self.assertEqual(relay.output_items,{'function-item':item,'actual-final':final})
            self.assertEqual(relay.call_ids,{'actual-call'})
            self.assertEqual(relay.response_ids,{'actual-response'})
            self.assertEqual(relay.requests[0]['runner_guard'],{'verified_call_ids':[],'fixture':True})
            self.assertEqual(relay.requests[0]['outcome'],'completed_with_genuine_delimiter')


class RequestBodyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.specs=dynamic_tools()
        self.request={'model':'gpt-6.1-sol','reasoning':{'effort':'high'},'store':False,'stream':True,
            'tools':[{'type':'function','name':s['name'],'parameters':native_wire_schema(s['inputSchema'])} for s in self.specs],
            'client_metadata':{'thread_id':'own-thread'},
            'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':'case-free task'}]}]}

    def replay_success(self, size, *, content_length=None, **limits):
        base=json.dumps(self.request,ensure_ascii=False).encode('utf-8')
        raw=base+b' '*(size-len(base))
        self.assertEqual(len(raw),size)
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'relay'
            guard=mock.Mock(return_value={'fixture_full_input_checked':True})
            relay=NativeRelay(folder,b'{}',self.specs,'case-free task',request_guard=guard,**limits)
            relay.thread_id,relay.armed='own-thread',True
            (folder/'input-reviewed.json').write_text(json.dumps({'request_body_sha256':sha(raw),
                'authorization':relay.review_authorization,'visible_input_reviewed':True}))
            stream=b'data: {"type":"response.completed","response":{"id":"fixture-response","output":[]}}\n\n'
            class Response(io.BytesIO):
                status=200
                def getheader(self,key,default=None):return 'text/event-stream' if key=='Content-Type' else default
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=5)
            context=object()
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream, \
                    mock.patch('evals.native_host_session.ssl.create_default_context',return_value=context) as tls_context:
                upstream.return_value.sock=None;upstream.return_value.getresponse.return_value=Response(stream)
                failure=None
                try:
                    headers={'Content-Type':'application/json','Authorization':'AUTH-DO-NOT-LOG'}
                    if content_length is not None:headers['Content-Length']=content_length
                    connection.request('POST','/backend-api/codex/responses',raw,headers)
                    response=connection.getresponse();self.assertEqual(response.status,200)
                    self.assertEqual(response.read(),stream)
                except Exception as error:
                    failure=error
                    raise
                finally:
                    connection.close();cleanup=relay.close()
                    if failure is not None:
                        failure.add_note(json.dumps({'fixture_relay_audits':relay.requests,
                            'fixture_cleanup':cleanup,'mocked_upstream_calls':upstream.call_count}))
                self.assertEqual(upstream.return_value.request.call_args.kwargs['body'],raw)
                tls_context.assert_called_once_with()
                upstream.assert_called_once_with('chatgpt.com',timeout=600,context=context)
            guard.assert_called_once_with(self.request,True)
            self.assertEqual((folder/'request-1.json').read_bytes(),raw)
            audit=json.loads((folder/'audit-1.json').read_bytes())
            self.assertEqual(audit['declared_request_body_bytes'],size)
            self.assertEqual(audit['received_request_body_bytes'],size)
            self.assertEqual(audit['received_request_body_sha256'],sha(raw))
            self.assertEqual(audit['forwarded_body_sha256'],sha(raw))
            self.assertNotIn('AUTH-DO-NOT-LOG',json.dumps(audit))
            self.assertTrue(cleanup['request_threads_finished'])

    def test_exact_legacy_limit_and_new_full_history_limit_preserve_all_bytes(self):
        self.replay_success(2_000_000)
        self.replay_success(2_000_001,max_request_body_bytes=MAX_REQUEST_BODY_BYTES)
        self.request['input'][0]['content'][0]['text']+=' 中文条件与未知保持。'
        self.replay_success(MAX_REQUEST_BODY_BYTES,max_request_body_bytes=MAX_REQUEST_BODY_BYTES)

    def test_legal_outer_whitespace_and_leading_zero_length_preserve_body(self):
        self.replay_success(50000,content_length=' 00050000 \t')

    def test_invalid_budget_is_rejected_before_directory_or_listener(self):
        with tempfile.TemporaryDirectory() as temporary:
            for value in [True,0,MAX_REQUEST_BODY_BYTES+1,float('inf')]:
                folder=Path(temporary)/str(value)
                with self.subTest(value=value),self.assertRaisesRegex(SessionError,'request_body_budget'):
                    NativeRelay(folder,b'{}',self.specs,'case-free task',max_request_body_bytes=value)
                self.assertFalse(folder.exists())
            for value in [False,0,31,float('nan')]:
                with self.subTest(timeout=value),self.assertRaisesRegex(SessionError,'request_body_timeout_budget'):
                    NativeRelay(Path(temporary)/'timeout',b'{}',self.specs,'case-free task',body_read_timeout_seconds=value)

    def test_declared_oversize_is_recorded_without_reading_or_forwarding(self):
        for limit in [2_000_000,MAX_REQUEST_BODY_BYTES]:
            with self.subTest(limit=limit),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)/'relay';relay=NativeRelay(folder,b'{}',self.specs,'case-free task',max_request_body_bytes=limit)
                relay.thread_id,relay.armed='own-thread',True
                connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
                with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                    try:
                        connection.putrequest('POST','/backend-api/codex/responses')
                        connection.putheader('Content-Length',str(limit+1));connection.endheaders()
                        response=connection.getresponse();self.assertEqual(response.status,400);response.read()
                    finally:connection.close();relay.close()
                    upstream.assert_not_called()
                audit=json.loads((folder/'audit-1.json').read_bytes())
                self.assertEqual(audit['declared_request_body_bytes'],limit+1)
                self.assertEqual(audit['failure_category'],'request_size')
                self.assertNotIn('received_request_body_bytes',audit)
                self.assertFalse((folder/'request-1.json').exists())

    def test_ambiguous_or_malformed_length_and_transfer_encoding_never_forward(self):
        variants=[([], 'request_length_invalid'),([('Content-Length','secret-length')],'request_length_invalid'),
            ([('Content-Length','1'),('Content-Length','1')],'request_length_invalid'),
            ([('Content-Length','1'),('Transfer-Encoding','chunked')],'request_transfer_encoding_unsupported')]
        for headers,category in variants:
            with self.subTest(headers=headers),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)/'relay';relay=NativeRelay(folder,b'{}',self.specs,'case-free task')
                relay.thread_id,relay.armed='own-thread',True
                connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
                with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                    try:
                        connection.putrequest('POST','/backend-api/codex/responses')
                        for key,value in headers:connection.putheader(key,value)
                        connection.endheaders();response=connection.getresponse()
                        self.assertEqual(response.status,400);response.read()
                    finally:connection.close();relay.close()
                    upstream.assert_not_called()
                audit=json.loads((folder/'audit-1.json').read_bytes())
                self.assertEqual(audit['failure_category'],category)
                self.assertNotIn('secret-length',json.dumps(audit))

    def test_incomplete_body_and_body_timeout_are_distinct_from_size_rejection(self):
        for end_write in [True,False]:
            with self.subTest(end_write=end_write),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)/'relay';relay=NativeRelay(folder,b'{}',self.specs,'case-free task',body_read_timeout_seconds=0.05)
                relay.thread_id,relay.armed='own-thread',True
                connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
                with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                    try:
                        connection.putrequest('POST','/backend-api/codex/responses');connection.putheader('Content-Length','10')
                        connection.endheaders()
                        if end_write:connection.send(b'{');connection.sock.shutdown(socket.SHUT_WR)
                        response=connection.getresponse();self.assertEqual(response.status,400);response.read()
                    finally:connection.close();cleanup=relay.close()
                    upstream.assert_not_called()
                audit=json.loads((folder/'audit-1.json').read_bytes())
                self.assertEqual(audit['failure_category'],'request_incomplete' if end_write else 'request_body_timeout')
                self.assertEqual(audit['declared_request_body_bytes'],10)
                self.assertTrue(cleanup['request_threads_finished'])
                if end_write:self.assertEqual(audit['received_request_body_bytes'],1)
                else:
                    self.assertEqual(audit['received_request_body_bytes'],0)
                    self.assertEqual(audit['received_request_body_sha256'],sha(b''))

    def test_shutdown_unblocks_an_owned_incoming_body_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)/'relay';relay=NativeRelay(folder,b'{}',self.specs,'case-free task')
            relay.thread_id,relay.armed='own-thread',True
            connection=http.client.HTTPConnection('127.0.0.1',relay.port,timeout=3)
            with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                try:
                    connection.putrequest('POST','/backend-api/codex/responses');connection.putheader('Content-Length','10')
                    connection.endheaders()
                    deadline=time.monotonic()+3
                    while not (relay.requests and relay.requests[0].get('body_read_started_monotonic')) and time.monotonic()<deadline:
                        time.sleep(0.005)
                    self.assertTrue(relay.requests and relay.requests[0].get('body_read_started_monotonic'))
                finally:cleanup=relay.close();connection.close()
                upstream.assert_not_called()
            self.assertTrue(cleanup['request_threads_finished'])
            audit=json.loads((folder/'audit-1.json').read_bytes())
            self.assertEqual(audit['failure_category'],'relay_stopped_during_body_read')
            self.assertEqual(audit['failure_context'],'observed_during_requested_relay_shutdown')


class NativeLifecycleTests(unittest.TestCase):
    def counters(self, process):
        return {'status':'observed_owned_handle','pid':process.pid,'creation_filetime_100ns':123,
                'kernel_cpu_100ns':0,'user_cpu_100ns':1,'handle_count':10}

    def test_rpc_timeout_records_flushed_request_and_empty_reader_without_secrets_or_retry(self):
        release=threading.Event()
        class WaitingOutput:
            def read1(self,limit):release.wait(3);return b''
        process=SimpleNamespace(pid=42,stdin=io.BytesIO(),stdout=WaitingOutput(),poll=lambda:None)
        lifecycle=io.BytesIO()
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):
            rpc=NativeRpc(process,io.BytesIO(),diagnostic_log=lifecycle)
            try:
                with self.assertRaisesRegex(SessionError,'rpc_response_timeout'):
                    rpc.request('initialize',{'private':'SECRET-PARAMS'},1,timeout=0.02)
                stages=[row['stage'] for row in rpc.lifecycle]
                self.assertEqual(stages,['rpc_created','rpc_request_started','rpc_request_flushed','rpc_response_timeout'])
                self.assertEqual(len(process.stdin.getvalue().splitlines()),1)
                self.assertEqual(rpc.lifecycle[-1]['reader_progress']['stdout_bytes_read'],0)
                self.assertNotIn(b'SECRET-PARAMS',lifecycle.getvalue())
                self.assertTrue(all(row['native_process']['creation_filetime_100ns']==123 for row in rpc.lifecycle))
            finally:release.set();rpc.reader.join(timeout=1)

    def test_partial_stdout_is_observed_before_an_initialization_timeout(self):
        release=threading.Event();partial=b'{"id":1,"result":'
        class PartialOutput:
            sent=False
            def read1(self,limit):
                if not self.sent:self.sent=True;return partial
                release.wait(3);return b''
        inbound=io.BytesIO();process=SimpleNamespace(pid=42,stdin=io.BytesIO(),stdout=PartialOutput(),poll=lambda:None)
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):
            rpc=NativeRpc(process,inbound,diagnostic_log=io.BytesIO())
            try:
                deadline=time.monotonic()+1
                while rpc.reader_progress['pending_frame_bytes']!=len(partial) and time.monotonic()<deadline:time.sleep(0.001)
                with self.assertRaisesRegex(SessionError,'rpc_response_timeout'):
                    rpc.request('initialize',{},1,timeout=0.02)
                self.assertEqual(inbound.getvalue(),partial)
                self.assertEqual(rpc.lifecycle[-1]['reader_progress']['stdout_bytes_read'],len(partial))
                self.assertEqual(rpc.lifecycle[-1]['reader_progress']['pending_frame_bytes'],len(partial))
                self.assertEqual(rpc.lifecycle[-1]['reader_progress']['frames_queued'],0)
            finally:release.set();rpc.reader.join(timeout=1)

    def test_eof_without_rpc_line_delimiter_never_becomes_a_response(self):
        raw=b'{"id":1,"result":{}}'
        process=SimpleNamespace(pid=42,stdin=io.BytesIO(),stdout=io.BytesIO(raw),poll=lambda:None)
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):
            rpc=NativeRpc(process,io.BytesIO(),diagnostic_log=io.BytesIO())
            with self.assertRaisesRegex(SessionError,'rpc_reader_error'):rpc.request('initialize',{},1)
            rpc.reader.join(timeout=1)
        self.assertEqual(rpc.frames,[])
        self.assertEqual(rpc.reader_progress['error_code'],'rpc_incomplete_frame')
        self.assertEqual(rpc.reader_progress['stdout_bytes_read'],len(raw))

    def test_late_exit_does_not_replace_original_five_second_failure(self):
        process=SimpleNamespace(pid=42,stdin=mock.Mock(),returncode=None)
        process.poll=lambda:process.returncode
        def wait(*,timeout):
            if process.wait.call_count==1:raise subprocess.TimeoutExpired('owned fixture',5)
            process.returncode=0;return 0
        process.wait=mock.Mock(side_effect=wait)
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):
            result=close_native_process(process)
        self.assertFalse(result['five_second_exit'])
        self.assertTrue(result['diagnostic_late_exit'])
        self.assertEqual(len(process.wait.call_args_list),2)
        for call,limit in zip(process.wait.call_args_list,[5,10]):
            self.assertGreater(call.kwargs['timeout'],0)
            self.assertLessEqual(call.kwargs['timeout'],limit)
        self.assertEqual(result['exit_code'],0)
        self.assertEqual([r['stage'] for r in result['observations']],
            ['stdin_close_started','stdin_closed','process_wait5_timeout','process_exited_during_late_observation'])
        process.stdin.close.assert_called_once()

    def test_still_live_close_is_recorded_incomplete_without_termination(self):
        process=SimpleNamespace(pid=42,stdin=mock.Mock(),poll=lambda:None,
            wait=mock.Mock(side_effect=subprocess.TimeoutExpired('owned fixture',5)))
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):result=close_native_process(process)
        self.assertTrue(result['cleanup_incomplete']);self.assertFalse(result['five_second_exit'])
        self.assertIsNone(result['exit_code'])
        self.assertEqual(result['observations'][-1]['stage'],'process_late_wait_timeout')

    def test_metadata_consumer_uses_only_initialize_and_list_then_closes(self):
        class RetainedInput(io.BytesIO):
            def close(self):self.closed_by_consumer=True
        replies=[{'id':1,'result':{}},{'id':2,'result':{'data':[{'skills':[],'errors':[]}]}}]
        process=SimpleNamespace(pid=42,stdin=RetainedInput(),stdout=io.BytesIO(
            b''.join(json.dumps(row).encode()+b'\n' for row in replies)),returncode=None)
        process.poll=lambda:process.returncode
        def wait(*,timeout):process.returncode=0;return 0
        process.wait=wait
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):
            result=read_native_metadata(process,'owned-workspace',io.BytesIO(),io.BytesIO(),io.BytesIO())
        self.assertEqual(result['status'],'metadata_received');self.assertEqual(result['inventory'],[])
        self.assertFalse(result['turn_requested']);self.assertTrue(result['five_second_exit'])
        self.assertEqual([json.loads(line)['method'] for line in process.stdin.getvalue().splitlines()],
            ['initialize','initialized','skills/list'])
        self.assertTrue(process.stdin.closed_by_consumer)

    def test_metadata_initialization_failure_never_lists_or_starts_a_turn(self):
        class RetainedInput(io.BytesIO):
            def close(self):self.closed_by_consumer=True
        process=SimpleNamespace(pid=42,stdin=RetainedInput(),stdout=io.BytesIO(),returncode=None)
        process.poll=lambda:process.returncode
        def wait(*,timeout):process.returncode=0;return 0
        process.wait=wait
        with mock.patch('evals.native_host_session.native_process_counters',side_effect=self.counters):
            result=read_native_metadata(process,'owned-workspace',io.BytesIO(),io.BytesIO(),io.BytesIO())
        self.assertEqual(result['status'],'metadata_failed')
        self.assertEqual(result['failure_category'],'rpc_eof')
        self.assertNotIn('inventory',result)
        self.assertEqual([json.loads(line)['method'] for line in process.stdin.getvalue().splitlines()],['initialize'])
        self.assertTrue(process.stdin.closed_by_consumer)

    def test_exit_during_reader_join_is_separate_from_primary_close_timeout(self):
        import subprocess
        process=SimpleNamespace(pid=42,returncode=None,stdin=SimpleNamespace(close=lambda:None))
        process.poll=lambda:process.returncode
        process.wait=mock.Mock(side_effect=subprocess.TimeoutExpired('synthetic-owned-process',5))
        rpc=SimpleNamespace(lifecycle=[{'native_process':self.counters(process)}])
        def fail_request(*args,**kwargs):raise SessionError('rpc_response_timeout')
        rpc.request=fail_request
        def join(*,timeout):process.returncode=0
        rpc.reader=SimpleNamespace(join=join,is_alive=lambda:False)
        def observe(stage,**kwargs):
            row={'stage':stage,'returncode':process.poll(),'native_process':self.counters(process)}
            rpc.lifecycle.append(row)
            return row
        rpc.record_lifecycle=observe
        with mock.patch('evals.native_host_session.NativeRpc',return_value=rpc):
            result=read_native_metadata(process,'owned-workspace',io.BytesIO(),io.BytesIO(),io.BytesIO())
        self.assertEqual(result['status'],'metadata_failed')
        self.assertEqual(result['failure_category'],'rpc_response_timeout')
        self.assertFalse(result['five_second_exit'])
        self.assertTrue(result['cleanup_incomplete'])
        self.assertIsNone(result['exit_code'])
        self.assertEqual(result['post_close_observation']['returncode'],0)
        self.assertEqual(result['post_close_observation']['native_process']['creation_filetime_100ns'],123)
        self.assertTrue(result['rpc_reader_finished'])
        self.assertEqual(len(process.wait.call_args_list),2)
        for call,limit in zip(process.wait.call_args_list,[5,10]):
            self.assertGreater(call.kwargs['timeout'],0)
            self.assertLessEqual(call.kwargs['timeout'],limit)


class DeadlineAccountingTests(unittest.TestCase):
    class Clock:
        now=0.0
        def __call__(self):return self.now

    def process(self,clock,exit_at):
        import subprocess
        p=SimpleNamespace(pid=42,stdin=SimpleNamespace(close=lambda:None),wait_calls=[])
        p.poll=lambda:0 if clock.now>=exit_at else None
        def wait(*,timeout):
            p.wait_calls.append(timeout)
            if clock.now+timeout<exit_at:
                clock.now+=timeout
                raise subprocess.TimeoutExpired('owned timing fixture',timeout)
            clock.now=max(clock.now,exit_at)
            return 0
        p.wait=wait
        return p

    def observer(self,clock,p,delays):
        def observe(stage):
            clock.now+=delays.get(stage,0)
            return {'stage':stage,'monotonic':clock.now,'returncode':p.poll(),
                'native_process':{'status':'observed_owned_handle','pid':42,'creation_filetime_100ns':123}}
        return observe

    def rpc(self,clock,reply_at,*,flushed_observation=0,honor_wait=True):
        import queue
        r=SimpleNamespace(pending_tools=[],stages=[])
        r.send=lambda message:None
        def observe(stage,**kwargs):
            r.stages.append(stage)
            if stage=='rpc_request_flushed':clock.now+=flushed_observation
        r.record_lifecycle=observe
        def receive(timeout):
            if honor_wait and clock.now+timeout<reply_at:
                clock.now+=timeout
                raise queue.Empty
            clock.now=max(clock.now,reply_at)
            return {'id':1,'result':{'ok':True}}
        r.receive=receive
        return r

    def test_primary_exit_deadline_includes_slow_stdin_closed_observation(self):
        clock=self.Clock();p=self.process(clock,8)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            result=close_native_process(p,observe=self.observer(clock,p,{'stdin_closed':6}))
        self.assertFalse(result['five_second_exit'])
        self.assertTrue(result['diagnostic_late_exit'])

    def test_late_exit_window_does_not_restart_after_observation_delays(self):
        clock=self.Clock();p=self.process(clock,17)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            result=close_native_process(p,observe=self.observer(clock,p,{'stdin_closed':4,'process_wait5_timeout':4}))
        self.assertTrue(result.get('cleanup_incomplete'))
        self.assertFalse(result.get('diagnostic_late_exit',False))
        self.assertLessEqual(clock.now,15)

    def test_rpc_deadline_includes_post_flush_observation(self):
        clock=self.Clock();rpc=self.rpc(clock,8,flushed_observation=6)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            with self.assertRaisesRegex(SessionError,'rpc_response_timeout'):
                NativeRpc.request(rpc,'initialize',{},1,timeout=5)
        self.assertIn('rpc_response_timeout',rpc.stages)

    def test_rpc_reply_observed_after_deadline_is_not_accepted(self):
        clock=self.Clock();rpc=self.rpc(clock,6,honor_wait=False)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            with self.assertRaisesRegex(SessionError,'rpc_response_timeout'):
                NativeRpc.request(rpc,'initialize',{},1,timeout=5)

    def test_valid_reply_and_exit_within_absolute_budgets_still_pass(self):
        clock=self.Clock();p=self.process(clock,3)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            result=close_native_process(p,observe=self.observer(clock,p,{'stdin_closed':0.5}))
        self.assertTrue(result['five_second_exit'])
        clock=self.Clock();rpc=self.rpc(clock,1.5,flushed_observation=0.5)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            self.assertEqual(NativeRpc.request(rpc,'initialize',{},1,timeout=5),{'ok':True})

    def test_diagnostics_after_timely_exit_keep_the_timely_decision(self):
        clock=self.Clock();p=self.process(clock,3)
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            result=close_native_process(p,observe=self.observer(clock,p,{'process_exited_within5s':6}))
        self.assertTrue(result['five_second_exit'])
        self.assertEqual(result['exit_code'],0)


class BodyReadDeadlineTests(unittest.TestCase):
    def read(self,delay):
        from evals.native_host_session import read_request_body
        clock=DeadlineAccountingTests.Clock()
        connection=SimpleNamespace(gettimeout=lambda:0.7,setblocking=mock.Mock(),settimeout=mock.Mock(),recv=mock.Mock())
        def read1(limit):
            clock.now+=delay
            return b'{}'
        audit={}
        with mock.patch('evals.native_host_session.time.monotonic',clock),mock.patch('evals.native_host_session.time.perf_counter',clock):
            try:
                return read_request_body(connection,SimpleNamespace(read1=read1),2,timeout=1,
                    stopped=threading.Event(),audit=audit),audit
            finally:
                connection.setblocking.assert_called_once_with(False)
                connection.settimeout.assert_called_once_with(0.7)
                connection.recv.assert_not_called()

    def test_final_chunk_after_total_deadline_is_not_accepted(self):
        with self.assertRaisesRegex(SessionError,'request_body_timeout'):
            self.read(2)

    def test_complete_buffered_body_before_or_at_deadline_preserves_bytes(self):
        for delay in [0.5,1]:
            with self.subTest(delay=delay):
                raw,audit=self.read(delay)
                self.assertEqual(raw,b'{}')
                self.assertEqual(audit['received_request_body_bytes'],2)
                self.assertEqual(audit['received_request_body_sha256'],sha(b'{}'))


class NativeStreamProgressTests(unittest.TestCase):
    def test_progress_preserves_wire_and_reports_only_metadata(self):
        raw = (b'data: {"type":"response.created","private":"AUTH-EXAMPLE-SECRET"}\n\n'
               b'data: {"type":"response.completed","response":{"id":"synthetic"}}\n\n')
        sink, record, reports, completed = io.BytesIO(), io.BytesIO(), [], []
        ticks = iter(range(8))
        kind = relay_sse(io.BytesIO(raw), sink, record, completed=completed.append,
            stopped=threading.Event(), progress=reports.append, clock=lambda: next(ticks))
        self.assertEqual(kind, 'response.completed')
        self.assertEqual(sink.getvalue(), raw)
        self.assertEqual(record.getvalue(), raw)
        self.assertEqual([r['kind'] for r in reports], ['created', 'non_json', 'terminal', 'terminal_separator'])
        self.assertEqual(sum(r['bytes_read'] for r in reports), len(raw))
        self.assertTrue(all(r['read_finished_monotonic'] - r['read_started_monotonic'] == 1 for r in reports))
        self.assertNotIn('AUTH-EXAMPLE-SECRET', json.dumps(reports))
        self.assertEqual(len(completed), 1)

    def test_eof_report_does_not_create_completion_or_bytes(self):
        raw = b'data: {"type":"response.created"}\n\n'
        reports, completed = [], []
        with self.assertRaisesRegex(SessionError, 'sse_eof_without_terminal'):
            relay_sse(io.BytesIO(raw), io.BytesIO(), io.BytesIO(), completed=completed.append,
                stopped=threading.Event(), progress=reports.append)
        self.assertEqual(reports[-1]['kind'], 'eof')
        self.assertEqual(reports[-1]['bytes_read'], 0)
        self.assertEqual(sum(r['bytes_read'] for r in reports), len(raw))
        self.assertEqual(completed, [])

    def test_unknown_event_type_cannot_copy_remote_text_into_progress(self):
        reports = []
        raw = b'data: {"type":"AUTH-EXAMPLE-SECRET","text":"private"}\n\n'
        with self.assertRaises(SessionError):
            relay_sse(io.BytesIO(raw), io.BytesIO(), io.BytesIO(), completed=lambda _: None,
                stopped=threading.Event(), progress=reports.append)
        self.assertEqual(reports[0]['kind'], 'other_json')
        self.assertNotIn('AUTH-EXAMPLE-SECRET', json.dumps(reports))
        self.assertNotIn('private', json.dumps(reports))

    def test_actual_loopback_progress_audit_binds_completion_and_eof_bytes(self):
        specs = dynamic_tools()
        request = {'model': 'gpt-6.1-sol', 'reasoning': {'effort': 'high'}, 'store': False, 'stream': True,
            'tools': [{'type': 'function', 'name': s['name'], 'parameters': native_wire_schema(s['inputSchema'])} for s in specs],
            'client_metadata': {'thread_id': 'own-thread'},
            'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'case-free task'}]}]}
        body = json.dumps(request).encode()
        created = b'data: {"type":"response.created"}\n\n'
        terminal = b'data: {"type":"response.completed","response":{"id":"synthetic","output":[],"usage":null}}\n\n'
        for complete in [True, False]:
            stream = created + terminal if complete else created
            with self.subTest(complete=complete), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary) / 'relay'
                relay = NativeRelay(folder, b'{}', specs, 'case-free task')
                relay.thread_id, relay.armed = 'own-thread', True
                (folder / 'input-reviewed.json').write_text(json.dumps({'request_body_sha256': sha(body),
                    'authorization': 'existing_official_cli_casefree_scope', 'visible_input_reviewed': True}), encoding='utf-8')
                class Response(io.BytesIO):
                    status = 200
                    def getheader(self, key, default=None):
                        return 'text/event-stream' if key == 'Content-Type' else default
                client = http.client.HTTPConnection('127.0.0.1', relay.port, timeout=3)
                with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                    upstream.return_value.sock = None
                    upstream.return_value.getresponse.return_value = Response(stream)
                    try:
                        client.request('POST', '/backend-api/codex/responses', body, {'Content-Type': 'application/json'})
                        self.assertEqual(client.getresponse().read(), stream)
                    finally:
                        client.close()
                        cleanup = relay.close()
                audit = json.loads((folder / 'audit-1.json').read_bytes())
                progress = audit['stream_progress']
                self.assertEqual(progress['bytes_read'], len(stream))
                self.assertEqual(progress['empty_reads'], 0 if complete else 1)
                self.assertLessEqual(progress['first_byte_monotonic'], progress['last_byte_monotonic'])
                self.assertLessEqual(progress['last_byte_monotonic'], progress['last_read_finished_monotonic'])
                self.assertTrue(cleanup['request_threads_finished'])
                if complete:
                    self.assertEqual(progress['kind_counts']['terminal_separator'], 1)
                    self.assertEqual(audit['outcome'], 'completed_with_genuine_delimiter')
                else:
                    self.assertEqual(audit['failure_category'], 'sse_eof_without_terminal')
                    self.assertNotIn('actual_terminal_delimiter', audit)


class RelayShutdownReadTests(unittest.TestCase):
    def test_real_loopback_audit_distinguishes_active_failure_from_requested_stop(self):
        specs = dynamic_tools()
        tools = [{'type': 'function', 'name': s['name'], 'parameters': native_wire_schema(s['inputSchema'])} for s in specs]
        request = {'model': 'gpt-6.1-sol', 'reasoning': {'effort': 'high'}, 'store': False, 'stream': True,
                   'tools': tools, 'client_metadata': {'thread_id': 'own-thread'},
                   'input': [{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'case-free task'}]}]}
        raw = json.dumps(request).encode()
        for requested_stop in [False, True]:
            with self.subTest(requested_stop=requested_stop), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary) / 'relay'
                relay = NativeRelay(folder, b'{}', specs, 'case-free task')
                relay.thread_id, relay.armed = 'own-thread', True
                (folder / 'input-reviewed.json').write_text(json.dumps({'request_body_sha256': sha(raw),
                    'authorization': 'existing_official_cli_casefree_scope', 'visible_input_reviewed': True}), encoding='utf-8')
                class Response:
                    status = 200
                    def getheader(self, key, default=None):
                        return 'text/event-stream' if key == 'Content-Type' else default
                    def readline(self):
                        if requested_stop:
                            relay.stopped.set()
                        raise AttributeError('AUTH-EXAMPLE-SECRET')
                connection = http.client.HTTPConnection('127.0.0.1', relay.port, timeout=3)
                with mock.patch('evals.native_host_session.http.client.HTTPSConnection') as upstream:
                    upstream.return_value.sock = None
                    upstream.return_value.getresponse.return_value = Response()
                    try:
                        connection.request('POST', '/backend-api/codex/responses', raw, {'Content-Type': 'application/json'})
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.read(), b'')
                    finally:
                        connection.close()
                        cleanup = relay.close()
                    self.assertEqual(upstream.call_count, 1)
                audit = json.loads((folder / 'audit-1.json').read_bytes())
                self.assertEqual(audit['failure_context'], 'observed_during_requested_relay_shutdown' if requested_stop else 'active_request_failure')
                self.assertEqual(audit['failure_category'], 'relay_stopped_during_read' if requested_stop else 'transport_or_parse_error')
                self.assertTrue(audit['failure_sites'])
                self.assertNotIn('AUTH-EXAMPLE-SECRET', json.dumps(audit))
                self.assertTrue(cleanup['request_threads_finished'])
                self.assertNotIn('actual_terminal_delimiter', audit)

    def test_shutdown_during_body_read_is_not_a_new_transport_failure(self):
        stop, completed, record = threading.Event(), [], io.BytesIO()
        class Response:
            def readline(self):
                stop.set()
                raise AttributeError('private exception detail must not enter an audit')
        with self.assertRaisesRegex(SessionError, 'relay_stopped_during_read') as caught:
            relay_sse(Response(), io.BytesIO(), record, completed=completed.append, stopped=stop)
        self.assertIsInstance(caught.exception.__cause__, AttributeError)
        self.assertEqual(completed, [])
        self.assertEqual(record.getvalue(), b'')

    def test_shutdown_during_terminal_separator_never_fabricates_completion(self):
        stop, completed = threading.Event(), []
        raw = b'data: {"type":"response.completed","response":{"id":"own"}}\n'
        class Response:
            calls = 0
            def readline(self):
                self.calls += 1
                if self.calls == 1:
                    return raw
                stop.set()
                raise ValueError('read of closed file')
        sink, record = io.BytesIO(), io.BytesIO()
        with self.assertRaisesRegex(SessionError, 'relay_stopped_during_read'):
            relay_sse(Response(), sink, record, completed=completed.append, stopped=stop)
        self.assertEqual(completed, [])
        self.assertEqual(sink.getvalue(), raw)
        self.assertEqual(record.getvalue(), raw)

    def test_active_reader_error_preserved_with_safe_code_site(self):
        from evals import native_host_session
        class Response:
            def readline(self):
                raise AttributeError('AUTH-EXAMPLE-SECRET')
        try:
            relay_sse(Response(), io.BytesIO(), io.BytesIO(), completed=lambda _: None, stopped=threading.Event())
        except AttributeError as error:
            sites = native_host_session.exception_sites(error)
        else:
            self.fail('active AttributeError was suppressed')
        self.assertTrue(sites)
        self.assertEqual(sites[-1]['function'], 'readline')
        self.assertNotIn('AUTH-EXAMPLE-SECRET', json.dumps(sites))
        self.assertTrue(all(set(row) == {'file', 'function', 'line'} and Path(row['file']).name == row['file'] for row in sites))


if __name__ == '__main__':
    unittest.main()
