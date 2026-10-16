"""Fixed-source scheduling and bounded attribution context; no live model calls."""
import asyncio
from copy import deepcopy
import json
import unittest

import test_searchos_online as fixtures
from searchos_online import OnlineRunner, context_window
from searchos_adapter import load, project


@unittest.skipUnless(fixtures.AVAILABLE, 'Use SearchOS environment')
class FixedURLContextTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor

    def test_fixed_url_done_source_is_not_claimed_again(self):
        self.config['max_rounds'] = 6
        models = {'extraction': fixtures.Model(self.extraction),
                  'judge': fixtures.Model(self.judgment)}
        def runner():
            return OnlineRunner(self.path, self.config, models=models,
                providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        first = asyncio.run(runner().run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
        meta = load(self.path)
        self.assertEqual(first['rounds'], 1)
        self.assertEqual(first['model_calls'], 3)
        self.assertEqual(first['stop_reason'], 'operational_pool_exhausted')
        self.assertEqual(first['operational_cause'], 'fixed_source_assessed_with_gaps')
        self.assertFalse(first['completed'])
        self.assertTrue(first['stop_evidence']['actions'])
        self.assertIn('not global exhaustion', first['stop_evidence']['endpoints'][0]['limitation'])
        self.assertTrue(meta['online']['assessments'])
        self.assertTrue(all(v == 'done' for v in meta['online']['assessments'].values()))
        self.assertTrue(any(t.status.value == 'pending' for t in project(meta).frontier.questions))
        self.assertEqual(len(meta['online']['attempted_tasks']), 1)
        self.assertEqual(len([e for e in meta['online']['events'] if e['kind'] == 'round_completed']), 1)
        self.assertEqual(self.provider.calls, [])
        second = asyncio.run(runner().run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(second['rounds'], 0)
        self.assertEqual(second['model_calls'], 0)
        self.assertEqual(second['operational_cause'], 'fixed_source_assessed_with_gaps')
        self.assertEqual(len(load(self.path)['online']['attempted_tasks']), 1)
        self.assertEqual(len(self.opened), 1)

    def check_failed_fixed_source(self, max_rounds):
        import httpx
        self.config['max_rounds'] = max_rounds
        async def opener(url, *args):
            self.opened.append(url)
            raise httpx.ConnectError('Synthetic connection failure; no external HTTP')
        models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=opener, extractor=self.extractor).run(
                known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['operational_cause'], 'source_unavailable')
        self.assertEqual(result['stop_evidence']['error_type'], 'ConnectError')
        self.assertNotIn('budget_cause', result['stop_evidence'])
        self.assertFalse(result['completed'])
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['rounds'], 1)
        self.assertEqual(self.opened, ['https://fixture.example/paper'] * 2)
        self.assertEqual(self.provider.calls, [])
        self.assertTrue(all(not model.calls for model in models.values()))
        meta = load(self.path)
        self.assertEqual(meta['claimed_tasks'], [])
        self.assertTrue(all(v['attempts'] == 2 for v in meta['online']['sources'].values()))
        retries = [e for e in meta['online']['events'] if e['kind'] == 'source_retry']
        self.assertEqual(len(retries), 1)
        self.assertTrue(retries[0]['within_invocation'])

    def test_failed_fixed_source_stops_even_on_last_round(self):
        self.check_failed_fixed_source(max_rounds=1)

    def test_failed_fixed_source_does_not_get_a_third_attempt_with_unused_budget(self):
        self.check_failed_fixed_source(max_rounds=6)

    def test_connect_error_once_then_success_continues_into_model_chain(self):
        import httpx
        self.config['max_rounds'] = 6
        original_opener = self.opener
        attempts = []
        async def opener(url, *args):
            attempts.append(url)
            if len(attempts) == 1:
                raise httpx.ConnectError('Synthetic first attempt fails')
            return await original_opener(url, *args)
        models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=opener, extractor=self.extractor).run(
                known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(result['stop_reason'], 'operational_pool_exhausted')
        record = next(iter(load(self.path)['online']['sources'].values()))
        self.assertEqual(record['status'], 'opened')
        self.assertEqual(record['attempts'], 2)
        self.assertNotIn('error_type', record)

    def check_nonretryable_source(self, error):
        self.config['max_rounds'] = 6
        async def opener(url, *args):
            self.opened.append(url)
            raise error
        models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=opener, extractor=self.extractor).run(
                known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['stop_evidence']['error_type'], type(error).__name__)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(self.opened), 1)
        self.assertFalse(any(e['kind'] == 'source_retry' for e in load(self.path)['online']['events']))

    def test_source_connect_timeout_is_not_retried(self):
        import httpx
        self.check_nonretryable_source(httpx.ConnectTimeout('Synthetic timeout'))

    def test_source_429_is_not_retried(self):
        import httpx
        request = httpx.Request('GET', 'https://fixture.example/paper')
        response = httpx.Response(429, request=request)
        self.check_nonretryable_source(httpx.HTTPStatusError('Synthetic 429', request=request, response=response))

    def test_connect_retry_cannot_extend_the_time_budget(self):
        import httpx
        async def opener(url, *args):
            self.opened.append(url)
            runner.deadline = 0
            raise httpx.ConnectError('Synthetic failure at total deadline')
        models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
        runner = OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=opener, extractor=self.extractor)
        result = asyncio.run(runner.run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['operational_cause'], 'wall_clock_limit')
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(len(self.opened), 1)
        self.assertFalse(any(e['kind'] == 'source_retry' for e in load(self.path)['online']['events']))

    def test_context_window_boundaries_and_actual_judge_payload(self):
        segments = [{'location': f'page:{i}', 'text': f'Unique body {i}.'} for i in range(1, 4)]
        for location, expected in [('page:1', [1, 2]), ('page:2', [1, 2, 3]), ('page:3', [2, 3])]:
            with self.subTest(location=location):
                window = context_window(segments, location)
                for i in range(1, 4):
                    self.assertEqual(f'[page:{i}]' in window, i in expected)
                    self.assertEqual(f'Unique body {i}.' in window, i in expected)
        self.assertEqual(context_window(segments[:1], 'page:1'), '[page:1]\nUnique body 1.')
        for supplied in [segments, []]:
            with self.assertRaises(ValueError):
                context_window(supplied, 'page:99')
        async def opener(*args):
            source = await self.opener(*args)
            source['segments'][0]['location'] = 'page:1'
            source['segments'] += segments[1:]
            source['text'] = '\n\n'.join(f"[{s['location']}]\n{s['text']}" for s in source['segments'])
            return source
        extraction = deepcopy(self.extraction)
        extraction['candidates'][0]['location'] = 'page:1'
        judgment = deepcopy(self.judgment)
        judgment['judgments'][0]['counter_evidence_search']['segments_searched'] = ['page:1']
        models = {'extraction': fixtures.Model(extraction), 'judge': fixtures.Model(judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=opener, extractor=self.extractor).run(
                known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(result['coverage']['filled'], 1)
        payload = json.loads(models['judge'].calls[0][1][1])
        self.assertIn('[page:2]\nUnique body 2.', payload['surrounding_text'])
        self.assertNotIn('Unique body 3.', payload['surrounding_text'])
        self.assertEqual(payload['location'], 'page:1')
        self.assertEqual(payload['quote'], self.candidate['quote'])
        self.assertEqual(payload['candidate_field'], self.candidate['field'])
        self.assertEqual(payload['candidate_value'], self.candidate['value_text'])
        self.assertEqual(payload['reference_sentences'], extraction['candidates'][0].get('references', []))
