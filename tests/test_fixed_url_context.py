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
        self.assertEqual(first['stop_reason'], 'budget_exhausted')
        self.assertEqual(first['operational_cause'], 'tasks_claimed_or_sources_pending')
        self.assertTrue(meta['online']['assessments'])
        self.assertTrue(all(v == 'done' for v in meta['online']['assessments'].values()))
        self.assertTrue(any(t.status.value == 'pending' for t in project(meta).frontier.questions))
        self.assertEqual(len(meta['online']['attempted_tasks']), 1)
        self.assertEqual(len([e for e in meta['online']['events'] if e['kind'] == 'round_completed']), 1)
        self.assertEqual(self.provider.calls, [])
        second = asyncio.run(runner().run(known_url='https://fixture.example/paper', case_id='TEST-0001'))
        self.assertEqual(second['rounds'], 0)
        self.assertEqual(second['model_calls'], 0)
        self.assertEqual(second['operational_cause'], 'tasks_claimed_or_sources_pending')
        self.assertEqual(len(load(self.path)['online']['attempted_tasks']), 1)
        self.assertEqual(len(self.opened), 1)

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
