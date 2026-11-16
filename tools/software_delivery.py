"""SW-02/04/05到CORE-07的本地候选成品链；不授予外发或专业批准。

完整母本先渲染并检查物理页，再选择首尾页。无转换器或检查失败时仅保留
明确标注的内部全量草稿，不把字符折行、Word分页指令或PDF存在当合规证明。
"""
from __future__ import annotations

import copy
import json
import math
import re
import struct
import subprocess
import tempfile
import unicodedata
import zlib
from datetime import datetime, timezone
from pathlib import Path

from . import core, documents, fidelity, software

VERSION = '1.2'
LEGACY_VERSION = '1.1'
MAX_IMAGE_BYTES = 20_000_000


def _access(context):
    now = datetime.now(timezone.utc).isoformat()
    core.preflight(context['environment'], context['permissions'],
                   sensitivity=context['sensitivity'], purpose=context['purpose'], now=now)
    core.check_permission(context['permissions'], action='local_write', purpose=context['purpose'],
                          recipient='local_tool', now=now)


def build_binding(preparation):
    """只绑定程序构建字节；权属/日期变化不无故使不变截图作废。"""
    return core.digest([{'file_id': row['file_id'], 'sha256': row['sha256']}
                        for row in preparation['source']['manifest'] if row['kind'] == 'source'])


def _wrap(text, columns):
    # 制表符按4列停靠、全角字符按2列估算；实际宽度仍由PDF回读确认。
    chunks, start, width = [], 0, 0
    for index, char in enumerate(text):
        size = 4 - width % 4 if char == '\t' else (0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in {'W', 'F'} else 1)
        if width + size > columns and index > start:
            chunks.append((start, index, text[start:index], width))
            start, width = index, 0
            if char == '\t':
                size = 4
        width += size
    chunks.append((start, len(text), text[start:], width))
    return chunks


def source_pages(lines):
    """全量原行到展示行的一基列映射；不删注释、不补行、不进行首尾抽取。"""
    pages, rows, current = [], [], []
    for line in lines:
        for start, end, text, width in _wrap(line['text'], 78):
            block_id = f'Source_{len(rows) + 1}'
            current.append({'id': block_id, 'kind': 'code', 'text': text})
            rows.append({'block_id': block_id, 'file_id': line['file_id'],
                         'source_line': line['source_line'], 'column_start': start + 1,
                         'column_end': end, 'display_width': width,
                         'planned_page': len(pages) + 1, 'planned_row': len(current)})
            if len(current) == 50:
                pages.append(current)
                current = []
    if current:
        pages.append(current)
    return pages, {'source_lines': len(lines), 'display_rows': len(rows), 'rows': rows,
                   'basis': 'planned_rows_not_physical_page_evidence'}


def select_pages(pages, selection):
    core.require(selection in {'all', 'head_tail'}, 'delivery_selection_invalid')
    count = len(pages)
    return (list(range(count)) if selection == 'all' or count <= 60 else
            list(range(30)) + list(range(count - 30, count)))


