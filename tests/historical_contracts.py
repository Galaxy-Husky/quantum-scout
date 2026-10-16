#!/usr/bin/env python3
"""Read-only batch compatibility and observed field-label inventory; no migration or models."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_calibration import render


def audit_history(paths, *, legacy_audit=False):
    rows = []
    for root in sorted({Path(p).resolve() for p in paths}):
        snapshot = root / 'calibration/batch.json'
        row = {'workspace': str(root)}
        rows.append(row)
        if not snapshot.is_file():
            row.update(status='unverified', reason='No batch snapshot')
            continue
        original = snapshot.read_bytes()
        row['batch_sha256'] = hashlib.sha256(original).hexdigest()
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in [snapshot, root / 'state/quantum_adapter.json', *root.glob('checkpoints/*.json')] if p.is_file()}
        try:
            data = json.loads(original)
            render(data, legacy_audit=legacy_audit)
            confidence = Counter()
            for case in data['cases']:
                refs = list(case.get('problem_definition', {}).values())
                for evaluation in case.get('tracks', {}).values():
                    refs += list(evaluation.get('criteria_evidence', {}).values())
                    refs += list(evaluation.get('score_evidence', {}).values())
                for ref in refs:
                    if ref.get('value_text') is not None and ref.get('source_id') and ref.get('quote'):
                        confidence[ref.get('confidence') or 'unprovided'] += 1
            row.update(status='passed', stop_reason=data['stop_reason'], counts=data['counts'],
                       confidence_by_field_reference=dict(confidence))
        except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
            row.update(status='incompatible', error_type=type(exc).__name__, reason=str(exc))
        row['inputs_unchanged'] = all(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == sha
                                     for p, sha in before.items())
        if not row['inputs_unchanged']:
            raise RuntimeError('Read-only audit changed an input')
    return {'scope': 'Current renderer against immutable historical batch snapshots; no resume or semantic verification',
            'confidence_scope': 'Observed current field references with value/source/quote; not unique candidates or quality',
            'legacy_audit': legacy_audit, 'workspaces': rows,
            'counts': dict(Counter(row['status'] for row in rows))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspaces', nargs='+', type=Path)
    parser.add_argument('--legacy-audit', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if any(args.output.resolve().is_relative_to(p.resolve()) for p in args.workspaces):
        parser.error('Audit output must be outside every input workspace')
    report = audit_history(args.workspaces, legacy_audit=args.legacy_audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return 2 if any(row['status'] != 'passed' for row in report['workspaces']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
