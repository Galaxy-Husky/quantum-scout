"""Recomputable stop evidence from adapter facts, never from aggregate coverage."""
from citation_backends import identity
from coverage_policy import coverage_witness, reviewed_cases


def source_key(meta, url):
    canonical = identity(url)
    for task in meta.get('citation_tasks', {}).values():
        if canonical in task['aliases']:
            canonical = identity(task['url'])
            break
    for record in meta['online']['sources'].values():
        if identity(record['url']) == canonical and record.get('source'):
            return record['source']['source_id']
    return canonical


def discovery_trace(meta):
    grouped, candidates = {}, []
    # Pages and citation discoveries share a chronological deduplication ledger.
    for page in meta['online']['searches'].values():
        key = (page['provider'], ' '.join(page['query'].split()).casefold())
        entry = grouped.setdefault(key, {'id': f'ADAPT-{len(grouped)+1}',
            'keyword_or_source': page['provider'] + ':' + key[1], 'query': page['query'],
            'provider': page['provider'], 'status': 'completed', 'produced_new_sources': 0,
            'results': [], 'at': page.get('attempted_at', page['at']), 'pages': 0})
        entry['pages'] += int(page['status'] == 'succeeded')
        if page['status'] != 'succeeded':
            entry['status'] = 'failed'
        for position, hit in enumerate(page.get('results', []), 1):
            candidates.append((page.get('attempted_at', page['at']), entry, hit, entry['id'], position, 'adaptive'))
    for task in meta.get('citation_tasks', {}).values():
        candidates.append((task['created_at'], None, task, task['id'], 1, 'layer3'))
    for record in meta['online']['sources'].values():
        candidates.append((record['at'], None, {'url': record['url']}, 'direct-open', 1, 'layer3'))
    seen, discoveries = set(), []
    for at, entry, hit, query_id, position, layer in sorted(candidates, key=lambda item: item[0]):
        name = source_key(meta, hit['url'])
        if name in seen:
            continue
        seen.add(name)
        discoveries.append({'at': at, 'url': hit['url'], 'query_id': query_id,
                            'position': position, 'layer': layer})
        if entry is not None:
            entry['results'].append(hit)
            entry['produced_new_sources'] += 1
    return sorted(grouped.values(), key=lambda q: q['at']), discoveries


def queries(meta):
    return discovery_trace(meta)[0]


def seed_pending(meta):
    online = meta['online']
    used = {(r['provider'], r['query']) for r in online['searches'].values()}
    return [f'{cid}:{provider}:{q}' for cid, case in online['config']['cases'].items()
            for provider, values in case.get('queries', {}).items() for q in values
            if (provider, q) not in used]


def retryable_source(record, online):
    """One explicit-resume retry for transport failures, never retry within a run."""
    transient = {'ConnectError', 'ConnectTimeout', 'ReadTimeout', 'ReadError',
                 'RemoteProtocolError', 'TimeoutError', 'ProcessInterrupted'}
    return (record.get('status') == 'failed' and record.get('error_type') in transient
            and record.get('attempts', 1) < 2 and bool(online.get('invocations'))
            and record.get('attempted_at', record['at']) < online['invocations'][-1]['started_at'])


def retryable_search(record, online):
    return retryable_source(record, online)


def search_backlog(meta):
    return [key for key, record in meta['online']['searches'].items()
            if retryable_search(record, meta['online'])]


def source_backlog(meta):
    online = meta['online']
    attempted = {source_key(meta, r['url']) for r in online['sources'].values()}
    found = {source_key(meta, h['url']) for r in online['searches'].values() for h in r.get('results', [])}
    found.update(source_key(meta, t['url']) for t in meta.get('citation_tasks', {}).values())
    retryable = {source_key(meta, r['url']) for r in online['sources'].values() if retryable_source(r, online)}
    return (found - attempted) | retryable


def current_assessments(online):
    events = [e for e in online.get('events', []) if e['kind'] == 'assessment_started']
    scopes = {e['task_id']: (e['case_id'], e['table_id']) for e in events if e.get('case_id') and e.get('table_id')}
    current = {}
    for event in events:
        scope = ((event['case_id'], event['table_id']) if event.get('case_id') and event.get('table_id')
                 else scopes.get(event['task_id'], ('legacy', event['task_id'])))
        current[(*scope, event['source_id'])] = event['assessment_id']
    return current


