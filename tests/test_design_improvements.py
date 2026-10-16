"""All-case completion, bounded recovery and auditable text matching (offline only)."""
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

import searchos_adapter as adapter
from baseline_policy import execution_baseline, skill_baseline
from citation_backends import CitationBackend, backend_capabilities
from coverage_policy import validate_case_coverage_stop
from export_batch import build
from online_policy import stop_decision, attribution_metrics
from review_policy import counter_search_valid, source_reviewable
from schema_generator import generate, digest
from searchos_online import OnlineRunner, CounterEvidenceSearch, doctor
import test_audit_layer as audit_fixtures
import test_searchos_online as online_fixtures
from test_searchos_online import Model, Provider
from validate_grounding import grounding_gate


def complete_meta(two=False):
    fixture = audit_fixtures.AuditTests('test_self_audit_recomputes_complete_chain')
    fixture.setUp()
    meta = deepcopy(fixture.meta)
    fixture.doCleanups()
    meta['online']['config']['cases'] = {'TEST-0001': {'description': 'Offline fixture', 'queries': {}}}
    meta['online']['sources']['s'].update(url=fixture.source['url'], at=adapter.now())
    if two:
        cid = 'TEST-0002'
        meta['case_ids'].append(cid)
        meta['schema'] = generate(meta['case_ids'], meta['config'])
        meta['online']['config']['cases'][cid] = {'description': 'Second offline case', 'queries': {}}
        source = deepcopy(fixture.source)
        source.update(source_id='synthetic2', url='https://fixture.example/paper2')
        meta['online']['sources']['s2'] = {'status': 'opened', 'source': source, 'url': source['url'], 'at': adapter.now()}
        for rid, entry in list(meta['grounding'].items()):
            new = deepcopy(entry)
            new['request']['source'] = deepcopy(source)
            new['request']['evidence'][0].update(case_id=cid, source_id='synthetic2')
            new['report'] = grounding_gate().validate(new['request'])
            new_id = digest(new['request'])
            meta['grounding'][new_id] = new
            for key in ('attributions', 'reviews'):
                old = next(d for d in meta[key] if d['report_id'] == rid)
                meta[key].append({**deepcopy(old), 'report_id': new_id, 'case_id': cid})
    return meta


def test_partial_multicase_does_not_stop_other_case():
    meta = complete_meta(two=True)
    meta['reviews'] = [r for r in meta['reviews'] if r['case_id'] == 'TEST-0001']
    decision = stop_decision(meta, adapter.project(meta))
    assert decision is None or decision[0] != 'case_coverage_complete'
    assert any('TEST-0002' in c for t in adapter.project(meta).frontier.questions for c in t.target_cells)


def test_all_cases_recompute_coverage_and_audit_body():
    meta = complete_meta(two=True)
    decision = stop_decision(meta, adapter.project(meta))
    assert decision[0] == 'case_coverage_complete'
    assert [r['coverage_witness']['case_id'] for r in decision[1]['case_completions']] == meta['case_ids']
    assert all(r['self_audit']['audit_passed'] for r in decision[1]['case_completions'])
    meta['online']['sources']['s2']['source']['text'] = 'Changed second source'
    trace = {}
    assert stop_decision(meta, adapter.project(meta), trace=trace) is None
    assert trace['reason'] == 'self_audit_rejected'
    assert trace['self_audit']['case_id'] == 'TEST-0002'


