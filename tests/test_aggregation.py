"""Synthetic human instructions and local model doubles; never a real human audit."""
from copy import deepcopy
import unittest

import searchos_adapter as adapter
from aggregation import context, record, resolve
from coverage_policy import reviewed_cases, coverage_witness
from online_policy import action_plan
from export_batch import build
from render_calibration import render_case_evidence
import test_searchos_online as fixtures


CELL = 'problem_definition/TEST-0001.parties_and_roles'


class AggregationTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor
    run_fixture = fixtures.OnlineTests.run_fixture

    def setup_candidates(self):
        self.run_fixture()
        meta = adapter.load(self.path)
        self.original = next(iter(meta['grounding']))
        self.copy_candidate(meta, self.original + '-alternative', value='Two participants')
        adapter.persist(self.path, meta)

    def copy_candidate(self, meta, rid, *, value=None, table='problem_definition', field='parties_and_roles'):
        entry = deepcopy(meta['grounding'][self.original])
        entry['request']['table_id'] = table
        c = entry['report']['validated_candidates'][0]
        c['field'] = field
        if value is not None:
            c['value_text'] = value
        entry['request']['evidence'][0].update(field=field, value_text=c['value_text'])
        meta['grounding'][rid] = entry
        for name in ('attributions', 'reviews'):
            d = deepcopy(next(d for d in meta[name] if d['report_id'] == self.original))
            d.update(report_id=rid, value_text=c['value_text'])
            meta[name].append(d)

    def request(self, kind, cell=CELL, selected=0, pending_reason='human_review_pending'):
        ctx = context(adapter.load(self.path), cell)
        req = {k: ctx[k] for k in ('run_id', 'cell_id', 'snapshot_sha256')}
        req.update(decision_type=kind, reviewer_kind='human', reviewer_id='synthetic-human-fixture',
                   reason='Synthetic explicit choice, not research evidence', request_ref='fixture:instruction')
        if kind == 'select_one':
            req['selected_candidate_id'] = ctx['candidates'][selected]['binding']['candidate_id']
        if kind == 'keep_pending':
            req['pending_reason'] = pending_reason
        return req

    def view(self):
        meta = adapter.load(self.path)
        state = adapter.project(meta)
        return meta, state, reviewed_cases(meta, state)[0]

    def test_rejected_candidate_open_scope_new_source(self):
        self.judgment['judgments'][0]['verdict'] = 'semantic_mismatch'
        self.run_fixture()
        meta = adapter.load(self.path)
        self.original = next(iter(meta['grounding']))
        state = adapter.project(meta)
        plan = action_plan(meta, state, known_url='https://fixture.example/new', case_id='TEST-0001')
        self.assertTrue(any(CELL in t['target_cells'] for t in plan['executable_actions']))
        self.assertIsNone(reviewed_cases(meta, state)[0]['problem_definition']['parties_and_roles']['value_text'])
        _, models = self.run_fixture()
        self.assertFalse(models['judge'].calls)  # Finished rejected assessment is not reviewed again.
        self.copy_candidate(meta, self.original + '-fresh')
        meta['reviews'][-1]['verdict'] = 'supported'
        state = adapter.project(meta)
        self.assertEqual(state.coverage_map.cells[CELL].status.value, 'filled')
        self.assertEqual(meta['reviews'][0]['verdict'], 'semantic_mismatch')

    def test_closed_scope_with_insufficient_evidence_stays_unfinished(self):
        self.judgment['judgments'][0]['verdict'] = 'semantic_mismatch'
        self.run_fixture()
        meta = adapter.load(self.path)
        meta.setdefault('gaps', {})[CELL] = {'investigate': False, 'reason': 'Bounded scope exhausted'}
        state = adapter.project(meta)
        self.assertNotEqual(state.coverage_map.cells[CELL].status.value, 'filled')
        self.assertNotEqual(state.coverage_map.cells[CELL].display_hint, 'aggregation_rejected')
        for task in action_plan(meta, state)['executable_actions']:
            self.assertNotIn(CELL, task['target_cells'])

    def test_selection_consumed_by_native_admission_scoring_and_witness(self):
        self.setup_candidates()
        meta = adapter.load(self.path)
        for f in meta['config']['fields']:
            if f != 'parties_and_roles':
                self.copy_candidate(meta, 'definition-' + f, field=f)
        track = 'nonlocal-coordination'
        for f in meta['config']['tracks'][track]['admission_criteria']:
            self.copy_candidate(meta, 'criterion-' + f, table=track + '_admission', field=f, value='true')
        criterion = next(iter(meta['config']['tracks'][track]['admission_criteria']))
        self.copy_candidate(meta, 'criterion-other', table=track + '_admission', field=criterion, value='false')
        score_fields = list(meta['config']['tracks'][track]['scoring_dimensions'])
        for f in score_fields:
            self.copy_candidate(meta, 'score-' + f, table=track + '_scoring', field=f, value='3')
        self.copy_candidate(meta, 'score-other', table=track + '_scoring', field=score_fields[0], value='1')
        adapter.persist(self.path, meta)
        decision = record(self.path, self.request('select_one'))
        admission_cell = f'{track}_admission/TEST-0001.{criterion}'
        ctx = context(adapter.load(self.path), admission_cell)
        index = next(i for i,c in enumerate(ctx['candidates']) if c['candidate']['value_text'] == 'true')
        record(self.path, self.request('select_one', admission_cell, selected=index))
        score_cell = f'{track}_scoring/TEST-0001.{score_fields[0]}'
        ctx = context(adapter.load(self.path), score_cell)
        index = next(i for i,c in enumerate(ctx['candidates']) if c['candidate']['value_text'] == '3')
        score_decision = record(self.path, self.request('select_one', score_cell, selected=index))
        meta, state, case = self.view()
        self.assertTrue(case['tracks'][track]['passed_admission'])
        self.assertEqual(case['tracks'][track]['scores'][score_fields[0]], 3)
        item = case['problem_definition']['parties_and_roles']
        self.assertEqual(item['aggregation_decision']['id'], decision['id'])
        self.assertFalse(case['pending_aggregation'])
        from audit_policy import self_audit
        audit = self_audit(meta, 'TEST-0001', track)
        self.assertTrue(audit['audit_passed'], audit)
        sources = {c['source_id'] for c in case['problem_definition'].values()}
        from coverage_policy import missing_coverage_fields
        self.assertEqual(missing_coverage_fields(case, meta['config'], sources, track), [])
        witness = coverage_witness([case], meta['config'], sources)
        self.assertEqual(witness['decision_chains'][f'{track}_scoring/{score_fields[0]}']['aggregation_decision']['id'], score_decision['id'])

    def test_reject_all_preserves_candidates_and_does_not_close_scope(self):
        self.setup_candidates()
        original = adapter.load(self.path)
        record(self.path, self.request('reject_all'))
        meta, state, case = self.view()
        self.assertEqual(resolve(meta, CELL)['outcome'], 'rejected')
        self.assertEqual(state.coverage_map.cells[CELL].display_hint, 'aggregation_rejected')
        self.assertIsNone(case['problem_definition']['parties_and_roles']['value_text'])
        self.assertEqual(meta['grounding'], original['grounding'])
        self.assertEqual(meta['reviews'], original['reviews'])
        plan = action_plan(meta, state, known_url='https://fixture.example/new', case_id='TEST-0001')
        self.assertTrue(any(CELL in t['target_cells'] for t in plan['executable_actions']))

    def test_selected_value_only_and_excluded_records_visible(self):
        self.setup_candidates()
        req = self.request('select_one')
        selected = next(c for c in context(adapter.load(self.path), CELL)['candidates']
                        if c['binding']['candidate_id'] == req['selected_candidate_id'])
        record(self.path, req)
        meta, state, case = self.view()
        self.assertEqual(case['problem_definition']['parties_and_roles']['value_text'], selected['candidate']['value_text'])
        self.assertEqual(len(state.evidence_graph.nodes), 2)
        self.assertEqual(len(state.coverage_map.cells[CELL].supporting_evidence_ids), 1)
        batch = build(meta)
        rendered = '\n'.join(render_case_evidence(case, {s['source_id']: s for s in batch['sources']}))
        self.assertIn('不采用作字段结论/', rendered)
        self.assertIn('fixture:instruction', rendered)
        self.assertEqual(len(batch['review_audit']['aggregations']), 1)

    def test_explicit_pending_neither_accepts_nor_rereviews(self):
        self.setup_candidates()
        record(self.path, self.request('keep_pending'))
        meta, state, case = self.view()
        self.assertEqual(resolve(meta, CELL)['outcome'], 'pending')
        self.assertIsNone(case['problem_definition']['parties_and_roles']['value_text'])
        plan = action_plan(meta, state, known_url='https://fixture.example/new', case_id='TEST-0001')
        self.assertTrue(any(CELL in t['target_cells'] for t in plan['executable_actions']))
        before = deepcopy(meta['reviews'])
        _, models = self.run_fixture()
        self.assertFalse(models['judge'].calls)
        self.assertEqual(adapter.load(self.path)['reviews'], before)

    def test_single_selection_contract_and_unsupported_combination(self):
        self.setup_candidates()
        request = self.request('select_one')
        request['selected_candidate_id'] = [request['selected_candidate_id']]
        with self.assertRaises(ValueError):
            record(self.path, request)
        record(self.path, self.request('keep_pending', pending_reason='combined_conclusion_unsupported'))
        meta, state, case = self.view()
        self.assertEqual(case['aggregation'][0]['pending_reason'], 'combined_conclusion_unsupported')
        self.assertEqual(len(case['pending_aggregation']), 2)
        self.assertNotEqual(state.coverage_map.cells[CELL].status.value, 'filled')

    def test_changed_snapshot_never_falls_back_to_automatic_acceptance(self):
        self.setup_candidates()
        record(self.path, self.request('select_one'))
        original = adapter.load(self.path)
        for change in ('candidate', 'review', 'source', 'new_candidate', 'ineligible'):
            with self.subTest(change=change):
                meta = deepcopy(original)
                if change == 'candidate':
                    meta['grounding'][self.original]['report']['validated_candidates'][0]['justification'] += ' revised'
                elif change == 'review':
                    meta['reviews'][0]['reason'] += ' revised'
                elif change == 'source':
                    next(iter(meta['online']['sources'].values()))['source']['document_version'] = 'new-version'
                elif change == 'new_candidate':
                    self.copy_candidate(meta, 'new-candidate')
                else:
                    for r in meta['reviews']:
                        r['verdict'] = 'semantic_mismatch'
                state = adapter.project(meta)
                result = resolve(meta, CELL)
                self.assertEqual(result['pending_reason'], 'evidence_changed')
                self.assertIsNone(result['selected'])
                self.assertNotEqual(state.coverage_map.cells[CELL].status.value, 'filled')
                self.assertEqual(meta['aggregations'], original['aggregations'])

    def test_rejected_candidates_require_explicit_human_reconsideration(self):
        self.setup_candidates()
        record(self.path, self.request('reject_all'))
        meta = adapter.load(self.path)
        excluded = resolve(meta, CELL)['excluded_candidate_ids']
        self.copy_candidate(meta, 'new-candidate')
        adapter.persist(self.path, meta)
        self.assertEqual(resolve(meta, CELL)['excluded_candidate_ids'], excluded)
        self.assertIsNone(resolve(meta, CELL)['selected'])
        request = self.request('select_one')
        request['selected_candidate_id'] = excluded[0]
        request['reason'] = 'Synthetic human explicitly reconsiders previously excluded candidate'
        record(self.path, request)
        result = resolve(adapter.load(self.path), CELL)
        self.assertEqual(result['selected']['binding']['candidate_id'], excluded[0])
        self.assertNotIn(excluded[0], result['excluded_candidate_ids'])

    def test_explicit_reconsideration_cannot_revive_ineligible_candidate(self):
        self.setup_candidates()
        record(self.path, self.request('reject_all'))
        meta = adapter.load(self.path)
        candidate = context(meta, CELL)['candidates'][0]['binding']
        for review in meta['reviews']:
            if (review['report_id'], review['candidate_index']) == (candidate['report_id'], candidate['candidate_index']):
                review['verdict'] = 'semantic_mismatch'
        adapter.persist(self.path, meta)
        before = adapter.load(self.path)
        request = self.request('select_one')
        request['selected_candidate_id'] = candidate['candidate_id']
        with self.assertRaisesRegex(ValueError, 'currently grounded, independently supported'):
            record(self.path, request)
        after, state, case = self.view()
        self.assertEqual(after, before)
        self.assertIsNone(resolve(after, CELL)['selected'])
        self.assertIsNone(case['problem_definition']['parties_and_roles']['value_text'])
        self.assertNotEqual(state.coverage_map.cells[CELL].status.value, 'filled')

    def test_automatic_search_processes_new_source_without_human_writeback(self):
        import asyncio
        from searchos_online import OnlineRunner
        self.setup_candidates()
        original = adapter.load(self.path)
        async def new_source(url, directory, run_id):
            source = await self.opener(url, directory, run_id)
            source.update(source_id='fixture-new', document_version='fixture-v2')
            return source
        models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
        runner = OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=new_source, extractor=self.extractor)
        result = asyncio.run(runner.run(known_url='https://fixture.example/new', case_id='TEST-0001'))
        meta = adapter.load(self.path)
        self.assertTrue(models['extraction'].calls)
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(meta['reviews'][:len(original['reviews'])], original['reviews'])
        self.assertEqual(len(meta['reviews']), len(original['reviews']) + 1)
        self.assertFalse(meta.get('aggregations'))

    def test_binding_stale_request_and_ineligible_candidate_fail_closed(self):
        self.setup_candidates()
        stale = self.request('select_one')
        record(self.path, self.request('keep_pending'))
        with self.assertRaises(ValueError):
            record(self.path, stale)
        for key, value in [('reviewer_kind', 'agent'), ('selected_candidate_id', 'unknown'),
                           ('snapshot_sha256', 'tampered'), ('request_ref', '')]:
            request = self.request('select_one')
            request[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                record(self.path, request)
