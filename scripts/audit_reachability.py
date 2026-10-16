#!/usr/bin/env python3
"""Observe recent workspace branches; unobserved branches need investigation, never automatic deletion."""
import argparse
from collections import Counter
import json
from pathlib import Path

from validate_batch import SUCCESS_STOPS, INCOMPLETE_STOPS, WARNING_CATEGORIES


def audit(paths, window=10):
    if window < 1:
        raise ValueError('window must be positive')
    snapshots, skipped = [], []
    for path in sorted({Path(p).resolve() for p in paths}):
        batch_path = path / 'calibration/batch.json'
        if not batch_path.exists():
            skipped.append({'workspace': str(path), 'reason': 'no batch snapshot'})
            continue
        try:
            data = json.loads(batch_path.read_text())
            if not isinstance(data, dict):
                raise ValueError('batch snapshot must be an object')
            events = data.get('events', [])
            if not isinstance(events, list) or any(not isinstance(e, dict) or
                    not isinstance(e.get('timestamp', ''), str) for e in events):
                raise ValueError('invalid snapshot events')
            quality = data.get('quality', {})
            if not isinstance(quality, dict):
                raise ValueError('invalid snapshot quality')
            warnings = quality.get('warnings', [])
            rows = quality.get('field_diagnostics', [])
            if (not isinstance(data.get('stop_reason'), (str, type(None))) or
                    not isinstance(warnings, list) or any(not isinstance(w, dict) or
                        not isinstance(w.get('category'), str) for w in warnings) or
                    not isinstance(rows, list) or any(not isinstance(row, dict) or
                        not isinstance(row.get('reasons', {}), dict) or any(
                            type(count) is not int or count < 0
                            for count in row.get('reasons', {}).values()) for row in rows)):
                raise ValueError('invalid snapshot branch observations')
        except (OSError, ValueError) as exc:
            skipped.append({'workspace': str(path), 'reason': 'unreadable snapshot',
                            'error_type': type(exc).__name__})
            continue
        # One latest snapshot per workspace; never count repeated invocations as
        # independent warning/diagnostic observations of the same current view.
        timestamp = max((e.get('timestamp', '') for e in events), default='')
        snapshots.append((timestamp, str(path), data))
    selected = sorted(snapshots, reverse=True)[:window]
    stops, warnings, diagnostics = Counter(), Counter(), Counter()
    for _, _, data in selected:
        if data.get('stop_reason'):
            stops[data['stop_reason']] += 1
        warnings.update({w['category'] for w in data.get('quality', {}).get('warnings', [])})
        diagnostics.update({name for row in data.get('quality', {}).get('field_diagnostics', [])
                            for name, count in row.get('reasons', {}).items() if count})
    reasons = {'no_candidate', 'candidate_rejected', 'quote_not_found', 'location_failed',
               'grounding_failed', 'attribution_rejected', 'semantic_rejected', 'review_pending'}
    def inventory(names, counts):
        return [{'branch': name, 'observations': counts[name],
                 'status': 'observed' if counts[name] else
                    'investigate_reachability' if len(selected) >= window else 'insufficient_window'}
                for name in sorted(names)]
    return {'window': window, 'snapshots': len(selected),
            'scope': 'latest snapshot per distinct workspace; applicability and logical reachability unknown',
            'automatic_deletion': False, 'workspaces': [p for _, p, _ in selected], 'skipped': skipped,
            'stop_values': inventory(SUCCESS_STOPS | INCOMPLETE_STOPS, stops),
            'warning_categories': inventory(WARNING_CATEGORIES, warnings),
            'diagnostic_reasons': inventory(reasons | diagnostics.keys(), diagnostics)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspaces', nargs='+', type=Path)
    parser.add_argument('--window', type=int, default=10)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.workspaces, args.window)
    from searchos_project import save
    save(args.output, result)


if __name__ == '__main__':
    main()
