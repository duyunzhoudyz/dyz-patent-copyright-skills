"""Phase F tests: unseen-task leakage guard, per-case blinding, hard-blocker benchmark aggregation,
honest cost accounting, expert trial-pack generation, and 3-consecutive-case upgrade gate.
"""
import hashlib
import hmac
import json
import os
import random
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals import benchmark_harness
from tools import trial_pack
from tools.core import ContractError, digest

ROOT = Path(__file__).resolve().parents[1]


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redaction_receipt(questions, history=(), *, artifact_hashes, case_id="C1", receipt_id="DEID-EV-01"):
    fields = {f"dispute_questions.{q['id']}.question": digest(q["question"]) for q in questions}
    fields.update({f"defect_history.{rec['defect_id']}.summary": digest(rec["summary"]) for rec in history})
    return {"receipt_id": receipt_id, "approved": True, "redactor_id": "SYNTHETIC-REDACTOR",
            "redacted_at": "2026-11-01T08:00:00Z", "case_id": case_id, "combination_id": "CN-patent-draft",
            "field_hashes": fields, "artifact_hashes": artifact_hashes}


class BenchmarkHarnessTests(unittest.TestCase):
    def test_case_pack_rejects_unseen_leakage_from_dev_or_known_hashes(self):
        dev_src = _h("known-dev-source")
        leaked = {
            "pack_id": "leak-test",
            "cases": [
                {"case_id": "DEV-1", "split": "dev_regression", "domain": "patent",
                 "prompt_sha256": _h("dev-p"), "source_sha256": dev_src},
                {"case_id": "UNSEEN-1", "split": "held_out_unseen", "domain": "patent",
                 "prompt_sha256": _h("unseen-p"), "source_sha256": dev_src},
            ],
        }
        report = benchmark_harness.validate_case_pack(leaked)
        self.assertEqual("rejected", report["status"])
        self.assertEqual(1, len(report["leakage_hits"]))
        with self.assertRaisesRegex(ContractError, "benchmark_unseen_leakage_detected"):
            benchmark_harness.require_valid_case_pack(leaked)

        # External known dev hash collision MUST also be rejected
        ext_leaked = {
            "pack_id": "ext-leak",
            "cases": [
                {"case_id": "UNSEEN-2", "split": "held_out_unseen", "domain": "software",
                 "prompt_sha256": _h("p2"), "source_sha256": dev_src},
            ],
        }
        report2 = benchmark_harness.validate_case_pack(ext_leaked, known_dev_sha256s={dev_src.upper()})
        self.assertEqual("rejected", report2["status"])
        same_source = {**ext_leaked['cases'][0], 'case_id': 'UNSEEN-3', 'prompt_sha256': _h('p3')}
        ext_leaked['cases'].append(same_source)
        self.assertIn('benchmark_unseen_hash_duplicate:UNSEEN-3:source_sha256',
                      benchmark_harness.validate_case_pack(ext_leaked)['errors'])

    def test_blinding_unknown_cost_guard_and_hard_blocker_priority(self):
        # Unknown cost disguised as 0 MUST be rejected
        with self.assertRaisesRegex(ContractError, "benchmark_unknown_cost_disguised_as_zero"):
            benchmark_harness.evaluate_submission({
                "case_id": "C1", "blind_label": "System-A", "completed": True,
                "clarification_rounds": 0, "rework_items": 0, "elapsed_seconds": 5.0,
                "cost_basis": "not_measured", "cost_usd": 0.0, "blockers": [],
            })

        # Dry run must execute cleanly with zero network/LLM calls and rank zero-blocker system ahead
        dry = benchmark_harness.run_fixture_dry_run()
        self.assertEqual("dry_run_passed", dry["status"])
        summary = dry["summary"]
        self.assertFalse(summary["claims_live_market_leadership"])
        self.assertEqual("not_performed", summary["human_blind_review"])
        self.assertEqual(1.0, summary["system_summaries"]["dyz_candidate"]["zero_blocker_rate"])
        self.assertEqual(0.0, summary["system_summaries"]["baseline_generic"]["zero_blocker_rate"])
        self.assertIsNone(summary["system_summaries"]["dyz_candidate"]["cost_summary"]["measured_total_usd"])
        self.assertEqual(2, summary["system_summaries"]["dyz_candidate"]["cost_summary"]["unmeasured_cases"])
        paired = summary["paired_comparisons"][0]
        # Alphabetical: baseline_generic (a) vs dyz_candidate (b) -> dyz wins both cases
        self.assertEqual((0, 2, 0), (paired["wins_a"], paired["wins_b"], paired["ties"]))

    def test_cli_dry_run_outputs_valid_json(self):
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(ROOT / "evals/benchmark_harness.py"), "--dry-run"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(0, proc.returncode, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual("dry_run_passed", data["status"])

    def test_blind_sheet_and_sealed_mapping_are_independent_with_domain_separated_seed(self):
        seed = _h('synthetic private seed')
        case_ids = ['case-2', 'case-1']
        systems = ['Hidden-gamma', 'Hidden-alpha', 'Hidden-beta']
        public, sealed = benchmark_harness.assign_blind_labels(case_ids, systems, seed=seed)
        public_bytes = json.dumps(public)
        self.assertNotIn(seed, public_bytes)
        self.assertNotIn('sealed_reveal_key', public)
        self.assertTrue(all(system not in public_bytes for system in systems))
        expected_commit = digest(['blinding-commitment-v2', seed, sorted(case_ids), sorted(systems)])
        self.assertEqual(expected_commit, public['seed_commitment_sha256'])
        entropy = hmac.new(seed.encode(), b'blinding-prng-v1', 'sha256').digest()
        rng = random.Random(int.from_bytes(entropy, 'big'))
        for case_id in sorted(case_ids):
            expected_order = sorted(systems)
            rng.shuffle(expected_order)
            self.assertEqual(expected_order, list(sealed[case_id].values()))

    def test_human_mode_requires_complete_case_ratings_and_independent_scorecards(self):
        seed = _h('synthetic human comparison seed')
        sheet, reveal = benchmark_harness.assign_blind_labels(['C2', 'C1'], ['two', 'one'], seed=seed)
        label_a, label_b = 'System-A', 'System-B'
        base = {'completed': True, 'clarification_rounds': 0, 'rework_items': 0, 'elapsed_seconds': 1.0,
                'cost_basis': 'local_hardware_no_api_fee'}
        blocker = {'code': 'fake_quote', 'detail': 'synthetic hard blocker'}
        evaluations = [benchmark_harness.evaluate_submission({**base, 'case_id': case, 'blind_label': label,
                       'blind_response': f'Synthetic answer {case}/{label}',
                       'blockers': [blocker] * (2 if system == 'two' else int(case == 'C1'))})
                       for case, labels in reveal.items() for label, system in labels.items()]
        for value in (float('inf'), float('nan')):
            with self.assertRaisesRegex(ContractError, 'elapsed_seconds_nonneg_number_required'):
                benchmark_harness.evaluate_submission({**base, 'case_id': 'C1', 'blind_label': 'A', 'elapsed_seconds': value})
            with self.assertRaisesRegex(ContractError, 'measured_cost_usd_required'):
                benchmark_harness.evaluate_submission({**base, 'case_id': 'C1', 'blind_label': 'A',
                                                       'cost_basis': 'measured_api_receipt', 'cost_usd': value})
        for response in ('', '\t\n', '\u200b', 'text\x01', '\ud800'):
            with self.subTest(response=response), self.assertRaisesRegex(ContractError, 'blind_response_text_required'):
                benchmark_harness.evaluate_submission({**base, 'case_id': 'C1', 'blind_label': 'A',
                                                       'blind_response': response})
        aggregate = benchmark_harness.aggregate_blind_comparison
        for incomplete in (evaluations[:-1], evaluations[:2]):
            with self.assertRaisesRegex(ContractError, 'benchmark_incomplete_case_coverage'):
                aggregate(incomplete, reveal)
        live = {'benchmark_mode': 'live_blind_human_rated', 'seed': seed,
                'seed_commitment_sha256': sheet['seed_commitment_sha256']}

        def assert_unverified(result, status):
            self.assertEqual(status, result['human_blind_review'])
            self.assertIs(False, result['live_comparison_valid'])
            self.assertEqual([], result['paired_comparisons'])
            self.assertEqual({}, result['system_summaries'])

        proof = {'reviewer_id': 'reviewer-1', 'reviewed_at': '2026-11-24T10:00:00Z',
                 'independent_scorecard_ref': 'independent-scorecard-1'}
        for evidence in (None, {}, {'C1': proof}, {'C1': proof, 'C2': {**proof, 'reviewer_id': '  '}}):
            with self.assertRaisesRegex(ContractError, 'human_blind_review_evidence_required'):
                aggregate(evaluations, reveal, human_review_evidence=evidence, **live)
        with self.assertRaisesRegex(ContractError, 'timezone_required'):
            aggregate(evaluations, reveal, human_review_evidence={'C1': {**proof, 'reviewed_at': '2026-11-24T10:00:00'},
                                                                 'C2': proof}, **live)
        with self.assertRaisesRegex(ContractError, 'invalid_timestamp'):
            aggregate(evaluations, reveal, human_review_evidence={
                'C1': {**proof, 'reviewed_at': '0001-01-01T00:00:00+23:59'}, 'C2': proof}, **live)
        for reviewer in ('unknown', 'ＴＢＤ', '\u200b', 'unknown\u200b', 'reviewer\x01', 'reviewer\ud800'):
            with self.subTest(reviewer=reviewer), self.assertRaisesRegex(ContractError, 'human_blind_review_evidence_required'):
                aggregate(evaluations, reveal, human_review_evidence={
                    'C1': {**proof, 'reviewer_id': reviewer}, 'C2': proof}, **live)
        with self.assertRaisesRegex(ContractError, 'scorecard_reused'):
            aggregate(evaluations, reveal, human_review_evidence={'C1': proof, 'C2': proof}, **live)
        asserted = {'C1': proof, 'C2': {**proof, 'independent_scorecard_ref': 'independent-scorecard-2'}}
        assert_unverified(aggregate(evaluations, reveal, human_review_evidence=asserted, **live),
                          'evidence_asserted_not_verified')

        evidence = {}
        for case, labels in reveal.items():
            binding = digest({label: _h(f'Synthetic answer {case}/{label}') for label in labels})
            ratings = {row['blind_label']: {
                'assessment': 'Reviewed the synthetic answer.\n\tSee the blocker findings.',
                **{field: row[field] for field in ('completed', 'hard_blocker_codes', 'hard_blocker_count',
                                                   'outcome', 'rework_items', 'clarification_rounds')},
            } for row in evaluations if row['case_id'] == case}
            payload = {'case_id': case, 'reviewer_id': proof['reviewer_id'], 'reviewed_at': proof['reviewed_at'],
                       'blind_response_sha256': binding, 'ratings': ratings}
            evidence[case] = {**proof, 'independent_scorecard_ref': digest(payload),
                              'blind_response_sha256': binding, 'scorecard_payload': payload}
        result = aggregate(evaluations, reveal, human_review_evidence=evidence, **live)
        self.assertEqual('performed', result['human_blind_review'])
        self.assertIs(True, result['live_comparison_valid'])
        flipped = {case: {label_a: labels[label_b], label_b: labels[label_a]} for case, labels in reveal.items()}
        for mapping, change in (
            (flipped, {}), (flipped, {'seed': _h('wrong private seed')}),
            (reveal, {'seed': None}), (reveal, {'seed_commitment_sha256': None}),
            (reveal, {'seed_commitment_sha256': _h('different commitment')}),
            ({'C1': reveal['C1'], 'C2': flipped['C2']}, {}),
            ({'C1': reveal['C1']}, {}),
        ):
            with self.subTest(mapping=mapping, change=change):
                assert_unverified(aggregate(evaluations, mapping, human_review_evidence=evidence, **{**live, **change}),
                                  'reveal_mismatch_not_verified')
        self.assertEqual({cid: {k: v for k, v in item.items() if k != 'scorecard_payload'} for cid, item in evidence.items()},
                         result['human_blind_review_evidence'])
        card = evidence['C1']
        payload = card['scorecard_payload']
        wrong_answer = {**payload, 'blind_response_sha256': evidence['C2']['blind_response_sha256']}
        wrong_case = {**payload, 'case_id': 'C2'}
        missing_rating = {**payload, 'ratings': {label_a: payload['ratings'][label_a]}}
        for bad_card in (
            {**card, 'scorecard_payload': None}, {**card, 'blind_response_sha256': None},
            {**card, 'scorecard_payload': {**payload, 'ratings': {label_a: 'changed', label_b: 'changed'}}},
            {**card, 'scorecard_payload': wrong_answer, 'independent_scorecard_ref': digest(wrong_answer),
             'blind_response_sha256': wrong_answer['blind_response_sha256']},
            {**card, 'scorecard_payload': wrong_case, 'independent_scorecard_ref': digest(wrong_case)},
            {**card, 'scorecard_payload': missing_rating, 'independent_scorecard_ref': digest(missing_rating)},
        ):
            with self.subTest(evidence=bad_card):
                downgraded = aggregate(evaluations, reveal, human_review_evidence={**evidence, 'C1': bad_card}, **live)
                assert_unverified(downgraded, 'evidence_asserted_not_verified')
        for rating in (None, {}, {'': 'text'}, {'\u200b': 'text'}, {**payload['ratings'][label_a], '': 'text'},
                       *({**payload['ratings'][label_a], 'assessment': invalid} for invalid in ('', '  ', '\u200b', '\x01', None)),
                       {**payload['ratings'][label_a], 'completed': 1}):
            with self.subTest(rating=rating):
                changed = {**payload, 'ratings': {**payload['ratings'], label_a: rating}}
                bad_card = {**card, 'scorecard_payload': changed, 'independent_scorecard_ref': digest(changed)}
                result_status = aggregate(evaluations, reveal, human_review_evidence={**evidence, 'C1': bad_card}, **live)
                assert_unverified(result_status, 'evidence_asserted_not_verified')
        replaced_response = {**evaluations[0], 'blind_response_sha256': _h('different answer')}
        assert_unverified(aggregate([replaced_response, *evaluations[1:]], reveal, human_review_evidence=evidence, **live),
                          'evidence_asserted_not_verified')
        for change in ({'completed': False}, {'hard_blocker_codes': []}, {'hard_blocker_count': 0},
                       {'rework_items': 2}, {'clarification_rounds': 2}, {'outcome': 'incomplete'},
                       {'blockers': [], 'hard_blocker_codes': [], 'hard_blocker_count': 0,
                        'outcome': 'completed_no_hard_blockers'}):
            with self.subTest(change=change):
                changed = [{**evaluations[0], **change}, *evaluations[1:]]
                downgraded = aggregate(changed, reveal, human_review_evidence=evidence, **live)
                assert_unverified(downgraded, 'evidence_asserted_not_verified')
        repeated = evaluations[0]['blind_response_sha256']
        repeated_evaluations = [*evaluations[:3], {**evaluations[3], 'blind_response_sha256': repeated}]
        repeated_binding = digest({row['blind_label']: row['blind_response_sha256'] for row in repeated_evaluations[2:]})
        repeated_payload = {**evidence['C2']['scorecard_payload'], 'blind_response_sha256': repeated_binding}
        repeated_card = {**evidence['C2'], 'blind_response_sha256': repeated_binding,
                         'scorecard_payload': repeated_payload, 'independent_scorecard_ref': digest(repeated_payload)}
        with self.assertRaisesRegex(ContractError, 'blind_response_reused'):
            aggregate(repeated_evaluations, reveal, human_review_evidence={**evidence, 'C2': repeated_card}, **live)
        pair = result['paired_comparisons'][0]
        self.assertEqual((1, 1, 1, 0, 0), (pair['both_blocked'], pair['both_blocked_fewer_on_a'],
                                           pair['wins_a'], pair['wins_b'], pair['ties']))
        self.assertEqual(2, result['system_summaries']['one']['cost_summary']['local_hardware_cases'])

    def test_count_metrics_and_aggregate_mean_reject_out_of_range_values(self):
        base = {'case_id': 'C1', 'blind_label': 'A', 'completed': True, 'clarification_rounds': 0,
                'rework_items': 0, 'elapsed_seconds': 1.0, 'cost_basis': 'not_measured'}
        accepted = benchmark_harness.evaluate_submission({**base, 'clarification_rounds': 1_000_000_000})
        self.assertEqual(1_000_000_000, accepted['clarification_rounds'])
        for field, error in (('clarification_rounds', 'clarification_rounds_nonneg_int_required'),
                             ('rework_items', 'rework_items_nonneg_int_required')):
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, error):
                benchmark_harness.evaluate_submission({**base, field: 1_000_000_001})
        other = benchmark_harness.evaluate_submission({**base, 'blind_label': 'B'})
        for field in ('clarification_rounds', 'rework_items', 'elapsed_seconds'):
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, 'benchmark_metric_out_of_range'):
                benchmark_harness.aggregate_blind_comparison(
                    [{**accepted, field: 10**500}, other], {'C1': {'A': 'one', 'B': 'two'}})
        for elapsed in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(elapsed=elapsed), self.assertRaisesRegex(ContractError, 'benchmark_metric_out_of_range'):
                benchmark_harness.aggregate_blind_comparison(
                    [{**accepted, 'elapsed_seconds': elapsed}, other], {'C1': {'A': 'one', 'B': 'two'}})

    def test_direct_aggregation_rejects_invalid_costs(self):
        base = {'case_id': 'C1', 'completed': True, 'clarification_rounds': 0, 'rework_items': 0,
                'elapsed_seconds': 1.0, 'cost_basis': 'not_measured'}
        first, other = [benchmark_harness.evaluate_submission({**base, 'blind_label': label}) for label in ('A', 'B')]
        aggregate = benchmark_harness.aggregate_blind_comparison
        reveal = {'C1': {'A': 'one', 'B': 'two'}}
        error = 'benchmark_metric_out_of_range'
        for basis in sorted(benchmark_harness.VALID_COST_BASES):
            for cost in (float('nan'), float('inf'), float('-inf'), -1, True, '1.0'):
                with self.subTest(basis=basis, cost=cost), self.assertRaisesRegex(ContractError, error):
                    aggregate([dict(first, cost_basis=basis, cost_usd=cost), other], reveal)
        measured = dict(first, cost_basis='measured_api_receipt')
        for row in (measured, {key: value for key, value in measured.items() if key != 'cost_usd'}):
            with self.subTest(has_cost='cost_usd' in row), self.assertRaisesRegex(ContractError, error):
                aggregate([row, other], reveal)
        for cost in (0, 1.25):
            with self.subTest(valid_cost=cost):
                report = aggregate([dict(measured, cost_usd=cost), other], reveal)
                json.dumps(report, allow_nan=False)
                self.assertEqual(cost, report['system_summaries']['one']['cost_summary']['measured_total_usd'])


