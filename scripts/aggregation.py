"""Explicit human single-candidate selection; no semantic inference or calls."""
from schema_generator import digest
from review_policy import find_decision, review_accepted


def candidate_id(report_id, index):
    return 'candidate_' + digest([report_id, index])[:24]


def context(meta, cell_id):
    if not any(cell_id == f"{t['table_id']}/{cid}.{field}"
               for t in meta['schema']['tables'] for cid in meta['case_ids'] for field in t['attributes']):
        raise ValueError('Unknown field')
    items, basis = [], []
    for rid, entry in sorted(meta['grounding'].items()):
        source = entry['request']['source']
        latest = [r.get('source') for r in meta.get('online', {}).get('sources', {}).values()
                  if r.get('source', {}).get('source_id') == source['source_id']
                  or (source.get('url') and r.get('url') == source['url'])]
        for index, candidate in enumerate(entry['report']['validated_candidates']):
            if f"{entry['request']['table_id']}/{candidate['case_id']}.{candidate['field']}" != cell_id:
                continue
            attribution = find_decision(meta, 'attributions', rid, index)
            review = find_decision(meta, 'reviews', rid, index)
            # Include rejected/unreviewed revisions too: they cannot silently leave a snapshot.
            fingerprint = digest([candidate, attribution, review, source, latest])
            cid = candidate_id(rid, index)
            basis.append([cid, fingerprint])
            if not review_accepted(meta, attribution, review, candidate, source):
                continue
            binding = {'candidate_id': cid, 'report_id': rid, 'candidate_index': index,
                       'evidence_id': 'qs_' + digest([rid, index])[:24],
                       'source_sha256': candidate['grounding']['source_sha256'],
                       'location': candidate['location'], 'span': candidate['grounding']['span'],
                       'content_sha256': fingerprint}
            items.append({'binding': binding, 'candidate': candidate,
                          'semantic_review': review, 'attribution_review': attribution})
    history = [d for d in meta.get('aggregations', []) if d['cell_id'] == cell_id]
    basis_sha256 = digest(basis)
    snapshot_sha256 = digest([meta['run_id'], cell_id, basis_sha256, history])
    return {'run_id': meta['run_id'], 'cell_id': cell_id, 'basis_sha256': basis_sha256,
            'snapshot_sha256': snapshot_sha256, 'candidates': items, 'decisions': history}


def resolve(meta, cell_id, ctx=None):
    """Derive disposition from facts. New evidence never silently revives a choice."""
    ctx = context(meta, cell_id) if ctx is None else ctx
    items, history = ctx['candidates'], ctx['decisions']
    excluded = set()
    for decision in history:
        if decision['decision_type'] in {'select_one', 'reject_all'}:
            excluded.update(b['candidate_id'] for b in decision['bindings'])
            if decision['decision_type'] == 'select_one':
                excluded.discard(decision['selected_candidate_id'])
    latest = history[-1] if history else None
    remaining = [c for c in items if c['binding']['candidate_id'] not in excluded]
    selected, reason = None, None
    if latest and latest['basis_sha256'] != ctx['basis_sha256']:
        outcome, reason = 'pending', 'evidence_changed'
    elif latest and latest['decision_type'] == 'keep_pending':
        outcome, reason = 'pending', latest['pending_reason']
    elif latest and latest['decision_type'] == 'reject_all':
        outcome = 'rejected'
    elif latest:
        selected = next((c for c in remaining if c['binding']['candidate_id'] == latest['selected_candidate_id']), None)
        outcome, reason = ('accepted', None) if selected else ('pending', 'evidence_changed')
    else:
        selected = remaining[0] if len(remaining) == 1 else None
        outcome = 'accepted' if selected else 'pending' if remaining else 'incomplete'
    return {'outcome': outcome, 'pending_reason': reason, 'selected': selected,
            'remaining': remaining, 'excluded_candidate_ids': sorted(excluded), 'decision': latest}


def record(path, request):
    from searchos_adapter import locked, load, persist, now
    required = {'run_id', 'cell_id', 'snapshot_sha256', 'decision_type',
                'reviewer_kind', 'reviewer_id', 'reason', 'request_ref'}
    kind = request.get('decision_type')
    required |= {'selected_candidate_id'} if kind == 'select_one' else {'pending_reason'} if kind == 'keep_pending' else set()
    if set(request) != required or kind not in {'select_one', 'reject_all', 'keep_pending'}:
        raise ValueError('Invalid aggregation request fields or decision_type')
    if kind == 'keep_pending' and request['pending_reason'] not in {'human_review_pending', 'combined_conclusion_unsupported'}:
        raise ValueError('Invalid pending_reason')
    if request['reviewer_kind'] != 'human' or any(not isinstance(request[k], str) or not request[k].strip()
            for k in ('reviewer_id', 'reason', 'request_ref')):
        raise ValueError('Explicit human identity, reason and instruction reference required')
    with locked(path):
        meta = load(path)
        # A completed coverage receipt is a historical decision chain, not an editing target.
        if any(i.get('completed') for i in meta.get('online', {}).get('invocations', [])):
            raise ValueError('Completed workspace is immutable; use a new workspace')
        ctx = context(meta, request['cell_id'])
        if any(request[k] != ctx[k] for k in ('run_id', 'cell_id', 'snapshot_sha256')):
            raise ValueError('Stale or altered aggregation context; reopen current candidates')
        ids = {c['binding']['candidate_id'] for c in ctx['candidates']}
        if kind == 'select_one' and (not isinstance(request['selected_candidate_id'], str) or request['selected_candidate_id'] not in ids):
            raise ValueError('Select only one currently grounded, independently supported candidate')
        if kind == 'reject_all' and not ids:
            raise ValueError('No eligible candidates to reject')
        decision = {**request, 'at': now(), 'basis_sha256': ctx['basis_sha256'],
                    'bindings': [c['binding'] for c in ctx['candidates']]}
        decision['id'] = digest(decision)
        meta.setdefault('aggregations', []).append(decision)
        persist(path, meta)
        return decision