def stop_decision(meta, state, audit=None, trace=None):
    trace = trace if trace is not None else {}
    trace.update(reason='pending_work')
    config = meta['online']['config']
    sources = {r['source']['source_id'] for r in meta['online']['sources'].values() if r['status'] == 'opened'}
    cases = reviewed_cases(meta, state)
    if len(sources) >= config['analysis_limit']:
        return 'analysis_limit_reached', {'opened_sources': len(sources)}
    accepted = [c['case_id'] for c in cases if any(t['passed_admission'] and t['score_normalized'] is not None
                and t['score_normalized'] >= meta['config']['tracks'][track]['min_total_score']
                for track, t in c['tracks'].items())]
    if len(accepted) >= config['max_cases']:
        return 'max_cases_reached', {'accepted_case_ids': accepted}
    scope = list(meta['case_ids'])
    witnesses = [coverage_witness([c for c in cases if c['case_id'] == cid], meta['config'], sources)
                 for cid in scope]
    if scope and all(witnesses):
        from audit_policy import self_audit, case_audit_metrics
        completions = []
        for witness in witnesses:
            result = (audit(witness['case_id'], witness['track_id']) if audit else
                      self_audit(meta, witness['case_id'], witness['track_id']))
            if not result['audit_passed']:
                trace.update(reason='self_audit_rejected', self_audit=result)
                return None
            metrics = case_audit_metrics(witness, meta.get('attribution_checks', []), meta['config'])
            completions.append({'coverage_witness': witness, 'self_audit': result,
                'case_audit': metrics, 'human_audit_status': metrics['status']})
        return 'case_coverage_complete', {**completions[0], 'case_completions': completions,
            'configured_case_ids': scope,
            'attribution_check_count': len(meta.get('attribution_checks', []))}
    tail = queries(meta)[-config['stall_rounds']:]
    online = meta['online']
    current = current_assessments(online).values() or online['assessments'].keys()
    unfinished_chunks = any(not assessment_done(online, k) for k in current)
    if (not source_backlog(meta) and not search_backlog(meta) and not seed_pending(meta) and not unfinished_chunks
            and len(tail) == config['stall_rounds']
            and len({q['keyword_or_source'] for q in tail}) == len(tail)
            and all(q['status'] == 'completed' and q['produced_new_sources'] == 0 for q in tail)):
        return 'diminishing_returns', {'basis': 'new_sources',
            'window_query_ids': [q['id'] for q in tail],
            'rationale': 'Last N distinct successful queries discovered no new sources; gaps remain.'}
    tasks = state.frontier.questions
    if any(t.status.value in {'pending', 'running'} for t in tasks) or source_backlog(meta) or search_backlog(meta):
        return None
    actions = [{'id': t.id, 'status': 'blocked',
                'reason': 'Unmet reviewed prerequisites: ' + ','.join(t.blocked_by)} for t in tasks]
    actions += [{'id': seed, 'status': 'blocked', 'reason': 'No eligible case/track task'} for seed in seed_pending(meta)]
    actions += [{'id': k, 'status': 'completed' if r['status'] == 'succeeded' else 'failed',
                 'reason': 'Query page ' + r['status']} for k, r in meta['online']['searches'].items()]
    actions += [{'id': 'expansion:' + k, 'status': 'completed' if r['status'] in {'succeeded', 'skipped'} else 'failed',
                 'reason': r.get('reason', r.get('error_type', r['status']))}
                for k, r in meta['online'].get('citation_expansions', {}).items()]
    actions += [{'id': t['id'], 'status': 'completed', 'reason': 'Citation source assessed'}
                for t in meta.get('citation_tasks', {}).values() if t['status'] == 'completed']
    if not actions:
        actions = [{'id': 'frontier', 'status': 'completed', 'reason': 'No eligible gap task remains'}]
    endpoints = [{'id': p, 'pages_fetched': sum(q['pages'] for q in queries(meta) if q['provider'] == p),
                  'limitation': 'Configured SearchOS backend and bounded results only; not global exhaustion'}
                 for p in config['providers']]
    if config['citation_backend'] != 'none':
        endpoints.append({'id': config['citation_backend'], 'pages_fetched': sum(
            r['status'] == 'succeeded' for e in meta['online'].get('citation_expansions', {}).values()
            for r in e.get('requests', [])), 'limitation': 'Metadata responses only; depth 1, at most 5 tasks per parent. Interrupted requests have unknown outcome.'})
    return 'operational_pool_exhausted', {'actions': actions, 'endpoints': endpoints,
        'rationale': 'No ready/running tasks or unattempted discovered sources within this operation scope.'}


