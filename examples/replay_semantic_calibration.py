"""Verify saved calibration bindings, NOT semantic labels. No network or mutations.

Usage: python skill/examples/replay_semantic_calibration.py /path/to/qscout
The semantic annotations are agent comparisons for review, not runtime verdicts.
"""
import hashlib
import json
from pathlib import Path
import sys


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def replay(project_root):
    fixture = json.loads(Path(__file__).with_name('semantic-calibration.json').read_text())
    states = {}
    for sample in fixture['samples']:
        path = sample['native_state']
        if path not in states:
            states[path] = json.loads((project_root / path).read_text())
        events = states[path]['online']['events']
        req, = [e for e in events if e['kind'] == 'model_call_started'
                and e['call_id'] == sample['call_id']]
        res, = [e for e in events if e['kind'] == 'model_response'
                and e['call_id'] == sample['call_id']]
        data = req['input']
        assert sha(json.dumps(data, ensure_ascii=False, sort_keys=True)) == req['input_sha256'] == sample['input_sha256']
        assert sha(res['content']) == sample['response_sha256']
        assert data['candidate']['field'] == sample['field']
        assert data['candidate']['value_text'] == sample['candidate_value']
        assert data['source_quote_options'][sample['location']][sample['source_quote_id']] == sample['quote']
        segment, = [s for s in data['context_segments'] if s['location'] == sample['location']]
        assert sample['quote'] in segment['text']  # Identity only; never semantic support.
        search = json.loads(res['content'])['judgments'][0]['counter_evidence_search']
        assert search['summary'] == sample['summary']
        group = sample['observed_group']
        if group:
            found = [f for f in search[group] if f['source_quote_id'] == sample['source_quote_id']]
            assert found == sample['observed_findings'] and found
        else:
            assert all(not search[g] for g in ('negation_evidence', 'conditional_limits_evidence',
                       'threat_model_boundary_evidence', 'contradictions_found'))
    return {'verified_bindings': len(fixture['samples']), 'semantic_labels': 'not machine-validated',
            'paid_calls': 0}


if __name__ == '__main__':
    print(json.dumps(replay(Path(sys.argv[1]).resolve()), indent=2))
