"""Fail-closed audit behavior with synthetic bodies and mocked HTTP only."""
from searchos_project import WorkspaceLayout
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import warnings

import httpx
import yaml

import searchos_adapter as adapter
from audit_policy import audit_thresholds, self_audit
from cost_policy import model_costs
from citation_backends import CitationBackend, title_similarity
from coverage_policy import coverage_witness, reviewed_cases
from online_policy import stop_decision
from review_policy import supported_pair
from schema_generator import digest, domain_config, write_strategy_skills
from searchos_online import DEFAULTS, OnlineRunner
from review_fixtures import reviewed_ref


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'audit'
        adapter.prepare(self.path, case_ids=['TEST-0001'])
        self.meta = adapter.load(self.path)
        self.source = {'source_id': 'synthetic', 'run_id': 'audit', 'status': 'opened',
                       'url': 'https://fixture.example/paper', 'document_version': 'page:1',
                       'text': 'Evidence', 'segments': [{'location': 'page:1', 'text': 'Evidence'}]}
        self.meta['online'] = {'sources': {'s': {'status': 'opened', 'source': self.source}},
            'events': [], 'config': {**DEFAULTS, 'providers': ['serper'], 'cases': {}}, 'assessments': {},
            'searches': {}, 'invocations': []}
        self.track = 'nonlocal-coordination'
        spec = importlib.util.spec_from_file_location('audit_grounding',
            Path(__file__).resolve().parents[1] / 'assets/quantum_grounding/executor.py')
        executor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(executor)
        for table, fields, value in (
                ('problem_definition', self.meta['config']['fields'], 'Evidence'),
                (self.track + '_admission', self.meta['config']['tracks'][self.track]['admission_criteria'], 'false')):
            for field in fields:
                ref = reviewed_ref(value, source_id='synthetic')
                ref['field'] = field
                request = {'run_id': 'audit', 'extractor_id': 'fixture-extractor', 'table_id': table,
                           'source': deepcopy(self.source), 'evidence': [{k: v for k, v in ref.items()
                           if k not in {'grounding', 'attribution_review', 'semantic_review'}}]}
                rid = digest(request)
                report = executor.validate(request)
                self.assertEqual(len(report['validated_candidates']), 1)
                self.meta['grounding'][rid] = {'request': request, 'report': report}
                for target, key in [('attributions', 'attribution_review'), ('reviews', 'semantic_review')]:
                    decision = {**ref[key], 'report_id': rid, 'source_sha256': hashlib.sha256(b'Evidence').hexdigest(),
                                'reason': 'Synthetic test evidence'}
                    self.meta[target].append(decision)

    def test_self_audit_recomputes_complete_chain(self):
        audit = self_audit(self.meta, 'TEST-0001', self.track)
        self.assertTrue(audit['audit_passed'])
        self.assertEqual(audit['fields_checked'], 12)
        self.assertTrue(any('_admission/' in key for key in audit['decision_chains']))
        initial = stop_decision(self.meta, adapter.project(self.meta))
        self.assertEqual(initial[0], 'case_coverage_complete')
        self.assertEqual(initial[1]['human_audit_status'], 'unverified')
        self.meta['attribution_checks'] = [{**d, 'reviewer_kind': 'human', 'reviewer_id': 'human-fixture',
            'attribution_correct': True, 'reason': 'Synthetic manual check'} for d in self.meta['attributions'][:3]]
        decision = stop_decision(self.meta, adapter.project(self.meta))
        self.assertEqual(decision[0], 'case_coverage_complete')
        self.assertTrue(decision[1]['self_audit']['audit_passed'])

    def test_field_diagnostics_distinguishes_attribution_and_semantics(self):
        from field_diagnostics import field_diagnostics
        self.meta['attributions'][0]['attribution'] = 'absent'
        self.meta['reviews'][1]['verdict'] = 'abstain'
        cases = reviewed_cases(self.meta, adapter.project(self.meta))
        rows = field_diagnostics(self.meta, cases)
        self.assertTrue(any(r['reasons'].get('attribution_rejected') == 1 for r in rows))
        self.assertTrue(any(r['reasons'].get('semantic_rejected') == 1 for r in rows))
        self.assertFalse(any(r['reasons'].get('no_candidate') for r in rows))

    def test_post_hoc_updates_current_label_without_changing_stop(self):
        from export_batch import build
        from render_calibration import render
        from coverage_policy import validate_case_coverage_stop
        stop, evidence = stop_decision(self.meta, adapter.project(self.meta))
        snapshot = deepcopy(evidence)
        self.meta['online']['sources']['s'].update(url=self.source['url'], at=adapter.now())
        self.meta['online']['invocations'] = [{'status': 'completed', 'stop_reason': stop,
                                              'stop_evidence': evidence}]
        adapter.persist(self.path, self.meta)
        batch = build(adapter.load(self.path))
        validate_case_coverage_stop(batch)
        self.assertIn('机器完成 / 人工未抽查', render(batch))
        with patch('online_policy.stop_decision', side_effect=AssertionError('must not restart')):
            for index, decision in enumerate(self.meta['attributions'][:3]):
                check = {**decision, 'reviewer_kind': 'human', 'reviewer_id': 'human-fixture',
                         'attribution_correct': True, 'reason': 'Synthetic post-hoc audit'}
                result = adapter.audit_attribution(self.path, check, post_hoc=True)
                self.assertEqual(result['human_audit_status']['TEST-0001'],
                                 'verified' if index == 2 else 'partial')
        with self.assertRaisesRegex(ValueError, 'already sampled'):
            adapter.audit_attribution(self.path, check, post_hoc=True)
        current = adapter.load(self.path)
        self.assertEqual(current['online']['invocations'][0]['stop_evidence'], snapshot)
        batch = build(current)
        validate_case_coverage_stop(batch)
        self.assertIn('机器完成 / 人工已验证', render(batch))
        broken = deepcopy(batch)
        broken['checkpoint']['stop_evidence']['self_audit']['audit_passed'] = False
        with self.assertRaises(ValueError):
            validate_case_coverage_stop(broken)
        broken = deepcopy(batch)
        broken['checkpoint']['stop_evidence']['case_audit']['status'] = 'verified'
        with self.assertRaises(ValueError):
            validate_case_coverage_stop(broken)

    def test_off_chain_rejection_and_post_hoc_membership(self):
        decision = self.meta['attributions'][0]
        check = {**decision, 'reviewer_kind': 'human', 'reviewer_id': 'human-fixture',
                 'attribution_correct': False, 'reason': 'Synthetic old candidate error'}
        # An opened source now mismatches; the originally dual-reviewed candidate is off-chain.
        self.source['citation_identity'] = {'state': 'mismatch'}
        adapter.persist(self.path, self.meta)
        with self.assertRaisesRegex(ValueError, 'current coverage chain'):
            adapter.audit_attribution(self.path, check)
        result = adapter.audit_attribution(self.path, check, post_hoc=True)
        self.assertEqual(result['human_audit_status']['TEST-0001'], 'rejected')
        meta = adapter.load(self.path)
        case = reviewed_cases(meta, adapter.project(meta))[0]
        self.assertTrue(case['case_audit']['off_chain_rejected'])
        for field, value in [('reviewer_kind', 'agent'), ('reason', ' '), ('source_sha256', 'wrong')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter.audit_attribution(self.path, {**check, field: value}, post_hoc=True)

    def test_self_audit_names_missing_cells(self):
        self.meta['reviews'].pop(0)
        result = self_audit(self.meta, 'TEST-0001', self.track)
        self.assertEqual(result['rejection_category'], 'missing_coverage')
        self.assertEqual(result['missing_fields'], ['problem_definition/real_world_problem'])

    def test_citation_throttle_resets_and_does_not_switch(self):
        adapter.persist(self.path, self.meta)
        runner = OnlineRunner(self.path, self.meta['online']['config'], providers={'serper': object()})
        for status in [429, 200, 429, 429, 429]:
            runner.observe_citation_requests('semantic_scholar', [{'status_code': status}])
        events = adapter.load(self.path)['online']['events']
        warnings = [e for e in events if e.get('warning_type') == 'citation_backend_throttled']
        self.assertEqual(len(warnings), 1)
        self.assertIn('openalex', warnings[0]['message'])
        self.assertEqual(runner.config['citation_backend'], 'none')

    def test_export_distinguishes_unopened_citations_and_definition_gaps(self):
        from export_batch import build
        from render_calibration import render
        self.meta['reviews'].pop(0)
        self.meta['online']['sources']['s'].update(url=self.source['url'], at=adapter.now())
        self.meta['online']['invocations'] = [{'status': 'incomplete',
            'stop_reason': 'budget_exhausted', 'stop_evidence': {'budget_cause': 'model_call_limit'}}]
        self.meta['citation_tasks'] = {'pending': {'id': 'pending', 'url': 'https://fixture.example/unopened',
            'aliases': ['https://fixture.example/unopened'], 'created_at': adapter.now()}}
        # The citation discovery affects export accounting without creating a new graph task here.
        state = adapter.project({**self.meta, 'citation_tasks': {}})
        with patch('export_batch.adapter.project', return_value=state):
            batch = build(self.meta)
        warnings = batch['quality']['warnings']
        self.assertEqual({w.get('type') for w in warnings if w['category'] == 'source_level'},
                         {'unprocessed_chunks', 'unopened_sources'})
        self.assertFalse(any(w['message'] == 'Discovered sources remain unattempted.' for w in warnings))
        self.assertIn('real_world_problem（硬阻塞）', render(batch))
        field = batch['cases'][0]['problem_definition']['real_world_problem']
        field.update(reason='Explicit synthetic gap', reason_source='explicit_gap')
        self.assertNotIn('（硬阻塞）', render(batch))
        field['reason_source'] = 'none'
        self.assertIn('real_world_problem（硬阻塞）', render(batch))

    def test_sql_defaults_and_downstream_rejection_filter(self):
        import sqlite3
        root = Path(__file__).resolve().parents[1]
        with sqlite3.connect(':memory:') as db:
            db.executescript((root / 'config/schema.sql').read_text())
            db.execute("INSERT INTO cases(case_id, domain) VALUES ('TEST-0001', 'test')")
            self.assertEqual(db.execute('SELECT human_audit_status FROM cases').fetchone()[0], 'unverified')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE cases SET human_audit_status='unknown'")
            db.execute("INSERT INTO cases(case_id, domain, human_audit_status) VALUES ('TEST-0002', 'test', 'rejected')")
            db.execute("INSERT INTO cases(case_id, domain, human_audit_status) VALUES ('TEST-0003', 'test', 'verified')")
            # Strip comments before splitting (comments may themselves contain semicolons).
            sql = '\n'.join(line for line in (root / 'references/queries.sql').read_text().splitlines()
                            if not line.lstrip().startswith('--'))
            results = [db.execute(query).fetchall() for query in sql.split(';') if query.strip()]
            self.assertEqual(results[-2], [('TEST-0003', 'test')])
            self.assertEqual(results[-1], [('TEST-0001', 'test')])
            self.assertEqual(results[3], [(2,)])

    def test_definition_completeness_requires_explicit_recorded_gaps(self):
        self.meta['reviews'] = []
        adapter.persist(self.path, self.meta)
        def current():
            meta = adapter.load(self.path)
            return reviewed_cases(meta, adapter.project(meta))[0]
        case = current()
        self.assertFalse(case['problem_definition_complete'])
        self.assertTrue(all(v['reason'] is None and v['reason_source'] == 'none'
                            for v in case['problem_definition'].values()))
        for field in self.meta['config']['fields']:
            adapter.record_gap(self.path, {'table_id': 'problem_definition', 'case_id': 'TEST-0001',
                'field': field, 'status': 'missing', 'reason': 'Explicit synthetic gap, not evidence'})
        case = current()
        self.assertTrue(case['problem_definition_complete'])
        self.assertTrue(all(not v['value_text'] and v['reason_source'] == 'explicit_gap'
                            for v in case['problem_definition'].values()))
        meta = adapter.load(self.path)
        self.assertIsNone(coverage_witness([case], meta['config'], {'synthetic'}))
        self.assertFalse(any('reason_source' in gap for gap in meta['gaps'].values()))

    def test_counter_report_is_retained_without_lexical_warning(self):
        from searchos_online import CounterEvidenceSearch
        from pydantic import ValidationError
        from export_batch import build
        review = self.meta['reviews'][0]
        review['counter_evidence_search'].update(conditional_limits_found=True, summary='Limits found.',
            conditional_limits_evidence=[{'location': 'page:1', 'quote': 'Evidence'}])
        self.meta['online']['sources']['s'].update(url=self.source['url'], at=adapter.now())
        self.meta['online']['invocations'] = [{'status': 'incomplete', 'stop_reason': 'budget_exhausted'}]
        batch = build(self.meta)
        self.assertFalse(any('counter_evidence_summary_unsubstantiated' in w['message']
                             for w in batch['quality']['warnings']))
        self.assertEqual(batch['review_audit']['reviews'][0]['counter_evidence_search'],
                         review['counter_evidence_search'])
        self.assertEqual(review['verdict'], 'supported')
        with self.assertRaises(ValidationError):
            CounterEvidenceSearch(**{**review['counter_evidence_search'], 'summary': 'x' * 2001})

    def test_manual_labels_use_current_chain_samples_and_bindings(self):
        from audit_policy import case_audit_metrics
        witness = self_audit(self.meta, 'TEST-0001', self.track)
        checks = [{**d, 'reviewer_kind': 'human', 'reviewer_id': 'human-fixture',
                   'attribution_correct': True, 'reason': 'Synthetic check'}
                  for d in self.meta['attributions'][:3]]
        def metrics(rows):
            return case_audit_metrics(witness, rows, self.meta['config'])
        self.assertFalse(metrics(checks[:2])['audit_passed'])  # 2/12 exceeds 10%, but needs 3.
        self.assertTrue(metrics(checks)['audit_passed'])
        for field, value in [('report_id', 'old-candidate'), ('case_id', 'TEST-0002'),
                             ('source_sha256', 'changed'), ('reviewer_kind', 'agent'),
                             ('attribution_correct', False), ('reason', '  ')]:
            rows = deepcopy(checks)
            rows[-1][field] = value
            with self.subTest(field=field):
                self.assertFalse(metrics(rows)['audit_passed'])
        self.assertEqual(metrics(checks + checks)['audited_samples'], 3)

    def test_missing_or_unbound_reviews_never_pass_even_with_cached_chain(self):
        original = deepcopy(self.meta)
        for mutation in ('missing', 'abstain', 'wrong_binding', 'empty_scope', 'unknown_segment', 'legacy_text', 'blank_summary'):
            with self.subTest(mutation=mutation):
                meta = deepcopy(original)
                meta['decision_chains'] = {'fake': {'semantic_verdict': 'supported'}}
                review = meta['reviews'][-1]  # Required admission cell, not just a definition.
                if mutation == 'missing': meta['reviews'].pop()
                elif mutation == 'abstain': review['verdict'] = 'abstain'
                elif mutation == 'wrong_binding': review['source_sha256'] = 'wrong'
                elif mutation == 'empty_scope': review['counter_evidence_search']['segments_searched'] = []
                elif mutation == 'unknown_segment': review['counter_evidence_search']['segments_searched'].append('page:999')
                elif mutation == 'legacy_text': review['counter_evidence_search'] = 'No counter evidence'
                else: review['counter_evidence_search']['summary'] = '  '
                self.assertFalse(self_audit(meta, 'TEST-0001', self.track)['audit_passed'])

    def test_unknown_case_and_empty_reviews(self):
        self.assertFalse(self_audit(self.meta, 'NONE-0001', self.track)['audit_passed'])
        self.meta['reviews'] = []
        self.assertFalse(self_audit(self.meta, 'TEST-0001', self.track)['audit_passed'])

    def test_mutated_body_blocks_stop_and_runner_records_failure(self):
        self.meta['online']['sources']['s']['source']['text'] = 'Changed body'
        self.assertIsNone(stop_decision(self.meta, adapter.project(self.meta)))
        adapter.persist(self.path, self.meta)
        runner = OnlineRunner(self.path, self.meta['online']['config'], providers={'serper': object()})
        self.assertIsNone(runner.checked_stop_decision())
        events = adapter.load(self.path)['online']['events']
        self.assertFalse(events[-2]['audit_passed'])
        self.assertEqual(events[-2]['rejection_category'], 'body_changed')
        self.assertEqual(events[-1]['reason'], 'self_audit_rejected')

    def test_citation_unknown_does_not_lower_evidence_mismatch_does(self):
        for state, count in [('unknown', 12), ('verified', 12), ('mismatch', 0)]:
            with self.subTest(state=state):
                self.source['citation_identity'] = {'state': state}
                projected = adapter.project(self.meta)
                self.assertEqual(adapter.summary(projected)['filled'], count)
                self.assertEqual(self_audit(self.meta, 'TEST-0001', self.track)['audit_passed'], count == 12)

    def test_version_warning_preserves_snapshot_and_tampering_still_errors(self):
        config = deepcopy(self.meta['config'])
        config['scope']['audit']['min_audit_samples'] = 8
        with patch('searchos_adapter.domain_config', return_value=config):
            adapter.persist(self.path, self.meta)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                loaded = adapter.load(self.path)
            self.assertTrue(caught)
            self.assertEqual(loaded['config'], self.meta['config'])
        broken = deepcopy(self.meta)
        broken['config']['fields'].append('tampered')
        adapter.write_json(WorkspaceLayout(self.path).adapter, broken)
        with self.assertRaises(ValueError): adapter.load(self.path)


class AccountingTests(unittest.TestCase):
    def test_limits_small_population_and_zero(self):
        self.assertIsNone(audit_thresholds({}, 0, 0)['audit_warning'])
        self.assertEqual(audit_thresholds({}, 2, 0)['required_audit_samples'], 2)
        self.assertIsNone(audit_thresholds({}, 2, 2)['audit_warning'])
        self.assertEqual(audit_thresholds({}, 100, 2)['audit_warning_level'], 'critical')
        self.assertIsNotNone(audit_thresholds({}, 100, 7)['audit_warning'])
        self.assertIsNone(audit_thresholds({}, 100, 10)['audit_warning'])

    def test_costs_count_failed_attempts_repairs_and_unknown_prices(self):
        events = [
            {'kind': 'model_call_started', 'call_id': 'a', 'output_contract': 'ContextGem'},
            {'kind': 'model_call_started', 'call_id': 'b', 'output_contract': 'AttributionResult'},
            {'kind': 'model_response', 'call_id': 'b', 'usage': {'input_tokens': 4, 'output_tokens': 6}, 'cost_usd': .01},
            {'kind': 'model_call_started', 'call_id': 'c', 'output_contract': 'Judgments'},
            {'kind': 'model_response', 'call_id': 'c', 'usage': {'input_tokens': 10, 'output_tokens': 5}},
            {'kind': 'model_call_started', 'call_id': 'd', 'output_contract': 'Judgments'}]
        result = model_costs(events)
        self.assertEqual(sum(r['calls'] for r in result.values()), 4)
        self.assertEqual(result['semantic']['calls'], 2)
        self.assertEqual(result['semantic']['unknown_usage_calls'], 1)
        self.assertIsNone(result['semantic']['usd'])
        self.assertEqual(result['attribution']['total_tokens'], 10)
        self.assertEqual(result['attribution']['usd'], .01)
        self.assertEqual(result['extraction']['responses'], 0)
        partial = model_costs([{'kind': 'model_call_started', 'call_id': 'x', 'output_contract': 'Judgments'},
            {'kind': 'model_response', 'call_id': 'x', 'usage': {'output_tokens': 6}}])['semantic']
        self.assertEqual(partial['unknown_usage_calls'], 1)
        self.assertEqual(partial['known_token_calls']['input_tokens'], 0)

    def test_generated_strategy_has_snapshot_hash_and_time(self):
        config = domain_config()
        with tempfile.TemporaryDirectory() as folder:
            write_strategy_skills(folder, config)
            from datetime import datetime
            for file in Path(folder).rglob('skill.md'):
                front = yaml.safe_load(file.read_text().split('---')[1])
                self.assertEqual(front['config_sha256'], digest(config))
                self.assertIsNotNone(datetime.fromisoformat(front['generated_at']).tzinfo)


class CitationTests(unittest.TestCase):
    def verify(self, response, title='Quantum key distribution', ids=None):
        def handler(request):
            self.request = request
            if isinstance(response, Exception): raise response
            return response
        backend = CitationBackend('semantic_scholar', httpx.MockTransport(handler))
        result = asyncio.run(backend.verify(ids or {'doi': '10.1234/fixture'}, title))
        return result, backend

    def test_three_states_and_missing_metadata(self):
        for title, state in [('Quantum Key Distribution!', 'verified'), ('Unrelated tomato farming', 'mismatch')]:
            result, _ = self.verify(httpx.Response(200, json={'paperId': 'x', 'title': title, 'externalIds': {'DOI': '10.1234/fixture'}}))
            self.assertEqual(result['state'], state)
            self.assertEqual(self.request.url.params['fields'], 'title,externalIds')
        for status in (404, 429, 500):
            result, backend = self.verify(httpx.Response(status, headers={'retry-after': '4'}))
            self.assertEqual(result['state'], 'unknown')
            self.assertEqual(len(backend.requests), 1)
        for response in (httpx.ReadTimeout('fixture'), httpx.Response(200, json={}), httpx.Response(200, text='not JSON')):
            self.assertEqual(self.verify(response)[0]['state'], 'unknown')

    def test_openalex_expected_title_states(self):
        for expected, state in [('Quantum key distribution', 'verified'), ('Tomato farming', 'mismatch'), (None, 'unknown')]:
            with self.subTest(expected=expected), patch.dict('os.environ', {'OPENALEX_API_KEY': 'fake-openalex-api-key'}):
                backend = CitationBackend('openalex', httpx.MockTransport(lambda request:
                    httpx.Response(200, json={'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.1234/fixture', 'title': 'Quantum key distribution'})))
                result = asyncio.run(backend.verify({'doi': '10.1234/fixture'}, expected))
                self.assertEqual(result['state'], state)
                self.assertEqual(len(backend.requests), 1)

    def test_arxiv_endpoint_and_missing_expected_title(self):
        result, _ = self.verify(httpx.Response(200, json={'paperId': 'x', 'title': 'Real paper'}), title=None,
                                ids={'arxiv': '2601.00001'})
        self.assertEqual(result['state'], 'unknown')
        self.assertIn('ARXIV:2601.00001', self.request.url.path)

    def test_similarity_is_normalized_edit_distance(self):
        self.assertEqual(title_similarity('Quantum: KEY!', 'quantum key'), 1)
        self.assertAlmostEqual(title_similarity('abcdefghij', 'abcdefgxyz'), .7)
        self.assertEqual(title_similarity('', ''), 0)

class OnlineIdentityTests(unittest.TestCase):
    def test_body_open_survives_identity_budget_exhaustion(self):
        from test_searchos_online import OnlineTests
        from searchos_online import BudgetEnd
        fixture = OnlineTests()
        fixture.setUp()
        try:
            fixture.config['citation_backend'] = 'semantic_scholar'
            meta = adapter.load(fixture.path)
            meta['online'] = {'sources': {}, 'events': []}
            adapter.persist(fixture.path, meta)
            runner = OnlineRunner(fixture.path, fixture.config, providers={'serper': fixture.provider}, opener=fixture.opener)
            with patch.object(runner, 'remaining', side_effect=[10, BudgetEnd('wall_clock_limit')]):
                with self.assertRaises(BudgetEnd):
                    asyncio.run(runner.source('https://doi.org/10.1234/fixture', {'target_cells': []}))
            record = next(iter(adapter.load(fixture.path)['online']['sources'].values()))
            self.assertEqual(record['status'], 'opened')
            self.assertEqual(record['source']['citation_identity']['state'], 'unknown')
        finally:
            fixture.doCleanups()

    def test_mismatch_archived_unknown_warns_without_demoting(self):
        import json
        from test_searchos_online import OnlineTests, Model
        for status, title, expected, filled in [(200, 'Quantum key distribution', 'Quantum key distribution', 1),
                (200, 'Unrelated tomato farming', 'Quantum key distribution', 0),
                (200, 'Quantum key distribution', None, 1), (429, '', 'Quantum key distribution', 1)]:
            with self.subTest(status=status):
                fixture = OnlineTests()
                fixture.setUp()
                try:
                    fixture.config['citation_backend'] = 'semantic_scholar'
                    async def search(query, size):
                        from searchos.tools.simple_browser.search.base import SearchResult
                        return [SearchResult(url='https://doi.org/10.1234/fixture', title='Quantum key distribution')]
                    fixture.provider.search = search
                    backend = CitationBackend('semantic_scholar', httpx.MockTransport(
                        lambda request: httpx.Response(status, json={'paperId': 'p', 'title': title, 'externalIds': {'DOI': '10.1234/fixture'}})))
                    models = {'extraction': Model(fixture.extraction), 'judge': Model(fixture.judgment),
                              'orchestrator': Model({'query': 'fixture'})}
                    runner = OnlineRunner(fixture.path, fixture.config, models=models,
                        providers={'serper': fixture.provider}, opener=fixture.opener,
                        extractor=fixture.extractor, citations=backend)
                    result = asyncio.run(runner.run(known_url='https://doi.org/10.1234/fixture',
                                                     case_id='TEST-0001', expected_title=expected))
                    self.assertEqual(result['coverage']['filled'], filled)
                    meta = adapter.load(fixture.path)
                    batch = json.loads((fixture.path / 'calibration/batch.json').read_text())
                    if filled == 0:
                        failures = next(iter(meta['grounding'].values()))['report']['grounding_failures']
                        self.assertEqual(failures[0]['failure_type'], 'citation_mismatch')
                        self.assertEqual(len(batch['grounding_failures']), 1)
                    elif status == 429 or expected is None:
                        self.assertTrue(any(w['category'] == 'citation_unverified' for w in batch['quality']['warnings']))
                    else:
                        self.assertEqual(batch['sources'][0]['citation_identity']['state'], 'verified')
                    self.assertEqual(len(next(e for e in meta['online']['events'] if e['kind'] == 'citation_identity')['requests']), 1)
                    self.assertEqual(sum(row['calls'] for row in batch['quality']['cost_breakdown'].values()), result['model_calls'])
                finally:
                    fixture.doCleanups()


class BaselineTests(unittest.TestCase):
    def test_resume_rejects_changed_or_unknown_historical_baseline_without_mutation(self):
        from baseline_policy import execution_baseline, skill_baseline
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            code = root / 'scripts/test.py'
            code.write_text('initial')
            (root / 'SKILL.md').write_text('skill')
            (root / 'CHANGELOG.md').write_text('history')
            first = skill_baseline(root)
            self.assertEqual(execution_baseline({}, first), first)
            meta = {'online': {'skill_baseline': first, 'invocations': [{'status': 'incomplete'}]}}
            before = deepcopy(meta)
            self.assertEqual(execution_baseline(meta, first), first)
            code.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'baseline changed'):
                execution_baseline(meta, skill_baseline(root))
            self.assertEqual(meta, before)
            with self.assertRaisesRegex(ValueError, 'Historical workspace'):
                execution_baseline({'online': {'invocations': [{}]}}, first)

    def test_reachability_audit_deduplicates_workspaces_and_does_not_claim_unreachable(self):
        from audit_reachability import audit
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'calibration').mkdir()
            (root / 'calibration/batch.json').write_text(json.dumps({
                'stop_reason': 'error', 'quality': {'warnings': [], 'field_diagnostics': [
                    {'reasons': {'quote_not_found': 0}}]}, 'events': []}))
            result = audit([root, root], window=2)
            self.assertEqual(result['snapshots'], 1)
            self.assertFalse(result['automatic_deletion'])
            self.assertEqual(next(r for r in result['stop_values'] if r['branch'] == 'error')['observations'], 1)
            self.assertEqual(next(r for r in result['diagnostic_reasons']
                                  if r['branch'] == 'quote_not_found')['status'], 'insufficient_window')
            result = audit([root], window=1)
            self.assertEqual(next(r for r in result['stop_values']
                                  if r['branch'] == 'diminishing_returns')['status'], 'investigate_reachability')
