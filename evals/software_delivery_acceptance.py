"""本地软件成品验收：合成59/60/61物理页、GUI原图、换版和失败状态。

需要显式已安装LibreOffice及pdftotext；只写新的指定验收目录，不安装/联网。
本脚本的图像是标明的合成像素夹具，不是真实产品运行截图。
"""
from __future__ import annotations
import argparse
import copy
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools import core, documents, software, software_delivery, software_layout
from evals.test_software_delivery import png


def run(output, pdf_tool, pdf_text_tool):
    root = Path(output).resolve()
    core.require(not root.exists() and root.parent.is_dir(), 'new_acceptance_directory_required')
    root.mkdir()
    source_root = Path(__file__).resolve().parents[1]
    bound_names = tuple('tools/' + row['file'] for row in software_delivery._code_snapshot()) + (
        'evals/software_delivery_acceptance.py',)
    source_bindings = {name: core.sha256_bytes((source_root / name).read_bytes()) for name in bound_names}
    (root / 'run-binding.json').write_bytes(core.canonical_bytes(source_bindings) + b'\n')
    fixture = json.loads((Path(__file__).parent / 'fixtures/software/synthetic.json').read_text(encoding='utf-8'))
    now = datetime.now(timezone.utc)
    permission = {'purpose': 'synthetic_acceptance', 'recipient': 'local_tool', 'decision': 'allow',
                  'authority_evidence': 'synthetic-test-only-not-real-authority',
                  'valid_from': (now - timedelta(hours=1)).isoformat(),
                  'valid_until': (now + timedelta(hours=1)).isoformat()}
    context = {'environment': {}, 'sensitivity': 'synthetic', 'purpose': permission['purpose'],
               'now': now.isoformat(), 'permissions': [{**permission, 'action': action}
                                                      for action in ('local_read', 'local_write')]}
    observations, began = [], time.perf_counter()
    for count in (59, 60, 61):
        case = root / f'source-{count}'
        case.mkdir()
        source = ''.join(f'value_{i:04d} = {i}  # 合成源行 <tag> https://example.invalid/a//b\n' for i in range(count * 50))
        (case / 'sample.py').write_text(source, encoding='utf-8')
        payload = {'context': context, 'authorized_root': str(case),
                   'scope_input': fixture['scope_input'], 'rights': fixture['rights'],
                   'files': [{'id': 'f1', 'path': 'sample.py', 'component_id': 'cli', 'kind': 'source', 'include': True}],
                   'inventory_complete': True,
                   'pagination': {'lines_per_page': 50, 'wrap_columns': 78, 'selection': 'all', 'basis': 'synthetic-layout-only'},
                   'manual_input': fixture['manual_input']}
        preparation = software.prepare(payload, use_system_time=True)['artifacts']
        options = {'selection': 'head_tail', 'screenshots': [], 'sensitive_literals': []}
        start = time.perf_counter()
        manifest = software_delivery.build(case, preparation, options, 'pack', context=context,
                                           pdf_tool=pdf_tool, pdf_text_tool=pdf_text_tool)
        core.require(manifest['physical_review']['mother']['status'] == 'checked', 'mother_physical_check_failed')
        core.require(manifest['physical_review']['source']['status'] == 'checked', 'selected_physical_check_failed')
        expected = list(range(1, count + 1)) if count <= 60 else list(range(1, 31)) + list(range(32, 62))
        core.require(manifest['selected_mother_pages'] == expected, 'physical_selection_wrong')
        verified = software_delivery.verify(case, preparation, options, 'pack', context=context,
                                             pdf_text_tool=pdf_text_tool)
        core.require(verified['physical_review']['source']['status'] == 'checked', 'repeat_physical_check_failed')
        observations.append({'case': f'mother-{count}', 'seconds': round(time.perf_counter() - start, 3),
                             'selected_pages': len(expected), 'source_rows': count * 50,
                             'selected_mother_pages': expected, 'status': 'technical_checks_passed',
                             'candidate_status': manifest['status'], 'issues': manifest['issues']})
        if count == 59:
            changed_payload = copy.deepcopy(payload)
            changed_payload['scope_input']['metadata']['published_date'] = None
            changed_payload['previous_preparation'] = preparation
            changed = software.prepare(changed_payload, use_system_time=True)['artifacts']
            core.require(changed['binding'] != preparation['binding'], 'version_change_not_bound')
            core.require(software_delivery.build_binding(changed) == software_delivery.build_binding(preparation),
                         'unchanged_build_invalidated')
            try:
                software_delivery.verify(case, changed, options, 'pack', context=context)
            except core.ContractError:
                observations.append({'case': 'fact-change', 'status': 'old_delivery_rejected_build_unchanged'})
            else:
                raise AssertionError('stale delivery accepted')
    # 文档与程序各有自己的母本，不能用短源码的判断替代长说明书。
    for count in (59, 60, 61):
        case = root / f'manual-{count}'
        case.mkdir()
        (case / 'sample.py').write_text(fixture['source'], encoding='utf-8')
        manual = copy.deepcopy(fixture['manual_input'])
        manual['facts'] = [{
            'id': 'long-manual', 'evidence_id': 'synthetic-manual-only',
            'text': '\n'.join(f'说明第{i + 1:04d}行：此为独立文档分页合成样本。'
                              for i in range(count * 30 - 5)),
        }]
        manual_payload = {**payload, 'authorized_root': str(case), 'manual_input': manual}
        preparation = software.prepare(manual_payload, use_system_time=True)['artifacts']
        options = {'selection': 'head_tail', 'screenshots': [], 'sensitive_literals': []}
        manifest = software_delivery.build(case, preparation, options, 'pack', context=context,
                                           pdf_tool=pdf_tool, pdf_text_tool=pdf_text_tool)
        expected = list(range(1, count + 1)) if count <= 60 else list(range(1, 31)) + list(range(32, 62))
        core.require(manifest['physical_review']['manual_mother']['status'] == 'checked',
                     'manual_mother_physical_check_failed')
        core.require(manifest['physical_review']['manual']['status'] == 'checked',
                     'manual_selected_physical_check_failed')
        core.require(manifest['manual_selected_mother_pages'] == expected, 'manual_physical_selection_wrong')
        core.require(manifest['selected_mother_pages'] == [1], 'short_source_selection_changed')
        verified = software_delivery.verify(case, preparation, options, 'pack', context=context,
                                             pdf_text_tool=pdf_text_tool)
        core.require(verified['physical_review']['manual_mother']['status'] == 'checked'
                     and verified['physical_review']['manual']['status'] == 'checked',
                     'manual_repeat_physical_check_failed')
        observations.append({'case': f'manual-mother-{count}', 'selected_pages': len(expected),
                             'selected_mother_pages': expected, 'status': 'technical_checks_passed',
                             'candidate_status': manifest['status'], 'issues': manifest['issues']})
    case = root / 'gui'
    case.mkdir()
    (case / 'sample.py').write_text(fixture['source'], encoding='utf-8')
    manual = copy.deepcopy(fixture['manual_input'])
    manual['mode'] = 'GUI'
    manual['runtime_evidence'] = [{'id': 'screen', 'version': '1.0', 'kind': 'screenshot',
                                  'evidence_id': 'synthetic-pixel-fixture-not-real-execution'}]
    payload = {**payload, 'authorized_root': str(case), 'manual_input': manual}
    preparation = software.prepare(payload, use_system_time=True)['artifacts']
    image = png()
    (case / 'screen.png').write_bytes(image)
    options = {'selection': 'all', 'sensitive_literals': [], 'screenshots': [
        {'id': 'screen', 'path': 'screen.png', 'sha256': core.sha256_bytes(image), 'version': '1.0',
         'operation_id': 'count', 'build_binding': software_delivery.build_binding(preparation),
         'capture_evidence': 'synthetic-pixel-fixture-not-real-execution',
         'local_use_evidence': 'original-synthetic-pixels', 'visible_state': '合成像素夹具，不是产品运行截图'}]}
    manifest = software_delivery.build(case, preparation, options, 'pack', context=context,
                                       pdf_tool=pdf_tool, pdf_text_tool=pdf_text_tool)
    core.require(manifest['pdf'] == 'generated_needs_review', 'gui_pdf_not_generated')
    verification = software_delivery.verify(case, preparation, options, 'pack', context=context,
                                            pdf_text_tool=pdf_text_tool)
    observations.append({'case': 'gui-original-png', 'status': 'files_verified_visual_review_pending',
                         'candidate_status': manifest['status'], 'issues': manifest['issues'],
                         'physical': verification['physical_review']})
    # 完整正文路径必须实际渲染，不借用旧facts/operations骨架的PDF结论。
    case = root / 'authored-gui'
    case.mkdir()
    (case / 'sample.py').write_text(fixture['source'], encoding='utf-8')
    (case / 'screen.png').write_bytes(image)
    authored_manual = copy.deepcopy(manual)
    authored_manual['blocks'] = [
        {'id': 'Overview', 'kind': 'heading1', 'text': '合成完整正文说明'},
        {'id': 'Detail', 'kind': 'paragraph', 'text': '新增完整正文可在实页定位。先核输入列表，再执行计数。'},
        {'id': 'Steps', 'kind': 'list', 'text': '1. 输入合成数据\n2. 执行计数\n3. 核对预期输出'},
        {'id': 'Code', 'kind': 'code', 'text': 'count([1, 2])\n# static expected: 2'},
        {'id': 'Table', 'kind': 'table', 'text': '输入 | 预期输出\n[1, 2] | 2'},
        {'id': 'Figure', 'kind': 'image', 'image_id': 'screen', 'operation_id': 'count',
         'text': '合成像素夹具，不是产品运行截图'},
    ]
    for block in authored_manual['blocks']:
        block.update(evidence_ids=['synthetic-authored-evidence'], status='confirmed')
    authored_payload = {**payload, 'authorized_root': str(case), 'manual_input': authored_manual}
    preparation = software.prepare(authored_payload, use_system_time=True)['artifacts']
    options['screenshots'][0]['build_binding'] = software_delivery.build_binding(preparation)
    manifest = software_delivery.build(case, preparation, options, 'pack', context=context,
                                       pdf_tool=pdf_tool, pdf_text_tool=pdf_text_tool)
    verified = software_delivery.verify(case, preparation, options, 'pack', context=context,
                                        pdf_text_tool=pdf_text_tool)
    core.require(all(verified['physical_review'][kind]['status'] == 'checked'
                     for kind in ('mother', 'source', 'manual_mother', 'manual', 'worksheet')),
                 'authored_physical_check_failed')
    core.require(len(software_delivery._manual_pages(preparation,
        software_delivery._screenshots(case, preparation, options, context)[0])) == 1,
        'short_authored_image_split')
    observations.append({'case': 'authored-gui', 'status': 'technical_checks_passed',
                         'candidate_status': manifest['status'], 'issues': manifest['issues'],
                         'physical': verified['physical_review'],
                         'image_authenticity': 'synthetic_fixture_not_real_execution'})
    # 将最近调整的制表位、全角折行、原始LF及标题宽度送入真实渲染，不能仅验XML。
    case = root / 'layout-edges'
    case.mkdir()
    source_text = ['\tvalue = 1', '\t' * 19 + 'x', '', '# URL https://example.invalid/a//b <tag>',
                   '长行保留' * 45, 'x' * 180, 'end = "完成"']
    source_plan, source_map = software_delivery.source_pages([
        {'file_id': 'edge', 'source_line': index, 'text': text}
        for index, text in enumerate(source_text, 1)])
    flat = [block for page in source_plan for block in page]
    for index, original in enumerate(source_text, 1):
        restored = ''.join(block['text'] for block, row in zip(flat, source_map['rows'])
                           if row['source_line'] == index)
        core.require(restored == original, 'edge_source_changed')
    manual_plan = software_delivery._flow([
        {'id': 'Title', 'kind': 'heading1', 'text': '标题宽度检查' * 12},
        {'id': 'Body', 'kind': 'paragraph', 'text': '中文正文边界' * 24 + '\n已有换行保留\n末行'},
    ])
    edge_reports = {}
    for kind, pages in (('source', source_plan), ('manual', manual_plan)):
        raw = documents.make_software_docx(pages, title='合成版式边界', version='1.0', kind=kind)
        documents.inspect_software_docx(raw, pages, title='合成版式边界', version='1.0', kind=kind)
        path = case / (kind + '.docx')
        path.write_bytes(raw)
        pdf = software_delivery._convert(Path(pdf_tool), path, case)
        result = software_layout.inspect_pdf(pdf, pages, kind=kind, title='合成版式边界', version='1.0',
                                              pdf_text_tool=pdf_text_tool)
        (case / (kind + '-review.json')).write_bytes(core.canonical_bytes(result) + b'\n')
        core.require(result['status'] == 'checked', 'edge_physical_layout_failed')
        edge_reports[kind] = result
    observations.append({'case': 'layout-edges', 'status': 'technical_checks_passed',
                         'source_text_reassembled': True, 'physical': edge_reports})
    report = {'status': 'technical_acceptance_completed', 'seconds': round(time.perf_counter() - began, 3),
              'observations': observations, 'professional_review': 'not_performed',
              'real_customer_data': 'not_used', 'official_status': 'not_asserted',
              'external_action': 'not_performed',
              'source_bindings': source_bindings}
    core.require(source_bindings == {name: core.sha256_bytes((source_root / name).read_bytes())
                                     for name in bound_names}, 'acceptance_source_changed_during_run')
    (root / 'acceptance.json').write_bytes(core.canonical_bytes(report) + b'\n')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--pdf-tool', required=True)
    parser.add_argument('--pdf-text-tool', required=True)
    args = parser.parse_args()
    report = run(args.output, args.pdf_tool, args.pdf_text_tool)
    print(json.dumps({'status': report['status'], 'seconds': report['seconds'],
                      'cases': len(report['observations'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
