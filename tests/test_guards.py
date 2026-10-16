import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_calibration as render

spec = importlib.util.spec_from_file_location('grounding', ROOT / 'assets/quantum_grounding/executor.py')
grounding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grounding)


def batch():
    counts = dict(discovery_sources=1, discovery_pool_size=1, attempted_sources=1,
                  opened_sources=1, opened_metadata_only=0, sources_unattempted=0,
                  extracted_candidate_cases=0, problem_definition_complete_cases=0,
                  unique_cases=0, accepted_cases=0, cache_hits=0, analysis_limit=5,
                  discovery_limit=100, accepted_limit=20, batch_size=5,
                  diminishing_returns_threshold=2)
    return dict(run_id='test', batch_id='test-01', run_status='running', stop_reason=None,
                counts=counts, quality={'warnings': []},
                sources=[{'source_id': 'S1', 'status': 'opened'}], cases=[],
                events=[{'kind': 'source_discovered', 'source_id': 'S1', 'details': {'layer': 'layer1', 'query_id': 'SEED-1', 'position': 1}},
                        {'kind': 'source_opened', 'source_id': 'S1', 'details': {'access_level': 'full_text'}}],
                checkpoint=dict(run_status='running', stop_reason=None, completed=False,
                                new_source_ids=['S1'], input_source_ids=['S1'], opened_since_last_checkpoint=1,
                                counts_delta={k: 0 for k in ('opened_sources', 'attempted_sources', 'extracted_candidate_cases', 'problem_definition_complete_cases', 'accepted_cases', 'cache_hits')},
                                discovery_judgement={'judgement': 'not_exhausted'},
                                search_progress={'adaptive_queries': [], 'seed_pending': []}))


def stop(data, reason, status='incomplete'):
    data.update(stop_reason=reason, run_status=status)
    data['checkpoint'].update(stop_reason=reason, run_status=status, completed=status == 'completed')


def queries(data):
    qs = [dict(id=f'ADAPT-{i}', keyword_or_source=f'query {i}', status='completed', produced_new_sources=0) for i in range(2)]
    data['checkpoint']['search_progress']['adaptive_queries'] = qs
    data['events'] += [{'kind': 'adaptive_query', 'details': {'id': q['id']}} for q in qs]
    return qs