@pytest.mark.parametrize('two', [False, True])
def test_completed_stop_roundtrips_runner_export_and_guard(tmp_path, two):
    meta = complete_meta(two=two)
    path = tmp_path / 'audit'
    adapter.prepare(path, case_ids=meta['case_ids'])
    # Keep pending discovered sources: completion does not claim all sources were attempted.
    meta['online']['searches']['pending'] = {'provider': 'serper', 'query': 'offline', 'at': adapter.now(),
        'status': 'succeeded', 'results': [{'url': 'https://fixture.example/unattempted'}], 'target_cells': []}
    adapter.persist(path, meta)
    runner = OnlineRunner(path, meta['online']['config'], providers={'serper': object()})
    result = asyncio.run(runner.run())
    batch = json.loads((path / 'calibration/batch.json').read_text())
    assert result['stop_reason'] == 'case_coverage_complete'
    assert batch['run_status'] == 'completed' and batch['checkpoint']['completed'] is True
    assert batch['counts']['sources_unattempted'] == 1
    assert not any(w['category'] == 'citation_unverified' for w in batch['quality']['warnings'])
    validate_case_coverage_stop(batch)
    report = (path / 'calibration/comparison.md').read_text()
    assert report.count('：机器完成 /') == len(meta['case_ids'])
    if two:
        bad = deepcopy(batch)
        bad['cases'].pop()
        with pytest.raises(ValueError, match='scope'):
            validate_case_coverage_stop(bad)
        bad = deepcopy(batch)
        bad['checkpoint']['stop_evidence']['case_completions'][1]['self_audit']['audit_passed'] = False
        with pytest.raises(ValueError, match='self audit'):
            validate_case_coverage_stop(bad)
        bad = deepcopy(batch)
        bad['cases'][1]['problem_definition'] = {}
        with pytest.raises(ValueError, match='Every configured case'):
            validate_case_coverage_stop(bad)


@pytest.mark.parametrize('raw,quote,method', [
    ('A\t \n  B', 'A B', 'whitespace_normalized'),
    ('quan-\ntum', 'quantum', 'hyphen_joined'),
    ('quan-\r\n  tum', 'quantum', 'hyphen_joined'),
    ('quan\u00adtum', 'quantum', 'soft_hyphen_removed'),
    ('quan\u200btum', 'quantum', 'zero_width_removed'),
    ('quan\ufefftum', 'quantum', 'zero_width_removed'),
    ('quan-\ntum\t  secure', 'quantum secure', 'hyphen_joined'),
])
def test_format_artifacts_preserve_raw_span(raw, quote, method):
    text = 'prefix! ' + raw + ' suffix!'
    request = {'run_id': 'test', 'source': {'source_id': 's', 'run_id': 'test', 'status': 'opened',
        'document_version': 'v1', 'text': text}, 'evidence': [{'source_id': 's', 'case_id': 'TEST-0001',
        'field': 'constraints', 'quote': quote, 'location': 'v1', 'search_span': [8, 8 + len(raw)]}]}
    report = grounding_gate().validate(request)
    assert report['facts'] == [] and report['grounding_failures'] == []
    receipt = report['validated_candidates'][0]['grounding']
    assert receipt['span'] == [8, 8 + len(raw)]
    assert receipt['matched_text'] == text[slice(*receipt['span'])] == raw
    assert method in receipt['normalization_methods']


@pytest.mark.parametrize('raw,quote', [
    ('１２', '12'), ('2²', '22'), ('x₂', 'x2'), ('①', '1'), ('Ⅳ', 'IV'), ('ﬁ', 'fi'),
    ('no security', 'security guaranteed'), ('does not work', 'does work'),
    ('Quantum', 'quantum'), ('x,y', 'x y'), ('1-\n2', '12'), ('a\u200db', 'ab'), ('a\u200cb', 'ab'),
])
def test_semantic_and_nfkc_changes_cannot_auto_pass(raw, quote):
    request = {'run_id': 'test', 'source': {'source_id': 's', 'run_id': 'test', 'status': 'opened',
        'document_version': 'v1', 'text': raw}, 'evidence': [{'source_id': 's', 'case_id': 'TEST-0001',
        'field': 'constraints', 'quote': quote, 'location': 'v1'}]}
    report = grounding_gate().validate(request)
    assert report['validated_candidates'] == []
    assert report['grounding_failures'][0]['failure_type'] == 'quote_not_found'


def counter(**changes):
    return {'segments_searched': ['p1'], 'negation_found': False, 'conditional_limits_found': False,
            'threat_model_boundary_found': False, 'contradictions_found': [], 'summary': 'Offline bounded search', **changes}


