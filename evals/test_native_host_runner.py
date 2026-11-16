"""Offline phase/staging/source contracts. Never invokes a model or CLI."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from evals.native_host_session import SessionError, sha
from evals.native_host_runner import (DEVELOPER, NativeInputGuard, SKILLS, ToolDispatcher,
    output_matches, read_coverage, relative_path, run_frozen_phase, snapshot, stage_seed,
    validate_budget, validate_roots, validate_spec, verify_snapshot)
from evals.native_host_runner import source_components
from evals.native_host_runner import image_coverage, image_view_bindings, profile_fingerprint, stage_image_views, CLI_SHA


class StageTests(unittest.TestCase):
    def test_runtime_binding_covers_shared_worker_and_not_unused_legacy_worker(self):
        root = Path(__file__).resolve().parents[1]
        values = source_components()
        for name in ['host_bridge.py', 'host_bridge_worker.py', 'bundle.py', 'codex_host.py']:
            path = root / 'tools' / name
            self.assertEqual(sha(path.read_bytes()), values[str(path)])
        self.assertNotIn(str(root / 'evals/native_host_worker.py'), values)
        with mock.patch('evals.native_host_runner.digest', side_effect=lambda path: 'changed' if path.name == 'host_bridge_worker.py' else sha(path.read_bytes())):
            self.assertNotEqual(values, source_components())

    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.work=self.root/'work';self.work.mkdir()

    def seed(self,name,recipe_text,*,index_name='material-index.json',extra=None):
        folder=self.root/name;folder.mkdir()
        values={'request.md':b'controller request\n','input/recipes/source-input.json':recipe_text,
            'input/'+index_name:(json.dumps({'recipes':[{'runtime_input':'input/recipes/source-input.json',
                'mode':'synthetic','version':name}],'unrelated':'unchanged'})+'\n').encode(),
            'skills/demo/source.txt':b'fixed source\r\n'}
        values.update(extra or {})
        rows=[]
        for rel,raw in values.items():
            p=folder/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            rows.append({'path':rel,'sha256':sha(raw),'bytes':len(raw)})
        manifest=folder/'seed-manifest.json';manifest.write_text(json.dumps({'files':rows}),encoding='utf-8')
        return manifest,sha(manifest.read_bytes())

    def test_same_recipe_basename_is_versioned_without_overwriting_baseline(self):
        first,digest1=self.seed('v12',b'{"version":"1.2"}\n')
        before=stage_seed(first,digest1,self.work,1)
        baseline=self.work/'output/base/document.docx';baseline.parent.mkdir(parents=True);baseline.write_bytes(b'old binary')
        old=snapshot(self.work)
        second,digest2=self.seed('v13',b'{"version":"1.3"}\n',index_name='change-material-index.json')
        after=stage_seed(second,digest2,self.work,2,previous_files=old)
        verify_snapshot(self.work,old)
        self.assertEqual((self.work/'input/phase-1/recipes/source-input.json').read_bytes(),b'{"version":"1.2"}\n')
        self.assertEqual((self.work/'input/phase-2/recipes/source-input.json').read_bytes(),b'{"version":"1.3"}\n')
        current=json.loads((self.work/'input/change-material-index.json').read_bytes())
        self.assertEqual(current['recipes'][0]['runtime_input'],'input/phase-2/recipes/source-input.json')
        self.assertEqual(current['unrelated'],'unchanged')
        self.assertFalse((self.work/'request.md').exists())
        self.assertNotEqual(before['path_projection'],after['path_projection'])

    def test_changed_source_fails_before_any_write(self):
        path,digest=self.seed('seed',b'{}')
        (path.parent/'skills/demo/source.txt').write_bytes(b'bad source')
        with self.assertRaisesRegex(SessionError,'seed_file_changed'):
            stage_seed(path,digest,self.work,1)
        self.assertEqual(snapshot(self.work),[])

    def test_collision_does_not_partly_stage_new_phase(self):
        one,d1=self.seed('v12',b'{"value":"first"}')
        stage_seed(one,d1,self.work,1)
        old=snapshot(self.work)
        two,d2=self.seed('v13',b'{"value":"second"}')  # same index path, incompatible content
        with self.assertRaisesRegex(SessionError,'seed_destination_collision'):
            stage_seed(two,d2,self.work,2,previous_files=old)
        self.assertEqual(snapshot(self.work),old)

    def test_unowned_existing_workspace_or_changed_baseline_rejected(self):
        path,digest=self.seed('seed',b'{}')
        (self.work/'foreign.txt').write_bytes(b'private')
        with self.assertRaisesRegex(SessionError,'workspace_not_owned_or_snapshot_changed'):
            stage_seed(path,digest,self.work,1)
        old=snapshot(self.work);(self.work/'foreign.txt').write_bytes(b'changed')
        with self.assertRaises(SessionError):stage_seed(path,digest,self.work,2,previous_files=old)

    def test_scorer_or_traversal_manifest_rejected_before_write(self):
        path,_=self.seed('seed',b'{}',extra={'input/scorer-only.json':b'grades'})
        with self.assertRaisesRegex(SessionError,'scorer_in_seed'):
            stage_seed(path,sha(path.read_bytes()),self.work,1)
        self.assertEqual(snapshot(self.work),[])
        data=json.loads(path.read_bytes());data['files'][0]['path']='../outside.txt';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(SessionError,'unsafe_relative_path'):
            stage_seed(path,sha(path.read_bytes()),self.work,1)

    def test_shared_data_is_not_rewritten(self):
        path,digest=self.seed('one',b'{}');stage_seed(path,digest,self.work,1)
        data=self.work/'input/phase-1/materials/skills/demo/source.txt';before=data.stat().st_mtime_ns
        second,d2=self.seed('two',b'{"version":"new"}',index_name='change-material-index.json')
        stage_seed(second,d2,self.work,2,previous_files=snapshot(self.work))
        self.assertEqual(data.stat().st_mtime_ns,before)
        self.assertEqual(data.read_bytes(),(self.work/'input/phase-2/materials/skills/demo/source.txt').read_bytes())

    def test_recipe_paths_and_worker_index_project_without_changing_package_reads_or_literal_text(self):
        value={'sources':[{'id':'Source','path':'skills/demo/source.txt','sha256':sha(b'fixed source\r\n')}],
               'literal_text':'skills/demo/source.txt','classification':'synthetic'}
        raw=(json.dumps(value)+'\n').encode()
        manifest,digest=self.seed('one',raw)
        index=manifest.parent/'input/material-index.json'
        payload=json.loads(index.read_bytes())
        payload['source_files']=[{'worker_staged_path':'skills/demo/source.txt',
            'model_read':{'scope':'package','path':'skills/demo/source.txt'}}]
        payload['recipes'][0].update(source_package_path='skills/demo/recipe.json',sha256=sha(raw))
        index.write_text(json.dumps(payload),encoding='utf-8')
        rows=json.loads(manifest.read_bytes())
        for row in rows['files']:
            p=manifest.parent/row['path'];row.update(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
        manifest.write_text(json.dumps(rows),encoding='utf-8')
        receipt=stage_seed(manifest,sha(manifest.read_bytes()),self.work,1)
        staged=self.work/'input/phase-1/recipes/source-input.json'
        actual=json.loads(staged.read_bytes())
        self.assertEqual('input/phase-1/materials/skills/demo/source.txt',actual['sources'][0]['path'])
        self.assertEqual(value['literal_text'],actual['literal_text'])
        self.assertEqual(value['sources'][0]['sha256'],actual['sources'][0]['sha256'])
        current=json.loads((self.work/'input/material-index.json').read_bytes())
        self.assertEqual(sha(staged.read_bytes()),current['recipes'][0]['runtime_sha256'])
        self.assertEqual(sha(raw),current['recipes'][0]['source_package_sha256'])
        self.assertEqual(payload['source_files'][0]['model_read'],current['source_files'][0]['model_read'])
        self.assertEqual(actual['sources'][0]['path'],current['source_files'][0]['worker_staged_path'])
        self.assertEqual([{'pointer':'/sources/0/path','from':'skills/demo/source.txt',
            'to':'input/phase-1/materials/skills/demo/source.txt'}],receipt['recipe_path_relocations']['input/phase-1/recipes/source-input.json'])
        self.assertEqual(raw,(manifest.parent/'input/recipes/source-input.json').read_bytes())
        self.assertFalse((self.work/'skills').exists())

    def test_projected_index_advisory_matches_phase_paths_and_preserves_seed_note(self):
        old_note = 'Data at worker workspace root; recipes are not rebased.'
        payload = {'source_note': old_note, 'unrelated': 'keep literal text'}
        raw_index = (json.dumps(payload) + '\n').encode()
        manifest, digest = self.seed('note', b'{}', extra={'input/material-index.json': raw_index})
        stage_seed(manifest, digest, self.work, 2)
        current = json.loads((self.work/'input/material-index.json').read_bytes())
        self.assertIn('input/phase-2/materials/', current['source_note'])
        self.assertIn('input/phase-2/recipes/', current['source_note'])
        self.assertIn('runtime_sha256', current['source_note'])
        self.assertIn('source_package_sha256', current['source_note'])
        self.assertNotIn('worker workspace root', current['source_note'])
        self.assertEqual(current['source_note_original'], {
            'scope': 'historical_seed_advisory_not_current_runtime_guidance',
            'source_path': 'input/material-index.json', 'source_sha256': sha(raw_index), 'value': old_note})
        self.assertEqual('keep literal text', current['unrelated'])
        self.assertEqual(raw_index, (manifest.parent/'input/material-index.json').read_bytes())

    def test_projected_index_advisory_provenance_collision_fails_before_writes(self):
        payload = {'source_note': 'old', 'source_note_original': {'private_original': 'preserve'}}
        manifest, digest = self.seed('collision', b'{}', extra={
            'input/material-index.json': json.dumps(payload).encode()})
        with self.assertRaisesRegex(SessionError, 'seed_index_provenance_collision'):
            stage_seed(manifest, digest, self.work, 1)
        self.assertEqual([], snapshot(self.work))

    def test_unstaged_legacy_recipe_source_is_rejected_before_any_write(self):
        manifest,digest=self.seed('one',b'{"sources":[{"path":"skills/private/controller.txt"}]}')
        with self.assertRaisesRegex(SessionError,'recipe_source_not_staged'):
            stage_seed(manifest,digest,self.work,1)
        self.assertEqual([],snapshot(self.work))

    def test_invalid_recipe_is_rejected_before_any_write(self):
        manifest,digest=self.seed('one',b'not json')
        with self.assertRaisesRegex(SessionError,'seed_recipe_json_invalid'):
            stage_seed(manifest,digest,self.work,1)
        self.assertEqual([],snapshot(self.work))

    def test_relative_paths_and_overlapping_roots(self):
        for path in ['../x','C:/x','a\\..\\b','/root','input/CON.txt','input/x.','input/x ']:
            with self.subTest(path=path),self.assertRaises(SessionError):relative_path(path)
        package=self.root/'package';package.mkdir()
        with self.assertRaisesRegex(SessionError,'runner_roots_overlap'):
            validate_roots(package,self.work,self.work/'control')
        self.assertFalse((self.work/'control').exists())


class FileRecoveryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / 'actor'
        (self.work / 'input').mkdir(parents=True)
        (self.work / 'input/original.txt').write_bytes(b'fixed original synthetic input')
        self.retained = snapshot(self.work)
        self.old_spec = {'kind': 'known_host_phase', 'case_id': 'HOST-PAT-F', 'phase': 1,
                         'prompt': 'original frozen task', 'components': {'old': 'source'}, 'profile_fingerprint': 'old'}
        self.failed = {'kind': 'known_host_phase', 'case_id': 'HOST-PAT-F', 'phase': 1, 'status': 'native_phase_failed',
                       'profile_fingerprint': 'old', 'callbacks': [{'success': True}], 'workspace_files': self.retained}
        self.old_spec_ref = self.save('failed-spec.json', self.old_spec)
        self.failed_ref = self.save('failed-result.json', self.failed)
        self.assessment = {'status': 'failed_native_idle_timeout_incomplete_stream_no_wholecase_acceptance',
            'case_id': 'HOST-PAT-F', 'phase': 1, 'spec_sha256': self.old_spec_ref['sha256'],
            'execution_components': self.old_spec['components'], 'actual_callbacks': 1,
            'failed_request': {'callback_executed': False, 'completed_function_item': False, 'genuine_terminal': False}}
        assessment_ref = self.save('failed-assessment.json', self.assessment)
        state = {'kind': 'declared_file_only_recovery_of_known_internal_task', 'status': 'interrupted', 'retained_files': self.retained}
        (self.work / 'input/recovery-state.json').write_text(json.dumps(state), encoding='utf-8')
        baseline = snapshot(self.work)
        self.prepared = {'status': 'prepared_file_recovery_only_not_admitted_not_executed', 'original_case_id': 'HOST-PAT-F',
            'workspace': str(self.work), 'original_failed_spec_sha256': self.old_spec_ref['sha256'],
            'original_failed_result_sha256': self.failed_ref['sha256'], 'initial_files_and_protected_baseline': baseline,
            'frozen_proposed_recovery_prompt': 'declared recovery of original frozen task'}
        prepared_ref = self.save('prepared.json', self.prepared)
        admission = self.save('g6.json', {'status': 'passed_native_runner_g6_only', 'profile_fingerprint': 'new', 'components': {'new': 'source'}})
        self.spec = {'kind': 'known_host_recovery', 'case_id': 'HOST-PAT-F', 'phase': 1, 'workspace': str(self.work),
            'prompt': self.prepared['frozen_proposed_recovery_prompt'], 'initial_files': baseline, 'protected_files': baseline,
            'components': {'new': 'source'}, 'admission': admission,
            'recovery_binding': {'prepared': prepared_ref, 'predecessor_spec': self.old_spec_ref,
                                 'predecessor_result': self.failed_ref, 'predecessor_assessment': assessment_ref}}
        self.inputs = {'cases': [{'id': 'HOST-PAT-F', 'phases': [{'number': 1, 'prompt': 'original frozen task'}]}]}

    def save(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding='utf-8')
        return {'path': str(path), 'sha256': sha(path.read_bytes())}

    def validate(self):
        from evals import native_host_runner
        return native_host_runner.validate_file_recovery(self.spec, 'new', self.inputs)

    def test_current_file_recovery_has_its_own_binding_and_no_source_mutation(self):
        before = snapshot(self.work)
        result = self.validate()
        self.assertEqual(result['scope'], 'declared_known_file_recovery_not_original_clean_case')
        self.assertEqual(result['protected_file_count'], len(before))
        self.assertEqual(snapshot(self.work), before)

    def test_recovery_prompt_cannot_be_substituted_for_original_or_other_task(self):
        self.spec['prompt'] = 'original frozen task'
        with self.assertRaisesRegex(SessionError, 'recovery_prompt_changed'):
            self.validate()

    def test_changed_retained_source_or_added_score_file_is_rejected(self):
        path = self.work / 'input/original.txt'
        path.write_bytes(b'changed source')
        with self.assertRaises(SessionError):
            self.validate()
        path.write_bytes(b'fixed original synthetic input')
        (self.work / 'input/score.txt').write_bytes(b'author grades forbidden')
        with self.assertRaisesRegex(SessionError, 'recovery_workspace_changed'):
            self.validate()

    def test_completed_or_ambiguous_mutation_predecessor_cannot_be_relabelled(self):
        for completed in [True, False]:
            failed = copy.deepcopy(self.failed)
            assessment = copy.deepcopy(self.assessment)
            if completed:
                failed['status'] = 'native_phase_loop_completed_pending_author_artifact_review'
            else:
                assessment['failed_request']['callback_executed'] = True
            self.spec['recovery_binding']['predecessor_result'] = self.save('modified-result.json', failed)
            self.spec['recovery_binding']['predecessor_assessment'] = self.save('modified-assessment.json', assessment)
            prepared = copy.deepcopy(self.prepared)
            prepared['original_failed_result_sha256'] = self.spec['recovery_binding']['predecessor_result']['sha256']
            self.spec['recovery_binding']['prepared'] = self.save('modified-prepared.json', prepared)
            with self.subTest(completed=completed), self.assertRaises(SessionError):
                self.validate()

    def test_stale_g6_and_unprotected_retained_files_are_rejected(self):
        self.spec['admission'] = self.save('stale-g6.json', {'status': 'passed_native_runner_g6_only',
            'profile_fingerprint': 'old', 'components': {'old': 'source'}})
        with self.assertRaisesRegex(SessionError, 'current_runner_g6_not_admitted'):
            self.validate()
        self.spec['admission'] = self.save('current-g6.json', {'status': 'passed_native_runner_g6_only',
            'profile_fingerprint': 'new', 'components': {'new': 'source'}})
        self.spec['protected_files'] = self.spec['protected_files'][:-1]
        with self.assertRaisesRegex(SessionError, 'recovery_baseline_not_protected'):
            self.validate()


class NativeTaskConfigTests(unittest.TestCase):
    def template(self):
        prefix = 'model_providers.dyz_official_single_attempt.'
        values = {'name': 'DYZ task official single attempt', 'wire_api': 'responses', 'requires_openai_auth': True,
                  'request_max_retries': 0, 'stream_max_retries': 0, 'stream_idle_timeout_ms': 300000,
                  'supports_websockets': False}
        return {'per_process_config': {'model_provider': 'dyz_official_single_attempt',
                                      **{prefix + k: v for k, v in values.items()}}}

    def build(self, template=None, url='http://127.0.0.1:12345/backend-api/codex'):
        from evals import native_host_runner
        return native_host_runner.build_native_config(template or self.template(), url, Path('synthetic-catalog.json'))

    def test_alias_uses_dynamic_loopback_without_mutating_template(self):
        template = self.template()
        before = copy.deepcopy(template)
        config = self.build(template)
        self.assertEqual(template, before)
        self.assertEqual(config['model_provider'], 'dyz_official_single_attempt')
        self.assertEqual(config['model_providers.dyz_official_single_attempt.base_url'], config['openai_base_url'])
        self.assertEqual(config['model_providers.dyz_official_single_attempt.stream_max_retries'], 0)
        self.assertIs(config['model_providers.dyz_official_single_attempt.requires_openai_auth'], True)
        self.assertFalse(config['sandbox_workspace_write.network_access'])

    def test_unreviewed_provider_auth_retry_and_endpoint_changes_are_rejected(self):
        for key, value in [('requires_openai_auth', False), ('stream_max_retries', 1),
                           ('request_max_retries', False), ('stream_idle_timeout_ms', 600000), ('env_key', 'PRIVATE_KEY')]:
            template = self.template()
            template['per_process_config']['model_providers.dyz_official_single_attempt.' + key] = value
            with self.subTest(key=key), self.assertRaisesRegex(SessionError, 'unreviewed_native_transport_config'):
                self.build(template)
        for url in ['https://example.com/backend-api/codex', 'http://localhost:12345/backend-api/codex',
                    'http://127.0.0.1:0/backend-api/codex']:
            with self.subTest(url=url), self.assertRaisesRegex(SessionError, 'native_relay_url_required'):
                self.build(url=url)

    def test_legacy_openai_still_works_but_reserved_overrides_are_rejected(self):
        config = self.build({'per_process_config': {'features.shell_tool': False}})
        self.assertNotIn('model_provider', config)
        self.assertFalse(config['features.shell_tool'])
        with self.assertRaisesRegex(SessionError, 'unreviewed_native_transport_config'):
            self.build({'per_process_config': {'model_providers.openai.name': 'forbidden override'}})


class SpecTests(unittest.TestCase):
    def budget(self):return {'max_requests':6,'max_calls':12,'max_seconds':600,'review_seconds':300}

    def test_budget_type_scope_and_caps(self):
        validate_budget(self.budget())
        for key,value in [('max_requests',0),('max_calls',True),('max_seconds',1801),('review_seconds',0)]:
            data=self.budget();data[key]=value
            with self.subTest(key=key),self.assertRaises(SessionError):validate_budget(data)
        with self.assertRaises(SessionError):validate_budget({**self.budget(),'max_tokens':100})
        validate_budget({**self.budget(),'max_requests':81})
        with self.assertRaises(SessionError):validate_budget({**self.budget(),'max_requests':82})

    def spec(self):
        return {**{key:None for key in ['components','cli','authority','package','workspace','control',
            'profile_template','profile_fingerprint','catalog']},'kind':'casefree','budget':self.budget(),
            'prompt':'read/write probe','protected_files':[],'initial_files':[],'token_cap':None}

    def test_host_admission_and_no_generation_token_cap(self):
        data=self.spec();validate_spec(data)
        data['token_cap']=100
        with self.assertRaisesRegex(SessionError,'generation_token_cap'):validate_spec(data)
        data=self.spec();data['kind']='known_host_phase'
        with self.assertRaisesRegex(SessionError,'host_admission_fields'):validate_spec(data)
        data=self.spec();data['image_views']=[{'source_sha256':'s'}]
        with self.assertRaisesRegex(SessionError,'image_view_review_required'):validate_spec(data)

    def test_unreviewed_transport_rejected_before_control_or_listener_creation(self):
        from evals import native_host_runner as runner
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve()
            package,work=root/'package',root/'workspace'
            package.mkdir();work.mkdir();(root/'outputs').mkdir()
            control=root/'outputs'/'unstarted-control'
            cli=root/'synthetic-cli.exe';cli.write_bytes(b'not executable')
            spec_path,authority,template_path=(root/name for name in ['spec.json','authority.json','template.json'])
            components={'bound':'synthetic'}
            data={**self.spec(),'components':components,'cli':str(cli),'package':str(package),
                  'workspace':str(work),'control':str(control),'authority':{'path':str(authority)},
                  'profile_template':{'path':str(template_path),'sha256':'frozen'},'profile_fingerprint':'frozen'}
            template={'environment_keys':[],'per_process_config':{'model_provider':'unreviewed'}}
            records={spec_path:data,authority:{},template_path:template}
            with mock.patch.multiple(runner,CLI_PATH=cli,CLI_SHA=sha(cli.read_bytes()),
                    PACKAGE_PATH=package,DEVELOPMENT_ROOT=root), \
                 mock.patch.object(runner,'checked_json',side_effect=lambda path, expected:records[Path(path)]), \
                 mock.patch.object(runner,'source_components',return_value=components), \
                 mock.patch.object(runner,'verify_bundle'), \
                 mock.patch.object(runner,'profile_fingerprint',return_value='frozen'), \
                 mock.patch.object(runner,'NativeHostBridge',side_effect=AssertionError('bridge must not be created')) as bridge, \
                 mock.patch.object(runner,'NativeRelay',side_effect=AssertionError('listener must not start')) as relay, \
                 mock.patch.object(runner.subprocess,'Popen') as launch:
                with self.assertRaisesRegex(SessionError,'unreviewed_native_transport_config'):
                    run_frozen_phase(spec_path,'frozen')
                bridge.assert_not_called();relay.assert_not_called();launch.assert_not_called()
            self.assertFalse(control.exists())

    def test_image_view_identity_is_bound_but_staging_path_is_not_profile_state(self):
        template={'per_process_config':{},'environment_keys':[]}
        a=[{'source_sha256':'source','view_sha256':'view','view_path':'old/owned/file.png'}]
        b=[{**a[0],'view_path':'new/owned/file.png'}]
        self.assertEqual(profile_fingerprint(template,{},a),profile_fingerprint(template,{},b))
        b[0]['view_sha256']='different'
        self.assertNotEqual(profile_fingerprint(template,{},a),profile_fingerprint(template,{},b))

    def test_request_byte_budget_is_profile_state_and_does_not_change_tool_or_call_contract(self):
        from evals import native_host_runner as runner
        template={'per_process_config':{},'environment_keys':[]}
        first=profile_fingerprint(template,{})
        with mock.patch.object(runner,'FROZEN_REQUEST_LIMITS',{
                'max_request_body_bytes':2_000_000,'body_read_timeout_seconds':30}):
            self.assertNotEqual(first,profile_fingerprint(template,{}))
        validate_budget(self.budget())

    def test_view_staging_requires_review_and_current_asset_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();assets=root/'outputs';assets.mkdir();control=assets/'control';control.mkdir()
            image=assets/'view.png';image.write_bytes(b'bounded fixture asset')
            policy={'source_sha256':'source','view_sha256':sha(image.read_bytes()),'view_path':str(image)}
            review=assets/'review.json';value={'status':'passed_known_internal_image_views_only','cli_sha256':CLI_SHA,'bindings':image_view_bindings([policy])}
            review.write_text(json.dumps(value))
            spec={'image_views':[policy],'image_view_review':{'path':str(review),'sha256':sha(review.read_bytes())}}
            image.write_bytes(b'changed')
            with mock.patch('evals.native_host_runner.DEVELOPMENT_ROOT',root):
                with self.assertRaisesRegex(SessionError,'image_view_asset_changed'):stage_image_views(spec,control)
            self.assertFalse((control/'image-views').exists())
            image.write_bytes(b'bounded fixture asset')
            with mock.patch('evals.native_host_runner.DEVELOPMENT_ROOT',root):
                staged=stage_image_views(spec,control)
            self.assertEqual(Path(staged[0]['view_path']).read_bytes(),image.read_bytes())
            self.assertTrue(Path(staged[0]['view_path']).is_relative_to(control/'image-views'))
            self.assertEqual(image_view_bindings(staged),image_view_bindings([policy]))

    def test_no_process_starts_on_components_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'spec.json';data=self.spec();data['components']={}
            path.write_text(json.dumps(data))
            with mock.patch('evals.native_host_runner.subprocess.Popen') as launch:
                with self.assertRaisesRegex(SessionError,'runner_components_changed'):
                    run_frozen_phase(path,sha(path.read_bytes()))
                launch.assert_not_called()


class InputGuardTests(unittest.TestCase):
    def setUp(self):
        self.selected=[{'name':name,'description':'Original '+name,'path':'D:/fixed/skills/'+name+'/SKILL.md'}
                       for name in sorted(SKILLS)]
        meta='<skills_instructions>\n- `r0` = `D:/fixed`\n'+ '\n'.join(
            f"- {s['name']}: {s['description']} (file: r0/skills/{s['name']}/SKILL.md)" for s in self.selected)+'\n</skills_instructions>'
        self.first={'input':[{'type':'message','role':'developer','content':[{'type':'input_text','text':DEVELOPER},
                {'type':'input_text','text':meta}]},{'type':'message','role':'user','content':[{'type':'input_text','text':'task'}]}]}
        self.guard=NativeInputGuard(self.selected);self.guard.relay=SimpleNamespace(output_items={})

    def test_actual6_required_not_a_metadata_stub(self):
        self.assertTrue(self.guard(self.first,True)['selected6_descriptions_exact'])
        changed=copy.deepcopy(self.first);changed['input'][0]['content'][1]['text']=changed['input'][0]['content'][1]['text'].replace('Original dyz-patent','Different')
        with self.assertRaisesRegex(SessionError,'project_description_mismatch'):NativeInputGuard(self.selected)(changed,True)

    def test_other_skill_or_wrong_path_rejected(self):
        for extra in ['\n- other: Other (file: r0/other/SKILL.md)','']:
            changed=copy.deepcopy(self.first)
            if extra:changed['input'][0]['content'][1]['text']+=extra
            else:changed['input'][0]['content'][1]['text']=changed['input'][0]['content'][1]['text'].replace('r0/skills/dyz-patent/','r0/foreign/dyz-patent/')
            with self.assertRaises(SessionError):NativeInputGuard(self.selected)(changed,True)

    def test_context_or_unexplained_history_cannot_change(self):
        self.guard(self.first,True)
        changed=copy.deepcopy(self.first);changed['input'][1]['content'][0]['text']='secret grader'
        with self.assertRaisesRegex(SessionError,'initial_context_changed'):self.guard(changed,False)
        changed=copy.deepcopy(self.first);changed['input'].append({'type':'message','id':'unknown','role':'assistant','content':[]})
        with self.assertRaisesRegex(SessionError,'unexplained_native_history'):self.guard(changed,False)

    def test_native_text_tool_result_must_be_exact(self):
        self.guard(self.first,True);self.guard.expected_outputs['c']=[{'type':'inputText','text':'full original text'}]
        changed=copy.deepcopy(self.first);changed['input'].append({'type':'function_call_output','call_id':'c','output':'full original text'})
        self.assertEqual(self.guard(changed,False)['verified_call_ids'],['c'])
        changed['input'][-1]['output']='...truncated...'
        with self.assertRaisesRegex(SessionError,'native_tool_output_changed_or_truncated'):self.guard(changed,False)

    def test_only_empty_response_arrays_are_omitted(self):
        self.guard(self.first,True)
        source={'type':'message','id':'m','role':'assistant','content':[{'type':'output_text','text':'actual','annotations':[],'logprobs':[]}]}
        self.guard.relay.output_items['m']=source
        changed=copy.deepcopy(self.first);changed['input'].append({'type':'message','id':'m','role':'assistant','content':[{'type':'output_text','text':'actual'}]})
        self.guard(changed,False)
        self.guard.relay.output_items['m']['content'][0]['annotations']=[{'real':'annotation'}]
        with self.assertRaisesRegex(SessionError,'native_history_changed'):self.guard(changed,False)

    def test_image_output_matches_exact_bytes_and_text(self):
        expected=[{'type':'inputText','text':'metadata'},{'type':'inputImage','imageUrl':'data:image/png;base64,YWJj'}]
        actual=[{'type':'input_text','text':'metadata'},{'type':'input_image','image_url':'data:image/png;base64,YWJj','detail':'original'}]
        self.assertTrue(output_matches(actual,expected))
        actual[1]['image_url']='data:image/png;base64,ZGlmZmVyZW50'
        self.assertFalse(output_matches(actual,expected))
        self.assertFalse(output_matches('metadata',expected))


class FakeBridge:
    def __init__(self,answer=None):
        self.calls=[];self.answer=answer or {'success':True,'contentItems':[{'type':'inputText','text':'{"success":true,"result":{"status":"blocked"}}'}]}
    def native_tool_result(self,params,**_):
        self.calls.append(params);return copy.deepcopy(self.answer)


class DispatchTests(unittest.TestCase):
    def setup_dispatch(self,tool='case_read',args=None,**kwargs):
        self.params={'callId':'c','threadId':'t','turnId':'v','tool':tool,'arguments':args or {'scope':'workspace','path':'input/source.txt'},'namespace':None}
        self.bridge=FakeBridge();self.relay=SimpleNamespace(calls={'c':{'name':tool,'arguments':self.params['arguments'],'namespace':None}},failed=None)
        self.guard=SimpleNamespace(expected_outputs={})
        return ToolDispatcher(self.bridge,self.relay,self.guard,thread_id='t',turn_id='v',max_calls=2,**kwargs)

    def test_literal_success_and_blocked_state_are_preserved(self):
        dispatch=self.setup_dispatch();answer,allowed=dispatch.handle(self.params)
        self.assertTrue(allowed);self.assertTrue(answer['success']);self.assertIn('blocked',answer['contentItems'][0]['text'])
        self.assertEqual(self.guard.expected_outputs['c'],answer['contentItems'])

    def test_wrong_session_source_or_duplicate_never_executes(self):
        for key,value in [('threadId','foreign'),('turnId','foreign'),('arguments',{'scope':'workspace','path':'other'})]:
            dispatch=self.setup_dispatch();changed={**self.params,key:value}
            with self.subTest(key=key),self.assertRaises(SessionError):dispatch.handle(changed)
            self.assertEqual(self.bridge.calls,[])
        dispatch=self.setup_dispatch();dispatch.handle(self.params)
        with self.assertRaisesRegex(SessionError,'duplicate_callback'):dispatch.handle(self.params)
        self.assertEqual(len(self.bridge.calls),1)

    def test_baseline_write_and_nested_bundle_overwrite_blocked(self):
        protected=[{'path':'work/base.md'},{'path':'output/old/body/document.docx'}]
        for tool,args in [('case_write',{'path':'work/base.md','text':'change'}),
                          ('case_documents',{'input':'input/recipe.json','output':'output/old','mode':'synthetic'})]:
            dispatch=self.setup_dispatch(tool,args,protected=protected)
            with self.assertRaises(SessionError):dispatch.handle(self.params)
            self.assertEqual(self.bridge.calls,[])

    def test_exact_negative_once_and_unexpected_failure_stops_forwarding(self):
        dispatch=self.setup_dispatch();self.bridge.answer={'success':False,'contentItems':[{'type':'inputText','text':'{"success":false,"error":"file_missing"}'}]}
        _,allowed=dispatch.handle(self.params);self.assertFalse(allowed);self.assertEqual(self.relay.failed,'unexpected_tool_failure')
        args={'scope':'workspace','path':'input/missing.txt'}
        expected={'tool':'case_read','arguments_sha256':sha(json.dumps(args,sort_keys=True,ensure_ascii=False).encode()),'error':'file_missing'}
        dispatch=self.setup_dispatch(args=args,expected_failures=[expected]);self.bridge.answer={'success':False,'contentItems':[{'type':'inputText','text':'{"success":false,"error":"file_missing"}'}]}
        answer,allowed=dispatch.handle(self.params);self.assertTrue(allowed);self.assertFalse(answer['success'])
        self.assertIsNone(self.relay.failed);self.assertTrue(dispatch.calls[0]['expected_negative'])

    def test_casefree_does_not_expand_to_skill_or_other_files(self):
        dispatch=self.setup_dispatch(args={'scope':'package','path':'skills/dyz-patent/SKILL.md'},casefree=True)
        with self.assertRaisesRegex(SessionError,'casefree_callback_scope'):dispatch.handle(self.params)
        self.assertEqual(self.bridge.calls,[])

    def test_typed_document_negative_requires_exact_arguments_and_code_once(self):
        args={'input':'input/channel-check-v1.json','output':'output/channel-check-document','mode':'synthetic','verify':True}
        expected={'tool':'case_documents','arguments_sha256':sha(json.dumps(args,sort_keys=True,ensure_ascii=False).encode()),
                  'error':'document_input_binding_changed'}
        failure={'success':False,'contentItems':[{'type':'inputText',
            'text':'{"success":false,"error":"document_input_binding_changed","result":{"exit_code":2}}'}]}
        for actual_args, actual_error in [(args,'document_contract_rejected'),
                ({**args,'input':'input/channel-check-v2.json'},'document_input_binding_changed')]:
            with self.subTest(arguments=actual_args,error=actual_error):
                dispatch=self.setup_dispatch('case_documents',actual_args,expected_failures=[expected],casefree=True)
                self.bridge.answer={'success':False,'contentItems':[{'type':'inputText','text':json.dumps({'success':False,'error':actual_error})}]}
                answer,allowed=dispatch.handle(self.params)
                self.assertFalse(answer['success']);self.assertFalse(allowed)
                self.assertEqual('unexpected_tool_failure',self.relay.failed)
                self.assertFalse(dispatch.calls[0]['expected_negative'])
        dispatch=self.setup_dispatch('case_documents',args,expected_failures=[expected],casefree=True)
        self.bridge.answer=failure
        answer,allowed=dispatch.handle(self.params)
        self.assertTrue(allowed);self.assertFalse(answer['success']);self.assertTrue(dispatch.calls[0]['expected_negative'])
        second={**self.params,'callId':'c2'}
        self.relay.calls['c2']=copy.deepcopy(self.relay.calls['c'])
        answer,allowed=dispatch.handle(second)
        self.assertFalse(allowed);self.assertFalse(answer['success']);self.assertFalse(dispatch.calls[1]['expected_negative'])
        self.assertEqual('unexpected_tool_failure',self.relay.failed)

    def test_casefree_document_probe_cannot_build_or_expand_its_paths(self):
        args={'input':'input/channel-check-v1.json','output':'output/channel-check-document','mode':'synthetic','verify':True}
        for changed in [{'verify':False},{'verify':1},{'mode':'research_example'},
                        {'input':'input/case.json'},{'output':'output/other'},{'extra':'value'}]:
            with self.subTest(changed=changed):
                dispatch=self.setup_dispatch('case_documents',{**args,**changed},casefree=True)
                with self.assertRaisesRegex(SessionError,'casefree_callback_scope'):dispatch.handle(self.params)
                self.assertEqual(self.bridge.calls,[])


class CoverageTests(unittest.TestCase):
    def record(self,start,end,total=10,hash_value='version1'):
        return {'tool':'case_read','arguments':{'scope':'package','path':'source.md'},'answer':{'success':True,
            'result':{'sha256':hash_value,'start_line':start,'end_line':end,'total_lines':total}}}

    def test_gap_or_unsent_result_is_not_complete(self):
        records=[self.record(1,5),self.record(7,10)]
        callbacks=[{'call_id':'a','bridge_record_ordinal':1},{'call_id':'b','bridge_record_ordinal':2}]
        values=read_coverage(records,callbacks,{'a','b'})
        self.assertFalse(values[0]['all_physical_lines_in_completed_model_input'])
        self.assertEqual(read_coverage(records,callbacks,set()),[])

    def test_ranges_merge_only_with_same_content_hash(self):
        callbacks=[{'call_id':'a','bridge_record_ordinal':1},{'call_id':'b','bridge_record_ordinal':2}]
        complete=read_coverage([self.record(1,5),self.record(6,10)],callbacks,{'a','b'})
        self.assertTrue(complete[0]['all_physical_lines_in_completed_model_input'])
        different=read_coverage([self.record(1,5),self.record(6,10,hash_value='version2')],callbacks,{'a','b'})
        self.assertEqual(len(different),2);self.assertTrue(all(not x['all_physical_lines_in_completed_model_input'] for x in different))

    def test_prepared_image_is_distinct_from_full_source_and_requires_completed_input(self):
        record={'tool':'case_image','arguments':{'scope':'package','path':'flow.png'},'answer':{'success':True,'result':{
            'sha256':'original','width':1400,'height':2070,'image_view':{'sha256':'prepared','width':1298,'height':1920}}}}
        callbacks=[{'call_id':'image','bridge_record_ordinal':1}]
        self.assertEqual(image_coverage([record],callbacks,set()),[])
        actual=image_coverage([record],callbacks,{'image'})[0]
        self.assertEqual(actual['source_sha256'],'original');self.assertEqual(actual['image_content_sha256'],'prepared')
        self.assertFalse(actual['original_resolution_bytes_in_completed_model_input'])

    def fragment_record(self,begin,end,total=50000,hash_value='same-source'):
        return {'tool':'case_read','arguments':{'scope':'workspace','path':'dense.json'},'answer':{'success':True,'result':{
            'sha256':hash_value,'start_line':1,'end_line':1,'total_lines':1,
            'line_fragments':[{'line':1,'from_column':begin,'to_column':end,'total_columns':total}]}}}

    def test_partial_line_or_gap_is_never_full_line_coverage(self):
        callbacks=[{'call_id':'a','bridge_record_ordinal':1},{'call_id':'b','bridge_record_ordinal':2}]
        records=[self.fragment_record(0,25000),self.fragment_record(25001,50000)]
        coverage=read_coverage(records,callbacks,{'a','b'})[0]
        self.assertFalse(coverage['all_physical_lines_in_completed_model_input']);self.assertEqual(coverage['ranges'],[])
        self.assertFalse(coverage['fragmented_line_coverage'][0]['complete_line_text_in_completed_model_input'])
        records[1]=self.fragment_record(25000,50000)
        self.assertFalse(read_coverage(records,callbacks,{'b'})[0]['all_physical_lines_in_completed_model_input'])
        coverage=read_coverage(records,callbacks,{'a','b'})[0]
        self.assertTrue(coverage['all_physical_lines_in_completed_model_input']);self.assertEqual(coverage['ranges'],[[1,1]])
        self.assertEqual(coverage['fragmented_line_coverage'][0]['ranges'],[[0,50000]])

    def test_different_source_versions_cannot_complete_a_fragmented_line(self):
        records=[self.fragment_record(0,25000),self.fragment_record(25000,50000,hash_value='changed-source')]
        callbacks=[{'call_id':'a','bridge_record_ordinal':1},{'call_id':'b','bridge_record_ordinal':2}]
        coverage=read_coverage(records,callbacks,{'a','b'})
        self.assertEqual(len(coverage),2);self.assertTrue(all(not x['all_physical_lines_in_completed_model_input'] for x in coverage))


class NativeFailureSummaryTests(unittest.TestCase):
    def frame(self, *, details='stream disconnected before completion: idle timeout waiting for SSE', status=None):
        return {'method': 'error', 'params': {'threadId': 'own-thread', 'turnId': 'own-turn', 'willRetry': True,
            'error': {'message': 'Reconnecting... 1/5', 'additionalDetails': details,
                      'codexErrorInfo': {'responseStreamDisconnected': {'httpStatusCode': status}}}}}

    def summarize(self, frame):
        from evals import native_host_runner
        return native_host_runner.native_error_summary(frame, thread_id='own-thread', turn_id='own-turn')

    def test_idle_error_is_bound_hash_only_and_not_server_completion(self):
        frame = self.frame()
        before = copy.deepcopy(frame)
        result = self.summarize(frame)
        self.assertEqual(result['classification'], 'response_stream_idle_timeout')
        self.assertIsNone(result['http_status_code'])
        self.assertIs(result['will_retry_reported'], True)
        self.assertEqual(result['server_state'], 'not_inferred_from_native_error')
        self.assertEqual(result['error_frame_sha256'], sha(json.dumps(frame, ensure_ascii=False, sort_keys=True).encode()))
        self.assertEqual(frame, before)
        self.assertNotIn('additionalDetails', result)
        self.assertNotIn('message', result)

    def test_unknown_native_error_details_never_enter_summary(self):
        frame = self.frame(details='private marker AUTH-EXAMPLE-SECRET', status='AUTH-EXAMPLE-SECRET')
        frame['params']['error']['codexErrorInfo'] = {'unknown-private-type': {'token': 'AUTH-EXAMPLE-SECRET'}}
        result = self.summarize(frame)
        self.assertEqual(result['classification'], 'native_reported_error')
        self.assertNotIn('AUTH-EXAMPLE-SECRET', json.dumps(result))
        self.assertNotIn('unknown-private-type', json.dumps(result))

    def test_other_disconnect_is_not_misclassified_as_idle(self):
        result = self.summarize(self.frame(details='private unexpected transport detail', status=429))
        self.assertEqual(result['classification'], 'response_stream_disconnected')
        self.assertEqual(result['http_status_code'], 429)
        self.assertNotIn('private unexpected transport detail', json.dumps(result))

    def test_foreign_thread_or_turn_is_rejected(self):
        for key in ['threadId', 'turnId']:
            frame = self.frame()
            frame['params'][key] = 'foreign'
            with self.subTest(key=key), self.assertRaisesRegex(SessionError, 'native_error_binding_mismatch'):
                self.summarize(frame)

    def test_observed_final_idle_other_variant_is_classified_without_details(self):
        frame = self.frame(details=None)
        frame['params'].update(willRetry=False)
        frame['params']['error'].update(codexErrorInfo='other',
            message='stream disconnected before completion: idle timeout waiting for SSE')
        before = copy.deepcopy(frame)
        result = self.summarize(frame)
        self.assertEqual(result['classification'], 'response_stream_idle_timeout')
        self.assertIs(result['will_retry_reported'], False)
        self.assertEqual(result['server_state'], 'not_inferred_from_native_error')
        self.assertEqual(frame, before)
        self.assertNotIn('message', result)

    def test_observed_final_eof_other_variant_is_distinct_from_idle(self):
        frame = self.frame(details=None)
        frame['params'].update(willRetry=False)
        frame['params']['error'].update(codexErrorInfo='other',
            message='stream disconnected before completion: stream closed before response.completed')
        result = self.summarize(frame)
        self.assertEqual(result['classification'], 'response_stream_eof')
        self.assertEqual(result['server_state'], 'not_inferred_from_native_error')
        self.assertIsNone(result['http_status_code'])

    def test_unknown_final_text_or_conflicting_details_remains_unknown(self):
        idle = 'stream disconnected before completion: idle timeout waiting for SSE'
        for message, details in [(idle + ' AUTH-EXAMPLE-SECRET', None), (idle, 'conflicting private detail')]:
            frame = self.frame(details=details)
            frame['params']['error'].update(codexErrorInfo='other', message=message)
            result = self.summarize(frame)
            self.assertEqual(result['classification'], 'native_reported_error')
            self.assertNotIn('AUTH-EXAMPLE-SECRET', json.dumps(result))
            self.assertNotIn('conflicting private detail', json.dumps(result))


if __name__=='__main__':unittest.main()