class StopTests(unittest.TestCase):
    def test_empty_adaptive_running(self):
        self.assertIn('running', render.render(batch()))

    def test_seed_only_budget_stop(self):
        data = batch(); data['counts']['analysis_limit'] = 1
        stop(data, 'analysis_limit_reached', 'completed')
        self.assertIn('✅ completed', render.render(data))

    def test_case_coverage_complete_guard(self):
        from schema_generator import domain_config
        from coverage_policy import coverage_witness
        config = domain_config()
        from review_fixtures import reviewed_ref
        ref = reviewed_ref('Evidence', source_id='S1')
        track = next(iter(config['tracks']))
        criteria = config['tracks'][track]['admission_criteria']
        case = dict(case_id='TEST-0001', problem_definition={f: copy.deepcopy(ref) for f in config['fields']},
                    tracks={track: dict(criteria={c: False for c in criteria}, passed_admission=0,
                        criteria_evidence={c: reviewed_ref('false', source_id='S1') for c in criteria})})
        data = batch()
        data['cases'] = [case]
        stop(data, 'case_coverage_complete', 'completed')
        data['checkpoint']['stop_evidence'] = {'coverage_witness': coverage_witness([case], config, {'S1'})}
        from review_fixtures import add_witness_audits
        add_witness_audits(data, config)
        # Serialize first: exercise the same batch-JSON entry point as online exports.
        self.assertIn('✅ completed', render.render(json.loads(json.dumps(data))))
        for mutation in ('completed', 'checkpoint', 'cross_case', 'witness', 'missing'):
            bad = copy.deepcopy(data)
            if mutation == 'completed': stop(bad, 'case_coverage_complete', 'incomplete')
            if mutation == 'checkpoint': bad['checkpoint']['completed'] = False
            if mutation == 'cross_case':
                other = copy.deepcopy(bad['cases'][0])
                other.update(case_id='TEST-0002', problem_definition={})
                bad['cases'][0]['tracks'] = {}
                bad['cases'].append(other)
            if mutation == 'witness': bad['checkpoint']['stop_evidence']['coverage_witness']['track_id'] = 'wrong'
            if mutation == 'missing': bad['cases'][0]['problem_definition'].pop(config['fields'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): render.render(bad)

    def test_unknown_stop_and_unavailable_verifier(self):
        for reason in ('invented', 'evidence_coverage_sufficient'):
            with self.subTest(reason=reason):
                data = batch(); stop(data, reason, 'completed')
                with self.assertRaises(ValueError): render.render(data)

    def test_legacy_audit_is_explicit(self):
        data = batch(); stop(data, 'discovery_pool_exhausted', 'completed')
        data['checkpoint']['discovery_judgement']['judgement'] = 'discovery_pool_exhausted'
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError): render.render(data)
        text = render.render(data, legacy_audit=True)
        self.assertIn('historical / unverified', text)
        self.assertIn('未声称全局搜索空间耗尽', text)
        self.assertEqual(data, before)

    def test_event_causality_uses_full_event_offsets(self):
        data = batch(); queries(data)
        # Discovery before ADAPT-1 but after unrelated events used to pass.
        data['events'].insert(3, {'kind': 'source_discovered', 'source_id': 'S2', 'details': {'query_id': 'ADAPT-1'}})
        data['checkpoint']['search_progress']['adaptive_queries'][1]['produced_new_sources'] = 1
        with self.assertRaises(ValueError): render.validate_adaptive_queries(data)

    def test_seed_duplicate_is_not_a_new_source(self):
        data = batch(); qs = queries(data)
        data['events'].append({'kind': 'source_discovered', 'source_id': 'S1', 'details': {'query_id': 'ADAPT-1'}})
        render.validate_adaptive_queries(data)
        qs[1]['produced_new_sources'] = 1
        with self.assertRaises(ValueError): render.validate_adaptive_queries(data)

    def test_orphan_event_with_empty_list(self):
        data = batch(); data['events'].append({'kind': 'adaptive_query', 'details': {'id': 'ADAPT-0'}})
        with self.assertRaises(ValueError): render.validate_adaptive_queries(data)

    def test_diminishing_returns_and_invalid_windows(self):
        data = batch(); qs = queries(data); stop(data, 'diminishing_returns')
        data['checkpoint']['stop_evidence'] = dict(basis='new_sources', window_query_ids=[q['id'] for q in qs], rationale='no new sources; unresolved claims')
        self.assertIn('⚠️ incomplete', render.render(data))
        for mutation in ('failed', 'duplicate', 'window', 'pending', 'complete'):
            bad = copy.deepcopy(data)
            if mutation == 'failed': bad['checkpoint']['search_progress']['adaptive_queries'][0]['status'] = 'failed'
            if mutation == 'duplicate': bad['checkpoint']['search_progress']['adaptive_queries'][1]['keyword_or_source'] = 'query 0'
            if mutation == 'window': bad['checkpoint']['stop_evidence']['window_query_ids'].reverse()
            if mutation == 'pending': bad['checkpoint']['search_progress']['seed_pending'] = ['SEED-2']
            if mutation == 'complete': stop(bad, 'diminishing_returns', 'completed')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): render.render(bad)

    def test_operational_stop_requires_closed_action_inventory(self):
        data = batch(); stop(data, 'operational_pool_exhausted')
        with self.assertRaises(ValueError): render.render(data)
        data['checkpoint']['stop_evidence'] = dict(rationale='access blocked',
            endpoints=[dict(id='web', pages_fetched=1, limitation='no pagination')],
            actions=[dict(id='SEED-2', status='blocked', reason='403')])
        data['checkpoint']['search_progress']['seed_pending'] = ['SEED-2']
        self.assertIn('未声称全局搜索空间耗尽', render.render(data))
        data['checkpoint']['stop_evidence']['actions'][0]['status'] = 'pending'
        with self.assertRaises(ValueError): render.render(data)

    def test_incomplete_final_checkpoint_can_be_partial(self):
        data = batch(); stop(data, 'user_aborted')
        data['events'].append({'kind': 'checkpoint', 'details': {'opened_since_last_checkpoint': 1, 'final': True, 'completed': False}})
        self.assertIn('incomplete', render.render(data))
        data['events'][-1]['details']['final'] = False
        with self.assertRaises(ValueError): render.render(data)

    def test_status_and_count_forgery(self):
        data = batch(); stop(data, 'max_cases_reached', 'completed')
        data['counts']['accepted_cases'] = 20
        with self.assertRaises(ValueError): render.render(data)
        data = batch(); data['checkpoint']['run_status'] = 'completed'
        with self.assertRaises(ValueError): render.render(data)


