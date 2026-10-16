"""Explicit offline checks for effective policy, provenance, seeds, scores, and PDF order."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

import searchos_adapter as adapter
from coverage_policy import reviewed_cases
from export_batch import build
from render_calibration import render
from review_fixtures import reviewed_ref
from schema_generator import digest
from searchos_online import OnlineRunner, validation_details
from searchos_seeds import seed_actions
from validate_batch import validate_structure
from validate_grounding import grounding_gate
import searchos_network as network
import test_searchos_online as fixtures
from test_design_improvements import complete_meta
from test_network_boundaries import pdf_document


class ReviewFollowupTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor
    run_fixture = fixtures.OnlineTests.run_fixture

    def test_online_and_phase_limits_are_independent_and_counts_bound(self):
        result, models = self.run_fixture()
        batch = build(adapter.load(self.path))
        policy = batch['quality']['limit_policy']
        self.assertFalse(policy['phase_applied'])
        self.assertEqual(policy['phase_reference']['diminishing_returns_threshold'], 5)
        self.assertEqual(policy['effective']['stall_rounds'], 3)
        self.assertEqual(batch['counts']['diminishing_returns_threshold'], 3)
        self.assertEqual(batch['counts']['analysis_limit'], 20)
        self.assertEqual(policy['phase_reference']['analysis_limit'], 100)
        self.assertIn('stall_rounds=3', render(batch))
        batch['counts']['diminishing_returns_threshold'] = 5
        with self.assertRaisesRegex(ValueError, 'limit policy'):
            validate_structure(batch)

    def test_disabled_identity_retains_local_conflict_without_blocking_evidence(self):
        from searchos.tools.simple_browser.search.base import SearchResult
        class Hit(SearchResult):
            identifiers: dict[str, str]
        class Provider:
            async def search(self, *args):
                return [Hit(url='https://arxiv.org/pdf/2510.00199v1', title='Offline fixture',
                            identifiers={'arxiv': '1309.3923'})]
        self.config.update(citation_identity={'enabled': []}, citation_expansion_backend='none')
        models = {'extraction': fixtures.Model(self.extraction), 'judge': fixtures.Model(self.judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': Provider()}, opener=self.opener, extractor=self.extractor).run())
        meta = adapter.load(self.path)
        self.assertEqual(result['coverage']['filled'], 1)
        source = next(iter(meta['online']['sources'].values()))['source']
        self.assertEqual(source['citation_identity']['state'], 'unknown')
        self.assertEqual(source['citation_identity']['reason'], 'backend_disabled')
        self.assertEqual(source['metadata_identifier_conflict']['metadata_identifiers']['arxiv'], '1309.3923')
        self.assertFalse(meta['online'].get('citation_requests'))
        batch = build(meta)
        self.assertTrue(any(w.get('type') == 'source_metadata_identifier_conflict' for w in batch['quality']['warnings']))
        self.assertFalse(any(w['category'] == 'citation_unverified' for w in batch['quality']['warnings']))

    def test_rejected_review_still_discloses_same_model(self):
        bad = deepcopy(self.judgment)
        bad['judgments'][0]['verdict'] = 'semantic_mismatch'
        with patch.object(fixtures.Model, 'model_name', 'offline-common-model', create=True):
            result, models = self.run_fixture(judge=bad)
        batch = build(adapter.load(self.path))
        quality = batch['quality']['attribution']
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(quality['eligible_supported'], 0)
        self.assertTrue(quality['same_model_used'])
        self.assertEqual(quality['model_pairs_recorded'], 1)
        self.assertIn('offline-common-model', render(batch))
        self.assertIsNone(quality['attribution_precision'])

    def test_layer1_seeds_distinguish_body_open_from_web_query(self):
        actions = seed_actions()
        self.assertEqual([a['kind'] for a in actions], ['open-source', 'open-source', 'search'])
        self.assertTrue(all(a['url'].startswith('https://arxiv.org/pdf/') for a in actions[:2]))
        self.assertIn('Dawei Ding', actions[-1]['query'])
        for seed in ({'id': 'x', 'source': 'arXiv:2510.00199'},
                     {'id': 'x', 'query': 'author: Dawei Ding'},
                     {'id': 'x', 'query': 'arXiv:2510.00199'}):
            with self.subTest(seed=seed):
                path = self.path.parent / 'seeds.yaml'
                path.write_text(yaml.safe_dump({'configured_seed_queries': {'layer1_sources': [seed]}}))
                with self.assertRaises(ValueError):
                    seed_actions(path)

    def test_both_tracks_raw_maximum_normalizes_to_25(self):
        meta = complete_meta()
        keep = {rid for rid, e in meta['grounding'].items() if e['request']['table_id'] == 'problem_definition'}
        meta['grounding'] = {rid: e for rid, e in meta['grounding'].items() if rid in keep}
        for collection in ('attributions', 'reviews'):
            meta[collection] = [r for r in meta[collection] if r['report_id'] in keep]
        source = next(iter(meta['grounding'].values()))['request']['source']
        for track, rules in meta['config']['tracks'].items():
            for kind, fields, value in [('admission', rules['admission_criteria'], 'true'),
                                        ('scoring', rules['scoring_dimensions'], '5')]:
                for field in fields:
                    ref = reviewed_ref(value, source_id=source['source_id'])
                    ref['field'] = field
                    evidence = {k: v for k, v in ref.items() if k not in
                                {'grounding', 'attribution_review', 'semantic_review'}}
                    request = {'run_id': source['run_id'], 'extractor_id': 'offline-fixture',
                               'table_id': track + '_' + kind, 'source': source, 'evidence': [evidence]}
                    rid = digest(request)
                    report = grounding_gate().validate(request)
                    self.assertEqual(len(report['validated_candidates']), 1)
                    meta['grounding'][rid] = {'request': request, 'report': report}
                    for collection, key in [('attributions', 'attribution_review'), ('reviews', 'semantic_review')]:
                        meta[collection].append({**ref[key], 'report_id': rid,
                            'source_sha256': report['validated_candidates'][0]['grounding']['source_sha256'],
                            'reason': 'Synthetic score path, not scientific evidence'})
        case = reviewed_cases(meta, adapter.project(meta))[0]
        for track, total, count in [('nonlocal-coordination', 25, 5), ('quantum-security', 30, 6)]:
            evaluation = case['tracks'][track]
            self.assertEqual(evaluation['passed_admission'], 1)
            self.assertEqual(evaluation['score_total'], total)
            self.assertEqual(evaluation['score_normalized'], 25)
            self.assertEqual(evaluation['valid_dimension_count'], count)
            self.assertIsNone(evaluation['failure_class'])

    def test_two_column_pdf_uses_reading_order_with_exact_raw_span(self):
        commands = '\n'.join(f'BT /F1 12 Tf {x} {y} Td ({line}) Tj ET' for x, column in
            [(40, ['Alice and Bob each', 'possess local clocks.', 'They compare timing.']),
             (330, ['Unrelated detector statistics.', 'Visibility and efficiency.', 'An independent discussion.'])]
            for y, line in zip([700, 686, 672], column))
        body = pdf_document([commands])
        sync = network.source_segments(body, 'application/pdf')
        asynchronous = asyncio.run(network.parse_source(body, 'application/pdf'))
        self.assertEqual(sync, asynchronous)
        text = sync[0]['text']
        self.assertIn('Alice and Bob each possess local clocks. They compare timing.', ' '.join(text.split()))
        source = {'source_id': 'offline-pdf', 'run_id': 'fixture', 'status': 'opened',
                  'document_version': 'pdf-v1', 'text': text, 'segments': sync}
        report = grounding_gate().validate({'run_id': 'fixture', 'source': source, 'evidence': [{
            'source_id': 'offline-pdf', 'case_id': 'TEST-0001', 'field': 'parties_and_roles',
            'quote': 'Alice and Bob each possess local clocks.', 'location': 'page:1'}]})
        self.assertFalse(report['grounding_failures'])
        receipt = report['validated_candidates'][0]['grounding']
        self.assertEqual(receipt['matched_text'], text[slice(*receipt['span'])])
        self.assertEqual(report['facts'], [])


if __name__ == '__main__':
    unittest.main()
