"""Online workflow invariants with explicit test doubles, no paid model calls."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    import searchos
    AVAILABLE = True
except ImportError:
    AVAILABLE = False
if AVAILABLE:
    from searchos_adapter import prepare, load, project, summary, persist
    from searchos_online import DEFAULTS, OnlineRunner, single_runner, Extraction
    from searchos_network import source_segments
    from searchos.tools.simple_browser.search.base import SearchResult


class Model:
    def __init__(self, output):
        self.output, self.calls = output, []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if isinstance(self.output, Exception):
            raise self.output
        if 'attribution_reason' in messages[0][1]:
            return SimpleNamespace(content=json.dumps(getattr(self, 'attribution_output', {
                'candidate_index': 0, 'attribution': 'attributed', 'attribution_reason': 'Synthetic explicit case link'})), usage_metadata={})
        output = self.output.pop(0) if isinstance(self.output, list) else self.output
        return SimpleNamespace(content=json.dumps(output), usage_metadata={'output_tokens': 10})


class Provider:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def search(self, query, max_results):
        self.calls.append((query, 0))
        if self.fail:
            raise TimeoutError('synthetic provider failure')
        return [SearchResult(url='https://fixture.example/paper', title='Test fixture')]


@unittest.skipUnless(AVAILABLE, 'Use SearchOS environment')
class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'online-test'
        prepare(self.path, case_ids=['TEST-0001'])
        self.config = {**DEFAULTS, 'providers': ['serper'], 'max_rounds': 1, 'cases': {'TEST-0001': {
            'description': 'Synthetic fixture; not research evidence', 'queries': {'serper': ['fixture']}}}}
        self.candidate = {'field': 'parties_and_roles', 'value_text': 'Two parties',
                          'quote': 'Two parties decide.', 'location': 'paragraph:1',
                          'evidence_level': 'primary', 'confidence': 'medium', 'justification': 'Synthetic source names two parties.'}
        self.extraction = {'candidates': [self.candidate], 'missing': {}}
        self.judgment = {'judgments': [{'candidate_index': 0, 'verdict': 'supported',
                                       'location_checked': True, 'domain_rule_met': 'met', 'domain_rule_reason': 'Synthetic field rule satisfied',
                                       'counter_evidence_search': {'summary': 'Synthetic search for not and only',
                    'segments_searched': ['paragraph:1'], 'negation_found': False,
                    'conditional_limits_found': False, 'threat_model_boundary_found': False, 'contradictions_found': []},
                                       'reason': 'Synthetic test judgment.'}]}
        self.opened = []
        self.provider = Provider()

    async def opener(self, url, directory, run_id):
        self.opened.append(url)
        text = '[paragraph:1]\nTwo parties decide. This is synthetic text for an offline fixture only.'
        return {'source_id': 'fixture', 'run_id': run_id, 'status': 'opened',
                'url': url, 'document_version': 'fixture-v1', 'text': text,
                'segments': [{'location': 'paragraph:1', 'text': text.split('\n', 1)[1]}]}

    async def extractor(self, runner, context, segments):
        return await runner.call('extraction', 'Offline fixture extractor', {**context, 'segments': segments}, Extraction)

    def run_fixture(self, extraction=None, judge=None):
        models = {'orchestrator': Model({'query': 'fixture'}),
                  'extraction': Model(extraction if extraction is not None else self.extraction),
                  'judge': Model(judge if judge is not None else self.judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor).run())
        return result, models

    def test_direct_source_uses_full_pipeline_and_cached_body_on_resume(self):
        models = {'extraction': Model(self.extraction), 'judge': Model(self.judgment),
                  'orchestrator': Model({'query': 'fixture'})}
        def runner():
            return OnlineRunner(self.path, self.config, models=models,
                providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        result = asyncio.run(runner().run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(result['model_calls'], 3)
        asyncio.run(runner().run())
        self.assertEqual(len(self.opened), 1)
        self.assertEqual(self.provider.calls, [('fixture', 0)])  # Finished source is not reprocessed.
        self.assertEqual(len(models['extraction'].calls), 1)
        events = load(self.path)['online']['events']
        opened = [e for e in events if e['kind'] == 'source_opened']
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]['details']['opened_order'], 1)
        self.assertTrue(any(e['kind'] == 'stop_decision' and e.get('final') for e in events))

    def test_interruption_uses_earliest_unanswered_call_in_round(self):
        from searchos_online import BudgetEnd
        runner = OnlineRunner(self.path, self.config, providers={'serper': self.provider},
                              opener=self.opener, extractor=self.extractor)
        async def interrupted(task):
            runner.begin_model_call('judge', 'fixture', {}, 'AttributionResult')
            runner.begin_model_call('judge', 'fixture', {}, 'Judgments')
            raise BudgetEnd('synthetic interruption')
        runner.run_task = interrupted
        asyncio.run(runner.run())
        event = next(e for e in load(self.path)['online']['events'] if e['kind'] == 'round_interrupted')
        self.assertEqual(event['pending_stage'], 'attribution')
        self.assertEqual(event['pending_kind'], 'awaiting_response')
        self.assertEqual(event['calls_this_round'], {'attribution': 1, 'semantic': 1})

    def test_interrupted_chunk_stays_pending_and_resumes_missing_review(self):
        self.config['max_model_calls'] = 2
        self.extraction['candidates'].insert(0, {**self.candidate, 'field': 'inputs_and_outputs', 'location': 'unknown'})
        first, _ = self.run_fixture()
        meta = load(self.path)
        self.assertEqual(list(meta['online']['assessments'].values()), [0])
        self.assertEqual(first['stop_evidence']['calls_by_category_at_exhaustion'],
                         {'extraction': 1, 'attribution': 1})
        interrupted = [e for e in meta['online']['events'] if e['kind'] == 'round_interrupted'][-1]
        self.assertEqual(interrupted['round'], 1)
        self.assertEqual(interrupted['pending_stage'], 'semantic')
        self.assertEqual(interrupted['pending_kind'], 'next_stage_blocked_by_budget')
        self.assertEqual(interrupted['calls_cumulative'], {'extraction': 1, 'attribution': 1})
        self.assertEqual(interrupted['calls_this_round'], {'extraction': 1, 'attribution': 1})
        batch = json.loads((self.path / 'calibration/batch.json').read_text())
        self.assertTrue(any(w.get('type') == 'unprocessed_chunks' and 'TEST-0001/problem_definition' in w['message']
                            for w in batch['quality']['warnings']))
        second, models = self.run_fixture()
        self.assertEqual(second['coverage']['filled'], 1)
        self.assertEqual(models['extraction'].calls, [])
        self.assertEqual(len(models['judge'].calls), 1)
        self.assertEqual(list(load(self.path)['online']['assessments'].values()), ['done'])
        batch = json.loads((self.path / 'calibration/batch.json').read_text())
        self.assertEqual({k: batch['quality']['model_calls'][k] for k in ('invocation', 'workspace')},
                         {'invocation': 1, 'workspace': 3})
        rows = batch['quality']['model_calls']['by_table']
        self.assertEqual(rows[0]['invocation'], {'semantic': 1})
        self.assertEqual(rows[0]['workspace'], {'extraction': 1, 'attribution': 1, 'semantic': 1})

    def test_legacy_table_call_grouping_preserves_unknown_and_totals(self):
        from online_policy import table_model_calls
        events = [
            {'kind': 'model_call_started', 'at': '1', 'cost_category': 'orchestrator'},
            {'kind': 'assessment_started', 'case_id': 'C', 'table_id': 'problem_definition'},
            {'kind': 'model_call_started', 'at': '1', 'cost_category': 'extraction'},
            {'kind': 'round_completed'},
            {'kind': 'assessment_started', 'case_id': 'C', 'table_id': 'admission'},
            {'kind': 'model_call_started', 'at': '2', 'cost_category': 'semantic'},
            {'kind': 'round_interrupted'},
            {'kind': 'model_call_started', 'at': '2', 'cost_category': 'extraction'},
        ]
        rows = {(r['case_id'], r['table_id']): r for r in table_model_calls(events, '2')}
        self.assertEqual(rows[('C', 'problem_definition')]['invocation'], {})
        self.assertEqual(rows[('C', 'admission')]['invocation'], {'semantic': 1})
        self.assertEqual(rows[(None, None)]['workspace'], {'orchestrator': 1, 'extraction': 1})
        self.assertEqual(sum(sum(r['workspace'].values()) for r in rows.values()), 4)

    def test_two_round_chunks_report_incremental_and_cumulative_calls(self):
        self.config.update(max_rounds=2, max_context_chars=80)
        async def opener(url, directory, run_id):
            source = await self.opener(url, directory, run_id)
            source['segments'].append({'location': 'paragraph:2', 'text': 'Later page. ' * 5})
            source['text'] += '\n[paragraph:2]\n' + source['segments'][1]['text']
            return source
        runner = OnlineRunner(self.path, self.config, models={
            'extraction': Model([self.extraction, {'candidates': [], 'missing': {}}]), 'judge': Model(self.judgment)},
            providers={'serper': self.provider}, opener=opener, extractor=self.extractor)
        asyncio.run(runner.run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
        meta = load(self.path)
        rounds = [e for e in meta['online']['events'] if e['kind'] == 'round_completed']
        self.assertEqual([e['calls_this_round'] for e in rounds], [{'extraction': 1, 'attribution': 1, 'semantic': 1}, {'extraction': 1}])
        self.assertEqual([e['calls_cumulative'] for e in rounds], [{'extraction': 1, 'attribution': 1, 'semantic': 1}, {'extraction': 2, 'attribution': 1, 'semantic': 1}])
        self.assertEqual([e['start_segment'] for e in meta['online']['events'] if e['kind'] == 'source_context'], [0, 1])
        from online_policy import current_assessments
        self.assertTrue(all(meta['online']['assessments'][key] == 'done' for key in current_assessments(meta['online']).values()))
        batch = json.loads((self.path / 'calibration/batch.json').read_text())
        self.assertFalse(any(w['category'] == 'source_level' for w in batch['quality']['warnings']))

    def test_assessment_scope_inheritance_and_restarts(self):
        from online_policy import resolve_assessment, current_assessments
        source = {'source_id': 'fixture', 'document_version': 'v1', 'segments': [{}, {}]}
        fields = ['real_world_problem', 'parties_and_roles', 'constraints']
        task = {'id': 'stable-task', 'table_id': 'problem_definition',
                'target_cells': ['problem_definition/TEST-0001.' + f for f in fields[:2]]}
        old = {'kind': 'assessment_started', 'assessment_id': 'old', 'task_id': task['id'],
               'case_id': 'TEST-0001', 'table_id': 'problem_definition', 'source_id': 'fixture',
               'document_version': 'v1', 'total_segments': 2, 'fields': fields, 'start_segment': 0}
        online = {'events': [old], 'assessments': {'old': 1}}
        plan = resolve_assessment(online, task, source)
        self.assertEqual(plan['cursor'], 1)
        self.assertEqual(plan['inherited_from'], 'old')
        self.assertEqual(plan['cursor_source'], 'inherited')
        self.assertEqual(plan['inherited_total_segments'], 2)
        for mutation in ('version', 'segments', 'expanded', 'case', 'table', 'source'):
            with self.subTest(mutation=mutation):
                changed_task, changed_source = deepcopy(task), deepcopy(source)
                if mutation == 'version': changed_source['document_version'] = 'v2'
                elif mutation == 'segments': changed_source['segments'].append({})
                elif mutation == 'expanded': changed_task['target_cells'].append('problem_definition/TEST-0001.existing_practice')
                elif mutation == 'case': changed_task['target_cells'] = ['problem_definition/TEST-0002.real_world_problem']
                elif mutation == 'table':
                    changed_task.update(table_id='other', target_cells=['other/TEST-0001.real_world_problem'])
                else: changed_source['source_id'] = 'another'
                result = resolve_assessment(online, changed_task, changed_source)
                self.assertEqual(result['cursor'], 0)
                self.assertIsNone(result['assessment_id'])
                self.assertEqual(result['cursor_source'], 'restarted' if mutation in {'version', 'segments', 'expanded'} else 'new')
                if mutation == 'expanded': self.assertEqual(result['restart_reason'], 'target_expanded')
        online['assessments']['old'] = 'done'
        meta = load(self.path)
        meta['online'] = {**online, 'config': self.config}
        persist(self.path, meta)
        runner = OnlineRunner(self.path, self.config, providers={'serper': self.provider})
        plan = resolve_assessment(online, task, source)
        identity, cursor = runner.start_assessment(task, plan)
        self.assertEqual(cursor, 'done')
        current = load(self.path)['online']
        self.assertEqual(current['assessments'], {'old': 'done', identity: 'done'})
        self.assertEqual(current_assessments(current), {('TEST-0001', 'problem_definition', 'fixture'): identity})
        self.assertEqual(runner.calls, 0)
        from online_policy import assessment_done
        current['sources'] = {'s': {'status': 'opened', 'source': deepcopy(source)}}
        self.assertTrue(assessment_done(current, identity))
        current['sources']['s']['source']['document_version'] = 'changed'
        self.assertFalse(assessment_done(current, identity))
        # Expanding again starts a fresh record without deleting either prior record.
        task['target_cells'].append('problem_definition/TEST-0001.existing_practice')
        identity2, cursor = runner.start_assessment(task, resolve_assessment(current, task, source))
        self.assertEqual(cursor, 0)
        current = load(self.path)['online']
        self.assertEqual(len(current['assessments']), 3)
        self.assertEqual(current['events'][-1]['restart_reason'], 'target_expanded')
        self.assertEqual(current_assessments(current), {('TEST-0001', 'problem_definition', 'fixture'): identity2})
        self.assertEqual(runner.calls, 0)

    def test_category_accounting_has_no_fractional_hard_quotas(self):
        from searchos_online import BudgetEnd
        for budget in (8, 64):
            with self.subTest(budget=budget):
                self.config['max_model_calls'] = budget
                runner = OnlineRunner(self.path, self.config, providers={'serper': self.provider})
                meta = load(self.path)
                meta['online'] = {'events': []}
                persist(self.path, meta)
                reviews = (budget - 2) // 2
                contracts = ['Extraction'] + ['AttributionResult'] * reviews + ['Judgments'] * reviews + ['Query']
                for contract in contracts:
                    runner.begin_model_call('fixture', 'fixture', {}, contract)
                with self.assertRaisesRegex(BudgetEnd, 'model_call_limit'):
                    runner.begin_model_call('fixture', 'fixture', {}, 'Judgments')
                self.assertEqual(runner.category_calls, {'extraction': 1, 'attribution': reviews,
                                                       'semantic': reviews, 'orchestrator': 1})

    def test_actual_grounding_and_separate_review_before_filling(self):
        result, models = self.run_fixture()
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(result['coverage']['evidence_nodes'], 1)
        self.assertEqual(len(models['extraction'].calls), 1)
        self.assertEqual(len(models['judge'].calls), 2)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['status'], 'incomplete')
        self.assertFalse(result['claims_global_exhaustion'])
        self.assertEqual(load(self.path)['claimed_tasks'], [])

    def test_quote_not_found_never_reaches_judge_or_graph(self):
        self.candidate['quote'] = 'Fabricated quote.'
        result, models = self.run_fixture()
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(models['judge'].calls, [])
        entry = next(iter(load(self.path)['grounding'].values()))
        self.assertEqual(entry['report']['grounding_failures'][0]['failure_type'], 'quote_not_found')

    def test_semantic_mismatch_is_audited(self):
        self.judgment['judgments'][0]['verdict'] = 'semantic_mismatch'
        result, _ = self.run_fixture()
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(result['coverage']['evidence_nodes'], 0)
        self.assertGreater(result['coverage']['failure_patterns'], 0)

    def test_abstention_leaves_uncertain_and_failure_memory(self):
        self.judgment['judgments'][0]['verdict'] = 'abstain'
        result, _ = self.run_fixture()
        self.assertEqual(result['coverage']['uncertain'], 1)
        self.assertEqual(load(self.path)['reviews'][0]['verdict'], 'abstain')
        self.assertEqual(result['coverage']['filled'], 0)

    def test_budget_between_grounding_and_review_keeps_resumable_task(self):
        self.config['max_model_calls'] = 1
        result, models = self.run_fixture()
        self.assertEqual(result['operational_cause'], 'model_call_limit')
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(result['coverage']['uncertain'], 1)
        self.assertEqual(result['coverage']['running_tasks'], 0)
        self.assertEqual(models['judge'].calls, [])

    def test_failed_search_is_not_empty_success_and_retried_once_on_resume(self):
        self.provider.fail = True
        first, _ = self.run_fixture()
        second, _ = self.run_fixture()
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.opened, [])
        search = next(iter(load(self.path)['online']['searches'].values()))
        self.assertEqual(search['status'], 'failed')
        self.assertEqual(search['attempts'], 2)
        self.assertEqual(len(search['previous_attempts']), 1)
        self.assertGreater(second['coverage']['failure_patterns'], 0)
        self.assertNotEqual(second['stop_reason'], 'diminishing_returns')

    def test_model_error_releases_claim_and_does_not_report_exhaustion(self):
        result, _ = self.run_fixture(extraction=RuntimeError('synthetic model error'))
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['coverage']['running_tasks'], 0)
        self.assertEqual(result['coverage']['filled'], 0)

    def test_mixed_contract_rejections_preserve_valid_candidate_and_judges(self):
        invalid = {**self.candidate, 'field': 'constraints', 'quote': 'x' * 51}
        high = {**self.candidate, 'field': 'real_world_problem', 'confidence': 'high'}
        result, models = self.run_fixture(extraction={'candidates': [invalid, high, self.candidate], 'missing': {}})
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(len(models['judge'].calls), 2)
        self.assertEqual(len(models['extraction'].calls), 1)
        events = [e for e in load(self.path)['online']['events'] if e['kind'] == 'contract_rejection']
        self.assertEqual([e['candidate'] for e in events], [invalid, high])
        batch = json.loads((self.path / 'calibration/batch.json').read_text())
        self.assertEqual(batch['quality']['contract_rejections']['candidates'], 2)
        self.assertEqual(batch['quality']['contract_rejections']['affected_calls'], 1)

    def test_entrypoint_and_contextgem_share_contract_exception(self):
        import runpy
        from contextgem_extractor import ContractViolation
        namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/searchos_online.py'),
                                  run_name='cli_test_entry')
        self.assertIs(namespace['ContractViolation'], ContractViolation)

    def test_all_rejected_is_classified_without_advancing_cursor(self):
        invalid = {**self.candidate, 'confidence': 'high'}
        result, models = self.run_fixture(extraction={'candidates': [invalid], 'missing': {}})
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(result['stop_evidence']['error_kind'], 'contract_violation')
        self.assertFalse(models['judge'].calls)
        meta = load(self.path)
        self.assertEqual(list(meta['online']['assessments'].values()), [0])
        event = next(e for e in reversed(meta['online']['events']) if e['kind'] == 'round_interrupted')
        self.assertEqual(event['pending_kind'], 'contract_rejected')
        self.assertIn('contract_violation', (self.path / 'calibration/comparison.md').read_text())

    def test_malformed_typed_output_fails_closed(self):
        result, _ = self.run_fixture(extraction={'candidates': [{'field': 'unknown'}], 'missing': {}})
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['coverage']['evidence_nodes'], 0)

    def test_one_schema_repair_is_audited_and_charged_to_budget(self):
        invalid = deepcopy(self.extraction)
        invalid['candidates'][0]['confidence'] = 'high'
        result, models = self.run_fixture(extraction=[invalid, self.extraction])
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(len(models['extraction'].calls), 2)
        self.assertTrue(any(e.get('failure_type') == 'invalid_model_output'
                            for e in load(self.path)['online']['events']))

    def test_schema_repair_cannot_exceed_model_budget(self):
        self.config['max_model_calls'] = 1
        invalid = deepcopy(self.extraction)
        invalid['candidates'][0]['confidence'] = 'high'
        result, models = self.run_fixture(extraction=invalid)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['model_calls'], 1)
        self.assertEqual(result['coverage']['filled'], 0)

    def test_wrong_location_does_not_fill(self):
        self.candidate['location'] = 'page:999'
        result, models = self.run_fixture()
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertFalse(models['judge'].calls)
        self.assertGreater(result['coverage']['failure_patterns'], 0)

    def test_one_search_result_set_is_cached_on_resume(self):
        self.config.update(results_per_page=1)
        self.run_fixture()
        self.run_fixture()
        self.assertEqual(self.provider.calls, [('fixture', 0)])
        self.assertEqual(len(load(self.path)['online']['searches']), 1)
        self.assertEqual(len(self.opened), 1)

    def test_search_http_failure_records_status_without_success_or_body_open(self):
        import httpx
        class Limited(Provider):
            async def search(inner, query, max_results):
                inner.calls.append((query, 0))
                response = httpx.Response(429, headers={'retry-after': '60'},
                                          request=httpx.Request('POST', 'https://fixture.example/search'))
                response.raise_for_status()
        self.provider = Limited()
        self.run_fixture()
        record = next(iter(load(self.path)['online']['searches'].values()))
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['status_code'], 429)
        self.assertEqual(record['retry_after'], '60')
        self.assertEqual(record['results'], [])
        self.assertEqual(self.opened, [])

    def test_new_source_without_verified_cells_is_not_diminishing_returns(self):
        self.config['stall_rounds'] = 1
        result, _ = self.run_fixture(extraction={'candidates': [], 'missing': {'parties_and_roles': 'No evidence'}})
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['coverage']['filled'], 0)
        # A single document's missing fields do not unlock admission.
        self.assertEqual(result['coverage']['blocked_tasks'], 4)

    def test_parallel_runner_is_rejected(self):
        with single_runner(self.path):
            with self.assertRaises(RuntimeError):
                self.run_fixture()

    def test_source_backlog_is_drained_before_new_queries(self):
        self.config['max_sources_per_round'] = 1
        class TwoSources(Provider):
            async def search(inner, query, max_results):
                inner.calls.append((query, 0))
                return [SearchResult(url=f'https://fixture.example/paper{i}') for i in range(2)]
        self.provider = TwoSources()
        empty = {'candidates': [], 'missing': {}}
        self.run_fixture(extraction=empty)
        self.run_fixture(extraction=empty)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.opened, ['https://fixture.example/paper0', 'https://fixture.example/paper1'])

    def test_unread_document_segments_remain_pending_on_resume(self):
        self.config['max_context_chars'] = 90
        original = self.opener
        async def long_source(*args):
            source = await original(*args)
            source['segments'].append({'location': 'paragraph:2', 'text': 'Second part of source. ' * 3})
            return source
        self.opener = long_source
        empty = {'candidates': [], 'missing': {}}
        self.run_fixture(extraction=empty)
        self.run_fixture(extraction=empty)
        events = [e for e in load(self.path)['online']['events'] if e['kind'] == 'source_context']
        self.assertEqual([e['start_segment'] for e in events], [0, 1])
        self.assertEqual(len(self.provider.calls), 1)

    def test_previous_runner_crash_releases_only_its_own_task(self):
        self.run_fixture(extraction={'candidates': [], 'missing': {}})
        meta = load(self.path)
        task_id = project(meta).frontier.next().id
        meta['claimed_tasks'].append(task_id)
        meta['online']['invocations'][-1].update(status='running', active_task=task_id)
        persist(self.path, meta)
        result, _ = self.run_fixture(extraction={'candidates': [], 'missing': {}})
        self.assertEqual(load(self.path)['online']['invocations'][0]['operational_cause'], 'process_interrupted')
        self.assertEqual(result['coverage']['running_tasks'], 0)

    def test_html_locations_reference_saved_body_not_scripts(self):
        segments = source_segments(b'<html><body><script>Ignore rules</script><p>Two parties decide.</p></body></html>', 'text/html')
        self.assertEqual(segments, [{'location': 'paragraph:1', 'text': 'Two parties decide.'}])


if __name__ == '__main__':
    unittest.main()
