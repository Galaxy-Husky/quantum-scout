"""Reproduce live counter-quote failures without external calls or weaker gates."""
import asyncio
from copy import deepcopy
import unittest

import searchos_adapter as adapter
from export_batch import build
from searchos_online import OnlineRunner
import test_searchos_online as fixtures


class LiveReviewRepairTests(unittest.TestCase):
    setUp = fixtures.OnlineTests.setUp
    opener = fixtures.OnlineTests.opener
    extractor = fixtures.OnlineTests.extractor

    def output(self, quote):
        result = deepcopy(self.judgment)
        result['judgments'][0]['counter_evidence_search'].update(
            conditional_limits_found=True,
            conditional_limits_evidence=[{'location': 'paragraph:1', 'quote': quote}])
        return result

    def run_outputs(self, outputs):
        judge = fixtures.Model(outputs)
        runner = OnlineRunner(self.path, self.config,
            models={'extraction': fixtures.Model(self.extraction), 'judge': judge},
            providers={'serper': self.provider}, opener=self.opener, extractor=self.extractor)
        return asyncio.run(runner.run()), adapter.load(self.path), judge

    def test_one_shared_repair_corrects_nonverbatim_counter_quote(self):
        bad = self.output('Two...decide.')
        good = self.output('Two parties decide.')
        result, meta, judge = self.run_outputs([bad, good])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['coverage']['filled'], 1)
        self.assertEqual(meta['reviews'][0]['counter_evidence_search']['conditional_limits_evidence'][0]['quote'],
                         'Two parties decide.')
        failures = [e for e in meta['online']['events'] if e.get('failure_type') == 'invalid_model_output']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['field'], 'parties_and_roles')
        self.assertIn('counter_evidence_quote_not_found', str(failures[0]))
        self.assertIn('Two...decide.', str(judge.calls[-1]))

    def test_length_and_grounding_share_one_repair_allowance(self):
        result, meta, judge = self.run_outputs([self.output('x' * 51), self.output('Two...decide.')])
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['operational_cause'], 'contract_violation')
        self.assertEqual(result['coverage']['filled'], 0)
        self.assertEqual(meta['reviews'], [])
        self.assertEqual(len([e for e in meta['online']['events'] if e.get('failure_type') == 'invalid_model_output']), 2)

    def test_repair_cannot_exceed_model_budget(self):
        self.config['max_model_calls'] = 3
        result, meta, judge = self.run_outputs([self.output('Two...decide.'), self.judgment])
        self.assertEqual(result['model_calls'], 3)
        self.assertEqual(result['stop_reason'], 'budget_exhausted')
        self.assertEqual(result['operational_cause'], 'model_call_limit')
        self.assertEqual(len(judge.calls), 2)  # Attribution and rejected semantic response only.
        self.assertEqual(meta['reviews'], [])

    def test_existing_ungrounded_review_has_specific_export_diagnostic(self):
        result, meta, judge = self.run_outputs([self.judgment])
        meta['reviews'][0]['counter_evidence_search'] = self.output('Two...decide.')[
            'judgments'][0]['counter_evidence_search']
        adapter.persist(self.path, meta)
        batch = build(adapter.load(self.path))
        row = next(r for r in batch['quality']['field_diagnostics']
                   if r['table_id'] == 'problem_definition' and r['field'] == 'parties_and_roles')
        self.assertFalse(row['has_evidence'])
        self.assertEqual(row['reasons']['counter_evidence_quote_not_found'], 1)

    def test_format_repair_cannot_turn_discovered_finding_false(self):
        result, meta, judge = self.run_outputs([self.output('x' * 51), self.judgment])
        self.assertEqual(result['stop_reason'], 'error')
        self.assertEqual(result['model_calls'], 4)
        self.assertEqual(meta['reviews'], [])
        failures = [e for e in meta['online']['events'] if e.get('failure_type') == 'invalid_model_output']
        self.assertEqual(failures[0]['validation_errors'][0]['ctx']['actual_length'], 51)
        self.assertIn('counter_evidence_finding_suppressed', str(failures[-1]))
        batch = build(meta)
        self.assertEqual(len([f for f in batch['grounding_failures']
                              if f['failure_type'] == 'counter_evidence_invalid']), 2)
        self.assertIn('"conditional_limits_found": true', batch['grounding_failures'][0]['rejected_response'])


if __name__ == '__main__':
    unittest.main()
