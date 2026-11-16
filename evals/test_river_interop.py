"""Finite parser/process regression for the original local River exercise."""
from pathlib import Path
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'skills/dyz-standards/resources/river-local-interop'


def module(name):
    spec = importlib.util.spec_from_file_location('tested_river_' + name, BASE / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


A, B, RUN = module('peer_a'), module('peer_b'), module('run_interop')


class RiverLocalInteropTests(unittest.TestCase):
    def command(self, plan=None):
        args = [sys.executable, '-E', '-s', '-S', str(BASE / 'run_interop.py')]
        if plan:
            args += ['--plan', str(plan)]
        run = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=25)
        self.assertEqual('', run.stderr)
        return run.returncode, json.loads(run.stdout)

    def test_escaped_duplicate_and_numeric_policy_apply_before_shape(self):
        messages = [b'{"version":"1.1","batch":"A","records":[{"seq":1,"value":0,"s\\u0065q":2}]}',
                    b'{"unknown":{"x":1.0}}', b'{"x":01}', b'{"x":true,}', b'[1,]', b'{} {}']
        for raw in messages:
            for implementation in [A, B]:
                with self.subTest(message=raw, implementation=implementation.__name__):
                    self.assertEqual('json', implementation.receive(raw, '1.1', {})['reason'])
        valid = b'{"version":"1.1","batch":"\\u0041","records":[{"seq":1,"value":-0}]}'
        for implementation in [A, B]:
            self.assertEqual({'A': [{'seq': 1, 'value': 0}]}, implementation.receive(valid, '1.1', {})['state'])

    def test_late_field_error_wins_over_earlier_order_and_replay(self):
        raw = b'{"version":"1.1","batch":"A","records":[{"seq":7,"value":1},{"seq":4,"value":true}]}'
        state = {'A': [{'seq': 1, 'value': 9}]}
        frozen = copy.deepcopy(state)
        for implementation in [A, B]:
            result = implementation.receive(raw, '1.1', state)
            self.assertEqual(('rejected', 'field', frozen), (result['status'], result['reason'], result['state']))
            self.assertEqual(frozen, state)

    def test_iterative_depth_and_unpaired_surrogate_keep_field_categories(self):
        deep = b'{"version":"1.1","batch":"A","records":[{"seq":1,"value":' + b'[' * 100 + b'0' + b']' * 100 + b'}]}'
        surrogate = b'{"version":"1.1","batch":"\\ud800","records":[{"seq":1,"value":0}]}'
        for implementation in [A, B]:
            self.assertEqual('field', implementation.receive(deep, '1.1', {})['reason'])
            self.assertEqual('batch', implementation.receive(surrogate, '1.1', {})['reason'])

    def test_encoders_reject_extra_fields_instead_of_sanitizing(self):
        for implementation in [A, B]:
            with self.assertRaises(ValueError):
                implementation.encode('1.1', 'A', [{'seq': 1, 'value': 0, 'extra': 2}])
        rows = [{'seq': 4, 'value': None}, {'seq': 7, 'value': 0}]
        left, right = A.encode('1.1', 'ABC', rows), B.encode('1.1', 'ABC', rows)
        self.assertNotEqual(left, right)
        self.assertIn(b'\\u0041', right)
        self.assertEqual(rows, A.receive(right, '1.1', {})['state']['ABC'])
        self.assertEqual(rows, B.receive(left, '1.1', {})['state']['ABC'])

    def test_actual_default_process_exchange_is_complete_and_closed(self):
        code, report = self.command()
        self.assertEqual(0, code)
        self.assertEqual('passed_finite_local_process_exercise', report['status'])
        self.assertEqual((304, 6, 22, 15, 7), tuple(report['summary'][key] for key in
                         ('peer_evaluations', 'actual_state_sequences', 'state_steps', 'wire_deliveries', 'started_processes')))
        self.assertTrue(report['sources_unchanged_after'])
        self.assertTrue(all(p['closed'] and p['returncode'] == 0 for p in report['processes']))
        restart = report['fresh_process_scope'][0]
        self.assertNotEqual(restart['old_pid'], restart['new_pid'])
        self.assertTrue(restart['old_state'])
        self.assertEqual({}, restart['actual_new_initial_state'])

    def test_changed_source_binding_rejected_before_start(self):
        plan = json.loads((BASE / 'plan.json').read_text(encoding='utf-8'))
        plan['bound_sources']['requirements.json'] = '0' * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong-source.json'
            path.write_text(json.dumps(plan), encoding='utf-8')
            code, report = self.command(path)
        self.assertEqual((2, 'rejected', 'source_binding_changed', 0),
                         (code, report['status'], report['error'], report['processes_started']))

    def test_wrong_expected_state_is_not_used_as_actual_state(self):
        plan = json.loads((BASE / 'plan.json').read_text(encoding='utf-8'))
        plan['configurations'][0]['steps'][0]['expected']['state']['GHOST'] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong-expectation.json'
            path.write_text(json.dumps(plan), encoding='utf-8')
            code, report = self.command(path)
        self.assertEqual((1, 'failed', 1), (code, report['status'], report['summary']['failed_groups']))
        third = report['wire_exchanges'][2]
        self.assertEqual('same-A-again', third['id'])
        self.assertNotIn('GHOST', third['actual_input_state'])
        self.assertTrue(third['passed'])
        self.assertTrue(report['summary']['all_owned_processes_closed'])

    def test_owned_hung_peer_has_bounded_timeout_and_cleanup(self):
        bounds = dict(json.loads((BASE / 'plan.json').read_text(encoding='utf-8'))['bounds'])
        bounds['request_seconds'] = 0.2
        events = []
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / 'owned-hung-peer.py'
            program.write_text('import json,sys,time\nprint(json.dumps({"ready":True,"version":"1.1"}),flush=True)\nsys.stdin.readline()\ntime.sleep(60)\n', encoding='utf-8')
            peer = RUN.Peer(program, '1.1', events, bounds)
            try:
                with self.assertRaisesRegex(RUN.PeerError, 'peer_read_timeout'):
                    peer.request({'op': 'snapshot'})
            finally:
                peer.close(graceful=False)
        self.assertEqual(1, len(events))
        self.assertTrue(events[0]['closed'])
        self.assertTrue(events[0]['reader_threads_finished'])
        self.assertEqual('terminated_own_child', events[0]['close_mode'])

    def test_ready_eof_is_terminal_and_does_not_restart(self):
        events = []
        bounds = json.loads((BASE / 'plan.json').read_text(encoding='utf-8'))['bounds']
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / 'owned-eof-peer.py'
            program.write_text('raise SystemExit(0)\n', encoding='utf-8')
            with self.assertRaisesRegex(RUN.PeerError, 'peer_eof'):
                RUN.Peer(program, '1.1', events, bounds)
        self.assertEqual(1, len(events))
        self.assertTrue(events[0]['closed'])

    def test_non_numeric_timeout_rejected_before_start(self):
        plan = json.loads((BASE / 'plan.json').read_text(encoding='utf-8'))
        plan['bounds']['request_seconds'] = 'unbounded'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wrong-bounds.json'
            path.write_text(json.dumps(plan), encoding='utf-8')
            code, report = self.command(path)
        self.assertEqual((2, 'time_budget', 0), (code, report['error'], report['processes_started']))


if __name__ == '__main__':
    unittest.main()
