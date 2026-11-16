"""Evaluation-only complete candidate bootstrap, never a global installation.

Run in a fresh -I -S -B Python process. It checks the externally bound review,
every listed source byte and the evaluation sources before importing the
runner. tools imports use the candidate's verified source-only loader; evals
imports also compile their bound source rather than reading cached bytecode.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
from pathlib import Path,PureWindowsPath
import re
import stat
import sys
import tempfile
import types

DEVELOPMENT_ROOT=Path(__file__).resolve().parents[1]
NAMES={'dyz-patent','dyz-procedure','dyz-rendering','dyz-software','dyz-standards','dyz-workbench'}
MANIFEST='bundle-manifest.json'
EVALUATION_FILES=('native_host_runner.py','native_host_session.py','native_host_bridge.py','native_host_candidate.py')

class CandidateError(ValueError):pass

def require(condition,code):
    if not condition:raise CandidateError(code)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def regular(path):
    path=Path(path)
    require(path.is_absolute(),'candidate_absolute_path_required')
    for item in (path,*path.parents):
        info=item.lstat()
        require(not item.is_symlink() and not getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT,
                'candidate_reparse_path')
        if item==path:
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink==1,'candidate_nonregular_file')
    return path

def read_json(path,expected,code):
    raw=regular(path).read_bytes();require(len(raw)<=4_000_000,'candidate_json_size')
    require(isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected) is not None and sha(raw)==expected,code)
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'candidate_duplicate_json_key');result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(CandidateError('candidate_json_constant')))

def validate_candidate(spec,*,development_root=DEVELOPMENT_ROOT):
    """Pure reads only; a caller-supplied hash binds a reviewed complete tree."""
    require(isinstance(spec,dict) and isinstance(spec.get('candidate'),dict) and set(spec['candidate'])=={'review'},'candidate_review_required')
    ref=spec['candidate']['review'];require(isinstance(ref,dict) and set(ref)=={'path','sha256'},'candidate_review_required')
    root=Path(development_root).resolve();review_path=Path(ref['path'])
    require(review_path.is_absolute() and review_path.resolve().is_relative_to(root/'outputs'),'candidate_review_outside_outputs')
    review=read_json(review_path,ref['sha256'],'candidate_review_changed')
    fields={'status','project_root','package','manifest_sha256','source_files','source_inventory_sha256','project_root_markers','selected'}
    require(isinstance(review,dict) and fields<=set(review) and review['status']=='passed_local_current_package_only','candidate_review_status')
    project,package,work=map(Path,(review['project_root'],spec['package'],spec['workspace']))
    version=review.get('review_version',1)
    require(type(version) is int and version in {1,2},'candidate_review_version')
    if version==1:
        require('workspace' in review and 'workspace_policy' not in review,'candidate_workspace_policy')
        workspace_bound=work==project/'workspace' and str(work)==review['workspace']
    else:
        policy=review.get('workspace_policy')
        require('workspace' not in review and isinstance(policy,dict) and set(policy)=={'kind','allowed_cases'}
                and policy['kind']=='owned_project_case_roots','candidate_workspace_policy')
        cases=policy['allowed_cases'];reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
        require(isinstance(cases,list) and 1<=len(cases)<=16 and all(isinstance(case,str)
                and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',case) is not None and case.upper() not in reserved for case in cases)
                and len({case.casefold() for case in cases})==len(cases),'candidate_workspace_policy')
        workspace_bound=work.parent==project/'workspaces' and work.name in cases
        kind=spec.get('kind')
        if kind=='casefree':require(work.name=='G6','candidate_case_workspace_mismatch')
        elif kind in {'known_host_phase','known_host_recovery'}:
            require(work.name==spec.get('case_id'),'candidate_case_workspace_mismatch')
    require(project.is_absolute() and project.name.startswith('dyz-native-candidate-')
            and project.parent.resolve()==Path(tempfile.gettempdir()).resolve()
            and not project.resolve().is_relative_to(root)
            and package==project/'.codex' and workspace_bound
            and str(package)==review['package'],'candidate_project_layout')
    for path in (project,package,work):regular(path)
    require(review['project_root_markers']==['.codex'],'candidate_project_marker')
    manifest=read_json(package/MANIFEST,review['manifest_sha256'],'candidate_manifest_changed')
    require(isinstance(manifest,dict) and manifest.get('kind')=='local_tool_bundle' and isinstance(manifest.get('files'),list),'candidate_manifest_invalid')
    rows=manifest['files']
    require(type(review['source_files']) is int and 1<=review['source_files']<=1000 and len(rows)==review['source_files']
            and sha(canonical(rows))==review['source_inventory_sha256'],'candidate_inventory_binding')
    inventory={};total=0
    for row in rows:
        require(isinstance(row,dict) and set(row)=={'path','bytes','sha256'},'candidate_manifest_invalid')
        name=row['path'];require(isinstance(name,str) and name and not PureWindowsPath(name).drive and ':' not in name and '\\' not in name,'candidate_source_path')
        parts=name.split('/')
        require(all(part and part not in {'.','..'} and not part.startswith('.') and part.rstrip(' .')==part for part in parts)
                and name not in inventory,'candidate_source_path')
        require(type(row['bytes']) is int and 0<=row['bytes']<=10_000_000
                and isinstance(row['sha256'],str) and re.fullmatch('[0-9a-f]{64}',row['sha256']) is not None,'candidate_manifest_invalid')
        path=regular(package/name);require(path.is_file(),'candidate_source_changed')
        require(path.stat().st_size==row['bytes'],'candidate_source_changed')
        raw=path.read_bytes();require(sha(raw)==row['sha256'],'candidate_source_changed')
        inventory[name]=row;total+=len(raw);require(total<=100_000_000,'candidate_source_budget')
    selected=review['selected'];require(isinstance(selected,list) and len(selected)==6,'candidate_selected_entries')
    require(all(isinstance(entry,dict) and entry.get('name') in NAMES and entry.get('enabled') is True for entry in selected)
            and {entry['name'] for entry in selected}==NAMES,'candidate_selected_entries')
    for entry in selected:
        relative='skills/'+entry['name']+'/SKILL.md'
        require(relative in inventory and Path(entry['path'])==package/relative,'candidate_selected_entries')
        header=(package/relative).read_text(encoding='utf-8').split('---',2)
        require(len(header)==3,'candidate_entry_frontmatter')
        description=[line.split(':',1)[1].strip().strip('"').strip("'") for line in header[1].splitlines() if line.startswith('description:')]
        require(len(description)==1 and entry.get('description')==description[0],'candidate_entry_description')
    require(all(name in inventory for name in ['LICENSE','COMMERCIAL-LICENSE.md','THIRD-PARTY-NOTICES.md','tools/__init__.py',
        'tools/host_bridge.py','tools/host_bridge_worker.py','tools/bundle.py','tools/codex_host.py']),'candidate_required_sources')
    return {**review,'workspace':str(work),'review_path':str(review_path),'review_sha256':ref['sha256'],'rows':inventory}

def assert_candidate_runtime(plan):
    package=Path(plan['package'])
    finder=[value for value in sys.meta_path if type(value).__name__=='_FrozenToolsFinder' and getattr(value,'package',None)==package
            and getattr(value,'rows',None)==plan['rows']]
    require(len(finder)==1,'candidate_runtime_not_source_bound')
    for name in ['tools','tools.bundle','tools.host_bridge']:
        module=sys.modules.get(name);relative=name.replace('.','/')+('/__init__.py' if name=='tools' else '.py')
        require(module is not None and Path(module.__file__)==package/relative
                and type(module.__spec__.loader).__name__=='_SourceOnlyLoader'
                and module.__spec__.loader.row==plan['rows'][relative],'candidate_runtime_not_source_bound')

class _EvaluationLoader(importlib.machinery.SourceFileLoader):
    def __init__(self,name,path,expected):super().__init__(name,str(path));self.expected=expected
    def get_code(self,fullname):
        raw=regular(Path(self.path)).read_bytes();require(sha(raw)==self.expected,'candidate_evaluation_source_changed')
        return self.source_to_code(raw,self.path)

class _EvaluationFinder(importlib.abc.MetaPathFinder):
    def __init__(self,root,components):self.root,self.components=root,components
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='evals':
            result=importlib.machinery.ModuleSpec(fullname,None,is_package=True);result.submodule_search_locations=[str(self.root/'evals')];return result
        if not fullname.startswith('evals.'):return None
        source=self.root/(fullname.replace('.','/')+'.py')
        require(str(source) in self.components,'candidate_evaluation_module_not_bound')
        loader=_EvaluationLoader(fullname,source,self.components[str(source)])
        return importlib.util.spec_from_file_location(fullname,source,loader=loader)

def prepare(spec_path,expected_sha256):
    """No model/process/listener. Import exact candidate and evaluation sources."""
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,'candidate_isolated_python_required')
    require(not any(name=='tools' or name.startswith('tools.') or name=='evals' or name.startswith('evals.') for name in sys.modules),
            'candidate_fresh_python_required')
    spec=read_json(Path(spec_path),expected_sha256,'candidate_spec_changed');plan=validate_candidate(spec)
    package=Path(plan['package']);components=spec.get('components')
    paths=[DEVELOPMENT_ROOT/'evals'/name for name in EVALUATION_FILES]
    paths += [package/'tools'/name for name in ['host_bridge.py','host_bridge_worker.py','bundle.py','codex_host.py']]
    require(isinstance(components,dict) and set(components)=={str(path) for path in paths},'candidate_evaluation_components')
    require(all(sha(regular(path).read_bytes())==components[str(path)] for path in paths),'candidate_evaluation_source_changed')
    worker=package/'tools/host_bridge_worker.py'
    loader_module=types.ModuleType('_dyz_native_candidate_source_bootstrap');loader_module.__file__=str(worker)
    sys.modules[loader_module.__name__]=loader_module
    exec(compile(worker.read_bytes(),str(worker),'exec'),loader_module.__dict__)
    sys.meta_path.insert(0,loader_module._FrozenToolsFinder(package,plan['rows']))
    sys.meta_path.insert(0,_EvaluationFinder(DEVELOPMENT_ROOT,components))
    from evals import native_host_runner as runner
    assert_candidate_runtime(plan)
    require(runner.source_components()==components,'candidate_actual_components_changed')
    return runner,plan,spec

def main(argv=None):
    parser=argparse.ArgumentParser(description='Explicit fresh-process current candidate evaluation, not installation.')
    parser.add_argument('--spec',required=True);parser.add_argument('--sha256',required=True);parser.add_argument('--inspect',action='store_true')
    args=parser.parse_args(argv);runner,plan,spec=prepare(args.spec,args.sha256)
    if args.inspect:
        print(json.dumps({'status':'source_bound_current_candidate','manifest_sha256':plan['manifest_sha256'],
            'source_files':plan['source_files'],'source_inventory_sha256':plan['source_inventory_sha256'],
            'actual_module_origins':{name:module.__file__ for name,module in sys.modules.items() if name=='tools' or name.startswith('tools.') or name.startswith('evals.')},
            'source_components':runner.source_components(),'model_or_native_process_started':False},ensure_ascii=False))
        return 0
    runner.run_frozen_phase(args.spec,args.sha256);return 0

if __name__=='__main__':raise SystemExit(main())
