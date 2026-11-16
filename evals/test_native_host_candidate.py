"""Complete candidate binding and isolated source-loader regression checks."""
import copy
import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest import mock

from tools.bundle import BUNDLE_FILES,build_bundle,MANIFEST_NAME
from evals import native_host_runner as runner

ROOT=Path(__file__).resolve().parents[1]
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')

class CandidateBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dyz-native-candidate-test-');self.addCleanup(self.temp.cleanup)
        self.project=Path(self.temp.name).resolve();self.package=self.project/'.codex';self.work=self.project/'workspace';self.work.mkdir()
        build_bundle(self.package,source_root=ROOT)
        self.development=self.project/'development';self.control=self.development/'outputs';self.control.mkdir(parents=True)
        manifest=json.loads((self.package/MANIFEST_NAME).read_bytes());self.pin=sha((self.package/MANIFEST_NAME).read_bytes())
        selected=[]
        for name in sorted(runner.SKILLS):
            path=self.package/'skills'/name/'SKILL.md';header=path.read_text(encoding='utf-8').split('---',2)[1]
            description=next(line.split(':',1)[1].strip().strip('"') for line in header.splitlines() if line.startswith('description:'))
            selected.append({'name':name,'description':description,'path':str(path),'enabled':True})
        self.review={'status':'passed_local_current_package_only','project_root':str(self.project),'package':str(self.package),
            'workspace':str(self.work),'manifest_sha256':self.pin,'source_files':len(BUNDLE_FILES),'source_inventory_sha256':sha(canonical(manifest['files'])),
            'project_root_markers':['.codex'],'selected':selected}
        self.review_path=self.control/'candidate-review.json'
        self.spec={'package':str(self.package),'workspace':str(self.work)};self.bind_review()

    def bind_review(self):
        self.review_path.write_bytes(canonical(self.review))
        self.spec['candidate']={'review':{'path':str(self.review_path),'sha256':sha(self.review_path.read_bytes())}}

    def plan(self):
        from evals.native_host_candidate import validate_candidate
        return validate_candidate(self.spec,development_root=self.development)

    def test_full_tree_and_exact_review_produce_bound_identity(self):
        plan=self.plan()
        self.assertEqual(self.pin,plan['manifest_sha256']);self.assertEqual(len(BUNDLE_FILES),plan['source_files'])
        self.assertEqual(self.review['source_inventory_sha256'],plan['source_inventory_sha256'])
        self.assertEqual(6,len(plan['selected']))

    def test_source_change_fails_before_any_process_or_control_write(self):
        (self.package/'tools/fidelity.py').write_bytes(b'changed')
        with mock.patch('subprocess.Popen',side_effect=AssertionError('must not launch')) as launch:
            with self.assertRaisesRegex(ValueError,'candidate_source_changed'):self.plan()
            launch.assert_not_called()

    def test_manifest_and_review_hashes_are_not_self_certified(self):
        self.review_path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'candidate_review_changed'):self.plan()
        self.bind_review();(self.package/MANIFEST_NAME).write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'candidate_manifest_changed'):self.plan()

    def test_partial_inventory_cannot_become_a_complete_candidate(self):
        self.review['source_files']=256;self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_inventory_binding'):self.plan()

    def test_other_workspace_or_project_layout_is_not_accepted(self):
        self.spec['workspace']=str(self.project/'other')
        with self.assertRaisesRegex(ValueError,'candidate_project_layout'):self.plan()

    def test_unreviewed_project_marker_or_disabled_entry_is_rejected(self):
        self.review['project_root_markers']=['.git'];self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_project_marker'):self.plan()
        self.review['project_root_markers']=['.codex'];self.review['selected'][0]['enabled']=False;self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_selected_entries'):self.plan()

    def test_entry_from_old_tree_cannot_stand_in_for_current_entry(self):
        self.review['selected'][0]['path']=str(ROOT/'skills/dyz-patent/SKILL.md');self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_selected_entries'):self.plan()

    def test_inventory_digest_and_entry_description_are_exact(self):
        self.review['source_inventory_sha256']='0'*64;self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_inventory_binding'):self.plan()
        manifest=json.loads((self.package/MANIFEST_NAME).read_bytes());self.review['source_inventory_sha256']=sha(canonical(manifest['files']))
        self.review['selected'][0]['description']+=' changed';self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_entry_description'):self.plan()

    def test_profile_binds_whole_package_identity_and_loader_not_only_three_tools(self):
        plan=self.plan();template={'per_process_config':{},'environment_keys':[]};components=runner.source_components(package=self.package)
        self.assertIn(str(ROOT/'evals/native_host_candidate.py'),components)
        first=runner.profile_fingerprint(template,components,candidate=plan)
        changed=copy.deepcopy(plan);changed['manifest_sha256']='0'*64
        self.assertNotEqual(first,runner.profile_fingerprint(template,components,candidate=changed))
        self.assertNotEqual(first,runner.profile_fingerprint(template,components))

    def test_candidate_selectors_disable_old_same_names_by_path_and_preserve_exact_new_paths(self):
        plan=self.plan();selected=plan['selected'];old=[{**s,'path':str(ROOT/'skills'/s['name']/'SKILL.md')} for s in selected]
        inventory=[*selected,*old,{'name':'unrelated','path':'D:/unrelated/SKILL.md','enabled':True,'description':'other'}]
        chosen,selectors=runner.select_native_skills(inventory,self.package,candidate=plan)
        self.assertEqual(selected,chosen)
        self.assertTrue(all({'path':s['path'],'enabled':False} in selectors for s in old))
        self.assertTrue(all({'path':s['path'],'enabled':True} in selectors for s in selected))
        with self.assertRaisesRegex(ValueError,'duplicate_project_names'):runner.select_native_skills(inventory,self.package)

    def test_selected_metadata_change_cannot_be_hidden_by_equal_names(self):
        plan=self.plan();inventory=copy.deepcopy(plan['selected']);inventory[0]['description']+=' changed'
        with self.assertRaisesRegex(ValueError,'candidate_native_metadata_changed'):
            runner.select_native_skills(inventory,self.package,candidate=plan)

    def test_candidate_runtime_refuses_development_tool_modules(self):
        from evals.native_host_candidate import assert_candidate_runtime
        with self.assertRaisesRegex(ValueError,'candidate_runtime_not_source_bound'):
            assert_candidate_runtime(self.plan())

    def case_policy(self,case='G6'):
        self.review['review_version']=2
        self.review.pop('workspace',None)
        self.review['workspace_policy']={'kind':'owned_project_case_roots','allowed_cases':['G6','HOST-PAT-F']}
        work=self.project/'workspaces'/case;work.mkdir(parents=True,exist_ok=True)
        self.spec['workspace']=str(work);self.bind_review()
        return work

    def test_v2_runtime_identity_can_qualify_separate_reviewed_case_workspaces(self):
        self.case_policy();first=self.plan();components=runner.source_components(package=self.package)
        template={'per_process_config':{},'environment_keys':[]}
        fingerprint=runner.profile_fingerprint(template,components,candidate=first)
        self.case_policy('HOST-PAT-F');second=self.plan()
        self.assertNotEqual(first['workspace'],second['workspace'])
        self.assertEqual(first['review_sha256'],second['review_sha256'])
        self.assertEqual(fingerprint,runner.profile_fingerprint(template,components,candidate=second))

    def test_v2_policy_does_not_allow_an_unlisted_case_or_nested_directory(self):
        self.case_policy()
        for work in [self.project/'workspaces/HOST-PAT-M',self.project/'workspaces/G6/input']:
            work.mkdir(parents=True,exist_ok=True);self.spec['workspace']=str(work)
            with self.assertRaisesRegex(ValueError,'candidate_project_layout'):self.plan()

    def test_v2_workspace_policy_rejects_windows_aliases_and_traversal(self):
        self.case_policy()
        for cases in [['G6','g6'],['../escape'],['G6/input'],['CON'],[],[True]]:
            self.review['workspace_policy']['allowed_cases']=cases;self.bind_review()
            with self.assertRaisesRegex(ValueError,'candidate_workspace_policy'):self.plan()

    def test_v1_workspace_and_v2_policy_cannot_be_ambiguously_mixed(self):
        self.case_policy();self.review['workspace']=str(self.project/'workspace');self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_workspace_policy'):self.plan()
        self.review['review_version']=1;self.bind_review()
        with self.assertRaisesRegex(ValueError,'candidate_workspace_policy'):self.plan()

    def test_changed_case_policy_requires_new_runtime_qualification(self):
        self.case_policy();plan=self.plan();template={'per_process_config':{},'environment_keys':[]}
        components=runner.source_components(package=self.package)
        first=runner.profile_fingerprint(template,components,candidate=plan)
        plan=copy.deepcopy(plan);plan['workspace_policy']['allowed_cases'].append('HOST-PAT-M')
        self.assertNotEqual(first,runner.profile_fingerprint(template,components,candidate=plan))

    def test_qualifier_and_case_data_are_separate_even_under_the_same_project(self):
        from tools.host_bridge import HostToolBridge
        own=self.case_policy();self.plan();(own/'input').mkdir();(own/'input/own.md').write_bytes(b'own synthetic fixture')
        other=self.project/'workspaces/HOST-PAT-F/input';other.mkdir(parents=True);(other/'source.md').write_bytes(b'other synthetic fixture')
        control=self.control/'case-bridge';control.mkdir()
        bridge=HostToolBridge(self.package,own,control,self.pin)
        self.assertTrue(bridge.call('case_read',{'scope':'workspace','path':'input/own.md'})['success'])
        self.assertFalse(bridge.call('case_read',{'scope':'workspace','path':'../HOST-PAT-F/input/source.md'})['success'])

    def test_v2_actual_phase_identity_must_match_its_named_case_root(self):
        self.case_policy();self.spec.update(kind='known_host_phase',case_id='HOST-PAT-F')
        with self.assertRaisesRegex(ValueError,'candidate_case_workspace_mismatch'):self.plan()
        self.case_policy('HOST-PAT-F');self.assertEqual(str(self.project/'workspaces/HOST-PAT-F'),self.plan()['workspace'])
        self.spec['kind']='casefree'
        with self.assertRaisesRegex(ValueError,'candidate_case_workspace_mismatch'):self.plan()

    def isolated_spec(self):
        folder=self.development/'evals';folder.mkdir()
        for name in ['native_host_runner.py','native_host_session.py','native_host_bridge.py','native_host_candidate.py']:
            (folder/name).write_bytes((ROOT/'evals'/name).read_bytes())
        paths=[*folder.glob('*.py'),*(self.package/'tools'/name for name in ['host_bridge.py','host_bridge_worker.py','bundle.py','codex_host.py'])]
        spec={**self.spec,'components':{str(path):sha(path.read_bytes()) for path in paths}}
        path=self.control/'inspect-spec.json';path.write_bytes(canonical(spec))
        return path,folder/'native_host_candidate.py'

    def test_isolated_bootstrap_ignores_valid_unlisted_tool_and_evaluation_bytecode(self):
        path,bootstrap=self.isolated_spec()
        for source in [self.package/'tools/host_bridge.py',self.development/'evals/native_host_bridge.py']:
            cache=source.parent/'__pycache__';cache.mkdir(exist_ok=True)
            code=compile("raise RuntimeError('UNLISTED_BYTECODE_EXECUTED')",str(source),'exec');info=source.stat()
            raw=importlib.util.MAGIC_NUMBER+struct.pack('<III',0,int(info.st_mtime)&0xffffffff,info.st_size)+marshal.dumps(code)
            (cache/(source.stem+'.'+sys.implementation.cache_tag+'.pyc')).write_bytes(raw)
        parent_module=sys.modules['tools.host_bridge']
        process=subprocess.run([getattr(sys,'_base_executable',None) or sys.executable,'-I','-S','-B','-X','utf8',str(bootstrap),
            '--spec',str(path),'--sha256',sha(path.read_bytes()),'--inspect'],cwd=self.work,capture_output=True,timeout=30)
        self.assertEqual(0,process.returncode,process.stderr.decode('utf-8'))
        report=json.loads(process.stdout);self.assertEqual('source_bound_current_candidate',report['status'])
        self.assertEqual(self.package/'tools/host_bridge.py',Path(report['actual_module_origins']['tools.host_bridge']))
        self.assertEqual(self.development/'evals/native_host_bridge.py',Path(report['actual_module_origins']['evals.native_host_bridge']))
        self.assertFalse(report['model_or_native_process_started']);self.assertIs(parent_module,sys.modules['tools.host_bridge'])

    def test_actual_copied_file_producer_is_used_inside_the_isolated_candidate_runtime(self):
        path,bootstrap=self.isolated_spec();(self.work/'input').mkdir();control=self.control/'bridge';control.mkdir()
        resource=self.package/'skills/dyz-rendering/resources';spec=json.loads((resource/'reading-scope-example.json').read_bytes())
        for source in spec['sources']:
            origin=self.package/source['path'];(self.work/'input'/origin.name).write_bytes(origin.read_bytes());source['path']='input/'+origin.name
        (self.work/'input/spec.json').write_bytes(canonical(spec))
        program='''import json,runpy,sys
from pathlib import Path
ns=runpy.run_path(sys.argv[1],run_name="candidate_api")
runner,plan,spec=ns["prepare"](sys.argv[2],sys.argv[3])
bridge=runner.NativeHostBridge(plan["package"],plan["workspace"],sys.argv[4],plan["manifest_sha256"])
args={"input":"input/spec.json","output":"output/pack","mode":"synthetic"}
answers=[bridge.call("case_documents",args),bridge.call("case_documents",{**args,"verify":True}),bridge.call("case_docx_review",{"input":"output/pack/body/document.docx","output":"output/readback.json","mode":"synthetic"})]
print(json.dumps({"successes":[r["success"] for r in answers],"origin":sys.modules["tools.host_bridge"].__file__}))
'''
        process=subprocess.run([getattr(sys,'_base_executable',None) or sys.executable,'-I','-S','-B','-X','utf8','-c',program,
            str(bootstrap),str(path),sha(path.read_bytes()),str(control)],cwd=self.work,capture_output=True,timeout=30)
        self.assertEqual(0,process.returncode,process.stderr.decode('utf-8'))
        self.assertEqual([True]*3,json.loads(process.stdout)['successes'])
        manifest=json.loads((self.work/'output/pack/manifest.json').read_bytes());self.assertEqual('checked',manifest['reading_scope']['status'])
        report=json.loads((self.work/'output/readback.json').read_bytes())
        self.assertIn('合计覆盖31/51页',next(row['text'] for row in report['current']['bookmarks'] if row['name']=='Scope3'))
        for n in [1,2]:
            audit=json.loads((control/f'tool-{n:04}.audit.json').read_bytes())
            self.assertEqual(self.package/'tools/fidelity.py',Path(audit['loaded_tools_modules']['tools.fidelity']))


if __name__=='__main__':unittest.main()
