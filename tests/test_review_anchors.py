"""One semantic call selects saved anchors; no quote repair/fidelity calls."""
import asyncio
from copy import deepcopy
import json
import unittest

import httpx
import searchos_adapter as adapter
from schema_generator import digest
from searchos_online import OnlineRunner
import test_searchos_online as fixtures


class AnchorModel(fixtures.Model):
    async def ainvoke(self, messages, **kwargs):
        response = await super().ainvoke(messages)
        raw = json.loads(response.content)
        if 'judgments' not in raw:
            return response
        data = json.loads(messages[1][1])
        self.review_input = deepcopy(data)
        ids = [qid for choices in data['source_quote_options'].values() for qid in choices]
        for judgment in raw['judgments']:
            search = judgment['counter_evidence_search']
            for group in ('negation_evidence', 'conditional_limits_evidence',
                          'threat_model_boundary_evidence', 'contradictions_found'):
                for finding in search.get(group, []):
                    if finding.get('source_quote_id') == 'SELECT_FIRST':
                        finding['source_quote_id'] = ids[0]
        if getattr(self, 'alter', None):
            self.alter(raw, data)
        if getattr(self, 'after_response', None):
            self.after_response()
        response.content = json.dumps(raw)
        return response


class AnchorReviewTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor

    def output(self, qid='SELECT_FIRST', verdict='supported'):
        result = deepcopy(self.judgment)
        result['judgments'][0]['verdict'] = verdict
        result['judgments'][0]['counter_evidence_search'].update(
            conditional_limits_evidence=[{'source_quote_id': qid,
                'reason': 'Synthetic finding assessed in context; not real research.'}])
        return result

    def run_output(self, output, alter=None, after_response=None):
        judge = AnchorModel(output)
        judge.alter, judge.after_response = alter, after_response
        runner = OnlineRunner(self.path, self.config,
            models={'extraction': fixtures.Model(self.extraction), 'judge': judge},
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        result = asyncio.run(runner.run())
        return result, adapter.load(self.path), judge

    def assert_no_extra_call(self, result, meta):
        self.assertEqual(result['model_calls'], 3)  # extraction, attribution, semantics
        contracts = [e['output_contract'] for e in meta['online']['events']
                     if e['kind'] == 'model_call_started']
        self.assertEqual(contracts, ['Extraction', 'AttributionResult', 'AnchoredJudgments'])

    def test_saved_anchor_is_restored_and_audited_in_one_review(self):
        result, meta, judge = self.run_output(self.output())
        self.assert_no_extra_call(result, meta)
        self.assertEqual(result['coverage']['filled'], 1)
        review = meta['reviews'][0]
        self.assertTrue(review['counter_evidence_search']['conditional_limits_found'])
        self.assertFalse(review['counter_evidence_search']['negation_found'])
        finding = review['counter_evidence_search']['conditional_limits_evidence'][0]
        location, choices = next(iter(judge.review_input['source_quote_options'].items()))
        anchor = {'location': location, 'quote': next(iter(choices.values()))}
        self.assertNotIn('context_segments', judge.review_input['claim_ledger'])
        self.assertEqual(finding, {**anchor, 'reason': self.output()['judgments'][0]
                                  ['counter_evidence_search']['conditional_limits_evidence'][0]['reason']})
        started = next(e for e in meta['online']['events']
                       if e['kind'] == 'model_call_started' and e['call_id'] == review['model_call']['call_id'])
        self.assertEqual(started['output_contract'], 'AnchoredJudgments')
        self.assertEqual(review['model_call']['input_sha256'], digest(judge.review_input))

    def test_unknown_id_stops_without_repair_and_keeps_raw_discovery(self):
        result, meta, _ = self.run_output(self.output('invented-id'))
        self.assert_no_extra_call(result, meta)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        responses = [e['content'] for e in meta['online']['events'] if e['kind'] == 'model_response']
        self.assertIn('invented-id', responses[-1])
        self.assertTrue(json.loads(responses[-1])['judgments'][0]['counter_evidence_search']['conditional_limits_evidence'])

    def test_unlocatable_discovery_is_not_silently_dropped(self):
        result, meta, _ = self.run_output(self.output(None))
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'], [])
        self.assertIn('quote_unlocatable', str(meta['online']['events']))

    def test_literal_quote_and_location_overrides_are_rejected(self):
        def alter(raw, data):
            raw['judgments'][0]['counter_evidence_search']['conditional_limits_evidence'][0].update(
                quote='invented quote', location='page:999')
        result, meta, _ = self.run_output(self.output(), alter)
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'], [])

    def test_duplicate_anchor_in_same_group_is_rejected(self):
        output = self.output()
        group = output['judgments'][0]['counter_evidence_search']['conditional_limits_evidence']
        group.append(deepcopy(group[0]))
        result, meta, _ = self.run_output(output)
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'], [])

    def test_valid_anchor_does_not_override_semantic_rejection(self):
        result, meta, _ = self.run_output(self.output(verdict='semantic_mismatch'))
        self.assert_no_extra_call(result, meta)
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(meta['reviews'][0]['verdict'], 'semantic_mismatch')

    def test_changed_saved_catalog_stops_even_when_ids_are_valid(self):
        def tamper():
            meta = adapter.load(self.path)
            event = next(e for e in reversed(meta['online']['events'])
                         if e.get('output_contract') == 'AnchoredJudgments')
            choices = next(iter(event['input']['source_quote_options'].values()))
            choices[next(iter(choices))] = 'tampered'
            adapter.persist(self.path, meta)
        result, meta, _ = self.run_output(self.output(), after_response=tamper)
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'], [])
        self.assertIn('Saved model request is missing, duplicated or changed', str(meta['online']['events']))

    def test_missing_findings_cannot_satisfy_a_true_flag(self):
        output = self.output()
        output['judgments'][0]['counter_evidence_search'].update(
            conditional_limits_found=True, conditional_limits_evidence=[])
        result, meta, _ = self.run_output(output)
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'], [])

    def test_anchor_location_must_be_in_declared_search_scope(self):
        def alter(raw, data):
            raw['judgments'][0]['counter_evidence_search']['segments_searched'] = ['page:999']
        result, meta, _ = self.run_output(self.output(), alter)
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'], [])

    def test_known_location_cannot_replace_candidate_location(self):
        from searchos_online import AnchoredJudgments, ContractViolation, resolve_judgment_anchors
        output = self.output('q1')
        search = output['judgments'][0]['counter_evidence_search']
        search['segments_searched'] = ['page:2']
        saved = {'candidate': {'location': 'page:1'},
                 'context_segments': [{'location': 'page:1', 'text': 'Claim.'},
                                      {'location': 'page:2', 'text': 'Only in theory.'}],
                 'source_quote_options': {'page:2': {'q1': 'Only in theory.'}}}
        with self.assertRaisesRegex(ContractViolation, 'omitted the candidate'):
            resolve_judgment_anchors(AnchoredJudgments.model_validate(output), saved)

    def test_whitespace_is_restored_from_saved_source(self):
        original = self.opener
        async def opener(*args):
            source = await original(*args)
            source['segments'][0]['text'] = 'Two parties decide.\nOnly within 10 ns.'
            source['text'] = '[paragraph:1]\n' + source['segments'][0]['text']
            return source
        self.opener = opener
        result, meta, _ = self.run_output(self.output())
        self.assert_no_extra_call(result, meta)
        self.assertEqual(meta['reviews'][0]['counter_evidence_search']['conditional_limits_evidence'][0]['quote'],
                         'Two parties decide.\nOnly within 10 ns.')

    def test_schema_rejection_stops_without_json_mode_fallback(self):
        from langchain_openai import ChatOpenAI
        self.config['semantic_output_format'] = 'json_schema'
        oracle, requests = AnchorModel(self.output()), []
        async def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            if payload.get('response_format', {}).get('type') == 'json_schema':
                return httpx.Response(400, json={'error': {'message': 'unsupported schema'}})
            response = await oracle.ainvoke([(m['role'], m['content']) for m in payload['messages']])
            return httpx.Response(200, json={'id': 'offline', 'object': 'chat.completion',
                'created': 0, 'model': 'fixture', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': response.content}}]})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                model = ChatOpenAI(model='fixture', api_key='synthetic', base_url='https://fixture.invalid/v1',
                                   http_async_client=client, max_retries=0)
                return await OnlineRunner(self.path, self.config,
                    models={'extraction': fixtures.Model(self.extraction), 'judge': model},
                    providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor).run()
        result = asyncio.run(run())
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(len(requests), 2)
        self.assertEqual(adapter.load(self.path)['reviews'], [])

    def test_real_sdk_receives_anchor_schema_without_extra_requests(self):
        from langchain_openai import ChatOpenAI
        self.config['semantic_output_format'] = 'json_schema'
        oracle, requests = AnchorModel(self.output()), []
        async def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            response = await oracle.ainvoke([(m['role'], m['content']) for m in payload['messages']])
            return httpx.Response(200, json={'id': 'offline-anchor', 'object': 'chat.completion',
                'created': 0, 'model': 'fixture', 'choices': [{'index': 0, 'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': response.content}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                model = ChatOpenAI(model='fixture', api_key='synthetic', base_url='https://fixture.invalid/v1',
                                   http_async_client=client, max_retries=0)
                runner = OnlineRunner(self.path, self.config,
                    models={'extraction': fixtures.Model(self.extraction), 'judge': model},
                    providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
                return await runner.run()
        result = asyncio.run(run())
        self.assert_no_extra_call(result, adapter.load(self.path))
        self.assertEqual(len(requests), 2)  # attribution and semantic review
        response_format = requests[-1]['response_format']
        self.assertEqual(response_format['type'], 'json_schema')
        self.assertTrue(response_format['json_schema']['strict'])
        import jsonschema
        schema = response_format['json_schema']['schema']
        jsonschema.Draft202012Validator.check_schema(schema)
        self.assertNotIn('\"properties\"', requests[-1]['messages'][0]['content'])
        from searchos_online import AnchoredJudgments
        # Every finding list is explicit in strict mode; no implicit empty evidence.
        valid = json.loads(requests[-1]['messages'][1]['content'])
        qid = next(qid for choices in valid['source_quote_options'].values() for qid in choices)
        valid = AnchoredJudgments.model_validate(self.output(qid)).model_dump()
        jsonschema.validate(valid, schema)
        wrong_location = deepcopy(valid)
        wrong_location['judgments'][0]['counter_evidence_search']['segments_searched'] = ['],page:1']
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(wrong_location, schema)
        for mutation in ('unknown_id', 'wrong_candidate', 'blank_reason', 'missing_list'):
            bad = deepcopy(valid)
            item = bad['judgments'][0]
            search = item['counter_evidence_search']
            if mutation == 'unknown_id':
                search['conditional_limits_evidence'][0]['source_quote_id'] = 'other-request:Q1'
            elif mutation == 'wrong_candidate':
                item['candidate_index'] = 1
            elif mutation == 'blank_reason':
                search['conditional_limits_evidence'][0]['reason'] = '  '
            else:
                del search['negation_evidence']
            with self.subTest(mutation=mutation), self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(bad, schema)
        # An unlocatable discovery is expressible on the wire, but fails local commitment.
        unlocatable = deepcopy(valid)
        unlocatable['judgments'][0]['counter_evidence_search']['conditional_limits_evidence'][0]['source_quote_id'] = None
        jsonschema.validate(unlocatable, schema)
        self.assertIn('source_quote_options', requests[-1]['messages'][1]['content'])


if __name__ == '__main__':
    unittest.main()