def test_counter_true_requires_bound_short_quote_and_body_match():
    for key in ('negation', 'conditional_limits', 'threat_model_boundary'):
        with pytest.raises(ValidationError):
            CounterEvidenceSearch(**counter(**{key + '_found': True}))
        data = counter(**{key + '_found': True, key + '_evidence': [{'location': 'p1', 'quote': 'not'}]})
        assert CounterEvidenceSearch(**data)
        review = {'counter_evidence_search': data}
        assert counter_search_valid(review, {'location': 'p1'})
        assert source_reviewable({'segments': [{'location': 'p1', 'text': 'does not work'}]}, review)
        assert not source_reviewable({'segments': [{'location': 'p1', 'text': 'works'}]}, review)
        data[key + '_evidence'][0]['location'] = 'p2'
        assert not counter_search_valid(review, {'location': 'p1'})
    for finding in ('unstructured', {'location': 'p1', 'quote': 'x' * 51}, {'location': 'p2', 'quote': 'x'}):
        with pytest.raises(ValidationError):
            CounterEvidenceSearch(**counter(contradictions_found=[finding]))


def test_document_baseline_warns_execution_changes_block_and_legacy_is_not_migrated(tmp_path):
    for folder in ('scripts', 'config', 'assets', 'references'):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'a').write_text('original')
    (tmp_path / 'SKILL.md').write_text('entry')
    (tmp_path / 'CHANGELOG.md').write_text('log')
    first = skill_baseline(tmp_path)
    meta = {'online': {'skill_baseline': first, 'invocations': [{}]}}
    snapshot = deepcopy(meta)
    (tmp_path / 'references/a').write_text('clarification')
    with pytest.warns(UserWarning, match='document baseline'):
        assert execution_baseline(meta, skill_baseline(tmp_path)) == first
    assert meta == snapshot
    (tmp_path / 'scripts/a').write_text('execution change')
    with pytest.raises(ValueError, match='baseline changed'):
        execution_baseline(meta, skill_baseline(tmp_path))
    with pytest.raises(ValueError, match='baseline changed'):
        execution_baseline({'online': {'skill_baseline': {'version': 2, 'sha256': 'old'}}}, first)


def test_doctor_capabilities_without_network_and_no_backend_switch():
    meta = complete_meta()
    config = meta['online']['config']
    for name in ('none', 'openalex', 'semantic_scholar'):
        config['citation_backend'] = name
        with patch.object(httpx.AsyncClient, 'send', side_effect=AssertionError('No network allowed')):
            result = doctor(config, ['https://arxiv.org/abs/2510.00199'])
        assert result['state_owner'] == 'state/quantum_adapter.json'
        assert result['searchos_runtime_enabled'] is False
        assert result['citation_capabilities'] == backend_capabilities(name)
        assert any(w['type'] == 'citation_identifier_unsupported' for w in result['warnings']) == (name == 'openalex')
        assert config['citation_backend'] == name


@pytest.mark.parametrize('name,ids,reason', [
    ('openalex', {'arxiv': '2510.00199'}, 'unsupported_identifier'),
    ('semantic_scholar', {}, 'no_identifier'), ('none', {'doi': '10.1234/x'}, 'backend_disabled'),
])
def test_citation_unsupported_combinations_do_not_request(name, ids, reason):
    backend = CitationBackend(name, transport=httpx.MockTransport(lambda _: pytest.fail('unexpected request')))
    assert asyncio.run(backend.verify(ids))['reason'] == reason
    assert backend.requests == []


@pytest.mark.parametrize('response,reason', [(404, 'not_indexed_by_provider'), (429, 'rate_limited'), (200, 'invalid_response')])
def test_citation_unknown_receipts(response, reason):
    backend = CitationBackend('semantic_scholar', transport=httpx.MockTransport(
        lambda _: httpx.Response(response, json=[], headers={'retry-after': '42'})))
    result = asyncio.run(backend.verify({'doi': '10.1234/x'}, 'expected'))
    assert result['state'] == 'unknown' and result['reason'] == reason
    assert result['retry_after'] == '42' and len(backend.requests[0]['response_sha256']) == 64


