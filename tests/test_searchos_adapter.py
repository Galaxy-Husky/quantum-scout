"""Behavioral tests using actual SearchOS models and isolated worker, offline."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    import searchos
    import yaml
    AVAILABLE = True
except ImportError:
    AVAILABLE = False
if AVAILABLE:
    from searchos_project import WorkspaceLayout
    from schema_generator import generate
    from searchos_adapter import prepare, ground, attribute, review, load, project, summary, persist, record_gap


@unittest.skipUnless(AVAILABLE, 'Use the SearchOS venv for integration tests')
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'adapter-test'
        self.state = prepare(self.path, case_ids=['TEST-0001'])

    def request(self, value='Two participants', quote='Two parties'):
        return {'run_id': 'adapter-test', 'extractor_id': 'extractor-A', 'table_id': 'problem_definition',
                'source': {'source_id': 'fixture', 'run_id': 'adapter-test', 'status': 'opened',
                           'document_version': 'v1 section 1', 'text': 'Two parties decide. Three parties observe.'},
                'evidence': [{'case_id': 'TEST-0001', 'field': 'parties_and_roles', 'source_id': 'fixture',
                              'value_text': value, 'quote': quote, 'location': 'v1 section 1',
                              'evidence_level': 'primary', 'confidence': 'medium'}]}

    def decision(self, report, verdict='supported', with_attribution=True):
        candidate = report['validated_candidates'][0]
        if with_attribution and not any(a['report_id'] == report['report_id'] for a in load(self.path).get('attributions', [])):
            attribute(self.path, {'report_id': report['report_id'], 'candidate_index': 0,
                'reviewer_kind': 'agent', 'reviewer_id': 'attribution-A',
                'case_id': candidate['case_id'], 'location': candidate['location'],
                'value_text': candidate['value_text'], 'source_sha256': candidate['grounding']['source_sha256'],
                'attribution': 'attributed', 'attribution_reason': 'Synthetic case-specific evidence'})
        return {'report_id': report['report_id'], 'candidate_index': 0, 'reviewer_kind': 'agent',
                'case_id': candidate['case_id'], 'location': candidate['location'],
                'domain_rule_met': 'met', 'domain_rule_reason': 'Synthetic field rule satisfied',
                'counter_evidence_search': {'summary': 'Synthetic search for not and only',
                    'segments_searched': [candidate['location']], 'negation_found': False,
                    'conditional_limits_found': False, 'threat_model_boundary_found': False, 'contradictions_found': []},
                'reviewer_id': 'reviewer-B', 'verdict': verdict, 'reason': 'Synthetic test review only',
                'location_checked': True, 'source_sha256': candidate['grounding']['source_sha256'],
                'value_text': candidate['value_text']}

    def test_eight_fields_and_track_columns_no_auto_filled_identity(self):
        tables = generate(['TEST-0001'])['tables']
        self.assertEqual(len(tables[0]['attributes']), 8)
        self.assertEqual([len(t['attributes']) for t in tables], [8, 4, 5, 4, 6])
        self.assertEqual(summary(self.state)['filled'], 0)
        self.assertEqual(summary(self.state)['ready_tasks'], 1)
        self.assertEqual(summary(self.state)['blocked_tasks'], 4)

    def test_duplicate_ids_and_unknown_cases_rejected(self):
        with self.assertRaises(ValueError): generate(['TEST-0001', 'TEST-0001'])
        request = self.request(); request['evidence'][0]['case_id'] = 'TEST-0002'
        with self.assertRaises(ValueError): ground(self.path, request)

    def test_existing_workspace_never_overwritten(self):
        before = (WorkspaceLayout(self.path).adapter).read_bytes()
        with self.assertRaises(FileExistsError): prepare(self.path, case_ids=['TEST-0001'])
        self.assertEqual(before, (WorkspaceLayout(self.path).adapter).read_bytes())

    def test_quote_match_stays_uncertain_until_independent_review(self):
        report = ground(self.path, self.request())
        self.assertEqual(report['facts'], [])
        state = project(load(self.path))
        self.assertEqual(summary(state)['filled'], 0)
        self.assertEqual(summary(state)['uncertain'], 1)
        self.assertEqual(summary(state)['evidence_nodes'], 0)
        result = review(self.path, self.decision(report))
        self.assertEqual(result['filled'], 1)
        self.assertEqual(result['evidence_nodes'], 1)
        self.assertIsNone(result['stop_reason'])

    def test_failed_quote_audited_in_failure_memory_and_idempotent(self):
        request = self.request(quote='Six parties')
        report = ground(self.path, request)
        self.assertEqual(report['grounding_failures'][0]['failure_type'], 'quote_not_found')
        self.assertEqual(ground(self.path, request)['report_id'], report['report_id'])
        meta = load(self.path)
        self.assertEqual(len(meta['grounding']), 1)
        self.assertEqual(summary(project(meta))['failure_patterns'], 1)
        self.assertEqual(summary(project(meta))['filled'], 0)

    def test_wrong_run_and_metadata_source_cannot_supply_evidence(self):
        request = self.request(); request['run_id'] = 'old'
        with self.assertRaises(ValueError): ground(self.path, request)
        request = self.request(); request['source']['status'] = 'opened_metadata_only'
        report = ground(self.path, request)
        self.assertTrue(report['grounding_failures'])
        self.assertEqual(summary(project(load(self.path)))['evidence_nodes'], 0)

    def test_review_must_bind_text_claim_location_and_reviewer(self):
        report = ground(self.path, self.request())
        decision = self.decision(report)
        for field, value in [('source_sha256', 'stale'), ('value_text', 'Changed claim'),
                             ('reviewer_id', 'extractor-A'), ('case_id', 'OTHER-0001'),
                             ('reviewer_kind', 'halt')]:
            bad = {**decision, field: value}
            with self.subTest(field=field), self.assertRaises(ValueError): review(self.path, bad)
        self.assertFalse(load(self.path)['reviews'])

    def test_semantic_mismatch_is_preserved_without_graph_insertion(self):
        report = ground(self.path, self.request())
        result = review(self.path, self.decision(report, 'semantic_mismatch'))
        self.assertEqual(result['evidence_nodes'], 0)
        self.assertEqual(result['filled'], 0)
        self.assertEqual(result['failure_patterns'], 1)

    def test_conflicts_downgrade_cell_and_create_graph_edges(self):
        first = ground(self.path, self.request())
        review(self.path, self.decision(first))
        second = ground(self.path, self.request('Three participants', 'Three parties'))
        result = review(self.path, self.decision(second))
        state = project(load(self.path))
        self.assertEqual(result['filled'], 0)
        self.assertEqual(result['uncertain'], 1)
        self.assertEqual(len(state.evidence_graph.edges), 1)

    def test_duplicate_reviews_of_same_fact_have_no_dangling_evidence_ids(self):
        first = ground(self.path, self.request()); review(self.path, self.decision(first))
        request = self.request(); request['extractor_id'] = 'extractor-C'
        second = ground(self.path, request); review(self.path, self.decision(second))
        state = project(load(self.path))
        ids = {n.id for n in state.evidence_graph.nodes}
        self.assertEqual(len(ids), 1)
        cell = state.coverage_map.cells['problem_definition/TEST-0001.parties_and_roles']
        self.assertEqual(set(cell.supporting_evidence_ids), ids)

    def test_case_sensitive_values_are_not_merged_by_upstream_dedup(self):
        first = ground(self.path, self.request('10 mW')); review(self.path, self.decision(first))
        second = ground(self.path, self.request('10 MW')); review(self.path, self.decision(second))
        state = project(load(self.path))
        self.assertEqual(len(state.evidence_graph.nodes), 2)
        self.assertEqual(summary(state)['filled'], 0)

    def test_replay_recovers_projection_without_repeating_reviews(self):
        report = ground(self.path, self.request()); review(self.path, self.decision(report))
        (WorkspaceLayout(self.path).socm / 'search_state.json').unlink()
        restored = persist(self.path, load(self.path))
        self.assertEqual(summary(restored)['filled'], 1)
        with self.assertRaises(ValueError): review(self.path, self.decision(report))

    def test_legacy_values_and_missing_reasons_never_count_as_evidence(self):
        batch = {'run_id': 'old-run', 'cases': [{'case_id': 'TEST-0001', 'problem_definition': {
            'real_world_problem': {'value_text': 'Legacy conclusion', 'quote': 'legacy quote'},
            'constraints': {'value_text': None, 'reason': 'not reported'}}, 'tracks': {}}]}
        path = Path(self.temporary.name) / 'migration'
        result = summary(prepare(path, batch=batch))
        self.assertEqual(result['filled'], 0)
        self.assertEqual(result['uncertain'], 1)
        self.assertEqual(result['missing'], 26)
        self.assertEqual(result['evidence_nodes'], 0)

    def test_admission_cannot_use_invalid_enum_or_missing_evidence_claim(self):
        for value in ('yes', 'insufficient_evidence'):
            request = self.request(value)
            request['table_id'] = 'nonlocal-coordination_admission'
            request['evidence'][0]['field'] = 'C1'
            with self.subTest(value=value), self.assertRaises(ValueError): ground(self.path, request)

    def test_gap_reason_completes_audit_but_does_not_fill_evidence(self):
        for field in load(self.path)['config']['fields']:
            record_gap(self.path, {'table_id': 'problem_definition', 'case_id': 'TEST-0001',
                       'field': field, 'status': 'hard_cell', 'reason': 'Synthetic access failure',
                       'attempts': [{'endpoint': 'fixture', 'error': '403'}]})
        result = summary(project(load(self.path)))
        self.assertEqual(result['filled'], 0)
        self.assertEqual(result['hard_cell'], 8)
        self.assertEqual(result['ready_tasks'], 2)
        self.assertEqual(result['blocked_tasks'], 2)
        self.assertIsNone(result['stop_reason'])

    def test_add_case_expands_denominator_and_task_can_be_released(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/searchos_adapter.py'
        def call(*args):
            result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        result = call('add-case', str(self.path), '--case-id', 'TEST-0002')
        self.assertEqual(result['total_cells'], 54)
        task = call('next-task', str(self.path))
        self.assertEqual(summary(project(load(self.path)))['running_tasks'], 1)
        result = call('release-task', str(self.path), task['id'], '--reason', 'fixture interrupted')
        self.assertEqual(result['running_tasks'], 0)
        self.assertEqual(result['ready_tasks'], 2)


if __name__ == '__main__':
    unittest.main()