def _png(raw):
    core.require(raw.startswith(b'\x89PNG\r\n\x1a\n'), 'screenshot_png_required')
    offset, dimensions, data_seen, ended = 8, None, False, False
    while offset + 12 <= len(raw):
        length = struct.unpack('>I', raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        core.require(end <= len(raw), 'screenshot_png_truncated')
        data = raw[offset + 8:offset + 8 + length]
        crc = struct.unpack('>I', raw[offset + 8 + length:end])[0]
        core.require(zlib.crc32(kind + data) == crc, 'screenshot_png_crc')
        if dimensions is None:
            core.require(kind == b'IHDR' and length == 13, 'screenshot_png_header')
            width, height = struct.unpack('>II', data[:8])
            core.require(0 < width <= 10000 and 0 < height <= 10000 and width * height <= 40_000_000,
                         'screenshot_png_dimensions')
            dimensions = (width, height)
        elif kind == b'IHDR':
            raise core.ContractError('screenshot_png_duplicate_header')
        if kind == b'IDAT':
            data_seen = True
        if kind == b'IEND':
            core.require(length == 0 and end == len(raw), 'screenshot_png_trailing_data')
            ended = True
            break
        # 动画、文本和未知附加块可能携带私密原件或隐藏信息，要求另存静态清洁副本。
        core.require(kind in {b'IHDR', b'IDAT', b'PLTE', b'tRNS', b'sRGB', b'gAMA', b'cHRM', b'pHYs'},
                     'screenshot_png_metadata_unsupported')
        offset = end
    core.require(dimensions is not None and data_seen and ended, 'screenshot_png_incomplete')
    return dimensions


def _screenshots(root, preparation, options, context):
    items = options.get('screenshots', [])
    core.require(isinstance(items, list) and len(items) <= 100, 'screenshots_list_required')
    manual = preparation['manual']
    core.require(not items or manual is not None and manual['mode'] == 'GUI', 'screenshots_require_gui')
    operations = {row['id'] for row in manual['operations']} if manual else set()
    runtime = {row['id'] for row in manual['runtime_evidence'] if row['kind'] == 'screenshot'} if manual else set()
    version = preparation['scope']['metadata']['version']
    images, mappings, issues, ids, paths = [], [], [], set(), set()
    for item in items:
        core.require_fields(item, ('id', 'path', 'sha256', 'version', 'operation_id', 'build_binding',
                                   'capture_evidence', 'local_use_evidence', 'visible_state'))
        core.require(isinstance(item['id'], str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,30}', item['id'])
                     and item['id'] not in ids, 'screenshot_id_invalid')
        ids.add(item['id'])
        core.require(item['id'] in runtime and item['operation_id'] in operations, 'screenshot_operation_mismatch')
        core.require(item['version'] == version, 'screenshot_version_mismatch')
        core.require(item['build_binding'] == build_binding(preparation), 'screenshot_build_changed')
        for key in ('capture_evidence', 'local_use_evidence', 'visible_state'):
            core.require(isinstance(item[key], str) and bool(item[key].strip()), 'screenshot_evidence_required')
        path = core.safe_path(root, item['path'])
        core.require(path not in paths, 'screenshot_duplicate_path')
        paths.add(path)
        _access(context)
        with path.open('rb') as stream:
            raw = stream.read(MAX_IMAGE_BYTES + 1)
        core.require(len(raw) <= MAX_IMAGE_BYTES, 'screenshot_too_large')
        core.require(core.sha256_bytes(raw) == item['sha256'], 'screenshot_hash_changed')
        width, height = _png(raw)
        review = item.get('visual_review', {})
        reviewed = (review.get('status') == 'reviewed' and review.get('sha256') == item['sha256']
                    and bool(review.get('actor')) and bool(review.get('evidence')))
        if not reviewed:
            issues.append('screenshot_visual_review_missing')
        images.append({'id': 'Image_' + item['id'], 'kind': 'image', 'png': raw,
                       'width': width, 'height': height, 'text': item['visible_state'],
                       'operation_id': item['operation_id']})
        mappings.append({**item, 'visual_review_status': 'caller_record_only' if reviewed else 'not_performed',
                         'authenticity': 'not_independently_verified', 'bytes': len(raw)})
    if runtime - ids:
        issues.append('screenshot_missing')
    return images, mappings, issues


def _flow(blocks, *, preserve_metadata=False):
    pages, current, used = [], [], 0
    for block in blocks:
        if block['kind'] == 'image':
            # 与documents的A4图框同尺度；按18.4pt正文行距预估，实页仍须PDF核验。
            scale = min(5940000 / block['width'], 3600000 / block['height'])
            image_rows = math.ceil(scale * block['height'] / 12700 / 18.4)
            caption_rows = sum(len(_wrap(line, 72)) for line in block.get('text', '').split('\n')) if block.get('text') else 0
            cost = image_rows + caption_rows
            parts = [block]
        else:
            width = 52 if block['kind'] == 'heading1' else 60 if block['kind'] == 'heading2' else 72
            pieces = [part for line in block['text'].split('\n') for part in _wrap(line, width)]
            parts = []
            for index, (start, end, text, _) in enumerate(pieces, 1):
                if preserve_metadata:
                    part = {**block, 'id': 'ManualBlock_' + core.digest(block['id'])[:24] + f'_{index}',
                            'text': text, 'source_block_id': block['id'],
                            'source_kind': block['kind'], 'fragment': index,
                            'column_start': start + 1, 'column_end': end}
                    if part['kind'] in {'list', 'table'}:
                        part['kind'] = 'paragraph'
                else:
                    part = {**block, 'id': block['id'] + f'_{index}', 'text': text}
                parts.append(part)
            cost = 1
        for part in parts:
            if used + cost > 30 and current:
                pages.append(current)
                current, used = [], 0
            current.append(part)
            used += cost
    if current:
        pages.append(current)
    return pages


def _manual_pages(preparation, images):
    manual = preparation['manual']
    if manual is None:
        return []
    if 'blocks' in manual:
        blocks, used = [], set()
        by_id = {image['id'].removeprefix('Image_'): image for image in images}
        operations = {row['id'] for row in manual['operations']}
        authored = manual['blocks']
        explicit = {block.get('image_id') for block in authored if block['kind'] == 'image'}

        def append_image(image_id, block=None, owner=None):
            core.require(image_id in by_id, 'manual_image_not_authorized')
            core.require(image_id not in used, 'manual_image_duplicate')
            image = by_id[image_id]
            if block and block.get('operation_id'):
                core.require(block['operation_id'] == image['operation_id'], 'manual_image_operation_mismatch')
            source_id = block['id'] if block else 'Screenshot_' + image_id
            inherited = {key: owner[key] for key in ('evidence_ids', 'status')
                         if owner and key in owner}
            blocks.append({**image, **inherited, **(block or {}), 'png': image['png'],
                           'width': image['width'], 'height': image['height'],
                           'id': 'ManualImage_' + core.digest(source_id)[:24],
                           'source_block_id': source_id, 'source_kind': 'image', 'image_id': image_id})
            used.add(image_id)

        for block in authored:
            if block.get('operation_id'):
                core.require(block['operation_id'] in operations, 'manual_operation_unknown')
            if block['kind'] == 'image':
                append_image(block.get('image_id'), block)
            else:
                blocks.append(copy.deepcopy(block))
                for image_id, image in by_id.items():
                    if (image_id not in used and image_id not in explicit
                            and block.get('operation_id') == image['operation_id']):
                        append_image(image_id, owner=block)
        core.require(used == set(by_id), 'manual_screenshot_unmatched')
        return _flow(blocks, preserve_metadata=True)
    blocks = []
    def add(text, kind='paragraph'):
        blocks.append({'id': f'Manual_{len(blocks) + 1}', 'kind': kind, 'text': text})
    add({'GUI': '界面操作说明', 'CLI': '命令操作说明', 'API': '接口调用说明',
         'embedded': '嵌入式输入输出说明'}[manual['mode']], 'heading1')
    for fact in manual['facts']:
        add(fact['text'])
    for operation in manual['operations']:
        add(operation['id'], 'heading2')
        add('输入：' + operation['input'])
        add('预期输出（不是已执行结果）：' + operation['expected_output'])
        add('失败路径：' + operation['failure'])
        blocks.extend(image for image in images if image['operation_id'] == operation['id'])
    return _flow(blocks)


def _worksheet_pages(preparation, selected_lines):
    blocks = [{'id': 'Worksheet_title', 'kind': 'heading1', 'text': '申请字段工作表（内部候选）'}]
    for index, (key, value) in enumerate(preparation['form'].items(), 1):
        text = '未知，待有据确认' if value is None else json.dumps(value, ensure_ascii=False)
        blocks.append({'id': f'Worksheet_{index}', 'kind': 'paragraph', 'text': key + '：' + text})
    blocks.append({'id': 'Worksheet_selected', 'kind': 'paragraph',
                   'text': '本候选选段的原始源码行数：' + str(selected_lines) + '；不是原创表达或官方程序量认定。'})
    worksheet = preparation.get('worksheet')
    if worksheet:
        def add(text, kind='paragraph'):
            blocks.append({'id': f'WorksheetDetail_{len(blocks) + 1}', 'kind': kind, 'text': text})

        def value_text(value):
            return '未知' if value is None else (value if isinstance(value, str)
                                                else json.dumps(value, ensure_ascii=False))

        def confirmation_text(confirmation):
            if confirmation is None:
                add('独立确认：未提供')
                return
            add('确认记录自报状态：' + confirmation['status'] + '；当前是否采纳以上方处理结果为准')
            for key, label in (('actor', '确认者'), ('role', '角色'), ('evidence_id', '确认依据'),
                               ('candidate_digest', '确认所绑定的候选摘要'),
                               ('input_binding', '确认所绑定的输入摘要')):
                add(label + '：' + value_text(confirmation.get(key)))

        add('字段候选与确认依据', 'heading1')
        add('以下均为调用者记录；来源引用和哈希不认证身份、权属或专业结论。')
        add('本轮字段确认输入绑定：' + worksheet['input_binding'])
        for row in worksheet.get('rows', []):
            add('字段：' + row['field'], 'heading2')
            add('原声明值：' + value_text(row.get('current_value', preparation['form'].get(row['field']))))
            add('候选值：' + value_text(row.get('value')))
            add('当前状态：' + row['status'] + '；来源类别：' + row.get('origin', 'unknown'))
            if 'candidate_status' in row:
                add('候选提出状态：' + row['candidate_status'])
            add('处理结果：' + ('已采纳到表单' if row.get('applied') else '未采纳，保留原声明或未知'))
            if row.get('reason'):
                add('待处理原因：' + row['reason'])
            if row.get('candidate_digest'):
                add('本候选摘要：' + row['candidate_digest'])
            sources = row.get('sources', [])
            if not sources:
                add('候选来源记录：未提供；原声明自带的引用见原声明值')
            for index, source in enumerate(sources, 1):
                add('来源 ' + str(index) + '：' + source.get('path', source.get('evidence_id', '未知')))
                if 'sha256' in source:
                    add('来源文件SHA-256：' + source['sha256'])
                add('来源定位：' + source['locator'])
            confirmation_text(row.get('confirmation'))
        for index, confirmation in enumerate(worksheet.get('unmatched_confirmations', []), 1):
            add('未匹配候选的确认记录 ' + str(index), 'heading2')
            add('处理结果：未采纳，须重新提供同版候选及确认')
            confirmation_text(confirmation)
    return _flow(blocks)


def _text_review(preparation, options):
    """在折行和首尾抽取之前扫原文；报告只留定位，不复制私有待核正文。"""
    manual = preparation['manual'] or {}
    inputs = {
        'metadata': preparation['scope']['metadata'],
        'source': preparation['source']['selected_lines'],
        'manual': {key: manual.get(key, []) for key in ('facts', 'operations', 'runtime_evidence')},
        'worksheet': {'form': preparation['form'], 'worksheet': preparation.get('worksheet')},
        'screenshots': options.get('screenshots', []),
    }
    for key in ('blocks', 'revision', 'document_metadata', 'import_provenance'):
        if key in manual:
            inputs['manual'][key] = manual[key]
    texts, locators = {}, {}

    def collect(value, location):
        if isinstance(value, str):
            key = f'Input_{len(texts) + 1}'
            texts[key], locators[key] = value, location
        elif isinstance(value, dict):
            for key in sorted(value):
                collect(value[key], location + [key])
        elif isinstance(value, list):
            for index, item in enumerate(value):
                collect(item, location + [index])

    collect(inputs, [])
    documents_by_id = {'input': {'role': 'internal', 'version': preparation['binding']}}
    bindings = {key: {'document_id': 'input'} for key in texts}
    report = fidelity.scan_placeholders(texts, documents_by_id, bindings, [])
    issues = [{key: row[key] for key in ('code', 'block_id', 'offset', 'severity')}
              for row in report['issues']]
    # AF-01识别有括号的待核标记；这两个流程令牌另属于正文/内部流程隔离边界。
    for key, text in texts.items():
        for match in re.finditer(r'\b(?:STOP_FOR_USER|NEXT_ACTION)\b', text):
            issues.append({'code': 'internal_workflow_marker', 'block_id': key,
                           'offset': match.start(), 'severity': 'review', 'token': match.group(0)})
    return {
        'status': 'needs_review' if issues else 'checked',
        'checks': ['AF-01:scan_placeholders', 'internal_workflow_tokens'],
        'input_binding': core.digest(inputs), 'issues': issues,
        'locations': {row['block_id']: locators[row['block_id']] for row in issues},
        'coverage': {'scope': 'unwrapped_full_inputs_before_page_selection',
                     'areas': sorted(inputs), 'text_blocks': len(texts),
                     'image_pixels': 'not_checked', 'semantic_secrets': 'not_checked'},
        'stage': 'internal_draft', 'resolutions_authenticated': 'not_performed',
        'professional_review': 'not_performed',
    }


def _plan(root, preparation, options, context):
    _access(context)
    software._artifact(preparation, 'software_preparation')
    for key, kind in (('scope', 'software_scope'), ('rights', 'software_rights'), ('source', 'software_source')):
        software._artifact(preparation[key], kind)
    source = preparation['source']
    core.require(source['pagination']['selection'] == 'all', 'delivery_full_source_required')
    core.require(source['scope_binding'] == preparation['scope']['binding']
                 and source['rights_binding'] == preparation['rights']['binding'], 'delivery_preparation_stale')
    core.require(isinstance(options, dict) and set(options) <= {'selection', 'screenshots', 'sensitive_literals'},
                 'delivery_options_invalid')
    selection = options.get('selection', 'all')
    select_pages([], selection)
    secrets = options.get('sensitive_literals', [])
    core.require(isinstance(secrets, list) and all(isinstance(s, str) and s for s in secrets), 'delivery_secrets_invalid')
    # 扫描未折行的全部正文及元数据，避免折行或表单重复值绕过声明秘密。
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    core.require(not any(secret in text for text in strings(
        {'preparation': preparation, 'screenshots': options.get('screenshots', [])})
        for secret in secrets), 'delivery_sensitive_literal_found')
    images, image_map, issues = _screenshots(root, preparation, options, context)
    if preparation['manual'] is not None:
        software._artifact(preparation['manual'], 'software_manual')
        core.require(preparation['manual']['scope_binding'] == preparation['scope']['binding'], 'delivery_preparation_stale')
        if not preparation['manual']['runtime_evidence']:
            issues.append('runtime_not_verified')
    else:
        issues.append('manual_missing')
    if source['source_coverage']['status'] != 'complete':
        issues.append('source_coverage_incomplete')
    pages, mapping = source_pages(source['selected_lines'])
    if not pages:
        issues.append('no_selected_source')
    for row in preparation['scope']['issues'] + preparation.get('issues', []):
        if row['code'] not in {'public_not_authorized', 'cloud_not_authorized'}:
            issues.append(row['code'])
    consistency = preparation.get('consistency')
    if consistency:
        software._artifact(consistency, 'software_consistency')
        for row in consistency['rows']:
            if not row['matches']:
                issues.append('field_mismatch:' + row['field'])
            if row.get('basis_available') is False:
                issues.append('field_basis_missing:' + row['field'])
    worksheet = preparation.get('worksheet')
    if worksheet and any(row['status'] != 'confirmed' for row in worksheet['rows']):
        issues.append('field_confirmation_pending')
    if any(block.get('status') != 'confirmed' for block in (preparation['manual'] or {}).get('blocks', [])):
        issues.append('manual_block_confirmation_pending')
    if any(not block.get('evidence_ids') for block in (preparation['manual'] or {}).get('blocks', [])):
        issues.append('manual_block_evidence_missing')
    plans = {'source': pages, 'manual': _manual_pages(preparation, images),
             'worksheet': _worksheet_pages(preparation, len(source['selected_lines']))}
    text_review = _text_review(preparation, options)
    issues.extend(row['code'] for row in text_review['issues'])
    return plans, {'source': mapping, 'screenshots': image_map,
                   'text_review': text_review}, sorted(set(issues))


def _tool(value, names):
    if value is None:
        return None
    path = Path(value)
    core.require(path.is_absolute() and path.is_file() and path.name.lower() in names,
                 'delivery_tool_invalid')
    return path.resolve(strict=True)


def _convert(executable, docx, destination):
    with tempfile.TemporaryDirectory(prefix='dyz-software-office-') as profile:
        process = subprocess.run([str(executable), '-env:UserInstallation=' + Path(profile).as_uri(),
                                  '--headless', '--convert-to', 'pdf', '--outdir', str(destination), str(docx)],
                                 capture_output=True, timeout=60,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    pdf = destination / (docx.stem + '.pdf')
    core.require(process.returncode == 0 and pdf.is_file() and pdf.read_bytes().startswith(b'%PDF-'),
                 'pdf_conversion_failed')
    return pdf


def _write(root, target, name, raw, context):
    _access(context)
    path = core.safe_path(root, (target / name).relative_to(root).as_posix(), must_exist=False)
    with path.open('xb') as stream:
        stream.write(raw)


def _serialize_pages(plans):
    return {kind: [[{k: (core.sha256_bytes(v) if k == 'png' else v) for k, v in block.items()}
                    for block in page] for page in pages] for kind, pages in plans.items()}


def _select_documents(plans, mapping, preparation, indices):
    """选中页保留母本页号及块身份；程序原行与文档页分别追溯。"""
    selected_keys = {(row['file_id'], row['source_line']) for row in mapping['source']['rows']
                     if row['planned_page'] - 1 in indices['source']}
    mapping['source'].update(selected_mother_pages=[i + 1 for i in indices['source']],
                             selected_source_lines=len(selected_keys))
    block_rows = [{'layout_block_id': block['id'], 'mother_page': page_number,
                   **{key: value for key, value in block.items()
                      if key not in {'id', 'kind', 'text', 'png', 'width', 'height'}}}
                  for page_number, page in enumerate(plans['manual'], 1) for block in page
                  if 'source_block_id' in block]
    mapping['manual'] = {
        'mother_page_count': len(plans['manual']),
        'selected_mother_pages': [i + 1 for i in indices['manual']],
        'pages': [{'selected_page': number, 'mother_page': index + 1,
                   'block_ids': [block['id'] for block in plans['manual'][index]]}
                  for number, index in enumerate(indices['manual'], 1)],
    }
    if block_rows:
        mapping['manual']['blocks'] = block_rows
    for kind in ('source', 'manual'):
        plans[kind] = [plans[kind][index] for index in indices[kind]]
    plans['worksheet'] = _worksheet_pages(preparation, len(selected_keys))


def _code_snapshot():
    directory = Path(__file__).resolve().parent
    names = {path.name for path in directory.glob('software*.py')}
    names.update({'core.py', 'fidelity.py', 'documents.py', 'cli.py'})
    return [{'file': name, 'sha256': core.sha256_bytes((directory / name).read_bytes())}
            for name in sorted(names) if (directory / name).is_file()]


def _input_snapshot(preparation, options):
    return {'preparation_binding': preparation['binding'],
            'scope_binding': preparation['scope']['binding'],
            'source_binding': preparation['source']['binding'],
            'rights_binding': preparation['rights']['binding'],
            'manual_binding': (preparation.get('manual') or {}).get('binding'),
            'form_binding': core.digest(preparation['form']),
            'confirmation_binding': core.digest(preparation.get('worksheet')),
            'source_files': copy.deepcopy(preparation['source']['manifest']),
            'screenshots': copy.deepcopy(options.get('screenshots', [])),
            'options_binding': core.digest(options)}


def _page_sources(plans, physical):
    return {kind: {'count': len(pages),
                   'basis': 'rendered' if physical.get(kind, {}).get('status') == 'checked' else 'estimated',
                   'physical_review': 'checked' if physical.get(kind, {}).get('status') == 'checked'
                                      else 'not_verified',
                   'native_word': 'not_performed', 'human_confirmed': 'not_performed'}
            for kind, pages in plans.items() if pages}


def _tool_version(tool):
    try:
        process = subprocess.run([str(tool), '--version'], capture_output=True, timeout=5,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if process.returncode == 0:
            text = (process.stdout or process.stderr).decode('utf-8', errors='replace').strip()
            if text:
                return {'status': 'recorded', 'output': text[:2048], 'command': '--version'}
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {'status': 'unavailable', 'command': '--version'}


def build(root, preparation, options, output, *, context, pdf_tool=None, pdf_text_tool=None):
    """受控调用者提供已绑定准备包；仅新建目录，所有状态保持内部待审。"""
    root = Path(root).resolve(strict=True)
    target = core.safe_path(root, output, must_exist=False)
    core.require(target.parent.is_dir() and not target.exists(), 'output_exists')
    executable = _tool(pdf_tool, {'soffice', 'soffice.exe', 'soffice.com'})
    text_tool = _tool(pdf_text_tool, {'pdftotext', 'pdftotext.exe'})
    core.require(executable is not None or text_tool is None, 'pdf_converter_required')
    plans, mapping, issues = _plan(root, preparation, options, context)
    metadata = preparation['scope']['metadata']
    title, version = metadata['name'], metadata['version']
    # 所有内容/图片校验成功后才占用输出目录，拒绝时不留下可能误用的正文。
    # 在创建目录前验证所有候选部件，非法XML/图片不留下半套正文。
    for kind, pages in plans.items():
        if pages:
            documents.make_software_docx(pages, title=title, version=version, kind=kind)
    _access(context)
    target.mkdir()
    (target / 'body').mkdir()
    (target / 'internal').mkdir()
    selection = options.get('selection', 'all')
    indices = {kind: list(range(len(plans[kind]))) for kind in ('source', 'manual')}
    applied = {kind: ('not_applicable' if not plans[kind] else
                     'all' if selection == 'all' else 'all_pending_physical_validation')
               for kind in indices}
    physical, generated, failed = {}, [], False
    for kind in ('source', 'manual'):
        pages = plans[kind]
        if not pages:
            continue
        stem = 'mother' if kind == 'source' else 'manual-mother'
        report_key = 'mother' if kind == 'source' else 'manual_mother'
        pending = ('physical_selection_not_verified' if kind == 'source'
                   else 'physical_manual_selection_not_verified')
        if selection == 'head_tail':
            issues.append(pending)
        if not (executable and text_tool):
            continue
        from .software_layout import inspect_pdf
        mother = documents.make_software_docx(pages, title=title, version=version, kind=kind)
        documents.inspect_software_docx(mother, pages, title=title, version=version, kind=kind)
        _write(root, target, f'internal/{stem}.docx', mother, context)
        try:
            _access(context)
            pdf = _convert(executable, target / f'internal/{stem}.docx', target / 'internal')
            _access(context)
            physical[report_key] = inspect_pdf(pdf, pages, kind=kind, title=title,
                                               version=version, pdf_text_tool=str(text_tool))
            if physical[report_key]['status'] == 'checked':
                indices[kind] = select_pages(pages, selection)
                if selection == 'head_tail':
                    applied[kind] = 'head_tail_from_verified_physical_mother'
                    issues.remove(pending)
            else:
                issues.append('physical_' + report_key + '_failed')
        except (OSError, subprocess.TimeoutExpired, core.ContractError, ValueError):
            physical[report_key] = {'status': 'blocked', 'issues': ['pdf_conversion_or_inspection_failed']}
            issues.append('physical_' + report_key + '_failed')
            failed = True
    _select_documents(plans, mapping, preparation, indices)
    for kind, pages in plans.items():
        if not pages:
            continue
        raw = documents.make_software_docx(pages, title=title, version=version, kind=kind)
        documents.inspect_software_docx(raw, pages, title=title, version=version, kind=kind)
        _write(root, target, f'body/{kind}.docx', raw, context)
        _write(root, target, f'body/{kind}.txt', ('\n'.join(block.get('text', '') for page in pages for block in page) + '\n').encode('utf-8'), context)
        if executable:
            try:
                _access(context)
                pdf = _convert(executable, target / f'body/{kind}.docx', target / 'body')
                generated.append(kind)
                if text_tool:
                    from .software_layout import inspect_pdf
                    _access(context)
                    physical[kind] = inspect_pdf(pdf, pages, kind=kind, title=title,
                                                version=version, pdf_text_tool=str(text_tool))
                    if physical[kind]['status'] != 'checked':
                        issues.append('physical_' + kind + '_failed')
            except (OSError, subprocess.TimeoutExpired, core.ContractError, ValueError):
                failed = True
                issues.append('pdf_conversion_failed')
    if not executable:
        issues.append('pdf_not_generated')
    if not text_tool:
        issues.append('physical_layout_not_checked')
    mapping['document_pages'] = _serialize_pages(plans)
    files = {'internal/source-map.json': mapping, 'internal/preparation.json': preparation,
             'internal/physical-review.json': physical}
    for name, content in files.items():
        _write(root, target, name, core.canonical_bytes(content) + b'\n', context)
    manifest = {'kind': 'software_delivery', 'generator_version': VERSION,
                'preparation_binding': preparation['binding'], 'options_binding': core.digest(options),
                'status': 'partial' if issues else 'needs_review', 'issues': sorted(set(issues)),
                'selection_requested': selection, 'selection_applied': applied['source'],
                'selected_mother_pages': [index + 1 for index in indices['source']],
                'manual_selection_applied': applied['manual'],
                'manual_selected_mother_pages': [index + 1 for index in indices['manual']],
                'pdf': 'failed' if failed else 'generated_needs_review' if generated else 'not_generated',
                'pdf_documents': generated, 'physical_review': physical,
                'text_review': mapping['text_review'],
                'visual_review': 'not_performed', 'professional_review': 'not_performed',
                'output_scope': 'internal_only_not_for_submission', 'external_action': 'not_performed',
                'official_status': 'not_asserted', 'host_egress': 'not_controlled',
                'identity_verification': 'not_performed', 'tool_bindings': {}, 'files': []}
    manifest.update(code_snapshot=_code_snapshot(), input_snapshot=_input_snapshot(preparation, options),
                    page_sources=_page_sources(plans, physical), tool_versions={})
    for key, tool in (('pdf', executable), ('pdf_text', text_tool)):
        if tool:
            manifest['tool_bindings'][key] = {'name': tool.name, 'sha256': core.sha256_bytes(tool.read_bytes())}
            manifest['tool_versions'][key] = _tool_version(tool)
    for path in sorted(target.rglob('*')):
        if path.is_file():
            _access(context)
            raw = path.read_bytes()
            manifest['files'].append({'path': path.relative_to(target).as_posix(),
                                      'sha256': core.sha256_bytes(raw), 'bytes': len(raw)})
    _write(root, target, 'manifest.json', core.canonical_bytes(manifest) + b'\n', context)
    return manifest


def _export_fields(preparation):
    """只投影已确认的值，不将候选来源、确认者或哈希写入外发正文。"""
    form, worksheet = preparation['form'], preparation.get('worksheet') or {}
    pending = {row['field'] for row in worksheet.get('rows', []) if row['status'] != 'confirmed'}
    fields = {}
    allowed = {'software_id', 'name', 'version', 'completed_date', 'published_date',
               'runtime_environment', 'total_source_lines', 'selected_source_lines'}
    allowed.update(getattr(software, 'FIELD_NAMES', ()))
    for field in sorted(allowed.intersection(form)):
        value = form[field]
        if field in pending or value is None:
            continue
        if isinstance(value, dict):
            # 原声明日期/环境带证据引用，正文只保留可识别值。
            value = value.get('value', value.get('description'))
        if isinstance(value, (str, int, float, bool)) and value != '':
            fields[field] = value
    return fields


def export_package(root, preparation, options, package, output, *, context, approval,
                   pdf_text_tool=None):
    """按具体文件审批复制本地外发候选；不发送、不提交、不代签专业审核。

    approval包含files[{path, sha256}]及recipient/purpose/channel/evidence_id。
    purpose为deposit/public/local_process；context须分别有同用途本地读写和
    向该recipient复制的许可。application-fields.json是可选的确定性值投影。
    """
    core.require(isinstance(approval, dict), 'export_approval_required')
    core.require_fields(approval, ('files', 'recipient', 'purpose', 'channel', 'evidence_id'))
    for key in ('recipient', 'purpose', 'channel', 'evidence_id'):
        core.require(isinstance(approval[key], str) and bool(approval[key].strip()),
                     'export_approval_evidence_required')
    core.require(approval['purpose'] in {'deposit', 'public', 'local_process'}
                 and approval['purpose'] == context['purpose'], 'export_purpose_mismatch')
    _access(context)
    core.check_permission(context['permissions'], action='copy', purpose=approval['purpose'],
                          recipient=approval['recipient'], now=datetime.now(timezone.utc).isoformat())
    checked = verify(root, preparation, options, package, context=context, pdf_text_tool=pdf_text_tool)
    root = Path(root).resolve(strict=True)
    source = core.safe_path(root, package)
    target = core.safe_path(root, output, must_exist=False)
    core.require(target.parent.is_dir() and not target.exists(), 'output_exists')
    core.require(not target.is_relative_to(source), 'export_output_inside_package')
    manifest = core.strict_json_loads((source / 'manifest.json').read_text(encoding='utf-8'))
    core.require(manifest['generator_version'] == VERSION, 'export_current_report_required')
    manual = preparation.get('manual') or {}
    rows = approval['files']
    core.require(isinstance(rows, list) and bool(rows), 'export_files_required')
    selected = {}
    known = {row['path']: row for row in manifest['files']}
    for row in rows:
        core.require(isinstance(row, dict), 'export_file_invalid')
        core.require_fields(row, ('path', 'sha256'))
        name = row['path']
        core.require(isinstance(name, str) and (re.fullmatch(r'body/(?:source|manual)\.(?:txt|docx|pdf)', name)
                     or name == 'application-fields.json'), 'export_file_not_whitelisted')
        core.require(name not in selected, 'export_file_duplicate')
        if name == 'application-fields.json':
            fields = _export_fields(preparation)
            core.require(bool(fields), 'export_confirmed_fields_missing')
            raw = core.canonical_bytes(fields) + b'\n'
        else:
            core.require(name in known, 'export_file_missing')
            raw = core.safe_path(source, name).read_bytes()
            core.require(core.sha256_bytes(raw) == known[name]['sha256'], 'delivery_file_changed')
        core.require(row['sha256'] == core.sha256_bytes(raw), 'export_file_approval_changed')
        selected[name] = raw
    areas = {'metadata'}
    if any(name.startswith('body/source.') for name in selected):
        areas.add('source')
    if any(name.startswith('body/manual.') for name in selected):
        areas.update({'manual', 'screenshots'})
        core.require(all(block.get('status') == 'confirmed' for block in manual.get('blocks', [])),
                     'export_manual_confirmation_pending')
        core.require(all(block.get('evidence_ids') for block in manual.get('blocks', [])),
                     'export_manual_evidence_missing')
    if 'application-fields.json' in selected:
        areas.add('worksheet')
        core.require(not any(code.startswith(('field_mismatch:', 'field_basis_missing:'))
                             for code in checked['issues']), 'export_field_conflict')
    text_review = checked['text_review']
    core.require(not any(text_review['locations'][row['block_id']][0] in areas
                         for row in text_review['issues']), 'export_text_review_unresolved')
    # 许可按实际被复制的源码组件检查；部分/待审不是一个可绕过具体缺件的状态。
    purpose = approval['purpose']
    component_ids = {row['component_id'] for row in preparation['source']['manifest']
                     if row.get('selection_basis') is not None}
    if any(name.startswith('body/manual.') for name in selected):
        component_ids.update(row['id'] for row in preparation['scope']['components'] if row.get('claim'))
    decisions = {row['component_id']: row for row in preparation['rights']['decisions']}
    core.require(all(component in decisions and decisions[component]['permissions'].get(purpose) == 'allow'
                     and bool(decisions[component].get('evidence_ids')) for component in component_ids),
                 'export_rights_not_authorized')
    core.require(not any('not_authorized' in code or code in {
        'scope_issue_unresolved', 'license_or_notice_missing', 'human_contribution_unknown',
        'ownership_conflict', 'baseline_or_exclusion_missing', 'permission_unknown'}
        for decision in decisions.values() for code in decision.get('issues', [])
        if code not in {'public_not_authorized', 'cloud_not_authorized', 'deposit_not_authorized'}),
        'export_rights_unresolved')
    if any(name.startswith('body/source.') for name in selected):
        core.require(preparation['source']['source_coverage']['status'] == 'complete',
                     'export_source_coverage_incomplete')
    if any(name.startswith('body/manual.') for name in selected):
        core.require(bool(manual), 'export_manual_missing')
        # 图片像素和来源独立于正文确认；未有当前图片复核记录不能复制到接收方候选。
        core.require(all(row.get('visual_review_status') == 'caller_record_only'
                         for row in _plan(root, preparation, options, context)[1]['screenshots']),
                     'export_screenshot_review_pending')
    # 复制前再次核对批准字节，避免审批检查后目录被其他本地进程替换。
    for name, raw in selected.items():
        if name in known:
            core.require(core.safe_path(source, name).read_bytes() == raw, 'delivery_file_changed')
    report = {'kind': 'software_export_candidate', 'status': 'needs_review',
              'output_scope': 'local_copy_for_recipient_review',
              'recipient': approval['recipient'], 'purpose': purpose, 'channel': approval['channel'],
              'approval_evidence_id': approval['evidence_id'], 'approval_binding': core.digest(approval),
              'files': [{'path': name, 'sha256': core.sha256_bytes(raw), 'bytes': len(raw)}
                        for name, raw in sorted(selected.items())],
              'page_sources': checked['page_sources'], 'issues': checked['issues'],
              'visual_review': 'not_performed', 'professional_review': 'not_performed',
              'external_action': 'not_performed', 'official_status': 'not_asserted'}
    # 报告只返回给内部调用者；外发目录严格只含批准正文与干净字段结果。
    _access(context)
    target.mkdir()
    if any(name.startswith('body/') for name in selected):
        (target / 'body').mkdir()
    for name, raw in selected.items():
        _write(root, target, name, raw, context)
    return report


def verify(root, preparation, options, output, *, context, pdf_text_tool=None):
    """重建两种完整母本和实际选段；清单状态不代替本次物理页证据。"""
    root = Path(root).resolve(strict=True)
    plans, mapping, issues = _plan(root, preparation, options, context)
    mothers = {kind: plans[kind] for kind in ('source', 'manual')}
    text_tool = _tool(pdf_text_tool, {'pdftotext', 'pdftotext.exe'})
    target = core.safe_path(root, output)
    manifest = core.strict_json_loads((target / 'manifest.json').read_text(encoding='utf-8'))
    selection = options.get('selection', 'all')
    core.require(manifest['kind'] == 'software_delivery' and manifest['generator_version'] in {VERSION, LEGACY_VERSION}
                 and manifest['preparation_binding'] == preparation['binding']
                 and manifest['options_binding'] == core.digest(options)
                 and manifest['selection_requested'] == selection, 'delivery_binding_changed')
    provenance_keys = {'code_snapshot', 'input_snapshot', 'page_sources', 'tool_versions'}
    current_report = manifest['generator_version'] == VERSION or bool(provenance_keys.intersection(manifest))
    if current_report:
        core.require(provenance_keys.issubset(manifest), 'delivery_provenance_incomplete')
        core.require(manifest.get('code_snapshot') == _code_snapshot(), 'delivery_code_changed')
        core.require(manifest.get('input_snapshot') == _input_snapshot(preparation, options),
                     'delivery_input_snapshot_changed')
        core.require(isinstance(manifest.get('tool_versions'), dict)
                     and set(manifest['tool_versions']) == set(manifest['tool_bindings'])
                     and all(isinstance(row, dict) and row.get('command') == '--version'
                             and row.get('status') in {'recorded', 'unavailable'}
                             for row in manifest['tool_versions'].values()),
                     'delivery_tool_versions_changed')
        if text_tool:
            core.require(manifest['tool_bindings'].get('pdf_text') == {
                'name': text_tool.name, 'sha256': core.sha256_bytes(text_tool.read_bytes())},
                'delivery_tool_changed')
            core.require(manifest['tool_versions']['pdf_text'] == _tool_version(text_tool),
                         'delivery_tool_version_changed')
    for key, value in {'visual_review': 'not_performed', 'professional_review': 'not_performed',
                       'output_scope': 'internal_only_not_for_submission', 'external_action': 'not_performed',
                       'official_status': 'not_asserted'}.items():
        core.require(manifest.get(key) == value, 'delivery_state_changed')
    core.require(manifest.get('text_review') == mapping['text_review'], 'delivery_text_review_changed')
    indices, states = {}, {}
    for kind, pages in mothers.items():
        prefix = '' if kind == 'source' else 'manual_'
        states[kind] = manifest[prefix + 'selection_applied']
        chosen = manifest[prefix + 'selected_mother_pages']
        allowed = ({'not_applicable'} if not pages else {'all'} if selection == 'all' else
                   {'all_pending_physical_validation', 'head_tail_from_verified_physical_mother'})
        core.require(states[kind] in allowed, 'delivery_selection_changed')
        expected = (select_pages(pages, selection)
                    if states[kind] == 'head_tail_from_verified_physical_mother'
                    else list(range(len(pages))))
        core.require(isinstance(chosen, list) and all(type(i) is int for i in chosen)
                     and chosen == [i + 1 for i in expected], 'delivery_selection_changed')
        indices[kind] = expected
        report_key = 'mother' if kind == 'source' else 'manual_mother'
        if states[kind] == 'head_tail_from_verified_physical_mother':
            core.require(report_key in manifest['physical_review'], 'delivery_mother_missing')
    _select_documents(plans, mapping, preparation, indices)
    mapping['document_pages'] = _serialize_pages(plans)
    if current_report:
        core.require(manifest.get('page_sources') == _page_sources(plans, manifest['physical_review']),
                     'delivery_page_sources_changed')
    rows = manifest['files']
    names = {row['path'] for row in rows}
    core.require(len(names) == len(rows) and {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()} == names | {'manifest.json'},
                 'delivery_members_changed')
    expected_names = {'internal/source-map.json', 'internal/preparation.json', 'internal/physical-review.json'}
    for kind, pages in plans.items():
        if pages:
            expected_names.update({f'body/{kind}.docx', f'body/{kind}.txt'})
    expected_names.update('body/' + kind + '.pdf' for kind in manifest['pdf_documents'])
    for kind in mothers:
        stem = 'mother' if kind == 'source' else 'manual-mother'
        report_key = 'mother' if kind == 'source' else 'manual_mother'
        if report_key in manifest['physical_review']:
            core.require(bool(mothers[kind]), 'delivery_mother_unexpected')
            expected_names.add(f'internal/{stem}.docx')
            if f'internal/{stem}.pdf' in names:
                expected_names.add(f'internal/{stem}.pdf')
    core.require(names == expected_names, 'delivery_members_changed')
    for row in rows:
        _access(context)
        raw = core.safe_path(target, row['path']).read_bytes()
        core.require(core.sha256_bytes(raw) == row['sha256'] and len(raw) == row['bytes'], 'delivery_file_changed')
    for name, content in (('internal/source-map.json', mapping), ('internal/preparation.json', preparation),
                           ('internal/physical-review.json', manifest['physical_review'])):
        core.require((target / name).read_bytes() == core.canonical_bytes(content) + b'\n', 'delivery_mapping_changed')
    metadata = preparation['scope']['metadata']
    physical, selection_verification = {}, {}
    for kind, pages in mothers.items():
        stem = 'mother' if kind == 'source' else 'manual-mother'
        report_key = 'mother' if kind == 'source' else 'manual_mother'
        pending = ('physical_selection_not_verified' if kind == 'source'
                   else 'physical_manual_selection_not_verified')
        if report_key in manifest['physical_review']:
            documents.inspect_software_docx((target / f'internal/{stem}.docx').read_bytes(), pages,
                                           title=metadata['name'], version=metadata['version'], kind=kind)
            if text_tool and (target / f'internal/{stem}.pdf').is_file():
                from .software_layout import inspect_pdf
                _access(context)
                physical[report_key] = inspect_pdf(target / f'internal/{stem}.pdf', pages,
                    kind=kind, title=metadata['name'], version=metadata['version'], pdf_text_tool=str(text_tool))
            else:
                issues.append('physical_' + report_key + '_not_rechecked')
        if not pages:
            selection_verification[kind] = 'not_applicable'
        elif selection == 'all':
            selection_verification[kind] = 'checked'
        elif (states[kind] == 'head_tail_from_verified_physical_mother'
              and physical.get(report_key, {}).get('status') == 'checked'):
            selection_verification[kind] = 'checked'
        else:
            selection_verification[kind] = 'not_verified'
            issues.append(pending)
    if not text_tool:
        issues.append('physical_layout_not_rechecked')
    for kind, pages in plans.items():
        if not pages:
            continue
        documents.inspect_software_docx((target / f'body/{kind}.docx').read_bytes(), pages,
                                       title=metadata['name'], version=metadata['version'], kind=kind)
        expected_text = '\n'.join(block.get('text', '') for page in pages for block in page) + '\n'
        core.require((target / f'body/{kind}.txt').read_bytes() == expected_text.encode('utf-8'), 'delivery_text_changed')
        if kind not in manifest['pdf_documents']:
            issues.append('pdf_not_generated:' + kind)
        if text_tool and kind in manifest['pdf_documents']:
            from .software_layout import inspect_pdf
            _access(context)
            physical[kind] = inspect_pdf(target / f'body/{kind}.pdf', pages, kind=kind,
                                         title=metadata['name'], version=metadata['version'], pdf_text_tool=str(text_tool))
    return {'status': 'partial' if issues or manifest['status'] == 'partial' or any(
                report['status'] != 'checked' for report in physical.values()) else 'needs_review',
            'file_hashes_equal': True, 'generated_docx_equal': True, 'physical_review': physical,
            'selection_verification': selection_verification, 'issues': sorted(set(issues)),
            'text_review': mapping['text_review'],
            'visual_review': 'not_performed', 'professional_review': 'not_performed',
            'pdf_recheck': 'performed' if physical else 'not_performed',
            'generator_version': manifest['generator_version'],
            'provenance': ('current_code_checked' if current_report
                           else 'legacy_report_without_code_snapshot'),
            'page_sources': _page_sources(plans, physical)}
