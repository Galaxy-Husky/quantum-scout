"""Case-relative source contribution and role classification."""

def _evidence_refs(value):
    """Extract source IDs from a structured evidence object."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, dict):
        return []
    refs = [value["source_id"]] if value.get("source_id") else []
    for key in ("evidence_refs", "evidence", "references"):
        items = value.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("source_id"):
                    refs.append(item["source_id"])
                elif isinstance(item, str):
                    refs.append(item)
    return refs


def _admission_items(evaluation):
    """Use the current keyed contract, or one legacy representation, once."""
    if isinstance(evaluation.get('criteria_evidence'), dict):
        return list(evaluation['criteria_evidence'].values())
    for key in ('admission_evidence', 'evidence_refs', 'admission_refs'):
        if isinstance(evaluation.get(key), list) and evaluation[key]:
            return evaluation[key]
    return []


def classify_source_role(case, source_id):
    """Classify a source from field/admission evidence density."""
    field_count = sum(
        source_id in _evidence_refs(field)
        for field in (case.get("problem_definition", {}) or {}).values()
    )
    has_two_admissions = any(
        sum(source_id in _evidence_refs(item) for item in _admission_items(evaluation)) >= 2
        for evaluation in (case.get('tracks', {}) or {}).values()
    )
    return 'primary' if field_count >= 4 or has_two_admissions else 'supporting'


def case_references_source(case, source_id):
    """Whether field/admission evidence points at source_id."""
    if any(source_id in _evidence_refs(field)
           for field in (case.get("problem_definition", {}) or {}).values()):
        return True
    return any(
        source_id in _evidence_refs(item)
        for evaluation in (case.get("tracks", {}) or {}).values()
        for item in _admission_items(evaluation) + list((evaluation.get('score_evidence') or {}).values())
    )