class GroundingTests(unittest.TestCase):
    def request(self):
        return dict(run_id='run', source=dict(source_id='S1', run_id='run', status='opened',
                    document_version='v1 section 2', text='Our system does not provide security.\nTwo\n parties decide.'),
                    evidence=[dict(case_id='TEL-0001', field='constraints', source_id='S1',
                                   quote='does not provide security', location='v1 section 2')])

    def test_exact_receipt_and_no_graph_insertion(self):
        result = grounding.validate(self.request())
        self.assertEqual(result['facts'], [])
        self.assertEqual(result['grounding_failures'], [])
        receipt = result['validated_candidates'][0]['grounding']
        self.assertEqual(receipt['semantic_status'], 'unverified')
        self.assertEqual(receipt['location_status'], 'unverified')
        self.assertEqual(len(receipt['source_sha256']), 64)
        start, end = receipt['span']
        self.assertEqual(self.request()['source']['text'][start:end], receipt['matched_text'])

    def test_whitespace_preserves_raw_offsets(self):
        req = self.request(); req['evidence'][0]['quote'] = 'Two parties'
        receipt = grounding.validate(req)['validated_candidates'][0]['grounding']
        self.assertEqual(receipt['method'], 'whitespace_normalized')
        self.assertEqual(receipt['matched_text'], 'Two\n parties')

    def test_missing_negation_rejected_and_audited(self):
        req = self.request(); req['evidence'][0]['quote'] = 'does provide security'
        result = grounding.validate(req)
        self.assertFalse(result['validated_candidates'])
        failure = result['grounding_failures'][0]
        self.assertEqual(failure['failure_type'], 'quote_not_found')
        self.assertEqual(failure['candidate'], req['evidence'][0])

    def test_no_text_metadata_wrong_run_and_source(self):
        for name in ('text', 'status', 'run_id', 'source_id', 'empty_quote'):
            req = self.request()
            if name == 'text': req['source']['text'] = None
            elif name == 'status': req['source']['status'] = 'opened_metadata_only'
            elif name == 'run_id': req['source']['run_id'] = 'old-run'
            elif name == 'source_id': req['evidence'][0]['source_id'] = 'S2'
            else: req['evidence'][0]['quote'] = '  '
            with self.subTest(name=name):
                result = grounding.validate(req)
                self.assertTrue(result['grounding_failures'])
                self.assertFalse(result['validated_candidates'])

    def test_cli_writes_failure_before_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / 'request.json'; report = Path(tmp) / 'report.json'
            req = self.request(); req['evidence'][0]['quote'] = 'invented quote'
            request.write_text(json.dumps(req))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_grounding.py'), str(request), str(report)], capture_output=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(report.read_text())['grounding_failures'][0]['failure_type'], 'quote_not_found')


if __name__ == '__main__':
    unittest.main()


class SourceRoleTests(unittest.TestCase):
    def test_role_counts_current_criteria_per_track_and_retains_score_only_contributions(self):
        from classify_source import classify_source_role, case_references_source
        case = {'problem_definition': {}, 'tracks': {
            'A': {'criteria_evidence': {'C1': {'source_id': 's'}}},
            'B': {'criteria_evidence': {'S1': {'source_id': 's'}}}}}
        self.assertEqual(classify_source_role(case, 's'), 'supporting')
        self.assertTrue(case_references_source(case, 's'))
        case['tracks']['A']['criteria_evidence']['C2'] = {'source_id': 's'}
        self.assertEqual(classify_source_role(case, 's'), 'primary')
        case['tracks'] = {'A': {'criteria_evidence': {}, 'score_evidence': {'D1': {'source_id': 's'}}}}
        self.assertTrue(case_references_source(case, 's'))
        self.assertEqual(classify_source_role(case, 's'), 'supporting')
        case['problem_definition'] = {str(i): {'source_id': 's'} for i in range(4)}
        self.assertEqual(classify_source_role(case, 's'), 'primary')

    def test_legacy_aliases_do_not_double_count_one_condition(self):
        from classify_source import classify_source_role, case_references_source
        case = {'tracks': {'A': {'admission_evidence': ['s'], 'admission_refs': ['s']}}}
        self.assertEqual(classify_source_role(case, 's'), 'supporting')
        self.assertTrue(case_references_source(case, 's'))
