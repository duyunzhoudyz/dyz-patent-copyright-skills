"""Original River peer B: iterative wire parser and separately built encoder.

json is used ONLY for the test-control envelope, never to decode River bytes.
No old model/peer A import. Same author and exposed requirements, not a vendor
independence claim. Memory serial state, no networking or durable storage.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys


def _string(text, position):
    parts = []
    position += 1
    escapes = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
    while position < len(text):
        char = text[position]
        position += 1
        if char == '"':
            return ''.join(parts), position
        if ord(char) < 32:
            raise ValueError('string_control')
        if char != '\\':
            parts.append(char)
            continue
        if position >= len(text):
            raise ValueError('escape_end')
        char = text[position]
        position += 1
        if char in escapes:
            parts.append(escapes[char])
            continue
        if char != 'u':
            raise ValueError('escape')
        digits = text[position:position + 4]
        if len(digits) != 4 or any(x not in '0123456789abcdefABCDEF' for x in digits):
            raise ValueError('unicode_escape')
        code = int(digits, 16)
        position += 4
        if 0xD800 <= code <= 0xDBFF and text[position:position + 2] == '\\u':
            other = text[position + 2:position + 6]
            if len(other) == 4 and all(x in '0123456789abcdefABCDEF' for x in other):
                low = int(other, 16)
                if 0xDC00 <= low <= 0xDFFF:
                    code = 0x10000 + (code - 0xD800) * 1024 + low - 0xDC00
                    position += 6
        parts.append(chr(code))
    raise ValueError('string_end')


def _tokens(text):
    position = 0
    while position < len(text):
        char = text[position]
        if char in ' \t\r\n':
            position += 1
        elif char in '{}[]:,':
            yield char, None
            position += 1
        elif char == '"':
            value, position = _string(text, position)
            yield 'value', value
        elif char == '-' or char in '0123456789':
            start = position
            position += char == '-'
            if position >= len(text) or text[position] not in '0123456789':
                raise ValueError('number')
            if text[position] == '0':
                position += 1
            else:
                while position < len(text) and text[position] in '0123456789':
                    position += 1
            if position < len(text) and text[position] in '.eE':
                raise ValueError('number_policy')
            yield 'value', int(text[start:position])
        else:
            for word, value in [('true', True), ('false', False), ('null', None)]:
                if text.startswith(word, position):
                    position += len(word)
                    yield 'value', value
                    break
            else:
                raise ValueError('token')


def decode_wire(text):
    """Iterative container assembly; bounded by the caller's1024byte limit."""
    stack, root, done = [], None, False

    def attach(value):
        nonlocal root, done
        if not stack:
            if done:
                raise ValueError('trailing_value')
            root, done = value, True
        else:
            frame = stack[-1]
            if frame['kind'] == 'object':
                if frame['stage'] != 'value':
                    raise ValueError('object_value')
                frame['data'][frame['key']] = value
            else:
                if frame['stage'] not in ('value0', 'value1'):
                    raise ValueError('array_value')
                frame['data'].append(value)
            frame['stage'] = 'after'

    for token, value in _tokens(text):
        if stack:
            f = stack[-1]
            if f['kind'] == 'object' and f['stage'] in ('key0', 'key1'):
                if token == '}' and f['stage'] == 'key0':
                    stack.pop()
                    continue
                if token != 'value' or type(value) is not str or value in f['data']:
                    raise ValueError('key_or_duplicate')
                f['key'], f['stage'] = value, 'colon'
                continue
            if f['kind'] == 'object' and f['stage'] == 'colon':
                if token != ':':
                    raise ValueError('colon')
                f['stage'] = 'value'
                continue
            if f['stage'] == 'after':
                if token == ',':
                    f['stage'] = 'key1' if f['kind'] == 'object' else 'value1'
                    continue
                if token == ('}' if f['kind'] == 'object' else ']'):
                    stack.pop()
                    continue
                raise ValueError('separator')
            if f['kind'] == 'array' and f['stage'] == 'value0' and token == ']':
                stack.pop()
                continue
        if token == 'value':
            attach(value)
        elif token in ('{', '['):
            container = {} if token == '{' else []
            attach(container)
            stack.append({'kind': 'object' if token == '{' else 'array', 'data': container,
                          'stage': 'key0' if token == '{' else 'value0'})
        else:
            raise ValueError('value')
    if not done or stack:
        raise ValueError('unfinished')
    return root


