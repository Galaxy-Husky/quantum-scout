"""Observable resource boundaries and recovery, entirely offline."""
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from citation_backends import CitationBackend, CitationRequestError, MAX_METADATA_BYTES
from searchos_online import budget_diagnostics, DEFAULTS


def test_metadata_transport_retry_is_one_budgeted_persistent_attempt():
    store, charges, seen = {}, [], []
    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            raise httpx.ReadTimeout('synthetic transport outage')
        return httpx.Response(200, json={'message': {'DOI': '10.1234/test', 'title': ['Quantum key distribution']}})
    def client():
        return CitationBackend('crossref', httpx.MockTransport(handler), request_store=store,
                               charge=lambda: charges.append(1))
    with patch('citation_backends.asyncio.sleep'):
        first = client()
        result = asyncio.run(first.verify({'doi': '10.1234/test'}, 'Quantum key distribution'))
        assert result['state'] == 'verified'
        assert len(seen) == len(charges) == len(store) == 2
        assert first.requests[0]['status'] == 'failed' and first.requests[0]['retry_recovered']
        assert first.requests[1]['attempt'] == 2 and first.requests[1]['retry_of']
        assert asyncio.run(client().verify({'doi': '10.1234/test'}, 'Quantum key distribution'))['state'] == 'verified'
    assert len(seen) == len(charges) == 2


def test_retry_exhaustion_and_budget_do_not_loop_on_resume():
    for budget in (1, 2):
        store, seen = {}, []
        def handler(request):
            seen.append(request)
            raise httpx.ConnectError('synthetic')
        def charge():
            if len(store) >= budget: raise CitationRequestError('request_budget_exhausted')
        def client(): return CitationBackend('crossref', httpx.MockTransport(handler), request_store=store, charge=charge)
        with patch('citation_backends.asyncio.sleep'):
            for _ in range(3):
                result = asyncio.run(client().verify({'doi': '10.1234/test'}, 'Title'))
                assert result['state'] == 'unknown'
        assert len(seen) == len(store) == budget
        assert result['reason'] == ('request_budget_exhausted' if budget == 1 else 'transport_error')
    for status in (404, 429, 500):
        service = CitationBackend('crossref', httpx.MockTransport(lambda _: httpx.Response(status)))
        asyncio.run(service.verify({'doi': '10.1234/test'}, 'Title'))
        assert len(service.requests) == 1


def test_metadata_payload_boundary_is_bounded_and_not_retried():
    service = CitationBackend('crossref', httpx.MockTransport(lambda _:
            httpx.Response(200, content=b'x' * (MAX_METADATA_BYTES + 1))))
    result = asyncio.run(service.verify({'doi': '10.1234/test'}, 'Title'))
    assert result['state'] == 'unknown' and result['reason'] == 'response_too_large'
    assert len(service.requests) == 1
    receipt = service.requests[0]
    assert receipt['response_truncated'] and receipt['response_hash_scope'] == 'received_prefix'
    assert len(receipt['response_body']) == MAX_METADATA_BYTES


def test_cache_download_includes_equal_byte_boundary_and_http_errors_do_not_retry(tmp_path):
    import download_source
    from email.message import Message
    from urllib.error import HTTPError
    headers = Message(); headers['content-type'] = 'application/pdf'
    class Response(io.BytesIO):
        def __init__(self, size): super().__init__(b'x'*size); self.headers = headers
    for size, exitcode in [(9, 0), (10, 0), (11, 2)]:
        args = ['download_source', '--workspace', str(tmp_path/str(size)), '--source-id', 'fixture',
                '--url', 'https://fixture.example/body', '--max-bytes', '10']
        with patch.object(sys, 'argv', args), patch.object(download_source, 'urlopen', return_value=Response(size)), redirect_stdout(io.StringIO()):
            assert download_source.main() == exitcode
    args = ['download_source', '--workspace', str(tmp_path/'http'), '--source-id', 'fixture', '--url', 'https://fixture.example/body']
    with patch.object(sys, 'argv', args), patch.object(download_source, 'urlopen', side_effect=HTTPError(args[-1],429,'limited',{},None)) as calls, redirect_stdout(io.StringIO()):
        assert download_source.main() == 2 and calls.call_count == 1
    for option, value in [('--max-bytes','0'), ('--retries','-1'), ('--retries','2')]:
        with patch.object(sys,'argv',args+[option,value]), pytest.raises(SystemExit) as exc:
            download_source.main()
        assert exc.value.code == 2


