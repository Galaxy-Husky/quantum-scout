"""Read-only field diagnostics from recorded scopes, observations and review bindings."""
from collections import Counter
from online_policy import current_assessments, assessment_done
from review_policy import find_decision, bound, counter_quote_failures


def field_diagnostics(meta, cases):
    rows = {}
    for case in cases:
        tables = {'problem_definition': case['problem_definition']}
        for track, evaluation in case['tracks'].items():
            tables[track + '_admission'] = evaluation['criteria_evidence']
            tables[track + '_scoring'] = evaluation['score_evidence']
        for table in meta['schema']['tables']:
            refs = tables.get(table['table_id'], {})
            for field in table['attributes']:
                key = (case['case_id'], table['table_id'], field)
                rows[key] = {'case_id': key[0], 'table_id': key[1], 'field': field,
                    'has_evidence': bool(refs.get(field, {}).get('value_text')),
                    'reasons': Counter(), 'sources': {}}
    online = meta.get('online', {})
    events = online.get('events', [])
    sources = {r['source']['source_id']: r['source'] for r in online.get('sources', {}).values()
               if r.get('status') == 'opened'}
    def detail(key, sid):
        if key not in rows:
            return None
        return rows[key]['sources'].setdefault(sid or 'unknown', {
            'source_id': sid, 'context_presentations': 0, 'shared_extraction_calls': 0,
            'grounded_candidates': 0, 'attribution_records': 0, 'semantic_records': 0,
            'provided_segments': set(), 'segment_scopes': [], 'reasons': Counter(), 'observations': []})
    def note(key, sid, reason, **evidence):
        row = detail(key, sid)
        if row is not None:
            row['reasons'][reason] += 1
            row['observations'].append({'reason': reason, **evidence})
    active, segment, rejected_here = {}, [], set()
    for index, event in enumerate(events):
        kind = event['kind']
        if kind in {'round_completed', 'round_interrupted'}:
            active, segment, rejected_here = {}, [], set()
        elif kind == 'assessment_started':
            active, segment, rejected_here = event, [], set()
        elif kind == 'source_context':
            if event.get('task_id') != active.get('task_id'):
                active = {}
            segment = list(range(event['start_segment'], event['start_segment'] + event['included_segments']))
            rejected_here = set()
            for field in active.get('fields', []):
                row = detail((active.get('case_id'), active.get('table_id'), field), event['source_id'])
                if row is not None:
                    row['context_presentations'] += 1
                    row['provided_segments'].update(segment)
                    row['segment_scopes'].append({'event_index': index, 'segments': segment,
                                                  'document_version': active.get('document_version')})
        elif kind == 'model_call_started' and event.get('cost_category') == 'extraction':
            for field in active.get('fields', []):
                row = detail((active.get('case_id'), active.get('table_id'), field), active.get('source_id'))
                if row is not None:
                    row['shared_extraction_calls'] += 1
        elif kind == 'contract_rejection' or (kind == 'failure' and event.get('failure_type') in
                {'contextgem_reference_rejected', 'invalid_location', 'location_mismatch', 'quote_not_found'}):
            field = event.get('field') or (event.get('candidate') or {}).get('field')
            reason = ('candidate_rejected' if kind == 'contract_rejection' else
                      'quote_not_found' if event.get('failure_type') == 'quote_not_found' else 'location_failed')
            key = (event.get('case_id') or active.get('case_id'), event.get('table_id') or active.get('table_id'), field)
            rejected_here.add(field)
            note(key, event.get('source_id') or active.get('source_id'), reason, event_index=index,
                 segments=segment, document_version=active.get('document_version'), call_id=event.get('call_id'), report_id=event.get('report_id'), detail=event.get('reason') or event.get('validation_errors'))
        elif kind == 'failure' and event.get('failure_type') == 'invalid_model_output' and event.get('field'):
            note((event.get('case_id') or active.get('case_id'), event.get('table_id') or active.get('table_id'),
                  event['field']), event.get('source_id') or active.get('source_id'),
                 'invalid_model_output', event_index=index, call_id=event.get('call_id'),
                 detail=event.get('validation_errors'))
        elif kind == 'field_gap_observation' and event.get('field') not in rejected_here:
            # An explicit observation, never absence of a candidate in an incomplete response.
            note((event['case_id'], active.get('table_id'), event['field']), event.get('source_id'),
                 'no_candidate', event_index=index, segments=segment, document_version=active.get('document_version'), detail=event['reason'])
    for rid, entry in meta.get('grounding', {}).items():
        table = entry['request']['table_id']
        sid = entry['request']['source']['source_id']
        report = entry['report']
        for failure in report.get('grounding_failures', []):
            candidate = failure.get('candidate') or {}
            note((candidate.get('case_id'), table, candidate.get('field')), sid,
                 'grounding_failed', report_id=rid, detail=failure.get('failure_type'))
        for index, candidate in enumerate(report.get('validated_candidates', [])):
            key = (candidate['case_id'], table, candidate['field'])
            row = detail(key, sid)
            if row is None:
                continue
            row['grounded_candidates'] += 1
            a, r = (find_decision(meta, name, rid, index) for name in ('attributions', 'reviews'))
            if bound(a, candidate):
                row['attribution_records'] += 1
                if a.get('attribution') in {'absent', 'abstained'}:
                    note(key, sid, 'attribution_rejected', report_id=rid, candidate_index=index,
                         detail=a.get('attribution_reason'), verdict=a['attribution'], location=candidate['location'])
            if bound(r, candidate):
                row['semantic_records'] += 1
                failures = counter_quote_failures(entry['request']['source'].get('segments', []),
                                                  r.get('counter_evidence_search') or {})
                if failures:
                    note(key, sid, 'counter_evidence_quote_not_found', report_id=rid,
                         candidate_index=index, detail=failures)
                if r.get('verdict') != 'supported' or not r.get('location_checked') or r.get('domain_rule_met') != 'met':
                    note(key, sid, 'semantic_rejected', report_id=rid, candidate_index=index,
                         detail=r.get('reason'), verdict=r.get('verdict'), location=candidate['location'])
            # A pending review is not a rejected review.
            location_blocked = any(o.get('report_id') == rid and o['reason'] == 'location_failed' for o in row['observations'])
            if not location_blocked and (not bound(a, candidate) or (a.get('attribution') == 'attributed' and not bound(r, candidate))):
                note(key, sid, 'review_pending', report_id=rid, candidate_index=index)
    current = current_assessments(online)
    assessment_events = {e['assessment_id']: e for e in events if e['kind'] == 'assessment_started'}
    for key, row in rows.items():
        for sid, source in row['sources'].items():
            aid = current.get((key[0], key[1], sid))
            scope = assessment_events.get(aid, {})
            done = key[2] in scope.get('fields', []) and assessment_done(online, aid)
            source['processing_status'] = 'done' if done else 'pending_or_unknown'
            source['total_segments'] = len(sources[sid].get('segments', [])) if sid in sources else None
            source['provided_segments'] = sorted(source['provided_segments'])
            source['diagnostic_status'] = 'observed' if source['reasons'] else 'diagnosis_unavailable'
            row['reasons'].update(source['reasons'])
            source['reasons'] = dict(source['reasons'])
        # Absence of observations is a status, never an invented failure count.
        row['attempt_status'] = 'attempted' if row['sources'] else 'not_attempted'
        row['diagnostic_status'] = 'observed' if row['reasons'] else 'diagnosis_unavailable'
        row['reasons'] = dict(row['reasons'])
        row['sources'] = list(row['sources'].values())
    return list(rows.values())
