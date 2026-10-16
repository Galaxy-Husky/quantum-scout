"""Pilot engineering contracts. All evidence and human checks here are synthetic."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import searchos_adapter as adapter
from citation_backends import identity, identifiers
from coverage_policy import coverage_witness
from export_batch import build
from render_calibration import render, render_case_files
from searchos_online import read_config, single_runner, partition_candidates
from audit_reachability import audit
from validate_batch import SUCCESS_STOPS, INCOMPLETE_STOPS, WARNING_CATEGORIES
from review_fixtures import add_witness_audits
import test_guards as guards
import test_integrations as integrations
import test_workflow_contracts as workflows


class IdentityBoundaryTests(unittest.TestCase):
    def test_allowlisted_paths_case_and_redundancy(self):
        for host in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org', 'ARXIV.ORG'):
            for path in ('abs/1309.3923v1', 'pdf/1309.3923v2.pdf',
                         'PDF//1309.3923V2.PDF/', 'html/1309.3923v1/',
                         'abs/1309.3923?context=cs#fragment'):
                with self.subTest(host=host, path=path):
                    self.assertEqual(identity('https://' + host + '/' + path), 'arxiv:1309.3923')
        self.assertEqual(identity('https://arxiv.org/abs/math.GT/0309136v1'),
                         identity('https://export.arxiv.org/pdf/MATH.gt/0309136V2.PDF'))
        self.assertEqual(identity('https://DX.DOI.ORG/10.1234/ABC%2Fxyz'), 'doi:10.1234/abc/xyz')

    def test_no_identity_from_mirrors_or_ambiguous_paths(self):
        urls = ['https://arxiv.org.evil.example/pdf/1309.3923',
                'https://ar5iv.labs.arxiv.org/html/1309.3923',
                'https://mirror.example/arxiv/1309.3923',
                'https://arxiv.org/pdf/1309.3923/supplement',
                'https://arxiv.org/abs/../1309.3923',
                'https://arxiv.org/abs/1309.3923vbad']
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(identifiers(url), {})
                self.assertEqual(identity(url), url)
        # A preprint and a publication DOI require explicit provider metadata to link them.
        self.assertNotEqual(identity('https://arxiv.org/abs/1309.3923'),
                            identity('https://doi.org/10.1234/published'))
        self.assertNotEqual(identity('https://doi.org/10.1234/preprint'),
                            identity('https://doi.org/10.1234/published'))

    def test_normalized_aliases_count_once_in_real_runner_export(self):
        fixture = workflows.WorkflowContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.config['max_sources_per_round'] = 3
        urls = ['https://arxiv.org/abs/1309.3923v1',
                'https://EXPORT.ARXIV.ORG/PDF//1309.3923V2.PDF/',
                'https://arxiv.org/html/1309.3923v3']
        runner = workflows.OnlineRunner(fixture.path, fixture.config,
            models={'extraction': workflows.fixtures.Model(fixture.extraction),
                    'judge': workflows.fixtures.Model(fixture.judgment)},
            providers={'serper': workflows.SequenceProvider(urls)},
            opener=fixture.opener, extractor=fixture.extractor)
        result = asyncio.run(runner.run())
        _, batch = fixture.assert_views(fixture.path, result)
        self.assertEqual(fixture.opened, urls[:1])
        self.assertEqual(batch['counts']['discovery_sources'], 1)
        self.assertEqual(batch['counts']['opened_sources'], 1)


class HumanImportTests(unittest.TestCase):
    def test_cli_import_projection_batch_and_drafts_share_current_labels(self):
        fixture = workflows.WorkflowContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.three_source_sequence(admitted=True)
        initial = adapter.load(fixture.path)
        snapshot = deepcopy(initial['online']['invocations'][-1]['stop_evidence'])
        original_reviews = deepcopy((initial['grounding'], initial['attributions'], initial['reviews']))
        decisions = initial['attributions'][:4]
        for step, status in enumerate(('unverified', 'partial', 'partial', 'verified', 'rejected')):
            if step:
                request = fixture.path / 'synthetic-human.json'
                request.write_text(json.dumps({**decisions[step - 1], 'reviewer_kind': 'human',
                    'reviewer_id': 'offline-synthetic-human', 'attribution_correct': step != 4,
                    'reason': 'Disposable fixture only; no real human audit occurred'}))
                process = subprocess.run([sys.executable, str(Path(adapter.__file__)), 'audit-attribution',
                    str(fixture.path), str(request), '--post-hoc'], capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout)['human_audit_status']['TEST-0001'], status)
            raw = adapter.load(fixture.path)
            batch = build(raw)
            case = batch['cases'][0]
            self.assertEqual(case['human_audit_status'], status)
            current_text = f'（{status}，当前派生状态）'
            self.assertIn(current_text, render(batch))
            output = fixture.path / 'drafts'
            render_case_files(batch, output)
            self.assertIn(current_text, (output / 'TEST-0001.md').read_text())
            self.assertEqual(batch['quality']['attribution']['audited_samples'], min(step, 4))
            self.assertEqual(raw['online']['invocations'][-1]['stop_evidence'], snapshot)
            self.assertEqual((raw['grounding'], raw['attributions'], raw['reviews']), original_reviews)
        self.assertEqual(len(raw['attribution_checks']), 4)
        self.assertEqual(raw['claimed_tasks'], [])


class RenderCompletenessTests(unittest.TestCase):
    def accepted(self):
        fixture = integrations.CoverageTests()
        fixture.setUp()
        data = guards.batch()
        case = fixture.case('TEST-0001', passed=True, score_count=5)
        case['human_audit_status'] = 'unverified'
        for evaluation in case['tracks'].values():
            evaluation.update(score_total=15, score_normalized=15, failure_class=None)
        case['source_ids'] = ['s1']
        data['sources'][0]['source_id'] = 's1'
        for event in data['events']:
            event['source_id'] = 's1'
        data['checkpoint']['new_source_ids'] = data['checkpoint']['input_source_ids'] = ['s1']
        data['cases'] = [case]
        data['counts'].update(accepted_cases=1, extracted_candidate_cases=1,
                              problem_definition_complete_cases=1, unique_cases=1)
        return data, fixture.config

    def test_every_current_stop_and_all_warning_categories(self):
        for reason in sorted(SUCCESS_STOPS | INCOMPLETE_STOPS):
            with self.subTest(reason=reason):
                data, config = self.accepted()
                guards.stop(data, reason, 'completed' if reason in SUCCESS_STOPS else 'incomplete')
                cp, counts = data['checkpoint'], data['counts']
                if reason == 'analysis_limit_reached':
                    counts['analysis_limit'] = 1
                elif reason == 'max_cases_reached':
                    counts['accepted_limit'] = 1
                elif reason == 'budget_exhausted':
                    cp['stop_evidence'] = {'budget_cause': 'model_call_limit'}
                elif reason == 'case_coverage_complete':
                    cp['stop_evidence'] = {'coverage_witness': coverage_witness(data['cases'], config, {'s1'})}
                    add_witness_audits(data, config)
                elif reason == 'diminishing_returns':
                    qs = guards.queries(data)
                    cp['stop_evidence'] = {'basis': 'new_sources', 'window_query_ids': [q['id'] for q in qs],
                                           'rationale': 'Synthetic bounded search'}
                elif reason == 'operational_pool_exhausted':
                    cp['stop_evidence'] = {'rationale': 'Synthetic blocked endpoint',
                        'actions': [{'id': 'blocked', 'status': 'blocked', 'reason': 'fixture'}],
                        'endpoints': [{'id': 'fixture', 'pages_fetched': 0, 'limitation': 'fixture'}]}
                data['quality']['warnings'] = [{'category': name, 'message': 'fixture-' + name}
                                               for name in sorted(WARNING_CATEGORIES)]
                before = deepcopy(data)
                report = render(json.loads(json.dumps(data)))
                self.assertIn(f'`{reason}`', report)
                self.assertIn('有限运行范围', report)
                self.assertIn('不保证语义判断或反证充分性', report)
                for warning in data['quality']['warnings']:
                    self.assertIn(f"[{warning['category']}] {warning['message']}", report)
                self.assertIn('成功打开 1', report)
                self.assertEqual(data, before)

    def test_two_tracks_scores_and_each_human_label_in_both_views(self):
        data, _ = self.accepted()
        # Distinct values catch accidental reuse of another Track's score.
        evaluations = list(data['cases'][0]['tracks'].values())
        evaluations[1].update(score_total=20, score_normalized=20)
        for dimension in evaluations[1]['scores']:
            evaluations[1]['scores'][dimension] = 4
        with tempfile.TemporaryDirectory() as directory:
            for status in ('unverified', 'partial', 'verified', 'rejected', 'not_applicable'):
                with self.subTest(status=status):
                    data['cases'][0]['human_audit_status'] = status
                    report = render(data)
                    render_case_files(data, directory)
                    draft = (Path(directory) / 'TEST-0001.md').read_text()
                    for text in (report, draft):
                        self.assertIn(f'（{status}，当前派生状态）', text)
                        self.assertIn('有限运行范围', text)
                        for track, evaluation in data['cases'][0]['tracks'].items():
                            self.assertIn(f"`{track}`", text)
                            self.assertIn(f"{evaluation['score_normalized']:.2f}", text)
                    for dimension, value in evaluations[1]['scores'].items():
                        self.assertIn(f'| `{dimension}` | {value:.2f} |', draft)


class ConfigurationAndLockTests(unittest.TestCase):
    def test_rejects_cli_extremes_before_workspace_creation(self):
        base = {'cases': {'TEST-0001': {'description': 'Synthetic configuration'}}}
        invalid = [{'max_rounds': 0}, {'max_model_calls': 0}, {'pages_per_query': 6},
                   {'results_per_page': 11}, {'max_seconds': 1.5}, {'providers': ['arxiv', 'arxiv']},
                   {'citation_backend': 'automatic'}, {'extra': 1}, {'cases': {}},
                   {'cases': {'TEST-0001': {'description': 'fixture', 'fields': ['unknown']}}}]
        import searchos_online
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, change in enumerate(invalid):
                with self.subTest(change=change):
                    config = root / 'config.json'
                    config.write_text(json.dumps({**base, **change}))
                    workspace = root / f'invalid-{index}'
                    process = subprocess.run([sys.executable, searchos_online.__file__, 'run',
                        '--config', str(config), '--project-root', folder, '--workspace', str(workspace)],
                        capture_output=True, text=True, timeout=30)
                    self.assertEqual(process.returncode, 2, process.stderr)
                    self.assertNotIn('Traceback', process.stderr)
                    self.assertFalse(workspace.exists())

    def test_nine_candidates_are_rejected_before_grounding(self):
        from pydantic import ValidationError
        fixture = workflows.WorkflowContractTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with self.assertRaises(ValidationError):
            partition_candidates({'candidates': [fixture.candidate] * 9, 'missing': {}}, ['parties_and_roles'])
        self.assertEqual(adapter.load(fixture.path)['grounding'], {})

    def test_process_lock_rejects_contender_and_releases_after_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            script = ('from pathlib import Path\nfrom searchos_online import single_runner\n'
                      'import sys\nwith single_runner(Path(sys.argv[1])):\n'
                      ' print("locked", flush=True)\n sys.stdin.read()\n')
            process = subprocess.Popen([sys.executable, '-c', script, folder],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                # select prevents an unbounded wait if the child fails to acquire.
                import select
                ready, _, _ = select.select([process.stdout], [], [], 20)
                self.assertTrue(ready, 'Lock owner did not become ready')
                self.assertEqual(process.stdout.readline().strip(), 'locked')
                with self.assertRaisesRegex(RuntimeError, 'Another online runner'):
                    with single_runner(path):
                        self.fail('Contender entered critical section')
                process.kill()
                process.wait(timeout=10)
                with single_runner(path):
                    pass
                with self.assertRaisesRegex(RuntimeError, 'synthetic exception'):
                    with single_runner(path):
                        raise RuntimeError('synthetic exception')
                with single_runner(path):
                    pass
                # Keep the inode: unlinking a flock file can create two lock domains.
                self.assertTrue((path / '.online.lock').exists())
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)


class ReachabilityScaleTests(unittest.TestCase):
    def test_twelve_snapshots_deduplicate_sort_window_and_skip_nested_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = []
            for index in range(12):
                path = root / f'workspace-{index:02}'
                (path / 'calibration').mkdir(parents=True)
                (path / 'calibration/batch.json').write_text(json.dumps({
                    'stop_reason': 'error' if index % 2 else 'budget_exhausted',
                    'events': [{'timestamp': f'2026-10-{index + 1:02}T00:00:00Z'}],
                    'quality': {'warnings': [{'category': 'grounding'}] * 3,
                                'field_diagnostics': [{'reasons': {'quote_not_found': 2}}] * 4}}))
                paths.append(path)
            bad = root / 'bad'
            (bad / 'calibration').mkdir(parents=True)
            invalid = bad / 'calibration/batch.json'
            for change in ({'quality': None}, {'quality': []}, {'quality': {'warnings': [None]}},
                           {'quality': {'field_diagnostics': [None]}},
                           {'quality': {'field_diagnostics': [{'reasons': []}]}},
                           {'quality': {'field_diagnostics': [{'reasons': {'bad': 'many'}}]}},
                           {'stop_reason': []}):
                with self.subTest(change=change):
                    invalid.write_text(json.dumps(change))
                    before = {p: p.read_bytes() for p in root.rglob('batch.json')}
                    result = audit([*paths, *paths, paths[-1] / '..' / paths[-1].name, bad], window=10)
                    self.assertEqual(result['snapshots'], 10)
                    self.assertEqual(result['workspaces'], [str(p) for p in reversed(paths[2:])])
                    self.assertEqual(len(result['skipped']), 1)
                    self.assertEqual(next(r['observations'] for r in result['warning_categories']
                                          if r['branch'] == 'grounding'), 10)
                    self.assertEqual(next(r['observations'] for r in result['diagnostic_reasons']
                                          if r['branch'] == 'quote_not_found'), 10)
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('batch.json')})
