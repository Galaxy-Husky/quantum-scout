#!/usr/bin/env python3
"""Export a reviewed SOCM workspace to the current calibration batch contract."""
import argparse
import json
from pathlib import Path

import searchos_adapter as adapter
from citation_backends import identity, identity_backends
from coverage_policy import reviewed_cases, case_evidence
from online_policy import discovery_trace, seed_pending, attribution_metrics, current_assessments, assessment_done, table_model_calls
from render_calibration import render, render_case_files
from validate_batch import CHECKPOINT_DELTA_KEYS
from searchos_project import save, WorkspaceLayout


def build(meta):
    online = meta['online']
    config = online['config']
    invocation = online['invocations'][-1]
    state = adapter.project(meta)
    cases = reviewed_cases(meta, state)
    records = online['sources']
    known_ids = {identity(r['url']): r.get('source', {}).get('source_id', 'source_' + adapter.digest(identity(r['url']))[:20])
                 for r in records.values()}
    def sid(url):
        # Preserve exact opened-body IDs, including explicitly opened versions.
        # Canonical paper identity is only a fallback for unopened discoveries.
        source = records.get(adapter.digest(url), {}).get('source', {})
        if source.get('source_id'):
            return source['source_id']
        return known_ids.get(identity(url), 'source_' + adapter.digest(identity(url))[:20])
    query_list, discoveries = discovery_trace(meta)
    events, discovered = [], set()
    for q in query_list:
        events.append({'timestamp': q['at'], 'kind': 'adaptive_query', 'details': {'id': q['id']}})
        q['hits'] = len(q['results'])
        q['opened'] = sum(records.get(adapter.digest(h['url']), {}).get('status') == 'opened' for h in q['results'])
        q.update(trigger='case_gap', rationale='Targeted online gap query')
        del q['results']
    for discovery in discoveries:
        source_id = sid(discovery['url'])
        discovered.add(source_id)
        events.append({'timestamp': discovery['at'], 'kind': 'source_discovered', 'source_id': source_id,
                       'details': {k: discovery[k] for k in ('layer', 'query_id', 'position')}})
    events.sort(key=lambda e: e['timestamp'])
    observed = {'stop_decision', 'self_audit', 'round_completed', 'round_interrupted',
                'assessment_started', 'source_context', 'contract_rejection'}
    events.extend({'timestamp': e['at'], 'kind': e['kind'],
                   'details': {k: v for k, v in e.items() if k not in {'kind', 'at'}}}
                  for e in online['events'] if e['kind'] in observed)
    sources = []
    evidence_by_source = {}
    for case in cases:
        for ref in case_evidence(case):
            if ref.get('source_id'):
                evidence_by_source.setdefault(ref['source_id'], []).append(ref)
    for record in records.values():
        source_id = sid(record['url'])
        source = record.get('source', {})
        status = 'opened' if record['status'] == 'opened' else 'open_failed'
        sources.append({'source_id': source_id, 'status': status, 'url': record['url'],
            'document_version': source.get('document_version'), 'error': record.get('error_type'),
            'citation_identity': source.get('citation_identity'),
            'metadata_identifier_conflict': source.get('metadata_identifier_conflict'),
            'text_extraction': source.get('text_extraction'),
            'evidence': evidence_by_source.get(source_id, []),
            'supports_cases': [c['case_id'] for c in cases if source_id in c['source_ids']]})
        if source_id not in discovered:
            discovered.add(source_id)
            events.append({'timestamp': record['at'], 'kind': 'source_discovered', 'source_id': source_id,
                           'details': {'layer': 'layer3', 'query_id': 'direct-open', 'position': 1}})
        events.append({'timestamp': source.get('opened_at', record['at']),
                       'kind': 'source_opened' if status == 'opened' else 'open_failed',
                       'source_id': source_id, 'details': {'access_level': 'full_text' if status == 'opened' else 'none',
                                                        'opened_order': record.get('opened_order')}})
    # Redirect aliases must not inflate unique opened-body counts.
    sources = list({s['source_id']: s for s in sources}.values())
    counts = {'discovery_sources': len(discovered), 'discovery_pool_size': len(discovered),
        'attempted_sources': len(sources), 'opened_sources': sum(s['status'] == 'opened' for s in sources),
        'opened_metadata_only': 0, 'sources_unattempted': len(discovered) - len(sources),
        'extracted_candidate_cases': len(cases), 'problem_definition_complete_cases': sum(c['problem_definition_complete'] for c in cases),
        'unique_cases': len(cases), 'accepted_cases': sum(c['failure_class'] is None for c in cases),
        'cache_hits': 0, 'analysis_limit': config['analysis_limit'], 'discovery_limit': None,
        'accepted_limit': config['max_cases'], 'batch_size': config['batch_size'],
        'diminishing_returns_threshold': config['stall_rounds']}
    all_evidence = [e for values in evidence_by_source.values() for e in values]
    criteria = [v for case in cases for t in case['tracks'].values() for v in t['criteria'].values()]
    ratio = sum(v == 'insufficient_evidence' for v in criteria) / len(criteria) if criteria else None
    quality = {'primary_evidence_ratio': sum(e['evidence_level'] == 'primary' for e in all_evidence) / len(all_evidence) if all_evidence else None,
        'insufficient_evidence_admission_ratio': ratio, 'quantitative_quote_coverage': None,
        'warnings': [{'category': 'search_adequacy', 'message': 'Bounded online run; no global exhaustion or evidence sufficiency claim.'}]}
    from online_policy import online_limit_policy
    quality['limit_policy'] = online_limit_policy(config, meta['config'].get('scope', {}))
    for record in records.values():
        conflict = record.get('source', {}).get('metadata_identifier_conflict')
        if conflict:
            quality['warnings'].append({'category': 'trace_consistency',
                'type': 'source_metadata_identifier_conflict', 'source_id': record['source']['source_id'],
                'details': conflict, 'message': record['url'] + ': discovery metadata and URL identifiers disagree; '
                    'local warning is not external identity verification.'})
    for record in records.values():
        check = record.get('source', {}).get('citation_identity', {})
        if (bool(identity_backends(config)) and record['status'] == 'opened'
                and check.get('state', 'unknown') == 'unknown'):
            quality['warnings'].append({'category': 'citation_unverified',
                'message': record['url'] + ': ' + check.get('reason', 'Citation identity not checked')})
    quality['citation_identity'] = {
        'enabled_backends': identity_backends(config),
        'status': 'enabled' if identity_backends(config) else 'disabled',
        'scope': 'Identifier/title checks only; no body support or global sufficiency claim',
        'requests_consumed': sum(r.get('budget_consumed', 1) for r in online.get('citation_requests', {}).values()),
        'max_requests': config.get('max_citation_requests', 20)}
    for record in records.values():
        check = record.get('source', {}).get('citation_identity', {})
        if check.get('cross_check') in {'cross_check_partial', 'cross_check_conflict'}:
            quality['warnings'].append({'category': check['cross_check'],
                'message': record['url'] + ': ' + check.get('reason', '')})
    # Assessment keys represent task/chunk scopes, not source IDs. Superseded scopes
    # must not inflate the number of partly processed sources.
    latest, provided = current_assessments(online), {}
    for event in online['events']:
        if event['kind'] == 'source_context':
            provided.setdefault(event['source_id'], set()).update(range(
                event['start_segment'], event['start_segment'] + event['included_segments']))
    rejections = [e for e in online['events'] if e['kind'] == 'contract_rejection']
    for source_id, source in {r['source']['source_id']: r['source'] for r in records.values()
                              if r['status'] == 'opened'}.items():
        scopes = [key for (_, _, sid), key in latest.items() if sid == source_id]
        unfinished = sorted({f'{cid}/{table}' for (cid, table, sid), key in latest.items()
                             if sid == source_id and not assessment_done(online, key)})
        total = len(source.get('segments', []))
        shown = len(provided.get(source_id, set()))
        if not scopes or shown < total or any(not assessment_done(online, key) for key in scopes):
            quality['warnings'].append({'category': 'source_level', 'type': 'unprocessed_chunks', 'message':
                f'{source_id}: 正文处理未完成；未完成案例/表：{", ".join(unfinished) or "尚无评估或分段提供记录不完整"}；'
                f'已向模型提供 {shown}/{total} 个分段（提供不等于复核完成）；'
                f'contract_rejections={sum(e.get("source_id") == source_id for e in rejections)}。'})
    attempted = {identity(r['url']) for r in records.values()}
    unopened = {identity(t['url']) for t in meta.get('citation_tasks', {}).values()} - attempted
    if unopened:
        quality['warnings'].append({'category': 'source_level', 'type': 'unopened_sources',
            'message': f'引用扩展有 {len(unopened)} 个来源尚未打开。'})
    for event in online['events']:
        if event['kind'] == 'warning' and event.get('warning_type') == 'citation_backend_throttled':
            quality['warnings'].append({'category': 'citation_unverified',
                'type': 'citation_backend_throttled', 'message': event['message']})
    quality['contract_rejections'] = {'candidates': len(rejections),
        'affected_calls': len({e['call_id'] for e in rejections if e.get('call_id')}),
        'invocation_candidates': sum(e['at'] >= invocation.get('started_at', '') for e in rejections)}
    if rejections:
        quality['warnings'].append({'category': 'grounding', 'message':
            f'contract_rejections: {len(rejections)} 个候选在入图前因契约违规被拒绝，原值和原因见事件。'})
    from field_diagnostics import field_diagnostics
    quality['field_diagnostics'] = field_diagnostics(meta, cases)
    quality['attribution'] = attribution_metrics(meta)
    from cost_policy import model_costs
    quality['cost_breakdown'] = model_costs(online['events'])
    starts = [e for e in online['events'] if e['kind'] == 'model_call_started']
    quality['model_calls'] = {'invocation': sum(e['at'] >= invocation.get('started_at', '') for e in starts),
                              'workspace': len(starts),
                              'by_table': table_model_calls(online['events'], invocation.get('started_at', ''))}
    if quality['attribution']['audit_warning']:
        quality['warnings'].append({'category': 'audit_coverage', 'message': quality['attribution']['audit_warning']})
    if counts['sources_unattempted'] > len(unopened):
        quality['warnings'].append({'category': 'search_adequacy', 'message': 'Discovered sources remain unattempted.'})
    if ratio:
        quality['warnings'].append({'category': 'evidence_breakdown',
            'message': 'Unresolved admission evidence requires document-level attribution; exporter does not infer absence or ambiguity.'})
    status = invocation['status']
    stop = invocation.get('stop_reason')
    checkpoints = online.get('checkpoints', [])
    last = checkpoints[-1] if checkpoints else {'new_source_ids': [], 'final': False, 'at': adapter.now()}
    previous_counts = checkpoints[-2].get('counts', {}) if len(checkpoints) > 1 else {}
    cp = {'completed': status == 'completed', 'run_status': status, 'stop_reason': stop,
        'input_source_ids': last['new_source_ids'], 'new_source_ids': last['new_source_ids'],
        'opened_since_last_checkpoint': len(last['new_source_ids']), 'counts': counts,
        'counts_delta': {k: counts[k] - previous_counts.get(k, 0) for k in CHECKPOINT_DELTA_KEYS}, 'quality': quality,
        'discovery_judgement': {'judgement': 'not_exhausted'},
        'search_progress': {'seed_completed': [], 'seed_pending': seed_pending(meta), 'seed_not_applicable': [],
            'seed_executed_outside_scope': [], 'adaptive_queries': query_list,
            'adaptive_converged': False, 'loop_status': 'stopped' if stop else 'running'},
        'stop_evidence': invocation.get('stop_evidence', {}),
        'operational_cause': invocation.get('operational_cause')}
    for i, checkpoint in enumerate(checkpoints):
        # Previous invocation-final snapshots remain separate checkpoint files.
        if checkpoint['final'] and i != len(checkpoints) - 1:
            continue
        events.append({'timestamp': checkpoint['at'], 'kind': 'checkpoint', 'details': {
            'opened_since_last_checkpoint': len(checkpoint['new_source_ids']), 'final': checkpoint['final'],
            'completed': status == 'completed' and i == len(checkpoints) - 1}})
    failures = [f for entry in meta['grounding'].values() for f in entry['report']['grounding_failures']]
    calls = {e['call_id']: e for e in online['events'] if e['kind'] == 'model_call_started'}
    responses = {e['call_id']: e for e in online['events'] if e['kind'] == 'model_response' and e.get('call_id')}
    for event in online['events']:
        if event.get('failure_category') != 'counter_evidence_unsubstantiated':
            continue
        started = calls.get(event.get('call_id'), {})
        candidate = started.get('input', {}).get('candidate', {})
        if candidate.get('case_id') and candidate.get('source_id') and candidate.get('field'):
            failures.append({'case_id': candidate['case_id'], 'field': candidate['field'],
                'source_id': candidate['source_id'], 'failure_type': 'counter_evidence_invalid',
                'call_id': event['call_id'], 'candidate': candidate,
                'validation_errors': event.get('validation_errors', []),
                'rejected_response': responses.get(event['call_id'], {}).get('content')})
    for entry in meta['grounding'].values():
        source = entry['request']['source']
        check = source.get('citation_identity', {})
        latest = next((r['source'].get('citation_identity', {}) for r in records.values()
                       if r.get('source', {}).get('source_id') == source['source_id']), {})
        if check.get('state') == 'mismatch' or latest.get('state') == 'mismatch':
            for c in entry['report']['validated_candidates']:
                if any(f.get('failure_type') == 'citation_mismatch' and f.get('candidate') == c for f in failures):
                    continue
                failures.append({'case_id': c['case_id'], 'field': c['field'], 'source_id': c['source_id'],
                                 'failure_type': 'citation_mismatch', 'candidate': c, 'citation_identity': latest or check})
    for review in meta['reviews']:
        if review['verdict'] == 'semantic_mismatch':
            entry = meta['grounding'][review['report_id']]
            c = entry['report']['validated_candidates'][review['candidate_index']]
            failures.append({'case_id': c['case_id'], 'field': c['field'], 'source_id': c['source_id'],
                             'failure_type': 'semantic_mismatch', 'candidate': c, 'review': review})
    return {'run_id': meta['run_id'], 'batch_id': meta['run_id'] + '-online', 'run_status': status,
            'stop_reason': stop, 'configured_case_ids': meta['case_ids'], 'counts': counts, 'quality': quality, 'sources': sources, 'cases': cases,
            'events': sorted(events, key=lambda e: e['timestamp']), 'checkpoint': cp, 'grounding_failures': failures,
            'review_audit': {'attributions': meta.get('attributions', []), 'reviews': meta['reviews'],
                             'attribution_checks': meta.get('attribution_checks', [])},
            'audit_source': 'quantum_adapter.json', 'export_version': 2,
            'config_snapshot': meta['config'], 'config_sha256': meta['schema']['config_sha256']}


def write_export(workspace):
    workspace = Path(workspace)
    with adapter.locked(workspace):
        meta = adapter.load(workspace)
        batch = build(meta)
        batch['audit_source'] = str(WorkspaceLayout(workspace).adapter.relative_to(workspace))
        comparison = render(batch)  # Fail closed before writing a misleading artifact.
        folder = workspace / 'calibration'
        save(folder / 'batch.json', batch)
        save(folder / 'comparison.md', comparison)
        render_case_files(batch, folder / 'cases')
        checkpoints = meta['online'].get('checkpoints', [])
        if checkpoints:
            checkpoints[-1]['counts'] = batch['counts']
            save(folder / f'checkpoint-{len(checkpoints):04d}.json', batch['checkpoint'])
            # Only checkpoint counts changed; build/render already validated the facts.
            # Export must not rewrite the schema or rebuild scheduling projections.
            adapter.write_json(WorkspaceLayout(workspace).adapter, meta)
        return batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    args = parser.parse_args()
    batch = write_export(args.workspace)
    print(json.dumps({'run_status': batch['run_status'], 'stop_reason': batch['stop_reason'],
                      'output': str(args.workspace / 'calibration/batch.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
