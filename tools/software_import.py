"""把获准新稿映射到既有prepare；旧包和原始修订文件保持只读。"""
from __future__ import annotations

import copy
from pathlib import Path

from . import core, software_revision


def import_manual(root, payload, allowed, *, check_access):
    """读取固定hash新稿；PNG必须另有逐项授权及原截图证据，不能由Word隐式授予。"""
    request = copy.deepcopy(payload)
    revision = request.pop('manual_revision')
    core.require(isinstance(revision, dict)
                 and set(revision) <= {'path', 'sha256', 'format', 'document_metadata'}
                 and {'path', 'sha256', 'format'} <= revision.keys(), 'revision_request_invalid')
    path, expected, format_name = revision['path'], revision['sha256'], revision['format']
    core.require(format_name in {'markdown', 'docx'}, 'revision_format_invalid')
    core.require(path in allowed and allowed[path] == expected, 'revision_not_authorized')
    source = core.safe_path(root, path)
    core.require(source.suffix.lower() in ({'.md', '.markdown'} if format_name == 'markdown' else {'.docx'}),
                 'revision_extension_mismatch')
    check_access()
    with source.open('rb') as stream:
        raw = stream.read(software_revision.MAX_INPUT_BYTES + 1)
    core.require(len(raw) <= software_revision.MAX_INPUT_BYTES, 'revision_input_size')
    core.require(core.sha256_bytes(raw) == expected, 'revision_snapshot_changed')
    try:
        parsed = (software_revision.parse_markdown(raw.decode('utf-8')) if format_name == 'markdown'
                  else software_revision.parse_docx(raw))
    except UnicodeError:
        raise core.ContractError('revision_invalid_unicode') from None
    options = request.get('delivery', {})
    literals = options.get('sensitive_literals', [])
    core.require(isinstance(literals, list) and all(isinstance(value, str) and value for value in literals),
                 'invalid_sensitive_literals')
    # 对全稿而非首尾选页扫描；差异/页眉也不得成为敏感字面值的输出旁路。
    serialized = core.canonical_bytes({key: value for key, value in parsed.items() if key != 'images'}).decode('utf-8')
    core.require(not any(value in serialized for value in literals), 'sensitive_literal_in_revision')
    images = options.get('screenshots', [])
    core.require(isinstance(images, list), 'screenshots_list_required')
    mapped = {}
    for image in parsed['images']:
        candidates = [entry for entry in images if
                      (entry.get('path') == image.get('path') if image.get('png') is None
                       else entry.get('sha256') == core.sha256_bytes(image['png']))]
        core.require(len(candidates) == 1, 'revision_image_authorization_required')
        item = candidates[0]
        core.require(item.get('path') in allowed and allowed[item['path']] == item.get('sha256'),
                     'revision_image_not_authorized')
        image_path = core.safe_path(root, item['path'])
        check_access()
        with image_path.open('rb') as stream:
            image_raw = stream.read(20_000_001)
        core.require(len(image_raw) <= 20_000_000 and core.sha256_bytes(image_raw) == item['sha256'],
                     'revision_image_snapshot_changed')
        from .software_delivery import _png
        _png(image_raw)
        if image.get('png') is not None:
            core.require(image_raw == image['png'], 'revision_image_snapshot_changed')
        mapped[image['image_id']] = item['id']
    for block in parsed['blocks']:
        if block['kind'] == 'image':
            block['image_id'] = mapped[block['image_id']]
            image = next(item for item in images if item['id'] == block['image_id'])
            block['operation_id'] = image['operation_id']
            block['sha256'] = image['sha256']
    previous = request.get('previous_preparation')
    if previous is not None:
        from .software import _artifact
        _artifact(previous, 'software_preparation')
    old_blocks = ((previous or {}).get('manual') or {}).get('blocks', [])
    # 外部新稿自带confirmed注释不构成人工确认；所有导入块必须重新核对。
    for block in parsed['blocks']:
        block['status'] = 'needs_review'
    difference = software_revision.diff_blocks(old_blocks, parsed['blocks'])
    manual = copy.deepcopy(request.get('manual_input') or {})
    manual['blocks'] = parsed['blocks']
    if 'document_metadata' in revision:
        manual['document_metadata'] = revision['document_metadata']
    metadata = request['scope_input']['metadata']
    old_metadata = ((previous or {}).get('scope') or {}).get('metadata', {})
    metadata_changes = {key: {'before': old_metadata.get(key), 'after': metadata.get(key)}
                        for key in ('software_id', 'name', 'version')
                        if old_metadata and old_metadata.get(key) != metadata.get(key)}
    manual['revision'] = {'input': {'path': path, 'sha256': expected, 'format': format_name},
                          'parser_metadata': parsed['metadata'], 'difference': difference,
                          'metadata_changes': metadata_changes,
                          'previous_manual_binding': ((previous or {}).get('manual') or {}).get('binding'),
                          'confirmations': 'invalidated_reconfirmation_required',
                          'layout': 'rebuild_required_not_preserved'}
    previous_revision = ((previous or {}).get('manual') or {}).get('revision', {})
    if (previous_revision.get('input') == manual['revision']['input']
            and [{key: value for key, value in block.items()
                  if key not in {'input_binding', 'confirmation'}} for block in old_blocks]
                == manual['blocks'] and not metadata_changes
            and ((previous or {}).get('manual') or {}).get('document_metadata', {})
                == manual.get('document_metadata', {})):
        # 相同稿件重复准入沿用首次差异证据，避免将上一稿绑定不断串成新版本。
        manual['revision'] = copy.deepcopy(previous_revision)
    request['manual_input'] = manual
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
    inspected = {key: value for key, value in request.items() if key != 'delivery'}
    inspected['screenshots'] = images
    core.require(not any(secret in text for text in strings(inspected) for secret in literals),
                 'sensitive_literal_in_revision')
    return request
