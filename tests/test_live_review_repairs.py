"""Reproduce live counter-quote failures without external calls or weaker gates."""
import asyncio
from copy import deepcopy
import json
import unittest

import httpx
from pydantic import ValidationError
import searchos_adapter as adapter
from export_batch import build
from searchos_online import OnlineRunner, CounterQuoteSpanSelections, ContractViolation
from searchos_online import counter_quote_options, selected_counter_quotes
import test_searchos_online as fixtures


class SelectingModel(fixtures.Model):
    """Choose a fixture-requested literal quote from the actual presented options."""
    _llm_type = 'openai-chat'

    async def ainvoke(self, messages, **kwargs):
        response = await super().ainvoke(messages)
        raw = json.loads(response.content)
        if isinstance(raw, dict) and 'raw_content' in raw:
            response.content = raw['raw_content']
            return response
        if isinstance(raw, dict) and 'choose_quotes' in raw:
            data = json.loads(messages[1][1])
            selections = []
            for wanted in raw['choose_quotes']:
                key = ('judgment_index', 'group', 'finding_index')
                row = next(row for row in data['source_quote_options']
                           if all(row[k] == wanted[k] for k in key))
                option = next(option for option in row['options'] if option['quote'] == wanted['quote'])
                selections.append({**{k: wanted[k] for k in key}, 'option_id': option['option_id']})
            response.content = json.dumps(selections if raw.get('bare_array') else {'selections': selections})
        if isinstance(raw, dict) and 'findings' in raw:
            data = json.loads(messages[1][1])
            if 'replacements' in data:
                findings = []
                for f in raw['findings']:
                    if 'quote_id' in f:
                        findings.append(f)
                        continue
                    matches = [r for r in data['replacements'] if all(r[k] == f[k]
                        for k in ('judgment_index', 'group', 'finding_index'))
                        and r['quote'] == f['selected_quote']]
                    findings.append({'quote_id': matches[0]['quote_id'] if matches else 'unknown-id',
                                     'support': f['support'], 'reason': f['reason']})
                response.content = json.dumps({'findings': findings})
                if getattr(self, 'on_fidelity', None):
                    self.on_fidelity()
        return response


class LiveReviewRepairTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor

    def output(self, quote):
        result = deepcopy(self.judgment)
        result['judgments'][0]['counter_evidence_search'].update(
            conditional_limits_found=True, negation_evidence=[], threat_model_boundary_evidence=[],
            conditional_limits_evidence=[{'location': 'paragraph:1', 'quote': quote}])
        return result

    def run_outputs(self, outputs):
        judge = SelectingModel(outputs)
        judge.on_fidelity = getattr(self, 'on_fidelity', None)
        runner = OnlineRunner(self.path, self.config,
            models={'extraction': fixtures.Model(self.extraction), 'judge': judge},
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        return asyncio.run(runner.run()), adapter.load(self.path), judge

    def choice(self, quote='Two parties decide.', finding_index=0):
        return {'choose_quotes': [{'judgment_index': 0, 'group': 'conditional_limits_evidence',
                                  'finding_index': finding_index, 'quote': quote}]}

    def fidelity(self, finding_index=0, support='supported', quote='Two parties decide.'):
        return {'findings': [{'judgment_index': 0, 'group': 'conditional_limits_evidence',
                             'finding_index': finding_index, 'selected_quote': quote, 'support': support,
                             'reason': 'Synthetic independent check of the same original finding.'}]}

    def test_one_shared_repair_corrects_nonverbatim_counter_quote(self):
        bad = self.output('Two...decide.')
        result, meta, judge = self.run_outputs([bad, self.choice(), self.fidelity()])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(meta['reviews'][0]['counter_evidence_search']['conditional_limits_evidence'][0]['quote'],
                         'Two parties decide.')
        failures = [e for e in meta['online']['events'] if e.get('failure_type') == 'invalid_model_output']
        self.assertEqual(len(failures), 1)
        self.assertIn('counter_evidence_quote_not_found', str(failures[0]))
        self.assertIn('Two...decide.', str(judge.calls[-2]))
        self.assertEqual(meta['reviews'][0]['counter_evidence_search']['summary'],
                         bad['judgments'][0]['counter_evidence_search']['summary'])

    def test_live_reciprocity_paraphrase_and_other_findings_survive(self):
        original_opener = self.opener
        async def opener(*args):
            source = await original_opener(*args)
            source['segments'][0]['text'] += ' The derivation relies on channel reciprocity.'
            source['text'] = '[paragraph:1]\n' + source['segments'][0]['text']
            return source
        self.opener = opener
        bad = self.output('assumes channel reciprocity')
        search = bad['judgments'][0]['counter_evidence_search']
        search['conditional_limits_evidence'].insert(0, {'location': 'paragraph:1', 'quote': 'Two parties'})
        choice = self.choice('relies on channel reciprocity.', 1)
        choice['bare_array'] = True
        result, meta, judge = self.run_outputs([bad, choice, self.fidelity(1, quote='relies on channel reciprocity.')])
        self.assertEqual(result['model_calls'], 5)
        repaired = deepcopy(search)
        repaired['conditional_limits_evidence'][1]['quote'] = 'relies on channel reciprocity.'
        self.assertEqual(meta['reviews'][0]['counter_evidence_search'], repaired)

    def test_semantic_drift_stops_without_another_correction(self):
        result, meta, judge = self.run_outputs([
            self.output('Two...decide.'), self.choice(), self.fidelity(support='not_supported')])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        event = next(e for e in meta['online']['events'] if e['kind'] == 'counter_quote_fidelity')
        self.assertEqual(event['findings'][0]['support'], 'not_supported')

    def mock_transport_run(self, fidelity_response):
        """Exercise the real SDK request payload without any external service."""
        from langchain_openai import ChatOpenAI
        oracle = SelectingModel([self.output('Two...decide.'), self.choice(), fidelity_response])
        requests = []

        async def handler(request):
            payload = json.loads(request.content)
            requests.append(payload)
            response = await oracle.ainvoke([(m['role'], m['content']) for m in payload['messages']])
            return httpx.Response(200, json={
                'id': 'offline-fidelity', 'object': 'chat.completion', 'created': 0, 'model': 'fixture',
                'choices': [{'index': 0, 'finish_reason': 'stop',
                             'message': {'role': 'assistant', 'content': response.content}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                model = ChatOpenAI(model='fixture', api_key='offline-placeholder',
                    base_url='https://offline.invalid/v1', http_async_client=client, max_retries=0)
                runner = OnlineRunner(self.path, self.config,
                    models={'extraction': fixtures.Model(self.extraction), 'judge': model},
                    providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
                return await runner.run()

        return asyncio.run(run()), adapter.load(self.path), requests

    def test_native_json_mode_reaches_sdk_transport_and_is_audited(self):
        result, meta, requests = self.mock_transport_run(self.fidelity())
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(len(requests), 4)  # Attribution, judgment, selection, fidelity.
        self.assertTrue(all('response_format' not in r for r in requests[:-1]))
        self.assertEqual(requests[-1]['response_format'], {'type': 'json_object'})
        event = next(e for e in meta['online']['events']
                     if e.get('output_contract') == 'CounterQuoteFidelity')
        self.assertEqual(event['parameters']['response_format'], {'type': 'json_object'})
        self.assertEqual(event['parameters']['max_retries'], 0)

    def test_provider_ignoring_json_mode_still_fails_closed_without_retry(self):
        raw = 'Explanation before JSON.\n' + json.dumps(self.fidelity())
        result, meta, requests = self.mock_transport_run({'raw_content': raw})
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(len(requests), 4)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        self.assertFalse(any(e['kind'] == 'counter_quote_repair' for e in meta['online']['events']))
        self.assertTrue(any(e.get('content') == raw for e in meta['online']['events']))

    def test_fidelity_cannot_exceed_budget(self):
        self.config['max_model_calls'] = 4
        result, meta, judge = self.run_outputs([self.output('Two...decide.'), self.choice(), self.fidelity()])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(meta['reviews'], [])

    def test_fidelity_cannot_rebind_the_checked_finding(self):
        result, meta, judge = self.run_outputs([self.output('Two...decide.'), self.choice(), self.fidelity(9)])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_fidelity_of_rejected_quote_is_not_a_review_of_selected_quote(self):
        rejected = 'Two...decide.'
        result, meta, judge = self.run_outputs([
            self.output(rejected), self.choice(), self.fidelity(quote=rejected)])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        self.assertFalse(any(e['kind'] == 'counter_quote_repair' for e in meta['online']['events']))

    def test_fidelity_id_restores_selected_source_whitespace(self):
        original_opener = self.opener
        async def opener(*args):
            source = await original_opener(*args)
            source['segments'][0]['text'] = source['segments'][0]['text'].replace(
                'Two parties', 'Two\nparties')
            source['text'] = '[paragraph:1]\n' + source['segments'][0]['text']
            return source
        self.opener = opener
        result, meta, judge = self.run_outputs([
            self.output('Two...decide.'), self.choice('Two\nparties decide.'),
            self.fidelity(quote='Two\nparties decide.')])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(meta['reviews'][0]['counter_evidence_search']['conditional_limits_evidence'][0]['quote'],
                         'Two\nparties decide.')
        raw = [e for e in meta['online']['events'] if e['kind'] == 'model_response'][-1]
        self.assertEqual(set(json.loads(raw['content'])['findings'][0]), {'quote_id', 'support', 'reason'})

    def test_duplicate_or_missing_fidelity_ids_reject_entire_judgment(self):
        bad, good, repairs = self.boundary_outputs()
        self.boundary_fidelity['findings'][1] = deepcopy(self.boundary_fidelity['findings'][0])
        result, meta, judge = self.run_outputs([bad, repairs, self.boundary_fidelity])
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_missing_fidelity_finding_rejects_entire_judgment(self):
        bad, good, repairs = self.boundary_outputs()
        self.boundary_fidelity['findings'].pop()
        result, meta, judge = self.run_outputs([bad, repairs, self.boundary_fidelity])
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_changed_saved_fidelity_input_is_rejected(self):
        def tamper():
            meta = adapter.load(self.path)
            event = next(e for e in meta['online']['events']
                         if e.get('output_contract') == 'CounterQuoteFidelity')
            event['input']['replacements'][0]['quote'] = 'changed evidence'
            adapter.persist(self.path, meta)
        self.on_fidelity = tamper
        result, meta, judge = self.run_outputs([self.output('Two...decide.'), self.choice(), self.fidelity()])
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        self.assertFalse(any(e['kind'] == 'counter_quote_repair' for e in meta['online']['events']))

    def test_selection_rejects_generated_text_without_another_attempt(self):
        repairs = {'replacements': [{'judgment_index': 0, 'group': 'conditional_limits_evidence',
                                    'finding_index': 0, 'quote': 'Two parties make a decision.'}]}
        result, meta, judge = self.run_outputs([self.output('Two...decide.'), repairs])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_options_preserve_raw_whitespace_and_reject_wrong_binding_or_id(self):
        segments = [{'location': 'page:2', 'text': 'Two\nparties\tdecide.'}]
        targets = [{'judgment_index': 0, 'group': 'conditional_limits_evidence', 'finding_index': 1,
                    'location': 'page:2', 'quote': 'Two...decide.', 'reason': 'counter_evidence_quote_not_found'}]
        options = counter_quote_options(targets, segments)[0]['options']
        option = next(o for o in options if o['quote'] == segments[0]['text'])
        selection = {'judgment_index': 0, 'group': 'conditional_limits_evidence',
                     'finding_index': 1, 'option_id': option['option_id']}
        def choose(items):
            return selected_counter_quotes(CounterQuoteSpanSelections(selections=items), targets, counter_quote_options(targets, segments))
        self.assertEqual(choose([selection])[0]['quote'], 'Two\nparties\tdecide.')
        for change in ({'finding_index': 0}, {'option_id': len(options)}):
            with self.subTest(change=change), self.assertRaises(ContractViolation):
                choose([{**selection, **change}])
        with self.assertRaises(ContractViolation):
            choose([selection, selection])

    def test_live_55_and_61_character_ranges_are_never_offered_as_options(self):
        for text in ['adversarial tampering\ncould introduce asymmetric delays',
                     'security against intercept-resend\nand photon-number splitting']:
            target = {'judgment_index': 0, 'group': 'threat_model_boundary_evidence', 'finding_index': 0,
                      'location': 'page:4', 'quote': text, 'reason': 'quote_too_long'}
            options = counter_quote_options([target], [{'location': 'page:4', 'text': text}])[0]['options']
            self.assertTrue(options)
            self.assertNotIn(text, [o['quote'] for o in options])
            self.assertTrue(all(1 <= len(o['quote']) <= 50 and o['quote'] in text for o in options))
            # Free indices cannot recreate the rejected full range.
            with self.assertRaises(ValidationError):
                CounterQuoteSpanSelections(selections=[{'judgment_index': 0,
                    'group': 'threat_model_boundary_evidence', 'finding_index': 0,
                    'start_token': 0, 'end_token': 6}])

    def test_overlong_options_stay_within_original_grounded_span(self):
        quote = 'adversarial tampering could introduce asymmetric delays'
        target = {'judgment_index': 0, 'group': 'threat_model_boundary_evidence', 'finding_index': 0,
                  'location': 'page:4', 'quote': quote, 'reason': 'quote_too_long'}
        text = 'Unrelated security statement. ' + quote + '. Other claims.'
        options = counter_quote_options([target], [{'location': 'page:4', 'text': text}])[0]['options']
        self.assertTrue(all(o['quote'] in quote for o in options))
        self.assertTrue(any('could introduce asymmetric delays' in o['quote'] for o in options))

    def test_repair_catalog_excludes_empty_words_and_preserves_grounded_negation(self):
        # Observed run25 failures: isolated "it" and a shortened quote dropping "no".
        original = 'no further assumptions are made about the internal workings'
        target = {'judgment_index': 0, 'group': 'threat_model_boundary_evidence',
                  'finding_index': 0, 'location': 'page:1', 'quote': original,
                  'reason': 'quote_too_long'}
        options = counter_quote_options([target], [{'location': 'page:1', 'text': original}])[0]['options']
        quotes = [o['quote'] for o in options]
        self.assertNotIn('assumptions are made about the internal workings', quotes)
        self.assertTrue(any('no further assumptions are made' in q for q in quotes))
        self.assertTrue(all('no' in q.split() for q in quotes))
        target.update(quote='it not the case... aborts', reason='counter_evidence_quote_not_found')
        text = 'If this is not the case, it aborts.'
        quotes = [o['quote'] for o in counter_quote_options([target],
                  [{'location': 'page:1', 'text': text}])[0]['options']]
        self.assertNotIn('it', quotes)
        self.assertNotIn('If this', quotes)
        self.assertIn('it aborts.', quotes)
        # Do not require an invented negation from rejected nonverbatim wording.
        self.assertIn(text, quotes)

    def test_source_percentages_cannot_lose_unit_or_comparison(self):
        target = {'judgment_index': 0, 'group': 'conditional_limits_evidence',
                  'finding_index': 0, 'location': 'page:4',
                  'quote': 'detection efficiency... is ≈ 2 %',
                  'reason': 'counter_evidence_quote_not_found'}
        for quantity in ['≈ 2 %', '≤ 2.5 %', '2\n%', '2％', '2‰']:
            text = 'efficiency is ' + quantity + ', necessitating many attempts'
            quotes = [o['quote'] for o in counter_quote_options([target],
                      [{'location': 'page:4', 'text': text}])[0]['options']]
            with self.subTest(quantity=quantity):
                self.assertNotIn('≈ 2', quotes)
                self.assertNotIn('efficiency is ≈ 2', quotes)
                self.assertNotIn('efficiency is ≤ 2.5', quotes)
                self.assertNotIn('efficiency is 2', quotes)
                self.assertNotIn(quantity, quotes)  # Bare quantity is not a finding.
                self.assertIn(quantity + ', necessitating many attempts', quotes)
                self.assertTrue(all(q in text and len(q) <= 50 for q in quotes))
        # Numbers remain selectable when they carry substantive source wording.
        text = 'from 1.5 million Bell pairs'
        quotes = [o['quote'] for o in counter_quote_options([target],
                  [{'location': 'page:4', 'text': text}])[0]['options']]
        self.assertIn(text, quotes)
        self.assertNotIn('1.5', quotes)

    def test_grounded_long_finding_keeps_context_instead_of_isolated_noun(self):
        original = ('necessitating a platform capable of distributing and measuring '
                    'high-quality entangled states while closing the detection loophole.')
        target = {'judgment_index': 0, 'group': 'conditional_limits_evidence',
                  'finding_index': 0, 'location': 'page:1', 'quote': original,
                  'reason': 'quote_too_long'}
        quotes = [o['quote'] for o in counter_quote_options([target],
                  [{'location': 'page:1', 'text': 'Unrelated. ' + original + ' Other claims.'}])[0]['options']]
        self.assertNotIn('loophole.', quotes)
        self.assertIn('states while closing the detection loophole.', quotes)
        self.assertTrue(all(q in original and len(q) <= 50 for q in quotes))

    def test_deduplicated_grounded_quote_still_requires_fidelity(self):
        original = ('necessitating a platform capable of distributing and measuring '
                    'high-quality entangled states while closing the detection loophole.')
        selected = 'states while closing the detection loophole.'
        original_opener = self.opener
        async def opener(*args):
            source = await original_opener(*args)
            source['segments'][0]['text'] += ' ' + original
            source['text'] = '[paragraph:1]\n' + source['segments'][0]['text']
            return source
        self.opener = opener
        result, meta, _ = self.run_outputs([
            self.output(original), self.choice(selected),
            self.fidelity(support='unclear', quote=selected)])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        findings = next(e['findings'] for e in meta['online']['events']
                        if e['kind'] == 'counter_quote_fidelity')
        request = next(e['input'] for e in meta['online']['events']
                       if e.get('output_contract') == 'CounterQuoteFidelity')
        self.assertEqual(next(r['quote'] for r in request['replacements']
                              if r['quote_id'] == findings[0]['quote_id']), selected)
        self.assertEqual(findings[0]['support'], 'unclear')

    def test_unselectable_long_token_is_not_clipped(self):
        target = {'judgment_index': 0, 'group': 'conditional_limits_evidence', 'finding_index': 0,
                  'location': 'page:1', 'quote': 'x' * 51, 'reason': 'quote_too_long'}
        segments = [{'location': 'page:1', 'text': 'x' * 51}]
        self.assertEqual(counter_quote_options([target], segments)[0]['options'], [])
        with self.assertRaises(ContractViolation):
            selected_counter_quotes(CounterQuoteSpanSelections(selections=[{'judgment_index': 0,
                'group': 'conditional_limits_evidence', 'finding_index': 0, 'option_id': 0}]), [target], counter_quote_options([target], segments))

    def test_length_and_grounding_share_one_repair_allowance(self):
        result, meta, judge = self.run_outputs([self.output('x' * 51), self.output('Two...decide.')])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])
        self.assertEqual(len([e for e in meta['online']['events'] if e.get('failure_type') == 'invalid_model_output']), 2)

    def boundary_outputs(self):
        quotes = ['Section IV analyzes security against intercept-resend',
                  'adversarial tampering could introduce asymmetric delays']
        original_opener = self.opener
        async def opener(*args):
            source = await original_opener(*args)
            source['segments'][0]['text'] += ' ' + '. '.join(quotes) + '.'
            source['text'] = '[paragraph:1]\n' + source['segments'][0]['text']
            return source
        self.opener = opener
        bad = deepcopy(self.judgment)
        search = bad['judgments'][0]['counter_evidence_search']
        search.update(negation_evidence=[], conditional_limits_evidence=[],
                      threat_model_boundary_found=True, threat_model_boundary_evidence=[
            {'location': 'paragraph:1', 'quote': quote} for quote in quotes])
        good = deepcopy(bad)
        excerpts = ['IV analyzes security against intercept-resend',
                    'tampering could introduce asymmetric delays']
        for finding, quote in zip(good['judgments'][0]['counter_evidence_search'][
                'threat_model_boundary_evidence'], excerpts):
            finding['quote'] = quote
        repairs = {'choose_quotes': [{'judgment_index': 0, 'group': 'threat_model_boundary_evidence',
                    'finding_index': i, 'quote': quote} for i, quote in enumerate(excerpts)]}
        self.boundary_fidelity = {'findings': [{'judgment_index': 0, 'group': 'threat_model_boundary_evidence',
            'finding_index': i, 'selected_quote': quote, 'support': 'supported',
            'reason': 'Synthetic same-finding check.'} for i, quote in enumerate(excerpts)]}
        return bad, good, repairs

    def test_both_live_overlong_findings_are_reselected_in_one_repair(self):
        bad, good, repairs = self.boundary_outputs()
        result, meta, judge = self.run_outputs([bad, repairs, self.boundary_fidelity])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['coverage']['filled'], 1)
        repair_input = json.loads(judge.calls[-2][1][1])
        self.assertEqual([t['actual_length'] for t in repair_input['targets']], [53, 55])
        self.assertEqual(meta['reviews'][0]['counter_evidence_search'],
                         good['judgments'][0]['counter_evidence_search'])
        calls = [e for e in meta['online']['events'] if e['kind'] == 'model_call_started']
        self.assertEqual(calls[-1]['cost_category'], 'semantic')

    def test_missing_target_stops_without_another_call(self):
        bad, good, unused = self.boundary_outputs()
        selections = [{'judgment_index': 0, 'group': 'threat_model_boundary_evidence',
                       'finding_index': 0, 'option_id': 0}]
        result, meta, judge = self.run_outputs([bad, {'selections': selections}])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_unlisted_option_stops_without_another_call(self):
        bad, good, unused = self.boundary_outputs()
        selections = [{'judgment_index': 0, 'group': 'threat_model_boundary_evidence',
                       'finding_index': i, 'option_id': 999999} for i in range(2)]
        result, meta, judge = self.run_outputs([bad, {'selections': selections}])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_selection_list_is_wrapped_without_editing_values_or_extra_calls(self):
        bad, good, repairs = self.boundary_outputs()
        repairs['bare_array'] = True
        result, meta, judge = self.run_outputs([bad, repairs, self.boundary_fidelity])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(meta['reviews'][0]['counter_evidence_search'], good['judgments'][0]['counter_evidence_search'])
        event = next(e for e in meta['online']['events'] if e['kind'] == 'counter_quote_envelope_normalized')
        raw = next(e for e in meta['online']['events'] if e['kind'] == 'model_response'
                   and e['call_id'] == event['call_id'])
        self.assertEqual(event['content']['selections'], json.loads(raw['content']))

    def test_selection_extra_keys_do_not_change_verdict(self):
        bad, good, repairs = self.boundary_outputs()
        result, meta, judge = self.run_outputs([bad, {'selections': [{'judgment_index': 0,
            'group': 'threat_model_boundary_evidence', 'finding_index': 0, 'option_id': 0, 'verdict': 'supported'}]}])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_overlong_selection_also_requires_same_finding_fidelity(self):
        bad, good, repairs = self.boundary_outputs()
        self.boundary_fidelity['findings'][1]['support'] = 'not_supported'
        result, meta, judge = self.run_outputs([bad, repairs, self.boundary_fidelity])
        self.assertEqual(result['model_calls'], 5)
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(meta['reviews'], [])

    def test_repair_cannot_exceed_model_budget(self):
        self.config['max_model_calls'] = 3
        result, meta, judge = self.run_outputs([self.output('Two...decide.'), self.choice()])
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(result['operational_cause'], 'model_call_limit')
        self.assertEqual(len(judge.calls), 2)
        self.assertEqual(meta['reviews'], [])

    def test_existing_ungrounded_review_has_specific_export_diagnostic(self):
        result, meta, judge = self.run_outputs([self.judgment])
        meta['reviews'][0]['counter_evidence_search'] = self.output('Two...decide.')[
            'judgments'][0]['counter_evidence_search']
        adapter.persist(self.path, meta)
        row = next(r for r in build(adapter.load(self.path))['quality']['field_diagnostics']
                   if r['table_id'] == 'problem_definition' and r['field'] == 'parties_and_roles')
        self.assertFalse(row['has_evidence'])
        self.assertEqual(row['reasons']['counter_evidence_quote_not_found'], 1)

    def test_format_repair_cannot_turn_discovered_finding_false(self):
        result, meta, judge = self.run_outputs([self.output('x' * 51), self.judgment])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(meta['reviews'], [])
        failures = [e for e in meta['online']['events'] if e.get('failure_type') == 'invalid_model_output']
        self.assertEqual(failures[0]['validation_errors'][0]['ctx']['actual_length'], 51)
        self.assertIn('counter_evidence_finding_suppressed', str(failures[-1]))
        self.assertIn('"conditional_limits_found": true', build(meta)['grounding_failures'][0]['rejected_response'])


if __name__ == '__main__':
    unittest.main()