def fixed_source_stop_evidence(meta, state, url, case_id):
    """A fully assessed fixed source is an operation limit, not spent model/time budget."""
    from schema_generator import digest
    online = meta['online']
    record = online['sources'].get(digest(url))
    if (meta.get('claimed_tasks') or not record or record['status'] != 'opened'
            or source_backlog(meta) or search_backlog(meta)):
        return None
    tasks = [t for t in state.frontier.questions if t.id not in meta.get('citation_tasks', {})
             and any(c.split('/', 1)[1].split('.', 1)[0] == case_id for c in t.target_cells)]
    if any(t.status.value == 'running' or (t.status.value == 'pending' and
           resolve_assessment(online, t.model_dump(), record['source'])['cursor'] != 'done') for t in tasks):
        return None
    reason = 'Fixed-source invocation: other sources, searches and citation expansion are outside this invocation'
    actions = [{'id': t.id, 'status': 'blocked', 'reason': reason + '; reviewed prerequisites or source evidence remain missing'}
               for t in state.frontier.questions if t.status.value in {'pending', 'blocked', 'running'}]
    actions += [{'id': seed, 'status': 'blocked', 'reason': reason} for seed in seed_pending(meta)]
    actions += [{'id': 'fixed-source:' + record['source']['source_id'], 'status': 'completed',
                 'reason': 'Opened source has no unassessed segments for any ready task in the selected case'},
                {'id': 'fixed-source:search-and-pagination', 'status': 'blocked', 'reason': reason},
                {'id': 'fixed-source:citation-expansion', 'status': 'blocked', 'reason': reason}]
    return {'actions': actions, 'endpoints': [{'id': url, 'pages_fetched': 1,
        'limitation': 'One explicit body URL and case only; no search or citation expansion; not global exhaustion'}],
        'rationale': 'All executable assessments of the fixed body source are complete; evidence gaps remain. '
                     'Model-call and time budgets were not exhausted by this condition.'}


def online_limit_policy(config, scope):
    """Online values are effective; phase settings are planning context, not overrides."""
    phase = scope.get('current_phase')
    reference = scope.get('phases', {}).get(phase, {})
    return {'owner': 'online.config', 'phase_applied': False, 'phase': phase,
            'effective': {'analysis_limit': config['analysis_limit'], 'max_cases': config['max_cases'],
                          'batch_size': config['batch_size'], 'stall_rounds': config['stall_rounds'],
                          'discovery_limit': None},
            'phase_reference': {k: reference.get(k) for k in
                ('analysis_limit', 'max_cases', 'batch_size', 'diminishing_returns_threshold', 'discovery_limit')}}


def attribution_metrics(meta):
    """Sample precision is not a population estimate; unreviewed is never correct."""
    from review_policy import find_decision, bound, supported_pair, source_reviewable, citation_allowed
    counts = {'attributed': 0, 'abstained': 0, 'absent': 0, 'pending_attribution': 0}
    chains, review_pairs = {}, []
    for rid, entry in meta['grounding'].items():
        for index, candidate in enumerate(entry['report']['validated_candidates']):
            a = find_decision(meta, 'attributions', rid, index)
            verdict = a.get('attribution') if bound(a, candidate) else None
            counts[verdict if verdict in {'attributed', 'abstained', 'absent'} else 'pending_attribution'] += 1
            review = find_decision(meta, 'reviews', rid, index)
            if bound(a, candidate) and bound(review, candidate):
                review_pairs.append((a, review))
            if (not supported_pair(a, review, candidate)
                    or not source_reviewable(entry['request']['source'], review)
                    or not citation_allowed(meta, candidate['source_id'])):
                continue
            chains[(rid, index)] = candidate
    from audit_policy import _audit_walk
    eligible, checked, correct = _audit_walk(chains, meta.get('attribution_checks', []), strip_reason=False)
    from audit_policy import audit_thresholds
    thresholds = audit_thresholds(meta, eligible, checked)
    pairs = review_pairs  # Model provenance includes rejected pairs; acceptance/human metrics do not.
    known = [(a['model_call']['model'], r['model_call']['model']) for a, r in pairs
             if (a.get('model_call') or {}).get('model') and (r.get('model_call') or {}).get('model')]
    counts['same_model_used'] = any(a == r for a, r in known) if known else None
    counts['model_pairs_recorded'] = len(known)
    counts['model_pairs_unknown'] = len(pairs) - len(known)
    counts['review_models'] = sorted({model for pair in known for model in pair})
    return {**counts, **thresholds, 'eligible_supported': eligible, 'audited_samples': checked,
            'audited_correct': correct, 'audited_incorrect': checked - correct,
            'attribution_precision': correct / checked if checked else None,
            'audit_coverage': checked / eligible if eligible else None}



