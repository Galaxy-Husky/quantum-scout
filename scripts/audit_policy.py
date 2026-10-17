"""Deterministic audit and accounting; no additional model calls or framework."""
import math

# Read-only import compatibility for existing consumers.
from cost_policy import cost_category, model_costs


def audit_thresholds(meta, eligible, checked):
    policy = {'min_audit_coverage': .10, 'min_audit_samples': 3, 'warn_if_coverage_below': .05,
              **meta.get('config', {}).get('scope', {}).get('audit', {})}
    minimum, severe = policy['min_audit_coverage'], policy['warn_if_coverage_below']
    samples = policy['min_audit_samples']
    if (type(minimum) not in (int, float) or type(severe) not in (int, float)
            or not 0 <= severe <= minimum <= 1 or type(samples) is not int or samples < 0):
        raise ValueError('Invalid audit coverage policy')
    required = min(eligible, max(samples, math.ceil(eligible * minimum)))
    coverage = checked / eligible if eligible else None
    warning = None
    if eligible and checked < required:
        warning = '审计覆盖率或样本数低于要求；精确率仅描述抽查样本，不能据此推断总体可靠性。'
    return {**policy, 'required_audit_samples': required, 'audit_warning': warning,
            'audit_warning_level': ('critical' if coverage < severe else 'warning') if warning else None}


def self_audit(meta, case_id, track_id):
    """Recompute all required cells from bound raw reviews; no snapshot input."""
    from coverage_policy import coverage_witness, reviewed_cases
    import searchos_adapter as adapter
    import hashlib
    base = {'case_id': case_id, 'track_id': track_id, 'audit_kind': 'deterministic_consistency'}
    def fail(reason, category, missing_fields=None):
        return {**base, 'audit_passed': False, 'reason': reason, 'rejection_category': category,
                'missing_fields': missing_fields or []}
    if case_id not in meta['case_ids'] or track_id not in meta['config']['tracks']:
        return fail('Unknown case or track', 'unknown_target')
    config = {**meta['config'], 'tracks': {track_id: meta['config']['tracks'][track_id]}}
    sources = {r['source']['source_id'] for r in meta['online']['sources'].values() if r['status'] == 'opened'}
    cases = [c for c in reviewed_cases(meta, adapter.project(meta)) if c['case_id'] == case_id]
    actual = coverage_witness(cases, config, sources)
    if not actual or not actual.get('decision_chains'):
        from coverage_policy import missing_coverage_fields
        missing = missing_coverage_fields(cases[0], config, sources, track_id) if cases else list(config['fields'])
        return fail('Required definitions, admission or scoring cells lack dual-reviewed supported evidence',
                    'missing_coverage', missing)
    recomputed = {}
    for chain in actual['decision_chains'].values():
        try:
            entry = meta['grounding'][chain['report_id']]
            source = entry['request']['source']
            body_hash = hashlib.sha256(source['text'].encode()).hexdigest()
            candidate = entry['report']['validated_candidates'][chain['candidate_index']]
            from validate_grounding import grounding_gate
            rid = chain['report_id']
            if rid not in recomputed:
                recomputed[rid] = grounding_gate().validate(entry['request'])['validated_candidates']
            if (chain['candidate_index'] >= len(recomputed[rid])
                    or recomputed[rid][chain['candidate_index']] != candidate):
                return fail('Stored grounding differs from recomputed quote/span/location receipt', 'invalid_grounding')
            if body_hash != chain['source_sha256'] or candidate['source_id'] != chain['source_id']:
                return fail('Source digest or identity mismatch', 'hash_mismatch')
            current = [r['source'] for r in meta['online']['sources'].values()
                       if r.get('status') == 'opened' and r['source']['source_id'] == candidate['source_id']]
            if not current or any(hashlib.sha256(s['text'].encode()).hexdigest() != body_hash for s in current):
                return fail('Opened body differs from reviewed body', 'body_changed')
        except (KeyError, IndexError, TypeError):
            return fail('Incomplete source/review binding', 'invalid_binding')
    return {**base, 'audit_passed': True, 'reason': 'Recomputed from bound reviews and matching source bodies',
            'fields_checked': len(actual['decision_chains']), 'decision_chains': actual['decision_chains']}


def _audit_walk(chains, checks, *, strip_reason=True):
    """Count each eligible candidate once, using the caller's eligibility view.

    Workspace metrics retain their historical truthy-reason policy; case labels
    require nonblank reasons. Neither view can count an agent as a human.
    """
    from review_policy import bound, find_decision, nonempty
    checked = correct = 0
    for (rid, index), candidate in chains.items():
        check = find_decision({'checks': checks}, 'checks', rid, index)
        if (bound(check, candidate) and check.get('reviewer_kind') == 'human'
                and type(check.get('attribution_correct')) is bool
                and (nonempty(check.get('reason')) if strip_reason else bool(check.get('reason')))):
            checked += 1
            correct += int(check['attribution_correct'])
    return len(chains), checked, correct


def case_audit_metrics(witness, checks, config):
    """Count unique, currently witnessed candidates, never other tracks or old claims."""
    from review_policy import nonempty
    chains = {(c['report_id'], c['candidate_index']): c
              for c in witness['decision_chains'].values()}
    candidates = {key: {**chain, 'case_id': witness['case_id'],
                         'grounding': {'source_sha256': chain['source_sha256']}}
                  for key, chain in chains.items()}
    eligible, checked, correct = _audit_walk(candidates, checks)
    thresholds = audit_thresholds({'config': config}, eligible, checked)
    off_chain_rejected = any(c.get('case_id') == witness['case_id']
        and c.get('reviewer_kind') == 'human' and nonempty(c.get('reason'))
        and c.get('attribution_correct') is False
        and (c.get('report_id'), c.get('candidate_index')) not in chains for c in checks)
    status = ('rejected' if off_chain_rejected or correct < checked else
              'not_applicable' if not eligible else 'unverified' if not checked else
              'partial' if checked < thresholds['required_audit_samples'] else 'verified')
    return {**thresholds, 'case_id': witness['case_id'], 'track_id': witness['track_id'],
            'status': status, 'off_chain_rejected': off_chain_rejected,
            'eligible_supported': eligible, 'audited_samples': checked,
            'audited_correct': correct, 'audited_incorrect': checked - correct,
            'audit_coverage': checked / eligible if eligible else None,
            'audit_passed': status in {'verified', 'not_applicable'}}


def current_case_audit(case, config, sources, checks):
    """Derived current label; never use a historical stop snapshot as authority."""
    from coverage_policy import coverage_witness, verified, case_evidence
    witness = coverage_witness([case], config, sources)
    if witness is None:
        witness = {'case_id': case['case_id'], 'track_id': None, 'decision_chains': {
            str(i): {**v['semantic_review'], 'source_id': v['source_id']}
            for i, v in enumerate(case_evidence(case)) if verified(v, sources)}}
    result = case_audit_metrics(witness, checks, config)
    # An unfinished case with no supported candidates is unverified, not exempt.
    if result['status'] == 'not_applicable':
        result.update(status='unverified', audit_passed=False)
    return result

