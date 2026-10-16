"""A local, DeepDive-inspired claim ledger; no DeepDive pipeline is executed."""
import hashlib


def build_claim_ledger(candidate, source, segments, existing_nodes):
    receipt = candidate['grounding']
    text = source['text']
    if hashlib.sha256(text.encode()).hexdigest() != receipt['source_sha256']:
        raise ValueError('Claim source version changed after grounding')
    start, end = receipt['span']
    if text[start:end] != receipt['matched_text']:
        raise ValueError('Claim span does not match grounding receipt')
    # Opposing *reviewed* values are candidates for counter-evidence, not a
    # semantic assertion of contradiction. The judge must inspect them.
    counter = [dict(evidence_id=n.id, claim=n.value, source=n.source,
                    span_excerpt=n.source_excerpt, span=n.span, source_sha256=n.text_hash)
               for n in existing_nodes
               if n.entity == candidate['case_id'] and n.attribute == candidate['field']
               and n.value != candidate['value_text']]
    return {'claim': candidate['value_text'], 'case_id': candidate['case_id'],
            'field': candidate['field'], 'source_id': source['source_id'],
            'source_sha256': receipt['source_sha256'], 'span': [start, end],
            'span_excerpt': text[start:end], 'location': candidate['location'],
            'counter_evidence': counter,
            'counter_evidence_status': 'requires_judge_check',
            'search_scope': 'supplied body segments and previously reviewed same-cell evidence',
            'context_segments': segments,
            'extractor_justification': candidate.get('justification', '')}
