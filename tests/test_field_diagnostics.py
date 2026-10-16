import unittest
from copy import deepcopy
from field_diagnostics import field_diagnostics


class FieldDiagnosticsTests(unittest.TestCase):
    def fixture(self):
        fields = ['x', 'y', 'z']
        meta = {'schema': {'tables': [{'table_id': 'problem_definition', 'attributes': fields},
                                      {'table_id': 'T_admission', 'attributes': ['C1']}]},
                'grounding': {}, 'online': {'sources': {'s': {'status': 'opened', 'source':
                    {'source_id': 's', 'document_version': 'v', 'segments': [{}, {}]}}},
                    'assessments': {'a': 'done'}, 'events': []}}
        scope = {'kind': 'assessment_started', 'case_id': 'C', 'table_id': 'problem_definition',
                 'task_id': 't', 'source_id': 's', 'fields': fields, 'assessment_id': 'a',
                 'document_version': 'v', 'total_segments': 2}
        meta['online']['events'] = [scope, {'kind': 'source_context', 'task_id': 't',
            'source_id': 's', 'start_segment': 0, 'included_segments': 2},
            {'kind': 'model_call_started', 'cost_category': 'extraction'}]
        cases = [{'case_id': 'C', 'problem_definition': {}, 'tracks': {}}]
        return meta, cases

    def test_explicit_observations_multicausal_and_read_only(self):
        meta, cases = self.fixture()
        meta['online']['events'] += [
            {'kind': 'field_gap_observation', 'case_id': 'C', 'field': 'x', 'source_id': 's', 'reason': 'No item in first chunk'},
            {'kind': 'contract_rejection', 'field': 'x', 'candidate': {'quote': 'bad'}},
            {'kind': 'field_gap_observation', 'case_id': 'C', 'field': 'x', 'source_id': 's', 'reason': 'Filtered item'},
            {'kind': 'failure', 'failure_type': 'contextgem_reference_rejected', 'field': 'y', 'reason': 'Wrong sentence'}]
        before = deepcopy(meta)
        rows = {(r['table_id'], r['field']): r for r in field_diagnostics(meta, cases)}
        self.assertEqual(rows[('problem_definition', 'x')]['reasons'], {'no_candidate': 1, 'candidate_rejected': 1})
        self.assertEqual(rows[('problem_definition', 'y')]['reasons'], {'location_failed': 1})
        self.assertEqual(rows[('problem_definition', 'z')]['reasons'], {})
        self.assertEqual(rows[('problem_definition', 'z')]['diagnostic_status'], 'diagnosis_unavailable')
        self.assertEqual(rows[('T_admission', 'C1')]['reasons'], {})
        self.assertEqual(rows[('T_admission', 'C1')]['attempt_status'], 'not_attempted')
        row = rows[('problem_definition', 'x')]['sources'][0]
        self.assertEqual(row['processing_status'], 'done')
        self.assertEqual(row['shared_extraction_calls'], 1)
        self.assertEqual(meta, before)

    def test_source_and_table_scopes_do_not_leak(self):
        meta, cases = self.fixture()
        meta['online']['events'] += [
            {'kind': 'round_completed'},
            {'kind': 'assessment_started', 'case_id': 'C', 'table_id': 'T_admission', 'task_id': 't2',
             'source_id': 'other', 'fields': ['C1'], 'assessment_id': 'b'},
            {'kind': 'source_context', 'task_id': 't2', 'source_id': 'other', 'start_segment': 3, 'included_segments': 1},
            {'kind': 'contract_rejection', 'field': 'C1', 'candidate': {}},
        ]
        rows = {(r['table_id'], r['field']): r for r in field_diagnostics(meta, cases)}
        row = rows[('T_admission', 'C1')]
        self.assertEqual(row['reasons'], {'candidate_rejected': 1})
        self.assertEqual(row['sources'][0]['provided_segments'], [3])
        self.assertEqual(row['sources'][0]['processing_status'], 'pending_or_unknown')
        self.assertNotIn('candidate_rejected', rows[('problem_definition', 'x')]['reasons'])

    def test_actual_grounding_failure_is_not_no_candidate(self):
        import json
        from test_searchos_online import OnlineTests
        fixture = OnlineTests()
        fixture.setUp()
        try:
            fixture.candidate['quote'] = 'Fabricated quote.'
            fixture.run_fixture()
            batch = json.loads((fixture.path / 'calibration/batch.json').read_text())
            row = next(r for r in batch['quality']['field_diagnostics']
                       if r['table_id'] == 'problem_definition' and r['field'] == 'parties_and_roles')
            self.assertEqual(row['reasons'], {'grounding_failed': 1})
        finally:
            fixture.doCleanups()
