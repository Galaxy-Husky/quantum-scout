"""Behavioral boundaries for independent case attribution; no live calls."""
import asyncio
from copy import deepcopy
import json
import unittest

import searchos_adapter as adapter
from searchos_online import OnlineRunner
from online_policy import attribution_metrics
from coverage_policy import verified, reviewed_cases
from review_fixtures import reviewed_ref
import test_searchos_online as online
import test_searchos_adapter as local


class OnlineAttributionTests(unittest.TestCase):
    setUp = online.OnlineTests.setUp
    opener = online.OnlineTests.opener
    extractor = online.OnlineTests.extractor
    run_fixture = online.OnlineTests.run_fixture

    def run_attribution(self, verdict):
        models = {'orchestrator': online.Model({'query': 'fixture'}),
                  'extraction': online.Model(self.extraction), 'judge': online.Model(self.judgment)}
        models['judge'].attribution_output = {'candidate_index': 0, 'attribution': verdict,
            'attribution_reason': 'Synthetic attribution decision'}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor).run())
        return result, models

    def test_root_is_not_automatically_attributed_and_rejection_skips_semantic(self):
        result, models = self.run_attribution('absent')
        self.assertEqual(result['model_calls'], 2)
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(result['coverage']['uncertain'], 1)
        meta = adapter.load(self.path)
        self.assertEqual(meta['attributions'][0]['attribution'], 'absent')
        self.assertEqual(meta['attributions'][0]['source_depth'], 0)
        self.assertEqual(meta['reviews'], [])
        self.assertEqual(len(models['judge'].calls), 1)
        self.assertEqual(meta['pending_attribution'], [])

    def test_abstained_is_audited_and_never_supported(self):
        result, _ = self.run_attribution('abstained')
        self.assertEqual(result['coverage']['evidence_nodes'], 0)
        self.assertEqual(adapter.load(self.path)['attributions'][0]['attribution'], 'abstained')

    def test_distinct_contracts_contexts_and_resume_between_steps(self):
        self.config['max_model_calls'] = 2
        first, models = self.run_fixture()
        self.assertEqual(first['model_calls'], 2)
        self.assertEqual(first['coverage']['filled'], 0)
        meta = adapter.load(self.path)
        self.assertEqual(len(meta['attributions']), 1)
        self.assertFalse(meta['reviews'])
        second, models = self.run_fixture()
        self.assertEqual(second['model_calls'], 1)
        self.assertEqual(second['coverage']['filled'], 1)
        self.assertEqual(models['extraction'].calls, [])
        self.assertEqual(len(models['judge'].calls), 1)
        calls = [e for e in adapter.load(self.path)['online']['events']
                 if e['kind'] == 'model_call_started' and e['role'] == 'judge']
        self.assertEqual([e['output_contract'] for e in calls], ['AttributionResult', 'Judgments'])
        self.assertIn('surrounding_text', calls[0]['input'])
        self.assertNotIn('claim_ledger', calls[0]['input'])
        self.assertIn('claim_ledger', calls[1]['input'])
        self.assertNotIn('case_description', calls[1]['input'])
        self.assertNotIn('attribution_reason', calls[1]['input'])

    def test_multicandidate_resume_reuses_extraction_after_gap_shrinks(self):
        self.config['max_model_calls'] = 4
        self.extraction['candidates'].append({**self.candidate, 'field': 'constraints'})
        first, _ = self.run_fixture()
        self.assertEqual(first['coverage']['filled'], 1)
        self.assertEqual(len(adapter.load(self.path)['attributions']), 2)
        second, models = self.run_fixture()
        self.assertEqual(second['coverage']['filled'], 2)
        self.assertEqual(second['model_calls'], 1)
        self.assertEqual(models['extraction'].calls, [])
        self.assertEqual(len(models['judge'].calls), 1)

    def test_supported_but_domain_unclear_is_cached_not_filled(self):
        self.judgment['judgments'][0]['domain_rule_met'] = 'unclear'
        result, _ = self.run_fixture()
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(result['coverage']['uncertain'], 1)
        self.assertEqual(adapter.load(self.path)['reviews'][0]['verdict'], 'supported')

    def test_failed_attribution_cache_does_not_call_either_judge_again(self):
        self.run_attribution('absent')
        meta = adapter.load(self.path)
        rid, entry = next(iter(meta['grounding'].items()))
        candidate = entry['report']['validated_candidates'][0]
        source = next(iter(meta['online']['sources'].values()))['source']
        runner = OnlineRunner(self.path, self.config, models={}, providers={'serper': self.provider})
        task = next(t for t in adapter.project(meta).frontier.questions if t.table_id == 'problem_definition').model_dump()
        asyncio.run(runner.review_candidate({'report_id': rid}, candidate, candidate,
                                           runner.context(task), source, source['segments'], task))
        self.assertEqual(runner.calls, 0)


