"""Observable coverage, extraction, citation, and export boundaries; no live calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import searchos_adapter as adapter
from schema_generator import domain_config, digest
from coverage_policy import coverage_witness, validate_case_coverage_stop
from contextgem_extractor import ExtractionUnavailable, extract
from searchos_online import OnlineRunner, BudgetEnd
from citation_backends import CitationBackend, identifiers
import test_searchos_online as fixtures
from review_fixtures import reviewed_ref


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.config = domain_config()
        self.ref = reviewed_ref()

    def case(self, cid, definitions=True, admission=True, passed=False, score_count=0):
        case = {'case_id': cid, 'problem_definition': {
            f: reviewed_ref(case_id=cid) for f in self.config['fields']} if definitions else {}, 'tracks': {}}
        if admission:
            for track, rules in self.config['tracks'].items():
                evidence = {c: reviewed_ref(str(passed).lower(), cid) for c in rules['admission_criteria']}
                dims = list(rules['scoring_dimensions'])[:score_count]
                case['tracks'][track] = {'criteria': {c: passed for c in evidence}, 'criteria_evidence': evidence,
                    'passed_admission': int(passed), 'scores': {d: 3 for d in dims},
                    'score_evidence': {d: reviewed_ref('3', cid) for d in dims}}
        return case

    def test_cannot_join_different_cases(self):
        cases = [self.case('TEST-0001', admission=False), self.case('TEST-0002', definitions=False)]
        self.assertIsNone(coverage_witness(cases, self.config, {'s1'}))

    def test_false_admission_coverage_needs_no_scores_and_completes_scope(self):
        cases = [self.case('TEST-0001')]
        witness = coverage_witness(cases, self.config, {'s1'})
        self.assertFalse(witness['passed_admission'])
        data = {'cases': cases, 'sources': [{'source_id': 's1', 'status': 'opened'}], 'run_status': 'completed',
                'checkpoint': {'completed': True, 'stop_evidence': {'coverage_witness': witness}}}
        with self.assertRaisesRegex(ValueError, 'self audit'):
            validate_case_coverage_stop(data, self.config)
        from review_fixtures import add_witness_audits
        add_witness_audits(data, self.config)
        validate_case_coverage_stop(data, self.config)
        data['run_status'] = 'incomplete'
        with self.assertRaises(ValueError): validate_case_coverage_stop(data, self.config)

    def test_coverage_export_uses_snapshot_audit_policy_and_rejects_tampering(self):
        from copy import deepcopy
        from schema_generator import digest
        from review_fixtures import add_witness_audits
        config = deepcopy(self.config)
        config['scope']['audit']['min_audit_samples'] = 1
        cases = [self.case('TEST-0001')]
        witness = coverage_witness(cases, config, {'s1'})
        data = {'cases': cases, 'sources': [{'source_id': 's1', 'status': 'opened'}],
                'run_status': 'completed', 'config_snapshot': config, 'config_sha256': digest(config),
                'checkpoint': {'completed': True, 'stop_evidence': {'coverage_witness': witness}}}
        add_witness_audits(data, config)
        validate_case_coverage_stop(data)
        data['config_sha256'] = 'tampered'
        with self.assertRaisesRegex(ValueError, 'snapshot digest'):
            validate_case_coverage_stop(data)

    def test_passed_admission_requires_same_track_valid_dimensions(self):
        case = self.case('TEST-0001', passed=True, score_count=3)
        self.assertIsNone(coverage_witness([case], self.config, {'s1'}))
        case = self.case('TEST-0001', passed=True, score_count=4)
        self.assertEqual(coverage_witness([case], self.config, {'s1'})['track_id'], 'nonlocal-coordination')
        for item in case['tracks']['nonlocal-coordination']['score_evidence'].values():
            item['has_conflict'] = True
        self.assertIsNone(coverage_witness([case], self.config, {'s1'}))

    def test_missing_is_not_not_applicable_and_metadata_never_covers(self):
        case = self.case('TEST-0001')
        field = self.config['fields'][0]
        case['problem_definition'][field]['coverage_status'] = 'not_applicable'
        self.assertIsNone(coverage_witness([case], self.config, {'s1'}))
        case['problem_definition'][field]['applicability_reason'] = 'Supported explicit inapplicability'
        self.assertIsNotNone(coverage_witness([case], self.config, {'s1'}))
        self.assertIsNone(coverage_witness([case], self.config, set()))


class WorkflowTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor
    run_fixture = fixtures.OnlineTests.run_fixture

    def test_transient_source_failure_recovers_via_formal_resume(self):
        original = self.opener
        calls = []
        async def flaky(*args):
            calls.append(args[0])
            if len(calls) == 1:
                raise httpx.ConnectError('fixture')
            return await original(*args)
        self.opener = flaky
        first, _ = self.run_fixture()
        second, _ = self.run_fixture()
        self.assertEqual(first['coverage']['filled'], 0)
        self.assertEqual(second['coverage']['filled'], 1)
        self.assertEqual(len(calls), 2)
        meta = adapter.load(self.path)
        self.assertTrue(any(e['kind'] == 'source_retry' for e in meta['online']['events']))
        self.assertEqual(next(iter(meta['online']['sources'].values()))['attempts'], 2)

    def test_transient_source_retry_has_workspace_cap(self):
        calls = []
        async def unavailable(*args):
            calls.append(args[0])
            raise httpx.ConnectError('fixture')
        self.opener = unavailable
        for _ in range(3):
            self.run_fixture()
        self.assertEqual(len(calls), 2)

    def test_service_failure_falls_back_once_and_still_requires_judge(self):
        async def unavailable(*args):
            raise ExtractionUnavailable('synthetic service failure')
        self.extractor = unavailable
        result, models = self.run_fixture()
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(len(models['judge'].calls), 2)
        self.assertTrue(any(e['kind'] == 'extraction_fallback' for e in adapter.load(self.path)['online']['events']))

    def test_budget_error_does_not_fall_back(self):
        async def budget(*args):
            raise BudgetEnd('model_call_limit')
        self.extractor = budget
        result, models = self.run_fixture()
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(models['extraction'].calls, [])

    def test_invalid_field_names_do_not_poison_resume_cache(self):
        self.candidate['field'] = 'problem_definition/TEST-0001.parties_and_roles'
        first, _ = self.run_fixture()
        self.assertEqual(first['stop_reason'], 'error')
        self.assertFalse(adapter.load(self.path)['online'].get('extractions'))
        self.candidate['field'] = 'parties_and_roles'
        second, _ = self.run_fixture()
        self.assertEqual(second['coverage']['filled'], 1)

    def test_reference_mapping_error_does_not_fall_back(self):
        async def invalid(*args):
            raise ValueError('bad reference')
        self.extractor = invalid
        result, models = self.run_fixture()
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(models['extraction'].calls, [])

    def test_one_call_budget_resumes_at_judge(self):
        self.config['max_model_calls'] = 1
        first, _ = self.run_fixture()
        second, _ = self.run_fixture()
        third, models = self.run_fixture()
        self.assertEqual(first['coverage']['filled'], 0)
        self.assertEqual(second['coverage']['filled'], 0)
        self.assertEqual(third['coverage']['filled'], 1)
        self.assertEqual(models['extraction'].calls, [])
        self.assertEqual(len(models['judge'].calls), 1)

    def test_source_limit_produces_completed_export(self):
        self.config['analysis_limit'] = 1
        result, _ = self.run_fixture()
        self.assertEqual(result['status'], 'completed')
        batch = json.loads((self.path / 'calibration/batch.json').read_text())
        self.assertEqual(batch['stop_reason'], 'analysis_limit_reached')
        self.assertTrue(batch['checkpoint']['completed'])
        self.assertEqual(batch['counts']['opened_sources'], 1)
        self.assertIsNone(batch['counts']['discovery_limit'])
        self.assertIn('饱和度 N/A', (self.path / 'calibration/comparison.md').read_text())

    def test_citations_do_not_run_after_model_budget(self):
        self.config.update(max_model_calls=3, citation_backend='semantic_scholar')
        with patch('citation_backends.CitationBackend') as backend:
            result, _ = self.run_fixture()
        backend.assert_not_called()
        self.assertEqual(result['stop_evidence']['budget_cause'], 'model_call_limit')
        self.assertEqual(result['coverage']['filled'], 1)

    def test_one_citation_fetch_per_paper_even_on_failure(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                self.setUp()
                self.config['citation_backend'] = 'semantic_scholar'
                self.extraction['candidates'].append({**self.candidate, 'field': 'constraints'})
                original = fixtures.OnlineTests.opener.__get__(self)
                async def identified(*args):
                    source = await original(*args)
                    source['url'] = 'https://arxiv.org/pdf/2601.00002'
                    return source
                self.opener = identified
                with patch.object(CitationBackend, 'expand', side_effect=TimeoutError('fixture') if failed else None,
                                  return_value=[]) as expand:
                    self.run_fixture()
                self.assertEqual(expand.await_count, 1)
                records = list(adapter.load(self.path)['online']['citation_expansions'].values())
                self.assertEqual(len(records), 2)
                self.assertEqual(sum('reused_from' in x for x in records), 1)
                self.assertTrue(all(x['status'] == ('failed' if failed else 'succeeded') for x in records))

    def test_citation_cap_dedup_and_orphan_base(self):
        self.run_fixture()
        meta = adapter.load(self.path)
        state = adapter.project(meta)
        node = state.evidence_graph.nodes[0]
        hits = [{'url': f'https://arxiv.org/pdf/2601.0000{i}', 'identifiers': {'arxiv': f'2601.0000{i}'},
                 'relation': 'reference'} for i in range(8)]
        added = adapter.add_citation_results(self.path, node.id, hits)
        self.assertEqual(len(added), 5)
        self.assertEqual(adapter.add_citation_results(self.path, node.id, hits), [])
        meta = adapter.load(self.path)
        for f in (x for x in meta['config']['fields'] if x != self.candidate['field']):
            adapter.record_gap(self.path, {'table_id': 'problem_definition', 'case_id': 'TEST-0001',
                'field': f, 'status': 'hard_cell', 'reason': 'synthetic access block', 'attempts': ['fixture']})
        state = adapter.project(adapter.load(self.path))
        citations = [t for t in state.frontier.questions if t.created_by == 'citation-expansion']
        self.assertEqual(len(citations), 5)
        self.assertTrue(all(t.depth == 1 and t.priority == .3 for t in citations))
        meta = adapter.load(self.path)
        next(iter(meta['online']['sources'].values()))['citation_depth'] = 1
        adapter.persist(self.path, meta)
        with self.assertRaises(ValueError): adapter.add_citation_results(self.path, node.id, hits)

    def test_new_sources_not_new_verified_fields_controls_stall(self):
        self.config.update(max_rounds=2, stall_rounds=1)
        class EmptyAfterFirst(fixtures.Provider):
            async def search(inner, query, max_results):
                if inner.calls:
                    inner.calls.append((query, 0))
                    return []
                return await super().search(query, max_results)
        self.provider = EmptyAfterFirst()
        models = {'orchestrator': fixtures.Model({'query': 'different fixture'}),
                  'extraction': fixtures.Model({'candidates': [], 'missing': {}}), 'judge': fixtures.Model(self.judgment)}
        result = asyncio.run(OnlineRunner(self.path, self.config, models=models,
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor).run())
        self.assertEqual(result['stop_reason'], 'diminishing_returns')
        self.assertEqual(result['stop_evidence']['basis'], 'new_sources')

    def test_citation_discovery_is_not_new_again_in_later_query(self):
        from online_policy import queries
        self.run_fixture()
        meta = adapter.load(self.path)
        node = adapter.project(meta).evidence_graph.nodes[0]
        hit = {'url': 'https://arxiv.org/pdf/2601.00009', 'identifiers': {'arxiv': '2601.00009'}}
        adapter.add_citation_results(self.path, node.id, [hit])
        meta = adapter.load(self.path)
        meta['online']['searches']['second'] = {'provider': 'arxiv', 'query': 'later', 'status': 'succeeded',
            'results': [hit], 'at': adapter.now(), 'target_cells': []}
        self.assertEqual(queries(meta)[-1]['produced_new_sources'], 0)

    def test_repeated_quote_receipt_binds_selected_segment(self):
        original = self.opener
        async def duplicate(url, directory, run_id):
            source = await original(url, directory, run_id)
            source['text'] += '\n\n[paragraph:2]\nTwo parties decide.'
            source['segments'].append({'location': 'paragraph:2', 'text': 'Two parties decide.'})
            return source
        self.opener = duplicate
        self.candidate['location'] = 'paragraph:2'
        self.run_fixture()
        entry = next(iter(adapter.load(self.path)['grounding'].values()))
        receipt = entry['report']['validated_candidates'][0]['grounding']
        self.assertEqual(receipt['span'][0], entry['request']['source']['text'].rfind('Two parties decide.'))


class ContextGemTests(unittest.TestCase):
    def test_bad_reference_isolated_without_rewriting_quote(self):
        from contextgem_extractor import candidates_from
        sentence = SimpleNamespace(raw_text='Two\n parties decide.')
        def item(quote):
            return SimpleNamespace(value={'quote': quote, 'value_text': 'Two parties'},
                reference_sentences=[sentence], justification='Synthetic fixture')
        document = SimpleNamespace(concepts=[
            SimpleNamespace(name='good', extracted_items=[item('Two parties')]),
            SimpleNamespace(name='bad', extracted_items=[item('Other parties')])],
            get_sentence_index=lambda s: (0, 0))
        result = candidates_from(document, [{'location': 'page:1', 'text': sentence.raw_text}])
        self.assertEqual([c['field'] for c in result['candidates']], ['good'])
        self.assertEqual(result['candidates'][0]['quote'], 'Two parties')
        self.assertEqual([f['field'] for f in result['reference_failures']], ['bad'])
        self.assertIn('bad', result['missing'])

    def test_all_definition_fields_form_one_real_document(self):
        from contextgem_extractor import document_for
        fields = domain_config()['fields']
        document = document_for([{'location': 'page:1', 'text': 'Synthetic source.'}],
            {'target_cells': ['problem_definition/TEST-0001.' + f for f in fields]})
        self.assertEqual(len(document.concepts), 8)
        for concept in document.concepts:
            self.assertTrue(concept.description.startswith('Target field: ' + concept.name + '.'))

    def test_real_library_reference_mapping_and_budgeted_transport(self):
        from litellm import ModelResponse
        profile = SimpleNamespace(provider='openai_compatible', model='gpt-4o-mini', api_base='https://fixture.example/v1',
                                  api_key_env='UNUSED_FIXTURE_KEY', api_key_fallback='fixture', max_tokens=1000,
                                  temperature=0.0, thinking_style='enable_thinking', enable_thinking=False, extra={})
        class Runner:
            config = {'call_timeout': 10}
            def __init__(self): self.calls, self.events = 0, []
            def begin_model_call(self, *args): self.calls += 1; return 'fixture'
            def remaining(self): return 10
            def event(self, *args, **kwargs): self.events.append((args, kwargs))
        runner = Runner()
        content = [{'concept_id': 'C0', 'extracted_items': [{'value': {
            'value_text': 'Two parties', 'quote': 'Two parties decide.', 'evidence_level': 'primary',
            'confidence': 'medium', 'coverage_status': 'covered', 'applicability_reason': ''},
            'justification': 'Synthetic test source says two parties.',
            'reference_paragraphs': [{'reference_paragraph_id': 'P1', 'reference_sentence_ids': ['P1-S0']},
                                     {'reference_paragraph_id': 'P1', 'reference_sentence_ids': ['P1-S1']}]}]}]
        async def completion(**kwargs):
            self.assertEqual(json.dumps(kwargs['messages']).count('TEST-0001.parties_and_roles'), 1)
            self.assertEqual(kwargs['extra_body'], {'enable_thinking': False})
            self.assertEqual(kwargs['temperature'], 0.0)
            self.assertEqual(kwargs['num_retries'], 0)
            self.assertEqual(kwargs['max_retries'], 0)
            body_prompt = next(m['content'] for m in kwargs['messages'] if m['role'] == 'user')
            for phrase in ('timing protocols', 'vulnerable to asymmetric', 'Hong–Ou–Mandel (HOM)'):
                self.assertIn(phrase, body_prompt)
            for joined in ('timingprotocols', 'toasymmetric', 'Mandel(HOM)'):
                self.assertNotIn(joined, body_prompt)
            return ModelResponse(model='gpt-4o-mini', choices=[{'message': {'role': 'assistant', 'content': json.dumps(content)}}],
                usage={'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2})
        body = ('Two parties decide. Evidence exists. Classical two–way timing\nprotocols are '
                'vulnerable to\nasymmetric channel delays. Bidirectional Hong–Ou–Mandel\n(HOM) interferometry.')
        with patch('searchos.config.models.resolve_profile', return_value=profile), patch('litellm.acompletion', completion):
            result = asyncio.run(extract(runner, {'target_cells': ['problem_definition/TEST-0001.parties_and_roles']},
                [{'location': 'page:1', 'text': 'Two parties decide.'}, {'location': 'page:2', 'text': body}]))
        self.assertEqual(runner.calls, 1)
        self.assertEqual(result['candidates'][0]['location'], 'page:2')
        self.assertTrue(result['candidates'][0]['justification'])
        self.assertEqual([r['sentence_index'] for r in result['candidates'][0]['references']], [0, 1])
        self.assertTrue(any(args[0] == 'contextgem_reference_deduplication' for args, _ in runner.events))
        raw = next(data['content'] for args, data in runner.events if args[0] == 'model_response')
        self.assertEqual(len(json.loads(raw)[0]['extracted_items'][0]['reference_paragraphs']), 2)
        # Actual ContextGem bulk validator must never see the rejected high item.
        bad = deepcopy(content[0]); bad['concept_id'] = 'C1'
        bad['extracted_items'][0]['value']['confidence'] = 'high'
        content.append(bad)
        context = {'target_cells': ['problem_definition/TEST-0001.parties_and_roles',
                                   'problem_definition/TEST-0001.constraints']}
        segments = [{'location': 'page:1', 'text': 'Two parties decide.'},
                    {'location': 'page:2', 'text': body}]
        with patch('searchos.config.models.resolve_profile', return_value=profile), patch('litellm.acompletion', completion):
            result = asyncio.run(extract(runner, context, segments))
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(any(args[0] == 'contract_rejection' for args, _ in runner.events))
        content[0]['extracted_items'][0]['value']['confidence'] = 'high'
        from searchos_online import ContractViolation
        with patch('searchos.config.models.resolve_profile', return_value=profile), patch('litellm.acompletion', completion):
            with self.assertRaises(ContractViolation):
                asyncio.run(extract(runner, context, segments))
        self.assertEqual(runner.calls, 3)
        self.assertEqual(segments[1]['text'], body)



class ContextContractTests(unittest.TestCase):
    def test_missing_admission_is_empty_and_false_evidence_is_preserved(self):
        from contextgem_extractor import document_for, candidates_from, isolate_contract_items
        from pydantic import ValidationError
        segments = [{'location': 'page:1', 'text': 'Classical transfer can run in parallel.'}]
        doc = document_for(segments, {'target_cells': [
            'nonlocal-coordination_admission/TEST-0001.C2', 'nonlocal-coordination_admission/TEST-0001.C3']})
        value = {'value_text': 'false', 'quote': 'Classical transfer', 'evidence_level': 'primary',
                 'confidence': 'medium', 'coverage_status': 'covered', 'applicability_reason': ''}
        validator = doc.concepts[0]._get_structure_validator()
        self.assertEqual(validator.model_validate(value).value_text, 'false')
        for change in ({'value_text': 'insufficient_evidence'}, {'coverage_status': 'not_applicable'}):
            with self.assertRaises(ValidationError):
                validator.model_validate({**value, **change})
        empty = candidates_from(doc, segments)
        self.assertEqual(empty['candidates'], [])
        self.assertEqual(set(empty['missing']), {'C2', 'C3'})
        item = {'value': value, 'justification': 'Explicit classical transfer.',
                'reference_paragraphs': [{'reference_paragraph_id': 'P0', 'reference_sentence_ids': ['P0-S0']}]}
        bad = deepcopy(item); bad['value'].update(value_text='insufficient_evidence', coverage_status='not_applicable')
        raw = [{'concept_id': 'C0', 'extracted_items': [item]}, {'concept_id': 'C1', 'extracted_items': [bad]}]
        filtered, rejected, retained = isolate_contract_items(
            json.dumps(raw), ['C2', 'C3'], 'nonlocal-coordination_admission')
        self.assertEqual(retained, 1)
        self.assertEqual(json.loads(filtered)[0]['extracted_items'], [item])
        self.assertEqual(json.loads(filtered)[1]['extracted_items'], [])
        self.assertEqual(rejected[0]['candidate'], bad)

    def test_raw_contextgem_filter_preserves_items_and_envelope_failures(self):
        from contextgem_extractor import isolate_contract_items
        item = {'value': {'value_text': 'two parties', 'quote': 'Two parties', 'confidence': 'medium',
                         'evidence_level': 'primary'}, 'justification': 'fixture', 'reference_paragraphs': []}
        bad = deepcopy(item); bad['value']['confidence'] = 'high'
        long = deepcopy(item); long['value']['quote'] = 'x' * 51
        content = json.dumps([{'concept_id': 'C0', 'extracted_items': [item]},
                              {'concept_id': 'C1', 'extracted_items': [bad, long]}])
        filtered, rejected, kept = isolate_contract_items(content, ['a', 'b'])
        self.assertEqual(kept, 1)
        self.assertEqual(json.loads(filtered)[0]['extracted_items'], [item])
        self.assertEqual([r['candidate'] for r in rejected], [bad, long])
        self.assertEqual(isolate_contract_items('{bad', ['a']), ('{bad', [], 0))

class BackendTests(unittest.TestCase):
    def test_s2_uses_both_directions_and_returns_metadata_only(self):
        requests = []
        def handler(request):
            requests.append(request)
            key = 'citedPaper' if request.url.path.endswith('references') else 'citingPaper'
            return httpx.Response(200, json={'data': [{key: {'paperId': 'x', 'title': 'Fixture',
                'externalIds': {'ArXiv': '2601.00001'}, 'openAccessPdf': None}}]})
        result = asyncio.run(CitationBackend('semantic_scholar', httpx.MockTransport(handler)).expand({'arxiv': '2601.00002'}))
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(result), 2)
        self.assertTrue(all('text' not in h for h in result))
        self.assertEqual(identifiers('https://arxiv.org/pdf/2601.00001v2.pdf'), {'arxiv': '2601.00001'})

    def test_partial_references_survive_citations_rate_limit(self):
        def handler(request):
            if request.url.path.endswith('/citations'):
                return httpx.Response(429, headers={'retry-after': '60'})
            return httpx.Response(200, json={'data': [{'citedPaper': {'paperId': 'fixture',
                'externalIds': {'ArXiv': '2601.00001'}, 'title': 'Fixture'}}]})
        backend = CitationBackend('semantic_scholar', httpx.MockTransport(handler))
        hits = asyncio.run(backend.expand({'arxiv': '2601.00002'}))
        self.assertEqual(len(hits), 1)
        self.assertEqual([r['status_code'] for r in backend.requests], [200, 429])
        self.assertEqual(backend.requests[-1]['retry_after'], '60')

    def test_rate_limit_is_failure_not_empty_result(self):
        from citation_backends import CitationRequestError
        transport = httpx.MockTransport(lambda request: httpx.Response(429))
        backend = CitationBackend('semantic_scholar', transport)
        with self.assertRaisesRegex(CitationRequestError, 'rate_limited'):
            asyncio.run(backend.expand({'doi': '10.1000/fixture'}))
        self.assertEqual(len(backend.requests), 1)
        self.assertEqual(backend.requests[0]['status'], 'failed')
        self.assertEqual(backend.requests[0]['status_code'], 429)