def resolve_assessment(online, task, source):
    """Resolve by scope, then compare fields/version/segment count; never mutate history."""
    case_id = task['target_cells'][0].split('/', 1)[1].split('.', 1)[0]
    table_id = task['table_id']
    fields = sorted({c.rsplit('.', 1)[1] for c in task['target_cells']})
    total = len(source.get('segments', []))
    plan = {'case_id': case_id, 'table_id': table_id, 'source_id': source['source_id'],
            'document_version': source.get('document_version'), 'fields': fields,
            'total_segments': total, 'cursor': 0, 'assessment_id': None, 'cursor_source': 'new'}
    previous = next((e for e in reversed(online.get('events', [])) if e['kind'] == 'assessment_started'
        and e['source_id'] == source['source_id'] and (
            (e.get('case_id'), e.get('table_id')) == (case_id, table_id)
            or (not e.get('case_id') and e['task_id'] == task['id']))), None)
    if previous is None:
        return plan
    reason = ('legacy_scope_unknown' if 'fields' not in previous else
              'document_version_changed' if previous.get('document_version') != plan['document_version'] else
              'segment_count_changed' if previous.get('total_segments') != total else
              'target_expanded' if not set(fields) <= set(previous['fields']) else None)
    cursor = online['assessments'].get(previous['assessment_id'], 0)
    if cursor != 'done' and (type(cursor) is not int or not 0 <= cursor <= total):
        reason = 'invalid_cursor'
    if reason:
        return {**plan, 'cursor_source': 'restarted', 'restart_reason': reason, 'previous_assessment': previous['assessment_id']}
    if fields == previous['fields']:
        return {**plan, 'cursor_source': 'resumed', 'cursor': cursor, 'assessment_id': previous['assessment_id']}
    return {**plan, 'cursor_source': 'inherited', 'cursor': cursor, 'inherited_from': previous['assessment_id'],
            'inherited_total_segments': previous['total_segments']}


def assessment_done(online, key):
    if online['assessments'].get(key) != 'done':
        return False
    event = next((e for e in reversed(online.get('events', []))
                  if e['kind'] == 'assessment_started' and e['assessment_id'] == key), None)
    if not event or 'document_version' not in event:
        return True  # Historical diagnostics lack scope metadata; resolve_assessment restarts safely.
    sources = [r['source'] for r in online.get('sources', {}).values()
               if r.get('status') == 'opened' and r['source']['source_id'] == event['source_id']]
    return bool(sources) and all(s.get('document_version') == event['document_version']
        and len(s.get('segments', [])) == event['total_segments'] for s in sources)


def table_model_calls(events, started_at):
    """Derived call counts; legacy sequential assessments provide scope, never guessed inputs."""
    from cost_policy import cost_category
    grouped, scope = {}, (None, None)
    for event in events:
        kind = event['kind']
        if kind in {'round_completed', 'round_interrupted', 'stop_decision'}:
            scope = (None, None)
        elif kind == 'assessment_started':
            scope = (event.get('case_id'), event.get('table_id'))
        elif kind == 'model_call_started':
            key = ((event['case_id'], event['table_id'])
                   if event.get('case_id') and event.get('table_id') else scope)
            row = grouped.setdefault(key, {'case_id': key[0], 'table_id': key[1],
                'invocation': {}, 'workspace': {}})
            category = event.get('cost_category') or cost_category(event.get('output_contract', ''))
            for period in ('workspace', 'invocation') if event['at'] >= started_at else ('workspace',):
                row[period][category] = row[period].get(category, 0) + 1
    return list(grouped.values())
