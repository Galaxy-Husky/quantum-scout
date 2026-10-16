"""Bounded citation metadata discovery; metadata is never research evidence."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
import xml.etree.ElementTree as ET

import hashlib
import os
import re
import unicodedata
from urllib.parse import quote, unquote, urlparse

import httpx


def identifiers(url):
    parsed = urlparse(url)
    if parsed.hostname in {'doi.org', 'dx.doi.org'}:
        value = unquote(parsed.path.lstrip('/')).lower()
        if re.fullmatch(r'10\.\d{4,9}/\S+', value):
            return {'doi': value}
    if parsed.hostname in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
        # Only allowlisted hosts and complete identifier paths establish aliases.
        # This is discovery identity; explicitly opened bodies keep their own IDs.
        path = re.sub(r'/+', '/', unquote(parsed.path)).rstrip('/')
        match = re.fullmatch(r'/(?:abs|pdf|html)/(.+?)(?:\.pdf)?', path, re.IGNORECASE)
        if match:
            value = re.sub(r'v\d+$', '', match[1], flags=re.IGNORECASE).lower()
            if re.fullmatch(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})', value):
                return {'arxiv': value}
    return {}


def identity(url):
    ids = identifiers(url)
    return next((k + ':' + v for k, v in ids.items()), url)


def aliases(hit):
    result = {identity(hit['url'])}
    result.update(k + ':' + v.lower() if k == 'doi' else k + ':' + v
                  for k, v in hit.get('identifiers', {}).items() if v)
    return result


def title_similarity(left, right):
    """Normalized edit similarity, 1 - distance/max length; no new dependency."""
    def normalize(value):
        return ' '.join(''.join(c if c.isalnum() else ' ' for c in
                               unicodedata.normalize('NFKC', value).casefold()).split())
    left, right = normalize(left), normalize(right)
    if not left or not right:
        return 0.0
    if len(left) > 4000 or len(right) > 4000:
        raise ValueError('Title exceeds bounded comparison size')
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return 1 - previous[-1] / max(len(left), len(right))


MAX_METADATA_BYTES = 2_000_000
BACKENDS = ('crossref', 'arxiv', 'semantic_scholar', 'openalex')


def normalize_title(value):
    # Bibliographic comparison only; never used by the body grounding gate.
    return ' '.join(''.join(c if c.isalnum() else ' ' for c in
                           unicodedata.normalize('NFKC', value).casefold()).split())


def lookup_identifiers(url):
    ids = identifiers(url)
    if 'arxiv' in ids:
        path = unquote(urlparse(url).path).rstrip('/')
        match = re.search(r'(v\d+)(?:\.pdf)?$', path, re.I)
        if match:
            ids['arxiv'] += match[1].lower()
    return ids


def valid_identifiers(ids):
    if not isinstance(ids, dict):
        raise ValueError('Identifiers must be an object')
    result = {}
    for key, value in ids.items():
        if key not in {'doi', 'arxiv'} or not isinstance(value, str):
            raise ValueError('Only DOI/arXiv identifiers are accepted')
        value = value.strip().lower()
        pattern = (r'10\.\d{4,9}/\S+' if key == 'doi' else
                   r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?')
        if not re.fullmatch(pattern, value):
            raise ValueError('Invalid ' + key + ' identifier')
        result[key] = value
    return result


def identity_backends(config):
    policy = config.get('citation_identity')
    if policy is not None:
        return list(policy['enabled'])
    name = config.get('citation_backend', 'none')
    return [] if name == 'none' else [name]


def expansion_backend(config):
    name = config.get('citation_expansion_backend', 'inherit')
    if name != 'inherit':
        return name
    legacy = config.get('citation_backend', 'none')
    return legacy if config.get('citation_identity') is None and legacy in {'semantic_scholar', 'openalex'} else 'none'


def backend_capabilities(name):
    return {'backend': name, 'identifiers': {'openalex': ['doi'], 'crossref': ['doi'],
            'arxiv': ['arxiv'], 'semantic_scholar': ['doi', 'arxiv'], 'none': []}[name],
            'key_requirement': {'openalex': 'OPENALEX_API_KEY', 'crossref': None, 'arxiv': None,
                                'semantic_scholar': 'S2_API_KEY (optional)', 'none': None}[name],
            'expansion': name in {'semantic_scholar', 'openalex'},
            'citation_unverified_warning': name != 'none'}


class CitationRequestError(Exception):
    pass


class CitationBackend:
    """Official endpoints, local receipts; no hidden retries or title searches.

    request_store is an adapter-owned persistent mapping, including started requests.
    notify stores every mutation before/after IO; charge reserves one request first.
    """
    def __init__(self, name, transport=None, *, request_store=None, notify=None, charge=None):
        if name not in (*BACKENDS, 'none'):
            raise ValueError('Unknown citation backend')
        self.name, self.transport = name, transport
        self.requests = []
        self.request_store = request_store if request_store is not None else {}
        self.notify, self.charge = notify, charge

    def _invalid_response(self):
        """A successful HTTP exchange can still contain an unusable payload."""
        record = self.requests[-1]
        record.update(status='failed', reason='invalid_response')
        original = self.request_store.get(record.get('cache_key'))
        if original is not None:
            # A reused observation consumes zero; its original reservation remains one.
            original.update(status='failed', reason='invalid_response')
            if self.notify:
                self.notify(record['cache_key'], original)

    async def _get(self, url, params=None, purpose='citation_identity'):
        try:
            return await self._request(url, params, purpose, attempt=1)
        except CitationRequestError as exc:
            if str(exc) not in {'timeout', 'transport_error'}:
                raise
            first = self.requests[-1]
            # A distinct persistent attempt key bounds retries even after process restarts.
            retry_key = first['cache_key'] + ':retry:1'
            if retry_key not in self.request_store:
                await asyncio.sleep(1.0)
            body = await self._request(url, params, purpose, attempt=2)
            first['retry_recovered'] = True
            original = self.request_store[first['cache_key']]
            original['retry_recovered'] = True
            if self.notify:
                self.notify(first['cache_key'], original)
            return body

    async def _request(self, url, params=None, purpose='citation_identity', attempt=1):
        params = dict(params or {})
        # URL and parameters below are rebuilt from validated identifiers, never from API links.
        cache_key = hashlib.sha256(json.dumps([self.name, url, params], sort_keys=True).encode()).hexdigest()
        base_key = cache_key
        if attempt == 2:
            cache_key += ':retry:1'
        previous = self.request_store.get(cache_key)
        if previous:
            record = deepcopy(previous)
            record.update(reused=True, budget_consumed=0)
            self.requests.append(record)
            if previous.get('status') != 'succeeded':
                raise CitationRequestError(previous.get('reason', 'process_interrupted'))
            return record['response_body']
        if any(r.get('backend') == self.name and r.get('status_code') == 429
               for r in self.request_store.values()):
            raise CitationRequestError('service_paused_after_429')
        if self.name == 'openalex' and not os.environ.get('OPENALEX_API_KEY'):
            raise CitationRequestError('missing_api_key')
        if self.charge:
            self.charge()
        headers = {'User-Agent': 'quantum-scout/14 citation-metadata'}
        secrets = [os.environ.get(k, '') for k in ('OPENALEX_API_KEY', 'S2_API_KEY')]
        if self.name == 'openalex':
            if not os.environ.get('OPENALEX_API_KEY'):
                raise CitationRequestError('missing_api_key')
            params['api_key'] = os.environ['OPENALEX_API_KEY']
        elif self.name == 'semantic_scholar' and os.environ.get('S2_API_KEY'):
            headers['x-api-key'] = os.environ['S2_API_KEY']
        def redact(text):
            for secret in secrets:
                if secret:
                    text = text.replace(secret, '[REDACTED]').replace(quote(secret, safe=''), '[REDACTED]')
            return text
        # Persist the pacing anchor and reservation before waiting/IO, across resumes.
        record = {'backend': self.name, 'endpoint': url, 'request_url': str(httpx.URL(url, params={
            k: v for k, v in params.items() if k != 'api_key'})), 'status': 'started', 'purpose': purpose,
            'at': datetime.now(timezone.utc).isoformat(), 'started_epoch': time.time(), 'budget_consumed': 1,
                  'attempt': attempt, 'cache_key': cache_key, 'retry_of': base_key if attempt == 2 else None}
        self.requests.append(record)
        self.request_store[cache_key] = record
        if self.notify:
            self.notify(cache_key, record)
        started = time.monotonic()
        try:
            interval = 3.1 if self.name == 'arxiv' else 1.0
            last = max((r.get('finished_epoch', r.get('started_epoch', 0)) for r in self.request_store.values()
                        if r is not record and r.get('backend') == self.name), default=0)
            await asyncio.sleep(max(0, interval - (time.time() - last)))
            async with httpx.AsyncClient(timeout=20, transport=self.transport, follow_redirects=False) as client:
                async with client.stream('GET', url, params=params, headers=headers) as response:
                    record['status_code'] = response.status_code
                    if response.headers.get('retry-after'):
                        record['retry_after'] = redact(response.headers['retry-after'])
                    data = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        data.extend(chunk)
                        if len(data) > MAX_METADATA_BYTES:
                            prefix = bytes(data[:MAX_METADATA_BYTES])
                            decoded_prefix = prefix.decode('utf-8', errors='replace')
                            record.update(response_body=redact(decoded_prefix),
                                response_sha256=hashlib.sha256(prefix).hexdigest(),
                                response_truncated=True, response_hash_scope='received_prefix',
                                response_body_redacted=redact(decoded_prefix) != decoded_prefix)
                            raise CitationRequestError('response_too_large')
                    decoded = bytes(data).decode(response.encoding or 'utf-8', errors='replace')
                    record.update(response_sha256=hashlib.sha256(data).hexdigest(),
                        response_body=redact(decoded), response_encoding=response.encoding,
                        response_body_redacted=redact(decoded) != decoded, response_hash_scope='complete_response')
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise ValueError('Unexpected successful status')
            record['status'] = 'succeeded'
            return record['response_body']
        except BaseException as exc:
            status = record.get('status_code')
            reason = ('rate_limited' if status == 429 else
                      'not_covered_by_crossref' if status == 404 and self.name == 'crossref' else
                      'not_indexed_by_provider' if status == 404 else
                      'http_' + str(status) if status and status != 200 else
                      str(exc) if isinstance(exc, CitationRequestError) else
                      'process_interrupted' if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else
                      'timeout' if isinstance(exc, (httpx.TimeoutException, TimeoutError)) else
                      'transport_error' if isinstance(exc, httpx.TransportError) else 'invalid_response')
            record.update(status='failed', reason=reason, error_type=type(exc).__name__)
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            raise CitationRequestError(reason) from None
        finally:
            record.update(duration_seconds=time.monotonic() - started, finished_epoch=time.time())
            if self.notify:
                self.notify(cache_key, record)

    async def verify(self, ids, title=None):
        result = {'state': 'unknown', 'reason': 'no_identifier', 'backend': self.name}
        if self.name == 'none':
            return {**result, 'reason': 'backend_disabled'}
        try:
            ids = valid_identifiers(ids)
        except ValueError:
            return {**result, 'reason': 'invalid_identifier'}
        result['requested_identifiers'] = ids
        if not ids:
            return result
        supported = backend_capabilities(self.name)['identifiers']
        kind = next((k for k in ('doi', 'arxiv') if k in ids and k in supported), None)
        if kind is None:
            return {**result, 'reason': 'unsupported_identifier'}
        value = ids[kind]
        result['identifier'] = {kind: value}
        offset = len(self.requests)
        try:
            if self.name == 'crossref':
                body = await self._get('https://api.crossref.org/works/' + quote(value, safe=''))
                data = json.loads(body)['message']
                if not isinstance(data.get('title'), list) or not data['title']:
                    raise ValueError('Expected title list')
                returned = data['title'][0]
                canonical = data['DOI']
                returned_ids = {'doi': canonical.lower()}
            elif self.name == 'arxiv':
                body = await self._get('https://export.arxiv.org/api/query', {'id_list': value, 'max_results': 1})
                feed = ET.fromstring(body)
                if feed.tag != '{http://www.w3.org/2005/Atom}feed':
                    raise ValueError('Expected Atom feed')
                entries = feed.findall('{http://www.w3.org/2005/Atom}entry')
                if not entries:
                    return {**result, 'reason': 'not_indexed_by_provider'}
                if len(entries) != 1:
                    raise ValueError('Expected one identity')
                entry = entries[0]
                returned = entry.findtext('{http://www.w3.org/2005/Atom}title')
                canonical = entry.findtext('{http://www.w3.org/2005/Atom}id')
                returned_ids = lookup_identifiers(canonical or '')
                if not returned_ids:
                    raise ValueError('Invalid arXiv entry')
            elif self.name == 'openalex':
                body = await self._get('https://api.openalex.org/works/https://doi.org/' + quote(value, safe='/'))
                data = json.loads(body)
                canonical, returned = data['id'], data['title']
                returned_ids = identifiers(data.get('doi') or '')
            else:
                body = await self._get('https://api.semanticscholar.org/graph/v1/paper/' +
                    quote(('DOI:' if kind == 'doi' else 'ARXIV:') + value, safe=''), {'fields': 'title,externalIds'})
                data = json.loads(body)
                canonical, returned = data['paperId'], data['title']
                external = data.get('externalIds') or {}
                returned_ids = {k: str(external[v]).lower() for k, v in [('doi', 'DOI'), ('arxiv', 'ArXiv')] if external.get(v)}
            if not isinstance(canonical, str) or not canonical or not isinstance(returned, str) or not returned.strip():
                raise ValueError('Incomplete provider identity')
            if '[REDACTED]' in json.dumps([canonical, returned, returned_ids]):
                return {**result, 'reason': 'response_redacted'}
            result.update(canonical_id=canonical, canonical_title=returned, normalized_title=normalize_title(returned),
                          returned_identifiers=returned_ids, identifier_found=True,
                          version=re.search(r'v\d+$', returned_ids.get('arxiv', ''))[0]
                          if re.search(r'v\d+$', returned_ids.get('arxiv', '')) else None)
            actual = returned_ids.get(kind)
            if actual:
                matches = (actual == value if kind == 'doi' or re.search(r'v\d+$', value)
                           else re.sub(r'v\d+$', '', actual) == value)
                if not matches and kind == 'arxiv' and re.sub(r'v\d+$', '', actual) == re.sub(r'v\d+$', '', value) and not re.search(r'v\d+$', actual):
                    return {**result, 'reason': 'version_unverified'}
                if not matches:
                    return {**result, 'state': 'mismatch', 'reason': 'identifier_mismatch'}
            if not actual:
                return {**result, 'reason': 'identifier_unverified'}
            # Aggregators without version metadata cannot certify a specific preprint version.
            if kind == 'arxiv' and re.search(r'v\d+$', value) and not actual:
                return {**result, 'reason': 'version_unverified'}
            if not isinstance(title, str) or not title.strip():
                return {**result, 'reason': 'expected_title_unavailable'}
            score = title_similarity(returned, title)
            return {**result, 'state': 'verified' if score >= .70 else 'mismatch', 'title_similarity': score,
                    'reason': 'identifier_title_match' if score >= .70 else 'title_mismatch'}
        except CitationRequestError as exc:
            record = self.requests[-1] if len(self.requests) > offset else {}
            return {**result, 'reason': str(exc), 'status_code': record.get('status_code'),
                    'retry_after': record.get('retry_after')}
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, ET.ParseError):
            record = self.requests[-1] if len(self.requests) > offset else {}
            if record:
                self._invalid_response()
            return {**result, 'reason': 'invalid_response', 'status_code': record.get('status_code'),
                    'retry_after': record.get('retry_after')}

    async def expand(self, ids, title=None):
        self.root_identity = await self.verify(ids, title) if title is not None else None
        if self.root_identity and self.root_identity['state'] == 'mismatch':
            return []
        ids = valid_identifiers(ids)
        async def get(url, params=None):
            body = await self._get(url, params, purpose='citation_expansion')
            try:
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError('Expected metadata object')
                if self.name == 'semantic_scholar':
                    key = 'citedPaper' if url.endswith('/references') else 'citingPaper'
                    if (not isinstance(data.get('data'), list) or any(
                            not isinstance(item, dict) or key not in item or
                            item[key] is not None and not isinstance(item[key], dict)
                            for item in data['data'])):
                        raise ValueError('Expected S2 expansion records')
                elif url == 'https://api.openalex.org/works':
                    if (not isinstance(data.get('results'), list) or any(
                            not isinstance(item, dict) or not isinstance(item.get('id'), str)
                            for item in data['results'])):
                        raise ValueError('Expected OpenAlex expansion records')
                elif (not isinstance(data.get('id'), str) or
                      not re.fullmatch(r'W\d+', data['id'].rsplit('/', 1)[-1]) or
                      not isinstance(data.get('referenced_works', []), list) or any(
                          not isinstance(item, str) for item in data.get('referenced_works', []))):
                    raise ValueError('Expected OpenAlex work')
                return data
            except (ValueError, TypeError, KeyError):
                self._invalid_response()
                raise CitationRequestError('invalid_response') from None
        if self.name == 'openalex':
            if 'doi' not in ids:
                raise ValueError('OpenAlex backend requires a DOI; use S2 for arXiv IDs')
            root = await get('https://api.openalex.org/works/https://doi.org/' + quote(ids['doi'], safe='/'))
            # Do not follow arbitrary URLs returned by metadata. Rebuild endpoints.
            root_id = root['id'].rsplit('/', 1)[-1]
            if not re.fullmatch(r'W\d+', root_id):
                raise ValueError('Invalid OpenAlex work ID')
            failure = None
            try:
                cited = await get('https://api.openalex.org/works', {'filter': 'cites:' + root_id, 'per-page': 5})
            except CitationRequestError as exc:
                cited, failure = {'results': []}, exc
            references = []
            for ref in root.get('referenced_works', [])[:5]:
                work_id = ref.rsplit('/', 1)[-1]
                if re.fullmatch(r'W\d+', work_id):
                    try:
                        references.append(await get('https://api.openalex.org/works/' + work_id))
                    except CitationRequestError as exc:
                        failure = failure or exc
                        break
            def hit(paper, relation):
                doi = paper.get('doi')
                location = paper.get('best_oa_location') or paper.get('primary_location') or {}
                url = location.get('pdf_url') or doi
                return {'url': url, 'title': paper.get('title') or '', 'relation': relation,
                        'identifiers': identifiers(doi or ''), 'backend_id': paper['id']} if url else None
            outgoing = [hit(p, 'reference') for p in references]
            incoming = [hit(p, 'citation') for p in cited.get('results', [])]
            if failure and not (any(outgoing) or any(incoming)):
                raise failure
        elif self.name == 'semantic_scholar':
            identifier = 'DOI:' + ids['doi'] if 'doi' in ids else 'ARXIV:' + ids['arxiv']
            endpoint = 'https://api.semanticscholar.org/graph/v1/paper/' + quote(identifier, safe='')
            def hit(paper, relation):
                external = paper.get('externalIds') or {}
                ids = {k: external[v] for k, v in [('doi', 'DOI'), ('arxiv', 'ArXiv')] if external.get(v)}
                pdf = paper.get('openAccessPdf') or {}
                url = pdf.get('url') or ('https://arxiv.org/pdf/' + ids['arxiv'] if ids.get('arxiv') else
                                        'https://doi.org/' + ids['doi'] if ids.get('doi') else None)
                return {'url': url, 'title': paper.get('title') or '', 'relation': relation,
                        'identifiers': ids, 'backend_id': paper.get('paperId')} if url else None
            outgoing, incoming = [], []
            for direction, key, target in [('references', 'citedPaper', outgoing), ('citations', 'citingPaper', incoming)]:
                try:
                    result = await get(endpoint + '/' + direction,
                                       {'fields': 'title,externalIds,openAccessPdf', 'limit': 5})
                except CitationRequestError:
                    # Keep real metadata already fetched in the other direction;
                    # requests retains the failed endpoint and rate-limit details.
                    if any(outgoing) or any(incoming):
                        break
                    raise
                target.extend(hit(p[key], direction) for p in result.get('data', []) if p.get(key))
        else:
            raise ValueError('Unknown citation backend')
        # Interleave both directions so references do not consume the entire cap.
        results = []
        for i in range(max(len(outgoing), len(incoming))):
            for group in (outgoing, incoming):
                if i < len(group) and group[i]:
                    results.append(group[i])
        return results


class CitationVerifier:
    """Explicit service allowlist; mismatch is never overridden by another service."""
    def __init__(self, enabled, factory=CitationBackend):
        if len(set(enabled)) != len(enabled) or set(enabled) - set(BACKENDS):
            raise ValueError('Invalid enabled citation services')
        self.enabled, self.factory, self.requests = list(enabled), factory, []

    async def verify(self, ids, title=None):
        base = {'state': 'unknown', 'checks': [], 'enabled_backends': self.enabled,
                'cross_check': 'citation_unverified', 'reason': 'no_identifier'}
        if not self.enabled:
            return {**base, 'reason': 'backend_disabled', 'cross_check': 'disabled'}
        try:
            ids = valid_identifiers(ids)
        except ValueError:
            return {**base, 'reason': 'invalid_identifier'}
        if not ids:
            return base
        checks = base['checks']
        async def check(name, selected):
            backend = self.factory(name)
            offset = len(backend.requests)
            result = await backend.verify(selected, title)
            self.requests.extend(backend.requests[offset:])
            checks.append(result)
        for kind, name in [('doi', 'crossref'), ('arxiv', 'arxiv')]:
            if kind in ids and name in self.enabled:
                await check(name, {kind: ids[kind]})
        need_supplement = not checks or any(c['state'] != 'verified' for c in checks)
        if need_supplement:
            for name in ('semantic_scholar', 'openalex'):
                if name not in self.enabled:
                    continue
                for kind in ('doi', 'arxiv'):
                    if kind in ids and kind in backend_capabilities(name)['identifiers']:
                        await check(name, {kind: ids[kind]})
                # Preserve every mismatch; additional votes cannot resolve it.
                if any(c['state'] == 'verified' and c['backend'] == name for c in checks):
                    break
        if not checks:
            return {**base, 'reason': 'unsupported_identifier'}
        titles = [c['canonical_title'] for c in checks if c.get('canonical_title')]
        conflict = any(c['state'] == 'mismatch' for c in checks) or any(
            title_similarity(left, right) < .70 for i, left in enumerate(titles) for right in titles[i+1:])
        if conflict:
            return {**base, 'state': 'mismatch', 'cross_check': 'cross_check_conflict', 'reason': 'citation_identity_conflict'}
        verified = [c for c in checks if c['state'] == 'verified']
        if verified:
            complete = len({c['backend'] for c in verified}) > 1 and len(verified) == len(checks)
            return {**base, 'state': 'verified', 'cross_check': 'cross_check_verified' if complete else 'cross_check_partial',
                    'reason': 'identifier_title_match', 'canonical_title': verified[0]['canonical_title']}
        return {**base, 'reason': 'all_checks_unknown'}
