"""标准五文书编排与实物回验；不替代组织批准、专业签核或外发审批。

业务规则归standards，OOXML归documents。实物证明不回写处置决定，最终
清单不含自身hash；阶段确认引用现有VersionLedger，而不是第二个账本。
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
import stat

from tools import documents, standards
from tools.core import (
    ContractError, VersionLedger, canonical_bytes, check_permission, digest, is_macos_system_root_symlink,
    parse_time, preflight, require, require_fields, safe_path, sha256_bytes,
)

VERSION = '1.7'
ASSESSMENT_VERSION = 'standards-consistency/1'
ROLES = ('standard', 'compilation_note', 'comment_disposition',
         'verification_matrix', 'review_report')
MAX_INPUT_BYTES = 5_000_000
MAX_FILE_BYTES = 20_000_000


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plain_path(path, *, file=False):
    """不跟随链接/Windows重解析点；工作根仍须由调用者排他保护。"""
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        is_link = stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
        if is_link:
            if current != path and is_macos_system_root_symlink(current):
                try:
                    info = current.stat()
                except OSError:
                    raise ContractError('standard_path_link_unsupported') from None
            else:
                require(False, 'standard_path_link_unsupported')
        if current == path and file:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    'standard_file_alias_unsupported')


def _admit(root, payload, output, *, synthetic, admission, write=False):
    require(type(synthetic) is bool, 'standard_synthetic_flag_invalid')
    require(isinstance(payload, dict), 'standard_payload_required')
    require(len(canonical_bytes(payload)) <= MAX_INPUT_BYTES, 'standard_payload_too_large')
    _plain_path(Path(root).absolute())
    base = Path(root).resolve(strict=True)
    require(base.is_dir(), 'standard_root_required')
    target = safe_path(base, output, must_exist=False)
    # 根内链接同样可能指向另一份用户材料，不能仅靠resolve后的包含关系放行。
    relative = Path(output.replace('\\', '/'))
    current = base
    for part in relative.parts:
        current = current / part
        _plain_path(current)
    if synthetic:
        require(admission is None and payload.get('sensitivity') == 'synthetic',
                'standard_synthetic_scope_required')
        return base, target, 'synthetic'
    require(isinstance(admission, dict), 'standard_admission_required')
    package_root = Path(__file__).resolve().parents[1]
    require(not (base == package_root or base.is_relative_to(package_root)
                 or package_root.is_relative_to(base)), 'standard_case_root_must_be_independent')
    require_fields(admission, ('root', 'output', 'payload_hash', 'sensitivity',
                               'purpose', 'permissions', 'environment'))
    require(Path(admission['root']).resolve(strict=True) == base
            and admission['output'] == output
            and admission['payload_hash'] == digest(payload), 'standard_admission_binding_changed')
    require(admission['sensitivity'] in {'public', 'confidential', 'restricted'}
            and admission['sensitivity'] == payload.get('sensitivity'),
            'standard_admission_sensitivity_mismatch')
    now = _now()
    # 公开可读不等于允许外部处理；所有真实模式都按完整数据路径预检。
    preflight(admission['environment'], admission['permissions'],
              sensitivity='restricted', purpose=admission['purpose'], now=now)
    for action in ('local_process', 'copy'):
        check_permission(admission['permissions'], action=action,
                         purpose=admission['purpose'], recipient='local_tool', now=now)
    if write:
        check_permission(admission['permissions'], action='local_write',
                         purpose=admission['purpose'], recipient='local_tool', now=now)
    return base, target, 'authorized_case'


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # JSON对象键顺序不是内容；包内规范化保存再读不得改变成件字节。
        return '\n'.join(str(key) + '：' + _text(value[key]) for key in sorted(value)) or '（空记录）'
    if isinstance(value, list):
        return '\n'.join(f'{index}. ' + _text(item) for index, item in enumerate(value, 1)) or '（空集合）'
    return canonical_bytes(value).decode('utf-8')


def _pending_reader_text(pending):
    # 同一理由合并展示，但保留每项原序号与目标，完整机器证据仍由checks拥有。
    groups = {}
    labels = {'clause': '条款', 'comment': '意见原文', 'comment_reason': '意见理由',
              'verification': '验证方法', 'verification_basis': '验证依据',
              'compilation_note': '编制说明', 'note_section': '说明章节'}
    for index, row in enumerate(pending, 1):
        key = (row['code'], row.get('reason', ''), row.get('limitation_type'))
        target = row.get('target_id', row.get('record_id', '未定位'))
        location = '第' + str(index) + '项：' + labels.get(row.get('target_type'), '记录') + target
        if row.get('record_id') and row['record_id'] != target:
            location += '，记录' + row['record_id']
        if row.get('binding_id'):
            location += '，来源绑定' + row['binding_id']
        groups.setdefault(key, []).append(location)
    lines = []
    for index, ((code, reason, limitation), locations) in enumerate(groups.items(), 1):
        kind = '；限制类型' + limitation if limitation else ''
        lines.append(str(index) + '. ' + (reason or '需责任人补充复核依据。')
                     + '（' + code + kind + '）\n涉及：' + '；'.join(locations))
    return ('有限核对待审事项（共' + str(len(pending)) + '项）：\n' + '\n'.join(lines)
            + '\n完整逐项证据与原序号见 internal/checks.json 的 pending_reviews；'
            + '上述事项尚需相应专业复核，确定性问题为零不构成完成审阅。')


def _source_citation_reader_text(citations):
    # 页段和引文供人核对；完整字段及重复上下文由来源链保全。
    lines = []
    for citation in citations:
        lines.append('引文 ' + citation['id'])
        for segment in citation['segments'] if 'segments' in citation else [citation]:
            lines.append('第' + str(segment['page']) + '页，字符范围['
                         + str(segment['start']) + ',' + str(segment['end']) + ')')
            lines.append('原文：\n' + segment['quote'])
            context = segment.get('context')
            if context and context != segment['quote']:
                lines.append('上下文（字符范围[' + str(segment['context_start'])
                             + ',' + str(segment['context_end']) + ')）：\n' + context)
    lines.append('完整来源字段与字节绑定见 internal/source-trace.json；字符范围为零基半开区间。')
    return '\n'.join(lines)


def _block(identity, text, *, heading=False, origin='derived'):
    require(isinstance(text, str) and bool(text.strip()), 'standard_document_text_required')
    require(all(c in '\n\t' or ord(c) >= 32 for c in text)
            and not any(0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF} for c in text),
            'standard_document_character_invalid')
    return {'id': identity, 'kind': 'heading1' if heading else 'paragraph',
            'audience': 'body', 'text': text, 'text_sha256': sha256_bytes(text.encode('utf-8')),
            'origin': origin}


def _identifier(prefix, identity):
    return prefix + '_' + digest(identity)[:24]


def _table(identity, cells, origin):
    require(bool(cells) and 1 <= len(cells[0]) <= 6
            and all(len(row) == len(cells[0]) for row in cells), 'standard_table_shape')
    # 概览表只放短定位，完整意见、理由和未知状态始终在后续详情保留。
    for row in cells:
        for value in row:
            _block('Cell', value)
    return {'id': identity, 'kind': 'table', 'audience': 'body', 'cells': cells,
            'text': _text(cells), 'text_sha256': digest(cells), 'origin': origin}


def _outline(payload, issues):
    """章号只是一层显示关系；稳定ID与原始条款从不随排版重编号。"""
    presentation = payload.get('presentation', {})
    require(isinstance(presentation, dict), 'standard_presentation_required')
    rows = presentation.get('outline')
    clauses = {row['id']: row for row in payload['clauses']}
    if rows is None:
        rows = [dict(id='outline-' + str(index), kind='clause', clause_id=key,
                     title='') for index, key in enumerate(clauses, 1)]
        default = True
    else:
        require(isinstance(rows, list) and len(rows) <= 1000, 'standard_outline_required')
        default = False
    by_id, children, located = {}, {}, set()
    for row in rows:
        require(isinstance(row, dict), 'standard_outline_node_required')
        require_fields(row, ('id', 'kind'))
        require(isinstance(row['id'], str) and bool(row['id'].strip())
                and row['id'] not in by_id, 'standard_outline_duplicate_id')
        require(set(row) <= {'id', 'parent_id', 'kind', 'title', 'clause_id'},
                'standard_outline_field_unsupported')
        require(isinstance(row['kind'], str) and row['kind'] in {'section', 'clause', 'annex'},
                'standard_outline_kind')
        require(isinstance(row.get('title', ''), str), 'standard_outline_title')
        parent = row.get('parent_id')
        require(parent is None or isinstance(parent, str) and bool(parent.strip()),
                'standard_outline_parent')
        if row['kind'] == 'clause':
            key = row.get('clause_id')
            require(isinstance(key, str) and key in clauses, 'standard_outline_clause_unknown')
            require(key not in located, 'standard_outline_clause_duplicate')
            located.add(key)
        else:
            require('clause_id' not in row, 'standard_outline_clause_on_section')
        by_id[row['id']] = row
        children.setdefault(parent, []).append(row)
    for row in rows:
        parent = row.get('parent_id')
        require(parent is None or parent in by_id, 'standard_outline_parent_unknown')
        seen, current = set(), row
        while current is not None:
            require(current['id'] not in seen, 'standard_outline_cycle')
            seen.add(current['id'])
            require(len(seen) <= 4, 'standard_outline_depth_unsupported')
            current = by_id.get(current.get('parent_id'))
        if parent is not None:
            require(by_id[parent]['kind'] != 'clause', 'standard_outline_clause_has_children')
        if row['kind'] == 'annex':
            require(parent is None, 'standard_outline_annex_must_be_root')
    for key in sorted(clauses.keys() - located):
        issues.append({'code': 'standard_outline_clause_missing', 'clause_id': key})
        row = dict(id='missing-' + digest(key)[:20], kind='clause', clause_id=key, title='')
        require(row['id'] not in by_id, 'standard_outline_duplicate_id')
        children.setdefault(None, []).append(row)
    blocks, locations = [], {}
    root_number, annex_number = 0, 0
    def walk(parent=None, prefix='', depth=1, in_annex=False):
        nonlocal root_number, annex_number
        local_number = 0
        for row in children.get(parent, []):
            local_number += 1
            if parent is None:
                if row['kind'] == 'annex':
                    annex_number += 1
                    require(annex_number <= 26, 'standard_outline_annex_limit')
                    number = chr(64 + annex_number)
                else:
                    root_number += 1
                    number = str(root_number)
            else:
                number = prefix + '.' + str(local_number)
            title = row.get('title', '')
            if not title and not default:
                issues.append({'code': 'standard_outline_title_missing', 'node_id': row['id']})
            label = ('附录' + number if row['kind'] == 'annex' else number)
            if title:
                label += ' ' + title
            heading = _block(_identifier('Title', row['id']), label, heading=True,
                             origin='presentation/outline/' + row['id'])
            supports_depth = payload['profile'].get('rendering') in {
                'dyz-standard-internal-v2', 'dyz-standard-internal-v3',
            }
            heading['kind'] = 'heading' + str(depth if supports_depth else min(depth, 2))
            heading['outline_level'] = depth
            if supports_depth:
                heading['annex'] = in_annex or row['kind'] == 'annex'
            blocks.append(heading)
            if row['kind'] == 'clause':
                clause = clauses[row['clause_id']]
                block = _block(_identifier('Clause', clause['id']), clause['text'],
                               origin='clauses/' + clause['id'])
                block.update(display_number=number, text_kind=clause.get('text_kind', 'narrative'))
                blocks.append(block)
                labels = {'conditions': '适用条件', 'exceptions': '例外', 'quantities': '量值与容差（tolerance）'}
                for field, label in labels.items():
                    if clause.get(field):
                        blocks.append(_block(_identifier('Constraint', [clause['id'], field]),
                            label + '：' + _text(clause[field]),
                            origin='clauses/' + clause['id'] + '/' + field))
                locations[clause['id']] = dict(display_number=number, document_role='standard',
                    block_id=block['id'], bookmark=block['id'],
                    source_path='/clauses/' + str(next(i for i, c in enumerate(payload['clauses'])
                                                      if c['id'] == clause['id'])))
            walk(row['id'], number, depth + 1, in_annex or row['kind'] == 'annex')
    walk()
    return blocks, locations, default


def _record_text(record, labels):
    return '\n'.join(labels.get(key, '补充记录/' + key) + '：' + _text(record[key])
                     for key in sorted(record))


def _projection_coverage(payload, maps):
    """核心记录须供读者看到；每个原始叶子另绑定到规范保存的输入位置。"""
    origins = {}
    for role, blocks in maps.items():
        for block in blocks:
            if block['kind'] == 'field':
                continue
            origins.setdefault(block.get('origin'), []).append(
                {'document_role': role, 'block_id': block['id'], 'bookmark': block['id']})
    core = []
    for collection in ('clauses', 'comments', 'comment_outcomes', 'verification_matrix',
                       'open_items', 'verification_open_items', 'reference_open_items',
                       'profile_open_items', 'material_open_items'):
        for index, record in enumerate(payload.get(collection, [])):
            identity = record.get('id', str(index))
            origin = collection + '/' + (identity if collection in {'clauses', 'comments'} else str(index))
            core.append({'source_path': '/' + collection + '/' + str(index),
                         'record_hash': digest(record), 'reader_blocks': origins.get(origin, [])})
    for index, record in enumerate(payload.get('compilation_note', {}).get('sections', [])):
        origin = 'compilation_note/sections/' + str(index)
        core.append({'source_path': '/' + origin, 'record_hash': digest(record),
                     'reader_blocks': origins.get(origin, [])})
    missing = [row['source_path'] for row in core if not row['reader_blocks']]
    require(not missing, 'standard_projection_core_missing')
    leaves = []
    def walk(value, path=''):
        if isinstance(value, dict) and value:
            for key in sorted(value):
                walk(value[key], path + '/' + key.replace('~', '~0').replace('/', '~1'))
        elif isinstance(value, list) and value:
            for index, item in enumerate(value):
                walk(item, path + '/' + str(index))
        else:
            leaves.append({'source_path': path, 'value_hash': digest(value),
                           'retained_at': 'internal/input.json#' + path})
    walk(payload)
    return {'status': 'complete', 'input_hash': digest(payload), 'core_records': core,
            'leaves': leaves, 'unmapped_core_records': missing, 'unpreserved_leaves': []}


def _profile_fields(blocks, rendering):
    """仅原创内部版式写受限域；源映射也保存这些实际块，不冒充刷新。"""
    if rendering not in {'dyz-standard-internal-v1', 'dyz-standard-internal-v2', 'dyz-standard-internal-v3'}:
        return blocks
    result = []
    has_contents = any(block['kind'] in {'heading1', 'heading2'} for block in blocks[1:])
    for index, block in enumerate(blocks):
        if index == 0 and block['kind'] == 'heading1':
            block = dict(block, kind='title')
        if block['kind'] == 'table':
            sequence_id = _identifier('Sequence', block['id'])
            result.append({'id': sequence_id, 'kind': 'field', 'field_type': 'SEQ',
                           'sequence': 'Table', 'prefix': '表 ', 'origin': block['origin']})
        result.append(block)
        if index == 1 and has_contents:
            result.append({'id': 'DocumentContents', 'kind': 'field', 'field_type': 'TOC',
                           'origin': 'derived_headings'})
        if block['kind'] == 'table':
            result.extend([
                {'id': _identifier('TableReference', block['id']), 'kind': 'field',
                 'field_type': 'REF', 'target': sequence_id, 'prefix': '表号引用：',
                 'origin': block['origin']},
                {'id': _identifier('TablePage', block['id']), 'kind': 'field',
                 'field_type': 'PAGEREF', 'target': block['id'], 'prefix': '表起始页：',
                 'origin': block['origin']}])
        elif block['id'].startswith('Clause_'):
            result.append({'id': _identifier('ClausePage', block['id']), 'kind': 'field',
                           'field_type': 'PAGEREF', 'target': block['id'],
                           'prefix': '本条正文起始页：', 'origin': block['origin']})
    return result


def _document(role, blocks, rendering, *, stage):
    if rendering is None:
        raw = documents.make_docx(blocks, [])
        checks = documents.inspect_generated_docx(raw, blocks, [])
    else:
        raw = documents.make_docx(blocks, [], profile=rendering)
        checks = documents.inspect_generated_docx(raw, blocks, [], profile=rendering)
    # 不用源JSON冒充最终文字扫描：quality_docx重新读取真实ZIP/XML。
    quality = documents.quality_docx(raw, stage=stage)
    return raw, {'role': role, 'checks': checks, 'quality': quality,
                 'visual_review': 'not_performed', 'semantic_fidelity': 'not_performed'}


def _realizations(payload, body_hash, assessment):
    old = {item['id']: item['text'] for item in payload.get('baseline_clauses', [])}
    new = {item['id']: item['text'] for item in payload['clauses']}
    rows = []
    for outcome in payload.get('comment_outcomes', []):
        if outcome['outcome'] not in {'accepted', 'partially_accepted'}:
            continue
        changes = outcome.get('changes', [])
        if not changes and 'proposed_text' in outcome and 'clause_id' in outcome:
            changes = [{'operation': 'replace', 'clause_id': outcome['clause_id'],
                        'proposed_text': outcome['proposed_text']}]
        matches = []
        for change in changes:
            key, operation = change['clause_id'], change['operation']
            actual = (key in old and key not in new if operation == 'delete' else
                      key in new and new[key] == change.get('proposed_text')
                      and (key in old if operation == 'replace' else key not in old))
            matches.append({'clause_id': key, 'operation': operation, 'text_matches': actual})
        no_change = next((item for item in assessment.get('no_change_checks', [])
                          if item['comment_id'] == outcome['comment_id']), None)
        status = ('unchanged_structure_bound' if no_change and no_change['structure_status'] == 'matched'
                  else 'text_binding_checked' if matches and all(m['text_matches'] for m in matches)
                  else 'needs_review')
        rows.append({'comment_id': outcome['comment_id'], 'decision_hash': digest(outcome),
                     'baseline_clause_digest': digest(payload.get('baseline_clauses', [])),
                     'target_clause_digest': digest(payload['clauses']), 'body_sha256': body_hash,
                     'changes': matches, 'no_change': outcome.get('no_change') is True,
                     'status': status, 'no_change_check': no_change,
                     'scope': 'text_equality_only_not_authority_or_professional_acceptance'})
    return rows


def _verify_sources(root, payload, *, synthetic, admission):
    if not payload.get('source_reports') and not payload.get('source_bindings'):
        return None
    from tools import standard_sources
    source_admission = None
    if not synthetic:
        require(isinstance(admission.get('inputs'), dict), 'standard_source_inventory_required')
        source_admission = {key: admission[key] for key in
            ('root', 'payload_hash', 'sensitivity', 'purpose', 'permissions', 'environment', 'inputs')}
        source_admission['outputs'] = []
    return standard_sources.verify_reports(root, payload, synthetic=synthetic, admission=source_admission)


def _trace_locations(payload, trace, maps, actual_documents):
    result = []
    for source in trace:
        row = copy.deepcopy(source)
        kind, identity = row['target_type'], row['target_id']
        origins = set()
        if kind == 'clause':
            origins.add('clauses/' + identity)
        elif kind in {'comment', 'comment_reason'}:
            origins.add('comments/' + identity)
            origins.update('comment_outcomes/' + str(index)
                for index, record in enumerate(payload.get('comment_outcomes', []))
                if record['comment_id'] == identity)
        elif kind in {'verification', 'verification_basis'}:
            origins.update('verification_matrix/' + str(index)
                for index, record in enumerate(payload.get('verification_matrix', []))
                if record['id'] == identity)
        elif kind in {'compilation_note', 'note_section'}:
            origins.update('compilation_note/sections/' + str(index)
                for index, record in enumerate(payload.get('compilation_note', {}).get('sections', []))
                if record['id'] == identity)
        elif kind == 'external_reference':
            origins.add('external_references/' + identity)
        row['final_locations'] = [{'document_role': role, 'block_id': block['id'],
            'bookmark': block['id'], 'display_number': block.get('display_number'),
            'origin': block.get('origin'),
            'page': None, 'page_status': 'not_generated', 'text_sha256': block.get('text_sha256')}
            for role, blocks in maps.items() for block in blocks
            if block['kind'] != 'field' and block.get('origin') in origins]
        require(bool(row['final_locations']), 'standard_source_projection_missing')
        for location in row['final_locations']:
            actual = actual_documents[location['document_role']]
            records = [record for record in actual['bookmarks']
                       if record['name'] == location['bookmark']]
            valid = (len(records) == 1 and records[0]['identity_state'] == 'paired_unique_name'
                     and records[0]['text_state'] == 'literal_span')
            location.update(document_sha256=actual['sha256'],
                actual_text=records[0]['text'] if valid else None,
                actual_text_sha256=sha256_bytes(records[0]['text'].encode('utf-8')) if valid else None,
                actual_text_state='literal_span_verified' if valid else 'not_verified',
                semantic_review='needs_review')
        result.append(row)
    return result


def _actual_source_blocks(payload, traces):
    """只取实际书签中唯一匹配的业务字段；表头、附注及结构摘要不替代原文。"""
    result = {}
    for row in traces:
        kind, identity = row['target_type'], row['target_id']
        fields = []
        if kind == 'comment':
            fields = [('comments/' + identity, item.get('text'))
                      for item in payload.get('comments', []) if item['id'] == identity]
        elif kind == 'comment_reason':
            fields = [('comment_outcomes/' + str(index), item.get('reason'))
                      for index, item in enumerate(payload.get('comment_outcomes', []))
                      if item['comment_id'] == identity]
        elif kind in {'verification', 'verification_basis'}:
            fields = [('verification_matrix/' + str(index),
                       item.get('reason', item.get('method')) if kind == 'verification_basis'
                       else item.get('method'))
                      for index, item in enumerate(payload.get('verification_matrix', []))
                      if item['id'] == identity]
        elif kind in {'compilation_note', 'note_section'}:
            fields = [('compilation_note/sections/' + str(index), item.get('body'))
                      for index, item in enumerate(payload.get('compilation_note', {}).get('sections', []))
                      if item['id'] == identity]
        if kind == 'clause':
            continue
        result[row['binding_id']] = []
        for location in row['final_locations']:
            if location['actual_text_state'] != 'literal_span_verified':
                continue
            text = location['actual_text']
            for origin, quote in fields:
                if (location['origin'] == origin and isinstance(quote, str) and quote
                        and text.count(quote) == 1):
                    start = text.index(quote)
                    result[row['binding_id']].append({
                        'target_type': kind, 'target_id': identity,
                        'document_role': location['document_role'], 'bookmark': location['bookmark'],
                        'text': text, 'start': start, 'end': start + len(quote)})
    return result


def _project(payload, *, source_verification=None):
    require(type(payload.get('contract_version')) is int and payload['contract_version'] == 2,
            'unsupported_standard_contract_version')
    require_fields(payload, ('project_id', 'version', 'adaptation', 'clauses', 'profile'))
    require_fields(payload['adaptation'], ('organization', 'standard_type', 'domain', 'stage'))
    require(isinstance(payload['clauses'], list) and 0 < len(payload['clauses']) <= 500,
            'standard_clauses_required')
    require(payload.get('delivery_stage', 'draft') in {'draft', 'review_candidate'},
            'standard_delivery_stage_unsupported')
    require('comment_realizations' not in payload, 'standard_realizations_are_derived')
    assessment = standards.closed_loop(payload)
    issues = copy.deepcopy(assessment['issues'])
    source_trace = []
    if source_verification is not None:
        from tools.standard_sources import is_current_verification
        require(is_current_verification(payload, source_verification), 'standard_source_verification_not_current')
        issues.extend(copy.deepcopy(source_verification['issues']))
        source_trace = source_verification['source_trace']
    elif payload.get('source_reports') or payload.get('source_bindings'):
        issues.append({'code': 'source_reports_not_verified', 'scope': 'actual_files_not_read'})
    supported = {'contract_version', 'project_id', 'version', 'adaptation', 'evidence_ids',
                 'sensitivity', 'delivery_stage', 'clauses', 'baseline_clauses', 'profile',
                 'comments', 'comment_outcomes', 'compilation_note', 'verification_matrix',
                 'collection_status', 'collection_evidence', 'participants', 'decisions',
                 'open_items', 'verification_open_items', 'reference_open_items',
                 'profile_open_items', 'material_open_items', 'standard_name', 'baseline_version',
                 'votes', 'ballot_rule', 'presentation', 'external_reference_ids',
                 'external_references', 'reference_bindings', 'source_reports', 'source_bindings',
                 'limitation_reviews', 'terms', 'intake'}
    for field in sorted(set(payload) - supported):
        issues.append({'code': 'standard_package_field_unprojected', 'field': field})
    profile = payload['profile']
    require(isinstance(profile, dict), 'standard_profile_required')
    rendering = profile.get('rendering')
    quality_stage = 'final' if payload.get('delivery_stage') == 'review_candidate' else 'draft'
    verification = payload.get('verification_matrix', [])
    require(isinstance(verification, list), 'standard_verification_matrix_required')
    # 组织规则与验证就绪仅由standards契约判断，编排层不维护第二份规则。
    files, reviews, maps = {}, [], {}
    title = (payload.get('compilation_note', {}).get('standard_name')
             or payload.get('standard_name') or '标准正文候选')
    identity = _block('DocumentIdentity', '标准：' + title + '\n项目：' + payload['project_id']
                      + '\n当前版本：' + payload['version']
                      + '\n基线版本：' + str(payload.get('baseline_version', '未提供')))
    blocks = [_block('StandardTitle', title, heading=True, origin='compilation_note.standard_name'), identity]
    clause_blocks, clause_locations, default_outline = _outline(payload, issues)
    blocks.extend(clause_blocks)
    if payload.get('external_references'):
        blocks.append(_block('ExternalReferencesHeading', '外部引用登记（适用性另核）', heading=True))
        for reference in payload['external_references']:
            blocks.append(_block(_identifier('Reference', reference['id']),
                reference['identifier'] + ' — ' + reference['edition'] + ' ' + reference['title'],
                origin='external_references/' + reference['id']))
    blocks = _profile_fields(blocks, rendering)
    raw, review = _document('standard', blocks, rendering, stage=quality_stage)
    files['body/standard.docx'] = raw
    reviews.append(review)
    maps['standard'] = blocks
    realizations = _realizations(payload, sha256_bytes(raw), assessment)
    files['internal/realizations.json'] = canonical_bytes(realizations) + b'\n'
    references = [{'clause_id': clause['id'], 'references': clause.get('references', []),
                   'source': clause.get('source'), 'verification': 'caller_records_not_independently_verified'}
                  for clause in payload['clauses']]
    files['internal/reference-list.json'] = canonical_bytes(references) + b'\n'
    note = payload.get('compilation_note')
    blocks = [_block('NoteTitle', '编制说明（内部审阅候选）', heading=True), identity]
    if not note:
        blocks.append(_block('NoteMissing', '未提供编制说明；本件记录缺件，不构成完整说明。'))
    else:
        sections = note.get('sections', [])
        order = {key: index for index, key in enumerate(profile.get('required_sections', []))}
        ordered = sorted(enumerate(sections), key=lambda pair: order.get(pair[1]['id'], len(order)))
        for index, section in ordered:
            blocks.append(_block(f'NoteHeading{index}', section.get('heading') or section['id'], heading=True))
            blocks.append(_block(f'NoteBody{index}', section.get('body') or '本节未提供实质内容，需责任人补证。',
                                 origin='compilation_note/sections/' + str(index)))
            fields = {key: value for key, value in section.items() if key not in {'id', 'body', 'heading'}}
            labels = {'state': '记录状态', 'owner': '责任人', 'source': '依据定位',
                      'inference_basis': '推论依据', 'review_required': '需复核',
                      'reason': '不适用理由', 'question': '待解决问题', 'recovery': '恢复条件',
                      'blocks': '阻塞阶段', 'open_items': '本节未决', 'outcome_tally': '意见统计',
                      'verification_summary': '验证概要'}
            if fields:
                blocks.append(_block(f'NoteState{index}', _record_text(fields, labels)))
        extras = {key: value for key, value in note.items() if key not in {
            'standard_name', 'version', 'profile_id', 'profile_hash', 'clause_digest', 'sections'}}
        if extras:
            blocks.append(_block('NoteSupplement', '编制说明补充记录：\n' + _record_text(extras, {})))
    blocks.extend([_block('DerivedTally', '意见统计：' + _text(assessment['outcome_tally'])),
                   _block('DerivedOpenItems', '未决事项：' + _text(assessment['open_items']))])
    maps['compilation_note'] = blocks
    blocks = [_block('CommentTitle', '意见汇总处理表（内部审阅候选）', heading=True), identity]
    table_profile = documents.table_template_profile('dyz-comment-six-column-v1')
    summary = [[column['header'] for column in table_profile['columns']]]
    for index, comment in enumerate(payload.get('comments', []), 1):
        outcome = next((row for row in payload.get('comment_outcomes', [])
                        if row['comment_id'] == comment['id']), {})
        targets = comment.get('clause_ids', [comment['clause_id']] if 'clause_id' in comment else [])
        location = '、'.join(clause_locations[key]['display_number'] for key in targets if key in clause_locations)
        summary.append([str(index), location or '文档级／待定位', f'原文见第{index}项',
            outcome.get('outcome', 'missing'), f'理由见第{index}项', f'落实见第{index}项'])
    if len(summary) > 1:
        table = _table('CommentSummary', summary, 'comments/comment_outcomes')
        table['table_profile'] = table_profile['profile_id']
        blocks.append(table)
    by_comment, by_realization = {}, {}
    for row in payload.get('comment_outcomes', []):
        by_comment.setdefault(row['comment_id'], []).append(row)
    for row in realizations:
        by_realization.setdefault(row['comment_id'], []).append(row)
    comment_labels = {'id': '意见编号', 'seq': '序号', 'text': '原意见全文', 'source': '依据来源',
        'participant_id': '提出者记录', 'version': '所针对版本', 'clause_id': '稳定条款ID',
        'clause_ids': '稳定条款ID集合', 'scope': '意见范围', 'origin': '提出单位与代表范围',
        'suggestion': '修改建议'}
    decision_labels = {'comment_id': '原意见编号', 'outcome': '处置结果', 'classification': '分类',
        'reason': '完整处理理由', 'reason_source': '理由依据', 'decision_status': '决定状态',
        'changes': '拟议增删改全文', 'proposed_text': '拟改全文', 'no_change': '无需改文声明',
        'accepted_part': '采纳部分', 'rejected_part': '未采纳部分', 'rejected_reason': '未采纳理由',
        'impact': '逐项影响（verification／references／compilation_note／downstream_products）',
        'major_change': '重大变更', 'unresolved_item': '未决事项', 'owner': '责任人',
        'confirmation': '本次确认记录', 'confirmation_history': '历史确认记录',
        'decision_by': '决定记录者', 'decision_source': '决定依据', 'decision_version': '决定版本'}
    for index, comment in enumerate(payload.get('comments', []), 1):
        blocks.extend([_block(f'CommentHeading{index}', '意见 ' + comment['id'], heading=True),
                       _block(f'CommentOriginal{index}', _record_text(comment, comment_labels),
                              origin='comments/' + comment['id'])])
        for outcome_index, outcome in enumerate(payload.get('comment_outcomes', [])):
            if outcome['comment_id'] == comment['id']:
                blocks.append(_block(f'CommentOutcome{index}_{outcome_index}',
                    _record_text(outcome, decision_labels), origin='comment_outcomes/' + str(outcome_index)))
        if comment['id'] not in by_comment:
            blocks.append(_block(f'CommentMissing{index}', '尚无处置记录，不构成已采纳。'))
        realized = by_realization.get(comment['id'], [])
        blocks.append(_block(f'CommentRealization{index}',
            '实际落地（仅核文字或结构，专业与决定权限另审）：' + _text([
                {key: row[key] for key in ('comment_id', 'status', 'changes', 'no_change')}
                for row in realized] or {'state': 'not_applicable_or_unverified'})
            + '\n完整字节绑定及核对记录见 internal/realizations.json。'))
    for outcome_index, outcome in enumerate(payload.get('comment_outcomes', [])):
        if outcome['comment_id'] not in {row['id'] for row in payload.get('comments', [])}:
            blocks.append(_block('OrphanOutcome' + str(outcome_index),
                '未找到原意见的处置记录：' + _record_text(outcome, decision_labels),
                origin='comment_outcomes/' + str(outcome_index)))
    blocks.append(_block('CommentTally', '统计：' + _text(assessment['outcome_tally'])))
    if 'ballot_governance' in assessment:
        blocks.append(_block('BallotGovernance', '表决记录核查（不构成组织批准）：' + _text({
            'ballot_assessment': assessment['ballot_assessment'],
            'valid_vote_counts': assessment['valid_vote_counts'],
            'ballot_governance': assessment['ballot_governance']}), origin='votes/ballot_rule'))
    maps['comment_disposition'] = blocks
    blocks = [_block('VerificationTitle', '要求—方法—判定矩阵（内部审阅候选）', heading=True), identity]
    if verification:
        cells = [['记录编号', '状态', '条款及方法']]
        for index, row in enumerate(verification, 1):
            cells.append([str(row.get('id') or index), str(row.get('status') or 'unknown'), f'见第{index}项完整记录'])
        blocks.append(_table('VerificationSummary', cells, 'verification_matrix'))
    for index, row in enumerate(verification, 1):
        location = clause_locations.get(row.get('clause_id'), {}).get('display_number', '待定位')
        blocks.append(_block(f'VerificationHeading{index}', f'验证记录 {index} — 条款{location}', heading=True))
        labels = {'id': '记录编号', 'clause_id': '稳定条款ID', 'clause_hash': '条款版本绑定',
                  'method': '验证方法', 'status': '计划／执行／审阅状态', 'source': '方法依据',
                  'execution_evidence': '执行证据', 'result_evidence': '结果证据',
                  'review_evidence': '审阅证据', 'reason': '理由', 'applicability_source': '适用性依据'}
        blocks.append(_block(f'Verification{index}', _record_text(row, labels),
                             origin='verification_matrix/' + str(index - 1)))
    if not verification:
        blocks.append(_block('VerificationMissing', '未提供验证矩阵；没有实际验证完成的证据。'))
    maps['verification_matrix'] = blocks
    for role in ROLES[1:4]:
        maps[role] = _profile_fields(maps[role], rendering)
        raw, review = _document(role, maps[role], rendering, stage=quality_stage)
        files[f'body/{role}.docx'] = raw
        reviews.append(review)
    for review in reviews:
        for problem in review['quality'].get('issues', []):
            issues.append({'code': 'standard_document_quality', 'role': review['role'], 'detail': problem})
    # 只回读原条款书签；附加条件/例外块不能掩盖实际条款的遗漏或冲突。
    from tools.document_review import review_docx
    from tools.standard_review import assess
    actual_documents = {role: review_docx(files['body/' + role + '.docx'])['current']
                        for role in ROLES[:4]}
    body = actual_documents['standard']
    by_bookmark = {}
    for record in body['bookmarks']:
        by_bookmark.setdefault(record['name'], []).append(record)
    actual_texts = {}
    for clause_id, location in clause_locations.items():
        records = by_bookmark.get(location['bookmark'], [])
        if (len(records) == 1 and records[0]['identity_state'] == 'paired_unique_name'
                and records[0]['text_state'] == 'literal_span'):
            actual_texts[clause_id] = records[0]['text']
    located_trace = _trace_locations(payload, source_trace, maps, actual_documents)
    finite = assess(payload, actual_texts=actual_texts, source_verification=source_verification,
                    actual_blocks=_actual_source_blocks(payload, located_trace))
    body_hash = sha256_bytes(files['body/standard.docx'])
    finite['actual_document'] = {'role': 'standard', 'sha256': body_hash,
        'scope': 'unique_paired_original_clause_bookmarks_only'}
    for check in finite['limitation_checks']:
        location = (clause_locations.get(check['target_id'])
                    if check.get('target_type', 'clause') == 'clause' else None)
        if location is not None:
            check['final_location'] = {**location, 'document_sha256': body_hash,
                                      'page': None, 'page_status': 'not_generated'}
    pure_issue_hashes = {digest(row) for row in assessment['finite_review']['issues']}
    issues = [row for row in issues if digest(row) not in pure_issue_hashes]
    known = {digest(row) for row in issues}
    issues.extend(row for row in finite['issues'] if digest(row) not in known)
    assessment['finite_review'] = finite
    assessment['pending_reviews'] = copy.deepcopy(finite['pending_reviews'])
    pending_summary = _pending_reader_text(finite['pending_reviews'])
    if finite['pending_reviews']:
        for role in ROLES[1:4]:
            maps[role].append(_block('FiniteSemanticPending',
                pending_summary,
                origin='assessment/pending_reviews'))
            raw, review = _document(role, maps[role], rendering, stage=quality_stage)
            files['body/' + role + '.docx'] = raw
            reviews = [item for item in reviews if item['role'] != role] + [review]
            actual_documents[role] = review_docx(raw)['current']
            issues = [item for item in issues if not
                      (item.get('code') == 'standard_document_quality' and item.get('role') == role)]
            issues.extend({'code': 'standard_document_quality', 'role': role, 'detail': problem}
                          for problem in review['quality'].get('issues', []))
    assessment['issues'] = copy.deepcopy(issues)
    maps['review_report'] = [_block('ReviewTitle', '实际文件审查报告（内部审阅候选）', heading=True), identity,
                            _block('ReviewScope', '覆盖此前四件由本工具生成的DOCX。页面视觉、自然语言技术正确性和专业签核均未执行。'),
                            _block('ReviewIssues', '确定性检查问题：' + _text(issues)),
                            _block('ReviewFiniteScope', '有限正文规则核对：' + _text(finite['coverage'])
                                   + '\n机器核对不等于任意自然语言技术正确性或专业签核。'),
                            _block('ReviewSemanticPending', pending_summary, origin='assessment/pending_reviews'),
                            _block('ReviewOpenItems', '待审事项（按来源记录保留，不代表已完成审阅）：'
                                   + _text(assessment['open_items']), origin='open_items'),
                            _block('ReviewChecks', '实际回读：' + _text([
                                {'role': item['role'],
                                 'quality_status': item['quality']['status'],
                                 'visual_review': item['visual_review'],
                                 'semantic_fidelity': item['semantic_fidelity']}
                                for item in reviews])),
                            _block('ReviewDetails', '逐项机器检查及定位保留于 internal/checks.json；本报告不包含自身hash，外部清单在生成后固定五件字节。')]
    if issues:
        review_profile = documents.table_template_profile('dyz-comment-three-column-v1')
        rows = [[column['header'] for column in review_profile['columns']]]
        for index, issue in enumerate(issues, 1):
            key = issue.get('record_id', issue.get('clause_id'))
            location = clause_locations.get(key, {}).get('display_number', '详见问题记录')
            rows.append([str(location), f'核对第{index}项依据及受影响记录', f'问题{index}：{issue.get("code", "needs_review")}'])
        table = _table('ReviewSummary', rows, 'assessment/issues')
        table['table_profile'] = review_profile['profile_id']
        maps['review_report'].insert(2, table)
        for index, issue in enumerate(issues, 1):
            maps['review_report'].append(_block('ReviewIssue' + str(index),
                '问题' + str(index) + '完整记录（内部确定性检查；需责任人复核）：\n' + _text(issue),
                origin='assessment/issues/' + str(index - 1)))
    for collection in ('open_items', 'verification_open_items', 'reference_open_items',
                       'profile_open_items', 'material_open_items'):
        for index, item in enumerate(payload.get(collection, [])):
            maps['review_report'].append(_block(_identifier('Pending', [collection, index]),
                '未决详情：' + _text(item), origin=collection + '/' + str(index)))
    located_trace = _trace_locations(payload, source_trace, maps, actual_documents)
    by_binding = {row['binding_id']: row for row in located_trace}
    # 待审摘要追加后文书字节变化，业务书签文字不变；绑定最终实物hash而不覆盖有限核稿结论。
    for records in (finite['nonclause_final_text_checks'], finite['limitation_checks'],
                    finite['pending_reviews']):
        for record in records:
            source = by_binding.get(record.get('binding_id'))
            if source is None:
                continue
            locations = record.get('actual_locations', [])
            if record.get('actual_location'):
                locations = [*locations, record['actual_location']]
            for location in locations:
                final = next((item for item in source['final_locations']
                              if item['document_role'] == location['document_role']
                              and item['bookmark'] == location['bookmark']), None)
                if final is not None:
                    location.update(document_sha256=final['document_sha256'],
                        page=None, page_status='not_generated',
                        actual_text_state=final['actual_text_state'])
    assessment['pending_reviews'] = copy.deepcopy(finite['pending_reviews'])
    for block in maps['review_report']:
        if block['id'] == 'ReviewSemanticPending':
            block['text'] = pending_summary
            block['text_sha256'] = sha256_bytes(block['text'].encode('utf-8'))
    for index, row in enumerate(located_trace, 1):
        maps['review_report'].append(_block('SourceTrace' + str(index),
            '来源追溯 ' + str(index) + '：' + row['target_type'] + '/' + row['target_id']
            + '\n命题：' + row['proposition'] + '\n引文：' + '、'.join(row['citation_ids'])
            + '\n原件页段：\n' + _source_citation_reader_text(row['citations'])
            + '\n字面绑定：' + row['literal_binding'] + '\n覆盖：' + row['coverage']
            + '\n命题支持：' + row['proposition_support'] + '\n目标与位置：' + _text([
                {key: location[key] for key in ('document_role', 'bookmark', 'display_number', 'origin')
                 if key in location} for location in row['final_locations']]),
            origin='source_trace/' + row['binding_id']))
    coverage = _projection_coverage(payload, maps)
    maps['review_report'] = _profile_fields(maps['review_report'], rendering)
    raw, report_review = _document('review_report', maps['review_report'], rendering, stage=quality_stage)
    files['body/review_report.docx'] = raw
    reviews.append(report_review)
    for problem in report_review['quality'].get('issues', []):
        issues.append({'code': 'standard_document_quality', 'role': 'review_report', 'detail': problem})
    files['internal/input.json'] = canonical_bytes(payload) + b'\n'
    files['internal/source-map.json'] = canonical_bytes({'input_hash': digest(payload), 'documents': maps,
        'clause_locations': clause_locations, 'default_outline': default_outline,
        'outline_scope': 'internal_default' if default_outline else 'explicit_presentation'}) + b'\n'
    files['internal/projection-coverage.json'] = canonical_bytes(coverage) + b'\n'
    files['internal/source-trace.json'] = canonical_bytes(located_trace) + b'\n'
    files['internal/checks.json'] = canonical_bytes({'documents': reviews, 'issues': issues,
        'finite_review': finite, 'pending_reviews': finite['pending_reviews']}) + b'\n'
    return assessment, files, issues


def _manifest(payload, mode, files, issues, *, pending_reviews=()):
    return {'generator': 'dyz-standards-delivery', 'generator_version': VERSION,
            'assessment_version': ASSESSMENT_VERSION,
            'rendering_profile': payload['profile'].get('rendering'),
            'rendering_profile_hash': documents.document_profile(payload['profile'].get('rendering'))['hash'],
            'contract_version': 2, 'project_id': payload['project_id'], 'version': payload['version'],
            'input_hash': digest(payload), 'mode': mode, 'profile_hash': digest(payload['profile']),
            'status': 'needs_evidence' if issues else 'needs_review',
            'delivery_state': 'internal_draft_needs_evidence' if issues else
                              'internal_draft_needs_review' if pending_reviews else
                              'ready_for_professional_review' if payload.get('delivery_stage') == 'review_candidate'
                              else 'internal_draft',
            'issues': issues, 'pending_reviews': list(pending_reviews), 'files': [{'path': name, 'bytes': len(raw), 'sha256': sha256_bytes(raw)}
                                       for name, raw in sorted(files.items())],
            'machine_checks': {'status': 'completed_with_issues' if issues else 'completed_no_issues',
                               'scope': 'v2_contract_generated_docx_bytes_and_finite_clause_rules',
                               'finite_clause_review': 'performed',
                               'semantic_pending_count': len(pending_reviews),
                               'natural_language_correctness': 'not_performed'},
            'professional_attestations': 'not_obtained', 'organization_records': 'not_verified',
            'visual_review': 'not_performed', 'pdf': 'not_generated',
            'professional_review': 'not_performed', 'official_status': 'not_asserted',
            'external_action': 'not_performed', 'identity_verification': 'caller_responsibility',
            'filesystem_isolation': 'caller_exclusive_root_required_not_os_sandbox',
            'disclosure_scope': 'internal_candidate_not_an_approved_external_package'}


def prepare(root, payload, output, *, synthetic=False, admission=None):
    """输出新目录；所有业务内容来自载荷，缺证保留为内部候选而不伪造完整性。"""
    base, target, mode = _admit(root, payload, output, synthetic=synthetic, admission=admission, write=True)
    require(target.parent.is_dir(), 'output_parent_missing')
    require(not target.exists(), 'output_exists')
    sources = _verify_sources(base, payload, synthetic=synthetic, admission=admission)
    assessment, files, issues = _project(payload, source_verification=sources)
    manifest = _manifest(payload, mode, files, issues, pending_reviews=assessment['pending_reviews'])
    _admit(base, payload, output, synthetic=synthetic, admission=admission, write=True)
    target.mkdir()
    (target / 'body').mkdir()
    (target / 'internal').mkdir()
    # 清单最后写入，失败的半包不会留下“已完成”标志；不覆盖或清除失败现场。
    for name, raw in files.items():
        _admit(base, payload, output, synthetic=synthetic, admission=admission, write=True)
        _plain_path(target / name)
        with safe_path(target, name, must_exist=False).open('xb') as stream:
            stream.write(raw)
    _admit(base, payload, output, synthetic=synthetic, admission=admission, write=True)
    _plain_path(target / 'manifest.json')
    with (target / 'manifest.json').open('xb') as stream:
        stream.write(canonical_bytes(manifest) + b'\n')
    return manifest


def verify(root, payload, output, *, synthetic=False, admission=None):
    """从当前输入重建预期并回查全部实物；不信任被检查包自报的hash或状态。"""
    base, target, mode = _admit(root, payload, output, synthetic=synthetic, admission=admission)
    require(target.is_dir(), 'standard_package_missing')
    _plain_path(target / 'manifest.json', file=True)
    manifest_path = safe_path(target, 'manifest.json')
    require(manifest_path.stat().st_size <= MAX_FILE_BYTES, 'standard_manifest_too_large')
    from tools.core import strict_json_loads
    manifest = strict_json_loads(manifest_path.read_bytes().decode('utf-8'))
    require(isinstance(manifest, dict) and manifest.get('generator_version') == VERSION,
            'standard_generator_version_unsupported_use_frozen_tool_or_new_directory')
    sources = _verify_sources(base, payload, synthetic=synthetic, admission=admission)
    assessment, files, issues = _project(payload, source_verification=sources)
    expected_manifest = _manifest(payload, mode, files, issues,
                                  pending_reviews=assessment['pending_reviews'])
    expected = {**files, 'manifest.json': canonical_bytes(expected_manifest) + b'\n'}
    paths = list(target.rglob('*'))
    for path in paths:
        _plain_path(path, file=path.is_file())
    require({path.relative_to(target).as_posix() for path in paths if path.is_file()} == set(expected),
            'standard_package_members_changed')
    for name, raw in expected.items():
        _admit(base, payload, output, synthetic=synthetic, admission=admission)
        _plain_path(target / name, file=True)
        path = safe_path(target, name)
        require(path.stat().st_size <= MAX_FILE_BYTES and path.read_bytes() == raw,
                'standard_package_content_changed')
    return {**expected_manifest, 'file_hashes_equal': True,
            'manifest_sha256': sha256_bytes(expected['manifest.json'])}


def register_package(ledger, root, payload, output, *, synthetic=False, admission=None):
    """先核实物再登记；当前选择改变会使旧包确认失效，历史快照仍保留。"""
    require(isinstance(ledger, VersionLedger), 'standard_ledger_required')
    checked = verify(root, payload, output, synthetic=synthetic, admission=admission)
    prefix = 'standard/' + digest(payload['project_id'])[:24]
    base_id = prefix + '/base/' + digest(payload.get('baseline_clauses', []))
    decision_id = prefix + '/decisions/' + digest(payload.get('comment_outcomes', []))
    target_id = prefix + '/clauses/' + digest(payload['clauses'])
    ledger.put(base_id, payload.get('baseline_clauses', []))
    ledger.put(decision_id, payload.get('comment_outcomes', []), dependencies=[base_id])
    ledger.put(target_id, payload['clauses'], dependencies=[base_id, decision_id])
    selection_id = prefix + '/selection'
    selection = ledger.put(selection_id, {'input_hash': digest(payload),
        'profile_hash': digest(payload['profile']), 'admission_hash': digest(admission),
        'root': str(Path(root).resolve()), 'output': output,
        'manifest_sha256': checked['manifest_sha256']}, dependencies=[target_id, decision_id])
    package_id = prefix + '/package/' + checked['manifest_sha256']
    ledger.put(package_id, {'manifest_sha256': checked['manifest_sha256'],
        'input_hash': digest(payload), 'status': checked['status'],
        'delivery_state': checked['delivery_state']}, dependencies=[selection_id])
    return {'selection_id': selection_id, 'selection_hash': selection['hash'],
            'package_id': package_id, 'manifest_sha256': checked['manifest_sha256']}


def record_confirmation(ledger, binding, confirmation):
    """仅登记人类明确的内部审阅确认；不是身份认证、专业签核或发送授权。"""
    require(isinstance(ledger, VersionLedger), 'standard_ledger_required')
    require_fields(confirmation, ('id', 'actor_id', 'actor_type', 'authority_evidence',
                                  'stage', 'decision', 'manifest_sha256', 'confirmed_at'))
    require(confirmation['actor_type'] == 'human', 'human_confirmation_required')
    require(confirmation['stage'] == 'internal_review', 'standard_stage_not_supported')
    require(confirmation['decision'] in {'accepted', 'conditional', 'rejected'}, 'standard_confirmation_decision')
    require(parse_time(confirmation['confirmed_at']) <= parse_time(_now()), 'standard_confirmation_in_future')
    selection_id, package_id = binding['selection_id'], binding['package_id']
    require(ledger.is_current(package_id) and ledger.is_current(selection_id)
            and ledger.records[selection_id][-1]['hash'] == binding['selection_hash'],
            'standard_confirmation_binding_stale')
    require(confirmation['manifest_sha256'] == binding['manifest_sha256']
            == ledger.records[package_id][-1]['payload']['manifest_sha256'],
            'standard_confirmation_manifest_changed')
    record_id = selection_id.rsplit('/', 1)[0] + '/confirmation/' + digest(confirmation['id'])
    require(record_id not in ledger.records, 'standard_confirmation_already_recorded')
    ledger.put(record_id, {'kind': 'stage_confirmation', 'event': copy.deepcopy(confirmation),
                          'selection_id': selection_id,
                          'identity_verification': 'caller_responsibility',
                          'professional_review': 'not_performed', 'external_action': 'not_performed'},
               dependencies=[selection_id, package_id])
    return record_id


def confirmation_current(ledger, record_id, root, payload, output, *, synthetic=False, admission=None):
    checked = verify(root, payload, output, synthetic=synthetic, admission=admission)
    require(record_id in ledger.records, 'standard_confirmation_missing')
    record = ledger.records[record_id][-1]['payload']
    require(record.get('kind') == 'stage_confirmation', 'standard_confirmation_kind')
    selection = ledger.records[record['selection_id']][-1]['payload']
    return (ledger.is_current(record_id)
            and selection['admission_hash'] == digest(admission)
            and selection['root'] == str(Path(root).resolve())
            and selection['output'] == output
            and selection['input_hash'] == digest(payload)
            and record['event']['manifest_sha256'] == checked['manifest_sha256'])
