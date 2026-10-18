"""Case-local coverage rules shared by the online stop guard and batch renderer."""


from schema_generator import digest
from aggregation import candidate_id, context as aggregation_context, resolve as resolve_aggregation
from review_policy import supported_pair, find_decision, review_accepted


def case_evidence(case):
    """Iterate definitions, admission evidence and scores without filtering them."""
    yield from case['problem_definition'].values()
    for track in case['tracks'].values():
        yield from track['criteria_evidence'].values()
        yield from track['score_evidence'].values()


def verified(item, sources):
    if not isinstance(item, dict):
        return False
    review = item.get('semantic_review', {})
    return (item.get('source_id') in sources
            and all(item.get(k) for k in ('quote', 'location', 'value_text'))
            and item.get('evidence_level') in {'primary', 'secondary'}
            and item.get('confidence') in {'low', 'medium', 'high'}
            and supported_pair(item.get('attribution_review'), review, item)
            and not item.get('has_conflict', False))


def coverage_witness(cases, config, sources):
    """Never combine definitions, admissions, or scores from different cases/tracks."""
    for case in cases:
        definitions = case.get('problem_definition', {})
        for track, rules in config['tracks'].items():
            # The diagnostic and stop witness consume the same coverage policy.
            if missing_coverage_fields(case, config, sources, track):
                continue
            evaluation = case['tracks'][track]
            criteria = evaluation['criteria']
            evidence = evaluation['criteria_evidence']
            passed = all(criteria[c] for c in rules['admission_criteria'])
            if evaluation.get('passed_admission') != int(passed):
                continue
            valid = valid_score_dimensions(case, config, sources, track) if passed else []
            items = {f'problem_definition/{f}': definitions[f] for f in config['fields']}
            items.update({f'{track}_admission/{c}': evidence[c] for c in rules['admission_criteria']})
            items.update({f'{track}_scoring/{d}': evaluation['score_evidence'][d] for d in valid})
            chains = {}
            for key, item in items.items():
                a, r = item['attribution_review'], item['semantic_review']
                chains[key] = {'report_id': r['report_id'], 'candidate_index': r['candidate_index'],
                    'source_sha256': r['source_sha256'], 'source_id': item['source_id'],
                    'location': item['location'], 'value_text': item['value_text'],
                    'attribution': a['attribution'], 'attribution_reason': a['attribution_reason'],
                    'semantic_verdict': r['verdict'], 'domain_rule_met': r['domain_rule_met'],
                    'counter_evidence_search': r['counter_evidence_search'],
                    'reviewer_ids': [a['reviewer_id'], r['reviewer_id']]}
                if item.get('aggregation_decision'):
                    chains[key]['aggregation_decision'] = item['aggregation_decision']
            return {'case_id': case['case_id'], 'track_id': track,
                    'passed_admission': passed, 'valid_dimensions': valid, 'decision_chains': chains}
    return None


