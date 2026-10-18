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


def task_requirements(meta, state):
    """Domain prerequisites only; no Frontier state is used as an input."""
    from schema_generator import digest, TRACK_SKILLS
    from searchos_adapter import key
    cells = state.coverage_map.cells

    def prerequisites(cid, table):
        if table == 'problem_definition':
            return []
        track, kind = table.rsplit('_', 1)
        if kind == 'admission':
            complete = all(cells[key('problem_definition', cid, f)].status.value == 'filled'
                or meta.get('gaps', {}).get(key('problem_definition', cid, f), {}).get('reason')
                or (meta['legacy_values'].get(key('problem_definition', cid, f), {}).get('value') is None
                    and meta['legacy_values'].get(key('problem_definition', cid, f), {}).get('reason'))
                for f in meta['config']['fields'])
            return [] if complete else ['definition_incomplete']
        admission = [cells[key(track + '_admission', cid, c)]
                     for c in meta['config']['tracks'][track]['admission_criteria']]
        if any(c.status.value == 'filled' and c.display_hint == 'false' for c in admission):
            return ['admission_rejected']
        return [] if all(c.status.value == 'filled' and c.display_hint == 'true' for c in admission) else ['admission_incomplete']

    def scoped_targets(targets):
        pending = [k for k in targets if cells[k].status.value != 'filled']
        available = [k for k in pending if
            meta.get('gaps', {}).get(k, {}).get('investigate',
                meta.get('gaps', {}).get(k, {}).get('status') != 'hard_cell')
            and len(cells[k].supporting_evidence_ids) <= 1]
        reasons = []
        if pending and not available:
            if any(len(cells[k].supporting_evidence_ids) > 1 for k in pending):
                reasons.append('aggregation_pending')
            if any(not meta.get('gaps', {}).get(k, {}).get('investigate',
                meta.get('gaps', {}).get(k, {}).get('status') != 'hard_cell') for k in pending):
                reasons.append('outside_investigation_scope')
        return available or pending, reasons

    result = []
    for cid in meta['case_ids']:
        for table in meta['schema']['tables']:
            tid = table['table_id']
            targets, scope_reasons = scoped_targets([key(tid, cid, f) for f in table['attributes']])
            if not targets:
                continue
            reasons = prerequisites(cid, tid) + scope_reasons
            if 'admission_rejected' in reasons:
                continue
            skills, priority = ([], .9) if tid == 'problem_definition' else (
                ([TRACK_SKILLS[tid.rsplit('_', 1)[0]]], .8) if tid.endswith('_admission') else (['quantum-scoring'], .5))
            result.append({'task': {'id': 'qs_' + digest([cid, tid])[:20],
                'question': f'{cid}: fill and independently verify {tid}', 'table_id': tid,
                'target_cells': targets, 'skills': skills,
                'priority': min(1., priority + .2 * sum(cells[k].status.value == 'uncertain' for k in targets) / len(targets)),
                'created_by': 'quantum-scout', 'planner': 'coverage-heuristic',
                'task_prompt': 'Do not treat quote matching or coverage as semantic verification.'},
                'blocked_reasons': reasons})
    for record in meta.get('citation_tasks', {}).values():
        if record['status'] != 'pending':
            continue
        base = record['base_task']
        targets, scope_reasons = scoped_targets(base['target_cells'])
        if not targets:
            continue
        result.append({'task': {'id': record['id'], 'kind': 'explore', 'depth': 1,
            'parent_id': record['parent_node_id'], 'question': 'Verify citation body: ' + record['url'],
            'table_id': base['table_id'], 'target_cells': targets, 'skills': base['skills'],
            'priority': .3, 'created_by': 'citation-expansion', 'planner': 'bounded-bfs',
            'task_prompt': record['url']},
            'blocked_reasons': prerequisites(record['case_id'], base['table_id']) + scope_reasons})
    return result


def search_paused(provider, online):
    return any(r['provider'] == provider and
        (r.get('status_code') == 429 or r.get('error_type') in
         {'TimeoutError', 'ReadTimeout', 'ConnectTimeout', 'WriteTimeout', 'PoolTimeout'})
        for r in online.get('searches', {}).values())


def source_action(online, task, url, *, exact=False):
    """Normalize source availability and progress, without mutating either."""
    from schema_generator import digest
    if not exact and digest(url) not in online.get('sources', {}):
        canonical = identity(url)
        url = next((r['url'] for r in online.get('sources', {}).values() if identity(r['url']) == canonical), url)
    stored = online.get('sources', {}).get(digest(url))
    if stored and stored['status'] != 'opened' and not retryable_source(stored, online):
        return {'url': url, 'blocked_reasons': ['source_unavailable'], 'assessment': None}
    plan = resolve_assessment(online, task, stored['source']) if stored and stored.get('source') else None
    return {'url': url, 'blocked_reasons': ['source_assessed'] if plan and plan['cursor'] == 'done' else [],
            'assessment': plan}


def task_operations(meta, task, known_url=None):
    """Concrete available sources/search services for one eligible domain task."""
    online = meta['online']
    citation = meta.get('citation_tasks', {}).get(task['id'])
    if known_url or citation:
        hits = [{'url': known_url or citation['url']}]
    else:
        hits = [hit for record in online.get('searches', {}).values()
                if set(record['target_cells']) & set(task['target_cells']) for hit in record.get('results', [])]
        hits += [{'url': r['url']} for r in online.get('sources', {}).values() if r['status'] == 'opened']
    ready, unavailable, seen = [], [], set()
    for hit in hits:
        item = source_action(online, task, hit['url'], exact=bool(known_url))
        canonical = identity(item['url'])
        if canonical in seen:
            continue
        seen.add(canonical)
        if item['blocked_reasons']:
            unavailable.append(item)
        else:
            ready.append({**hit, 'url': item['url']})
    providers = [] if ready or known_url or citation else [p for p in online.get('config', {}).get('providers', [])
                                                          if not search_paused(p, online)]
    reasons = [] if ready or providers else sorted({r for item in unavailable for r in item['blocked_reasons']})
    if not ready and not providers and not reasons:
        reasons = ['service_unavailable']
    return {'hits': ready, 'providers': providers, 'blocked_reasons': reasons,
            'unavailable_sources': unavailable}


