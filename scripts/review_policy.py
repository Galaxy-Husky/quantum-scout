"""Shared fail-closed attribution and semantic review rules (no model calls)."""
from schema_generator import digest


def find_decision(meta, collection, report_id, index):
    return next((d for d in meta.get(collection, [])
                 if d.get('report_id') == report_id and type(d.get('candidate_index')) is int
                 and d['candidate_index'] == index), None)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def bound(decision, candidate):
    return (isinstance(decision, dict)
            and bool(decision.get('report_id')) and type(decision.get('candidate_index')) is int
            and decision.get('reviewer_kind') in {'agent', 'human'} and nonempty(decision.get('reviewer_id'))
            and bool(candidate.get('case_id')) and decision.get('case_id') == candidate['case_id']
            and decision.get('location') == candidate.get('location')
            and decision.get('source_sha256') == candidate.get('grounding', {}).get('source_sha256')
            and bool(decision.get('source_sha256'))
            and digest(decision.get('value_text')) == digest(candidate.get('value_text')))


def attributed(decision, candidate):
    return (bound(decision, candidate) and decision.get('attribution') == 'attributed'
            and nonempty(decision.get('attribution_reason')))


def counter_search_valid(review, candidate):
    if not isinstance(review, dict):
        return False
    search = review.get('counter_evidence_search')
    if not isinstance(search, dict):
        return False
    locations = search.get('segments_searched')
    contradictions = search.get('contradictions_found')
    flags = ('negation', 'conditional_limits', 'threat_model_boundary')
    if not (nonempty(search.get('summary')) and len(search['summary']) <= 2000
            and isinstance(locations, list) and bool(locations)
            and all(nonempty(x) for x in locations) and candidate.get('location') in locations
            and all(type(search.get(k + '_found')) is bool for k in flags)
            and isinstance(contradictions, list)):
        return False
    def finding_valid(finding):
        return (isinstance(finding, dict) and finding.get('location') in locations
                and nonempty(finding.get('quote')) and len(finding['quote']) <= 50)
    for key in flags:
        findings = search.get(key + '_evidence', [])
        if (not isinstance(findings, list) or bool(findings) != search[key + '_found']
                or not all(finding_valid(f) for f in findings)):
            return False
    return all(finding_valid(f) for f in contradictions)


def source_reviewable(source, review):
    # A provider lookup is metadata, never proof that the body supports a claim.
    if source.get('citation_identity', {}).get('state') == 'mismatch':
        return False
    locations = {s['location'] for s in source.get('segments', [])}
    if not locations:
        locations = {source.get('document_version')}
    search = review.get('counter_evidence_search') or {}
    if not isinstance(search, dict) or not set(search.get('segments_searched', [])) <= locations:
        return False
    from validate_grounding import grounding_gate
    segments = {s['location']: s['text'] for s in source.get('segments', [])}
    if not segments:
        segments = {source.get('document_version'): source.get('text', '')}
    findings = search.get('contradictions_found', [])
    findings = findings + [f for key in ('negation', 'conditional_limits', 'threat_model_boundary')
                           for f in search.get(key + '_evidence', [])]
    return all(isinstance(f, dict) and f.get('location') in segments
               and nonempty(f.get('quote')) and len(f['quote']) <= 50
               and grounding_gate().locate(segments[f['location']], f['quote']) is not None
               for f in findings)


def counter_quote_failures(segments, search):
    """Return deterministic location/string failures, never semantic judgments."""
    if not isinstance(search, dict):
        return []  # Legacy malformed structure is rejected by the structural policy.
    from validate_grounding import grounding_gate
    indexed = {s['location']: s['text'] for s in segments}
    failures = []
    for name in ('negation_evidence', 'conditional_limits_evidence',
                 'threat_model_boundary_evidence', 'contradictions_found'):
        findings = search.get(name, [])
        if not isinstance(findings, list):
            continue
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            location, quote = finding.get('location'), finding.get('quote')
            if location not in indexed or not nonempty(quote) or grounding_gate().locate(indexed[location], quote) is None:
                failures.append({'path': [name, index, 'quote'], 'location': location,
                                 'quote': quote, 'reason': 'counter_evidence_quote_not_found'})
    return failures


def citation_allowed(meta, source_id):
    return not any(r.get('source', {}).get('source_id') == source_id
                   and r.get('source', {}).get('citation_identity', {}).get('state') == 'mismatch'
                   for r in meta.get('online', {}).get('sources', {}).values())


def supported_pair(attribution, review, candidate):
    return (attributed(attribution, candidate) and bound(review, candidate)
            and attribution['report_id'] == review['report_id']
            and attribution['candidate_index'] == review['candidate_index']
            and attribution['reviewer_id'] != review['reviewer_id']
            and review.get('verdict') == 'supported' and review.get('location_checked') is True
            and review.get('domain_rule_met') == 'met'
            and nonempty(review.get('domain_rule_reason'))
            and counter_search_valid(review, candidate))


def source_depth(meta, source):
    record = next((record for record in meta.get('online', {}).get('sources', {}).values()
                   if record.get('source', {}).get('source_id') == source['source_id']), None)
    if source.get('citation_identity', {}).get('state') == 'mismatch':
        return 'unverified'
    return record.get('citation_depth') if record else None