def validate_case_coverage_stop(data, config=None):
    if config is None:
        from schema_generator import domain_config, digest
        config = data.get('config_snapshot')
        if config is not None and digest(config) != data.get('config_sha256'):
            raise ValueError('Batch configuration snapshot digest mismatch')
        if config is None:
            config = domain_config()
    if (data.get('run_status') != 'completed'
            or data.get('checkpoint', {}).get('completed') is not True):
        raise ValueError('case_coverage_complete requires completed / completed=true')
    sources = {s['source_id'] for s in data['sources'] if s['status'] == 'opened'
               and (s.get('citation_identity') or {}).get('state') != 'mismatch'}
    evidence = data['checkpoint'].get('stop_evidence', {})
    ids = [c['case_id'] for c in data['cases']]
    scope = data.get('configured_case_ids', ids)
    recorded_scope = evidence.get('configured_case_ids', ids)
    if (not scope or len(set(scope)) != len(scope) or len(set(ids)) != len(ids)
            or set(scope) != set(ids) or recorded_scope != scope):
        raise ValueError('Coverage stop requires the complete configured case scope')
    recorded = evidence.get('case_completions')
    if recorded is None and len(scope) == 1:
        recorded = [evidence]
    if not isinstance(recorded, list) or len(recorded) != len(scope):
        raise ValueError('Coverage stop requires one completion per configured case')
    from audit_policy import case_audit_metrics
    checks = data.get('review_audit', {}).get('attribution_checks', [])
    count = evidence.get('attribution_check_count', len(checks))
    if type(count) is not int or not 0 <= count <= len(checks):
        raise ValueError('Invalid stop audit snapshot boundary')
    witnesses = []
    for cid, completion in zip(scope, recorded):
        witness = coverage_witness([c for c in data['cases'] if c['case_id'] == cid], config, sources)
        if not witness:
            raise ValueError('Every configured case needs a single case and track reviewed coverage chain')
        if completion.get('coverage_witness') != witness:
            raise ValueError('Coverage stop must record the recomputed case/track witness')
        audit = completion.get('self_audit', {})
        if (audit.get('audit_passed') is not True or audit.get('case_id') != cid
                or audit.get('track_id') != witness['track_id']
                or audit.get('decision_chains') != witness['decision_chains']):
            raise ValueError('Coverage stop requires a matching passed self audit for every case')
        metrics = case_audit_metrics(witness, checks[:count], config)
        if 'case_audit' in completion and completion['case_audit'] != metrics:
            raise ValueError('Coverage stop must record recomputed historical case audit metrics')
        if 'human_audit_status' in completion and completion['human_audit_status'] != metrics['status']:
            raise ValueError('Historical human audit status mismatch')
        witnesses.append(witness)
    if evidence.get('coverage_witness') != witnesses[0]:
        raise ValueError('Primary coverage witness must match the first configured case')
    # Check the compatibility aliases too; they must never disagree with case_completions.
    if evidence.get('case_completions'):
        for key in ('self_audit', 'case_audit', 'human_audit_status'):
            if evidence.get(key) != recorded[0].get(key):
                raise ValueError('Coverage stop alias mismatch: ' + key)
    return witnesses[0]


def reviewed_cases(meta, state):
    """Export only unconflicted, independently supported facts; preserve all gaps."""
    cells, pending = {}, {}
    for decision in meta['reviews']:
        if decision['verdict'] != 'supported':
            continue
        entry = meta['grounding'][decision['report_id']]
        candidate = entry['report']['validated_candidates'][decision['candidate_index']]
        attribution = find_decision(meta, 'attributions', decision['report_id'], decision['candidate_index'])
        if not review_accepted(meta, attribution, decision, candidate, entry['request']['source']):
            continue
        table = entry['request']['table_id']
        key = f"{table}/{candidate['case_id']}.{candidate['field']}"
        cell = state.coverage_map.cells[key]
        if cell.status.value != 'filled':
            if cell.display_hint == 'aggregation_pending':
                if candidate_id(decision['report_id'], decision['candidate_index']) in resolve_aggregation(meta, key)['excluded_candidate_ids']:
                    continue
                pending.setdefault(candidate['case_id'], []).append({**candidate,
                    'table_id': table, 'semantic_review': decision, 'attribution_review': attribution})
            continue
        evidence_id = 'qs_' + digest([decision['report_id'], decision['candidate_index']])[:24]
        if evidence_id not in cell.supporting_evidence_ids:
            continue
        cells[key] = {**candidate, 'semantic_review': decision, 'attribution_review': attribution,
                      'coverage_status': candidate.get('coverage_status', 'covered')}
        aggregation = resolve_aggregation(meta, key) if meta.get('aggregations') else {'decision': None}
        if aggregation['decision']:
            cells[key]['aggregation_decision'] = aggregation['decision']
    config = meta['config']
    cases = []
    for cid in meta['case_ids']:
        def evidence(table, field):
            return cells.get(f'{table}/{cid}.{field}')
        definitions = {}
        for f in config['fields']:
            k = f'problem_definition/{cid}.{f}'
            reason = meta.get('gaps', {}).get(k, {}).get('reason')
            explicit = isinstance(reason, str) and bool(reason.strip())
            definitions[f] = evidence('problem_definition', f) or {
                'value_text': None, 'reason': reason if explicit else None,
                'reason_source': 'explicit_gap' if explicit else 'none'}
        case = {'case_id': cid, 'scenario_description': meta.get('online', {}).get('config', {}).get(
            'cases', {}).get(cid, {}).get('description', cid), 'sub_domain': None,
            'problem_definition': definitions, 'pending_aggregation': pending.get(cid, []),
            'problem_definition_complete': all(v.get('value_text') or v.get('reason_source') == 'explicit_gap' for v in definitions.values()),
            'failure_class': 'insufficient_evidence', 'tracks': {}, 'source_ids': [], 'discovery_trail': []}
        field_ids = sorted({d['cell_id'] for d in meta.get('aggregations', [])
                            if d['cell_id'].split('/', 1)[1].split('.', 1)[0] == cid})
        if field_ids:
            case['aggregation'] = []
            for k in field_ids:
                ctx = aggregation_context(meta, k)
                result = resolve_aggregation(meta, k, ctx)
                case['aggregation'].append({**ctx, **{name: result[name] for name in
                    ('outcome', 'pending_reason', 'excluded_candidate_ids')}})
        for track, rules in config['tracks'].items():
            ce = {c: evidence(track + '_admission', c) for c in rules['admission_criteria']}
            criteria = {c: v['value_text'] == 'true' if v else 'insufficient_evidence' for c, v in ce.items()}
            passed = all(v is True for v in criteria.values())
            se = {d: evidence(track + '_scoring', d) if passed else None for d in rules['scoring_dimensions']}
            scores = {d: int(v['value_text']) if v else None for d, v in se.items()}
            valid = [v for v in scores.values() if v is not None]
            total = sum(valid) if valid else None
            normalized = total / (len(valid) * 5) * 25 if len(valid) >= config['scoring_rules']['minimum_valid_dimensions'][track] else None
            accepted = passed and normalized is not None and normalized >= rules['min_total_score']
            case['tracks'][track] = {'criteria': criteria, 'criteria_evidence': {k: v for k, v in ce.items() if v},
                'passed_admission': int(passed), 'scores': scores, 'score_evidence': {k: v for k, v in se.items() if v},
                'score_total': total, 'score_normalized': normalized, 'valid_dimension_count': len(valid),
                'failure_class': None if accepted else 'failed_admission' if any(v is False for v in criteria.values()) else 'insufficient_evidence'}
        refs = [v for k, v in cells.items() if k.split('/', 1)[1].split('.', 1)[0] == cid]
        case['source_ids'] = sorted({v['source_id'] for v in refs})
        case['single_source'] = int(len(case['source_ids']) == 1)
        if any(t['failure_class'] is None for t in case['tracks'].values()):
            case['failure_class'] = None
        from audit_policy import current_case_audit
        sources = {r['source']['source_id'] for r in meta.get('online', {}).get('sources', {}).values()
                   if r['status'] == 'opened'}
        case['case_audit'] = current_case_audit(case, config, sources, meta.get('attribution_checks', []))
        case['human_audit_status'] = case['case_audit']['status']
        cases.append(case)
    return cases


