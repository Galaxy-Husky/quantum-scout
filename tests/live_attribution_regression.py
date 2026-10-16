#!/usr/bin/env python3
"""Paid, opt-in regression: replay one historical candidate through live judges.

Only extraction is replaced by an audited historical input. Search, opening,
grounding, both judges, budget enforcement and export use the production runner.
This is not an end-to-end extraction-quality test and never supplies a verdict.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import searchos_adapter as adapter
from searchos_project import WorkspaceLayout
from searchos_online import Candidate, OnlineRunner, configure, read_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-workspace', type=Path, required=True)
    parser.add_argument('--report-id', required=True)
    parser.add_argument('--candidate-index', type=int, default=0)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--settings-file', type=Path)
    args = parser.parse_args()
    historical = adapter.load(args.historical_workspace)
    report = historical['grounding'][args.report_id]['report']
    candidate = report['validated_candidates'][args.candidate_index]
    seed = Candidate.model_validate({k: v for k, v in candidate.items() if k in Candidate.model_fields})
    configure(args.env_file, args.settings_file)
    config = read_config(args.config)
    if candidate['case_id'] not in config['cases']:
        parser.error('Configuration must explicitly describe the historical target case')
    identity = {'historical_workspace': str(args.historical_workspace.resolve()),
                'report_id': args.report_id, 'candidate_index': args.candidate_index,
                'candidate': seed.model_dump(), 'source_sha256': candidate['grounding']['source_sha256']}
    manifest = WorkspaceLayout(args.workspace).replay
    if args.workspace.exists():
        if not manifest.exists() or json.loads(manifest.read_text()) != identity:
            parser.error('Resume requires the identical regression input and an isolated replay workspace')
    else:
        adapter.prepare(args.workspace, case_ids=list(config['cases']))
        adapter.write_json(manifest, identity)

    async def replay(runner, context, segments):
        if context['case_id'] != candidate['case_id']:
            raise ValueError('Historical candidate belongs to another case')
        # A matching source digest and segment prevent replay against another paper.
        meta = adapter.load(runner.path)
        matches = [r['source'] for r in meta['online']['sources'].values()
                   if r.get('status') == 'opened']
        import hashlib
        if not any(hashlib.sha256(s['text'].encode()).hexdigest() == candidate['grounding']['source_sha256']
                   for s in matches):
            raise ValueError('Live source does not match the historical source digest')
        if not any(s['location'] == seed.location for s in segments):
            raise ValueError('Historical candidate location is outside this live context')
        runner.event('historical_candidate_replay', historical_workspace=str(args.historical_workspace.resolve()),
                     report_id=args.report_id, candidate_index=args.candidate_index,
                     source_sha256=candidate['grounding']['source_sha256'],
                     scope='candidate-input regression; extraction intentionally not tested')
        return {'candidates': [seed.model_dump()], 'missing': {}}

    result = asyncio.run(OnlineRunner(args.workspace, config, extractor=replay).run())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['stop_reason'] in {'error', 'user_aborted'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