class TestSearchRecovery:
    @pytest.fixture(autouse=True)
    def setup(self):
        fixture = online_fixtures.OnlineTests('test_direct_source_uses_full_pipeline_and_cached_body_on_resume')
        fixture.setUp()
        self.f = fixture
        yield
        fixture.doCleanups()

    def runner(self, provider):
        f = self.f
        return OnlineRunner(f.path, f.config, models={'orchestrator': Model({'query': 'fixture'}),
            'extraction': Model(f.extraction), 'judge': Model(f.judgment)}, providers={'serper': provider},
            opener=f.opener, extractor=f.extractor)

    @pytest.mark.parametrize('recover', [False, True])
    def test_transient_search_retried_only_once_across_explicit_runs(self, recover):
        provider = Provider(fail=True)
        asyncio.run(self.runner(provider).run())
        assert len(provider.calls) == 1
        record = next(iter(adapter.load(self.f.path)['online']['searches'].values()))
        assert record['status'] == 'failed'
        provider.fail = not recover
        asyncio.run(self.runner(provider).run())
        assert len(provider.calls) == 2
        meta = adapter.load(self.f.path)
        record = next(iter(meta['online']['searches'].values()))
        assert record['attempts'] == 2 and record['previous_attempts'][0]['error_type'] == 'TimeoutError'
        assert len([e for e in meta['online']['events'] if e['kind'] == 'search_retry']) == 1
        asyncio.run(self.runner(provider).run())
        assert len(provider.calls) == 2
        if recover:
            metrics = attribution_metrics(adapter.load(self.f.path))
            assert metrics['same_model_used'] is True
            assert metrics['model_pairs_recorded'] == 1
            for key in ('attributions', 'reviews'):
                call = meta[key][0]['model_call']
                assert call['model'] == 'test-double' and 'temperature' in call['parameters']

    def test_http_search_errors_are_permanent_and_keep_retry_after(self):
        calls = []
        async def search(*args):
            calls.append(args)
            raise httpx.HTTPStatusError('synthetic', request=httpx.Request('GET', 'https://fixture.example'),
                response=httpx.Response(429, headers={'retry-after': '9'}))
        provider = SimpleNamespace(search=search)
        asyncio.run(self.runner(provider).run())
        asyncio.run(self.runner(provider).run())
        assert len(calls) == 1
        meta = adapter.load(self.f.path)
        record = next(iter(meta['online']['searches'].values()))
        assert record['status_code'] == 429 and record['retry_after'] == '9'
        assert not any(e['kind'] == 'search_retry' for e in meta['online']['events'])


def test_main_quote_cannot_cross_declared_segment_or_forge_receipt():
    source = {'source_id': 's', 'run_id': 'r', 'status': 'opened', 'document_version': 'v1',
        'text': 'Page one says nothing. Page two has evidence.',
        'segments': [{'location': 'p1', 'text': 'Page one says nothing.'},
                     {'location': 'p2', 'text': 'Page two has evidence.'}]}
    item = {'source_id': 's', 'case_id': 'TEST-0001', 'field': 'constraints', 'location': 'p1', 'quote': 'evidence'}
    request = {'run_id': 'r', 'source': source, 'evidence': [item]}
    report = grounding_gate().validate(request)
    assert not report['validated_candidates']
    assert report['grounding_failures'][0]['failure_type'] == 'quote_not_found'
    item['search_span'] = [0, len(source['text'])]
    assert grounding_gate().validate(request)['grounding_failures'][0]['failure_type'] == 'location_span_mismatch'
    meta = complete_meta()
    candidate = next(iter(meta['grounding'].values()))['report']['validated_candidates'][0]
    candidate['quote'] = 'fabricated quote'
    candidate['grounding'].update(span=[999, 1000], matched_text='wrong')
    trace = {}
    assert stop_decision(meta, adapter.project(meta), trace=trace) is None
    assert trace['self_audit']['rejection_category'] == 'invalid_grounding'