class AdapterAttributionTests(unittest.TestCase):
    setUp = local.AdapterTests.setUp
    request = local.AdapterTests.request
    decision = local.AdapterTests.decision

    def test_direct_review_cannot_bypass_attribution(self):
        report = adapter.ground(self.path, self.request())
        with self.assertRaises(ValueError):
            adapter.review(self.path, self.decision(report, with_attribution=False))
        self.assertEqual(adapter.summary(adapter.project(adapter.load(self.path)))['filled'], 0)

    def test_four_conditions_and_exact_binding_are_enforced_on_projection(self):
        report = adapter.ground(self.path, self.request())
        adapter.review(self.path, self.decision(report))
        original = adapter.load(self.path)
        for mutation in ('missing_attribution', 'absent', 'wrong_case', 'wrong_hash',
                         'mismatch', 'unchecked_location', 'unclear_domain', 'wrong_claim', 'same_reviewer'):
            meta = deepcopy(original)
            a, review = meta['attributions'][0], meta['reviews'][0]
            if mutation == 'missing_attribution': meta['attributions'] = []
            if mutation == 'absent': a['attribution'] = 'absent'
            if mutation == 'wrong_case': a['case_id'] = 'OTHER-0001'
            if mutation == 'wrong_hash': a['source_sha256'] = 'other text'
            if mutation == 'mismatch': review['verdict'] = 'semantic_mismatch'
            if mutation == 'unchecked_location': review['location_checked'] = False
            if mutation == 'unclear_domain': review['domain_rule_met'] = 'unclear'
            if mutation == 'wrong_claim': review['value_text'] = 'Another claim'
            if mutation == 'same_reviewer': review['reviewer_id'] = a['reviewer_id']
            with self.subTest(mutation=mutation):
                state = adapter.project(meta)
                self.assertEqual(adapter.summary(state)['evidence_nodes'], 0)
                self.assertEqual(adapter.summary(state)['uncertain'], 1)

    def test_old_reviews_become_pending_without_rewriting_raw_decisions(self):
        report = adapter.ground(self.path, self.request())
        decision = self.decision(report, with_attribution=False)
        meta = adapter.load(self.path)
        decision.pop('domain_rule_met'); decision.pop('domain_rule_reason')
        meta['reviews'].append(decision)
        state = adapter.persist(self.path, meta)
        self.assertEqual(adapter.summary(state)['filled'], 0)
        restored = adapter.load(self.path)
        self.assertEqual(restored['reviews'], [decision])
        self.assertEqual(restored['pending_attribution'][0]['report_id'], report['report_id'])

    def test_human_precision_uses_only_sampled_eligible_claims(self):
        reports = []
        for field in ('parties_and_roles', 'constraints', 'real_world_problem'):
            request = self.request(); request['evidence'][0]['field'] = field
            report = adapter.ground(self.path, request)
            adapter.review(self.path, self.decision(report)); reports.append(report)
        metrics = attribution_metrics(adapter.load(self.path))
        self.assertIsNone(metrics['attribution_precision'])
        for report, correct in zip(reports, [True, False]):
            decision = self.decision(report)
            adapter.audit_attribution(self.path, {**decision, 'reviewer_kind': 'human',
                'reviewer_id': 'human-fixture', 'attribution_correct': correct})
        metrics = attribution_metrics(adapter.load(self.path))
        self.assertEqual(metrics['eligible_supported'], 3)
        self.assertEqual(metrics['audited_samples'], 2)
        self.assertEqual(metrics['attribution_precision'], .5)
        self.assertAlmostEqual(metrics['audit_coverage'], 2 / 3)

    def test_exported_coverage_enforces_all_four_conditions(self):
        item = reviewed_ref()
        self.assertTrue(verified(item, {'s1'}))
        for section, key, value in [('attribution_review', 'attribution', 'absent'),
                                    ('semantic_review', 'verdict', 'abstain'),
                                    ('semantic_review', 'location_checked', False),
                                    ('semantic_review', 'domain_rule_met', 'not_met')]:
            bad = deepcopy(item); bad[section][key] = value
            with self.subTest(key=key): self.assertFalse(verified(bad, {'s1'}))
