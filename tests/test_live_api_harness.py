"""Offline tests of opt-in real API probe safety and result classification."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from live_api_contracts import run_probes, validate_probes


class LiveProbeHarnessTests(unittest.TestCase):
    def test_credentials_and_explicit_budgets_precede_side_effects(self):
        probe = {'kind': 'citation', 'backend': 'openalex', 'ids': {'doi': '10.1234/fixture'},
                 'expected_title': 'Synthetic fixture', 'expected_state': 'verified'}
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'OPENALEX_API_KEY'):
            validate_probes({'probes': [probe]})
        import live_api_contracts
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'must-not-exist'
            result = subprocess.run([sys.executable, live_api_contracts.__file__, '--config', 'missing.json',
                '--output', str(output), '--max-requests', '1', '--max-seconds', '5'],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--allow-live', result.stderr)
            self.assertFalse(output.exists())

    def test_recording_redacts_key_and_request_cap_is_hard(self):
        probe = {'kind': 'citation', 'backend': 'openalex', 'ids': {'doi': '10.1234/fixture'},
                 'expected_title': 'Synthetic fixture', 'expected_state': 'verified'}
        seen = []
        def handle(request):
            seen.append(request)
            return httpx.Response(200, json={'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.1234/fixture', 'title': 'Synthetic fixture'})
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'OPENALEX_API_KEY': 'secret-fixture'}):
            report = asyncio.run(run_probes({'probes': [probe, probe]}, folder, 1, 5,
                                            transport=httpx.MockTransport(handle)))
            self.assertEqual(len(seen), 1)
            self.assertEqual([p['status'] for p in report['probes']], ['passed', 'blocked'])
            self.assertFalse(report['passed'])
            self.assertNotIn('secret-fixture', (Path(folder) / 'report.json').read_text())
            self.assertEqual(len(list(Path(folder).glob('*.response'))), 1)
            self.assertEqual(json.loads((Path(folder) / 'report.json').read_text()), report)

    def test_throttling_pauses_service_and_preserves_failure_receipt(self):
        probe = {'kind': 'citation', 'backend': 'semantic_scholar', 'ids': {'arxiv': '1309.3923'},
                 'expected_title': 'Synthetic fixture', 'expected_state': 'unknown'}
        seen = []
        def handle(request):
            seen.append(request)
            return httpx.Response(429, headers={'retry-after': '30'})
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'S2_API_KEY': 'secret-fixture'}):
            report = asyncio.run(run_probes({'probes': [probe, probe]}, folder, 5, 5,
                                            transport=httpx.MockTransport(handle)))
        self.assertEqual(len(seen), 1)
        self.assertEqual([p['status'] for p in report['probes']], ['failed', 'blocked'])
        self.assertEqual(report['probes'][0]['identity']['reason'], 'rate_limited')
        self.assertEqual(report['requests'][0]['retry_after'], '30')

    def test_search_uses_native_provider_and_preserves_empty_result_contract(self):
        def handle(request):
            data = json.loads(request.content)
            entries = [] if data['q'] == 'empty' else [{'link': 'https://fixture.example/paper',
                'title': 'Fixture title', 'snippet': 'Discovery only', 'position': 1}]
            return httpx.Response(200, json={'organic': entries})
        probes = [{'kind': 'search', 'provider': 'serper', 'query': 'fixture', 'max_results': 1,
                   'expected_count': 1, 'expected_title': 'Fixture title'},
                  {'kind': 'search', 'provider': 'serper', 'query': 'empty', 'max_results': 1,
                   'expected_count': 0}]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'SERPER_API_KEY': 'fake-search-key'}):
            report = asyncio.run(run_probes({'probes': probes}, folder, 2, 5,
                                            transport=httpx.MockTransport(handle)))
        self.assertTrue(report['passed'], report)
        self.assertEqual([p['count'] for p in report['probes']], [1, 0])
        self.assertTrue(all(r['endpoint'] == 'https://google.serper.dev/search' for r in report['requests']))

    def test_search_throttling_stops_further_calls_to_the_backend(self):
        probe = {'kind': 'search', 'provider': 'serper', 'query': 'fixture', 'max_results': 1, 'expected_count': 1}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'SERPER_API_KEY': 'fake-search-key'}):
            report = asyncio.run(run_probes({'probes': [probe, probe]}, folder, 5, 5,
                transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={'retry-after': '60'}))))
        self.assertEqual(len(report['requests']), 1)
        self.assertEqual([r['status'] for r in report['probes']], ['failed', 'blocked'])
        self.assertEqual(report['requests'][0]['retry_after'], '60')

    @unittest.skipUnless(importlib.util.find_spec('tavily'), 'Optional native Tavily SDK')
    def test_native_sdk_rate_limit_error_is_recorded_and_stops_service(self):
        probe = {'kind': 'search', 'provider': 'tavily', 'query': 'fixture', 'max_results': 1, 'expected_count': 1}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TAVILY_API_KEY': 'fake-sdk-key'}):
            report = asyncio.run(run_probes({'probes': [probe, probe]}, folder, 5, 5,
                transport=httpx.MockTransport(lambda r: httpx.Response(429, json={'detail': {'error': 'Fixture limit'}},
                                                                       headers={'retry-after': '60'}))))
        self.assertEqual(len(report['requests']), 1)
        self.assertEqual([r['status'] for r in report['probes']], ['failed', 'blocked'])
        self.assertIn('error_type', report['probes'][0])
        self.assertNotIn('fake-sdk-key', json.dumps(report))


    def test_s2_public_probe_allows_no_key_but_still_enforces_budget(self):
        probe = {'kind': 'citation', 'backend': 'semantic_scholar', 'ids': {'arxiv': '2510.00199'},
                 'expected_title': 'Synthetic fixture', 'expected_state': 'verified'}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            validate_probes({'probes': [probe]})
            result = asyncio.run(run_probes({'probes': [probe, probe]}, folder, 1, 5,
                transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
                    'paperId': 'offline-fixture', 'title': 'Synthetic fixture', 'externalIds': {'ArXiv': '2510.00199'}}))))
        self.assertEqual(len(result['requests']), 1)
        self.assertEqual([p['status'] for p in result['probes']], ['passed', 'blocked'])