def evidence_covers(item, sources, value=None, definition=False):
    return (verified(item, sources) and (item.get('coverage_status', 'covered') == 'covered'
        or (definition and item.get('coverage_status') == 'not_applicable'
            and item.get('applicability_reason'))) and (value is None or item['value_text'] == value))


def valid_score_dimensions(case, config, sources, track):
    evaluation = case.get('tracks', {}).get(track, {})
    return [field for field in config['tracks'][track]['scoring_dimensions']
            if type(evaluation.get('scores', {}).get(field)) is int
            and evaluation['scores'][field] in (1, 3, 5)
            and evidence_covers(evaluation.get('score_evidence', {}).get(field), sources,
                                str(evaluation['scores'][field]))]


def missing_coverage_fields(case, config, sources, track):
    """Report cells lacking usable evidence, including conditional scoring gaps."""
    missing = []
    for field in config['fields']:
        if not evidence_covers(case.get('problem_definition', {}).get(field), sources, definition=True):
            missing.append('problem_definition/' + field)
    evaluation = case.get('tracks', {}).get(track, {})
    rules = config['tracks'][track]
    criteria = evaluation.get('criteria', {})
    for field in rules['admission_criteria']:
        value = criteria.get(field)
        if type(value) is not bool or not evidence_covers(evaluation.get('criteria_evidence', {}).get(field), sources, str(value).lower()):
            missing.append(track + '_admission/' + field)
    if all(criteria.get(f) is True for f in rules['admission_criteria']):
        valid = valid_score_dimensions(case, config, sources, track)
        if len(valid) < config['scoring_rules']['minimum_valid_dimensions'][track]:
            missing += [track + '_scoring/' + f for f in rules['scoring_dimensions'] if f not in valid]
    return missing
