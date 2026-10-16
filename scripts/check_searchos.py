#!/usr/bin/env python3
"""Offline compatibility check: imports, schema, registry, isolated executor."""
import asyncio
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
from searchos_project import ProjectLayout, save

async def check():
    from searchos.harness.session import SearchSession
    from searchos.skills.catalog.registry import SkillRegistry
    from searchos.skills.runtime.executor_runtime import ExecutionPolicy, run_executor
    from searchos_adapter import prepare, summary
    with tempfile.TemporaryDirectory(prefix='scout-searchos-check-') as temporary:
        path = Path(temporary) / 'smoke'
        state = prepare(path, case_ids=['TEST-0001'])
        registry = SkillRegistry()
        registered = registry.load_directory(path / 'skills')
        request = {'run_id': 'smoke', 'source': {'source_id': 'synthetic-fixture', 'run_id': 'smoke',
                   'status': 'opened', 'document_version': 'test v1', 'text': 'Two parties decide.'},
                   'evidence': [{'case_id': 'TEST-0001', 'field': 'parties_and_roles',
                   'source_id': 'synthetic-fixture', 'quote': 'Two parties', 'location': 'test v1'}]}
        result = await run_executor(path / 'skills/access/quantum_grounding', request,
                                    policy=ExecutionPolicy(timeout_s=10))
        if result.get('error') or len(result.get('validated_candidates', [])) != 1 or result.get('facts') != []:
            raise RuntimeError('Isolated executor failed: ' + json.dumps(result))
        if registered != 4 or summary(state)['ready_tasks'] != 1:
            raise RuntimeError('Registry/frontier check failed')
        return {'python': sys.version.split()[0], 'executable': sys.executable,
                'searchos_version': importlib.metadata.version('searchos'),
                'session_import': SearchSession.__name__, 'registered_domain_skills': registered,
                'isolated_executor': 'passed', 'network_access': 'none',
                'semantic_verifier': 'unavailable', 'live_search_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, help='Default: artifacts/quantum-scout/validation/offline.json')
    parser.add_argument('--stdout-only', action='store_true')
    args = parser.parse_args()
    try:
        report = asyncio.run(check())
        code = 0
    except Exception as exc:
        report, code = {'isolated_executor': 'failed', 'error_type': type(exc).__name__}, 2
    if not args.stdout_only:
        save(args.output or ProjectLayout(args.project_root).offline, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
