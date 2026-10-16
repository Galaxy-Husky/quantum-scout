"""Explicit synthetic dual-reviewed evidence; never research facts."""
def reviewed_ref(value='true', case_id='TEST-0001', source_id='s1'):
    binding = dict(report_id='fixture:' + case_id + ':' + value, candidate_index=0,
                   case_id=case_id, location='page:1', value_text=value, source_sha256='abc', reviewer_kind='agent')
    return dict(value_text=value, quote='Evidence', location='page:1', source_id=source_id,
                case_id=case_id, grounding={'source_sha256': 'abc'}, evidence_level='primary', confidence='medium',
                attribution_review={**binding, 'reviewer_id': 'attribution-fixture', 'attribution': 'attributed',
                                    'attribution_reason': 'Synthetic explicit case link'},
                semantic_review={**binding, 'reviewer_id': 'semantic-fixture', 'verdict': 'supported',
                                 'location_checked': True, 'domain_rule_met': 'met', 'domain_rule_reason': 'Synthetic rule check',
                                 'counter_evidence_search': {'summary': 'Synthetic search for not and only',
                    'segments_searched': ['page:1'], 'negation_found': False,
                    'conditional_limits_found': False, 'threat_model_boundary_found': False, 'contradictions_found': []}})


def add_witness_audits(data, config):
    """Synthetic human fixtures, used only to exercise batch admission guards."""
    from audit_policy import case_audit_metrics
    witness = data['checkpoint']['stop_evidence']['coverage_witness']
    checks = [{**chain, 'case_id': witness['case_id'], 'reviewer_kind': 'human',
               'reviewer_id': 'synthetic-human', 'attribution_correct': True,
               'reason': 'Offline fixture; not an actual human audit'}
              for chain in witness['decision_chains'].values()]
    data['review_audit'] = {'attribution_checks': checks}
    data['checkpoint']['stop_evidence']['case_audit'] = case_audit_metrics(witness, checks, config)
    data['checkpoint']['stop_evidence']['self_audit'] = {**witness, 'audit_passed': True}
