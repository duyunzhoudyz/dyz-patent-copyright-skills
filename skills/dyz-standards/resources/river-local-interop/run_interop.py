"""Bounded same-author local-process River exercise; standard library only.

No sockets, service, original model import, durable state or online ACK format.
Hex/JSON stdin/stdout is only test machinery. Results are finite development
observations, not independent product/vendor or professional acceptance.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import threading
import time


class PeerError(RuntimeError):
    pass


class Peer:
    """Own a newly started child only; never attach to or stop another task."""
    def __init__(self, program, version, events, bounds):
        self.events, self.bounds = events, bounds
        self.last_observation = None
        self.lines = queue.Queue()
        self.stderr = bytearray()
        self.closed = False
        self.name = Path(program).stem
        program = Path(program).resolve(strict=True)
        program_hash = hashlib.sha256(program.read_bytes()).hexdigest()
        env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'TEMP', 'TMP') if key in os.environ}
        self.process = subprocess.Popen([sys.executable, '-E', '-s', '-S', str(Path(program).resolve()), '--version', version],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=Path(program).resolve().parent, env=env,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.event = {'peer_file': Path(program).name, 'version': version, 'pid': self.process.pid,
                      'source_sha256': program_hash,
                      'started_at_monotonic': time.monotonic(), 'closed': False}
        events.append(self.event)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.error_reader = threading.Thread(target=self._read_error, daemon=True)
        self.reader.start()
        self.error_reader.start()
        try:
            hello = self._response(bounds['ready_seconds'])
            if hello.get('ready') is not True or hello.get('version') != version:
                raise PeerError('peer_not_ready')
            self.event['ready'] = hello
        except Exception:
            self.close(graceful=False)
            raise

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(self.bounds['response_line_bytes'] + 1)
                self.lines.put(line)
                if not line or len(line) > self.bounds['response_line_bytes'] or not line.endswith(b'\n'):
                    break
        except OSError:
            self.lines.put(b'')

    def _read_error(self):
        try:
            while True:
                part = self.process.stderr.read(4096)
                if not part:
                    return
                available = max(0, 65536 - len(self.stderr))
                self.stderr.extend(part[:available])
        except OSError:
            pass

    def _response(self, timeout):
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise PeerError('peer_read_timeout') from exc
        if not line:
            raise PeerError('peer_eof')
        if len(line) > self.bounds['response_line_bytes'] or not line.endswith(b'\n'):
            raise PeerError('peer_response_frame')
        try:
            result = json.loads(line)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise PeerError('peer_response_json') from exc
        if not isinstance(result, dict):
            raise PeerError('peer_response_shape')
        return result

    def request(self, value):
        if self.closed or self.process.poll() is not None:
            raise PeerError('peer_not_running')
        raw = (json.dumps(value, ensure_ascii=True, separators=(',', ':')) + '\n').encode('utf-8')
        if len(raw) > self.bounds['control_line_bytes']:
            raise PeerError('control_frame_too_large')
        errors = []

        def send():
            try:
                self.process.stdin.write(raw)
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                errors.append(type(exc).__name__)

        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        writer.join(timeout=self.bounds['request_seconds'])
        if writer.is_alive():
            raise PeerError('peer_write_timeout')
        if errors:
            raise PeerError('peer_write_failed')
        response = self._response(self.bounds['request_seconds'])
        if response.get('ok') is not True or 'result' not in response:
            raise PeerError('peer_control_rejected')
        self.last_observation = response.get('observation')
        return response['result']

    def close(self, graceful=True):
        if self.closed:
            return
        mode = 'already_exited'
        if self.process.poll() is None and graceful:
            try:
                self.request({'op': 'quit'})
                self.process.wait(timeout=self.bounds['close_seconds'])
                mode = 'graceful'
            except (PeerError, subprocess.TimeoutExpired):
                mode = 'graceful_failed'
        if self.process.poll() is None:
            self.process.terminate()  # This Popen-owned, nonsensitive child only.
            try:
                self.process.wait(timeout=self.bounds['close_seconds'])
                mode = 'terminated_own_child'
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=self.bounds['close_seconds'])
                mode = 'killed_own_child_after_terminate_timeout'
        self.closed = True
        self.reader.join(timeout=1)
        self.error_reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()
        self.event.update(closed=self.process.poll() is not None, returncode=self.process.poll(),
                          close_mode=mode, stderr=self.stderr.decode('utf-8', 'replace'),
                          reader_threads_finished=not self.reader.is_alive() and not self.error_reader.is_alive())


def load_plan(path):
    base = Path(__file__).resolve().parent
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError('plan_size')
    plan = json.loads(path.read_text(encoding='utf-8'))
    expected_sources = {'requirements.json', 'vectors.json', 'source-boundary-vectors.json', 'v11-boundary-vectors.json'}
    if type(plan) is not dict or plan.get('plan_id') != 'RIVER-LOCAL-INTEROP-1' or set(plan.get('bound_sources', {})) != expected_sources:
        raise ValueError('plan_identity')
    if type(plan.get('limits')) is not list or any(type(item) is not str for item in plan['limits']):
        raise ValueError('plan_limits')
    bound = []
    for name, expected in plan['bound_sources'].items():
        source = base.parent / 'river-demo' / name
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('source_binding_changed')
        bound.append({'name': name, 'sha256': actual, 'bytes': source.stat().st_size})
    if [c['version'] for c in plan['configurations']] != ['1.0', '1.1']:
        raise ValueError('configuration_list')
    if any(len(c['steps']) != 6 or len({s['id'] for s in c['steps']}) != 6 for c in plan['configurations']):
        raise ValueError('wire_steps')
    if len(plan['mixed_version_steps']) != 2 or plan['restart']['version'] != '1.1':
        raise ValueError('extra_steps')
    bounds = plan['bounds']
    if bounds['max_live_peers'] != 2 or bounds['expected_peer_starts'] != 7:
        raise ValueError('process_budget')
    if any(type(bounds[k]) not in (int, float) or not 0.05 <= bounds[k] <= 10 for k in ('ready_seconds', 'request_seconds', 'close_seconds')):
        raise ValueError('time_budget')
    if bounds['response_line_bytes'] != 262144 or bounds['control_line_bytes'] != 16384:
        raise ValueError('frame_budget')
    for config in plan['configurations']:
        for step in config['steps']:
            if (step['producer'], step['consumer']) not in {('A', 'B'), ('B', 'A')}:
                raise ValueError('peer_selection')
    return plan, bound


def raw_input(item):
    return bytes.fromhex(item['body_hex']) if 'body_hex' in item else item['body_text'].encode('utf-8')


def execute(path):
    base = Path(__file__).resolve().parent
    plan, sources = load_plan(path)  # Validate before starting any worker.
    start = time.monotonic()
    events, peers = [], []
    singles, sequences, exchanges, restarts = [], [], [], []
    execution_error = None
    corpora = [json.loads((base.parent / 'river-demo' / name).read_text(encoding='utf-8'))
               for name in ('vectors.json', 'source-boundary-vectors.json', 'v11-boundary-vectors.json')]
    vectors = [(name, item) for name, corpus in zip(('original58', 'source16', 'v11_78'), corpora) for item in corpus['vectors']]
    if len(vectors) != 152:
        raise ValueError('vector_count')
    own_sources = [Path(__file__), base / 'peer_a.py', base / 'peer_b.py', path]
    for source in own_sources:
        sources.append({'name': source.name, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'bytes': source.stat().st_size})
    all_paths = [base.parent / 'river-demo' / x['name'] for x in sources[:4]] + own_sources

    def launch(letter, version):
        if sum(p.process.poll() is None for p in peers) >= 2:
            raise PeerError('live_process_budget')
        peer = Peer(base / ('peer_' + letter.lower() + '.py'), version, events, plan['bounds'])
        peers.append(peer)
        return peer

    def observed_receive(peer, raw):
        before = peer.request({'op': 'snapshot'})
        actual = peer.request({'op': 'receive', 'body_hex': raw.hex()})
        observation = peer.last_observation
        if type(actual) is not dict or set(actual) != {'status', 'reason', 'state'} or type(actual['state']) is not dict:
            raise PeerError('actual_result_shape')
        if observation != {'input_bytes': len(raw), 'input_sha256': hashlib.sha256(raw).hexdigest()}:
            raise PeerError('actual_input_observation_mismatch')
        after = peer.request({'op': 'snapshot'})
        if actual.get('state') != after:
            raise PeerError('actual_state_snapshot_mismatch')
        return before, actual, observation

    try:
        for config in plan['configurations']:
            version = config['version']
            pair = {letter: launch(letter, version) for letter in ('A', 'B')}
            for letter, peer in pair.items():
                for corpus_name, item in vectors:
                    if item['receiver_version'] != version:
                        continue
                    peer.request({'op': 'reset', 'state': item['initial_state']})
                    raw = raw_input(item)
                    before, actual, observation = observed_receive(peer, raw)
                    singles.append({'corpus': corpus_name, 'id': item['id'], 'peer': letter, 'version': version,
                                    'initial_fixture': before, 'input_bytes': len(raw), 'input_sha256': observation['input_sha256'],
                                    'expected': item['expected'], 'actual': actual,
                                    'passed': actual == item['expected']})
                if version == '1.1':
                    for scenario in corpora[2]['sequences']:
                        peer.request({'op': 'reset', 'state': scenario['initial_state']})
                        steps = []
                        for index, item in enumerate(scenario['steps'], 1):
                            before, actual, observation = observed_receive(peer, raw_input(item))
                            steps.append({'step': index, 'actual_input_state': before, 'expected': item['expected'],
                                          'actual': actual, 'input_sha256': observation['input_sha256'],
                                          'passed': actual == item['expected']})
                        sequences.append({'id': scenario['id'], 'peer': letter, 'steps': steps,
                                          'passed': all(s['passed'] for s in steps)})
                peer.request({'op': 'reset', 'state': {}})
            payloads = {}
            for step in config['steps']:
                producer, receiver = pair[step['producer']], pair[step['consumer']]
                if 'payload_from' in step:
                    raw = payloads[step['payload_from']]
                else:
                    message = step['message']
                    encoded = producer.request({'op': 'encode', 'batch': message['batch'], 'records': message['records']})
                    raw = bytes.fromhex(encoded['body_hex'])
                    if encoded['bytes'] != len(raw):
                        raise PeerError('producer_length_mismatch')
                if 'replace_ascii' in step:
                    old = step['replace_ascii']['before'].encode('ascii')
                    if raw.count(old) != 1:
                        raise PeerError('declared_mutation_target')
                    raw = raw.replace(old, step['replace_ascii']['after'].encode('ascii'))
                payloads[step['id']] = raw
                before, actual, observation = observed_receive(receiver, raw)
                exchanges.append({'configuration': version, 'id': step['id'], 'producer': step['producer'],
                                  'consumer': step['consumer'], 'body_hex': raw.hex(), 'input_sha256': observation['input_sha256'],
                                  'actual_input_state': before, 'expected': step['expected'], 'actual': actual,
                                  'passed': actual == step['expected'], 'control_mutation': step.get('replace_ascii')})
            if version == '1.1':
                restart = plan['restart']
                old = pair['B']
                old_state = old.request({'op': 'snapshot'})
                old_pid = old.process.pid
                old.close()
                fresh = launch('B', version)
                initial = fresh.request({'op': 'snapshot'})
                before, actual, observation = observed_receive(fresh, payloads[restart['payload_from']])
                restarts.append({'version': version, 'peer': 'B', 'old_pid': old_pid, 'new_pid': fresh.process.pid,
                                 'old_state': old_state, 'actual_new_initial_state': initial,
                                 'actual_input_state': before, 'input_sha256': observation['input_sha256'],
                                 'expected': restart['expected'], 'actual': actual,
                                 'passed': initial == restart['expected_new_process_initial_state'] and actual == restart['expected'],
                                 'interpretation': restart['interpretation']})
                fresh.close()
            for peer in pair.values():
                peer.close()
        pair = {'A': launch('A', '1.0'), 'B': launch('B', '1.1')}
        for index, step in enumerate(plan['mixed_version_steps'], 1):
            message = step['message']
            encoded = pair[step['producer']].request({'op': 'encode', 'batch': message['batch'], 'records': message['records']})
            raw = bytes.fromhex(encoded['body_hex'])
            before, actual, observation = observed_receive(pair[step['consumer']], raw)
            exchanges.append({'configuration': 'mixed', 'id': 'mixed-' + str(index), 'producer': step['producer'],
                              'consumer': step['consumer'], 'body_hex': raw.hex(), 'input_sha256': observation['input_sha256'],
                              'actual_input_state': before, 'expected': step['expected'], 'actual': actual,
                              'passed': actual == step['expected']})
    except (PeerError, OSError, ValueError, KeyError, TypeError) as exc:
        execution_error = {'type': type(exc).__name__, 'reason': str(exc)}
    finally:
        for peer in peers:
            try:
                peer.close()
            except (OSError, subprocess.TimeoutExpired, PeerError) as exc:
                peer.event['cleanup_error'] = type(exc).__name__
    failed = sum(not row['passed'] for row in singles) + sum(not row['passed'] for row in sequences) + sum(not row['passed'] for row in exchanges + restarts)
    complete = len(singles) == 304 and len(sequences) == 6 and len(exchanges) == 14 and len(restarts) == 1
    cleanup_ok = len(events) == 7 and all(e['closed'] and e.get('returncode') == 0 and e.get('reader_threads_finished') for e in events)
    try:
        sources_unchanged = all(hashlib.sha256(p.read_bytes()).hexdigest() == item['sha256'] for p, item in zip(all_paths, sources))
    except OSError:
        sources_unchanged = False
    if not sources_unchanged:
        execution_error = execution_error or {'type': 'source_changed_after_start', 'reason': 'source_set_not_unchanged'}
    return {'date': '2026-11-03', 'kind': 'same_author_two_local_process_implementations_actual_run',
            'plan_id': plan['plan_id'], 'environment': {'python': platform.python_version(), 'platform': platform.platform()},
            'sources': sources, 'sources_unchanged_after': sources_unchanged, 'single_inputs': singles, 'state_sequences': sequences, 'wire_exchanges': exchanges,
            'fresh_process_scope': restarts, 'processes': events, 'execution_error': execution_error,
            'summary': {'visible_inputs': 152, 'peer_evaluations': len(singles), 'evaluations_failed': sum(not r['passed'] for r in singles),
                        'actual_state_sequences': len(sequences), 'state_steps': sum(len(s['steps']) for s in sequences),
                        'wire_deliveries': len(exchanges) + len(restarts), 'started_processes': len(events),
                        'all_owned_processes_closed': all(e['closed'] for e in events), 'complete': complete, 'failed_groups': failed},
            'wall_seconds': round(time.monotonic() - start, 6),
            'status': 'passed_finite_local_process_exercise' if complete and cleanup_ok and failed == 0 and execution_error is None else 'failed',
            'limits': plan['limits'] + ['No original model function used as live oracle; existing exposed expected fixtures still author-selected, not independent truth.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=Path(__file__).resolve().with_name('plan.json'))
    args = parser.parse_args()
    try:
        result = execute(args.plan.resolve())
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'rejected', 'error': str(exc), 'processes_started': 0}, ensure_ascii=True))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result['status'] == 'passed_finite_local_process_exercise' else 1


if __name__ == '__main__':
    raise SystemExit(main())