def test_html_parse_deadline_cancels_without_committing_source(tmp_path):
    import searchos_network as network
    async def download(url): return b'not a PDF', 'text/html', url
    def parser(*args):
        time.sleep(.04)
        return [{'location':'paragraph:1','text':'x'*200}]
    async def scenario():
        with patch.object(network,'download',download), patch.object(network,'source_segments',parser):
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(network.open_source('https://fixture.example/body',tmp_path,'test'),.01)
        await asyncio.sleep(.05)
    asyncio.run(scenario())
    assert not list(tmp_path.iterdir())


def test_pdf_parser_cancellation_reaps_child_and_commits_no_source(tmp_path):
    import searchos_network as network
    class Process:
        returncode = None
        killed = False
        calls = 0
        async def communicate(self):
            self.calls += 1
            if not self.killed: await asyncio.sleep(10)
            return b'', b''
        def kill(self): self.killed=True; self.returncode=-9
    process=Process()
    async def create(*a, **kw): return process
    async def download(url): return b'%PDF-fake', 'application/pdf', url
    async def scenario():
        with patch.object(network,'download',download), patch.object(network.shutil,'which',return_value='/fake/pdftotext'), patch.object(network.asyncio,'create_subprocess_exec',create):
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(network.open_source('https://fixture.example/body',tmp_path,'test'),.01)
    asyncio.run(scenario())
    assert process.killed and process.calls == 2
    assert not list(tmp_path.iterdir())


def test_explicit_small_budgets_remain_supported_and_disclose_partial_scope():
    hints = {h['type'] for h in budget_diagnostics({**DEFAULTS, 'max_model_calls':8, 'max_rounds':2})}
    assert {'partial_definition_budget','partial_track_rounds','stall_window_spans_resumes'} <= hints
    assert not any(h['type']=='partial_definition_budget' for h in budget_diagnostics(DEFAULTS))


def test_new_implicit_budget_can_schedule_both_tracks_without_changing_explicit_limits(tmp_path):
    from schema_generator import domain_config
    from searchos_online import read_config
    config = domain_config(Path(__file__).resolve().parents[1] / 'config')
    tables = 1 + len(config['tracks']) * 2
    # Best-case one extraction per table and two independent reviews per cell.
    cells = len(config['fields']) + sum(len(t['admission_criteria']) + len(t['scoring_dimensions'])
                                       for t in config['tracks'].values())
    assert DEFAULTS['max_rounds'] >= tables
    assert DEFAULTS['max_model_calls'] >= tables + cells * 2
    path = tmp_path/'config.json'
    path.write_text(json.dumps({'cases':{'TEST-0001':{'description':'fixture'}},
                               'max_model_calls':8,'max_rounds':2,'max_seconds':300}))
    with patch('searchos_configuration.search_provider_name',return_value='serper'):
        actual = read_config(path)
    assert (actual['max_model_calls'],actual['max_rounds'],actual['max_seconds']) == (8,2,300)


def test_custom_score_threshold_reaches_export_acceptance_and_failure_text():
    from validate_batch import accepted_cases, accepted_tracks
    from render_calibration import failure_context
    evaluation={'passed_admission':True,'score_normalized':17}
    case={'case_id':'TEST-0001','tracks':{'quantum-security':evaluation}}
    config={'tracks':{'quantum-security':{'min_total_score':20}}}
    assert accepted_tracks(case) == ['quantum-security']  # Legacy read-only fallback.
    assert accepted_tracks(case,config) == []
    assert accepted_cases({'cases':[case],'config_snapshot':config}) == []
    assert '评分失败' in failure_context(evaluation,20)
