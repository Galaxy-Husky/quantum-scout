"""Controlled sequence, configuration and cross-view contracts; not semantic quality evaluation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import searchos_adapter as adapter
from searchos_online import DEFAULTS, OnlineRunner, read_config
from searchos.tools.simple_browser.search.base import SearchResult
from export_batch import build
from render_calibration import render
from coverage_policy import reviewed_cases
from field_diagnostics import field_diagnostics
from online_policy import attribution_metrics
from searchos_project import WorkspaceLayout
import test_searchos_online as fixtures


class SequenceProvider:
    def __init__(self, urls):
        self.urls, self.calls = urls, []

    async def search(self, query, max_results):
        self.calls.append((query, 0))
        return [SearchResult(url=u, title='Generated sequence fixture') for u in self.urls]


class WorkflowContractTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor
    run_fixture = fixtures.OnlineTests.run_fixture

    def test_diagnostic_events_persist_without_rebuilding_views(self):
        self.run_fixture()
        runner = OnlineRunner(self.path, self.config,
            models={'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)},
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        layout = WorkspaceLayout(self.path)
        views = {p: p.read_bytes() for p in layout.socm.glob('*.json')}
        with patch.object(adapter, 'project', side_effect=AssertionError('Audit event rebuilt views')):
            runner.event('model_response', call_id='offline', content='raw response')
        self.assertEqual(adapter.load(self.path)['online']['events'][-1]['content'], 'raw response')
        self.assertEqual({p: p.read_bytes() for p in views}, views)
        with patch.object(adapter, 'project', side_effect=AssertionError('Diagnostic event rebuilt views')):
            runner.event('failure', failure_type='source_unavailable', error_type='SyntheticFailure')
        self.assertEqual({p: p.read_bytes() for p in views}, views)
        self.assertEqual(adapter.load(self.path)['online']['events'][-1]['error_type'], 'SyntheticFailure')

    def test_export_uses_facts_without_repairing_stale_socm_views(self):
        from export_batch import write_export
        result, _ = self.run_fixture()
        layout = WorkspaceLayout(self.path)
        views = [layout.socm / 'search_state.json', layout.socm / 'coverage_map.json']
        for view in views:
            view.write_text('stale derived view')
        schema_before = layout.schema.read_bytes()
        facts_before = adapter.load(self.path)
        batch = write_export(self.path)
        self.assertEqual(batch['cases'], build(deepcopy(facts_before))['cases'])
        self.assertEqual(layout.schema.read_bytes(), schema_before)
        self.assertTrue(all(view.read_text() == 'stale derived view' for view in views))
        facts_after = adapter.load(self.path)
        self.assertEqual(facts_after['online']['checkpoints'][-1]['counts'], batch['counts'])
        for facts in (facts_before, facts_after):
            facts['online']['checkpoints'][-1].pop('counts', None)
        self.assertEqual(facts_before, facts_after)
        # Explicit repair restores views from facts, independent of stale view contents.
        with adapter.locked(self.path):
            adapter.persist(self.path, adapter.load(self.path))
        self.assert_views(self.path, result)

    def test_export_validation_failure_preserves_existing_files_and_facts(self):
        from export_batch import write_export
        self.run_fixture()
        layout = WorkspaceLayout(self.path)
        paths = [layout.adapter, layout.schema, *layout.socm.glob('*.json'),
                 *(self.path / 'calibration').glob('*')]
        original = {p: p.read_bytes() for p in paths if p.is_file()}
        with patch('export_batch.render', side_effect=ValueError('Invalid export fixture')):
            with self.assertRaisesRegex(ValueError, 'Invalid export fixture'):
                write_export(self.path)
        self.assertEqual({p: p.read_bytes() for p in original}, original)

    def test_arxiv_url_versions_share_discovery_identity_before_opening(self):
        urls = ['https://arxiv.org/abs/1309.3923v1', 'https://arxiv.org/pdf/1309.3923v2',
                'https://export.arxiv.org/pdf/1309.3923v1.pdf']
        self.config['max_sources_per_round'] = 3
        runner = OnlineRunner(self.path, self.config,
            models={'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)},
            providers={'serper': SequenceProvider(urls)}, opener=self.opener, extractor=self.extractor)
        result = asyncio.run(runner.run())
        raw, batch = self.assert_views(self.path, result)
        self.assertEqual(len(next(iter(raw['online']['searches'].values()))['results']), 3)
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(batch['counts']['opened_sources'], 1)
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(next(e for e in raw['online']['events'] if e['kind'] == 'round_completed')
                         ['unattempted_sources'], 0)

    def test_explicit_versioned_open_never_substitutes_cached_discovery_alias(self):
        from schema_generator import digest
        urls = ['https://arxiv.org/pdf/1309.3923v1', 'https://arxiv.org/pdf/1309.3923v2']
        outputs = [self.extraction, {'candidates': [{**self.candidate, 'field': 'constraints'}], 'missing': {}}]
        models = {'extraction': fixtures.Model(outputs), 'judge': fixtures.Model(self.judgment)}
        async def opener(url, directory, run_id):
            source = await self.opener(url, directory, run_id)
            return {**source, 'source_id': digest(url), 'document_version': url}
        for url in urls:
            runner = OnlineRunner(self.path, self.config, models=models, providers={'serper': SequenceProvider([])},
                                  opener=opener, extractor=self.extractor)
            result = asyncio.run(runner.run(known_url=url, case_id='TEST-0001'))
            self.assert_views(self.path, result)
        self.assertEqual(self.opened, urls)
        self.assertEqual(result['coverage']['filled'], 2)
        self.assertEqual({r['url'] for r in adapter.load(self.path)['online']['sources'].values()}, set(urls))
        batch = json.loads((self.path / 'calibration/batch.json').read_text())
        source_ids = {s['source_id'] for s in batch['sources']}
        self.assertEqual(len(source_ids), 2)
        self.assertTrue(set(batch['cases'][0]['source_ids']) <= source_ids)

    def test_unidentified_mirror_is_visible_as_separate_source_not_guessed_equal(self):
        from schema_generator import digest
        urls = ['https://arxiv.org/pdf/1309.3923v1', 'https://mirror.example/paper']
        self.config['max_sources_per_round'] = 3
        async def opener(url, directory, run_id):
            source = await self.opener(url, directory, run_id)
            return {**source, 'source_id': digest(url), 'document_version': url}
        runner = OnlineRunner(self.path, self.config,
            models={'extraction': fixtures.Model([self.extraction, {'candidates': [], 'missing': {}}]),
                    'judge': fixtures.Model(self.judgment)},
            providers={'serper': SequenceProvider(urls)}, opener=opener, extractor=self.extractor)
        result = asyncio.run(runner.run())
        raw, batch = self.assert_views(self.path, result)
        self.assertEqual(self.opened, urls)
        self.assertEqual(batch['counts']['opened_sources'], 2)
        self.assertEqual(result['coverage']['filled'], 1)

    def test_low_and_medium_are_tags_not_fill_thresholds(self):
        for confidence in ('low', 'medium'):
            with self.subTest(confidence=confidence):
                path = self.path.parent / confidence
                adapter.prepare(path, case_ids=['TEST-0001'])
                candidate = {**self.candidate, 'confidence': confidence}
                models = {'extraction': fixtures.Model({'candidates': [candidate], 'missing': {}}),
                          'judge': fixtures.Model(self.judgment)}
                runner = OnlineRunner(path, self.config, models=models, providers={'serper': SequenceProvider([])},
                                      opener=self.opener, extractor=self.extractor)
                result = asyncio.run(runner.run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
                raw, batch = self.assert_views(path, result)
                self.assertEqual(result['coverage']['filled'], 1)
                attr, review = raw['attributions'][0], raw['reviews'][0]
                self.assertNotEqual(attr['reviewer_id'], review['reviewer_id'])
                self.assertNotEqual(review['reviewer_id'], 'online-extraction')
                self.assertEqual(batch['quality']['attribution']['audited_samples'], 0)
                self.assertIsNone(batch['quality']['attribution']['attribution_precision'])

    def test_counter_report_contract_is_structural_and_scoped(self):
        from searchos_online import CounterEvidenceSearch
        from pydantic import ValidationError
        search = deepcopy(self.judgment['judgments'][0]['counter_evidence_search'])
        search.update(negation_found=False, conditional_limits_found=False, threat_model_boundary_found=False)
        for change in ({'segments_searched': []}, {'summary': ''}, {'summary': 'x' * 2001},
                       {'negation_found': 'false'}, {'contradictions_found': False}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CounterEvidenceSearch.model_validate({**search, **change})
        # A bland declaration is structurally legal: no semantic-quality oracle exists.
        self.assertEqual(CounterEvidenceSearch.model_validate({**search, 'summary': 'No findings'}).summary,
                         'No findings')
        without_contradictions = {k: v for k, v in search.items() if k != 'contradictions_found'}
        self.assertEqual(CounterEvidenceSearch.model_validate(without_contradictions).contradictions_found, [])
        judgment = deepcopy(self.judgment)
        judgment['judgments'][0]['counter_evidence_search']['segments_searched'] = ['paragraph:999']
        result, _ = self.run_fixture(judge=judgment)
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(result['model_calls'], 3)  # No second semantic call on invalid scope.
        raw = adapter.load(self.path)
        self.assertEqual(raw['reviews'], [])
        self.assertTrue(any('unknown source location' in str(e)
                            for e in raw['online']['events'] if e['kind'] == 'failure'))

    def test_explicit_hard_gaps_leave_blocked_tasks_and_stop_operationally(self):
        # Constructed reachability test, never added to research workspaces.
        meta = adapter.load(self.path)
        for table in meta['schema']['tables']:
            if table['table_id'].endswith('_scoring'):
                continue
            for field in table['attributes']:
                adapter.record_gap(self.path, {'table_id': table['table_id'], 'case_id': 'TEST-0001',
                    'field': field, 'status': 'hard_cell', 'reason': 'Synthetic inaccessible source',
                    'attempts': [{'query': 'generated fixture', 'result': 'unavailable'}]})
        runner = OnlineRunner(self.path, self.config, models={}, providers={'serper': SequenceProvider([])})
        result = asyncio.run(runner.run())
        self.assertEqual(result['stop_reason'], 'operational_pool_exhausted')
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['completed'])
        self.assertTrue(result['stop_evidence']['actions'])
        self.assertTrue(result['stop_evidence']['endpoints'])
        self.assert_views(self.path, result)

    def assert_views(self, path, result):
        raw = adapter.load(path)
        state = adapter.project(raw)
        layout = WorkspaceLayout(path)
        stored_map = json.loads((layout.socm / 'coverage_map.json').read_text())
        self.assertEqual(stored_map, json.loads(state.coverage_map.model_dump_json()))
        self.assertEqual(result['coverage'], adapter.summary(state))
        batch = json.loads((path / 'calibration/batch.json').read_text())
        rebuilt = build(deepcopy(raw))
        for key in ('cases', 'sources', 'counts', 'quality', 'grounding_failures'):
            self.assertEqual(batch[key], rebuilt[key])
        self.assertEqual(batch['quality']['field_diagnostics'], field_diagnostics(raw, reviewed_cases(raw, state)))
        self.assertEqual(batch['quality']['attribution'], attribution_metrics(raw))
        self.assertEqual((path / 'calibration/comparison.md').read_text(), render(batch))
        self.assertEqual(batch['checkpoint']['completed'], result['completed'])
        self.assertEqual(batch['stop_reason'], result['stop_reason'])
        opened = {r['source']['source_id'] for r in raw['online']['sources'].values() if r['status'] == 'opened'}
        self.assertEqual(batch['counts']['opened_sources'], len(opened))
        self.assertFalse(raw['claimed_tasks'])
        return raw, batch

    def test_three_sources_progress_through_real_runner_to_case_coverage_stop(self):
        self.three_source_sequence(admitted=False)

    def test_synthetic_admission_and_scores_stop_at_case_cap_with_consistent_views(self):
        self.three_source_sequence(admitted=True)

    def test_preferred_track_reaches_scoring_before_other_track_can_reject(self):
        self.preferred_track_sequence(admitted=True)

    def test_preferred_track_rejection_does_not_schedule_scores(self):
        self.preferred_track_sequence(admitted=False)

    def preferred_track_sequence(self, admitted):
        # Explicit fixtures exercise scheduling and gates, not real Track eligibility.
        self.config.update(preferred_track='quantum-security', max_rounds=6, max_model_calls=64)
        config = adapter.load(self.path)['config']
        track = config['tracks']['quantum-security']
        def output(names, value='Evidence'):
            return {'candidates': [{**self.candidate, 'field': field, 'quote': 'Evidence.',
                'value_text': 'experimental: Evidence' if field == 'deployment_boundary' else value}
                for field in names], 'missing': {}}
        outputs = [output(config['fields']),
                   output(track['admission_criteria'], 'true' if admitted else 'false')]
        if admitted:
            outputs.append(output(track['scoring_dimensions'], '3'))
        models = {'extraction': fixtures.Model(outputs), 'judge': fixtures.Model(self.judgment)}
        provider = SequenceProvider([])
        async def opener(url, directory, run_id):
            return {'source_id': 'preferred-track-fixture', 'run_id': run_id, 'status': 'opened',
                'url': url, 'document_version': 'synthetic', 'text': '[paragraph:1]\nEvidence.',
                'segments': [{'location': 'paragraph:1', 'text': 'Evidence.'}]}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': provider}, opener=opener, extractor=self.extractor).run(
                known_url='https://fixture.example/preferred-track', case_id='TEST-0001'))
        raw, batch = self.assert_views(self.path, result)
        self.assertEqual(result['stop_reason'], 'case_coverage_complete')
        rounds = [e for e in raw['online']['events'] if e['kind'] == 'round_completed']
        # Completed tasks disappear from Frontier; derive their stable IDs from the contract.
        from schema_generator import digest
        expected = ['problem_definition', 'quantum-security_admission']
        if admitted:
            expected.append('quantum-security_scoring')
        self.assertEqual([e['task_id'] for e in rounds],
                         ['qs_' + digest(['TEST-0001', table])[:20] for table in expected])
        evaluation = batch['cases'][0]['tracks']['quantum-security']
        self.assertEqual(evaluation['passed_admission'], admitted)
        self.assertEqual(evaluation['score_normalized'], 15 if admitted else None)
        # The generated interpretation reaches both consumers; it never sets the verdict.
        calls = [e for e in raw['online']['events'] if e['kind'] == 'model_call_started']
        extraction = next(e for e in calls if e['role'] == 'extraction'
                          and e.get('table_id') == 'quantum-security_admission')
        review = next(e for e in calls if e['role'] == 'judge'
                      and e['input'].get('candidate', {}).get('field') == 'S4')
        s4_rule = extraction['input']['column_rules']['S4']
        self.assertEqual(review['input']['domain_rules'], s4_rule)
        interpreted = json.loads(s4_rule['desc'])
        self.assertFalse(interpreted['require_fault_tolerance'])
        self.assertIn('without fault-tolerant quantum computing', interpreted['description'])
        self.assertIn('neither true nor false', interpreted['description'])
        from contextgem_extractor import document_for
        doc = document_for([{'location': 'page:1', 'text': 'Synthetic laboratory implementation.'}],
            {'target_cells': ['quantum-security_admission/TEST-0001.S4'], 'column_rules': {'S4': s4_rule}})
        self.assertIn('without fault-tolerant quantum computing', doc.concepts[0].description)
        self.assertNotIn('description', config['tracks']['quantum-security']['admission_criteria']['S4'])
        self.assertEqual(provider.calls, [])
        self.assertEqual(models['extraction'].output, [])

    def three_source_sequence(self, admitted):
        # Both outcomes are explicit model fixtures; neither measures real admission quality.
        self.config.update(max_rounds=8, max_model_calls=50, analysis_limit=10,
                           max_sources_per_round=1, max_cases=1 if admitted else 10)
        urls = ['https://fixture.example/source-' + str(i) for i in range(3)]
        provider = SequenceProvider(urls)
        fields = [['real_world_problem', 'parties_and_roles', 'constraints'],
                  ['inputs_and_outputs', 'existing_practice', 'quantum_mechanism_role'],
                  ['success_criteria', 'deployment_boundary']]
        def output(names, value='Evidence'):
            return {'candidates': [{**self.candidate, 'field': field, 'quote': 'Evidence.',
                'value_text': 'experimental: Evidence' if field == 'deployment_boundary' else value}
                for field in names], 'missing': {}}
        track = adapter.load(self.path)['config']['tracks']['nonlocal-coordination']
        criteria = list(track['admission_criteria'])
        outputs = [*(output(fs) for fs in fields), output(criteria, 'true' if admitted else 'false')]
        if admitted:
            # Scheduler completes both admission tables before scoring either Track.
            other = adapter.load(self.path)['config']['tracks']['quantum-security']['admission_criteria']
            outputs.append(output(list(other), 'true'))
            outputs.append(output(list(track['scoring_dimensions']), '3'))
        models = {'extraction': fixtures.Model(outputs),
                  'judge': fixtures.Model(self.judgment)}
        opened = []
        async def opener(url, directory, run_id):
            opened.append(url)
            return {'source_id': url.rsplit('/', 1)[1], 'run_id': run_id, 'status': 'opened', 'url': url,
                'document_version': 'generated-sequence', 'text': '[paragraph:1]\nEvidence. Synthetic test source.',
                'segments': [{'location': 'paragraph:1', 'text': 'Evidence. Synthetic test source.'}]}
        runner = OnlineRunner(self.path, self.config, models=models, providers={'serper': provider},
                              opener=opener, extractor=self.extractor)
        result = asyncio.run(runner.run())
        raw, batch = self.assert_views(self.path, result)
        self.assertEqual(result['stop_reason'], 'max_cases_reached' if admitted else 'case_coverage_complete')
        self.assertTrue(result['completed'])
        self.assertEqual(result['rounds'], 6 if admitted else 4)
        self.assertEqual(opened, urls)
        self.assertEqual(len(provider.calls), 1)
        rounds = [e for e in raw['online']['events'] if e['kind'] == 'round_completed']
        self.assertEqual([r['filled_after'] for r in rounds], [3, 6, 8, 12, 16, 21] if admitted else [3, 6, 8, 12])
        self.assertEqual(batch['cases'][0]['human_audit_status'], 'unverified')
        evaluation = batch['cases'][0]['tracks']['nonlocal-coordination']
        self.assertEqual(evaluation['passed_admission'], admitted)
        if admitted:
            self.assertEqual(evaluation['score_total'], 15)
            self.assertEqual(evaluation['score_normalized'], evaluation['score_total'] / (5 * 5) * 25)
            self.assertEqual(set(evaluation['scores']), set(track['scoring_dimensions']))
        else:
            self.assertFalse(batch['checkpoint']['stop_evidence']['coverage_witness']['passed_admission'])
            self.assertTrue(batch['checkpoint']['stop_evidence']['self_audit']['audit_passed'])
            self.assertFalse(any('_scoring' in e.get('table_id', '') for e in raw['online']['events']))

    def test_distinct_empty_search_sequence_stops_on_exact_window(self):
        self.config.update(max_rounds=5, stall_rounds=2)
        self.config['cases']['TEST-0001']['queries']['serper'] = ['empty-one', 'empty-two', 'not-reached']
        # Unattempted seeds must prevent premature diminishing returns.
        provider = SequenceProvider([])
        runner = OnlineRunner(self.path, self.config, models={}, providers={'serper': provider},
                              opener=self.opener, extractor=self.extractor)
        # Use exactly two seeds; a separate three-seed case below checks the backlog.
        self.config['cases']['TEST-0001']['queries']['serper'].pop()
        result = asyncio.run(runner.run())
        raw, batch = self.assert_views(self.path, result)
        self.assertEqual(result['stop_reason'], 'diminishing_returns')
        self.assertEqual(provider.calls, [('empty-one', 0), ('empty-two', 0)])
        self.assertEqual(result['rounds'], 2)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(result['stop_evidence']['window_query_ids']), 2)

    def test_seed_backlog_prevents_early_diminishing_returns(self):
        self.config.update(max_rounds=2, stall_rounds=1)
        self.config['cases']['TEST-0001']['queries']['serper'] = ['empty-one', 'empty-two', 'pending']
        runner = OnlineRunner(self.path, self.config, models={}, providers={'serper': SequenceProvider([])})
        result = asyncio.run(runner.run())
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['operational_cause'], 'round_limit')
        self.assert_views(self.path, result)

    def test_budget_configuration_matrix_preserves_views_and_caps(self):
        for rounds, calls, limit, stall in [(1, 1, 1, 1), (2, 2, 3, 1), (2, 3, 1, 2),
                                            (1, 8, 3, 2), (3, 3, 3, 3), (3, 8, 1, 1)]:
            with self.subTest(rounds=rounds, calls=calls, limit=limit, stall=stall):
                path = self.path.parent / f'matrix-{rounds}-{calls}-{limit}-{stall}'
                adapter.prepare(path, case_ids=['TEST-0001'])
                config = deepcopy(self.config)
                config.update(max_rounds=rounds, max_model_calls=calls, analysis_limit=limit, stall_rounds=stall)
                models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
                runner = OnlineRunner(path, config, models=models, providers={'serper': SequenceProvider([])},
                                      opener=self.opener, extractor=self.extractor)
                result = asyncio.run(runner.run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
                self.assertLessEqual(result['model_calls'], calls)
                self.assertLessEqual(result['rounds'], rounds)
                raw, batch = self.assert_views(path, result)
                self.assertEqual(sum(r['calls'] for r in batch['quality']['cost_breakdown'].values()), result['model_calls'])
                self.assertEqual(result['coverage']['filled'], 1 if calls >= 3 else 0)

    def test_model_output_faults_fail_closed_and_repair_is_bounded(self):
        from types import SimpleNamespace
        class RawModel:
            async def ainvoke(self, messages):
                return SimpleNamespace(content=self.content, usage_metadata={})
        for content in ('{', '{"candidates": []}', '{"candidates": [], "missing": {}, "extra": 1}'):
            with self.subTest(content=content):
                path = self.path.parent / ('fault-' + str(len(content)))
                adapter.prepare(path, case_ids=['TEST-0001'])
                model = RawModel()
                model.content = content
                runner = OnlineRunner(path, self.config, models={'extraction': model},
                    providers={'serper': SequenceProvider(['https://fixture.example/paper'])},
                    opener=self.opener, extractor=self.extractor)
                result = asyncio.run(runner.run())
                self.assertEqual(result['stop_reason'], 'error')
                self.assertEqual(result['model_calls'], 2)
                self.assertEqual(result['coverage']['filled'], 0)
                raw, _ = self.assert_views(path, result)
                self.assertEqual(len([e for e in raw['online']['events'] if e.get('failure_type') == 'invalid_model_output']), 2)

    def test_independent_workspaces_run_concurrently_without_identity_leak(self):
        def work(index):
            path = self.path.parent / f'parallel-{index}'
            adapter.prepare(path, case_ids=['TEST-0001'])
            candidate = {**self.candidate, 'value_text': f'Fixture participant {index}'}
            models = {'extraction': fixtures.Model({'candidates': [candidate], 'missing': {}}),
                      'judge': fixtures.Model(self.judgment)}
            runner = OnlineRunner(path, self.config, models=models, providers={'serper': SequenceProvider([])},
                                  opener=self.opener, extractor=self.extractor)
            result = asyncio.run(runner.run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
            return path, result
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, range(2)))
        for index, (path, result) in enumerate(results):
            raw, _ = self.assert_views(path, result)
            values = [n.value for n in adapter.project(raw).evidence_graph.nodes]
            self.assertEqual(values, [f'Fixture participant {index}'])


class ConfigurationContractTests(unittest.TestCase):
    def read(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(data))
            return read_config(path)

    def test_provider_backend_matrix_and_invalid_shapes(self):
        base = {'cases': {'TEST-0001': {'description': 'Synthetic configuration'}}}
        for providers in (['serper'], ['tavily'], ['ragflow']):
            for backend in ('none', 'openalex', 'semantic_scholar'):
                with self.subTest(providers=providers, backend=backend), patch(
                        'searchos_configuration.search_provider_name', return_value=providers[0]):
                    config = self.read({**base, 'providers': providers, 'citation_backend': backend})
                    self.assertEqual(config['providers'], providers)
        invalid = [[], None, {'cases': []}, {**base, 'providers': [None]},
            {**base, 'providers': [{}]}, {'cases': {'TEST-0001': {'description': 7}}},
            {'cases': {'TEST-0001': {'description': ' '}}},
            {'cases': {'TEST-0001': {'description': 'fixture', 'queries': [None]}}}]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.read(data)
        for name in set(DEFAULTS) - {'providers', 'preferred_track', 'citation_backend', 'citation_identity', 'citation_expansion_backend'}:
            for value in (0, -1, True, '2', None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.read({**base, name: value})

    def test_optional_track_preference_is_validated_without_setting_verdicts(self):
        base = {'cases': {'TEST-0001': {'description': 'Synthetic configuration'}}}
        for value in (None, 'quantum-security', 'nonlocal-coordination'):
            with self.subTest(value=value):
                self.assertEqual(self.read({**base, 'preferred_track': value})['preferred_track'], value)
        for value in ('QS', '', [], {}, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read({**base, 'preferred_track': value})
