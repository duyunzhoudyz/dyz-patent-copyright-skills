"""Original local software-readiness cases; fictional title facts are not Harbor facts.

Uses existing SW tools, prints only bounded observations, starts no app/service.
The temporary secret is explicitly fake. No real owner, deposit or sending action.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from tools.core import ContractError, canonical_bytes, safe_path
from tools.software import run

FILES=['api.py','cli.py','core.py','gui.py','index.html']
IDS={'api.py':'api','cli.py':'cli','core.py':'core','gui.py':'gui','index.html':'ui'}
BASE=Path(__file__).resolve().parent
CODE=ROOT/'skills/dyz-software/resources/harbor-demo/v1.3'


def context():
    return {'environment':{},'permissions':[{'action':'local_read','purpose':'synthetic_software',
        'recipient':'local_tool','decision':'allow','authority_evidence':'synthetic-internal-case-development',
        'valid_from':'2026-01-01T00:00:00Z','valid_until':'2027-01-01T00:00:00Z'}],
        'sensitivity':'synthetic','purpose':'synthetic_software','now':'2026-11-03T00:00:00Z'}


def invoke(capability,payload):
    value={'context':context(),**copy.deepcopy(payload)}
    before=canonical_bytes(value)
    result=run(capability,value)
    if canonical_bytes(value)!=before:
        raise ValueError('caller_input_mutated')
    return result


def scope_input(declared):
    components=[]
    for name in FILES:
        cid=IDS[name]
        subjects=[{'subject_id':'SYNTHETIC-OWNER','basis':'fictional supplied ownership assumption for this branch only',
                   'evidence_id':'HYPOTHETICAL-TITLE-'+cid}] if declared else []
        components.append({'id':cid,'kind':'standalone','version':'1.3','origin':'adapted',
            'claim':['Current concrete expression candidate in '+name+'; not functionality or third-party runtime'],
            'exclusions':['Do not relabel inherited1.2 lines new1.3 expression','External runtime/format and unresolved actual title'],
            'baseline_evidence':'Observed1.2 bytes in evidence-map.json, not proof of baseline ownership',
            'subjects':subjects})
    return {'metadata':{'software_id':'harbor-hypothetical-rights','name':'港湾记录整理器（合成权利情景，非真实权属）',
                        'version':'1.3'},'components':components,
            'grouping_basis':'Shared core/CLI/API/GUI/UI in one technical fixture; legal grouping remains professional.'}


def rights_input(scope,deny_api=False):
    records=[]
    for name in FILES:
        cid=IDS[name]
        records.append({'component_id':cid,'requested_decision':'claim',
            'evidence_ids':['HYPOTHETICAL-TITLE-'+cid if scope['components'][0]['subjects'] else 'PROJECT-LOCAL-READ-ONLY'],
            'permissions':{'local_process':'deny' if deny_api and cid=='api' else 'allow',
                           'deposit':'unknown','public':'deny','cloud':'unknown'}})
    return {'scope':scope,'rights':records}


def source_input(scope,rights,purpose='local_process',withheld=False):
    files=[]
    for name in FILES:
        cid=IDS[name]
        files.append({'id':cid,'path':'withheld/does-not-exist.py' if withheld and cid=='api' else name,
            'component_id':cid,'kind':'source','include':True,
            'source_type_evidence':'Explicit original Python or HTML/CSS/JavaScript UI source in synthetic fixture'})
    return {'scope':scope,'rights_decisions':rights,'authorized_root':str(CODE),'files':files,
        'inventory_complete':True,'selection_purpose':purpose,
        'pagination':{'lines_per_page':60,'wrap_columns':120,'selection':'all',
                      'basis':'Internal synthetic review layout; no official quantity or deposit rule'}}


def execute(corpus):
    inventory=corpus.get('source_bindings')
    expected={str((CODE/name).relative_to(ROOT)).replace('\\','/') for name in FILES}
    expected.update({'skills/dyz-software/resources/harbor-delivery-v1.3/facts.json',
                     'skills/dyz-software/resources/harbor-review-readiness/evidence-map.json',
                     'tools/software.py','tools/core.py'})
    if (not isinstance(inventory,list) or len(inventory)!=len(expected)
            or any(not isinstance(r,dict) or set(r)!={'path','sha256'} for r in inventory)
            or {r['path'] for r in inventory}!=expected):
        raise ValueError('source_inventory_invalid')
    source_checks=[]
    for row in inventory:
        value=hashlib.sha256(safe_path(ROOT,row['path']).read_bytes()).hexdigest()
        if value!=row['sha256']:
            raise ValueError('source_binding_changed')
        source_checks.append(row)
    actual_facts=ROOT/'skills/dyz-software/resources/harbor-delivery-v1.3/facts.json'
    fact_before=actual_facts.read_bytes()
    missing=invoke('SW-01',scope_input(False))
    rights_missing=invoke('SW-07',rights_input(missing['artifacts']))
    source_missing=invoke('SW-02',source_input(missing['artifacts'],rights_missing['artifacts']))
    observations={
        'missing_actual_title':{'scope':missing['status'],
            'rights_decisions':sorted({r['decision'] for r in rights_missing['artifacts']['decisions']}),
            'source':source_missing['status'],'selected':source_missing['artifacts']['selected_source_lines'],
            'applicant_stays_null':json.loads(fact_before)['applicant'] is None}}
    declared=invoke('SW-01',scope_input(True))
    rights=invoke('SW-07',rights_input(declared['artifacts']))
    selected=invoke('SW-02',source_input(declared['artifacts'],rights['artifacts']))
    deposit=invoke('SW-02',source_input(declared['artifacts'],rights['artifacts'],'deposit'))
    observations['hypothetical_local_candidate']={'scope':declared['status'],
        'rights_decisions':sorted({r['decision'] for r in rights['artifacts']['decisions']}),
        'source':selected['status'],'selected':selected['artifacts']['selected_source_lines'],
        'deposit_source':deposit['status'],'deposit_selected':deposit['artifacts']['selected_source_lines']}
    changed_rights=invoke('SW-07',rights_input(declared['artifacts'],True))
    changed_input=source_input(declared['artifacts'],changed_rights['artifacts'],withheld=True)
    changed_input['previous_material']=selected['artifacts']
    changed=invoke('SW-02',changed_input)
    withheld=next(r for r in changed['artifacts']['excluded'] if r['file_id']=='api')
    different=scope_input(True);different['metadata']['version']='1.3-hypothetical-scope-change'
    new_scope=invoke('SW-01',different)
    stale_error=None
    try:
        invoke('SW-02',source_input(new_scope['artifacts'],rights['artifacts']))
    except ContractError as exc:
        stale_error=str(exc)
    observations['hypothetical_permission_change']={'source':changed['status'],
        'selected':changed['artifacts']['selected_source_lines'],'withheld_file':withheld['file_id'],
        'withheld_read_status':withheld['read_status'],'stale_scope_error':stale_error}

    secret=corpus['secret_literal']
    with tempfile.TemporaryDirectory(prefix='dyz-software-readiness-') as temporary:
        temp=Path(temporary).resolve()
        if not temp.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not temp.name.startswith('dyz-software-readiness-'):
            raise ValueError('temporary_probe_root_invalid')
        source=(CODE/'core.py').read_text(encoding='utf-8')+'\nDEMO_MARKER = "'+secret+'"\n'
        probe=temp/'probe.py';probe.write_text(source,encoding='utf-8')
        ss=scope_input(True);ss['components']=[ss['components'][2]]
        ss['metadata'].update(software_id='separate-synthetic-secret-probe',name='合成保密探针 '+secret,version='1.0-probe')
        ss['grouping_basis']='Single borrowed original synthetic core plus a fake marker; separate probe, no GUI/API release or actual Harbor title fact.'
        secret_scope=invoke('SW-01',ss)['artifacts']
        sr={'scope':secret_scope,'rights':[{'component_id':'core','requested_decision':'claim',
             'evidence_ids':['HYPOTHETICAL-SECRET-PROBE'],'notice':'演练重复值 '+secret,
             'permissions':{'local_process':'allow','deposit':'unknown','public':'deny','cloud':'deny'}}]}
        secret_rights=invoke('SW-07',sr)['artifacts']
        si=source_input(secret_scope,secret_rights);si.update(authorized_root=str(temp),
            files=[{'id':'probe','path':'probe.py','component_id':'core','kind':'source','include':True}])
        secret_source=invoke('SW-02',si)
        lines=source.splitlines();number=len(lines);column=lines[-1].index(secret)+1
        mi={'material':secret_source['artifacts'],'redactions':[{'file_id':'probe','line':number,'start':column,
             'end':column+len(secret)-1,'basis_id':'SYNTHETIC-REDACTION-1'}]}
        masked=invoke('SW-03',mi);public=invoke('SW-03',{**mi,'target_action':'public'})
        observations['separate_synthetic_secret_probe']={'source':secret_source['status'],'mask':masked['status'],
            'secret_in_masked_output':secret in json.dumps(masked,ensure_ascii=False),
            'exception_rule_issue':next(r['code'] for r in masked['issues'] if r['code']=='exception_deposit_rule_unverified'),
            'external_permission':masked['artifacts']['external_permission'],
            'public_issue':next(r['code'] for r in public['issues'] if r['code']=='separate_disclosure_authorization_required')}
    if actual_facts.read_bytes()!=fact_before:
        raise ValueError('actual_case_facts_changed')
    results=[{'id':key,'expected':value,'observed':observations[key],
              'status':'passed' if observations[key]==value else 'failed'} for key,value in corpus['expectations'].items()]
    return {'kind':'author_local_readiness_cases_not_actual_title_or_professional_acceptance',
            'source_bindings':source_checks,'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'results':results,'passed':sum(r['status']=='passed' for r in results),
            'failed':sum(r['status']=='failed' for r in results),'skipped':0,
            'actual_facts_unchanged':True,'temporary_secret_probe_removed':not temp.exists(),
            'limits':['Fictional title assumptions do not fill actual applicant/contributor/date facts.',
                      'Metadata, license and hashes do not prove title, originality or permission authority.',
                      'Withheld target is hypothetical, absent path; not a host-wide isolation claim.',
                      'Masking known fake spans does not discover all real secrets or authorize deposit/public/cloud.',
                      'No real filing, disclosure, reviewer signature, software server or browser action.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases',nargs='?',type=Path,default=BASE/'review-cases.json')
    args=parser.parse_args()
    try:
        result=execute(json.loads(args.cases.read_text(encoding='utf-8')))
    except (ContractError,ValueError,OSError,KeyError) as exc:
        print(json.dumps({'status':'rejected','error':str(exc)},ensure_ascii=False));return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if result['failed'] else 0


if __name__=='__main__':
    raise SystemExit(main())
