"""Decision consequences of state convergence, with no external services."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

import searchos_adapter as adapter
from coverage_policy import reviewed_cases
from online_policy import action_plan, decide
from searchos_online import OnlineRunner
from export_batch import build
from render_calibration import render_case_evidence
import test_searchos_online as fixtures


class StateConvergenceTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor
    run_fixture = fixtures.OnlineTests.run_fixture

    def test_multiple_candidates_neither_text_conflict_nor_text_consensus(self):
        self.run_fixture()
        original = adapter.load(self.path)
        rid = next(iter(original['grounding']))
        for text in ('Two parties', 'Two participants'):
            with self.subTest(text=text):
                meta = deepcopy(original)
                entry = deepcopy(meta['grounding'][rid])
                entry['report']['validated_candidates'][0]['value_text'] = text
                other = rid + '-independent-candidate'
                meta['grounding'][other] = entry
                for name in ('attributions', 'reviews'):
                    decision = deepcopy(meta[name][0])
                    decision.update(report_id=other, value_text=text)
                    meta[name].append(decision)
                state = adapter.project(meta)
                cell = state.coverage_map.cells['problem_definition/TEST-0001.parties_and_roles']
                self.assertEqual(cell.status.value, 'uncertain')
                self.assertFalse(cell.has_conflict)
                self.assertEqual(len(cell.supporting_evidence_ids), 2)
                self.assertFalse(state.evidence_graph.edges)
                case = reviewed_cases(meta, state)[0]
                self.assertIsNone(case['problem_definition']['parties_and_roles']['value_text'])
                self.assertEqual(len(case['pending_aggregation']), 2)
                batch = build(meta)
                visible = '\n'.join(render_case_evidence(case, {s['source_id']: s for s in batch['sources']}))
                self.assertIn('待汇总候选', visible)
                self.assertEqual(visible.count('Two parties decide.'), 2)
                definition = next(a for a in action_plan(meta, state)['actions'] if a['task']['table_id'] == 'problem_definition')
                self.assertNotIn('problem_definition/TEST-0001.parties_and_roles', definition['task']['target_cells'])
        self.assertEqual(adapter.load(self.path), original)

    def test_out_of_scope_is_not_evidence_and_decision_is_pure(self):
        meta = adapter.load(self.path)
        for field in meta['config']['fields']:
            adapter.record_gap(self.path, {'table_id': 'problem_definition', 'case_id': 'TEST-0001',
                'field': field, 'status': 'hard_cell', 'reason': 'Explicit bounded investigation',
                'attempts': [{'result': 'unavailable'}]})
        meta = adapter.load(self.path)
        original = deepcopy(meta)
        state = adapter.project(meta)
        plan = action_plan(meta, state)
        definition = next(a for a in plan['actions'] if a['task']['table_id'] == 'problem_definition')
        self.assertIn('outside_investigation_scope', definition['blocked_reasons'])
        self.assertEqual(adapter.summary(state)['filled'], 0)
        self.assertEqual(adapter.summary(state)['hard_cell'], 0)
        # Explicit reasons preserve admission scheduling, without becoming evidence.
        self.assertTrue(any(t['table_id'].endswith('_admission') for t in plan['executable_actions']))
        self.assertEqual(meta, original)

    def test_claimed_work_is_not_budget_exhaustion_and_recovery_keeps_other_owner(self):
        self.run_fixture(extraction={'candidates': [], 'missing': {}})
        meta = adapter.load(self.path)
        task = next(t for t in adapter.project(meta).frontier.questions if t.table_id == 'problem_definition')
        owner = meta['online']['invocations'][-1]['started_at']
        adapter.claim_task(meta, task.id, owner)
        adapter.claim_task(meta, 'manual-other-task', 'manual')
        meta['online']['invocations'][-1]['status'] = 'running'
        adapter.persist(self.path, meta)
        self.run_fixture(extraction={'candidates': [], 'missing': {}})
        current = adapter.load(self.path)
        self.assertEqual(set(adapter.task_claims(current)), {'manual-other-task'})
        self.assertEqual(current['online']['invocations'][0]['operational_cause'], 'process_interrupted')
        self.assertTrue(all('active_task' not in i for i in current['online']['invocations']))
        # Claim the only eligible task externally: zero calls, explicit reason, not budget.
        task = next(t for t in adapter.project(current).frontier.questions if t.table_id == 'problem_definition')
        adapter.claim_task(current, task.id, 'manual')
        adapter.persist(self.path, current)
        result, _ = self.run_fixture(extraction={'candidates': [], 'missing': {}})
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['operational_cause'], 'no_executable_action')
        self.assertIn('task_claimed', result['stop_evidence']['blocked_reasons'])
        self.assertIn(task.id, adapter.task_claims(adapter.load(self.path)))

    def test_frontier_is_display_not_scheduling_input(self):
        self.run_fixture()
        meta = adapter.load(self.path)
        state = adapter.project(meta)
        before = decide(meta, state)
        state.frontier.questions.clear()
        after = decide(meta, state)
        self.assertEqual(before, after)
        self.assertTrue(after['executable_actions'])
        exhausted = decide(meta, state, budget_cause='model_call_limit')
        self.assertFalse(exhausted['executable_actions'])
        self.assertEqual(exhausted['terminal_reason'], 'budget_exhausted')
        self.assertEqual(exhausted['stop_evidence']['budget_cause'], 'model_call_limit')

    def test_failed_and_unattempted_sources_have_different_actions(self):
        from schema_generator import digest
        self.run_fixture()
        meta = adapter.load(self.path)
        url = 'https://fixture.example/unavailable'
        state = adapter.project(meta)
        ready = decide(meta, state, known_url=url, case_id='TEST-0001')
        self.assertTrue(ready['executable_actions'])
        meta['online']['sources'][digest(url)] = {'url': url, 'status': 'failed',
            'error_type': 'ConnectError', 'attempts': 2, 'at': '2000-01-01'}
        blocked = decide(meta, state, known_url=url, case_id='TEST-0001')
        self.assertFalse(blocked['executable_actions'])
        self.assertEqual(blocked['terminal_reason'], 'error')
        self.assertEqual(blocked['stop_evidence']['error_kind'], 'source_unavailable')
        self.assertIn('definition_incomplete', blocked['blocked_reasons'])
        self.assertIn('source_unavailable', blocked['blocked_reasons'])

    def test_fixed_scope_is_shared_by_default_and_explicit_decisions(self):
        self.config['max_rounds'] = 4
        runner = OnlineRunner(self.path, self.config, models={
            'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)},
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        url = 'https://fixture.example/paper'
        asyncio.run(runner.run(known_url=url, case_id='TEST-0001'))
        meta = adapter.load(self.path)
        state = adapter.project(meta)
        implicit = decide(meta, state)
        explicit = decide(meta, state, known_url=url, case_id='TEST-0001')
        self.assertEqual(implicit, explicit)
        self.assertEqual(implicit['terminal_reason'], 'operational_pool_exhausted')
        self.assertFalse(implicit['executable_actions'])
        self.assertTrue(all(t.status.value != 'pending' for t in state.frontier.questions))

    def test_standalone_claim_does_not_ask_frontier_to_schedule(self):
        import io
        from contextlib import redirect_stdout
        frontier_type = type(adapter.project(adapter.load(self.path)).frontier)
        with patch.object(frontier_type, 'next', side_effect=AssertionError('Frontier made a decision')):
            with patch('sys.argv', ['searchos_adapter.py', 'next-task', str(self.path)]), redirect_stdout(io.StringIO()):
                adapter.main()
        claims = adapter.task_claims(adapter.load(self.path))
        self.assertEqual(len(claims), 1)
        self.assertEqual(next(iter(claims.values()))['owner'], 'manual')

    def test_actual_task_cancellation_preserves_provenance_and_resume_boundary(self):
        from searchos_online import StopRequest
        import json

        async def cancelled(message):
            started = asyncio.Event()
            runner = OnlineRunner(self.path, self.config, models={}, providers={'serper': self.provider})
            async def operation(task):
                runner.begin_model_call('judge', 'offline', {}, 'AttributionResult')
                started.set()
                await asyncio.Event().wait()
            runner.run_task = operation
            task = asyncio.create_task(runner.run())
            await asyncio.wait_for(started.wait(), 5)
            task.cancel(message)
            return await asyncio.wait_for(task, 5)

        cases = [(StopRequest('user', 'Explicit user stop', 'user-message:offline'), 'user_aborted', 'user'),
                 (None, 'error', 'unknown'),
                 ('user asked to cancel', 'error', 'unknown'),
                 (StopRequest('agent', 'Authorized experiment stop limit', 'receipt:offline'), 'error', 'agent'),
                 (StopRequest('system', 'Host shutdown', 'host-event:offline'), 'error', 'system')]
        for message, stop, initiator in cases:
            with self.subTest(initiator=initiator, message=message):
                # Same workspace, explicitly invoked offline: previous user origin must not leak.
                result = asyncio.run(cancelled(message))
                self.assertEqual(result['stop_reason'], stop)
                self.assertEqual(result['operational_cause'], 'CancelledError')
                self.assertEqual(result['stop_evidence']['initiator'], initiator)
                self.assertEqual(result['stop_evidence']['request_ref'],
                                 message.request_ref if isinstance(message, StopRequest) else None)
                self.assertFalse(result['completed'])
                self.assertEqual(result['model_calls'], 1)
                meta = adapter.load(self.path)
                self.assertFalse(adapter.task_claims(meta))
                interrupted = [e for e in meta['online']['events'] if e['kind'] == 'round_interrupted'][-1]
                self.assertEqual(interrupted['pending_kind'], 'awaiting_response')
                self.assertEqual(interrupted['pending_stage'], 'attribution')
                self.assertEqual(interrupted['calls_this_round'], {'attribution': 1})
                batch = json.loads((self.path/'calibration/batch.json').read_text())
                self.assertEqual(batch['checkpoint']['stop_evidence'], result['stop_evidence'])
                self.assertEqual(batch['stop_reason'], stop)
                failure = [e for e in meta['online']['events'] if e['kind'] == 'failure'][-1]
                self.assertEqual(failure['initiator'], initiator)
                self.assertEqual(failure['error_type'], 'CancelledError')

    def test_keyboard_interrupt_without_provenance_is_not_user_intent(self):
        runner = OnlineRunner(self.path, self.config, models={}, providers={'serper': self.provider})
        async def operation(task):
            raise KeyboardInterrupt()
        runner.run_task = operation
        result = asyncio.run(runner.run())
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['stop_evidence']['initiator'], 'unknown')
        self.assertEqual(result['stop_evidence']['error_type'], 'KeyboardInterrupt')
        self.assertFalse(adapter.task_claims(adapter.load(self.path)))
