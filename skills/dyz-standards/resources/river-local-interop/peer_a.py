"""Original local River peer A: stdlib JSON decoder, compact JSON encoder.

Only the test-control stdin/stdout envelope uses line framing. River itself
still has no specified transport, wire acknowledgment or durable state.
Same-author development implementation; imports neither old model nor peer B.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys


def _object(pairs):
    names = [key for key, _ in pairs]
    if len(names) != len(set(names)):
        raise ValueError('duplicate')
    return dict(pairs)


def _not_integer(_):
    raise ValueError('number_policy')


def receive(raw, version, state):
    def result(reason, accepted=None):
        after = copy.deepcopy(state)
        if accepted is not None:
            after[accepted['batch']] = copy.deepcopy(accepted['records'])
        return {'status': 'accepted' if reason == 'accepted' else 'rejected', 'reason': reason, 'state': after}

    if version not in ('1.0', '1.1'):
        raise ValueError('configuration')
    if len(raw) == 0 or len(raw) > 1024:
        return result('size')
    try:
        text = raw.decode('utf-8', 'strict')
    except UnicodeDecodeError:
        return result('encoding')
    if text.startswith('\ufeff'):
        return result('encoding')
    try:
        value = json.loads(text, object_pairs_hook=_object, parse_float=_not_integer, parse_constant=_not_integer)
    except (ValueError, RecursionError):
        return result('json')
    if type(value) is not dict or sorted(value) != ['batch', 'records', 'version']:
        return result('shape')
    if type(value['version']) is not str or value['version'] != version:
        return result('version')
    name = value['batch']
    if type(name) is not str or not re.fullmatch('[A-Z][A-Z0-9-]{0,15}', name):
        return result('batch')
    rows = value['records']
    if type(rows) is not list or len(rows) not in (1, 2, 3, 4):
        return result('records')

    def field_ok(row):
        if type(row) is not dict or sorted(row) != ['seq', 'value']:
            return False
        number, reading = row['seq'], row['value']
        if type(number) is not int or version == '1.1' and not 1 <= number <= 999:
            return False
        return version == '1.1' and reading is None or type(reading) is int and 0 <= reading <= 1000

    if not all(field_ok(row) for row in rows):
        return result('field')
    numbers = [row['seq'] for row in rows]
    order_ok = (numbers == list(range(1, len(rows) + 1)) if version == '1.0'
                else all(left < right for left, right in zip(numbers, numbers[1:])))
    if not order_ok:
        return result('order')
    if name in state:
        return result('replay')
    return result('accepted', value)


def encode(version, batch, records):
    wire = json.dumps({'version': version, 'batch': batch, 'records': records},
                      ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    if receive(wire, version, {})['status'] != 'accepted':
        raise ValueError('encoder_input_not_valid')
    return wire


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, choices=('1.0', '1.1'))
    version = parser.parse_args().version
    state = {}
    print(json.dumps({'ready': True, 'peer': 'A', 'version': version, 'wire_decoder': 'stdlib-json'}), flush=True)
    while True:
        line = sys.stdin.buffer.readline(16385)
        if not line:
            return 0
        if len(line) > 16384 or not line.endswith(b'\n'):
            print(json.dumps({'ok': False, 'error': 'control_frame'}), flush=True)
            return 2
        try:
            command = json.loads(line)
            op = command['op']
            observation = None
            if op == 'receive':
                raw = bytes.fromhex(command['body_hex'])
                response = receive(raw, version, state)
                state = response['state']
                observation = {'input_bytes': len(raw), 'input_sha256': hashlib.sha256(raw).hexdigest()}
            elif op == 'encode':
                wire = encode(version, command['batch'], command['records'])
                response = {'body_hex': wire.hex(), 'bytes': len(wire)}
            elif op == 'reset':
                if type(command['state']) is not dict:
                    raise ValueError('fixture')
                state = copy.deepcopy(command['state'])
                response = copy.deepcopy(state)
            elif op == 'snapshot':
                response = copy.deepcopy(state)
            elif op == 'quit':
                print(json.dumps({'ok': True, 'result': {'closed': True}}), flush=True)
                return 0
            else:
                raise ValueError('operation')
            print(json.dumps({'ok': True, 'result': response, 'observation': observation}, ensure_ascii=True, separators=(',', ':')), flush=True)
        except (ValueError, KeyError, TypeError, RecursionError):
            print(json.dumps({'ok': False, 'error': 'control_rejected'}), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
