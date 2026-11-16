"""Frozen, single-phase native host evaluation. Importing never starts a model.

The client is evaluation infrastructure, outside the shipped r21 runtime.
Each phase needs its own reviewed spec and control directory. A new process
and thread are created; continuation uses actual protected workspace files.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import queue
import re
import subprocess
import sys
import threading
import time

from evals.native_host_bridge import NativeHostBridge, dynamic_tools, _regular_chain
from evals.native_host_session import (NativeRelay, NativeRpc, SessionError, require, save_new, sha,
    MAX_REQUEST_BODY_BYTES, REQUEST_BODY_READ_SECONDS, close_native_process)
from tools.bundle import verify_bundle

CLI_SHA = '9e7c59c05cc1ce5677b1f94e835b2ac038ca3be14504e78d558eacdb0ea3f55d'
AUTH_SHA = '43ad750fc3215fc0e25f147662a715264d7d0a6991c77ed2196d2f94f65ca734'
CATALOG_SHA = '5994afab545e7f9e7b260d93fcb53230efba30170c14faf74340f756ef063b52'
MANIFEST_SHA = '5074f7446cf2b246269e80d22a3b7589d25e69850f30c263753cfb184af17708'
INPUTS_SHA = '9aa424eb7e04f65f7e4b5aa620ba43bfea68e7a9fa48883e31d013d9ecf1ffd0'
DEVELOPMENT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = Path('D:/skills/codex/dyz-patent-skills')
CLI_PATH = Path('D:/npm-global/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe')
ENVIRONMENT_KEYS = {'systemroot','windir','comspec','temp','tmp','userprofile','appdata','localappdata',
                    'path','pathext','homedrive','homepath','programdata','os','rust_log'}
SKILLS = {'dyz-patent','dyz-procedure','dyz-software','dyz-standards','dyz-rendering','dyz-workbench'}
REVIEW_AUTH = 'existing_official_cli_synthetic_skill_evaluation'
FROZEN_REQUEST_LIMITS = {'max_request_body_bytes': MAX_REQUEST_BODY_BYTES,
                         'body_read_timeout_seconds': REQUEST_BODY_READ_SECONDS}
DEVELOPER = ('请仅完成本轮用户明确授权的内部材料任务，按需要选择专业入口并实际读取有关方法和材料。'
    '本客户端只提供冻结完整包和当前案例目录的八个受限文件工具；无Shell、外部检索、账户、子代理或真实业务行动接口。'
    '目录中的未知、partial、blocked、needs_review与运算成功分别保留，不补造事实、测试、身份、权属、审批或专业签核。'
    '原生目录中的DYZ入口路径可映射为case_read的package相对路径skills/<技能名>/SKILL.md；资源链接相对该文件解析。'
    'package为已核完整树，workspace只读input/work/output，写入只限work/output；控制记录和评分材料不在这些根内。'
    '分段读取以实际范围为准；next_position非空时优先对同scope/path传next_chunk:true，不重抄位置或hash；手动位置/hash仍须精确校验。'
    '元数据或hash不等于已读全文；文件由实际工具生成及回查，不能把计划命令写成执行结果。'
    '文档工具使用当前案例根下已声明的源数据副本和本地配方，源分类、版本、hash及正文/内部材料边界须保留。')


def digest(path):
    return sha(Path(path).read_bytes())


def checked_json(path, expected):
    _regular_chain(Path(path))
    raw = Path(path).read_bytes()
    require(sha(raw) == expected, 'frozen_file_changed')
    return json.loads(raw)


def native_error_summary(message, *, thread_id, turn_id):
    """Classify a bound native error without logging free-form remote details."""
    require(isinstance(message, dict) and message.get('method') == 'error', 'native_error_frame_required')
    params = message.get('params')
    require(isinstance(params, dict) and params.get('threadId') == thread_id
            and params.get('turnId') == turn_id, 'native_error_binding_mismatch')
    error = params.get('error')
    require(isinstance(error, dict), 'native_error_payload_required')
    info = error.get('codexErrorInfo')
    disconnect = info.get('responseStreamDisconnected') if isinstance(info, dict) else None
    classification, status = 'native_reported_error', None
    if isinstance(disconnect, dict):
        classification = 'response_stream_disconnected'
        if error.get('additionalDetails') == 'stream disconnected before completion: idle timeout waiting for SSE':
            classification = 'response_stream_idle_timeout'
        value = disconnect.get('httpStatusCode')
        if type(value) is int and 100 <= value <= 599:
            status = value
    elif info == 'other' and error.get('additionalDetails') is None:
        # Native0.160.1 uses a different final-error shape when retries are
        # exhausted/disabled. Recognize only the observed exact messages.
        classification = {
            'stream disconnected before completion: idle timeout waiting for SSE': 'response_stream_idle_timeout',
            'stream disconnected before completion: stream closed before response.completed': 'response_stream_eof',
        }.get(error.get('message'), 'native_reported_error')
    retry = params.get('willRetry')
    return {'source': 'native_rpc_error', 'classification': classification, 'http_status_code': status,
            'will_retry_reported': retry if type(retry) is bool else None, 'thread_and_turn_bound': True,
            'error_frame_sha256': sha(json.dumps(message, ensure_ascii=False, sort_keys=True).encode('utf-8')),
            'server_state': 'not_inferred_from_native_error'}


def _checked_native_transport(template):
    """Reject unreviewed providers before creating any control or listener."""
    config = dict(template['per_process_config'])
    provider = config.get('model_provider', 'openai')
    provider_keys = {k: v for k, v in config.items() if k.startswith('model_providers.')}
    if provider == 'openai':
        require(not provider_keys, 'unreviewed_native_transport_config')
    else:
        require(provider == 'dyz_official_single_attempt', 'unreviewed_native_transport_config')
        prefix = 'model_providers.' + provider + '.'
        expected = {prefix + k: v for k, v in {
            'name': 'DYZ task official single attempt', 'wire_api': 'responses', 'requires_openai_auth': True,
            'request_max_retries': 0, 'stream_max_retries': 0, 'stream_idle_timeout_ms': 300000,
            'supports_websockets': False}.items()}
        require(set(provider_keys) == set(expected) and all(type(provider_keys[k]) is type(v)
                and provider_keys[k] == v for k, v in expected.items()), 'unreviewed_native_transport_config')
    return config


def build_native_config(template, relay_url, catalog):
    """Keep legacy config, or one reviewed task alias; always use owned relay."""
    match = re.fullmatch(r'http://127\.0\.0\.1:([0-9]{1,5})/backend-api/codex', relay_url)
    require(match is not None and 1 <= int(match.group(1)) <= 65535, 'native_relay_url_required')
    config = _checked_native_transport(template)
    provider = config.get('model_provider', 'openai')
    if provider != 'openai':
        config['model_providers.' + provider + '.base_url'] = relay_url
    config.update({'openai_base_url': relay_url, 'sandbox_mode': 'workspace-write',
        'sandbox_workspace_write.network_access': False, 'model_catalog_json': str(Path(catalog).resolve()),
        'skills.max_context_tokens': 10000})
    return config


def validate_file_recovery(spec, fingerprint, inputs):
    """Admit declared file continuation, never turn it into an original clean score."""
    require(spec['kind'] == 'known_host_recovery' and spec['case_id'] == 'HOST-PAT-F'
            and spec['phase'] == 1, 'unsupported_file_recovery')
    refs = spec['recovery_binding']
    require(isinstance(refs, dict) and set(refs) == {'prepared', 'predecessor_spec', 'predecessor_result',
            'predecessor_assessment'}, 'recovery_binding_fields')
    records = {}
    for key, ref in refs.items():
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'recovery_record_reference')
        records[key] = checked_json(ref['path'], ref['sha256'])
    prepared, previous, failed, assessment = (records[k] for k in
        ['prepared', 'predecessor_spec', 'predecessor_result', 'predecessor_assessment'])
    require(prepared['status'] == 'prepared_file_recovery_only_not_admitted_not_executed'
            and prepared['original_case_id'] == spec['case_id'], 'recovery_not_prepared')
    require(previous['kind'] == failed['kind'] == 'known_host_phase' and previous['case_id'] == failed['case_id'] == spec['case_id']
            and previous['phase'] == failed['phase'] == 1 and failed['status'] == 'native_phase_failed', 'predecessor_not_interrupted')
    case = next((c for c in inputs['cases'] if c['id'] == spec['case_id']), None)
    phase = next((p for p in case['phases'] if p['number'] == 1), None) if case else None
    require(phase is not None and phase['prompt'] == previous['prompt'], 'recovery_original_task_changed')
    require(prepared['original_failed_spec_sha256'] == refs['predecessor_spec']['sha256']
            and prepared['original_failed_result_sha256'] == refs['predecessor_result']['sha256'], 'recovery_predecessor_not_bound')
    require(assessment['status'] == 'failed_native_idle_timeout_incomplete_stream_no_wholecase_acceptance'
            and assessment['case_id'] == spec['case_id'] and assessment['phase'] == 1
            and assessment['spec_sha256'] == refs['predecessor_spec']['sha256']
            and assessment['execution_components'] == previous['components']
            and failed['profile_fingerprint'] == previous['profile_fingerprint'], 'recovery_assessment_not_bound')
    unfinished = assessment['failed_request']
    require(unfinished['callback_executed'] is False and unfinished['completed_function_item'] is False
            and unfinished['genuine_terminal'] is False and failed['callbacks']
            and all(row['success'] is True for row in failed['callbacks'])
            and assessment['actual_callbacks'] == len(failed['callbacks']), 'recovery_mutation_outcome_ambiguous')
    require(spec['prompt'] == prepared['frozen_proposed_recovery_prompt'], 'recovery_prompt_changed')
    require(Path(spec['workspace']).resolve() == Path(prepared['workspace']).resolve(), 'recovery_workspace_not_bound')
    g6 = checked_json(spec['admission']['path'], spec['admission']['sha256'])
    require(g6['status'] == 'passed_native_runner_g6_only' and g6['profile_fingerprint'] == fingerprint
            and g6['components'] == spec['components'], 'current_runner_g6_not_admitted')
    baseline = prepared['initial_files_and_protected_baseline']
    require(spec['initial_files'] == spec['protected_files'] == baseline, 'recovery_baseline_not_protected')
    require(all(row in baseline for row in failed['workspace_files'])
            and len(baseline) == len(failed['workspace_files']) + 1, 'recovery_retained_files_not_bound')
    index = [r for r in baseline if r['path'] == 'input/recovery-state.json']
    require(len(index) == 1, 'recovery_index_missing')
    verify_snapshot(spec['workspace'], baseline)
    require(snapshot(spec['workspace']) == baseline, 'recovery_workspace_changed')
    state = checked_json(Path(spec['workspace']) / 'input/recovery-state.json', index[0]['sha256'])
    require(state['kind'] == 'declared_file_only_recovery_of_known_internal_task' and state['status'] == 'interrupted'
            and state['retained_files'] == failed['workspace_files'], 'recovery_index_not_bound')
    return {'scope': 'declared_known_file_recovery_not_original_clean_case', 'original_case_id': spec['case_id'],
            'protected_file_count': len(baseline), 'prepared_sha256': refs['prepared']['sha256'],
            'predecessor_result_sha256': refs['predecessor_result']['sha256'], 'original_case_result': 'failed_unchanged'}


def relative_path(value):
    require(isinstance(value,str) and value and ':' not in value and '\x00' not in value
            and not PureWindowsPath(value).drive and not value.startswith(('/', '\\')), 'unsafe_relative_path')
    parts = value.replace('\\','/').split('/')
    require(all(p and p not in {'.','..'} and not p.startswith('.') and p.rstrip(' .') == p
                and p.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
                for p in parts), 'unsafe_relative_path')
    return '/'.join(parts)


def snapshot(workspace):
    workspace = Path(workspace)
    _regular_chain(workspace)
    rows = []
    for path in workspace.rglob('*'):
        _regular_chain(path)
        if path.is_file():
            rows.append({'path':path.relative_to(workspace).as_posix(), 'sha256':digest(path), 'bytes':path.stat().st_size})
    return sorted(rows,key=lambda r:r['path'])


def verify_snapshot(workspace, rows):
    for row in rows:
        path = Path(workspace)/relative_path(row['path'])
        _regular_chain(path)
        require(path.is_file() and digest(path) == row['sha256'], 'protected_file_changed')


def validate_roots(package,workspace,control):
    for path in (package,workspace):_regular_chain(Path(path))
    _regular_chain(Path(control),missing=True)
    roots=[Path(p).resolve() for p in (package,workspace,control)]
    require(all(not a.is_relative_to(b) for i,a in enumerate(roots) for j,b in enumerate(roots) if i!=j),
            'runner_roots_overlap')
    require(not roots[1].is_relative_to(Path(__file__).resolve().parents[1]),'workspace_inside_development_tree')


def stage_seed(seed_manifest, expected_sha256, workspace, phase, *, previous_files=()):
    """Keep frozen seeds; project data and recipe paths into readable input/.

    All validation precedes writes. Data bytes remain exact. Runtime recipes
    change only declared file-path values, with each relocation recorded;
    source recipes and package read paths remain intact in the frozen seed.
    request.md is controller data delivered as the frozen user prompt.
    """
    require(type(phase) is int and phase > 0, 'invalid_phase')
    manifest_path, workspace = Path(seed_manifest), Path(workspace)
    seed = manifest_path.parent
    data = checked_json(manifest_path,expected_sha256)
    _regular_chain(workspace)
    existing = snapshot(workspace)
    require(not existing or list(previous_files) == existing, 'workspace_not_owned_or_snapshot_changed')
    verify_snapshot(workspace,previous_files)
    source_rows, path_map = {}, {}
    for row in data['files']:
        relative = relative_path(row['path'])
        require(relative not in source_rows, 'duplicate_seed_path')
        require(relative == 'request.md' or relative.startswith(('input/','skills/','references/','tools/')),
                'unapproved_seed_kind')
        require('scorer' not in relative.lower(), 'scorer_in_seed')
        source = seed/relative
        _regular_chain(source)
        raw = source.read_bytes()
        require(sha(raw) == row['sha256'] and len(raw) == row['bytes'], 'seed_file_changed')
        source_rows[relative] = raw
        if relative.startswith('input/recipes/'):
            path_map[relative] = f'input/phase-{phase}/recipes/' + relative.removeprefix('input/recipes/')
        elif relative.startswith(('skills/','references/','tools/')):
            path_map[relative] = f'input/phase-{phase}/materials/' + relative

    recipes, relocations = {}, {}
    for relative, raw in source_rows.items():
        if not relative.startswith('input/recipes/'):
            continue
        try:
            value=json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise SessionError('seed_recipe_json_invalid') from None
        require(isinstance(value,dict),'seed_recipe_not_object')
        changes=[]
        def project_recipe(value, pointer=''):
            if isinstance(value,dict):
                result={}
                for key,item in value.items():
                    location=pointer+'/'+key.replace('~','~0').replace('/','~1')
                    if key=='path' and isinstance(item,str):
                        if item in path_map:
                            result[key]=path_map[item]
                            changes.append({'pointer':location,'from':item,'to':result[key]})
                            continue
                        require(not item.startswith(('skills/','references/','tools/')),'recipe_source_not_staged')
                    result[key]=project_recipe(item,location)
                return result
            if isinstance(value,list):
                return [project_recipe(item,pointer+'/'+str(i)) for i,item in enumerate(value)]
            return value
        projected=project_recipe(value)
        recipes[relative]=(json.dumps(projected,ensure_ascii=False,indent=2)+'\n').encode('utf-8') if changes else raw
        relocations[path_map[relative]]=changes

    def project_index(value):
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                if key in {'runtime_input','worker_staged_path'} and isinstance(item,str):
                    result[key]=path_map.get(item,item)
                elif key=='model_read' and isinstance(item,dict) and item.get('scope')=='workspace':
                    result[key]={**item,'path':path_map.get(item.get('path'),item.get('path'))}
                else:
                    result[key]=project_index(item)
            original=value.get('runtime_input')
            if isinstance(original,str) and original in recipes:
                result['runtime_sha256']=sha(recipes[original])
                if 'source_package_path' in value and 'sha256' in value:
                    result['source_package_sha256']=value['sha256']
                    result['sha256_scope']='source_package_path'
            return result
        return [project_index(item) for item in value] if isinstance(value,list) else value
    planned = []
    for relative, original in source_rows.items():
        if relative == 'request.md':
            continue
        raw = recipes.get(relative,original)
        if relative.startswith('input/') and relative.endswith('material-index.json'):
            index = project_index(json.loads(raw))
            if isinstance(index,dict):
                require('source_note_original' not in index,'seed_index_provenance_collision')
                if 'source_note' in index:
                    index['source_note_original'] = {
                        'scope':'historical_seed_advisory_not_current_runtime_guidance',
                        'source_path':relative,'source_sha256':sha(original),'value':index['source_note']}
                index['source_note'] = (
                    f'Current phase{phase} runtime: declared data copies are under input/phase-{phase}/materials/ '
                    f'and runtime recipes under input/phase-{phase}/recipes/. Source data bytes and package '
                    'model_read paths stay unchanged. Runtime recipes change only declared file-path values; '
                    'runtime_sha256 binds their projected bytes, while source_package_sha256/sha256 retain '
                    'the frozen source recipe. source_note_original is historical seed text, not current '
                    'placement or reading guidance.')
            raw = (json.dumps(index,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        target_relative = path_map.get(relative,relative)
        target = workspace/target_relative
        _regular_chain(target,missing=True)
        require(not target.exists() or target.is_file() and target.read_bytes() == raw, 'seed_destination_collision')
        planned.append((target_relative,target,raw,relative,sha(original)))
    for _,target,raw,_,_ in planned:
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            _regular_chain(target.parent)
            with target.open('xb') as file:file.write(raw)
    verify_snapshot(workspace,previous_files)
    return {'workspace':str(workspace.resolve()),'phase':phase,'seed_manifest_sha256':expected_sha256,
        'projection_version':2,'path_projection':path_map,'recipe_path_relocations':relocations,
        'controller_request_not_copied':True,
        'staged':[{'path':r,'sha256':sha(raw),'source_path':src,'source_sha256':oldsha}
                  for r,_,raw,src,oldsha in planned], 'files':snapshot(workspace)}


def validate_budget(budget):
    limits = {'max_requests':(1,81),'max_calls':(1,80),'max_seconds':(1,1800),'review_seconds':(1,600)}
    require(isinstance(budget,dict) and set(budget) == set(limits), 'budget_fields')
    for key,(low,high) in limits.items():
        require(type(budget[key]) is int and low <= budget[key] <= high, 'budget_range')


def validate_spec(spec):
    common={'kind','budget','components','cli','authority','package','workspace','control','profile_template',
            'profile_fingerprint','catalog','prompt','protected_files','initial_files','token_cap'}
    require(isinstance(spec,dict) and common <= set(spec),'phase_spec_fields')
    require(spec['kind'] in {'casefree','known_host_phase','known_host_recovery'},'task_kind')
    require(spec['token_cap'] is None and 'max_tokens' not in spec and 'max_output_tokens' not in spec,'generation_token_cap')
    require(isinstance(spec['prompt'],str) and spec['prompt'],'task_prompt_required')
    validate_budget(spec['budget'])
    if spec['kind']=='known_host_phase':
        require({'case_inputs','case_id','phase','seed_receipt','admission'} <= set(spec),'host_admission_fields')
        require(type(spec['phase']) is int and spec['phase']>0,'invalid_phase')
    elif spec['kind']=='known_host_recovery':
        require({'case_inputs','case_id','phase','recovery_binding','admission'} <= set(spec), 'recovery_admission_fields')
        require(type(spec['phase']) is int and spec['phase'] == 1, 'invalid_recovery_phase')
    for item in spec.get('expected_failures',[]):
        require(isinstance(item,dict) and set(item)=={'tool','arguments_sha256','error'}
                and item['tool'] in {t['name'] for t in dynamic_tools()}
                and isinstance(item['error'],str) and bool(item['error'])
                and isinstance(item['arguments_sha256'],str)
                and re.fullmatch('[0-9a-f]{64}',item['arguments_sha256']) is not None,'expected_failure_contract')
    require(isinstance(spec.get('image_views',[]),list),'image_views_type')
    if spec.get('image_views'):
        require('image_view_review' in spec,'image_view_review_required')


def output_matches(actual, content):
    if isinstance(actual,str):
        return len(content) == 1 and content[0].get('type') == 'inputText' and actual == content[0]['text']
    if not isinstance(actual,list) or len(actual) != len(content):
        return False
    for value,expected in zip(actual,content):
        if expected['type'] == 'inputText':
            if value != {'type':'input_text','text':expected['text']}:return False
        elif expected['type'] == 'inputImage':
            if not isinstance(value,dict) or set(value)-{'type','image_url','detail'}:return False
            if value.get('type') != 'input_image' or value.get('image_url') != expected['imageUrl']:return False
            if value.get('detail') not in {None,'auto','low','high','original'}:return False
        else:return False
    return True


class NativeInputGuard:
    def __init__(self, selected, developer=DEVELOPER):
        self.selected, self.developer = selected, developer
        self.prefix = None
        self.expected_outputs = {}
        self.relay = None

    def __call__(self,data,initial):
        if initial:
            texts=[c.get('text','') for row in data['input'] if row.get('role') == 'developer'
                   for c in row.get('content',[]) if isinstance(c,dict)]
            require(sum(self.developer in text for text in texts) == 1, 'neutral_protocol_missing')
            catalogs=[text for text in texts if '<skills_instructions>' in text]
            require(len(catalogs) == 1, 'project_catalog_missing')
            meta=catalogs[0]
            roots=dict(re.findall(r'- `([^`]+)` = `([^`]+)`',meta))
            rows=[line for line in meta.splitlines() if line.startswith('- ') and '(file: ' in line]
            require(len(rows) == len(self.selected) == 6, 'project_catalog_count')
            for entry in self.selected:
                lead=f"- {entry['name']}: {entry['description']} (file: "
                matches=[line for line in rows if line.startswith(lead) and line.endswith(')')]
                require(len(matches) == 1,'project_description_mismatch')
                location=matches[0][len(lead):-1]
                if '/' in location and location.split('/')[0] in roots:
                    alias,tail=location.split('/',1);location=str(Path(roots[alias])/tail)
                require(Path(location).resolve() == Path(entry['path']).resolve(),'project_catalog_path')
            self.prefix = data['input'][:]
        else:
            require(self.prefix is not None and data['input'][:len(self.prefix)] == self.prefix,
                    'initial_context_changed')
        outputs_checked=[]
        for item in data['input'][len(self.prefix):]:
            if item.get('type') == 'function_call_output':
                require(item.get('call_id') in self.expected_outputs,'unbound_native_tool_output')
                require(output_matches(item.get('output'),self.expected_outputs[item['call_id']]),
                        'native_tool_output_changed_or_truncated')
                outputs_checked.append(item['call_id'])
            else:
                require(item.get('id') in self.relay.output_items,'unexplained_native_history')
                source=self.relay.output_items[item['id']]
                for key,value in item.items():
                    if key == 'internal_chat_message_metadata_passthrough':continue
                    require(key in source,'unexplained_history_field')
                    expected=source[key]
                    if item.get('type') == 'message' and key == 'content':
                        expected=[{k:v for k,v in part.items() if not(k in {'annotations','logprobs'} and v == [])}
                                  for part in expected]
                    require(value == expected,'native_history_changed')
        return {'selected6_descriptions_exact':True,'initial_context_unchanged':True,
                'actual_tool_outputs_exact':len(outputs_checked),'verified_call_ids':outputs_checked,
                'no_unexplained_history':True}


class ToolDispatcher:
    def __init__(self, bridge, relay, guard, *, thread_id, turn_id, max_calls, protected=(), expected_failures=(), casefree=False):
        self.bridge,self.relay,self.guard=bridge,relay,guard
        self.thread_id,self.turn_id=thread_id,turn_id
        self.max_calls,self.casefree=max_calls,casefree
        self.protected={relative_path(p['path']) for p in protected}
        self.expected_failures=expected_failures
        self.calls,self.consumed_failures=[],set()

    def handle(self,params):
        require(params.get('threadId') == self.thread_id and params.get('turnId') == self.turn_id,'callback_session_mismatch')
        identity=params.get('callId'); require(identity in self.relay.calls,'callback_not_actual_stream_item')
        binding=self.relay.calls[identity]
        require(params.get('tool') == binding['name'] and params.get('arguments') == binding['arguments']
                and params.get('namespace') == binding['namespace'],'callback_source_mismatch')
        require(identity not in {c['call_id'] for c in self.calls},'duplicate_callback')
        require(len(self.calls)<self.max_calls,'tool_budget_reached')
        name,args=params['tool'],params['arguments']
        require(isinstance(args,dict),'callback_arguments')
        targets=[]
        if name=='case_write':targets=[args['path']]
        elif name=='case_copy':targets=[args['destination']]
        elif name in {'case_documents','case_docx_review','case_fidelity'} and not args.get('verify',False):
            target=relative_path(args['output'])
            require(not any(p==target or p.startswith(target+'/') for p in self.protected),'baseline_output_write')
        require(not any(relative_path(p) in self.protected for p in targets),'protected_baseline_write')
        if self.casefree:
            allowed=(name in {'case_read','case_info'} and (args.get('scope'),args.get('path')) in {
                ('workspace','input/channel-check.txt'),('workspace','work/channel-check.txt'),
                ('workspace','input/channel-check-dense.json'),('package','README.md')})
            allowed=allowed or name=='case_write' and args.get('path')=='work/channel-check.txt' and 'expected_sha256' not in args
            allowed=allowed or name=='case_image' and args=={'scope':'workspace','path':'input/channel-check.png'}
            allowed=allowed or name=='case_documents' and args.get('verify') is True and args in [
                {'input':f'input/channel-check-v{version}.json','output':'output/channel-check-document',
                 'mode':'synthetic','verify':True} for version in (1,2)]
            require(allowed,'casefree_callback_scope')
            if name=='case_read' and args.get('scope')=='package':
                start,count=args.get('start_line',1),args.get('max_lines',80)
                require(type(start) is int and type(count) is int and start>=1 and count>=1 and start+count-1<=8,'casefree_read_range')
        before=len(self.bridge.calls)
        answer=self.bridge.native_tool_result(params,thread_id=self.thread_id,turn_id=self.turn_id)
        self.guard.expected_outputs[identity]=answer['contentItems']
        record={'call_id':identity,'tool':name,'arguments_sha256':sha(json.dumps(args,sort_keys=True,ensure_ascii=False).encode()),
                'success':answer['success'],'expected_negative':False,
                'bridge_record_ordinal':len(self.bridge.calls) if len(self.bridge.calls)==before+1 else None}
        if not answer['success']:
            text=next((i['text'] for i in answer['contentItems'] if i['type']=='inputText'),'{}')
            actual=json.loads(text)
            for i,expected in enumerate(self.expected_failures):
                if i not in self.consumed_failures and expected=={'tool':name,'arguments_sha256':record['arguments_sha256'],'error':actual.get('error')}:
                    self.consumed_failures.add(i);record['expected_negative']=True;break
        self.calls.append(record)
        allowed=answer['success'] or record['expected_negative']
        if not allowed:self.relay.failed='unexpected_tool_failure'
        return answer,allowed


def read_coverage(bridge_records,callbacks,confirmed_call_ids):
    """Only text actually retained in completed official requests counts."""
    groups={}
    for callback in callbacks:
        ordinal=callback.get('bridge_record_ordinal')
        if callback['call_id'] not in confirmed_call_ids or ordinal is None:continue
        record=bridge_records[ordinal-1]
        if record['tool']!='case_read' or not record['answer']['success']:continue
        args,payload=record['arguments'],record['answer']['result']
        key=(args['scope'],args['path'],payload['sha256'])
        item=groups.setdefault(key,{'scope':key[0],'path':key[1],'sha256':key[2],
            'total_lines':payload['total_lines'],'ranges':[],'columns':{}})
        require(item['total_lines']==payload['total_lines'],'read_coverage_total_changed')
        if 'line_fragments' in payload:
            for fragment in payload['line_fragments']:
                line,begin,end,total=(fragment[k] for k in ('line','from_column','to_column','total_columns'))
                require(all(type(v) is int for v in (line,begin,end,total)) and 1<=line<=item['total_lines']
                        and 0<=begin<=end<=total,'read_coverage_fragment_range')
                column=item['columns'].setdefault(line,{'total_columns':total,'ranges':[],'fragmented':False})
                require(column['total_columns']==total,'read_coverage_line_length_changed')
                column['ranges'].append([begin,end]);column['fragmented']|=begin!=0 or end!=total
        elif payload['end_line']>=payload['start_line']:
            item['ranges'].append([payload['start_line'],payload['end_line']])
    result=[]
    for item in groups.values():
        fragmented=[]
        for line,column in sorted(item.pop('columns').items()):
            ranges=[]
            for begin,end in sorted(column['ranges']):
                if ranges and begin<=ranges[-1][1]:ranges[-1][1]=max(ranges[-1][1],end)
                else:ranges.append([begin,end])
            full=ranges==[[0,column['total_columns']]]
            if full:item['ranges'].append([line,line])
            if column['fragmented']:
                fragmented.append({'line':line,'total_columns':column['total_columns'],'ranges':ranges,'complete_line_text_in_completed_model_input':full})
        merged=[]
        for start,end in sorted(item['ranges']):
            if merged and start<=merged[-1][1]+1:merged[-1][1]=max(merged[-1][1],end)
            else:merged.append([start,end])
        complete=item['total_lines']==0 or merged==[[1,item['total_lines']]]
        result.append({**item,'ranges':merged,'fragmented_line_coverage':fragmented,'all_physical_lines_in_completed_model_input':complete,
            'status':'empty_read' if item['total_lines']==0 else 'complete_text_input' if complete else 'partial_text_input',
            'semantic_or_professional_review':False})
    return sorted(result,key=lambda r:(r['scope'],r['path'],r['sha256']))


def source_components(package=None):
    folder=Path(__file__).parent
    paths = [folder/name for name in ['native_host_runner.py','native_host_session.py','native_host_bridge.py']]
    tools_root=Path(package) if package is not None else Path(sys.modules[verify_bundle.__module__].__file__).resolve().parents[1]
    paths += [tools_root/'tools'/name for name in ['host_bridge.py','host_bridge_worker.py','bundle.py','codex_host.py']]
    if tools_root.resolve()!=folder.parent.resolve():paths.append(folder/'native_host_candidate.py')
    return {str(path):digest(path) for path in paths}


def image_coverage(bridge_records,callbacks,confirmed_call_ids):
    rows=[]
    for callback in callbacks:
        ordinal=callback.get('bridge_record_ordinal')
        if callback['call_id'] not in confirmed_call_ids or ordinal is None:continue
        record=bridge_records[ordinal-1]
        if record['tool']!='case_image' or not record['answer']['success']:continue
        data=record['answer']['result'];view=data.get('image_view')
        rows.append({'scope':record['arguments']['scope'],'path':record['arguments']['path'],
            'source_sha256':data['sha256'],'source_dimensions':[data['width'],data['height']],
            'image_content_sha256':view['sha256'] if view else data['sha256'],
            'image_content_dimensions':[view['width'],view['height']] if view else [data['width'],data['height']],
            'original_resolution_bytes_in_completed_model_input':view is None,
            'status':'exact_frozen_prepared_view_in_completed_model_input' if view else 'exact_source_image_in_completed_model_input',
            'semantic_or_professional_review':False})
    return rows


def image_view_bindings(views):
    return sorted([{k:v for k,v in row.items() if k!='view_path'} for row in views],key=lambda row:row['source_sha256'])


def stage_image_views(spec,control):
    views=spec.get('image_views',[])
    if not views:return []
    review=checked_json(spec['image_view_review']['path'],spec['image_view_review']['sha256'])
    require(review['status']=='passed_known_internal_image_views_only' and review['cli_sha256']==CLI_SHA
            and review['bindings']==image_view_bindings(views),'image_view_review_not_bound')
    planned=[]
    for view in views:
        source=Path(view['view_path']);_regular_chain(source)
        require(source.resolve().is_relative_to(DEVELOPMENT_ROOT/'outputs'),'image_view_asset_outside_outputs')
        raw=source.read_bytes();require(sha(raw)==view['view_sha256'],'image_view_asset_changed')
        planned.append((view,raw))
    folder=Path(control)/'image-views';folder.mkdir(exist_ok=False)
    result=[]
    for ordinal,(view,raw) in enumerate(planned,1):
        destination=folder/f'view-{ordinal}.png'
        with destination.open('xb') as file:file.write(raw)
        result.append({**view,'view_path':str(destination.resolve())})
    return result


def candidate_runtime_identity(candidate):
    value={key:candidate[key] for key in ['package','source_files','source_inventory_sha256','review_sha256','project_root_markers']}
    if candidate.get('review_version',1)==2:value['workspace_policy']=candidate['workspace_policy']
    else:value['workspace']=candidate['workspace']
    return value


def profile_fingerprint(template,components,image_views=(),*,candidate=None):
    value={'config':template['per_process_config'],'environment_keys':template['environment_keys'],
        'components':components,'developer':DEVELOPER,
        'local_request_limits':dict(FROZEN_REQUEST_LIMITS),
        'image_view_bindings':image_view_bindings(image_views),
        'tools':dynamic_tools(),'manifest':MANIFEST_SHA,'model':'gpt-6.1-sol','effort':'high',
        'selection':'installed6_thread_only','permission':'workspace-write_network_false'}
    if candidate is not None:
        value.update(manifest=candidate['manifest_sha256'],selection='current_candidate6_thread_paths_only',
            candidate=candidate_runtime_identity(candidate))
    return sha(json.dumps(value,sort_keys=True,ensure_ascii=False).encode())


def select_native_skills(inventory,package,*,candidate=None):
    selected=[s for s in inventory if Path(s['path']).resolve().is_relative_to(Path(package).resolve())]
    require(len(selected)==6 and {s['name'] for s in selected}==SKILLS and all(s['enabled'] for s in selected),'installed6_discovery')
    if candidate is None:
        require(all(sum(r['name']==s['name'] for r in inventory)==1 for s in selected),'duplicate_project_names')
    else:
        fields=lambda rows:sorted((s['name'],s['path'],s['description'],s['enabled']) for s in rows)
        require(fields(selected)==fields(candidate['selected']),'candidate_native_metadata_changed')
    selectors=[{'name':name,'enabled':False} for name in sorted({s['name'] for s in inventory}-SKILLS)]
    if candidate is not None:
        selectors += [{'path':s['path'],'enabled':False} for s in inventory if s['name'] in SKILLS and s not in selected]
    selectors += [{'path':s['path'],'enabled':True} for s in selected]
    return selected,selectors


def run_frozen_phase(spec_path, expected_sha256):
    """Explicit caller only. Fresh exclusive control folder and reviewed input.

    This records native execution, not task/professional acceptance. The next
    phase must be admitted after actual artifact/content review by the owner.
    """
    spec=checked_json(spec_path,expected_sha256)
    validate_spec(spec)
    require(spec['components']==source_components(),'runner_components_changed')
    require(Path(spec['cli']).resolve()==CLI_PATH.resolve() and digest(spec['cli'])==CLI_SHA,'cli_changed')
    checked_json(spec['authority']['path'],AUTH_SHA)
    package,work,control=map(Path,(spec['package'],spec['workspace'],spec['control']))
    candidate=None
    if 'candidate' in spec:
        from evals.native_host_candidate import validate_candidate,assert_candidate_runtime
        candidate=validate_candidate(spec);assert_candidate_runtime(candidate)
    else:require(package.resolve()==PACKAGE_PATH.resolve(),'installed_package_path_changed')
    manifest_sha=candidate['manifest_sha256'] if candidate is not None else MANIFEST_SHA
    require(control.resolve().is_relative_to(DEVELOPMENT_ROOT/'outputs'),'control_outside_task_outputs')
    validate_roots(package,work,control)
    verify_bundle(package,expected_manifest_sha256=manifest_sha)
    template=checked_json(spec['profile_template']['path'],spec['profile_template']['sha256'])
    require({k.lower() for k in template['environment_keys']} <= ENVIRONMENT_KEYS,'unapproved_environment_keys')
    _checked_native_transport(template)
    fingerprint=profile_fingerprint(template,spec['components'],spec.get('image_views',[]),**({'candidate':candidate} if candidate is not None else {}))
    require(spec['profile_fingerprint']==fingerprint,'profile_fingerprint_changed')
    recovery_binding = None
    if spec['kind']=='known_host_phase':
        inputs=checked_json(spec['case_inputs']['path'],INPUTS_SHA)
        case=next((c for c in inputs['cases'] if c['id']==spec['case_id']),None)
        require(case is not None,'unknown_host_case')
        phase=next((p for p in case['phases'] if p['number']==spec['phase']),None)
        require(phase is not None and phase['prompt']==spec['prompt'],'case_prompt_changed')
        receipt=checked_json(spec['seed_receipt']['path'],spec['seed_receipt']['sha256'])
        require(receipt['seed_manifest_sha256']==phase['seed_manifest']['sha256'] and Path(receipt['workspace'])==work.resolve(),
                'seed_receipt_not_bound')
        require(all(row in spec['protected_files'] for row in receipt['files']),'seed_files_not_protected')
        admission=checked_json(spec['admission']['path'],spec['admission']['sha256'])
        require(admission['status']=='passed_native_runner_g6_only' and admission['profile_fingerprint']==fingerprint,
                'current_runner_g6_not_admitted')
        require(spec['phase']==1 or spec.get('prior_phase_review') is not None,'continuation_review_missing')
        if spec['phase']>1:
            previous=checked_json(spec['prior_phase_review']['path'],spec['prior_phase_review']['sha256'])
            require(previous['status']=='passed_internal_host_phase_only' and previous['case_id']==spec['case_id']
                    and previous['phase']==spec['phase']-1 and Path(previous['workspace'])==work.resolve(),
                    'continuation_review_not_bound')
            require(all(row in spec['protected_files'] for row in previous['files']),'baseline_files_not_protected')
    elif spec['kind']=='known_host_recovery':
        inputs=checked_json(spec['case_inputs']['path'],INPUTS_SHA)
        recovery_binding=validate_file_recovery(spec,fingerprint,inputs)
    control.mkdir(exist_ok=False)
    require(not control.resolve().is_relative_to(work.resolve()) and not work.resolve().is_relative_to(control.resolve()),'control_workspace_overlap')
    bridge_dir=control/'bridge';bridge_dir.mkdir()
    staged_views=stage_image_views(spec,control)
    bridge=NativeHostBridge(package,work,bridge_dir,manifest_sha,max_calls=spec['budget']['max_calls'],image_views=staged_views)
    verify_snapshot(work,spec['protected_files'])
    require(snapshot(work)==spec['initial_files'],'initial_workspace_changed')
    metadata=Path(spec['catalog']).read_bytes();require(sha(metadata)==CATALOG_SHA,'catalog_changed')
    derived=json.loads(metadata);selected_model=[m for m in derived['models'] if m['slug']=='gpt-6.1-sol']
    require(len(selected_model)==1 and selected_model[0]['tool_mode']=='code_mode_only'
            and selected_model[0]['apply_patch_tool_type']=='freeform'
            and selected_model[0]['experimental_supported_tools']==['send_user_message_async','clock'],'original_catalog_selection_changed')
    selected_model[0].update(tool_mode='direct',apply_patch_tool_type=None,experimental_supported_tools=[])
    catalog=control/'derived-direct-tool-catalog.json';save_new(catalog,derived)
    guard=NativeInputGuard([])
    relay=NativeRelay(control/'relay',metadata,dynamic_tools(),spec['prompt'],max_requests=spec['budget']['max_requests'],
        review_seconds=spec['budget']['review_seconds'],review_authorization=REVIEW_AUTH,request_guard=guard,
        **FROZEN_REQUEST_LIMITS)
    guard.relay=relay
    config=build_native_config(template,f'http://127.0.0.1:{relay.port}/backend-api/codex',catalog)
    if candidate is not None:config['project_root_markers']=candidate['project_root_markers']
    provider=config.get('model_provider','openai')
    command=[str(spec['cli']),'app-server','--listen','stdio://']
    for key,value in config.items():command+=['-c',key+'='+json.dumps(value,ensure_ascii=False)]
    environment={k:v for k,v in os.environ.items() if k.lower() in {n.lower() for n in template['environment_keys']} and k.lower()!='rust_log'}
    environment['RUST_LOG']='off,codex_app_server::request_processors::thread_processor=warn,codex_app_server::message_processor=warn'
    save_new(control/'intent.json',{'spec_path':str(spec_path),'spec_sha256':expected_sha256,'profile_fingerprint':fingerprint,
        'components':spec['components'],'developer':DEVELOPER,'command':command,'environment_keys':sorted(environment),
        'image_view_bindings':image_view_bindings(staged_views),
        'local_request_limits':dict(relay.request_limits),
        'candidate_binding':({**candidate_runtime_identity(candidate),'manifest_sha256':manifest_sha,
                              'observed_workspace':str(work.resolve())} if candidate is not None else None),
        'derived_catalog_sha256':digest(catalog),'source_catalog_sha256':CATALOG_SHA,'scope':'3 declared metadata fields changed only in private process catalog; native configuration/OS/vendor isolation not claimed'})
    result={'status':'prepared','case_id':spec.get('case_id'),'phase':spec.get('phase'),'kind':spec['kind'],
        'workspace':str(work.resolve()),'profile_fingerprint':fingerprint,'closed_thread_ids':[],'whole_goal':'not_complete'}
    result['native_provider']=provider
    result['local_request_limits']=dict(relay.request_limits)
    if recovery_binding is not None:result['file_recovery_binding']=recovery_binding
    inbound=(control/'rpc-inbound.jsonl').open('xb');outbound=(control/'rpc-outbound.jsonl').open('xb')
    lifecycle=(control/'rpc-lifecycle.jsonl').open('xb')
    child=rpc=errors=dispatcher=None
    stderr_hash=hashlib.sha256();stderr_info={'bytes':0,'eof':False}
    start=time.monotonic()
    def observe(message):
        if message.get('method')=='thread/closed':result['closed_thread_ids'].append(message['params']['threadId'])
    def read_stderr():
        while True:
            data=child.stderr.read1(4096)
            if not data:stderr_info['eof']=True;return
            stderr_hash.update(data);stderr_info['bytes']+=len(data)
    try:
        login=subprocess.run([str(spec['cli']),'login','status'],env=environment,capture_output=True,timeout=20,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        require(login.returncode==0 and b'Logged in using ChatGPT' in login.stdout+login.stderr,'official_login_method_not_recognized')
        result['login_method']='Logged in using ChatGPT; no credential file read by coordinator'
        child=subprocess.Popen(command,cwd=work,env=environment,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result['pid']=child.pid;save_new(control/'live-ownership.json',{'pid':child.pid,'port':relay.port,'workspace':str(work),'driver_pid':os.getpid(),'cli_sha256':CLI_SHA})
        errors=threading.Thread(target=read_stderr,daemon=True);errors.start();rpc=NativeRpc(child,inbound,outbound,lifecycle)
        identity=rpc.lifecycle[0]['native_process']
        save_new(control/'native-process-identity.json',identity)
        require(identity.get('status')=='observed_owned_handle' and identity.get('pid')==child.pid
                and type(identity.get('creation_filetime_100ns')) is int, 'native_process_identity_unverified')
        rpc.request('initialize',{'clientInfo':{'name':'dyz_native_host_runner','title':'DYZ frozen host phase','version':'0.1.0'},
            'capabilities':{'experimentalApi':True,'explicitGatewayOauth':True}},1)
        rpc.send({'method':'initialized','params':{}})
        listed=rpc.request('skills/list',{'cwds':[str(work)],'forceReload':True},2)
        require(len(listed['data'])==1,'skill_roots_mismatch');inventory=listed['data'][0]['skills']
        selected,selectors=select_native_skills(inventory,package,candidate=candidate)
        guard.selected=selected
        before=sorted((s['name'],s['path'],s['description'],s['enabled']) for s in inventory)
        save_new(control/'thread-skills-config.json',{'selected':selected,'global_inventory_count':len(before),
            'config':{'skills.config':selectors},'scope':'owned ephemeral thread only'})
        models=rpc.request('model/list',{'includeHidden':True,'limit':100},3)
        model=[m for m in models['data'] if m.get('model')=='gpt-6.1-sol']
        require(len(model)==1 and any(v['reasoningEffort']=='high' for v in model[0]['supportedReasoningEfforts']),'model_high_missing')
        reply=rpc.request('thread/start',{'model':'gpt-6.1-sol','modelProvider':provider,'cwd':str(work),'ephemeral':True,
            'approvalPolicy':'never','sandbox':'workspace-write','dynamicTools':dynamic_tools(),'developerInstructions':DEVELOPER,
            'config':{'skills.config':selectors}},4)
        result['thread_id']=reply['thread']['id'];save_new(control/'thread-start.json',reply)
        require(reply['model']=='gpt-6.1-sol' and reply['modelProvider']==provider and reply['approvalPolicy']=='never'
                and reply.get('reasoningEffort')=='high' and Path(reply['cwd']).resolve()==work.resolve(),'native_thread_profile')
        require(reply['sandbox']['type']=='workspaceWrite' and reply['sandbox']['networkAccess'] is False,'native_permission_profile')
        mcp=rpc.request('mcpServerStatus/list',{'threadId':result['thread_id'],'detail':'toolsAndAuthOnly','limit':100},5)
        require(not mcp.get('nextCursor') and all((r['runtimeStatus'].get('status') if isinstance(r['runtimeStatus'],dict)
                else r['runtimeStatus'])=='disabled' and not r.get('tools') for r in mcp['data']),'mcp_not_disabled')
        result['mcp_status_count']=len(mcp['data'])
        relay.thread_id,relay.armed=result['thread_id'],True
        turn=rpc.request('turn/start',{'threadId':result['thread_id'],'input':[{'type':'text','text':spec['prompt']}],
            'effort':'high','model':'gpt-6.1-sol'},6)
        result['turn_id']=turn['turn']['id'];save_new(control/'turn-start.json',turn)
        dispatcher=ToolDispatcher(bridge,relay,guard,thread_id=result['thread_id'],turn_id=result['turn_id'],
            max_calls=spec['budget']['max_calls'],protected=spec['protected_files'],
            expected_failures=spec.get('expected_failures',[]),casefree=spec['kind']=='casefree')
        while True:
            require(time.monotonic()-start<spec['budget']['max_seconds'],'phase_time_budget')
            require(relay.failed is None,'relay_failed')
            if rpc.pending_tools:message=rpc.pending_tools.pop(0)
            else:
                try:message=rpc.receive(1)
                except queue.Empty:continue
            observe(message)
            if message.get('method') == 'error':
                result['first_native_error_observed_monotonic'] = time.monotonic()
                result['first_native_error'] = native_error_summary(message,
                    thread_id=result['thread_id'], turn_id=result['turn_id'])
            require(message.get('method')!='error','unexpected_native_error')
            if 'method' in message and 'id' in message:
                require(message['method']=='item/tool/call','unexpected_native_server_request')
                answer,allowed=dispatcher.handle(message['params'])
                rpc.send({'id':message['id'],'result':answer})
                print(json.dumps({'stage':'host_tool_returned','ordinal':len(dispatcher.calls),'tool':message['params']['tool'],'success':answer['success']}),flush=True)
                require(allowed,'unexpected_tool_failure')
            elif message.get('method')=='turn/completed':
                require(message['params']['threadId']==result['thread_id'] and message['params']['turn']['id']==result['turn_id'],'native_turn_mismatch')
                result['completed_turn']=message['params']['turn']
                require(result['completed_turn']['status']=='completed' and result['completed_turn'].get('error') is None,'native_turn_failed')
                break
        verify_snapshot(work,spec['protected_files'])
        after=rpc.request('skills/list',{'cwds':[str(work)],'forceReload':True},7)
        require(before==sorted((s['name'],s['path'],s['description'],s['enabled']) for s in after['data'][0]['skills']),'global_inventory_changed')
        result['global_inventory_before_after_equal']=True;result['global_inventory_count']=len(before)
        result['status']='native_phase_loop_completed_pending_author_artifact_review'
    except Exception as error:
        result['status']='native_phase_failed'
        result['failure_type']=type(error).__name__
        result['failure_category']=str(error) if isinstance(error,SessionError) else 'operator_or_transport_error'
        result['relay_failure_observed_before_stop']=relay.failed
        print(json.dumps({'stage':'host_phase_stopped','failure':result['failure_category'],'relay_failure':relay.failed}),flush=True)
    finally:
        relay.armed=False
        if child is not None and child.poll() is None:
            if result.get('turn_id') and not result.get('completed_turn'):
                try:result['interrupt']=rpc.request('turn/interrupt',{'threadId':result['thread_id'],'turnId':result['turn_id']},90,timeout=10)
                except Exception as error:result['interrupt_error']=type(error).__name__
            if result.get('thread_id'):
                try:
                    result['unsubscribe']=rpc.request('thread/unsubscribe',{'threadId':result['thread_id']},91,timeout=10)
                    for message in rpc.frames:observe(message)
                    deadline=time.monotonic()+10
                    while result['thread_id'] not in result['closed_thread_ids']:
                        observe(rpc.receive(max(0.01,deadline-time.monotonic())))
                        require(time.monotonic()<deadline,'thread_close_deadline')
                    result['owned_thread_closed_before_stdin_close']=True
                except Exception as error:result['thread_close_error']=type(error).__name__
            closed=close_native_process(child,observe=rpc.record_lifecycle if rpc is not None else None)
            result['five_second_exit']='met_this_run' if closed['five_second_exit'] else 'failed_this_run'
            for key in ['diagnostic_late_exit','cleanup_incomplete']:
                if key in closed:result[key]=closed[key]
            result['native_close_observations']=closed['observations']
            result['native_close_timing']=closed['timing']
            result['exit_seconds_after_stdin_close']=closed['exit_seconds']
        result['exit_code']=child.poll() if child is not None else None
        if rpc is not None:
            rpc.reader.join(timeout=1);result['rpc_reader_finished']=not rpc.reader.is_alive()
            result['post_close_observation']=rpc.record_lifecycle('rpc_reader_joined')
            result['native_lifecycle_events']=rpc.lifecycle
            samples=[row['native_process'] for row in rpc.lifecycle]
            born=samples[0].get('creation_filetime_100ns')
            result['native_identity_verified']=type(born) is int and all(
                row.get('status')=='observed_owned_handle' and row.get('pid')==child.pid
                and row.get('creation_filetime_100ns')==born for row in samples)
        if errors is not None:errors.join(timeout=1)
        result['relay_cleanup']=relay.close();result['relay_failure']=relay.failed
        result['requests']=relay.requests;result['metadata_gets']=relay.metadata_gets;result['local_negotiations']=relay.negotiations
        result['callbacks']=dispatcher.calls if dispatcher else []
        confirmed={identity for request in relay.requests if request.get('outcome')=='completed_with_genuine_delimiter'
                   for identity in request.get('runner_guard',{}).get('verified_call_ids',[])}
        result['model_visible_text_coverage']=read_coverage(bridge.calls,result['callbacks'],confirmed)
        result['model_visible_image_coverage']=image_coverage(bridge.calls,result['callbacks'],confirmed)
        result['stderr']={**stderr_info,'sha256':stderr_hash.hexdigest(),'body_not_recorded':True}
        result['elapsed_seconds']=round(time.monotonic()-start,6)
        result['workspace_files']=snapshot(work)
        result['external_workspace_retained']=True
        if rpc is not None:
            result['native_final_messages']=[m['params']['item'] for m in rpc.frames if m.get('method')=='item/completed'
                and m.get('params',{}).get('item',{}).get('type')=='agentMessage'
                and m['params']['item'].get('phase')=='final_answer']
        inbound.close();outbound.close();lifecycle.close()
        result['native_lifecycle_log_sha256']=digest(control/'rpc-lifecycle.jsonl')
        save_new(control/'result.json',result)
        print(json.dumps({k:result.get(k) for k in ['status','case_id','phase','pid','failure_category','relay_failure','five_second_exit','exit_code','elapsed_seconds']},ensure_ascii=False),flush=True)
    return result