class ExpertTrialPackAndUpgradeGateTests(unittest.TestCase):
    def _build_registered_pack(self, root, case_id, content, *, artifact_id="A1", source=None, supplement=None):
        path = f"{case_id}.md"
        (root / path).write_text(content, encoding="utf-8")
        artifacts = [{"id": artifact_id, "path": path, "role": "draft"}]
        hashes = {f"artifacts/{artifact_id}": hashlib.sha256((root / path).read_bytes()).hexdigest()}
        if supplement is not None:
            (root / "supp.json").write_bytes(supplement)
            artifacts.append({"id": "A2", "path": "supp.json", "role": "supplement"})
            hashes["artifacts/A2"] = hashlib.sha256(supplement).hexdigest()
        questions = [{"id": f"Q{i}", "category": "claim_scope_and_support", "artifact_ref": artifact_id,
                      "question": f"Synthetic substantive question {i}?"} for i in (1, 2)]
        return trial_pack.build_expert_trial_pack(
            root, combination_id="CN-patent-draft", case_id=case_id, expert_role="patent_attorney", author_id="author-1",
            artifacts=artifacts, dispute_questions=questions,
            deidentification_confirmed=True, deidentification_evidence="DEID-EV-01",
            redaction_receipt=_redaction_receipt(questions, artifact_hashes=hashes, case_id=case_id),
            source_material_sha256=source or _h(f"Original source {case_id}"),
        )

    def _review_record(self, pack):
        case_id = pack["case_id"]
        return {
            "combination_id": pack["combination_id"], "case_id": case_id, "expert_role": pack["expert_role"],
            "author_id": pack["author_id"], "reviewer_id": "attorney-9",
            "reviewer_qualification_evidence": "CNPA-LICENSE-SYNTHETIC-001",
            "pack_sha256": pack["pack_sha256"], "material_fingerprint_sha256": pack["material_fingerprint_sha256"],
            "reviewed_at": f"2026-11-{int(case_id[-1]) + 1:02d}T10:00:00+00:00",
            "artifact_hashes": {item["path"]: item["sha256"] for item in pack["artifacts"]},
            "substantive_findings": ["Reviewed Art. 26(4) and Art. 33 basis; no blocking scope drift."],
            "unresolved_blocking_defects": [], "unresolved_major_defects": [], "verdict": "approved_with_no_major_defects",
        }

    def test_trial_pack_enforces_deidentification_hashes_and_substantive_questions(self):
        with tempfile.TemporaryDirectory(prefix="dyz-trial-") as folder:
            root = Path(folder)
            (root / "draft.md").write_text("SYNTHETIC de-identified claim draft\n", encoding="utf-8")
            (root / "support.json").write_text('{"claim_1": "P001"}\n', encoding="utf-8")

            # Missing deidentification MUST fail
            with self.assertRaisesRegex(ContractError, "trial_pack_deidentification_required"):
                trial_pack.build_expert_trial_pack(
                    root, combination_id="CN-patent-draft", case_id="C1", expert_role="patent_attorney", author_id="author-1",
                    artifacts=[{"id": "A1", "path": "draft.md", "role": "draft"}],
                    dispute_questions=[
                        {"id": "Q1", "category": "claim_scope_and_support", "artifact_ref": "A1", "question": "q1"},
                        {"id": "Q2", "category": "technical_problem_and_effect", "artifact_ref": "A1", "question": "q2"},
                    ],
                    deidentification_confirmed=False,
                    source_material_sha256=_h('original source'),
                )

            # Numeric-only scorecard MUST be rejected
            with self.assertRaisesRegex(ContractError, "numeric_only_scorecard_rejected"):
                trial_pack.build_expert_trial_pack(
                    root, combination_id="CN-patent-draft", case_id="C1", expert_role="patent_attorney", author_id="author-1",
                    artifacts=[{"id": "A1", "path": "draft.md", "role": "draft"}],
                    dispute_questions=[
                        {"id": "Q1", "category": "claim_scope_and_support", "artifact_ref": "A1",
                         "question": "rate 1-5", "expected_judgment_type": "numeric_score_only"},
                        {"id": "Q2", "category": "technical_problem_and_effect", "artifact_ref": "A1", "question": "q2"},
                    ],
                    deidentification_confirmed=True, deidentification_evidence="DEID-EV-01",
                    source_material_sha256=_h('original source'),
                )

            questions = [
                {"id": "Q1", "category": "claim_scope_and_support", "artifact_ref": "A1",
                 "question": "Does Claim 1 stay within disclosed necessary conditions?"},
                {"id": "Q2", "category": "office_action_or_amendment_basis", "artifact_ref": "A2",
                 "question": "Is support mapping complete for Art. 33 review?"},
            ]
            history = [{"defect_id": "D-01", "severity": "minor", "summary": "terminology check", "status": "fixed"}]
            hashes = {f"artifacts/A{i}": hashlib.sha256((root / path).read_bytes()).hexdigest()
                      for i, path in enumerate(("draft.md", "support.json"), 1)}
            pack = trial_pack.build_expert_trial_pack(
                root, combination_id="CN-patent-draft", case_id="C1", expert_role="patent_attorney", author_id="author-1",
                artifacts=[
                    {"id": "A1", "path": "draft.md", "role": "claim_draft"},
                    {"id": "A2", "path": "support.json", "role": "support_map"},
                ],
                dispute_questions=questions, defect_history=history,
                redaction_receipt=_redaction_receipt(questions, history, artifact_hashes=hashes),
                source_material_sha256=_h('original source'),
                deidentification_confirmed=True, deidentification_evidence="DEID-EV-01",
            )
            self.assertEqual("ready_for_independent_expert_review", pack["status"])
            self.assertEqual("synthetic_helper_only", pack["catalog_support_unchanged"])
            self.assertEqual(2, len(pack["artifacts"]))
            self.assertEqual(64, len(pack["pack_sha256"]))
            self.assertEqual(digest({k: v for k, v in pack.items() if k != "pack_sha256"}), pack["pack_sha256"])
            self.assertEqual(history[0]["summary"], pack["defect_history"][0]["summary"])

    def test_trial_pack_binds_opaque_author_and_excludes_local_metadata(self):
        with tempfile.TemporaryDirectory(prefix='dyz-trial-metadata-') as folder:
            root = Path(folder).resolve()
            artifact = root / 'private-filename.txt'
            artifact.write_text('synthetic de-identified text', encoding='utf-8')
            history = [{'defect_id': 'D1', 'summary': 'reviewed summary', 'notes': 'unapproved defect notes'}]
            questions = [{'id': f'Q{i}', 'category': 'claim_scope_and_support', 'artifact_ref': 'A1',
                          'question': f'Check issue {i}\r\n\twith context', 'candidate_notes': 'unapproved candidate notes'} for i in (1, 2)]
            row = {'id': 'A1', 'path': artifact.name, 'role': 'draft', 'original_name': 'another private name'}
            hashes = {'artifacts/A1': _h('synthetic de-identified text')}
            receipt = _redaction_receipt(questions, history, receipt_id='PRIVATE-DEID-RECEIPT', artifact_hashes=hashes)
            opts = {'combination_id': 'CN-patent-draft', 'case_id': 'C1', 'expert_role': 'patent_attorney',
                    'author_id': 'PRIVATE-AUTHOR', 'dispute_questions': questions, 'deidentification_confirmed': True,
                    'deidentification_evidence': 'PRIVATE-DEID-RECEIPT', 'artifacts': [row],
                    'defect_history': history, 'redaction_receipt': receipt, 'source_material_sha256': _h('original source')}
            pack = trial_pack.build_expert_trial_pack(root, **opts)
            for value in ('unapproved candidate notes', 'unapproved defect notes', 'another private name', 'private-filename',
                          'PRIVATE-DEID-RECEIPT', receipt['redactor_id']):
                self.assertNotIn(value, json.dumps(pack))
            self.assertEqual('artifacts/A1', pack['artifacts'][0]['path'])
            self.assertEqual('PRIVATE-AUTHOR', pack['author_id'])
            self.assertEqual(digest(receipt), pack['redaction_receipt_sha256'])
            with self.assertRaisesRegex(ContractError, 'source_material_sha256_invalid'):
                trial_pack.build_expert_trial_pack(root, **{k: v for k, v in opts.items() if k != 'source_material_sha256'})
            for change, error in (
                ({'deidentification_evidence': 'TBD'}, 'trial_pack_deidentification_required'),
                ({'author_id': 'TBD'}, 'identifier_not_canonical'),
                ({'redaction_receipt': None}, 'unredacted_free_text_blocked'),
                ({'redaction_receipt': {**receipt, 'approved': False}}, 'unredacted_free_text_blocked'),
                ({'redaction_receipt': {**receipt, 'redactor_id': ''}}, 'unredacted_free_text_blocked'),
                ({'redaction_receipt': {**receipt, 'redacted_at': '2026-11-01T08:00:00'}}, 'unredacted_free_text_blocked'),
                ({'case_id': 'C2'}, 'unredacted_free_text_blocked'),
                ({'combination_id': 'other-combination'}, 'unredacted_free_text_blocked'),
                ({'redaction_receipt': {**receipt, 'artifact_hashes': {}}}, 'unredacted_free_text_blocked'),
                ({'redaction_receipt': {**receipt, 'artifact_hashes': {**hashes, 'artifacts/A2': _h('extra')}}},
                 'unredacted_free_text_blocked'),
                *(({'source_material_sha256': invalid}, 'source_material_sha256_invalid')
                  for invalid in (None, '', 'z' * 64, _h(''))),
                *(({'dispute_questions': [{**questions[0], 'question': invalid}, questions[1]]}, 'dispute_question_content_required')
                  for invalid in ('\u200b', 'question\x01', '\ud800', '\n\t',
                                  *(f'Check{mark} issue 2\r\n\twith context' for mark in
                                    ('\u034f', '\u180b', '\ufe0f', '\U000e0100')))),
                ({'dispute_questions': [{**questions[1], 'id': 'Q3'}, questions[1]]}, 'duplicate_dispute_question'),
                ({'dispute_questions': [{**questions[0], 'question': 'Chec\u0301k issue 2 with context'}, questions[1]]},
                 'duplicate_dispute_question'),
                *(({'defect_history': [{**history[0], 'summary': invalid}]}, 'defect_history_entry_invalid')
                  for invalid in ('\u200b', 'summary\x01', '\ud800', '\n\t')),
                ({'dispute_questions': [{**questions[0], 'question': 'unreviewed candidate question'}, questions[1]]},
                 'unredacted_free_text_blocked'),
                ({'defect_history': [{**history[0], 'summary': 'unreviewed private summary'}]}, 'unredacted_free_text_blocked'),
                ({'artifacts': [row, {**row, 'id': 'A2'}]}, 'trial_artifact_duplicate'),
                ({'artifacts': [{**row, 'path': '../outside.txt'}]}, 'trial_artifact_path_rejected'),
                ({'defect_history': [{'defect_id': 'D1', 'summary': 'approved summary',
                                      'status': {'private': 'unapproved metadata'}}]}, 'defect_history_entry_invalid'),
            ):
                with self.subTest(error=error), self.assertRaisesRegex(ContractError, error):
                    trial_pack.build_expert_trial_pack(root, **{**opts, **change})
            artifact.write_bytes(b'')
            with self.assertRaisesRegex(ContractError, 'trial_artifact_empty'):
                trial_pack.build_expert_trial_pack(root, **opts)
            artifact.write_bytes(b'other de-identified text')
            with self.assertRaisesRegex(ContractError, 'unredacted_free_text_blocked'):
                trial_pack.build_expert_trial_pack(root, **opts)
            artifact.write_bytes(b'synthetic de-identified text')
            with patch.object(trial_pack, 'MAX_TRIAL_FILE_BYTES', 8), self.assertRaisesRegex(ContractError, 'trial_artifact_byte_limit'):
                trial_pack.build_expert_trial_pack(root, **opts)
            with patch.object(trial_pack, 'MAX_TRIAL_TOTAL_BYTES', 8), self.assertRaisesRegex(ContractError, 'trial_artifact_byte_limit'):
                trial_pack.build_expert_trial_pack(root, **opts)
            original = Path.lstat

            def symlink_info(path):
                info = original(path)
                return os.stat_result((stat.S_IFLNK, *tuple(info)[1:])) if path == artifact else info

            with patch.object(Path, 'lstat', symlink_info), self.assertRaisesRegex(ContractError, 'trial_artifact_path_rejected'):
                trial_pack.build_expert_trial_pack(root, **opts)
            os.link(artifact, root / 'alias.txt')
            with self.assertRaisesRegex(ContractError, 'trial_artifact_link_rejected'):
                trial_pack.build_expert_trial_pack(root, **opts)

    def test_upgrade_gate_requires_three_consecutive_independent_nonstale_cases(self):
        with tempfile.TemporaryDirectory(prefix="dyz-trial-upgrade-") as folder:
            root = Path(folder)
            registry = {case_id: self._build_registered_pack(root, case_id, f"Synthetic material {case_id}")
                        for case_id in ("C0", "C1", "C2", "C3")}
        records = {case: self._review_record(pack) for case, pack in registry.items()}

        def _rec(case_id, **changes):
            return {**records[case_id], **changes}

        role = {"expected_expert_role": "patent_attorney"}
        current = {case: record["artifact_hashes"] for case, record in records.items()}
        bound = {**role, "current_artifact_hashes": current, "registered_packs": registry}
        two = trial_pack.evaluate_combination_upgrade("CN-patent-draft", [_rec("C1"), _rec("C2")], **bound)
        self.assertFalse(two["eligible_for_upgrade"])
        self.assertEqual("synthetic_helper_only", two["recommended_support_level"])

        # Self-review breaks streak -> NOT eligible
        self_rev = trial_pack.evaluate_combination_upgrade(
            "CN-patent-draft", [_rec("C1"), _rec("C2", reviewer_id="Author-1"), _rec("C3")], **bound
        )
        self.assertFalse(self_rev["eligible_for_upgrade"])
        self.assertIn("self_review_forbidden", self_rev["blocking_reasons"])

        # Stale artifact hash invalidates upgrade -> NOT eligible
        stale = trial_pack.evaluate_combination_upgrade(
            "CN-patent-draft", [_rec("C1"), _rec("C2"), _rec("C3")],
            **{**bound, "current_artifact_hashes": {**current, "C2": {"artifacts/A1": _h("changed")}}},
        )
        self.assertFalse(stale["eligible_for_upgrade"])
        self.assertIn("stale_artifact_hash:artifacts/A1", stale["blocking_reasons"])

        # Major defect in record 1 followed by 3 consecutive clean independent cases -> ELIGIBLE, still no auto-mutation!
        passed = trial_pack.evaluate_combination_upgrade(
            "CN-patent-draft",
            [_rec("C0", verdict="revisions_required", unresolved_major_defects=["scope issue"]),
             _rec("C1"), _rec("C2"), _rec("C3")],
            **bound,
        )
        self.assertTrue(passed["eligible_for_upgrade"])
        self.assertEqual(3, passed["trailing_consecutive_valid"])
        self.assertEqual("professionally_reviewed_limited_combination", passed["recommended_support_level"])
        self.assertFalse(passed["catalog_mutated"])
        self.assertTrue(passed["requires_explicit_maintainer_release_action"])
        self.assertEqual([], passed['blocking_reasons'])
        self.assertIn('verdict_not_approved:revisions_required', passed['historical_record_issues'][0]['reasons'])

        combination = 'CN-patent-draft'
        clean = [_rec('C1'), _rec('C2'), _rec('C3')]
        with self.assertRaisesRegex(ContractError, 'at_least_three'):
            trial_pack.evaluate_combination_upgrade(combination, clean, min_consecutive=2, **bound)
        with self.assertRaisesRegex(ContractError, 'combination_id_required'):
            trial_pack.evaluate_combination_upgrade(combination + '\u200b', clean, **bound)
        for kwargs, expected in ((role, 'current_artifact_hashes_required'),
                                 ({**bound, 'expected_expert_role': None}, 'expected_expert_role_required'),
                                 ({**bound, 'current_artifact_hashes': {'artifacts/A1': _h('draft'), 'support.json': _h('support')}},
                                  'artifact_hash_coverage_mismatch'),
                                 ({**bound, 'current_artifact_hashes': {'C1': current['C1']}},
                                  'current_artifact_hashes_missing_for_case')):
            result = trial_pack.evaluate_combination_upgrade(combination, clean, **kwargs)
            self.assertFalse(result['eligible_for_upgrade'])
            self.assertIn(expected, result['blocking_reasons'])
        for changed, expected in (({'case_id': 'c1'}, 'duplicate_case_id:c1'),
                                  ({'case_id': ' c1 '}, 'identifier_not_canonical'),
                                  ({'case_id': 'C1\u200b'}, 'identifier_not_canonical'),
                                  ({'case_id': 'C1\u200c'}, 'identifier_not_canonical'),
                                  ({'author_id': 'attorney-9\u200b'}, 'identifier_not_canonical'),
                                  ({'reviewer_id': 'author-1\u200c'}, 'identifier_not_canonical'),
                                  ({'reviewer_id': 'attorney-9\u0007'}, 'identifier_not_canonical'),
                                  ({'reviewer_id': 'unknown'}, 'reviewer_or_author_missing'),
                                  ({'author_id': 'author-1\ud800'}, 'identifier_not_canonical'),
                                  ({'pack_sha256': clean[0]['pack_sha256']}, 'duplicate_pack_sha256'),
                                  ({'expert_role': 'copyright_counsel'}, 'expert_role_mismatch'),
                                  ({'author_id': 'claimed-other', 'reviewer_id': 'author-1'}, 'trial_pack_not_verified'),
                                  *[({'reviewer_qualification_evidence': value}, 'reviewer_qualification_evidence_missing')
                                    for value in ('\u200b', '\x01', '\ud800', 'unknown\u200b', 'ＵＮＫＮＯＷＮ', '\tlicense',
                                                  '\ufeff', '\u00ad', '\u2028', '\u2029', '\u2800', '\u3164', '\u115f', '\uffa0', '\ufe0f')],
                                  *[({'substantive_findings': [value]}, 'substantive_findings_required')
                                    for value in ('\u200b', 'finding\x01', '\ud800', '\n\t', '\ufeff', '\u00ad', '\u2028',
                                                  '\u2029', '\u2800', '\u3164', '\u1160', '\uffa0', '\u034f', ' \u2800\u3164\n\t')],
                                  ({'reviewed_at': '2026-11-02T11:00:00+01:00'}, 'reviewed_at_not_strictly_increasing'),
                                  ({'reviewed_at': '2026-11-03T10:00:00'}, 'reviewed_at_invalid')):
            result = trial_pack.evaluate_combination_upgrade(combination, [clean[0], {**clean[1], **changed}, clean[2]], **bound)
            self.assertFalse(result['eligible_for_upgrade'])
            self.assertIn(expected, result['blocking_reasons'])
        self.assertFalse(trial_pack.evaluate_combination_upgrade(
            combination, [{**_rec('C0'), 'expert_role': 'copyright_counsel'}, *clean], **bound)['eligible_for_upgrade'])

    def test_upgrade_gate_rejects_unverified_packs_and_repackaged_material(self):
        assess = trial_pack.evaluate_combination_upgrade
        with tempfile.TemporaryDirectory(prefix='dyz-pack-registry-') as folder:
            root = Path(folder)
            packs = [self._build_registered_pack(root, f'C{i}', f'Synthetic material {i}') for i in (1, 2, 3)]
            repackaged = self._build_registered_pack(root, 'C2', 'Synthetic material 1', artifact_id='WRAPPER')
            with_supplement = self._build_registered_pack(root, 'C1', 'Synthetic material 1', supplement=b'Supplement')
            source = _h('same original materials')
            source_packs = [self._build_registered_pack(root, f'C{i}', f'Different redaction {i}', source=source) for i in (1, 2)]
            rotated = [self._build_registered_pack(root, f'C{i}', f'Role sample {i % 3 + 1}', source=_h(f'Role sample {i}'))
                       for i in (1, 2, 3)]
            cross_role_attachment = self._build_registered_pack(root, 'C2', 'Different draft', supplement=b'Role sample 1')
        clean = [self._review_record(pack) for pack in packs]
        combination = packs[0]['combination_id']
        context = {'expected_expert_role': 'patent_attorney',
                   'current_artifact_hashes': {rec['case_id']: rec['artifact_hashes'] for rec in clean}}
        registry = {pack['pack_sha256']: pack for pack in packs}
        self.assertTrue(assess(combination, clean, registered_packs=registry, **context)['eligible_for_upgrade'])
        for invalid_registry in (
            None, {packs[0]['case_id']: packs[0]}, {**registry, packs[1]['pack_sha256']: packs[0]},
            {**registry, packs[1]['pack_sha256']: {**packs[1], 'dispute_questions': []}},
            {**registry, packs[1]['pack_sha256']: {**packs[1], 'combination_id': 'other-combination'}},
        ):
            with self.subTest(registry=invalid_registry):
                result = assess(combination, clean, registered_packs=invalid_registry, **context)
                self.assertFalse(result['eligible_for_upgrade'])
                self.assertIn('trial_pack_not_verified', result['blocking_reasons'])
        for invalid_record in ({k: v for k, v in clean[1].items() if k != 'material_fingerprint_sha256'},
                               {**clean[1], 'material_fingerprint_sha256': _h('incorrect fingerprint')},
                               {**clean[1], 'artifact_hashes': {'artifacts/A1': _h('incorrect artifact')}}):
            result = assess(combination, [clean[0], invalid_record, clean[2]], registered_packs=registry, **context)
            self.assertFalse(result['eligible_for_upgrade'])
            self.assertIn('trial_pack_not_verified', result['blocking_reasons'])
        pack = packs[1]
        questions = pack['dispute_questions']
        original = {key: value for key, value in pack.items() if key != 'pack_sha256'}
        defect = {'defect_id': 'D1', 'summary': 'Reviewed prior terminology', 'severity': 'minor', 'status': 'fixed'}
        for invalid in ({k: v for k, v in original.items() if k != 'source_material_sha256'},
                        {**original, 'source_material_sha256': None}, {**original, 'source_material_sha256': 'z' * 64},
                        {**original, 'source_material_sha256': _h('')}, {**original, 'author_id': 'TBD'},
                        {k: v for k, v in original.items() if k != 'author_id'},
                        {**original, 'status': 'draft'}, {**original, 'dispute_questions': questions[:1]},
                        *({**original, 'dispute_questions': [bad_question, questions[1]]} for bad_question in (
                            {k: v for k, v in questions[0].items() if k != 'id'}, {**questions[0], 'id': ' '},
                            {**questions[0], 'id': 'q2'}, {k: v for k, v in questions[0].items() if k != 'category'},
                            {**questions[0], 'category': ' '}, {**questions[0], 'question': '\u2800'},
                            {**questions[0], 'question': f" {questions[1]['question'].upper()}\t"},
                            *({**questions[0], 'question': questions[1]['question'] + mark} for mark in
                              ('\u034f', '\ufe0f', '\U000e0100', '\u0301', '\u20dd')),
                        )),
                        {**original, 'dispute_questions': [{**questions[0], 'artifact_ref': 'unregistered'}, questions[1]]},
                        {**original, 'dispute_questions': [{**questions[0], 'expected_judgment_type': 'numeric'}, questions[1]]},
                        *({**original, 'defect_history': bad_history} for bad_history in (
                            [{k: v for k, v in defect.items() if k != 'defect_id'}],
                            [{**defect, 'defect_id': ''}], [{**defect, 'defect_id': ' '}],
                            [defect, {**defect, 'defect_id': 'd1', 'summary': 'Distinct wording'}],
                        )),
                        {**original, 'artifacts': [{**pack['artifacts'][0], 'bytes': 0}]}):
            with self.subTest(registration=invalid):
                updated = {**invalid, 'pack_sha256': digest(invalid)}
                record = {**clean[1], 'pack_sha256': updated['pack_sha256']}
                if 'author_id' in invalid:
                    record['author_id'] = invalid['author_id']
                result = assess(combination, [clean[0], record, clean[2]],
                                registered_packs={**registry, updated['pack_sha256']: updated}, **context)
                self.assertIn('trial_pack_not_verified', result['blocking_reasons'])
                self.assertFalse(result['eligible_for_upgrade'])
                if invalid.get('author_id') == 'TBD':
                    self.assertIn('reviewer_or_author_missing', result['record_audits'][1]['reasons'])

        self.assertNotEqual(packs[0]['pack_sha256'], repackaged['pack_sha256'])
        self.assertEqual(packs[0]['material_fingerprint_sha256'], repackaged['material_fingerprint_sha256'])
        self.assertNotEqual(source_packs[0]['material_fingerprint_sha256'], source_packs[1]['material_fingerprint_sha256'])
        self.assertNotEqual(with_supplement['material_fingerprint_sha256'], repackaged['material_fingerprint_sha256'])
        for duplicates in ([packs[0], repackaged, packs[2]], [*source_packs, packs[2]],
                           [with_supplement, repackaged, packs[2]], rotated, [rotated[0], cross_role_attachment, packs[2]]):
            records = [self._review_record(pack) for pack in duplicates]
            result = assess(combination, records, expected_expert_role='patent_attorney',
                            current_artifact_hashes={rec['case_id']: rec['artifact_hashes'] for rec in records},
                            registered_packs={pack['case_id']: pack for pack in duplicates})
            self.assertFalse(result['eligible_for_upgrade'])
            self.assertIn('duplicate_underlying_material', result['blocking_reasons'])


if __name__ == "__main__":
    unittest.main()