def action_plan(meta, state, known_url=None, case_id=None):
    """Ephemeral normalized decisions. All displays/consumers use this same result."""
    from searchos_adapter import task_claims
    invocation = next(iter(reversed(meta.get('online', {}).get('invocations', []))), {})
    scope = invocation.get('operation_scope', {})
    if known_url is None and scope.get('url'):
        known_url, case_id = scope['url'], scope['case_id']
    actions = task_requirements(meta, state)
    for item in actions:
        task, reasons = item['task'], item['blocked_reasons']
        if task['id'] in task_claims(meta):
            reasons.append('task_claimed')
        if known_url and (task['id'] in meta.get('citation_tasks', {}) or
                task['target_cells'][0].split('/', 1)[1].split('.', 1)[0] != case_id):
            reasons.append('outside_invocation_scope')
        item['operations'] = {'hits': [], 'providers': [], 'unavailable_sources': []}
        if 'online' in meta and 'outside_invocation_scope' not in reasons:
            item['operations'] = task_operations(meta, task, known_url)
            reasons.extend(item['operations']['blocked_reasons'])
        item['blocked_reasons'] = list(dict.fromkeys(reasons))
    ready = [item['task'] for item in actions if not item['blocked_reasons']]
    online = meta.get('online', {})
    preferred = online.get('config', {}).get('preferred_track')
    attempts = online.get('attempted_tasks', [])
    ready.sort(key=lambda t: (0 if preferred and t['table_id'].rsplit('_', 1)[0] == preferred else 1,
                             attempts.count(t['id']), -t['priority']))
    return {'scope': {'url': known_url, 'case_id': case_id},
            'actions': actions, 'executable_actions': ready,
            'blocked_reasons': sorted({r for item in actions for r in item['blocked_reasons']})}


def decide(meta, state, *, known_url=None, case_id=None, audit=None, budget_cause=None):
    plan = action_plan(meta, state, known_url, case_id)
    trace = {}
    terminal = stop_decision(meta, state, audit=audit, trace=trace, plan=plan,
                             known_url=known_url, case_id=case_id)
    if terminal is None and budget_cause:
        terminal = ('budget_exhausted', {'budget_cause': budget_cause})
        plan['blocked_reasons'] = sorted(set(plan['blocked_reasons']) | {'budget_exhausted'})
    return {**plan, 'executable_actions': [] if terminal else plan['executable_actions'],
            'terminal_reason': terminal[0] if terminal else None,
            'stop_evidence': terminal[1] if terminal else {}, 'trace': trace}


def stop_decision(meta, state, audit=None, trace=None, *, plan=None, known_url=None, case_id=None):
    trace = trace if trace is not None else {}
    trace.update(reason='pending_work')
    plan = plan if plan is not None else action_plan(meta, state, known_url, case_id)
    known_url, case_id = plan['scope']['url'], plan['scope']['case_id']
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
    if known_url:
        from schema_generator import digest
        record = meta['online']['sources'].get(digest(known_url))
        if record and record['status'] != 'opened' and not retryable_source(record, meta['online']):
            return 'error', {'error_kind': 'source_unavailable', 'source_url': known_url,
                             'error_type': record.get('error_type', 'Unknown')}
        evidence = fixed_source_stop_evidence(meta, state, known_url, case_id, plan=plan)
        if evidence:
            return 'operational_pool_exhausted', evidence
        if plan['executable_actions'] or 'task_claimed' in plan['blocked_reasons']:
            return None
        return 'error', {'error_kind': 'no_executable_action', 'blocked_reasons': plan['blocked_reasons']}
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
    if plan['executable_actions'] or 'task_claimed' in plan['blocked_reasons']:
        return None
    if source_backlog(meta) or search_backlog(meta):
        return 'error', {'error_kind': 'no_executable_action', 'blocked_reasons': plan['blocked_reasons'],
                         'rationale': 'Remaining sources/queries are blocked, not exhausted.'}
    actions = [{'id': item['task']['id'], 'status': 'blocked',
                'reason': ','.join(item['blocked_reasons']), 'reason_codes': item['blocked_reasons']}
               for item in plan['actions']]
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


def fixed_source_stop_evidence(meta, state, url, case_id, *, plan=None):
    """A fully assessed fixed source is an operation limit, not spent model/time budget."""
    from schema_generator import digest
    online = meta['online']
    record = online['sources'].get(digest(url))
    plan = plan if plan is not None else action_plan(meta, state, url, case_id)
    if (not record or record['status'] != 'opened' or plan['executable_actions']
            or 'task_claimed' in plan['blocked_reasons'] or source_backlog(meta) or search_backlog(meta)):
        return None
    reason = 'Fixed-source invocation: other sources, searches and citation expansion are outside this invocation'
    actions = [{'id': item['task']['id'], 'status': 'blocked',
                'reason': ','.join(item['blocked_reasons']), 'reason_codes': item['blocked_reasons']}
               for item in plan['actions']]
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
    from review_policy import find_decision, bound, review_accepted
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
            if not review_accepted(meta, a, review, candidate, entry['request']['source']):
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
