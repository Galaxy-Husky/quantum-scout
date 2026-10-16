#!/usr/bin/env python3
"""Opt-in real API contract probes, no LLMs. Not collected by default pytest."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import httpx
from citation_backends import CitationBackend, title_similarity
from searchos_network import make_provider


class ProbeBudget(RuntimeError):
    pass


def validate_probes(config):
    if not isinstance(config, dict) or set(config) != {'probes'} or not isinstance(config['probes'], list) or not config['probes']:
        raise ValueError('Expected an object containing a nonempty probes list')
    for probe in config['probes']:
        if not isinstance(probe, dict):
            raise ValueError('Each probe must be an object')
        if probe.get('kind') == 'search':
            if (set(probe) - {'kind', 'provider', 'query', 'max_results', 'expected_count', 'expected_title'} or
                    probe.get('provider') not in {'serper', 'tavily'} or
                    not isinstance(probe.get('query'), str) or not probe['query'].strip() or
                    type(probe.get('max_results')) is not int or not 1 <= probe['max_results'] <= 10 or
                    type(probe.get('expected_count')) is not int or
                    not 0 <= probe['expected_count'] <= probe['max_results']):
                raise ValueError('search requires provider, query, max_results (1..10), expected_count')
            key = probe['provider'].upper() + '_API_KEY'
            if not os.environ.get(key):
                raise ValueError('Explicit credential required: ' + key)
        elif probe.get('kind') == 'citation':
            if (set(probe) - {'kind', 'backend', 'ids', 'expected_title', 'expected_state'} or
                    probe.get('backend') not in {'semantic_scholar', 'openalex', 'crossref', 'arxiv'} or
                    not isinstance(probe.get('ids'), dict) or not probe['ids'] or
                    set(probe['ids']) - {'doi', 'arxiv'} or
                    any(not isinstance(v, str) or not v.strip() for v in probe['ids'].values()) or
                    probe.get('expected_state') not in {'verified', 'mismatch', 'unknown'}):
                raise ValueError('citation requires a backend, identifiers and expected_state')
            if probe['backend'] in {'openalex', 'crossref'} and not probe['ids'].get('doi'):
                raise ValueError('Selected backend requires a DOI')
            if probe['backend'] == 'arxiv' and not probe['ids'].get('arxiv'):
                raise ValueError('arXiv backend requires an arXiv ID')
            key = 'OPENALEX_API_KEY' if probe['backend'] == 'openalex' else 'S2_API_KEY'
            if probe['backend'] == 'openalex' and not os.environ.get(key):
                raise ValueError('Explicit credential required: ' + key)
        else:
            raise ValueError('Supported probe kinds: search, citation')
        if 'expected_title' in probe and (not isinstance(probe['expected_title'], str) or not probe['expected_title'].strip()):
            raise ValueError('expected_title must be nonblank')


async def run_probes(config, output, max_requests, max_seconds, *, transport=None):
    validate_probes(config)
    if type(max_requests) is not int or max_requests < 1 or max_seconds <= 0:
        raise ValueError('Explicit positive request and time budgets required')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    requests, results, throttled = [], [], set()
    deadline = started + max_seconds
    async def before(request):
        if len(requests) >= max_requests or time.monotonic() >= deadline:
            raise ProbeBudget('Request or time budget exhausted')
        service = request.url.host
        if service in throttled:
            raise ProbeBudget('Service paused after rate limit')
        requests.append({'method': request.method,
            'endpoint': str(request.url.copy_remove_param('api_key')), 'status': 'started'})
    async def after(response):
        row = requests[-1]
        row.update(status='received', status_code=response.status_code)
        if response.status_code == 429:
            throttled.add(response.request.url.host)
            row['retry_after'] = response.headers.get('retry-after')
        body = await response.aread()
        sha = hashlib.sha256(body).hexdigest()
        row['response_sha256'] = sha
        if len(body) <= 2_000_000:
            (output / (sha + '.response')).write_bytes(body)
        else:
            row['body_saved'] = False
    original = httpx.AsyncClient
    def client(**kwargs):
        kwargs['event_hooks'] = {'request': [before], 'response': [after]}
        if transport is not None:
            kwargs['transport'] = transport
        return original(**kwargs)
    with patch.object(httpx, 'AsyncClient', side_effect=client):
        for index, probe in enumerate(config['probes']):
            service = (('google.serper.dev' if probe['provider'] == 'serper' else 'api.tavily.com')
                       if probe['kind'] == 'search' else
                       {'openalex': 'api.openalex.org', 'semantic_scholar': 'api.semanticscholar.org',
                        'crossref': 'api.crossref.org', 'arxiv': 'export.arxiv.org'}[probe['backend']])
            row = {'index': index, 'kind': probe['kind'], 'service': service}
            results.append(row)
            if service in throttled:
                row.update(status='blocked', reason='Service paused after 429')
                continue
            offset = len(requests)
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or len(requests) >= max_requests:
                    raise ProbeBudget('Request or time budget exhausted')
                async with asyncio.timeout(remaining):
                    if probe['kind'] == 'search':
                        hits = await make_provider(probe['provider']).search(probe['query'], probe['max_results'])
                        passed = len(hits) == probe['expected_count']
                        if probe.get('expected_title'):
                            passed &= any(title_similarity(hit.title, probe['expected_title']) >= .70 for hit in hits)
                        row.update(count=len(hits), urls=[hit.url for hit in hits], titles=[hit.title for hit in hits])
                    else:
                        backend = CitationBackend(probe['backend'])
                        result = await backend.verify(probe['ids'], probe.get('expected_title'))
                        row['identity'] = result
                        row['backend_requests'] = backend.requests
                        passed = result['state'] == probe['expected_state']
                        # Availability failures never count as successful live validation.
                        passed &= not any(r['status'] == 'failed' for r in backend.requests)
                row['status'] = 'passed' if passed else 'failed'
            except Exception as exc:
                # Native search SDKs can raise their own error classes. Preserve
                # the receipt and failure classification without logging secrets.
                row.update(status='blocked' if isinstance(exc, (ProbeBudget, TimeoutError)) else 'failed',
                           error_type=type(exc).__name__)
            for request in requests[offset:]:
                if request['status'] == 'started':
                    request.update(status='failed', error_type=row.get('error_type', 'NoResponse'))
            row['request_range'] = [offset, len(requests)]
    report = {'scope': 'API contracts only; no LLM or semantic quality validation',
              'max_requests': max_requests, 'max_seconds': max_seconds,
              'elapsed_seconds': time.monotonic() - started, 'requests': requests, 'probes': results,
              'passed': all(row['status'] == 'passed' for row in results)}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--max-requests', type=int, required=True)
    parser.add_argument('--max-seconds', type=int, required=True)
    args = parser.parse_args()
    if not args.allow_live:
        parser.error('Live requests require --allow-live and explicit request/time budgets')
    try:
        if args.env_file:
            if not args.env_file.is_file():
                raise ValueError('env file does not exist')
            from dotenv import load_dotenv
            load_dotenv(args.env_file, override=False)
        config = json.loads(args.config.read_text())
        report = asyncio.run(run_probes(config, args.output, args.max_requests, args.max_seconds))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({'passed': report['passed'], 'report': str(args.output / 'report.json')}))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
