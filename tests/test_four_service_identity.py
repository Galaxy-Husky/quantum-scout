"""Offline official-format metadata receipts; no live services or semantic claims."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from citation_backends import (CitationBackend, CitationVerifier, identity_backends, expansion_backend,
                              lookup_identifiers, identifiers, title_similarity)

TITLE = 'Quantum key distribution'
DOI = '10.1234/fixture'
ARXIV = '2601.00001v2'


def run(coro):
    return asyncio.run(coro)


def feed(identifier=ARXIV, title=TITLE):
    return ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/' + identifier +
            '</id><title>' + title + '</title></entry></feed>')


def backend(name, response, **options):
    return CitationBackend(name, httpx.MockTransport(lambda request: response), **options)


def test_crossref_has_limited_coverage_and_identifier_binding():
    for status in (404, 429, 503):
        client = backend('crossref', httpx.Response(status, headers={'retry-after': '10'}))
        result = run(client.verify({'doi': '10.5281/zenodo.123'}, TITLE))
        assert result['state'] == 'unknown'
        assert result['reason'] == ('not_covered_by_crossref' if status == 404 else 'rate_limited' if status == 429 else 'http_503')
        assert len(client.requests) == 1
        assert client.requests[0]['retry_after'] == '10'
    for returned, state in [(DOI, 'verified'), ('10.1234/wrong', 'mismatch')]:
        client = backend('crossref', httpx.Response(200, json={'message': {'DOI': returned, 'title': [TITLE]}}))
        assert run(client.verify({'doi': DOI}, TITLE))['state'] == state
    assert run(client.verify({}, TITLE))['state'] == 'unknown'
    assert run(client.verify({}, TITLE))['reason'] == 'no_identifier'


def test_arxiv_id_lookup_retains_versions_and_rejects_invalid_feeds():
    assert lookup_identifiers('https://arxiv.org/pdf/2601.00001v2.pdf') == {'arxiv': ARXIV}
    assert identifiers('https://arxiv.org/pdf/2601.00001v2.pdf') == {'arxiv': '2601.00001'}
    for returned, state in [(ARXIV, 'verified'), ('2601.00001v1', 'mismatch'), ('2601.00002v2', 'mismatch')]:
        client = backend('arxiv', httpx.Response(200, text=feed(returned)))
        result = run(client.verify({'arxiv': ARXIV}, TITLE))
        assert result['state'] == state
        assert result['version'] == returned[-2:]
        assert 'id_list=2601.00001v2' in client.requests[0]['request_url']
        assert 'search_query' not in client.requests[0]['request_url']
    for text, reason in [('<feed xmlns="http://www.w3.org/2005/Atom"/>', 'not_indexed_by_provider'),
                         ('<html>bad</html>', 'invalid_response'), ('<feed', 'invalid_response')]:
        assert run(backend('arxiv', httpx.Response(200, text=text)).verify({'arxiv': ARXIV}, TITLE))['reason'] == reason


def test_service_allowlist_selection_and_disagreement():
    responses = {
        'crossref': httpx.Response(200, json={'message': {'DOI': DOI, 'title': [TITLE]}}),
        'arxiv': httpx.Response(200, text=feed()),
        'semantic_scholar': httpx.Response(200, json={'paperId': 'p', 'title': TITLE, 'externalIds': {'DOI': DOI}}),
        'openalex': httpx.Response(200, json={'id': 'https://openalex.org/W1', 'title': TITLE, 'doi': 'https://doi.org/' + DOI})}
    calls = []
    def factory(name):
        calls.append(name)
        return backend(name, responses[name])
    enabled = list(responses)
    result = run(CitationVerifier(enabled, factory).verify({'doi': DOI, 'arxiv': ARXIV}, TITLE))
    assert result['cross_check'] == 'cross_check_verified'
    assert calls == ['crossref', 'arxiv']  # No fourfold polling on successful primaries.
    calls.clear()
    responses['crossref'] = httpx.Response(404)
    result = run(CitationVerifier(enabled, factory).verify({'doi': DOI}, TITLE))
    assert result['state'] == 'verified'
    assert result['cross_check'] == 'cross_check_partial'
    assert calls == ['crossref', 'semantic_scholar']
    responses['crossref'] = httpx.Response(200, json={'message': {'DOI': DOI, 'title': ['Tomato farming']}})
    result = run(CitationVerifier(enabled, factory).verify({'doi': DOI}, TITLE))
    assert result['state'] == 'mismatch'
    assert result['cross_check'] == 'cross_check_conflict'
    assert [c['state'] for c in result['checks']] == ['mismatch', 'verified']
    calls.clear()
    result = run(CitationVerifier([], factory).verify({'doi': DOI}, TITLE))
    assert result['state'] == 'unknown' and result['reason'] == 'backend_disabled' and calls == []
    result = run(CitationVerifier(['arxiv'], factory).verify({'doi': DOI}, TITLE))
    assert result['reason'] == 'unsupported_identifier' and calls == []


def test_cross_service_titles_are_compared_without_expected_title():
    def factory(name):
        response = (httpx.Response(200, json={'message': {'DOI': DOI, 'title': [TITLE]}})
                    if name == 'crossref' else httpx.Response(200, text=feed(title='Tomato farming')))
        return backend(name, response)
    result = run(CitationVerifier(['crossref', 'arxiv'], factory).verify({'doi': DOI, 'arxiv': ARXIV}))
    assert result['cross_check'] == 'cross_check_conflict'


def test_invalid_payload_receipt_is_failed_and_cached_without_losing_budget():
    store, calls, persisted = {}, [], []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'unexpected': 'payload'})
    def create():
        return CitationBackend('crossref', httpx.MockTransport(handler), request_store=store,
                               notify=lambda key, record: persisted.append(dict(record)))
    first = create()
    assert run(first.verify({'doi': DOI}, TITLE))['reason'] == 'invalid_response'
    assert first.requests[0]['status_code'] == 200
    assert first.requests[0]['status'] == persisted[-1]['status'] == 'failed'
    second = create()
    assert run(second.verify({'doi': DOI}, TITLE))['reason'] == 'invalid_response'
    assert len(calls) == 1 and second.requests[0]['budget_consumed'] == 0
    assert next(iter(store.values()))['budget_consumed'] == 1


def test_expansion_missing_result_container_is_failed_not_empty():
    from citation_backends import CitationRequestError
    for payload in ([], None, {}, {'data': 'malformed'}):
        client = backend('semantic_scholar', httpx.Response(200, json=payload))
        with pytest.raises(CitationRequestError, match='invalid_response'):
            run(client.expand({'doi': DOI}))
        assert len(client.requests) == 1 and client.requests[0]['status'] == 'failed'
    # A declared, empty result container is an actual empty success.
    client = backend('semantic_scholar', httpx.Response(200, json={'data': []}))
    with patch('citation_backends.asyncio.sleep'):
        assert run(client.expand({'doi': DOI})) == []
    assert len(client.requests) == 2 and all(r['status']=='succeeded' for r in client.requests)


def test_openalex_preserves_metadata_when_one_expansion_direction_fails(monkeypatch):
    from citation_backends import CitationRequestError
    monkeypatch.setenv('OPENALEX_API_KEY','offline-placeholder-not-a-real-key')
    for failed_direction in ('references','citations','both'):
        def handler(request):
            direction = 'references' if request.url.path.endswith('/W2') else 'citations' if request.url.path=='/works' else 'root'
            if direction == failed_direction or failed_direction=='both' and direction!='root':
                return httpx.Response(503)
            if direction=='root':
                return httpx.Response(200,json={'id':'https://openalex.org/W1','referenced_works':['https://openalex.org/W2']})
            paper={'id':'https://openalex.org/W2','title':TITLE,'doi':'https://doi.org/'+DOI}
            return httpx.Response(200,json={'results':[paper]} if direction=='citations' else paper)
        client=CitationBackend('openalex',httpx.MockTransport(handler))
        with patch('citation_backends.asyncio.sleep'):
            if failed_direction=='both':
                with pytest.raises(CitationRequestError,match='http_503'):
                    run(client.expand({'doi':DOI}))
            else:
                hits=run(client.expand({'doi':DOI}))
                assert len(hits)==1 and hits[0]['relation']==('citation' if failed_direction=='references' else 'reference')
        assert len(client.requests)==3
        assert any(r['status']=='failed' for r in client.requests)


def test_receipts_cache_failure_latch_and_secret_redaction(monkeypatch):
    monkeypatch.setenv('OPENALEX_API_KEY', 'private-openalex-key')
    monkeypatch.setenv('S2_API_KEY', 'private-s2-key')
    store, charges, actual = {}, [], []
    def handler(request):
        actual.append(request)
        return httpx.Response(200, json={'id': 'W1', 'doi': 'https://doi.org/' + DOI, 'title': TITLE, 'echo': 'private-openalex-key'})
    def create():
        return CitationBackend('openalex', httpx.MockTransport(handler), request_store=store,
                               charge=lambda: charges.append(1))
    first = create()
    assert run(first.verify({'doi': DOI}, TITLE))['state'] == 'verified'
    second = create()
    assert run(second.verify({'doi': DOI}, 'Tomato farming'))['state'] == 'mismatch'
    assert len(actual) == len(charges) == 1
    assert second.requests[0]['reused'] and second.requests[0]['budget_consumed'] == 0
    saved = json.dumps(store)
    assert 'private-openalex-key' not in saved and 'private-s2-key' not in saved
    assert first.requests[0]['response_sha256'] and first.requests[0]['response_body_redacted']
    assert 'api_key' not in first.requests[0]['request_url']
    latch = {}
    one = backend('semantic_scholar', httpx.Response(429), request_store=latch)
    assert run(one.verify({'doi': DOI}, TITLE))['reason'] == 'rate_limited'
    two = backend('semantic_scholar', httpx.Response(200), request_store=latch)
    assert run(two.verify({'doi': '10.1234/other'}, TITLE))['reason'] == 'service_paused_after_429'
    assert two.requests == []


def test_arxiv_pacing_and_interrupted_request_reuse():
    store = {}
    async def scenario():
        with patch('citation_backends.asyncio.sleep') as wait:
            client = backend('arxiv', httpx.Response(200, text=feed()), request_store=store)
            await client.verify({'arxiv': ARXIV}, TITLE)
            await client.verify({'arxiv': '2601.00002v2'}, TITLE)
            assert wait.await_args_list[-1].args[0] > 3
        saved = next(iter(store.values()))
        saved['status'] = 'started'
        other = backend('arxiv', httpx.Response(200, text=feed()), request_store=store)
        assert (await other.verify({'arxiv': ARXIV}, TITLE))['reason'] == 'process_interrupted'
        assert other.requests[0]['reused']
    run(scenario())


def test_config_default_compatibility_and_ambiguity(tmp_path):
    from searchos_online import read_config
    cases = {'TEST-0001': {'description': 'Synthetic offline case'}}
    path = tmp_path / 'config.json'
    for extra, selected in [({}, []), ({'citation_backend': 'semantic_scholar'}, ['semantic_scholar']),
                            ({'citation_identity': {'enabled': ['crossref', 'arxiv']}}, ['crossref', 'arxiv'])]:
        path.write_text(json.dumps({'cases': cases, **extra}))
        config = read_config(path)
        assert identity_backends(config) == selected
    for extra in [ {'citation_identity': {'enabled': ['bad']}}, {'citation_identity': {'enabled': ['arxiv', 'arxiv']}},
                   {'citation_backend': 'openalex', 'citation_identity': {'enabled': []}},
                   {'max_citation_requests': False}, {'citation_expansion_backend': 'crossref'}]:
        path.write_text(json.dumps({'cases': cases, **extra}))
        with pytest.raises(ValueError): read_config(path)
    assert expansion_backend({'citation_backend': 'openalex'}) == 'openalex'
    assert expansion_backend({'citation_identity': {'enabled': ['openalex']}}) == 'none'


def test_runner_persistent_budget_and_conflict_gate():
    from test_searchos_online import OnlineTests, Model
    from searchos_online import OnlineRunner
    import searchos_adapter as adapter
    for status, returned, expected_filled in [(200, TITLE, 1), (200, 'Tomato farming', 0), (404, '', 1), (429, '', 1)]:
        fixture = OnlineTests(); fixture.setUp()
        try:
            fixture.config.update(citation_identity={'enabled': ['crossref']}, max_citation_requests=1)
            client = backend('crossref', httpx.Response(status, json={'message': {'DOI': DOI, 'title': [returned]}}))
            models = {'extraction': Model(fixture.extraction), 'judge': Model(fixture.judgment), 'orchestrator': Model({'query': 'fixture'})}
            runner = OnlineRunner(fixture.path, fixture.config, models=models, providers={'serper': fixture.provider},
                                  opener=fixture.opener, extractor=fixture.extractor, citations=client)
            result = run(runner.run(known_url='https://doi.org/' + DOI, case_id='TEST-0001', expected_title=TITLE))
            assert result['coverage']['filled'] == expected_filled
            meta = adapter.load(fixture.path)
            saved = list(meta['online']['citation_requests'].values())
            assert len(saved) == 1 and saved[0]['budget_consumed'] == 1
            batch = json.loads((fixture.path/'calibration/batch.json').read_text())
            assert batch['quality']['citation_identity']['requests_consumed'] == 1
            if status in (404,429):
                assert any(w['category'] == 'citation_unverified' for w in batch['quality']['warnings'])
            if not expected_filled:
                assert batch['grounding_failures'][0]['failure_type'] == 'citation_mismatch'
            # New runner resumes the same adapter-owned request budget, not a process-local counter.
            next_runner = OnlineRunner(fixture.path, fixture.config, providers={'serper': fixture.provider}, citations=client)
            check = run(next_runner.citation_client('crossref').verify({'doi': '10.1234/second'}, TITLE))
            assert check['state'] == 'unknown'
            assert check['reason'] in {'request_budget_exhausted','service_paused_after_429'}
            assert len(adapter.load(fixture.path)['online']['citation_requests']) == 1
        finally:
            fixture.doCleanups()


def test_incomplete_aggregator_identity_cannot_verify_by_title_only():
    for name, data in [('semantic_scholar', {'paperId': 'p', 'title': TITLE}),
                       ('openalex', {'id': 'W1', 'title': TITLE})]:
        with patch.dict('os.environ', {'OPENALEX_API_KEY': 'fixture-key'}):
            result = run(backend(name, httpx.Response(200, json=data)).verify({'doi': DOI}, TITLE))
        assert result['state'] == 'unknown' and result['reason'] == 'identifier_unverified'
    data = {'paperId': 'p', 'title': TITLE, 'externalIds': {'ArXiv': '2601.00001'}}
    result = run(backend('semantic_scholar', httpx.Response(200, json=data)).verify({'arxiv': ARXIV}, TITLE))
    assert result['state'] == 'unknown' and result['reason'] == 'version_unverified'


def test_multiple_service_conflict_reaches_graph_export_and_renderer():
    from test_searchos_online import OnlineTests, Model
    from searchos_online import OnlineRunner
    import searchos_adapter as adapter
    fixture = OnlineTests(); fixture.setUp()
    original = CitationBackend.__init__
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.host == 'api.crossref.org':
            return httpx.Response(200, json={'message': {'DOI': DOI, 'title': [TITLE]}})
        return httpx.Response(200, text=feed(title='Tomato farming'))
    transport = httpx.MockTransport(handle)
    def construct(self, name, transport=None, **kw):
        original(self, name, transport or transport_for_test, **kw)
    transport_for_test = transport
    try:
        fixture.config.update(citation_identity={'enabled': ['crossref','arxiv']})
        models = {'extraction': Model(fixture.extraction), 'judge': Model(fixture.judgment), 'orchestrator': Model({'query': 'fixture'})}
        runner = OnlineRunner(fixture.path, fixture.config, models=models, providers={'serper': fixture.provider},
                              opener=fixture.opener, extractor=fixture.extractor)
        meta = adapter.load(fixture.path)
        meta['online'] = {'config': fixture.config, 'sources': {}, 'events': [], 'searches': {},
                          'assessments': {}, 'attempted_tasks': [], 'invocations': []}
        adapter.persist(fixture.path, meta)
        with patch.object(CitationBackend, '__init__', construct):
            source = run(runner.source('https://doi.org/' + DOI, {'target_cells': []},
                                hit={'identifiers': {'arxiv': ARXIV}, 'title': TITLE}))
        assert source['citation_identity']['cross_check'] == 'cross_check_conflict'
        result = run(runner.run(known_url='https://doi.org/' + DOI, case_id='TEST-0001', expected_title=TITLE))
        assert result['coverage']['filled'] == 0
        batch = json.loads((fixture.path/'calibration/batch.json').read_text())
        assert any(w['category'] == 'cross_check_conflict' for w in batch['quality']['warnings'])
        assert batch['grounding_failures'][0]['failure_type'] == 'citation_mismatch'
        assert len(batch['sources'][0]['citation_identity']['checks']) == 2
        assert len(seen) == 2
    finally:
        fixture.doCleanups()


def test_expansion_keeps_partial_metadata_and_failed_endpoint_receipts():
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path.endswith('/references'):
            return httpx.Response(200, json={'data': [{'citedPaper': {'paperId': 'p', 'title': TITLE,
                            'externalIds': {'DOI': DOI}}}]})
        return httpx.Response(429, headers={'retry-after': '11'})
    client = CitationBackend('semantic_scholar', httpx.MockTransport(handle))
    with patch('citation_backends.asyncio.sleep'):
        hits = run(client.expand({'doi': DOI}))
    assert len(hits) == 1
    assert len(calls) == 2 and client.requests[-1]['status'] == 'failed'
    assert client.requests[-1]['retry_after'] == '11'
    with patch('citation_backends.asyncio.sleep'):
        assert run(client.expand({'doi': DOI})) == hits
    assert len(calls) == 2