def receive(raw, version, state):
    if version not in ('1.0', '1.1'):
        raise ValueError('configuration')
    reason, parsed = 'accepted', None
    if len(raw) < 1 or len(raw) > 1024:
        reason = 'size'
    else:
        try:
            if raw[:3] == bytes([239, 187, 191]):
                raise UnicodeError('bom')
            text = raw.decode('utf-8')
        except UnicodeError:
            reason = 'encoding'
        else:
            try:
                parsed = decode_wire(text)
            except ValueError:
                reason = 'json'
    if reason == 'accepted':
        if type(parsed) is not dict or len(parsed) != 3 or any(k not in parsed for k in ('version', 'batch', 'records')):
            reason = 'shape'
        elif type(parsed['version']) is not str or parsed['version'] != version:
            reason = 'version'
        else:
            batch = parsed['batch']
            if (type(batch) is not str or not 1 <= len(batch) <= 16 or not 'A' <= batch[0] <= 'Z'
                    or any(not ('A' <= c <= 'Z' or '0' <= c <= '9' or c == '-') for c in batch[1:])):
                reason = 'batch'
            elif type(parsed['records']) is not list or not 1 <= len(parsed['records']) <= 4:
                reason = 'records'
            else:
                previous = None
                ordering = True
                for index, row in enumerate(parsed['records'], 1):
                    if type(row) is not dict or len(row) != 2 or 'seq' not in row or 'value' not in row:
                        reason = 'field'
                        break
                    sequence, reading = row['seq'], row['value']
                    if type(sequence) is not int or version == '1.1' and (sequence < 1 or sequence > 999):
                        reason = 'field'
                        break
                    if not (version == '1.1' and reading is None):
                        if type(reading) is not int or reading < 0 or reading > 1000:
                            reason = 'field'
                            break
                    if version == '1.0' and sequence != index or version == '1.1' and previous is not None and sequence <= previous:
                        ordering = False
                    previous = sequence
                if reason == 'accepted' and not ordering:
                    reason = 'order'
                if reason == 'accepted' and batch in state:
                    reason = 'replay'
    after = copy.deepcopy(state)
    if reason == 'accepted':
        after[parsed['batch']] = copy.deepcopy(parsed['records'])
    return {'status': 'accepted' if reason == 'accepted' else 'rejected', 'reason': reason, 'state': after}


def encode(version, batch, records):
    if type(batch) is not str or not batch or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-' for c in batch):
        raise ValueError('batch')
    # Always escape the first batch character, reorder members and add JSON
    # whitespace: byte identity is not required for equal decoded identifiers.
    quoted_batch = '"\\u' + format(ord(batch[0]), '04x') + batch[1:] + '"'
    rows = []
    if type(records) is not list or not 1 <= len(records) <= 4:
        raise ValueError('encoder_records')
    for record in records:
        if type(record) is not dict or set(record) != {'seq', 'value'}:
            raise ValueError('encoder_fields')
        reading = record['value']
        if reading is not None and type(reading) is not int or type(record['seq']) is not int:
            raise ValueError('encoder_field')
        rows.append('{ "value" : ' + ('null' if reading is None else str(reading)) + ', "seq" : ' + str(record['seq']) + ' }')
    text = '{\n "records" : [ ' + ', '.join(rows) + ' ], "batch" : ' + quoted_batch + ', "version" : "' + version + '"\n}'
    wire = text.encode('utf-8')
    if receive(wire, version, {})['status'] != 'accepted':
        raise ValueError('encoder_input_not_valid')
    return wire


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, choices=('1.0', '1.1'))
    version = parser.parse_args().version
    state = {}
    print(json.dumps({'ready': True, 'peer': 'B', 'version': version, 'wire_decoder': 'own-iterative'}), flush=True)
    while True:
        line = sys.stdin.buffer.readline(16385)
        if not line:
            return 0
        if len(line) > 16384 or not line.endswith(b'\n'):
            print(json.dumps({'ok': False, 'error': 'control_frame'}), flush=True)
            return 2
        try:
            command = json.loads(line)  # Test envelope only, not River wire bytes.
            operation = command['op']
            observation = None
            if operation == 'encode':
                raw = encode(version, command['batch'], command['records'])
                response = {'body_hex': raw.hex(), 'bytes': len(raw)}
            elif operation == 'receive':
                raw = bytes.fromhex(command['body_hex'])
                response = receive(raw, version, state)
                state = response['state']
                observation = {'input_bytes': len(raw), 'input_sha256': hashlib.sha256(raw).hexdigest()}
            elif operation == 'snapshot':
                response = copy.deepcopy(state)
            elif operation == 'reset':
                if type(command['state']) is not dict:
                    raise ValueError('fixture')
                state = copy.deepcopy(command['state'])
                response = copy.deepcopy(state)
            elif operation == 'quit':
                print(json.dumps({'ok': True, 'result': {'closed': True}}), flush=True)
                return 0
            else:
                raise ValueError('operation')
            print(json.dumps({'ok': True, 'result': response, 'observation': observation}, ensure_ascii=True, separators=(',', ':')), flush=True)
        except (ValueError, KeyError, TypeError, RecursionError):
            print(json.dumps({'ok': False, 'error': 'control_rejected'}), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
